"""
Run this once, after:
  1. setting DEALS_BOARD_ID in config.py
  2. exporting MONDAY_API_TOKEN in your shell

to confirm the fetch -> clean pipeline works against real monday.com
data before building the conversational agent on top of it.

    export MONDAY_API_TOKEN="your_token_here"
    python test_pull.py
"""

from monday_client import fetch_work_orders, fetch_deals
from data_cleaning import clean_work_orders_df, clean_deals_df, data_quality_report

if __name__ == "__main__":
    print("Fetching Work Orders...")
    wo_raw = fetch_work_orders()
    print(f"  {len(wo_raw)} rows fetched")
    wo_df = clean_work_orders_df(wo_raw)
    print(wo_df.head())
    print(data_quality_report(wo_df, "work_orders"))

    print("\nFetching Deals...")
    deals_raw = fetch_deals()
    print(f"  {len(deals_raw)} rows fetched")
    deals_df = clean_deals_df(deals_raw)
    print(deals_df.head())
    print(data_quality_report(deals_df, "deals"))
