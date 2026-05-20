from datetime import datetime
from pathlib import Path

import streamlit as st
import pandas as pd
import numpy as np
import json
import feedparser
import plotly.express as px
import re
from typing import List, Dict, Optional

from narrative import Severity, SeverityMetrics, RawPost, ClassifiedPost, EventGroup, NewsFetcher, CommodityClassifier, EventGrouper

# Get the directory of the current script
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"

# ==========================================
# SESSION STATE INITIALIZATION
# ==========================================
state_keys = [
    "ing_shock_rules", "draft_rules", "raw_csv_context", 
    "ai_feed_data", "feed_asset", "draft_scenarios", 
    "confirmed_scenarios", "selected_scenario_idx", "logged_in", "username",
    "event_groups", "event_feed_asset", "total_articles_fetched"
]
for k in state_keys:
    if k not in st.session_state:
        if k == "logged_in":
            st.session_state[k] = False
        elif k == "username":
            st.session_state[k] = ""
        else:
            st.session_state[k] = "" if "rules" in k or k == "raw_csv_context" else None

# ==========================================
# DYNAMIC AI SCHEMA
# ==========================================
NEWS_ANALYSIS_SCHEMA = """
{
    "title": "Exact original title",
    "link": "Exact original link",
    "timestamp": "Exact original timestamp",
    "EventType": "Sanctions, Geopolitics, Shipping Disruption, Finance, or Macro",
    "Actor": "Initiating entity",
    "Target": "Receiving entity",
    "Sectors": ["List of affected sectors"],
    "Severity": Integer from 1 to 10
}
"""

