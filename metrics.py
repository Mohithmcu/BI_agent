"""
Business-intelligence metrics for Skylark Drones.

Every public function returns::

    {"data": { ... }, "caveats": [ ... ]}

so the AI agent can naturally surface data-quality issues in its
response rather than silently ignoring gaps.

An in-memory cache (5-min TTL) prevents hitting the Monday API
multiple times within a single conversation turn.
"""

import math
import time
from datetime import date, datetime

import pandas as pd

from monday_client import fetch_work_orders, fetch_deals
from data_cleaning import (
    clean_work_orders_df,
    clean_deals_df,
    data_quality_report,
)
STAGE_BUCKETS = {
    # Won (Closed/Post-Sale/Execution stages)
    "G. Project Won": "Won",
    "H. Work Order Received": "Won",
    "Project Completed": "Won",
    "J. Invoice sent": "Won",
    "K. Amount Accrued": "Won",
    "M. Projects On Hold": "Won",

    # Lost
    "L. Project Lost": "Lost",
    "N. Not relevant at the moment": "Lost",
    "O. Not Relevant at all": "Lost",

    # Active / Pipeline
    "A. Lead Generated": "Early-Stage",
    "B. Sales Qualified Leads": "Early-Stage",
    "C. Demo Done": "Early-Stage",
    "I. POC": "Early-Stage",

    "D. Feasibility": "Mid-Stage",
    "E. Proposal/Commercials Sent": "Mid-Stage",
    "F. Negotiations": "Mid-Stage",

    "Deal Stage": "Early-Stage",
}
# ────────────────────────────────────────────────────────────────────
# Cached data layer
# ────────────────────────────────────────────────────────────────────

_cache: dict = {"wo": None, "deals": None, "ts": 0}
_CACHE_TTL = 300  # seconds


def get_data() -> tuple:
    """Return (wo_df, deals_df), refreshing from Monday.com if stale."""
    now = time.time()
    if _cache["wo"] is None or (now - _cache["ts"]) > _CACHE_TTL:
        _cache["wo"] = clean_work_orders_df(fetch_work_orders())
        _cache["deals"] = clean_deals_df(fetch_deals())
        _cache["ts"] = now
    return _cache["wo"].copy(), _cache["deals"].copy()


def invalidate_cache():
    """Force a fresh pull on the next call."""
    _cache["ts"] = 0


# ────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────

def _safe(val):
    """Convert NaN / NaT / Inf → None for JSON safety."""
    if val is None:
        return None
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    if isinstance(val, (pd.Timestamp, datetime, date)):
        return val.isoformat()
    if pd.isna(val):
        return None
    return val


def format_inr(val) -> str:
    """Format numeric values to Indian Rupees (Lakhs / Crores)."""
    if val is None or pd.isna(val):
        return "₹0"
    val = float(val)
    if val >= 10000000:
        return f"₹{val / 10000000:.2f} Cr"
    elif val >= 100000:
        return f"₹{val / 100000:.2f} L"
    else:
        return f"₹{val:,.2f}"


def _ssum(series: pd.Series) -> float:
    """Sum ignoring NaN; 0.0 when empty."""
    v = series.sum()
    return 0.0 if pd.isna(v) else float(v)


def _pct_missing(series: pd.Series) -> float:
    if len(series) == 0:
        return 0.0
    return round(series.isna().mean() * 100, 1)


def _col_caveat(df, col, label, threshold=10):
    """Return a caveat string if >threshold % of col is missing, else None."""
    if col not in df.columns:
        return f"Column '{label}' not found in data"
    p = _pct_missing(df[col])
    if p > threshold:
        return f"{p}% of records are missing {label}"
    return None


def _groupby_dict(df, group_col, value_col=None):
    """Group by a column, returning {key: {count, total_value?, formatted_value?}}."""
    out = {}
    for key, grp in df.groupby(group_col, dropna=False):
        k = key if key and not pd.isna(key) else "Unknown"
        entry = {"count": int(len(grp))}
        if value_col and value_col in grp.columns:
            val = _ssum(grp[value_col])
            entry["total_value"] = _safe(val)
            entry["formatted_value"] = format_inr(val)
        out[k] = entry
    return out


