# Decision Log — Skylark Drones BI Agent

## Key Assumptions

1. **Year inference for ambiguous dates.** Several Monday.com fields contain dates like "Feb 26" with no year. We assume the current year (2026) and tag every such date with a `year_assumed=True` flag. The agent surfaces this as a caveat when the answer depends on one of these dates.

2. **Sector name normalization.** The Work Orders board uses "sector" and the Deals board uses "sector_service." Values may differ slightly in casing/whitespace (e.g., "Mining " vs "Mining"). We normalize via stripping + collapsing whitespace but never merge categories that aren't identical — the agent reports if a sector query finds no match rather than guessing.

3. **Empty strings = missing.** Monday.com returns `""` (empty string) for blank fields, not null. We convert these to `None`/`NaN` at ingestion so pandas treats them as genuinely missing, which lets us compute accurate completeness percentages.

4. **Currency is INR.** Skylark Drones is an Indian company; all financial fields are treated as Indian Rupees. The agent formats large numbers in lakhs/crores.

5. **Read-only integration.** The agent never writes back to Monday.com. All data flows one way: Monday → agent → user.

6. **Connection & Transport Resilience.** The Google GenAI SDK's underlying transport client (`httpx`) is prone to transient read timeouts or remote connection terminations during long-running tool loops (like generation of leadership updates). We configure the client with a 120,000ms (120s) timeout and a retry policy. Note that the `google-genai` SDK's `HttpOptions.timeout` parameter expects milliseconds (which it divides by 1000 before passing to `httpx.Client`), so setting a raw float like `120.0` translates to `0.12` seconds, causing immediate timeouts. We also implement an application-level wrapper (`_send_with_retry`) with exponential backoff specifically for network/transport-layer failures (`httpx.RemoteProtocolError`, `httpx.ReadTimeout`, `ConnectError`). Additionally, to handle SSL handshake timeouts on Windows/local networks caused by misconfigured IPv6 advertisements by some ISPs, we monkeypatch the python socket layer in `app.py` to force DNS lookup to IPv4.

## Trade-offs Chosen

| Decision | Chosen | Alternative | Why |
|----------|--------|-------------|-----|
| **LLM provider** | Google Gemini 3.5 Flash Lite via function-calling | OpenAI GPT-4o, Anthropic Claude | Free tier available via Google AI Studio, fast inference, excellent function-calling support, generous rate limits for a prototype. |
| **Agent pattern** | Tool-use (function calling) | RAG over embedded rows | Data is structured tabular data, not documents. Tool-use lets the LLM pick the right analytics function and pass filters — far more reliable than vector search over numbers. |
| **Data freshness** | Live fetch per query (5-min cache) | Pre-load + nightly sync | Boards are small (<500 rows each). A live pull takes ~1-2 seconds and guarantees the founder always sees current data. The 5-minute cache avoids redundant API calls within a single conversation turn. |
| **Frontend** | Streamlit | React/Next.js, Gradio | Fastest path to a deployed conversational UI. `st.chat_message` gives a clean chat experience. Streamlit Cloud offers free hosting with secrets management. |
| **Column mapping** | Hardcoded ID→name map | Dynamic schema discovery | Monday.com column IDs are opaque (`color_mm6q5ggg`) and stable once created. A one-time mapping is safer than parsing titles at runtime, which would break if someone renames a column. |
| **Metric functions** | Pre-built analytics functions exposed as tools | Raw DataFrame passed to LLM | Structured functions return consistent JSON with built-in caveats. Sending raw DataFrames to the LLM would be token-expensive, unreliable, and couldn't scale past a few hundred rows. |

## How I Interpreted "Leadership Updates"

A **leadership update** is a structured executive briefing designed for a weekly standup or board deck slide. It pulls the key numbers a founder needs to assess business health at a glance:

- **Pipeline snapshot** — total deals, total pipeline value, stage distribution (how many deals at Proposal vs. Negotiation vs. Won vs. Lost)
- **Revenue realization** — total order value, how much has been billed, how much collected, outstanding receivables
- **Sector mix** — which sectors are driving both work orders (execution) and deals (pipeline)
- **Operational status** — execution status distribution (how many projects are in progress, completed, on hold)
- **Data quality notes** — which columns have significant gaps, so the founder knows what to trust

The agent produces this as a formatted narrative summary, not raw JSON. It's triggered either by asking "generate a leadership update" or by clicking the sidebar button.

## What I'd Do Differently With More Time

1. **Add visualizations.** Embed Plotly/Altair charts directly in the Streamlit chat — funnel diagrams for deal stages, bar charts for sector revenue, timelines for project execution.

2. **Drill-down interaction.** Let users click on a sector or customer in a summary to see detailed breakdowns without re-typing a query.

3. **Scheduled reports.** Email/Slack delivery of the leadership update on a weekly cadence using a cron job or Monday.com automations.

4. **Historical trending.** Monday.com's activity log API could track how deal values and stages change over time, enabling "How has our pipeline changed this quarter?" queries.

5. **Test suite.** Unit tests for every metrics function with mock Monday.com payloads, plus integration tests against a sandbox board.

6. **Semantic caching.** Cache not just raw data but query→answer pairs for repeated questions, reducing both API cost and latency.