# ==========================================
# ING BRAND STYLING
# ==========================================
ING_CUSTOM_CSS = """
<style>
    /* ING Brand Colors */
    :root {
        --ing-orange: #FF6200;
        --ing-orange-dark: #D95200;
        --ing-orange-light: #FF8533;
        --ing-grey-10: #F7F4F1;
        --ing-grey-20: #F1EDE9;
        --ing-grey-30: #A69F98;
        --ing-grey-40: #6C6763;
        --ing-grey-50: #403B3B;
        --ing-grey-60: #302C2C;
        --ing-grey-70: #201E1E;
        --ing-grey-80: #111010;
        --ing-green: #1E8700;
        --ing-success: #65FF39;
        --ing-error: #D95200;
        --ing-sky-10: #E4F5FF;
        --ing-sky-50: #BEE8FE;
    }
    
    /* Main App Background */
    .stApp {
        background-color: var(--ing-grey-10);
    }
    
    /* Header Styling */
    h1, h2, h3 {
        color: var(--ing-grey-80) !important;
        font-family: 'ING Me', 'Inter', sans-serif !important;
    }
    
    /* Primary Buttons */
    .stButton > button[kind="primary"] {
        background-color: var(--ing-orange) !important;
        color: white !important;
        border: none !important;
        border-radius: 8px !important;
        padding: 0.75rem 2rem !important;
        font-weight: 700 !important;
        font-size: 1rem !important;
        transition: all 0.3s ease !important;
        box-shadow: 0 2px 8px rgba(255, 98, 0, 0.25) !important;
        text-transform: uppercase !important;
        letter-spacing: 0.5px !important;
    }
    
    .stButton > button[kind="primary"]:hover {
        background-color: var(--ing-orange-dark) !important;
        box-shadow: 0 4px 12px rgba(255, 98, 0, 0.35) !important;
        transform: translateY(-1px) !important;
    }
    
    /* Secondary Buttons */
    .stButton > button {
        background-color: white !important;
        color: var(--ing-orange) !important;
        border: 2px solid var(--ing-orange) !important;
        border-radius: 8px !important;
        padding: 0.75rem 2rem !important;
        font-weight: 600 !important;
        font-size: 0.95rem !important;
        transition: all 0.3s ease !important;
    }
    
    .stButton > button:hover {
        background-color: var(--ing-orange) !important;
        color: white !important;
        transform: translateY(-1px) !important;
    }
    
    /* Login Page Specific */
    /* Login Page Specific */
    .login-page-wrapper {
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        min-height: 80vh;
    }
    
    .login-header {
        text-align: center;
        margin-bottom: 2rem;
    }
    
    .login-brand {
        color: var(--ing-orange);
        font-size: 3.5rem;
        font-weight: 700;
        margin-bottom: 0.5rem;
        letter-spacing: -1px;
    }
    
    .login-tagline {
        color: var(--ing-grey-40);
        font-size: 1.1rem;
        font-weight: 400;
        margin-bottom: 2rem;
    }
    
    /* Center login form with smaller width */
    .login-form-container {
        max-width: 360px;
        width: 100%;
        margin: 0 auto;
    }
    
    /* Input Fields */
    .stTextInput > div > div > input {
        border: 2px solid var(--ing-grey-20) !important;
        border-radius: 8px !important;
        padding: 0.85rem 1rem !important;
        font-size: 1rem !important;
        transition: all 0.3s ease !important;
        background: white !important;
    }
    
    .stTextInput > div > div > input:focus {
        border-color: var(--ing-orange) !important;
        box-shadow: 0 0 0 3px rgba(255, 98, 0, 0.15) !important;
        outline: none !important;
    }
    
    .stTextInput label {
        font-weight: 600 !important;
        color: var(--ing-grey-70) !important;
        font-size: 0.95rem !important;
    }
    
    /* Sidebar Styling - Slightly darker than main panel */
    .css-1d391kg, [data-testid="stSidebar"] {
        background: linear-gradient(180deg, var(--ing-grey-20) 0%, var(--ing-grey-30) 100%) !important;
        border-right: 2px solid var(--ing-grey-40) !important;
    }
    
    .css-1d391kg h1, .css-1d391kg h2, .css-1d391kg h3, .css-1d391kg h4,
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3, [data-testid="stSidebar"] h4 {
        color: var(--ing-grey-80) !important;
    }
    
    .css-1d391kg label, [data-testid="stSidebar"] label {
        color: var(--ing-grey-70) !important;
        font-weight: 600 !important;
    }
    
    /* Sidebar text areas and inputs */
    .css-1d391kg .stTextArea textarea,
    [data-testid="stSidebar"] .stTextArea textarea {
        background-color: white !important;
        border: 2px solid var(--ing-grey-30) !important;
        color: var(--ing-grey-80) !important;
    }
    
    .css-1d391kg .stTextInput input,
    [data-testid="stSidebar"] .stTextInput input {
        background-color: white !important;
        border: 2px solid var(--ing-grey-30) !important;
        color: var(--ing-grey-80) !important;
    }
    
    /* Sidebar expanders (View Rules section) */
    .css-1d391kg .streamlit-expanderHeader,
    [data-testid="stSidebar"] .streamlit-expanderHeader {
        background-color: white !important;
        border: 2px solid var(--ing-grey-30) !important;
        border-left: 4px solid var(--ing-orange) !important;
        color: var(--ing-grey-80) !important;
    }
    
    .css-1d391kg .streamlit-expanderContent,
    [data-testid="stSidebar"] .streamlit-expanderContent {
        background-color: white !important;
        border: 1px solid var(--ing-grey-30) !important;
        border-top: none !important;
    }
    
    /* Sidebar captions */
    .css-1d391kg .stCaption,
    [data-testid="stSidebar"] .stCaption {
        color: var(--ing-grey-60) !important;
    }
    
    /* Sidebar success/info messages */
    .css-1d391kg .stSuccess,
    [data-testid="stSidebar"] .stSuccess {
        background-color: rgba(30, 135, 0, 0.1) !important;
        color: var(--ing-grey-80) !important;
    }
    
    .css-1d391kg .stInfo,
    [data-testid="stSidebar"] .stInfo {
        background-color: rgba(190, 232, 254, 0.2) !important;
        color: var(--ing-grey-80) !important;
        border-left-color: var(--ing-sky-50) !important;
    }
    
    /* Sidebar file uploader */
    .css-1d391kg .stFileUploader,
    [data-testid="stSidebar"] .stFileUploader {
        background-color: white !important;
        border: 2px dashed var(--ing-grey-30) !important;
    }
    
    /* Sidebar selectbox */
    .css-1d391kg .stSelectbox [data-baseweb="select"],
    [data-testid="stSidebar"] .stSelectbox [data-baseweb="select"] {
        background-color: white !important;
    }
    
    .css-1d391kg .stSelectbox label,
    [data-testid="stSidebar"] .stSelectbox label {
        color: var(--ing-grey-70) !important;
        font-weight: 600 !important;
    }
    
    /* Sidebar number input */
    .css-1d391kg .stNumberInput input,
    [data-testid="stSidebar"] .stNumberInput input {
        background-color: white !important;
        border: 2px solid var(--ing-grey-30) !important;
        color: var(--ing-grey-80) !important;
    }
    
    /* Sidebar horizontal rule */
    .css-1d391kg hr,
    [data-testid="stSidebar"] hr {
        border-color: var(--ing-grey-40) !important;
    }
    
    /* Sidebar button styling */
    .css-1d391kg .stButton button,
    [data-testid="stSidebar"] .stButton button {
        font-weight: 700 !important;
    }
    
    /* Sidebar Accent Bar */
    .css-1d391kg::before, [data-testid="stSidebar"]::before {
        content: '';
        position: absolute;
        left: 0;
        top: 0;
        width: 4px;
        height: 100%;
        background: var(--ing-orange);
    }
    
    /* Clean main content spacing */
    .main .block-container {
        padding-top: 3rem;
        padding-bottom: 3rem;
        max-width: 1400px;
    }
    
    /* Remove default streamlit padding on mobile */
    @media (max-width: 768px) {
        .main .block-container {
            padding-left: 1rem;
            padding-right: 1rem;
        }
    }
    
    /* Expander */
    .streamlit-expanderHeader {
        background-color: var(--ing-grey-10) !important;
        border: 1px solid var(--ing-grey-20) !important;
        border-left: 4px solid var(--ing-orange) !important;
        border-radius: 8px !important;
        color: var(--ing-grey-80) !important;
        font-weight: 600 !important;
        padding: 0.75rem 1rem !important;
    }
    
    .streamlit-expanderHeader:hover {
        border-left-color: var(--ing-orange-dark) !important;
        background-color: var(--ing-grey-20) !important;
    }
    
    /* Metrics */
    [data-testid="stMetricValue"] {
        color: var(--ing-orange) !important;
        font-size: 2.5rem !important;
        font-weight: 700 !important;
    }
    
    /* Data Editor */
    .stDataFrame {
        border: 1px solid var(--ing-grey-20) !important;
        border-radius: 8px !important;
    }
    
    /* Success/Warning/Error Messages */
    .stSuccess {
        background-color: rgba(30, 135, 0, 0.08) !important;
        border-left: 4px solid var(--ing-green) !important;
        border-radius: 8px !important;
        padding: 1rem !important;
    }
    
    .stWarning {
        background-color: rgba(255, 98, 0, 0.08) !important;
        border-left: 4px solid var(--ing-orange) !important;
        border-radius: 8px !important;
        padding: 1rem !important;
    }
    
    .stError {
        background-color: rgba(217, 82, 0, 0.08) !important;
        border-left: 4px solid var(--ing-error) !important;
        border-radius: 8px !important;
        padding: 1rem !important;
    }
    
    .stInfo {
        background-color: rgba(190, 232, 254, 0.15) !important;
        border-left: 4px solid var(--ing-sky-50) !important;
        border-radius: 8px !important;
        padding: 1rem !important;
    }
    
    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 4px;
        background-color: var(--ing-grey-10);
        padding: 0.5rem;
        border-radius: 10px;
    }
    
    .stTabs [data-baseweb="tab"] {
        background-color: transparent;
        border-radius: 8px;
        padding: 0.75rem 1.5rem;
        color: var(--ing-grey-70);
        font-weight: 600;
        transition: all 0.3s ease;
    }
    
    .stTabs [data-baseweb="tab"]:hover {
        background-color: rgba(255, 98, 0, 0.1);
    }
    
    .stTabs [aria-selected="true"] {
        background-color: var(--ing-orange) !important;
        color: white !important;
        box-shadow: 0 2px 8px rgba(255, 98, 0, 0.25);
    }
    
    /* Download Button */
    .stDownloadButton > button {
        background-color: var(--ing-green) !important;
        color: white !important;
        border: none !important;
        font-weight: 600 !important;
    }
    
    .stDownloadButton > button:hover {
        background-color: #0F4400 !important;
    }
    
    /* Selectbox and other inputs */
    .stSelectbox [data-baseweb="select"],
    .stNumberInput input {
        border-radius: 8px;
    }
    
    /* Plotly Charts */
    .js-plotly-plot {
        border-radius: 8px;
    }
    
    /* File uploader */
    .stFileUploader {
        border-radius: 8px;
    }
    
    /* Spinner */
    .stSpinner > div {
        border-top-color: var(--ing-orange) !important;
    }
</style>
"""

