"""
Streamlit chat interface for the Skylark Drones BI Agent.

Run locally:
    streamlit run app.py

Deploy to Streamlit Cloud:
    Push to GitHub, connect the repo in share.streamlit.io,
    add MONDAY_API_TOKEN and GEMINI_API_KEY in Secrets.
"""

import os
import socket

# Force IPv4 to prevent SSL handshake timeouts on misconfigured IPv6 networks
orig_getaddrinfo = socket.getaddrinfo
def getaddrinfo_ipv4(*args, **kwargs):
    responses = orig_getaddrinfo(*args, **kwargs)
    ipv4_responses = [r for r in responses if r[0] == socket.AF_INET]
    return ipv4_responses if ipv4_responses else responses
socket.getaddrinfo = getaddrinfo_ipv4

import streamlit as st

# ── Load secrets into env vars so all modules can read them ──
# Streamlit Cloud stores secrets in st.secrets; local dev uses env vars.
for key in ["MONDAY_API_TOKEN", "GEMINI_API_KEY"]:
    if key not in os.environ:
        try:
            val = st.secrets.get(key, None)
        except Exception:
            val = None
        if val:
            os.environ[key] = val

from agent import run_agent_turn, create_chat  # noqa: E402
from metrics import invalidate_cache  # noqa: E402

# ────────────────────────────────────────────────────────────────────
# Page config
# ────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="BI Agent",
    page_icon="📊",
    layout="wide",
)

# ────────────────────────────────────────────────────────────────────
# Session state
# ────────────────────────────────────────────────────────────────────

if "display_messages" not in st.session_state:
    st.session_state.display_messages = []

if "chat_session" not in st.session_state:
    st.session_state.chat_session = None

# ────────────────────────────────────────────────────────────────────
# Sidebar
# ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.image("https://img.icons8.com/color/96/drone.png", width=60)
    st.title("BI Agent")

    st.divider()

    # Connection check
    st.subheader("🔌 Connection Status")
    monday_token = os.environ.get("MONDAY_API_TOKEN")
    gemini_key = os.environ.get("GEMINI_API_KEY")

    if monday_token:
        st.success("Monday.com API: Connected", icon="✅")
    else:
        st.error("Monday.com API: Missing token", icon="❌")
        st.caption("Set `MONDAY_API_TOKEN` in Streamlit secrets or env vars.")

    if gemini_key:
        st.success("Gemini AI: Connected", icon="✅")
    else:
        st.error("Gemini AI: Missing API key", icon="❌")
        st.caption("Set `GEMINI_API_KEY` in Streamlit secrets or env vars.")

    st.divider()

    # Quick actions
    st.subheader("⚡ Quick Actions")

    if st.button("📊 Generate Leadership Update", use_container_width=True):
        st.session_state.pending_query = "Generate a comprehensive leadership update for this week."

    if st.button("💰 Revenue Overview", use_container_width=True):
        st.session_state.pending_query = "Give me a complete revenue overview across all sectors."

    if st.button("📈 Pipeline Health", use_container_width=True):
        st.session_state.pending_query = "How's our sales pipeline looking? Break it down by stage and sector."

    if st.button("🔄 Refresh Data", use_container_width=True):
        invalidate_cache()
        st.session_state.chat_session = None  # reset chat too
        st.toast("Cache cleared — next query will pull fresh data.", icon="🔄")

    if st.button("🗑️ Clear Chat", use_container_width=True):
        st.session_state.display_messages = []
        st.session_state.chat_session = None
        st.rerun()

    st.divider()

    # Example questions
    st.subheader("💡 Try asking")
    st.caption(
        "• How's our pipeline for energy sector?\n"
        "• Who are our top 5 customers by revenue?\n"
        "• What's the billing vs collection status?\n"
        "• Which sectors have the most stalled deals?\n"
        "• What's the data quality like across our boards?\n"
        "• Prepare a leadership update for this month"
    )

    st.divider()
    st.caption("Data from Monday.com · AI by Gemini")

# ────────────────────────────────────────────────────────────────────
# Main chat area
# ────────────────────────────────────────────────────────────────────

st.title("📊 Business Intelligence")
st.caption("Ask any business question about work orders, deals, pipeline, revenue, or operations.")

# Render chat history
for msg in st.session_state.display_messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ────────────────────────────────────────────────────────────────────
# Handle input (from chat box or sidebar buttons)
# ────────────────────────────────────────────────────────────────────

# Check for pending query from sidebar buttons
pending = st.session_state.pop("pending_query", None)
prompt = st.chat_input("Ask a business question…") or pending

if prompt:
    # Check prerequisites
    if not monday_token or not gemini_key:
        st.error(
            "⚠️ Both `MONDAY_API_TOKEN` and `GEMINI_API_KEY` must be set. "
            "See the sidebar for details."
        )
        st.stop()

    # Show user message
    st.session_state.display_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Call the agent
    with st.chat_message("assistant"):
        with st.spinner("Querying Monday.com and analyzing…"):
            try:
                response_text, updated_chat = run_agent_turn(
                    prompt, st.session_state.chat_session
                )
                st.session_state.chat_session = updated_chat
                st.markdown(response_text)

                st.session_state.display_messages.append(
                    {"role": "assistant", "content": response_text}
                )

            except Exception as e:
                import traceback
                tb_str = traceback.format_exc()
                # Print to terminal
                print("--- ERROR TRACEBACK ---")
                print(tb_str)
                print("-----------------------")

                error_msg = f"❌ **Error:** {str(e)}"
                st.error(error_msg)
                st.session_state.display_messages.append(
                    {"role": "assistant", "content": error_msg}
                )

                # Offer troubleshooting
                with st.expander("🔧 Troubleshooting"):
                    st.markdown(
                        "**Common issues:**\n"
                        "1. **API token expired** — regenerate in Monday.com > Admin > API\n"
                        "2. **Rate limit hit** — wait a moment and try again\n"
                        "3. **Board structure changed** — column IDs in `config.py` may need updating\n"
                        "4. **Gemini quota** — check your API usage at aistudio.google.com\n\n"
                        "**Traceback details:**"
                    )
                    st.code(tb_str, language="python")