def _groupby_value_summary(df, group_col, value_col):
    """
    Group by a column, returning {key: {count, total_value, formatted_value, missing_count, is_fully_missing, missing_pct}}.
    Unlike pandas defaults, if all values in a group are NaN, total_value is None (not 0.0).
    """
    out = {}
    for key, grp in df.groupby(group_col, dropna=False):
        k = key if key and not pd.isna(key) else "Unknown"
        count = len(grp)
        series = grp[value_col] if value_col in grp.columns else pd.Series()
        
        missing = int(series.isna().sum())
        is_fully_missing = (missing == count and count > 0)
        
        total_val = None
        if not is_fully_missing and count > 0:
            total_val = float(series.sum(skipna=True))
            
        out[k] = {
            "count": int(count),
            "total_value": _safe(total_val),
            "formatted_value": format_inr(total_val) if total_val is not None else "Unknown",
            "missing_count": missing,
            "is_fully_missing": is_fully_missing,
            "missing_pct": round(missing / count * 100, 1) if count > 0 else 0.0
        }
    return out


def _filter(df, col, value):
    """Case-insensitive substring filter; returns (filtered_df, applied?)."""
    if not value or col not in df.columns:
        return df, False
    mask = df[col].str.contains(value, case=False, na=False)
    return df[mask], True


def _parse_quarter(quarter_str: str) -> tuple:
    """
    Parses quarter strings like 'this quarter', 'Q2 2026', 'next q', etc.
    Returns (start_date, end_date, error_message)
    """
    import re
    import datetime
    
    today = date.today()
    current_year = today.year
    current_month = today.month
    current_quarter = (current_month - 1) // 3 + 1
    
    q_str = quarter_str.strip().lower()
    
    q_num = None
    q_year = current_year
    
    if q_str in ["this quarter", "current quarter", "this q", "current q"]:
        q_num = current_quarter
    elif q_str in ["next quarter", "next q"]:
        q_num = current_quarter + 1
        if q_num > 4:
            q_num = 1
            q_year = current_year + 1
    elif q_str in ["last quarter", "previous quarter", "last q", "prev q"]:
        q_num = current_quarter - 1
        if q_num < 1:
            q_num = 4
            q_year = current_year - 1
    else:
        # Match patterns like Q3, Q3 2026, 2026 Q3, etc.
        m = re.search(r"q([1-4])", q_str)
        if m:
            q_num = int(m.group(1))
            # look for a 4-digit year
            my = re.search(r"\b(20\d{2})\b", q_str)
            if my:
                q_year = int(my.group(1))
        else:
            return None, None, f"Unrecognized time frame or quarter format: '{quarter_str}'"
            
    # Compute start and end dates
    start_month = (q_num - 1) * 3 + 1
    start_date = date(q_year, start_month, 1)
    
    if start_month + 3 > 12:
        end_date = date(q_year + 1, 1, 1) - datetime.timedelta(days=1)
    else:
        end_date = date(q_year, start_month + 3, 1) - datetime.timedelta(days=1)
        
    return start_date, end_date, None


# ────────────────────────────────────────────────────────────────────
# Metric functions
# ────────────────────────────────────────────────────────────────────