# ==========================================
# LOCATION & TICKER MAPPINGS
# ==========================================
LOCATION_MAP = {'AMS': 'AMS - Amsterdam', 'LON': 'LON - London', 'NY': 'NY - New York', 'SIN': 'SIN - Singapore'}
REVERSE_LOCATION_MAP = {v: k for k, v in LOCATION_MAP.items()}

TICKER_MAP = {'Gold': 'GC=F', 'EU Gas': 'TTF=F', 'Copper': 'HG=F', 'Brent related': 'BZ=F', 'Aluminium': 'ALI=F', 'US Gas South': 'NG=F', 'Jet Fuel': 'CL=F', 'Nickel': 'NI=F', 'Diesel': 'HO=F', 'Zinc': 'ZN=F'}
EQ_TICKER_MAP = {'EURO STOXX 50': 'FEZ', 'S&P 500': 'SPY', 'FTSE 100': 'EWU', 'DAX': 'EWG', 'Nikkei 225': 'EWJ'}

# ==========================================
# DATA HELPERS
# ==========================================
def extract_json_from_response(response_text):
    """Safely extracts a JSON array from an LLM response."""
    text = response_text.strip()
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    text = text.replace("```json", "").replace("```", "")
    return json.loads(text)

def get_scenario_table(scenario_shocks, asset_class):
    """Formats the raw JSON shocks into a clean Pandas DataFrame."""
    records = []
    for rf, val in scenario_shocks.items():
        if asset_class == "Commodities":
            ticker = TICKER_MAP.get(rf, "N/A")
        elif asset_class == "Equities":
            ticker = EQ_TICKER_MAP.get(rf, "N/A")
        else:
            ticker = rf
            
        if isinstance(val, str):
            val = val.replace("%", "").strip()
        try:
            val = float(val)
            records.append({
                "Ticker": rf,
                "Shock (%)": f"{val*100:+.2f}%"
            })
        except:
            pass
    return pd.DataFrame(records)

def load_commodity_data_from_csv():
    # csv_path = DATA_DIR / "cmd_delta_vega_location_underlying 1.csv"
    csv_path = DATA_DIR / "sensi_20260413.csv"
    if not csv_path.exists():
        return pd.DataFrame({'Location': ['NY', 'LON', 'AMS'], 'Underlying': ['Brent related', 'Gold', 'EU Gas'], 'Ticker': ['BZ=F', 'GC=F', 'TTF=F'], 'CMD Delta': [5000000, -2000000, 3000000], 'CMD Vega': [15000, 5000, 25000]}), None
    
    df = pd.read_csv(csv_path)
    as_of_date = df['as_of_date'].iloc[0] if 'as_of_date' in df.columns else None
    
    df.rename(columns={'trading_location': 'Location', 'commodity_subtype': 'Underlying', 'delta': 'CMD Delta', 'vega': 'CMD Vega'}, inplace=True)
    df['CMD Vega'] = df['CMD Vega'].fillna(0)
    
    df_agg = df.groupby(['Location', 'Underlying']).agg({'CMD Delta': 'sum', 'CMD Vega': 'sum'}).reset_index()
    
    result = pd.DataFrame({
        'Location': df_agg['Location'].values,
        'Underlying': df_agg['Underlying'].values,
        'Ticker': [TICKER_MAP.get(str(u), 'CL=F') for u in df_agg['Underlying'].values],
        'CMD Delta': df_agg['CMD Delta'].values,
        'CMD Vega': df_agg['CMD Vega'].values
    })
    return result, as_of_date

def load_equities_data_from_csv():
    csv_path = DATA_DIR / "eq_delta_region.csv"
    if not csv_path.exists():
        return pd.DataFrame({'Location': ['NY', 'LON'], 'Underlying': ['S&P 500', 'EURO STOXX 50'], 'Ticker': ['SPY', 'FEZ'], 'EQ Delta': [10000000, 5000000]}), None
    
    df = pd.read_csv(csv_path)
    df['Underlying'] = df['Underlying'].astype(str)
    df = df[(df['Trading Location'] != 'Total') & (df['Underlying'] != 'Total')]
    
    df_agg = df.groupby(['Trading Location', 'Underlying'])['EQ Delta'].sum().reset_index()
    result = pd.DataFrame({'Location': df_agg['Trading Location'].values, 'Underlying': df_agg['Underlying'].values, 'Ticker': [EQ_TICKER_MAP.get(str(u), 'SPY') for u in df_agg['Underlying'].values], 'EQ Delta': df_agg['EQ Delta'].values})
    return result, None

# ==========================================
# GCP VERTEX AI SETUP 
# ==========================================
USE_MOCK_AI = False

if not USE_MOCK_AI:
    import vertexai
    from vertexai.generative_models import GenerativeModel
    PROJECT_ID = "turing-seeker-496208-q5"
    LOCATION = "europe-west4" 
    
    @st.cache_resource
    def load_model():
        vertexai.init(project=PROJECT_ID, location=LOCATION)
        return GenerativeModel("gemini-2.5-flash")
    model = load_model()

# ==========================================
# ASSET CONFIGURATION
# ==========================================
_cmd_data, _cmd_as_of_date = load_commodity_data_from_csv()
_eq_data, _eq_as_of_date = load_equities_data_from_csv()

ASSET_CONFIG = {
    "Commodities": {"metric": "CMD Delta ($)", "unit_label": "%", "data": _cmd_data, "as_of_date": _cmd_as_of_date, "value_column": "CMD Delta", "prompt_instruction": "Output shocks as decimal percentages (e.g., 0.20 for a 20% spike, -0.10 for 10% drop)."},
    "Equities": {"metric": "EQ Delta ($)", "unit_label": "%", "data": _eq_data, "as_of_date": _eq_as_of_date, "value_column": "EQ Delta", "prompt_instruction": "Output shocks as decimal percentages (e.g., -0.15)."},
    "Interest Rates": {"metric": "DV01 ($)", "unit_label": "bps", "data": pd.DataFrame({"Location": ["NY", "NY", "NY"], "Underlying": ["US_10Y_Yield", "US_2Y_Yield", "VIX_Volatility"], "Ticker": ["^TNX", "^IRX", "^VIX"], "DV01": [-100000, -80000, 20000]}), "as_of_date": None, "value_column": "DV01", "prompt_instruction": "Output shocks as integer basis points (e.g., 50)."}
}

