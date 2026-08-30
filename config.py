"""
Board IDs and column-ID -> friendly-name maps for the Skylark Drones
monday.com BI agent.

These maps were built directly from the real board schemas (pulled via
a `columns { id title type }` query), not guessed -- monday.com assigns
opaque IDs like `color_mm6q5ggg` to each column, and those don't
change once the board exists, so hardcoding this mapping is safe and
necessary. What must NOT be hardcoded is any actual row data -- that
always comes from a live API call (see monday_client.py).

Fill in DEALS_BOARD_ID below once you've grabbed it from the Deal
funnel Data board's URL.
"""

WORK_ORDERS_BOARD_ID = 5030963344
DEALS_BOARD_ID = 5030963465

WORK_ORDERS_COLUMNS = {
    "dropdown_mm6qr0qw": "customer_name_code",
    "text_mm6qj5b2": "serial_number",
    "color_mm6q5ggg": "nature_of_work",
    "text_mm6qfdrw": "last_executed_month",
    "color_mm6q4ayj": "execution_status",
    "date_mm6qk5gy": "data_delivery_date",
    "date_mm6q74et": "date_of_po_loi",
    "color_mm6qd1k3": "document_type",
    "date_mm6q3pfs": "probable_start_date",
    "date_mm6q9g1t": "probable_end_date",
    "dropdown_mm6qhda0": "bd_kam_personnel_code",
    "color_mm6q3s36": "sector",
    "color_mm6qza29": "type_of_work",
    "color_mm6qvknv": "skylark_software_involved",
    "date_mm6q9fs9": "last_invoice_date",
    "text_mm6q79yv": "latest_invoice_no",
    "numeric_mm6qv47w": "amount_excl_gst",
    "numeric_mm6qvszr": "amount_incl_gst",
    "numeric_mm6qj7cx": "billed_value_excl_gst",
    "numeric_mm6q3drs": "billed_value_incl_gst",
    "numeric_mm6qvwdv": "collected_amount_incl_gst",
    "numeric_mm6q6s5p": "amount_to_be_billed_excl_gst",
    "numeric_mm6qk6pa": "amount_to_be_billed_incl_gst",
    "numeric_mm6qnreg": "amount_receivable",
    "color_mm6qpayt": "ar_priority_account",
    "numeric_mm6qp6zr": "quantity_by_ops",
    "text_mm6qek4": "quantities_as_per_po",
    "numeric_mm6qtbd5": "quantity_billed_till_date",
    "numeric_mm6q57sw": "balance_in_quantity",
    "color_mm6qpaf9": "invoice_status",
    "text_mm6qssvj": "expected_billing_month",
    "text_mm6qv4f7": "actual_billing_month",
    "text_mm6qe00v": "actual_collection_month",
    "color_mm6qrh96": "wo_status_billed",
    "text_mm6q9qpb": "collection_status",
    "text_mm6qfty5": "collection_date",
    "color_mm6q3qf8": "billing_status",
}

DEALS_COLUMNS = {
    "dropdown_mm6qp7gk": "owner_code",
    "dropdown_mm6qpctt": "client_code",
    "color_mm6qer4w": "deal_status",
    "date_mm6qnwmz": "close_date",
    "color_mm6qhk53": "closure_probability",
    "numeric_mm6qy62v": "deal_value",
    "date_mm6qm61z": "tentative_close_date",
    "color_mm6q74w6": "deal_stage",
    "color_mm6qhh2b": "product_deal",
    "color_mm6q661c": "sector_service",
    "date_mm6qj4q9": "created_date",
}