def revenue_summary(sector: str = None, customer: str = None) -> dict:
    """Work-order revenue: total value, billed, collected, receivable."""
    wo, _ = get_data()
    caveats = []

    wo, _ = _filter(wo, "sector", sector)
    wo, _ = _filter(wo, "customer_name_code", customer)
    if wo.empty:
        return {"data": {"message": "No matching work orders found."}, "caveats": ["Filter returned zero rows"]}

    for label, col in [
        ("order amount (excl GST)", "amount_excl_gst"),
        ("billed value (excl GST)", "billed_value_excl_gst"),
        ("collected amount (incl GST)", "collected_amount_incl_gst"),
        ("receivable amount", "amount_receivable"),
    ]:
        c = _col_caveat(wo, col, label)
        if c:
            caveats.append(c)

    total   = _ssum(wo["amount_excl_gst"])          if "amount_excl_gst" in wo.columns else None
    billed  = _ssum(wo["billed_value_excl_gst"])    if "billed_value_excl_gst" in wo.columns else None
    collect = _ssum(wo["collected_amount_incl_gst"]) if "collected_amount_incl_gst" in wo.columns else None
    recv    = _ssum(wo["amount_receivable"])          if "amount_receivable" in wo.columns else None
    to_bill = _ssum(wo["amount_to_be_billed_excl_gst"]) if "amount_to_be_billed_excl_gst" in wo.columns else None

    bill_pct = round(billed / total * 100, 1) if total and total > 0 and billed is not None else None
    coll_pct = round(collect / billed * 100, 1) if billed and billed > 0 and collect is not None else None

    return {
        "data": {
            "total_work_orders": len(wo),
            "total_order_value_excl_gst": _safe(total),
            "total_order_value_excl_gst_formatted": format_inr(total),
            "total_billed_excl_gst": _safe(billed),
            "total_billed_excl_gst_formatted": format_inr(billed),
            "total_collected_incl_gst": _safe(collect),
            "total_collected_incl_gst_formatted": format_inr(collect),
            "total_receivable": _safe(recv),
            "total_receivable_formatted": format_inr(recv),
            "yet_to_bill_excl_gst": _safe(to_bill),
            "yet_to_bill_excl_gst_formatted": format_inr(to_bill),
            "billing_percentage": _safe(bill_pct),
            "collection_percentage": _safe(coll_pct),
        },
        "caveats": caveats,
    }


def pipeline_health(sector: str = None, deal_stage: str = None, quarter: str = None) -> dict:
    """Deals pipeline: counts, values, stage & sector distribution. Optionally filtered by quarter."""
    _, deals = get_data()
    caveats = []

    deals, _ = _filter(deals, "sector_service", sector)
    deals, _ = _filter(deals, "deal_stage", deal_stage)

    if quarter:
        start_date, end_date, q_err = _parse_quarter(quarter)
        if q_err:
            caveats.append(q_err)
        elif start_date and end_date:
            if "close_date" in deals.columns:
                # Filter by close_date
                in_window = (deals["close_date"] >= start_date) & (deals["close_date"] <= end_date)
                deals = deals[in_window]
                
                # Check for year-assumed caveats
                if "close_date_year_assumed" in deals.columns and deals["close_date_year_assumed"].any():
                    caveats.append(
                        "Close dates for some deals in this period had no year specified in the source data "
                        "(the current year was assumed)."
                    )
            else:
                caveats.append("close_date column not found; cannot apply quarter filter.")

    if deals.empty:
        return {
            "data": {
                "message": f"No matching deals found" + (f" for {quarter}" if quarter else "") + "."
            },
            "caveats": caveats + ["Filter returned zero rows"]
        }

    c = _col_caveat(deals, "deal_value", "deal value")
    if c:
        caveats.append(c)

    total_val = _ssum(deals["deal_value"]) if "deal_value" in deals.columns else None

    by_stage  = _groupby_dict(deals, "deal_stage", "deal_value") if "deal_stage" in deals.columns else {}
    by_status = _groupby_dict(deals, "deal_status") if "deal_status" in deals.columns else {}
    by_sector = _groupby_dict(deals, "sector_service", "deal_value") if "sector_service" in deals.columns else {}

    # Closure probability distribution
    by_prob = _groupby_dict(deals, "closure_probability", "deal_value") if "closure_probability" in deals.columns else {}

    return {
        "data": {
            "total_deals": len(deals),
            "total_pipeline_value": _safe(total_val),
            "total_pipeline_value_formatted": format_inr(total_val),
            "by_stage": by_stage,
            "by_status": by_status,
            "by_sector": by_sector,
            "by_closure_probability": by_prob,
        },
        "caveats": caveats,
    }