# ==========================================
# AI NEWS FETCHING
# ==========================================
# --- NEWS AGGREGATOR ---
@st.cache_data(ttl=300, show_spinner=False)
def fetch_and_classify_news(asset_class: str, max_posts: int = 30) -> List[ClassifiedPost]:
    """Fetch news from all sources and classify them"""
    fetcher = NewsFetcher()
    all_posts = []

    # Fetch from multiple sources
    queries = {
        "Commodities": ['commodity prices', 'oil prices OPEC', 'gold silver prices',
            'wheat corn agricultural', 'energy crisis pipeline',
            'sanctions embargo trade', 'mining production'],
        "Equities": ['stock market', 'equity markets', 'S&P 500', 'global stocks'],
        "Interest Rates": ['interest rates', 'federal reserve', 'treasury yields', 'central bank']
    }

    for query in queries.get(asset_class, queries["Commodities"]):
        all_posts.extend(fetcher.fetch_google_news(query, "4h"))

    if asset_class == "Commodities":
        all_posts.extend(fetcher.fetch_oilprice_news())
        all_posts.extend(fetcher.fetch_investing_com_news())

    all_posts.extend(fetcher.fetch_yahoo_finance(asset_class))

    # Deduplicate
    seen_titles = set()
    unique_posts = []
    for post in all_posts:
        normalized = post.title.lower().strip()[:50]
        if normalized not in seen_titles:
            seen_titles.add(normalized)
            unique_posts.append(post)

    # Pre-filter
    filtered_posts = [p for p in unique_posts if CommodityClassifier.quick_filter(p)]

    return filtered_posts[:max_posts]


def classify_and_group_news(raw_posts: List[RawPost], ai_model, max_classify: int = 20) -> List[EventGroup]:
    """Classify posts and group by event"""
    classified = []

    for post in raw_posts[:max_classify]:
        classified_post = CommodityClassifier.classify_with_ai(post, ai_model)
        if classified_post and classified_post.is_commodity_related and classified_post.relevance_score >= 0.3:
            classified.append(classified_post)

    if not classified:
        return []

    return EventGrouper.group_posts(classified, ai_model)


# ==========================================
# UI LAYOUT & SIDEBAR
# ==========================================
st.set_page_config(layout="wide", page_title="StressLess ING", page_icon="🦁")

# Apply ING Custom CSS
st.markdown(ING_CUSTOM_CSS, unsafe_allow_html=True)

