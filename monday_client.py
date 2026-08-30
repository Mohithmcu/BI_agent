"""
Thin GraphQL client for pulling Work Orders and Deals data out of
monday.com.

Read-only. Dynamic -- every call hits the live API; no row data is
ever cached to disk or hardcoded. Only the column-ID -> name maps in
config.py are fixed, since those describe board structure (set once
when the board was created), not the data itself.
"""

import os
import time
from typing import Optional

import requests

from config import (
    WORK_ORDERS_BOARD_ID,
    DEALS_BOARD_ID,
    WORK_ORDERS_COLUMNS,
    DEALS_COLUMNS,
)

MONDAY_API_URL = "https://api.monday.com/v2"


def _get_token() -> str:
    token = os.environ.get("MONDAY_API_TOKEN")
    if not token:
        raise RuntimeError(
            "MONDAY_API_TOKEN is not set. Export it as an environment "
            "variable (or set it as a secret in your hosting platform) "
            "before calling the monday.com API."
        )
    return token


def _run_query(query: str, variables: Optional[dict] = None) -> dict:
    retries = 3
    delay = 2.0
    for attempt in range(retries):
        try:
            resp = requests.post(
                MONDAY_API_URL,
                json={"query": query, "variables": variables or {}},
                headers={
                    "Authorization": _get_token(),
                    "Content-Type": "application/json",
                },
                timeout=30,
            )
            resp.raise_for_status()
            payload = resp.json()
            if "errors" in payload:
                raise RuntimeError(f"monday.com API error: {payload['errors']}")
            return payload["data"]
        except (requests.exceptions.RequestException, RuntimeError) as e:
            if attempt == retries - 1:
                raise e
            time.sleep(delay)
            delay *= 2.0


def _fetch_all_items(board_id: int) -> list:
    """
    Pull every item on a board, following the items_page cursor until
    exhausted. A board bigger than one page (100 items here) requires
    this loop -- don't assume a single query gets everything.
    """
    items = []
    cursor = None
    query = """
    query ($boardId: [ID!], $cursor: String) {
      boards(ids: $boardId) {
        items_page(limit: 100, cursor: $cursor) {
          cursor
          items {
            id
            name
            column_values {
              id
              text
            }
          }
        }
      }
    }
    """
    while True:
        data = _run_query(query, {"boardId": [board_id], "cursor": cursor})
        page = data["boards"][0]["items_page"]
        items.extend(page["items"])
        cursor = page["cursor"]
        if not cursor:
            break
    return items


def _flatten_items(raw_items: list, column_map: dict) -> list:
    """
    Turn monday's [{id, name, column_values:[{id, text}]}] shape into
    flat dicts keyed by friendly column names.

    - Unmapped column IDs are silently skipped rather than raising, so
      a board schema change doesn't take the whole pipeline down.
    - monday returns "" (empty string) for blank fields, not null --
      normalized here to None so pandas/downstream logic treats it as
      genuinely missing rather than an empty-but-present value.
    """
    flat = []
    for item in raw_items:
        row = {"item_id": item["id"], "item_name": item["name"]}
        for cv in item["column_values"]:
            friendly_name = column_map.get(cv["id"])
            if friendly_name:
                row[friendly_name] = cv["text"] if cv["text"] != "" else None
        flat.append(row)
    return flat


def fetch_work_orders() -> list:
    raw = _fetch_all_items(WORK_ORDERS_BOARD_ID)
    return _flatten_items(raw, WORK_ORDERS_COLUMNS)


def fetch_deals() -> list:
    if DEALS_BOARD_ID is None:
        raise RuntimeError(
            "DEALS_BOARD_ID is not set in config.py -- grab it from the "
            "Deal funnel Data board's URL first."
        )
    raw = _fetch_all_items(DEALS_BOARD_ID)
    return _flatten_items(raw, DEALS_COLUMNS)