def sector_breakdown() -> dict:
    """Cross-board: work-order revenue + deal pipeline per sector."""
    wo, deals = get_data()
    caveats = []

    wo_by = _groupby_dict(wo, "sector", "amount_excl_gst") if "sector" in wo.columns else {}
    deal_by = _groupby_dict(deals, "sector_service", "deal_value") if "sector_service" in deals.columns else {}

    sectors = sorted(set(list(wo_by.keys()) + list(deal_by.keys())))
    combined = {}
    
    total_wo_count = 0
    total_wo_val = 0.0
    total_deals_count = 0
    total_deals_val = 0.0
    
    for s in sectors:
        wo_info = wo_by.get(s, {"count": 0, "total_value": 0, "formatted_value": "₹0"})
        deal_info = deal_by.get(s, {"count": 0, "total_value": 0, "formatted_value": "₹0"})
        
        combined[s] = {
            "work_orders": wo_info,
            "deals": deal_info,
        }
        
        total_wo_count += wo_info["count"]
        total_wo_val += wo_info.get("total_value", 0) or 0
        total_deals_count += deal_info["count"]
        total_deals_val += deal_info.get("total_value", 0) or 0

    if not combined:
        caveats.append("No sector data available in either board")

    return {
        "data": combined,
        "totals": {
            "total_work_orders": {
                "count": total_wo_count,
                "total_value": _safe(total_wo_val),
                "formatted_value": format_inr(total_wo_val),
            },
            "total_deals": {
                "count": total_deals_count,
                "total_value": _safe(total_deals_val),
                "formatted_value": format_inr(total_deals_val),
            }
        },
        "caveats": caveats
    }


def operational_metrics(sector: str = None) -> dict:
    """Work-order execution: status distribution, nature of work, type."""
    wo, _ = get_data()
    caveats = []

    wo, _ = _filter(wo, "sector", sector)
    if wo.empty:
        return {"data": {"message": "No matching work orders."}, "caveats": []}

    by_exec_status = _groupby_dict(wo, "execution_status") if "execution_status" in wo.columns else {}
    by_nature       = _groupby_dict(wo, "nature_of_work") if "nature_of_work" in wo.columns else {}
    by_type         = _groupby_dict(wo, "type_of_work") if "type_of_work" in wo.columns else {}
    by_invoice_st   = _groupby_dict(wo, "invoice_status") if "invoice_status" in wo.columns else {}
    by_billing_st   = _groupby_dict(wo, "billing_status") if "billing_status" in wo.columns else {}

    # Software involvement
    by_software = _groupby_dict(wo, "skylark_software_involved") if "skylark_software_involved" in wo.columns else {}

    return {
        "data": {
            "total_work_orders": len(wo),
            "by_execution_status": by_exec_status,
            "by_nature_of_work": by_nature,
            "by_type_of_work": by_type,
            "by_invoice_status": by_invoice_st,
            "by_billing_status": by_billing_st,
            "by_software_involved": by_software,
        },
        "caveats": caveats,
    }


def top_customers(n: int = 10) -> dict:
    """Top customers by work-order revenue (excl GST)."""
    wo, _ = get_data()
    caveats = []

    if "customer_name_code" not in wo.columns or "amount_excl_gst" not in wo.columns:
        return {"data": {"message": "Customer or amount columns not found."}, "caveats": ["Missing columns"]}

    grouped = (
        wo.groupby("customer_name_code", dropna=False)
        .agg(
            order_count=("amount_excl_gst", "size"),
            total_value=("amount_excl_gst", "sum"),
            total_billed=("billed_value_excl_gst", "sum") if "billed_value_excl_gst" in wo.columns else ("amount_excl_gst", "size"),
            total_collected=("collected_amount_incl_gst", "sum") if "collected_amount_incl_gst" in wo.columns else ("amount_excl_gst", "size"),
            total_receivable=("amount_receivable", "sum") if "amount_receivable" in wo.columns else ("amount_excl_gst", "size"),
        )
        .sort_values("total_value", ascending=False)
        .head(n)
    )

    rows = []
    for cust, row in grouped.iterrows():
        rows.append({
            "customer": cust if cust and not pd.isna(cust) else "Unknown",
            "order_count": int(row["order_count"]),
            "total_value_excl_gst": _safe(row["total_value"]),
            "total_billed": _safe(row.get("total_billed")),
            "total_collected": _safe(row.get("total_collected")),
            "total_receivable": _safe(row.get("total_receivable")),
        })

    return {"data": {"customers": rows}, "caveats": caveats}