# ==========================================
# LOGIN PAGE
# ==========================================
if not st.session_state.logged_in:
    st.markdown('<div class="login-page-wrapper">', unsafe_allow_html=True)
    
    # Brand Header
    st.markdown('''<div class="login-header">
        <div class="login-brand">🦁 StressLess ING</div>
        <div class="login-tagline">Risk Intelligence Platform</div>
    </div>''', unsafe_allow_html=True)
    
    # Login Form
    st.markdown('<div class="login-form-container">', unsafe_allow_html=True)
    
    with st.form("login_form"):
        username = st.text_input("Username", placeholder="Enter your username", key="login_username")
        password = st.text_input("Password", type="password", placeholder="Enter your password", key="login_password")
        
        st.markdown('<br>', unsafe_allow_html=True)
        submit_button = st.form_submit_button("SIGN IN", use_container_width=True, type="primary")
        
        if submit_button:
            # Fake login - accepts any non-empty username/password
            if username and password:
                st.session_state.logged_in = True
                st.session_state.username = username
                st.rerun()
            else:
                st.error("⚠ Please enter both username and password")
    
    st.markdown('<p style="text-align: center; margin-top: 1.5rem; color: #6C6763; font-size: 0.85rem;">Demo Mode • Use any credentials to login</p>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)  # Close login-form-container
    st.markdown('</div>', unsafe_allow_html=True)  # Close login-page-wrapper
    
    # Stop execution here if not logged in
    st.stop()

# ==========================================
# MAIN DASHBOARD (Only visible after login)
# ==========================================

# User Info and Logout in Sidebar
st.sidebar.markdown(f"<div style='margin-bottom: 1rem;'>"
                   f"<div style='color: #6C6763; font-size: 0.85rem; margin-bottom: 0.25rem;'>Logged in as</div>"
                   f"<div style='color: var(--ing-grey-80); font-size: 1.1rem; font-weight: 700;'>👤 {st.session_state.username}</div>"
                   f"</div>", unsafe_allow_html=True)

if st.sidebar.button("LOGOUT", use_container_width=True, key="logout_btn"):
    st.session_state.logged_in = False
    st.session_state.username = ""
    st.rerun()

st.sidebar.markdown("---")

# --- Centered Main Headers ---
st.markdown("<h1 style='text-align: center; font-size: 3.2rem; font-weight: 700; margin-bottom: 0.5rem; color: #FF6200;'>🦁 StressLess ING</h1>", unsafe_allow_html=True)

st.sidebar.markdown("#### Asset Class")
selected_asset = st.sidebar.selectbox("Select asset class", list(ASSET_CONFIG.keys()), label_visibility="collapsed")
config = ASSET_CONFIG[selected_asset]
df_portfolio = config["data"]

st.sidebar.markdown("#### Location")
locations = ["AMS", "NYC", "LON", "SGP"]
# Default to LON for Commodities
default_location_idx = locations.index("LON") if selected_asset == "Commodities" else 0
selected_location = st.sidebar.selectbox("Select location", locations, index=default_location_idx, label_visibility="collapsed")

# Dynamic As of Date
if config.get("as_of_date"):
    st.markdown(f"<h4 style='text-align: center; color: gray;'>You are using the {selected_asset} Portfolio as of {config['as_of_date']}</h4>", unsafe_allow_html=True)
else:
    st.markdown(f"<h4 style='text-align: center; color: gray;'>You are using the {selected_asset} Portfolio</h4>", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# Sidebar: Teach AI
st.sidebar.markdown("---")
st.sidebar.subheader("AI Framework Configuration")
st.sidebar.caption("Upload historical shocks to set AI guardrails")
uploaded_csv = st.sidebar.file_uploader("Upload CSV", type=["csv"], label_visibility="collapsed")

if st.sidebar.button("ANALYZE CSV", use_container_width=True, key="analyze_csv_btn"):
    if uploaded_csv:
        with st.spinner("Analyzing CSV..."):
            df_rules = pd.read_csv(uploaded_csv)
            data_string = str(df_rules.head(15).to_dict('records'))
            st.session_state.raw_csv_context = data_string
            
            prompt = f"Analyze this historical shock data: {data_string}. Write exactly 3 concise, plain text bullet points stating the typical shock magnitudes. Start each line with a '-'. Do not use bolding or asterisks."
            st.session_state.draft_rules = "1. Energy shocks cap at 20%\n2. Metals drop 10%\n3. Follow 2022 baseline" if USE_MOCK_AI else model.generate_content(prompt).text
            st.rerun()

if st.session_state.draft_rules and not st.session_state.ing_shock_rules:
    st.sidebar.markdown("### Review Draft Rules")
    edited_draft = st.sidebar.text_area("AI Proposed Rules", value=st.session_state.draft_rules, height=120, label_visibility="collapsed")
    refine = st.sidebar.text_input("Adjustment instructions", placeholder="e.g., Make limits stricter")
    col_a, col_b = st.sidebar.columns(2)
    if col_a.button("REFINE", key="refine_btn"):
        if refine:
            st.session_state.draft_rules = model.generate_content(f"Rewrite these rules: {edited_draft}. Apply this instruction: {refine}. Output plain text bullets only.").text
            st.rerun()
    if col_b.button("CONFIRM", type="primary", key="confirm_rules_btn"):
        st.session_state.ing_shock_rules = edited_draft
        st.session_state.draft_rules = ""
        st.rerun()

if st.session_state.ing_shock_rules:
    st.sidebar.success("✓ Active Rulebook")
    with st.sidebar.expander("View Rules", expanded=False):
        st.info(st.session_state.ing_shock_rules)
    if st.sidebar.button("CLEAR FRAMEWORK", key="clear_framework_btn"):
        st.session_state.ing_shock_rules = ""
        st.rerun()

# ==========================================
# MAIN DASHBOARD - EVENT-BASED NEWS FEED
# ==========================================
st.markdown("### Live Market Intelligence")
st.caption("AI-analyzed market events grouped by topic and sorted by severity")

# Initialize session state for event groups
if "event_groups" not in st.session_state:
    st.session_state.event_groups = None
if "event_feed_asset" not in st.session_state:
    st.session_state.event_feed_asset = None

# Refresh button
col_refresh, col_status = st.columns([1, 4])
with col_refresh:
    refresh_btn = st.button("🔄 REFRESH FEED", use_container_width=True)

# Fetch and process news if needed
if refresh_btn or st.session_state.event_feed_asset != selected_asset or st.session_state.event_groups is None:
    with st.spinner("🔍 Fetching and analyzing market events..."):
        raw_posts = fetch_and_classify_news(selected_asset, max_posts=30)

        # Store total articles count
        st.session_state.total_articles_fetched = len(raw_posts)

        if raw_posts and not USE_MOCK_AI:
            st.session_state.event_groups = classify_and_group_news(raw_posts, model, max_classify=20)
        else:
            # Mock data for testing
            st.session_state.event_groups = []

        st.session_state.event_feed_asset = selected_asset

# Display stats
with col_status:
    if st.session_state.event_groups:
        total_articles = st.session_state.get("total_articles_fetched", 0)
        num_events = len(st.session_state.event_groups[:10])
        total_grouped = sum(len(e.posts) for e in st.session_state.event_groups[:10])

        st.markdown(f"""
        <div style="display: flex; gap: 20px; align-items: center; padding: 8px 0;">
            <span style="background: var(--ing-grey-20); padding: 6px 12px; border-radius: 6px;">
                📰 <strong>{total_articles}</strong> articles searched
            </span>
            <span style="background: var(--ing-grey-20); padding: 6px 12px; border-radius: 6px;">
                📂 <strong>{num_events}</strong> events identified
            </span>
            <span style="background: var(--ing-grey-20); padding: 6px 12px; border-radius: 6px;">
                ✅ <strong>{total_grouped}</strong> relevant articles grouped
            </span>
        </div>
        """, unsafe_allow_html=True)

# Display event groups
if st.session_state.event_groups:
    for idx, event in enumerate(st.session_state.event_groups[:10]):
        # Severity styling
        severity_config = {
            'CRITICAL': {'icon': '🔴', 'color': '#D95200', 'bg': 'rgba(217, 82, 0, 0.08)'},
            'HIGH': {'icon': '🟠', 'color': '#FF6200', 'bg': 'rgba(255, 98, 0, 0.08)'},
            'MEDIUM': {'icon': '🟡', 'color': '#FFA500', 'bg': 'rgba(255, 165, 0, 0.08)'},
            'LOW': {'icon': '🟢', 'color': '#1E8700', 'bg': 'rgba(30, 135, 0, 0.08)'},
            'INFO': {'icon': '🔵', 'color': '#0066CC', 'bg': 'rgba(0, 102, 204, 0.08)'}
        }
        sev_style = severity_config.get(event.severity, severity_config['INFO'])

        # Event header with key info visible
        header_html = f"""
        <div style="display: flex; align-items: center; gap: 12px;">
            <span style="font-size: 1.5rem;">{sev_style['icon']}</span>
            <div style="flex-grow: 1;">
                <span style="font-weight: 700; font-size: 1.1rem;">{event.event_name}</span>
                <span style="margin-left: 12px; padding: 2px 8px; background: {sev_style['bg']}; 
                       border-radius: 4px; font-size: 0.8rem; color: {sev_style['color']}; font-weight: 600;">
                    {event.severity}
                </span>
            </div>
            <span style="color: #6C6763; font-size: 0.85rem; background: var(--ing-grey-20); 
                   padding: 4px 10px; border-radius: 4px;">{event.event_type}</span>
        </div>
        """

        with st.expander(
                f"{sev_style['icon']} **{event.event_name}** | {event.event_type} | Severity: {event.severity} | 📰 {len(event.posts)} articles",
                expanded=False):
            # Event details container
            st.markdown(f"""
            <div style="border-left: 4px solid {sev_style['color']}; padding-left: 16px; margin-bottom: 16px;">
                <p style="font-size: 1rem; line-height: 1.6; margin-bottom: 12px;">{event.summary}</p>
            </div>
            """, unsafe_allow_html=True)

            # Key information in columns
            col1, col2, col3 = st.columns(3)

            with col1:
                st.markdown("**📊 Asset Types**")
                if event.asset_types:
                    st.markdown(", ".join(event.asset_types))
                else:
                    st.markdown("*N/A*")
                st.markdown("**🎯 Sub-classes**")
                if event.asset_subclasses:
                    st.markdown(", ".join(event.asset_subclasses))
                else:
                    st.markdown("*N/A*")

            with col2:
                st.markdown("**🎭 Actors**")
                if event.actors:
                    st.markdown(", ".join(event.actors))
                else:
                    st.markdown("*N/A*")

                st.markdown("**🎯 Targets**")
                if event.targets:
                    st.markdown(", ".join(event.targets))
                else:
                    st.markdown("*N/A*")

            with col3:
                st.markdown("**🌍 Regions**")
                if event.regions:
                    st.markdown(", ".join(event.regions))
                else:
                    st.markdown("*N/A*")

            # Severity Metrics
            if event.severity_metrics:
                st.markdown("---")
                st.markdown("**📈 Quantified Impact Metrics**")

                metrics_col1, metrics_col2, metrics_col3 = st.columns(3)
                m = event.severity_metrics

                with metrics_col1:
                    if m.supply_loss_mbd is not None:
                        st.metric("Supply Loss (Oil)", f"{m.supply_loss_mbd:.2f} mbd")
                    if m.supply_loss_bcf is not None:
                        st.metric("Supply Loss (Gas)", f"{m.supply_loss_bcf:.2f} bcf/day")

                with metrics_col2:
                    if m.demand_change_pct is not None:
                        st.metric("Demand Change", f"{m.demand_change_pct:+.1f}%")
                    if m.shipping_disruption_pct is not None:
                        st.metric("Shipping Impact", f"{m.shipping_disruption_pct:.1f}%")

                with metrics_col3:
                    if m.duration_range:
                        st.metric("Duration Est.", m.duration_range)
                    elif m.duration_days:
                        st.metric("Duration Est.", f"{m.duration_days} days")

                    # Confidence bar
                    conf_pct = int(m.confidence * 100)
                    st.markdown(f"**Confidence:** {conf_pct}%")
                    st.progress(m.confidence)

                if m.confidence_rationale:
                    st.caption(f"📝 {m.confidence_rationale}")

            # Source articles
            st.markdown("---")
            st.markdown(f"**📰 Contributing Sources ({len(event.posts)} articles)**")

            for j, post in enumerate(event.posts, 1):
                source_info = f"[{post.raw_post.source_platform}] {post.raw_post.source_name}"
                rel_score = f"Relevance: {post.relevance_score:.0%}"

                st.markdown(f"""
                <div style="padding: 8px 12px; margin: 4px 0; background: var(--ing-grey-10); 
                     border-radius: 6px; border-left: 3px solid {sev_style['color']};">
                    <div style="font-weight: 600; margin-bottom: 4px;">
                        {j}. {post.raw_post.title[:80]}{'...' if len(post.raw_post.title) > 80 else ''}
                    </div>
                    <div style="font-size: 0.85rem; color: #6C6763;">
                        {source_info} | {rel_score} | 
                        <a href="{post.raw_post.link}" target="_blank" style="color: #FF6200;">Read Article →</a>
                    </div>
                </div>
                """, unsafe_allow_html=True)

else:
    st.info("📭 No market events found. Click 'Refresh Feed' to fetch latest news.")

# Store event groups for scenario generation
if st.session_state.event_groups:
    st.session_state.ai_feed_data = [
        {
            "title": e.event_name,
            "summary": e.summary,
            "severity": e.severity,
            "event_type": e.event_type,
            "asset_types": e.asset_types,
            "asset_subclasses": e.asset_subclasses,
            "actors": e.actors,
            "targets": e.targets,
            "regions": e.regions,
            "article_count": len(e.posts),
            "severity_metrics": {
                "supply_loss_mbd": e.severity_metrics.supply_loss_mbd if e.severity_metrics else None,
                "supply_loss_bcf": e.severity_metrics.supply_loss_bcf if e.severity_metrics else None,
                "shipping_disruption_pct": e.severity_metrics.shipping_disruption_pct if e.severity_metrics else None,
                "demand_change_pct": e.severity_metrics.demand_change_pct if e.severity_metrics else None,
                "duration_range": e.severity_metrics.duration_range if e.severity_metrics else None,
                "confidence": e.severity_metrics.confidence if e.severity_metrics else None,
            } if e.severity_metrics else None
        }
        for e in st.session_state.event_groups[:10]
    ]

# ==========================================
# WIDE SCENARIO DESIGNER
# ==========================================
st.write("---")
st.markdown("<h2 style='text-align: center; font-size: 2.5rem; font-weight: 700;'>Scenario Designer</h2>", unsafe_allow_html=True)
st.markdown("<h4 style='text-align: center; color: #6C6763; margin-bottom: 30px; font-weight: 400;'>Instruct the AI to construct quantitative shocks based on a qualitative narrative</h4>", unsafe_allow_html=True)

# Prefill with live news headlines
# Prefill with event-based market intelligence
default_news_text = ""
if st.session_state.event_groups:
    event_summaries = []
    for event in st.session_state.event_groups[:10]:
        # Build event context string
        metrics_str = ""
        if event.severity_metrics:
            m = event.severity_metrics
            metrics_parts = []
            if m.supply_loss_mbd is not None:
                metrics_parts.append(f"Supply impact: {m.supply_loss_mbd} mbd")
            if m.supply_loss_bcf is not None:
                metrics_parts.append(f"Gas supply: {m.supply_loss_bcf} bcf/d")
            if m.shipping_disruption_pct is not None:
                metrics_parts.append(f"Shipping disruption: {m.shipping_disruption_pct}%")
            if m.demand_change_pct is not None:
                metrics_parts.append(f"Demand change: {m.demand_change_pct}%")
            if m.duration_range:
                metrics_parts.append(f"Duration: {m.duration_range}")
            if metrics_parts:
                metrics_str = f" | Impact: {', '.join(metrics_parts)}"

        regions_str = f" | Regions: {', '.join(event.regions)}" if event.regions else ""
        assets_str = f" | Assets: {', '.join(event.asset_subclasses[:3])}" if event.asset_subclasses else ""

        event_summaries.append(
            f"- [{event.severity}] {event.event_name} ({event.event_type}){regions_str}{assets_str}{metrics_str}"
        )

    default_news_text = f"""Live Market Events ({len(st.session_state.event_groups[:10])} events from {st.session_state.get('total_articles_fetched', 0)} articles):
{chr(10).join(event_summaries)}

Event Details:
""" + "\n".join([f"• {e.event_name}: {e.summary}" for e in st.session_state.event_groups[:5]])

col_text, col_settings = st.columns([3, 1])
with col_text:
    st.markdown("#### Insert Your Prompt")
    news_text = st.text_area("Enter scenario description", value=default_news_text, height=130, label_visibility="collapsed", help="Edit or clear to customize your prompt")
with col_settings:
    st.markdown("<br><br>", unsafe_allow_html=True)
    num_scenarios = st.number_input("Variants", min_value=1, max_value=3, value=2)
    gen_btn = st.button("GENERATE SCENARIOS", type="primary", use_container_width=True)

# ==========================================
# SCENARIO GENERATION & HITL
# ==========================================
all_underlyings = df_portfolio['Underlying'].unique().tolist()

if gen_btn:
    with st.spinner(f"AI architecting {num_scenarios} scenarios..."):
        rules_ctx = f"CRITICAL LIMITS (ING FRAMEWORK): {st.session_state.ing_shock_rules}" if st.session_state.ing_shock_rules else ""
        live_news_ctx = json.dumps([{"title": n.get("title", ""), "Severity": n.get("Severity", 1)} for n in st.session_state.ai_feed_data]) if st.session_state.ai_feed_data else "None"
        
        # Use news_text if provided, otherwise use live news and rules as narrative
        if not news_text:
            news_text = f"Based on current market conditions from live news feed and uploaded historical shock patterns, generate realistic stress scenarios."
        
        prompt = f"""
        Act as Chief Risk Officer. 
        User Narrative: "{news_text}"
        Recent Live Market News context: {live_news_ctx}
        
        {rules_ctx}
        
        Create {num_scenarios} distinct stress scenario variants. {config['prompt_instruction']}
        ALL shock values MUST be valid numerical floats (e.g. 0.25), NOT strings. Do not include the '%' symbol.
        
        CRITICAL RULE: You MUST generate a shock value for EVERY SINGLE ONE of the following portfolio underlyings: {all_underlyings}. 
        If an asset is unaffected by the narrative/news, assign it a shock of 0.0.
        
        Respond ONLY with a JSON array:
        [{{"scenario_name": "Name", "rationale": "Why", "shocks": {{"Underlying1": 0.15, "Underlying2": -0.05}}}}]
        """
        try:
            resp = model.generate_content(prompt).text
            st.session_state.draft_scenarios = extract_json_from_response(resp)
            st.session_state.confirmed_scenarios = None
        except Exception as e:
            st.error(f"Failed to parse initial AI output. Error: {e}")

# HITL Loop for Scenarios
if st.session_state.draft_scenarios and not st.session_state.confirmed_scenarios:
    st.warning("⚠ Review and refine AI-generated scenarios")
    
    tabs = st.tabs([s["scenario_name"] for s in st.session_state.draft_scenarios])
    for i, tab in enumerate(tabs):
        with tab:
            st.write(f"**Rationale:** {st.session_state.draft_scenarios[i]['rationale']}")
            df_shocks = get_scenario_table(st.session_state.draft_scenarios[i]['shocks'], selected_asset)
            st.dataframe(df_shocks, use_container_width=True, hide_index=True)
            
    hitl_col1, hitl_col2 = st.columns([3, 1])
    with hitl_col1:
        scenario_feedback = st.text_input("Refinement instructions", placeholder="e.g., 'Make the Severe variant push Brent to +25%'")
    with hitl_col2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("APPLY REFINEMENT", use_container_width=True, key="refine_scenario_btn") and scenario_feedback:
            with st.spinner("AI is applying your refinements..."):
                refine_prompt = f"""
                You previously drafted these scenarios: {json.dumps(st.session_state.draft_scenarios)}
                The Risk Manager provided this feedback: "{scenario_feedback}"
                
                Update the scenarios based strictly on this feedback. 
                CRITICAL RULE: Return ALL variants in the array.
                CRITICAL RULE: {config['prompt_instruction']}
                CRITICAL RULE: ALL shock values MUST be valid numerical floats. Do not use strings.
                CRITICAL RULE: You MUST maintain shock values for ALL of these underlyings: {all_underlyings}.
                
                Respond ONLY with a valid JSON array matching the structure.
                """
                try:
                    resp = model.generate_content(refine_prompt).text
                    st.session_state.draft_scenarios = extract_json_from_response(resp)
                    st.rerun()
                except Exception:
                    st.error("Refinement failed. Try rephrasing.")
                    
        if st.button("CONFIRM & RUN SIMULATION", type="primary", use_container_width=True, key="confirm_sim_btn"):
            st.session_state.confirmed_scenarios = st.session_state.draft_scenarios
            st.rerun()

# ==========================================
# NUMERIC ENGINE EXECUTION
# ==========================================
if st.session_state.confirmed_scenarios:
    st.write("---")
    st.header("Execution Engine")
    
    scenario_names = [s["scenario_name"] for s in st.session_state.confirmed_scenarios]
    active_scen_name = st.selectbox("Active Scenario", scenario_names)
    active_scenario = next(s for s in st.session_state.confirmed_scenarios if s["scenario_name"] == active_scen_name)
    
    with st.expander("Reference: AI Generated Shocks", expanded=True):
        st.markdown(f"**Rationale:** {active_scenario['rationale']}")
        st.dataframe(get_scenario_table(active_scenario['shocks'], selected_asset), hide_index=True)
    
    # Dynamic Layout - Data Editor for Tweak Terminal
    sim_col1, sim_col2 = st.columns([1, 2.5])
    
    current_shocks = {}
    total_pnl = 0
    pnl_records = []
    val_col = config["value_column"]
    
    with sim_col1:
        st.markdown("### Shock Adjustments")
        st.caption("Modify shock values as needed")
        
        # Build DataFrame for the Data Editor
        shock_data = []
        for rf in all_underlyings:
            raw_val = active_scenario["shocks"].get(rf, 0.0)
            if isinstance(raw_val, str):
                raw_val = raw_val.replace("%", "").strip()
            try:
                val = float(raw_val)
            except:
                val = 0.0
            shock_data.append({"Underlying": rf, "Target Shock": val})
        
        shock_df = pd.DataFrame(shock_data)
        
        # Excel-style Data Editor
        edited_shock_df = st.data_editor(
            shock_df, 
            hide_index=True, 
            use_container_width=True,
            column_config={
                "Target Shock": st.column_config.NumberColumn(
                    "Target Shock",
                    help="Adjust shock value (decimals for %)",
                    step=0.01 if config["unit_label"] == "%" else 1.0,
                    format="%.4f"
                )
            }
        )
        
        # Convert edited dataframe back to dictionary
        current_shocks = dict(zip(edited_shock_df["Underlying"], edited_shock_df["Target Shock"]))

    with sim_col2:
        st.markdown("#### Simulation Parameters")
        scale_to_daily = st.checkbox("Scale to 1-Day Equivalent (÷ √252)", value=True, help="Convert annualized shock to 1-day magnitude")

        # Backend calculates Delta and Vega automatically
        # Filter portfolio by selected location from sidebar
        df_filtered = df_portfolio[df_portfolio.get("Location", pd.Series(["N/A"] * len(df_portfolio))) == selected_location] if "Location" in df_portfolio.columns else df_portfolio
        
        for _, row in df_filtered.iterrows():
            rf = row["Underlying"]
            loc = row.get("Location", "N/A")
            delta_exp = row.get(val_col, 0.0)
            vega_exp = row.get("CMD Vega", 0.0) if "CMD Vega" in row else 0.0
            base_shock = current_shocks.get(rf, 0.0)
            # Mathematical Daily Scaling
            daily_shock = base_shock / np.sqrt(252) if scale_to_daily else base_shock
            # Vega shock derived from delta shock
            vega_shock = daily_shock * 0.8883
            delta_pnl = delta_exp * daily_shock
            vega_pnl = vega_exp * vega_shock
            row_total_pnl = delta_pnl + vega_pnl
            total_pnl += row_total_pnl
            delta_shock_display = f"{daily_shock*100:+.2f}%" if config["unit_label"] == "%" else f"{daily_shock:+.2f} bps"
            vega_shock_display = f"{vega_shock*100:+.2f}%" if config["unit_label"] == "%" else f"{vega_shock:+.2f} bps"
            pnl_records.append({
                "Trade Location": loc,
                "Underlying": rf,
                "Exposure Delta": delta_exp,
                "Exposure Vega": vega_exp,
                "Delta Shock (Daily)": delta_shock_display,
                "Vega Shock (Daily)": vega_shock_display,
                "Delta PnL": delta_pnl,
                "Vega PnL": vega_pnl,
                "Total PnL": row_total_pnl
            })
        
        # Calculate total from full results table
        df_pnl = pd.DataFrame(pnl_records)
        total_pnl = sum([r['Total PnL'] for r in pnl_records]) 
        abs_total_pnl = df_pnl['Total PnL'].abs().sum() if len(df_pnl) > 0 else 0
        
        st.markdown(f"<h1 style='text-align: center; font-size: 4rem; color: #FF6200'>€{total_pnl:,.0f}</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center;'>Total Estimated PnL Impact (Delta + Vega)</p>", unsafe_allow_html=True)
        # st.markdown(f"<p style='text-align: center; color: #6C6763; font-size: 1.1rem;'>Absolute Total: €{abs_total_pnl:,.0f}</p>", unsafe_allow_html=True)
        
        # Sort and get Top 5
        df_pnl['Abs Total PnL'] = df_pnl['Total PnL'].abs()
        df_pnl_sorted = df_pnl.sort_values(by='Abs Total PnL', ascending=False).drop(columns=['Abs Total PnL'])
        df_top5 = df_pnl_sorted.head(5)
        
        st.markdown("#### Top 5 Impact Drivers")
        st.dataframe(
            df_top5.style.format({
                "Exposure Delta": "€{:,.0f}", 
                "Exposure Vega": "€{:,.0f}",
                "Delta PnL": "€{:,.0f}",
                "Vega PnL": "€{:,.0f}",
                "Total PnL": "€{:,.0f}"
            }), 
            use_container_width=True, 
            hide_index=True
        )
        
        # Expander to view and download full dataset
        with st.expander("Full Results & Export"):
            st.dataframe(
                df_pnl_sorted.style.format({
                    "Exposure Delta": "€{:,.0f}", 
                    "Exposure Vega": "€{:,.0f}",
                    "Delta PnL": "€{:,.0f}",
                    "Vega PnL": "€{:,.0f}",
                    "Total PnL": "€{:,.0f}"
                }), 
                use_container_width=True, 
                hide_index=True
            )
            csv = df_pnl_sorted.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="DOWNLOAD CSV",
                data=csv,
                file_name=f"stress_test_pnl_{active_scen_name.replace(' ', '_')}.csv",
                mime="text/csv",
            )
        
        # Plotly Bar Graph
        df_plot = df_pnl_sorted.groupby("Underlying")["Total PnL"].sum().reset_index()
        fig = px.bar(
            df_plot, 
            x="Underlying", 
            y="Total PnL", 
            color="Total PnL", 
            color_continuous_scale=["#D95200", "#F7F4F1", "#1E8700"],  # ING colors: red to grey to green
            title="Total PnL Impact by Underlying"
        )
        fig.update_layout(
            template="plotly_white",
            title_font_size=20,
            title_font_color="#111010",
            font_family="Inter, sans-serif",
            plot_bgcolor="#F7F4F1",
            paper_bgcolor="white",
            xaxis=dict(
                gridcolor="#F1EDE9",
                title_font_color="#201E1E"
            ),
            yaxis=dict(
                gridcolor="#F1EDE9",
                title_font_color="#201E1E"
            )
        )
        st.plotly_chart(fig, use_container_width=True)

    # ==========================================
    # FINAL EXECUTIVE COMMENTARY
    # ==========================================
    st.write("---")
    if st.button("GENERATE EXECUTIVE REPORT", type="primary", key="exec_report_btn"):
        with st.spinner("Synthesizing rules, narrative, and final calculations..."):
            report_prompt = f"""
            Act as Global CRO. Write a concise executive summary based on:
            1. Narrative: {news_text}
            2. Applied Scenario: {active_scen_name}
            3. Final Calculated PnL: €{total_pnl:,.0f}
            4. ING Rules Applied: {st.session_state.ing_shock_rules}
            
            Include a small markdown table showing the final shocks. Keep it brief and authoritative.
            """
            try:
                report = model.generate_content(report_prompt).text
                st.markdown("### Executive Summary")
                st.markdown(report)
            except:
                st.error("Failed to generate report.")

# ==========================================
# FOOTER
# ==========================================
st.markdown("---")
st.markdown("""
<div style='text-align: center; padding: 2rem 0; color: var(--ing-grey-40);'>
    <p style='font-size: 0.85rem; margin-bottom: 0.5rem;'>
        <strong style='color: #FF6200;'>StressLess ING</strong> • Powered by Love, Python, Streamlit and GCP Vertex AI
    </p>
    <p style='font-size: 0.75rem;'>
        Intelligence Scenario Factory • Built with ING Web Components
    </p>
</div>
""", unsafe_allow_html=True)