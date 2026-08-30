"""
Normalization layer sitting between raw monday.com data and the
business-logic/metrics functions built on top of it.

Handles the specific messiness identified while setting the boards up:
  - dates with no year ("Feb 26") mixed with full dates ("Sep 30, 2024")
  - month-name-only fields (Dec, June, November) that aren't real dates
  - blank/None fields
  - inconsistent whitespace/casing in category-like text fields
  - "Product deal" values that are really multiple products joined
    with "+" (e.g. "Service + Spectra")
"""

import re
from datetime import datetime

import pandas as pd
from dateutil import parser as dateutil_parser

CURRENT_YEAR = datetime.now().year

MONTH_NAMES = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def parse_flexible_date(value):
    """
    Parse a date string that might be missing its year ("Feb 26"), be
    a full date ("Sep 30, 2024"), or be blank.

    Returns (parsed_date_or_None, year_was_assumed: bool).

    ASSUMPTION (documented in the decision log): when no year is given
    we assume CURRENT_YEAR. This is a genuine ambiguity in the source
    data, not a settled fact -- any answer that depends on one of these
    dates should surface the `year_was_assumed` flag as a caveat rather
    than presenting the date as certain.
    """
    if not value or not isinstance(value, str):
        return None, False
    value = value.strip()
    if not value:
        return None, False

    has_year = bool(re.search(r"\b(19|20)\d{2}\b", value))
    try:
        parsed = dateutil_parser.parse(value, default=datetime(CURRENT_YEAR, 1, 1))
        return parsed.date(), not has_year
    except (ValueError, OverflowError):
        return None, False


def parse_month_name(value):
    """Turn 'Dec', 'November', 'june' etc. into a month number (1-12), else None."""
    if not value or not isinstance(value, str):
        return None
    return MONTH_NAMES.get(value.strip().lower())


def normalize_text_category(value):
    """
    Collapse whitespace/case inconsistency in free-text category-ish
    fields. Trims and normalizes spacing only -- never invents or
    merges categories that weren't already the same value.
    """
    if not value or not isinstance(value, str):
        return None
    cleaned = re.sub(r"\s+", " ", value.strip())
    return cleaned if cleaned else None


def _apply_date_column(df: pd.DataFrame, col: str) -> None:
    if col not in df.columns:
        return
    parsed = df[col].apply(parse_flexible_date)
    df[col] = parsed.apply(lambda t: t[0])
    df[f"{col}_year_assumed"] = parsed.apply(lambda t: t[1])


def clean_work_orders_df(raw_rows: list) -> pd.DataFrame:
    df = pd.DataFrame(raw_rows)
    if df.empty:
        return df

    for col in [
        "data_delivery_date", "date_of_po_loi", "probable_start_date",
        "probable_end_date", "last_invoice_date", "collection_date",
    ]:
        _apply_date_column(df, col)

    for col in ["sector", "nature_of_work", "type_of_work", "execution_status",
                "invoice_status", "wo_status_billed", "billing_status"]:
        if col in df.columns:
            df[col] = df[col].apply(normalize_text_category)

    for col in ["expected_billing_month", "actual_billing_month", "actual_collection_month",
                "last_executed_month"]:
        if col in df.columns:
            df[f"{col}_num"] = df[col].apply(parse_month_name)

    numeric_cols = [c for c in df.columns if any(
        k in c for k in ["amount", "billed_value", "quantity", "balance"]
    )]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def clean_deals_df(raw_rows: list) -> pd.DataFrame:
    df = pd.DataFrame(raw_rows)
    if df.empty:
        return df

    for col in ["close_date", "tentative_close_date", "created_date"]:
        _apply_date_column(df, col)

    for col in ["sector_service", "deal_stage", "deal_status", "closure_probability"]:
        if col in df.columns:
            df[col] = df[col].apply(normalize_text_category)

    if "deal_value" in df.columns:
        df["deal_value"] = pd.to_numeric(df["deal_value"], errors="coerce")

    if "product_deal" in df.columns:
        # "Service + Spectra" style combined values -- split into a list
        # so a query about "Spectra deals" matches this row too, instead
        # of only matching an exact "Spectra"-only string.
        df["product_deal_list"] = df["product_deal"].apply(
            lambda v: [p.strip() for p in v.split("+")] if isinstance(v, str) else []
        )

    return df


def data_quality_report(df: pd.DataFrame, label: str) -> dict:
    """
    Quick per-column completeness summary -- feed this into the
    agent's context so it can caveat answers ("18% of deals are
    missing a close date") instead of silently ignoring gaps.
    """
    if df.empty:
        return {"label": label, "row_count": 0, "columns": {}}
    total = len(df)
    return {
        "label": label,
        "row_count": total,
        "columns": {
            col: {
                "missing": int(df[col].isna().sum()),
                "missing_pct": round(df[col].isna().mean() * 100, 1),
            }
            for col in df.columns
        },
    }