def billing_health() -> dict:
    """Billing & collections overview across all work orders."""
    wo, _ = get_data()
    caveats = []

    total_value  = _ssum(wo["amount_excl_gst"]) if "amount_excl_gst" in wo.columns else 0
    billed       = _ssum(wo["billed_value_excl_gst"]) if "billed_value_excl_gst" in wo.columns else 0
    collected    = _ssum(wo["collected_amount_incl_gst"]) if "collected_amount_incl_gst" in wo.columns else 0
    receivable   = _ssum(wo["amount_receivable"]) if "amount_receivable" in wo.columns else 0
    to_bill      = _ssum(wo["amount_to_be_billed_excl_gst"]) if "amount_to_be_billed_excl_gst" in wo.columns else 0

    # AR priority breakdown
    ar_priority = _groupby_dict(wo, "ar_priority_account", "amount_receivable") if "ar_priority_account" in wo.columns else {}

    # Billing status breakdown
    bill_status = _groupby_dict(wo, "billing_status", "amount_excl_gst") if "billing_status" in wo.columns else {}
    coll_status = _groupby_dict(wo, "collection_status", "collected_amount_incl_gst") if "collection_status" in wo.columns else {}

    return {
        "data": {
            "total_order_value": _safe(total_value),
            "total_billed": _safe(billed),
            "total_collected": _safe(collected),
            "total_receivable": _safe(receivable),
            "yet_to_bill": _safe(to_bill),
            "billing_rate_pct": _safe(round(billed / total_value * 100, 1) if total_value > 0 else None),
            "collection_rate_pct": _safe(round(collected / billed * 100, 1) if billed > 0 else None),
            "by_ar_priority": ar_priority,
            "by_billing_status": bill_status,
            "by_collection_status": coll_status,
        },
        "caveats": caveats,
    }


def deal_stage_funnel() -> dict:
    """Deal funnel: count + value at each stage, ordered by pipeline progression."""
    _, deals = get_data()
    caveats = []

    if "deal_stage" not in deals.columns:
        return {"data": {"message": "deal_stage column not found."}, "caveats": ["Missing column"]}

    # Raw stage breakdown (NaN-safe)
    funnel = _groupby_value_summary(deals, "deal_stage", "deal_value")

    # Create high-level and sub-bucket mappings
    deals["high_level_bucket"] = deals["deal_stage"].map(
        lambda s: "Won" if STAGE_BUCKETS.get(s) == "Won" else
                  "Lost" if STAGE_BUCKETS.get(s) == "Lost" else "Active"
    )
    deals["sub_bucket"] = deals["deal_stage"].map(
        lambda s: STAGE_BUCKETS.get(s, "Unknown")
    )

    high_level_summary = _groupby_value_summary(deals, "high_level_bucket", "deal_value")
    sub_bucket_summary = _groupby_value_summary(deals, "sub_bucket", "deal_value")

    # Product/service breakdown
    by_product = _groupby_value_summary(deals, "product_deal", "deal_value") if "product_deal" in deals.columns else {}

    # Identify stage-level caveats (where a group is fully missing data)
    for stage_name, info in funnel.items():
        if info["is_fully_missing"] and info["count"] > 0:
            caveats.append(f"Stage '{stage_name}' has {info['count']} deals but all are missing deal values.")

    for bucket_name, info in sub_bucket_summary.items():
        if info["is_fully_missing"] and info["count"] > 0:
            caveats.append(f"Stage-group '{bucket_name}' has {info['count']} deals but all are missing deal values.")

    c = _col_caveat(deals, "deal_value", "deal value")
    if c:
        caveats.append(c)

    return {
        "data": {
            "total_deals": len(deals),
            "total_value": _safe(deals["deal_value"].sum(skipna=True) if "deal_value" in deals.columns else 0),
            "high_level_summary": high_level_summary,
            "sub_bucket_summary": sub_bucket_summary,
            "funnel_by_stage": funnel,
            "by_product": by_product,
        },
        "caveats": caveats,
    }


