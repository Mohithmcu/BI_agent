# Skylark Drones — Monday.com BI Agent

A conversational AI agent that answers founder-level business intelligence queries by dynamically querying Monday.com boards containing Work Orders and Deals data.

**Live demo:** _(Add your Streamlit Cloud URL after deployment)_

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│           Streamlit Chat UI  (app.py)           │
│       Conversational interface + sidebar         │
├─────────────────────────────────────────────────┤
│         Gemini AI Agent  (agent.py)             │
│   Interprets query → calls tools → formats      │
│   response with caveats and insights             │
├─────────────────────────────────────────────────┤
│       Metrics & Analytics  (metrics.py)         │
│   9 analytics functions with data-quality        │
│   caveats: revenue, pipeline, sectors, billing   │
├─────────────────────────────────────────────────┤
│        Data Cleaning  (data_cleaning.py)        │
│   Flexible date parsing, text normalization,     │
│   numeric coercion, quality reporting            │
├─────────────────────────────────────────────────┤
│       Monday.com Client  (monday_client.py)     │
│   GraphQL API with cursor-based pagination       │
├─────────────────────────────────────────────────┤
│            Config  (config.py)                   │
│   Board IDs + column ID → friendly name maps     │
└─────────────────────────────────────────────────┘
```

### Data Flow

1. User types a business question in the chat interface
2. `agent.py` sends the query to Gemini with 10 available tools
3. Gemini decides which analytics function(s) to call and with what filters
4. `metrics.py` fetches live data from Monday.com via `monday_client.py`
5. `data_cleaning.py` normalizes dates, text, and numbers
6. Results (with data-quality caveats) flow back to Gemini
7. Gemini composes a clear, contextual answer with insights

---

## File Structure

```
companyproject/
├── app.py                  # Streamlit web UI (entry point)
├── agent.py                # Gemini tool-use agent
├── metrics.py              # Business analytics functions
├── data_cleaning.py        # Data normalization layer
├── monday_client.py        # Monday.com GraphQL client
├── config.py               # Board IDs + column mappings
├── test_pull.py            # Smoke test for data pipeline
├── requirements.txt        # Python dependencies
├── .gitignore
├── .streamlit/
│   └── secrets.toml        # API keys (template, not committed)
├── DECISION_LOG.md         # Design decisions & trade-offs
└── README.md               # This file
```

---

## Setup Instructions

### Prerequisites

- Python 3.10+
- A Monday.com account with API token
- A Google Gemini API key (free from [aistudio.google.com](https://aistudio.google.com))

### 1. Monday.com Board Setup

1. Import the two provided Excel files into Monday.com as separate boards:
   - **Work Order Tracker Data.xlsx** → "Work Order Tracker Data"
   - **Deal Funnel Data.xlsx** → "Deal funnel Data"

2. Get each board's ID from its URL (the number after `/boards/`):
   - Work Orders: `5030963344`
   - Deals: `5030963465`

3. Verify column IDs match `config.py` by running this query in monday.com's **API Playground** (profile picture → Developers → API Playground):
   ```graphql
   {
     boards(ids: [YOUR_BOARD_ID]) {
       columns { id title type }
     }
   }
   ```
   If IDs differ (e.g. you re-imported the boards), update the `WORK_ORDERS_COLUMNS` and `DEALS_COLUMNS` dicts in `config.py` to match.

4. Generate an API token: profile picture (bottom left) → **Developers** → **My Access Tokens** → **Generate**.

### 2. Local Development

```bash
# Clone the repo
git clone <your-repo-url>
cd companyproject

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export MONDAY_API_TOKEN="your_monday_api_token"
export GEMINI_API_KEY="your_gemini_api_key"

# Test the data pipeline
python test_pull.py

# Run the app
streamlit run app.py
```

### 3. Deploy to Streamlit Cloud

1. Push the repo to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect your GitHub repo, set `app.py` as the main file
4. Add secrets in **Settings → Secrets**:
   ```toml
   MONDAY_API_TOKEN = "your_monday_api_token"
   GEMINI_API_KEY = "your_gemini_api_key"
   ```
5. Deploy

> **Security note:** `.streamlit/secrets.toml` in this repo is a *template* — it must only ever contain placeholder text like `"your_monday_api_token"`, never real values. Real keys belong in your local environment variables and in Streamlit Cloud's Secrets dashboard, never in a committed or zipped file. `.gitignore` already excludes this file from git, but that doesn't protect a ZIP you hand-package for submission — double-check the file's contents before zipping the project.

---

## What the Agent Can Answer

| Category | Example Questions |
|----------|-------------------|
| **Revenue** | "What's our total revenue?" · "Revenue breakdown by sector" |
| **Pipeline** | "How's our pipeline for energy sector?" · "Deal funnel breakdown" |
| **Billing** | "What's our billing vs collection rate?" · "Outstanding receivables" |
| **Customers** | "Who are our top 5 customers?" · "How much does customer X owe?" |
| **Operations** | "How many projects are in progress?" · "Execution status overview" |
| **Cross-board** | "Compare sector performance across orders and deals" |
| **Leadership** | "Generate a leadership update" · "Prepare a weekly summary" |
| **Data Quality** | "How complete is our data?" · "Which fields have missing values?" |

---

## Tech Stack

| Component | Technology | Rationale |
|-----------|------------|-----------|
| LLM | Google Gemini 3.5 Flash Lite | Free tier, fast, excellent function-calling |
| Frontend | Streamlit | Fast to build, native chat UI, free cloud hosting |
| Data Source | Monday.com GraphQL API | Direct, real-time, read-only integration |
| Language | Python 3.10+ | Ecosystem (pandas, requests, Gemini SDK) |

---

## Key Design Decisions

See [DECISION_LOG.md](DECISION_LOG.md) for detailed rationale on:
- Tool-use agent vs RAG approach
- Live fetch vs caching strategy
- Column mapping approach
- Leadership update interpretation
