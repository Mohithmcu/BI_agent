"""
Gemini-powered BI agent with function-calling for Skylark Drones.

Uses the new `google-genai` SDK (replaces deprecated `google-generativeai`).

Architecture:
  1. User query comes in as natural language.
  2. Gemini decides which metric tool(s) to call (and with what filters).
  3. Tool results (always JSON) are fed back to Gemini.
  4. Gemini composes a clear, caveated, insight-rich answer.
"""

import json
import math
import os
from datetime import date, datetime

import time
import httpx
import pandas as pd
from google import genai
from google.genai import types
from google.genai.errors import APIError

from metrics import (
    revenue_summary,
    pipeline_health,
    sector_breakdown,
    operational_metrics,
    top_customers,
    billing_health,
    deal_stage_funnel,
    leadership_update,
    data_quality_summary,
    invalidate_cache,
)

# ────────────────────────────────────────────────────────────────────
# Config
# ────────────────────────────────────────────────────────────────────

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
MAX_TOOL_LOOPS = 6  # safety valve against infinite loops

# ────────────────────────────────────────────────────────────────────
# System prompt
# ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a senior Business Intelligence analyst for Skylark Drones, \
a drone services company operating across sectors like Energy, Mining, Infrastructure, \
Oil & Gas, Construction, and Government.

You have access to two live Monday.com data sources:
1. **Work Orders Board** — project execution data: customers, sectors, financials \
(order value, billed, collected, receivable), execution status, dates, billing info.
2. **Deals Board** — sales pipeline data: deal stages, values, closure probabilities, \
sectors, products, owners, timelines.

YOUR JOB:
• Answer founder-level business questions clearly and insightfully.
• ALWAYS call the relevant tools FIRST to get real-time data — never guess numbers.
• Surface data-quality caveats naturally (e.g., "Note: 18% of deals are missing values").
• Provide context and insights, not just raw numbers — trends, comparisons, risks.
• Format currency in Indian Rupees (₹). Use lakhs (₹1L = ₹1,00,000) and \
crores (₹1Cr = ₹1,00,00,000) for large amounts.
• If a question is ambiguous, ask ONE brief clarifying question.
• After answering, suggest 1-2 follow-up questions the founder might want to explore.

• Never sum individual deal stages manually. The pipeline tools return pre-computed `high_level_summary` (Active, Won, Lost) and `sub_bucket_summary` (Early-Stage, Mid-Stage, Late-Stage) groupings. Use these pre-calculated values directly.
• For stages or groups where all values are missing, do not report ₹0; instead, clearly state that values are unknown or not recorded, as flagged by the caveats.
• Always use the pre-computed `formatted_value` fields (e.g. `"₹10.93 Cr"`) from tool responses when rendering tables or bullet lists. Do not convert raw numeric values (like `109255888.7`) to Lakhs/Crores in your head.
• Always use the pre-computed `totals` fields from the tool responses (e.g. `totals.total_deals.formatted_value` or `totals.total_work_orders.count`) to print total rows in tables or summary paragraphs. Do not perform any additions or manual sums.