def leadership_update() -> dict:
    """
    Structured executive summary pulling KPIs from both boards.

    Interpretation of "leadership updates":
    A weekly/monthly executive briefing containing the key numbers a
    founder needs to assess business health at a glance — pipeline
    value, revenue realisation, sector mix, operational blockers, and
    data-quality notes so the founder knows what to trust.
    """
    wo, deals = get_data()
    caveats = []

    # ── Pipeline snapshot ──
    total_deals     = len(deals)
    pipeline_value  = _ssum(deals["deal_value"]) if "deal_value" in deals.columns else 0
    
    # NaN-safe stage summaries
    deals["high_level_bucket"] = deals["deal_stage"].map(
        lambda s: "Won" if STAGE_BUCKETS.get(s) == "Won" else
                  "Lost" if STAGE_BUCKETS.get(s) == "Lost" else "Active"
    )
    deals["sub_bucket"] = deals["deal_stage"].map(
        lambda s: STAGE_BUCKETS.get(s, "Unknown")
    )
    
    high_level_stage_dist = _groupby_value_summary(deals, "high_level_bucket", "deal_value")
    sub_bucket_stage_dist = _groupby_value_summary(deals, "sub_bucket", "deal_value")
    
    stage_dist      = _groupby_value_summary(deals, "deal_stage", "deal_value") if "deal_stage" in deals.columns else {}
    deal_status_dist = _groupby_dict(deals, "deal_status") if "deal_status" in deals.columns else {}

    # ── Revenue snapshot ──
    total_orders    = len(wo)
    order_value     = _ssum(wo["amount_excl_gst"]) if "amount_excl_gst" in wo.columns else 0
    billed          = _ssum(wo["billed_value_excl_gst"]) if "billed_value_excl_gst" in wo.columns else 0
    collected       = _ssum(wo["collected_amount_incl_gst"]) if "collected_amount_incl_gst" in wo.columns else 0
    receivable      = _ssum(wo["amount_receivable"]) if "amount_receivable" in wo.columns else 0

    # ── Sector mix ──
    wo_sectors   = _groupby_dict(wo, "sector", "amount_excl_gst") if "sector" in wo.columns else {}
    deal_sectors = _groupby_dict(deals, "sector_service", "deal_value") if "sector_service" in deals.columns else {}

    # ── Operational health ──
    exec_status = _groupby_dict(wo, "execution_status") if "execution_status" in wo.columns else {}

    # ── Data quality ──
    wo_quality   = data_quality_report(wo, "work_orders")
    deal_quality = data_quality_report(deals, "deals")

    high_missing = []
    for board_q in [wo_quality, deal_quality]:
        for col, info in board_q.get("columns", {}).items():
            if info.get("missing_pct", 0) > 20:
                high_missing.append(f"{board_q['label']}.{col}: {info['missing_pct']}% missing")
    if high_missing:
        caveats.append(f"High-missing columns: {'; '.join(high_missing[:5])}")

    return {
        "data": {
            "report_date": date.today().isoformat(),
            "pipeline": {
                "total_deals": total_deals,
                "total_pipeline_value": _safe(pipeline_value),
                "high_level_summary": high_level_stage_dist,
                "sub_bucket_summary": sub_bucket_stage_dist,
                "by_stage": stage_dist,
                "by_status": deal_status_dist,
            },
            "revenue": {
                "total_work_orders": total_orders,
                "total_order_value_excl_gst": _safe(order_value),
                "total_billed_excl_gst": _safe(billed),
                "total_collected_incl_gst": _safe(collected),
                "total_receivable": _safe(receivable),
                "billing_rate_pct": _safe(round(billed / order_value * 100, 1) if order_value > 0 else None),
                "collection_rate_pct": _safe(round(collected / billed * 100, 1) if billed > 0 else None),
            },
            "sector_mix": {
                "work_orders_by_sector": wo_sectors,
                "deals_by_sector": deal_sectors,
            },
            "operations": {
                "by_execution_status": exec_status,
            },
            "data_quality": {
                "work_orders_rows": wo_quality["row_count"],
                "deals_rows": deal_quality["row_count"],
                "notable_gaps": high_missing[:5],
            },
        },
        "caveats": caveats,
    }


def data_quality_summary() -> dict:
    """Per-column completeness for both boards."""
    wo, deals = get_data()
    return {
        "data": {
            "work_orders": data_quality_report(wo, "work_orders"),
            "deals": data_quality_report(deals, "deals"),
        },
        "caveats": [],
    }