IMPORTANT:
• Some dates were missing year information — when year was assumed, mention it briefly.
• Financial figures come in both GST-inclusive and GST-exclusive — state which you're reporting.
• For leadership updates, produce a structured executive summary suitable for a \
weekly standup or board deck."""

# ────────────────────────────────────────────────────────────────────
# Tool function declarations (google.genai format)
# ────────────────────────────────────────────────────────────────────

_TOOL_DECLARATIONS = [
    types.FunctionDeclaration(
        name="get_revenue_summary",
        description=(
            "Get revenue metrics from the Work Orders board: total order value, "
            "billed amount, collected amount, receivables, billing %. "
            "Optionally filter by sector or customer name."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "sector": types.Schema(type=types.Type.STRING, description="Filter by sector (e.g. 'Energy', 'Mining'). Case-insensitive substring match."),
                "customer": types.Schema(type=types.Type.STRING, description="Filter by customer name/code. Case-insensitive substring match."),
            },
        ),
    ),
    types.FunctionDeclaration(
        name="get_pipeline_health",
        description=(
            "Analyze the sales pipeline from the Deals board: total deals, "
            "pipeline value, stage distribution, status breakdown, sector split, "
            "closure probability. Optionally filter by sector, deal stage, or quarter."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "sector": types.Schema(type=types.Type.STRING, description="Filter by sector/service (e.g. 'Energy', 'Infrastructure'). Case-insensitive."),
                "deal_stage": types.Schema(type=types.Type.STRING, description="Filter by deal stage (e.g. 'Proposal', 'Negotiation'). Case-insensitive."),
                "quarter": types.Schema(type=types.Type.STRING, description="Filter by quarter (e.g. 'this quarter', 'Q3 2026', 'last quarter'). Case-insensitive."),
            },
        ),
    ),
    types.FunctionDeclaration(
        name="get_sector_breakdown",
        description="Cross-board analysis: shows work-order revenue AND deal pipeline value for each sector side by side.",
        parameters=types.Schema(type=types.Type.OBJECT, properties={}),
    ),
    types.FunctionDeclaration(
        name="get_operational_metrics",
        description=(
            "Work-order operational health: execution status distribution, "
            "nature of work breakdown, invoice/billing status, software involvement. "
            "Optionally filter by sector."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "sector": types.Schema(type=types.Type.STRING, description="Filter by sector. Case-insensitive."),
            },
        ),
    ),
    types.FunctionDeclaration(
        name="get_top_customers",
        description=(
            "Rank customers by work-order revenue (excl GST). "
            "Returns top N customers with order count, total value, "
            "billed, collected, and receivable amounts."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "n": types.Schema(type=types.Type.INTEGER, description="Number of top customers to return. Default 10."),
            },
        ),
    ),
    types.FunctionDeclaration(
        name="get_billing_health",
        description="Billing & collections overview: billing rate, collection rate, AR priority breakdown, billing/collection status distribution.",
        parameters=types.Schema(type=types.Type.OBJECT, properties={}),
    ),
    types.FunctionDeclaration(
        name="get_deal_funnel",
        description="Deal funnel/stage analysis: count and value at each deal stage, product/service breakdown.",
        parameters=types.Schema(type=types.Type.OBJECT, properties={}),
    ),
    types.FunctionDeclaration(
        name="generate_leadership_update",
        description=(
            "Generate a comprehensive executive summary / leadership update "
            "covering pipeline health, revenue snapshot, sector mix, "
            "operational status, and data quality notes."
        ),
        parameters=types.Schema(type=types.Type.OBJECT, properties={}),
    ),
    types.FunctionDeclaration(
        name="get_data_quality",
        description="Data completeness report: per-column missing-value percentages for both Work Orders and Deals boards.",
        parameters=types.Schema(type=types.Type.OBJECT, properties={}),
    ),
    types.FunctionDeclaration(
        name="refresh_data",
        description="Force a fresh data pull from Monday.com, clearing the cache. Use when the user says data may have changed.",
        parameters=types.Schema(type=types.Type.OBJECT, properties={}),
    ),
]

TOOLS = types.Tool(function_declarations=_TOOL_DECLARATIONS)

# ────────────────────────────────────────────────────────────────────
# Tool dispatch
# ────────────────────────────────────────────────────────────────────

def _dispatch(name: str, args: dict) -> dict:
    """Execute a tool by name and return its result dict."""
    dispatch = {
        "get_revenue_summary":        lambda a: revenue_summary(sector=a.get("sector"), customer=a.get("customer")),
        "get_pipeline_health":        lambda a: pipeline_health(sector=a.get("sector"), deal_stage=a.get("deal_stage"), quarter=a.get("quarter")),
        "get_sector_breakdown":       lambda a: sector_breakdown(),
        "get_operational_metrics":    lambda a: operational_metrics(sector=a.get("sector")),
        "get_top_customers":          lambda a: top_customers(n=int(a.get("n", 10))),
        "get_billing_health":         lambda a: billing_health(),
        "get_deal_funnel":            lambda a: deal_stage_funnel(),
        "generate_leadership_update": lambda a: leadership_update(),
        "get_data_quality":           lambda a: data_quality_summary(),
        "refresh_data":               lambda a: _do_refresh(),
    }
    fn = dispatch.get(name)
    if not fn:
        return {"data": {"error": f"Unknown tool: {name}"}, "caveats": []}
    return fn(args)


def _do_refresh():
    invalidate_cache()
    return {"data": {"message": "Cache cleared. Next query will fetch fresh data from Monday.com."}, "caveats": []}


# ────────────────────────────────────────────────────────────────────
# JSON serializer (handles NaN, dates, pandas types)
# ────────────────────────────────────────────────────────────────────

def _json_default(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    try:
        return str(obj)
    except Exception:
        return None


def _clean_for_response(obj) -> dict:
    """Round-trip through JSON to produce a protobuf-safe dict (no NaN/NaT)."""
    serialized = json.dumps(obj, default=_json_default, ensure_ascii=False)
    return json.loads(serialized)


# ────────────────────────────────────────────────────────────────────
# Client + Chat
# ────────────────────────────────────────────────────────────────────

_client_instance = None
_last_api_key = None

def _get_client() -> genai.Client:
    global _client_instance, _last_api_key
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Export it as an environment variable "
            "or add it to Streamlit secrets."
        )
    if _client_instance is None or api_key != _last_api_key:
        # Configure client with 120s timeout (value is in milliseconds, so 120,000 ms)
        http_options = types.HttpOptions(
            timeout=120000,
            retry_options=types.HttpRetryOptions(
                attempts=3,
                initial_delay=2.0,
                max_delay=10.0,
                exp_base=2.0,
                jitter=True,
            )
        )
        _client_instance = genai.Client(api_key=api_key, http_options=http_options)
        _last_api_key = api_key
    return _client_instance


def create_chat():
    """Create a new Gemini chat session with tools configured."""
    client = _get_client()
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=[TOOLS],
    )
    chat = client.chats.create(
        model=DEFAULT_MODEL,
        config=config,
    )
    return chat


def _send_with_retry(chat_session, message, retries=4, delay=2, backoff=2):
    """
    Wrapper for chat_session.send_message with exponential backoff retry.
    Handles any transport, SSL, or API errors robustly.
    """
    for attempt in range(retries):
        try:
            return chat_session.send_message(message)
        except Exception as e:
            if attempt == retries - 1:
                raise e
            time.sleep(delay)
            delay *= backoff


# ────────────────────────────────────────────────────────────────────
# Agent turn
# ────────────────────────────────────────────────────────────────────

def run_agent_turn(user_message: str, chat_session) -> tuple:
    """
    Process one user turn through Gemini with function-calling.

    Args:
        user_message: The user's natural-language query.
        chat_session: A genai ChatSession (or None to start fresh).

    Returns:
        (response_text, chat_session)
    """
    if chat_session is None:
        chat_session = create_chat()

    # Send user message
    response = _send_with_retry(chat_session, user_message)

    # Function-calling loop
    loop_count = 0
    while loop_count < MAX_TOOL_LOOPS:
        # Check for function calls in the response
        fn_calls = []
        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                if part.function_call:
                    fn_calls.append(part.function_call)

        if not fn_calls:
            break
        loop_count += 1

        # Execute each function call and build function responses
        fn_response_parts = []
        for fn_call in fn_calls:
            try:
                result = _dispatch(fn_call.name, dict(fn_call.args) if fn_call.args else {})
                clean_result = _clean_for_response(result)
            except Exception as e:
                clean_result = {"error": str(e), "caveats": ["Tool execution failed"]}

            fn_response_parts.append(
                types.Part.from_function_response(
                    name=fn_call.name,
                    response=clean_result,
                )
            )

        # Feed function results back to Gemini
        response = _send_with_retry(chat_session, fn_response_parts)

    # Extract final text
    response_text = ""
    try:
        response_text = response.text
    except (ValueError, AttributeError):
        # Fallback: manually extract text parts
        if response.candidates and response.candidates[0].content:
            texts = [p.text for p in response.candidates[0].content.parts if p.text]
            response_text = "\n".join(texts)

    if not response_text:
        response_text = "I wasn't able to generate a response. Please try rephrasing your question."

    return response_text, chat_session
