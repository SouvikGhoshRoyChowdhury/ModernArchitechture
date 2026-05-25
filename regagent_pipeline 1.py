import streamlit as st
import vertexai
from vertexai.generative_models import GenerativeModel
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_google_vertexai import VertexAIEmbeddings
from google.cloud import documentai_v1 as documentai
import difflib
import feedparser
import requests
import json
import os
from datetime import datetime, timedelta
from dateutil import parser as date_parser
import time

# ==========================================
# 1. CONFIGURATION (UPDATE THESE!)
# ==========================================
PROJECT_ID = "rk-fm-hackathon"   # Your GCP Project ID
LOCATION = "europe-west4"                 # Your Vertex AI Location
DOCAI_LOCATION = "eu"                     # Document AI Location (Usually 'us' or 'eu')
DOCAI_PROCESSOR_ID = "6572522ca4fc5d55"  # Create this in GCP Document AI Console!

# ==========================================
# 2. INITIALIZATION: REAL VERTEX AI
# ==========================================
@st.cache_resource
def load_models():
    vertexai.init(project=PROJECT_ID, location=LOCATION)
    # Using the latest stable Pro model
    gemini = GenerativeModel("gemini-2.0-flash-001")
    
    # Using real Vertex AI Embeddings for the Vector DB
    embeddings = VertexAIEmbeddings(
        project=PROJECT_ID,
        location=LOCATION,
        model="text-embedding-004"
    )
    return gemini, embeddings

gemini_model, embeddings_model = load_models()

# RSS Feed Configuration
RSS_FEEDS = {
    "EUR-Lex Feed 221": "https://eur-lex.europa.eu/EN/display-feed.rss?rssId=221",
    "EUR-Lex Feed 222": "https://eur-lex.europa.eu/EN/display-feed.rss?rssId=222",
    "ESMA Feed": "https://www.esma.europa.eu/rss.xml"
}

# MiFIR Keywords for content analysis
MIFIR_KEYWORDS = [
    "Investment firms", "Transaction reporting obligation", "Validation fields", "Reportable instrument",
    "Reference data", "Article 26", "Regulation (EU) No 600/2014", "MiFIR",
    "Commission Delegated Regulation (EU) 2017/590", "RTS 22", "Financial instruments",
    "Execute transactions", "Transaction reports", "AFM", "TOTV", "UTOTV",
    "Trading venue transaction identification code (TVTIC)", "Transaction reference number (TRN)",
    "ARM", "Completeness", "Accuracy", "Timeliness", "Methods", "Arrangements",
    "LEI", "Transmission", "Transmitting firm", "DEAL", "MTCH", "AOTC", "CONCAT",
    "Reconciliation", "MIC", "SEGMENT MIC", "OPERATING MIC", "INTC"
]

def clean_html_text(html_text: str) -> str:
    """Remove HTML tags and clean up text content."""
    if not html_text:
        return ""
    
    import re
    # Remove HTML tags
    clean_text = re.sub(r'<[^>]+>', '', html_text)
    # Replace HTML entities
    clean_text = clean_text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&#39;', "'")
    # Clean up whitespace
    clean_text = ' '.join(clean_text.split())
    return clean_text.strip()

def fetch_webpage_content(url: str) -> str:
    """Fetch content from a webpage URL."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        return response.text[:8000]  # Limit content to manage API costs
    except Exception as e:
        return f"Error fetching content: {str(e)}"

def analyze_content_with_gemini(content: str, title: str) -> dict:
    """Use Gemini to analyze webpage content for MiFIR keywords."""
    try:
        prompt = f"""
        Analyze the following document content to determine if it contains any MiFIR (Markets in Financial Instruments Regulation) related keywords.
        
        Document Title: {title}
        Content: {content[:4000]}  # Limit for API efficiency
        
        Keywords to search for:
        {', '.join(MIFIR_KEYWORDS)}
        
        Instructions:
        1. Look for exact matches or close variations of the keywords
        2. Consider the context - ensure the keywords relate to financial regulation
        3. Return ONLY the keywords that are actually found in the content
        
        Also take these additional instructions into account:
        {"\n".join([f"- {f}" for f in st.session_state.feedback_history]) if st.session_state.feedback_history else "No additional feedback from user."}

        Respond in this exact JSON format:
        {{
            "has_mifir_content": true/false,
            "found_keywords": ["keyword1", "keyword2", ...],
            "confidence": "high/medium/low",
            "summary": "Brief explanation of findings"
        }}
        """
        
        response = gemini_model.generate_content(prompt)
        result_text = response.text.strip()
        
        # Extract JSON from response
        import re
        json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            return {
                "has_mifir_content": result.get("has_mifir_content", False),
                "found_keywords": result.get("found_keywords", []),
                "confidence": result.get("confidence", "low"),
                "summary": result.get("summary", "No analysis available")
            }
        else:
            # Fallback: simple keyword matching
            content_lower = content.lower()
            found = [kw for kw in MIFIR_KEYWORDS if kw.lower() in content_lower]
            return {
                "has_mifir_content": len(found) > 0,
                "found_keywords": found,
                "confidence": "medium",
                "summary": f"Found {len(found)} keyword matches"
            }
            
    except Exception as e:
        error_msg = str(e)
        if "invalid_grant" in error_msg or "expired" in error_msg.lower():
            st.error("🔐 **Authentication Error**: Your Google Cloud credentials have expired. Please re-authenticate using: `gcloud auth application-default login`")
            return {
                "has_mifir_content": False,
                "found_keywords": [],
                "confidence": "low",
                "summary": "Authentication required - please refresh your Google Cloud credentials"
            }
        else:
            st.warning(f"Analysis error: {str(e)}")
            # Fallback to simple keyword matching when Gemini fails
            try:
                content_lower = content.lower()
                found = [kw for kw in MIFIR_KEYWORDS if kw.lower() in content_lower]
                return {
                    "has_mifir_content": len(found) > 0,
                    "found_keywords": found,
                    "confidence": "low",
                    "summary": f"Fallback analysis: Found {len(found)} keyword matches (Gemini unavailable)"
                }
            except:
                return {
                    "has_mifir_content": False,
                    "found_keywords": [],
                    "confidence": "low",
                    "summary": "Analysis failed - authentication or connection issue"
                }

def analyze_feed_content(feed_entries: list, feed_name: str) -> dict:
    """Analyze all entries in a feed for MiFIR content and mark them in place."""
    results = {
        "total_analyzed": 0,
        "mifir_relevant": 0
    }
    
    for entry in feed_entries[:10]:  # Analyze first 10 entries to manage API costs
        if not entry.get('link'):
            continue
            
        with st.spinner(f"Analyzing: {entry['title'][:50]}..."):
            content = fetch_webpage_content(entry['link'])
            analysis = analyze_content_with_gemini(content, entry['title'])
            
            # Mark the entry with analysis results
            entry['mifir_analysis'] = analysis
            entry['is_mifir_relevant'] = analysis["has_mifir_content"]
            
            results["total_analyzed"] += 1
            
            if analysis["has_mifir_content"]:
                results["mifir_relevant"] += 1
    
    return results

def fetch_rss_feed(feed_url: str):
    """Fetches and parses RSS feed, returns list of entries with metadata."""
    try:
        response = requests.get(feed_url, timeout=10)
        response.raise_for_status()
        
        feed = feedparser.parse(response.content)
        
        entries = []
        for entry in feed.entries:
            # Parse publication date
            pub_date = None
            if hasattr(entry, 'published'):
                try:
                    pub_date = date_parser.parse(entry.published)
                except:
                    pub_date = datetime.now()
            
            entries.append({
                'title': entry.get('title', 'No title'),
                'link': entry.get('link', ''),
                'summary': entry.get('summary', entry.get('description', '')),
                'published': pub_date,
                'published_str': entry.get('published', 'Unknown date')
            })
        
        return entries[:20]  # Return latest 20 entries
    except Exception as e:
        st.error(f"Error fetching RSS feed: {str(e)}")
        return []

def load_cached_feed_data(feed_name: str):
    """Load previously cached RSS feed data for a specific feed."""
    cache_file = f"rss_cache_{feed_name.lower().replace(' ', '_').replace('-', '_')}.json"
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Convert string dates back to datetime objects
                for entry in data:
                    if entry['published']:
                        entry['published'] = datetime.fromisoformat(entry['published'])
                return data
        except:
            return []
    return []

def save_cached_feed_data(entries, feed_name: str):
    """Save RSS feed data to cache for a specific feed."""
    cache_file = f"rss_cache_{feed_name.lower().replace(' ', '_').replace('-', '_')}.json"
    # Convert datetime objects to strings for JSON serialization
    serializable_entries = []
    for entry in entries:
        entry_copy = entry.copy()
        if entry_copy['published']:
            entry_copy['published'] = entry_copy['published'].isoformat()
        serializable_entries.append(entry_copy)
    
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(serializable_entries, f, indent=2, ensure_ascii=False)
    except Exception as e:
        st.error(f"Error saving cache for {feed_name}: {str(e)}")

def check_for_new_items(new_entries, cached_entries):
    """Compare new entries with cached ones and return count of new items."""
    if not cached_entries:
        return len(new_entries), new_entries
    
    cached_links = {entry['link'] for entry in cached_entries}
    new_items = [entry for entry in new_entries if entry['link'] not in cached_links]
    return len(new_items), new_items

def fetch_all_feeds():
    """Fetch all configured RSS feeds and return combined results."""
    all_entries = []
    total_new_count = 0
    feed_results = {}
    
    for feed_name, feed_url in RSS_FEEDS.items():
        try:
            cached_entries = load_cached_feed_data(feed_name)
            new_entries = fetch_rss_feed(feed_url)
            
            if new_entries:
                new_count, new_items = check_for_new_items(new_entries, cached_entries)
                
                # Add feed source to each entry
                for entry in new_entries:
                    entry['feed_source'] = feed_name
                
                all_entries.extend(new_entries)
                total_new_count += new_count
                
                feed_results[feed_name] = {
                    'entries': new_entries,
                    'new_count': new_count,
                    'new_items': new_items
                }
                
                # Save cache for this feed
                save_cached_feed_data(new_entries, feed_name)
            else:
                # Handle empty entries case
                feed_results[feed_name] = {
                    'entries': [],
                    'new_count': 0,
                    'new_items': []
                }
            
        except Exception as e:
            st.error(f"Error processing {feed_name}: {str(e)}")
            feed_results[feed_name] = {'entries': [], 'new_count': 0, 'new_items': []}
    
    # Sort all entries by publication date (newest first) with error handling
    try:
        all_entries.sort(key=lambda x: x.get('published', datetime.min) or datetime.min, reverse=True)
    except Exception as e:
        st.warning(f"Error sorting entries: {str(e)}")
    
    return all_entries, total_new_count, feed_results

# ==========================================
# 3. DOCUMENT AI & DIFFING HELPERS
# ==========================================
def extract_text_with_docai(file_bytes: bytes) -> str:
    """Processes a PDF directly from memory using Document AI."""
    client = documentai.DocumentProcessorServiceClient(
        client_options={"api_endpoint": f"{DOCAI_LOCATION}-documentai.googleapis.com"}
    )
    name = client.processor_path(PROJECT_ID, DOCAI_LOCATION, DOCAI_PROCESSOR_ID)
    
    raw_document = documentai.RawDocument(content=file_bytes, mime_type="application/pdf")
    request = documentai.ProcessRequest(name=name, raw_document=raw_document)
    
    result = client.process_document(request=request)
    return result.document.text

def compute_smart_diff(old_text: str, new_text: str) -> str:
    """Uses Python difflib to find exact additions and deletions."""
    old_lines = [line.strip() for line in old_text.split('\n') if line.strip()]
    new_lines = [line.strip() for line in new_text.split('\n') if line.strip()]
    
    # unified_diff shows added/removed lines with minimal context
    diff = difflib.unified_diff(old_lines, new_lines, n=1)
    
    # Filter to only show actual changes (lines starting with + or -)
    changes = [line for line in diff if line.startswith('+ ') or line.startswith('- ')]
    return '\n'.join(changes)

# ==========================================
# 4. UI CONFIG & SESSION STATE
# ==========================================
st.set_page_config(page_title="RegAgent: Scalable Pipeline", layout="wide")
st.title("🏛️ RegAgent: AI Regulatory Change Analyzer")

for key in ["changes_summary", "internal_vectorstore", "matched_evidence", "gap_analysis", "feedback_history", "rss_entries", "last_rss_check", "new_items_count", "feed_results", "selected_document"]:
    if key not in st.session_state:
        if key == "feedback_history":
            st.session_state[key] = []
        elif key == "internal_vectorstore":
            st.session_state[key] = None
        elif key in ["rss_entries", "feed_results"]:
            st.session_state[key] = []
        elif key == "last_rss_check":
            st.session_state[key] = None
        elif key == "new_items_count":
            st.session_state[key] = 0
        elif key == "selected_document":
            st.session_state[key] = None
        else:
            st.session_state[key] = ""

# ==========================================
# 5. SIDEBAR: SCOPE, KNOWLEDGE BASE, FEEDBACK
# ==========================================
with st.sidebar:
    st.header("🌍 1. Regulatory Scope")
    selected_region = st.selectbox("Jurisdiction / Region", ["EU", "UK", "US", "APAC", "Global"])
    selected_framework = st.selectbox("Regulatory Framework", ["MiFIR / MiFID II", "EMIR", "SFTR", "Basel IV", "DORA"])
    
    st.divider()
    
    st.header("🧠 2. Agent Memory / Feedback")
    new_feedback = st.text_input("Add rule (e.g., 'Ignore Retail')")
    if st.button("Add to Agent Memory"):
        if new_feedback:
            st.session_state.feedback_history.append(new_feedback)
            st.success("Rule added!")
            
    if st.session_state.feedback_history:
        for f in st.session_state.feedback_history:
            st.caption(f"✅ {f}")
            
    st.divider()

    st.header("🏢 3. Internal Knowledge Base")
    internal_docs = st.file_uploader("Upload Policies (PDF)", type=["pdf"], accept_multiple_files=True)
    
    if st.button("Build Knowledge Base"):
        if internal_docs and DOCAI_PROCESSOR_ID != "YOUR_PROCESSOR_ID":
            with st.spinner("Document AI is extracting precise layout & text..."):
                docs = []
                for uploaded_file in internal_docs:
                    # Parse with Document AI instead of basic PyPDFLoader
                    text = extract_text_with_docai(uploaded_file.getvalue())
                    docs.append(Document(page_content=text, metadata={"source": uploaded_file.name}))
                
                text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
                chunks = text_splitter.split_documents(docs)
                st.session_state.internal_vectorstore = FAISS.from_documents(chunks, embeddings_model)
                st.success(f"Knowledge Base Built! ({len(chunks)} high-quality chunks indexed)")
        else:
            st.error("Please upload PDFs and ensure DOCAI_PROCESSOR_ID is set in code.")

agent_context = ""
if st.session_state.feedback_history:
    agent_context = "\nCRITICAL USER FEEDBACK TO APPLY:\n" + "\n".join([f"- {f}" for f in st.session_state.feedback_history])

# ==========================================
# 6. MAIN WORKFLOW TABS
# ==========================================
tab1, tab2, tab3 = st.tabs(["1️⃣ Horizon Scanning", "2️⃣ Change detection", "3️⃣ Draft Deliverables"])

# ------------------------------------------
# TAB 1: Horizon Scanning & Document AI Diffing
# ------------------------------------------
with tab1:
    st.header("🌐 Horizon Scanning")
    
    col_a, col_b = st.columns(2, width = "stretch")

    col_a.success("🏦 EUR-Lex: Active")
    col_b.success("🏛️ ESMA: Active")
    # col_c.success("🏦 EBA: Active")
    # col_d.success("📋 Global FAQs: Active")
    st.write("---")
    
    # RSS Feed Window below horizon scanning button
    st.markdown("### 📡 EUR-Lex Live Feed Monitor")
    
    # Add authentication status check
    try:
        # Quick test of Gemini model availability
        test_response = gemini_model.generate_content("Test")
        auth_status = "✅ Google Cloud authentication active"
        auth_color = "success"
    except Exception as e:
        if "invalid_grant" in str(e) or "expired" in str(e).lower():
            auth_status = "🔐 Google Cloud credentials expired - MiFIR analysis disabled"
            auth_color = "error"
        else:
            auth_status = "⚠️ Google Cloud connection issue"
            auth_color = "warning"
    
    st.markdown(f"[{auth_status}]")
    
    rss_col1, rss_col2 = st.columns([3, 1])
    
    with rss_col1:
        st.info("📊 Monitoring: EUR-Lex Feed 221 & 222")
    
    with rss_col2:
        auto_refresh = st.checkbox("🔄 Auto-refresh (30s)", key="auto_refresh_rss")
    
    # Auto-refresh logic
    if auto_refresh:
        if st.session_state.last_rss_check is None or \
           (datetime.now() - st.session_state.last_rss_check).seconds >= 30:
            
            try:
                with st.spinner("Fetching latest EUR-Lex updates from both feeds..."):
                    all_entries, total_new_count, feed_results = fetch_all_feeds()
                    
                    if total_new_count > 0:
                        st.session_state.new_items_count = total_new_count
                        # Show breakdown by feed
                        feed_breakdown = []
                        for feed_name, results in feed_results.items():
                            if results['new_count'] > 0:
                                feed_breakdown.append(f"{results['new_count']} from {feed_name}")
                        
                        breakdown_text = ", ".join(feed_breakdown) if feed_breakdown else ""
                        st.toast(f"🆕 {total_new_count} new item(s) discovered! ({breakdown_text})", icon="🔔")
                        
                    st.session_state.rss_entries = all_entries
                    st.session_state.feed_results = feed_results
                    st.session_state.last_rss_check = datetime.now()
                        
                st.rerun()
            except Exception as e:
                st.error(f"Auto-refresh failed: {str(e)}")
                st.session_state.last_rss_check = datetime.now()  # Prevent repeated failures
    
    # Manual refresh button
    if st.button("🔄 Refresh Feeds", key="manual_refresh_rss"):
        try:
            with st.spinner("Fetching latest EUR-Lex updates from both feeds..."):
                all_entries, total_new_count, feed_results = fetch_all_feeds()
                
                if total_new_count > 0:
                    st.session_state.new_items_count = total_new_count
                    # Show breakdown by feed
                    feed_breakdown = []
                    for feed_name, results in feed_results.items():
                        if results['new_count'] > 0:
                            feed_breakdown.append(f"{results['new_count']} from {feed_name}")
                    
                    breakdown_text = ", ".join(feed_breakdown) if feed_breakdown else ""
                    st.success(f"🆕 Found {total_new_count} new item(s)! ({breakdown_text})")
                else:
                    st.info("✅ No new items since last check")
                    
                st.session_state.rss_entries = all_entries
                st.session_state.feed_results = feed_results
                st.session_state.last_rss_check = datetime.now()
        except Exception as e:
            st.error(f"Manual refresh failed: {str(e)}")
    
    # Display notification for new items
    if st.session_state.new_items_count > 0:
        st.warning(f"🔔 **{st.session_state.new_items_count} new item(s)** discovered in latest scan!")
        if st.button("✅ Mark as Reviewed"):
            st.session_state.new_items_count = 0
            
    
    # Display RSS feed entries - EUR-Lex Section
    if st.session_state.rss_entries:
        # Filter EUR-Lex entries
        eurlex_entries = [entry for entry in st.session_state.rss_entries if 'EUR-Lex' in entry.get('feed_source', '')]
        
        if eurlex_entries:
            st.markdown("#### 🇪🇺 EUR-Lex Publications")
            
            # EUR-Lex feed statistics
            eurlex_feeds = {k: v for k, v in st.session_state.feed_results.items() if 'EUR-Lex' in k}
            if eurlex_feeds:
                eurlex_cols = st.columns(len(eurlex_feeds))
                for i, (feed_name, results) in enumerate(eurlex_feeds.items()):
                    with eurlex_cols[i]:
                        st.metric(
                            label=feed_name,
                            value=f"{len(results.get('entries', []))} items",
                            delta=f"+{results.get('new_count', 0)} new" if results.get('new_count', 0) > 0 else None
                        )
            
            # EUR-Lex entries display
            with st.expander(f"📄 {len(eurlex_entries)} EUR-Lex Items", expanded=False):
                # Add MiFIR analysis button
                if st.button("🎯 Analyze EUR-Lex for MiFIR Keywords", key="analyze_eurlex_mifir", help="Use Gemini to analyze EUR-Lex documents for MiFIR-related content"):
                    with st.spinner("Analyzing EUR-Lex entries for MiFIR content..."):
                        analysis_results = analyze_feed_content(eurlex_entries, "EUR-Lex")
                        st.session_state.eurlex_analysis = analysis_results
                
                # Display analysis summary if available
                if hasattr(st.session_state, 'eurlex_analysis') and st.session_state.eurlex_analysis:
                    results = st.session_state.eurlex_analysis
                    
                    # Summary metrics
                    analysis_col1, analysis_col2, analysis_col3 = st.columns(3)
                    with analysis_col1:
                        st.metric("Documents Analyzed", results["total_analyzed"])
                    with analysis_col2:
                        st.metric("MiFIR Relevant", results["mifir_relevant"])
                    with analysis_col3:
                        relevance_pct = (results["mifir_relevant"] / results["total_analyzed"] * 100) if results["total_analyzed"] > 0 else 0
                        st.metric("Relevance %", f"{relevance_pct:.1f}%")
                    
                    st.divider()
                
                # Display feed entries with MiFIR markings
                for entry in eurlex_entries[:15]:  # Show latest 15
                    with st.container():
                        col1, col2 = st.columns([4, 1])
                        
                        with col1:
                            # Check if entry has been analyzed and is MiFIR relevant
                            if entry.get('is_mifir_relevant', False):
                                st.markdown(f"🎯 **[MiFIR RELEVANT]** {entry['title'][:100]}{'...' if len(entry['title']) > 100 else ''}**")
                                # Show MiFIR analysis details
                                analysis = entry.get('mifir_analysis', {})
                                if analysis.get('found_keywords'):
                                    st.caption(f"🏷️ **MiFIR Keywords**: {', '.join(analysis['found_keywords'][:3])}{'...' if len(analysis['found_keywords']) > 3 else ''}")
                                st.caption(f"🔍 **Analysis**: {analysis.get('summary', 'No summary')} (Confidence: {analysis.get('confidence', 'unknown')})")
                            else:
                                st.markdown(f"**{entry['title'][:100]}{'...' if len(entry['title']) > 100 else ''}**")
                            
                            st.caption(f"📡 Source: {entry.get('feed_source', 'Unknown Feed')}")
                            if entry['summary'] and not entry.get('is_mifir_relevant', False):  # Only show summary if not MiFIR (to save space)
                                clean_summary = clean_html_text(entry['summary'])
                                st.caption(clean_summary[:200] + ('...' if len(clean_summary) > 200 else ''))
                        
                        with col2:
                            st.caption(f"📅 {entry['published_str'][:10] if entry['published_str'] else 'Unknown'}")
                            if entry['link']:
                                st.link_button("🔗 View", entry['link'], use_container_width=True)
                                # Check if this document is currently selected
                                is_selected = (st.session_state.selected_document and 
                                             st.session_state.selected_document.get('link') == entry['link'])
                                
                                if is_selected:
                                    st.success("✅ Selected", icon="✅")
                                else:
                                    # Add Select button under View button
                                    if st.button("📌 Select", key=f"select_eurlex_{hash(entry.get('link', '') + entry.get('title', ''))}", use_container_width=True, help="Select this document for comparison in Tab 2"):
                                        st.session_state.selected_document = {
                                            'title': entry['title'],
                                            'link': entry['link'],
                                            'summary': entry.get('summary', ''),
                                            'feed_source': entry.get('feed_source', ''),
                                            'published_str': entry.get('published_str', ''),
                                            'is_mifir_relevant': entry.get('is_mifir_relevant', False),
                                            'mifir_analysis': entry.get('mifir_analysis', {})
                                        }
                                        st.rerun()  # Rerun to show selection immediately
                        
                        st.divider()
    else:
        st.info("Click 'Refresh Feeds' to load the latest EUR-Lex publications")
    
    st.write("---")
    
    # ESMA Feed Window
    st.markdown("### 🏦 ESMA Live Feed Monitor")
    
    esma_col1, esma_col2 = st.columns([3, 1])
    
    with esma_col1:
        st.info("📊 Monitoring: ESMA Publications")
    
    with esma_col2:
        if st.button("🔄 Refresh ESMA", key="refresh_esma_only"):
            try:
                with st.spinner("Fetching latest ESMA updates..."):
                    all_entries, total_new_count, feed_results = fetch_all_feeds()
                    st.session_state.rss_entries = all_entries
                    st.session_state.feed_results = feed_results
                    st.session_state.last_rss_check = datetime.now()
                    
                    esma_new_count = feed_results.get('ESMA Feed', {}).get('new_count', 0)
                    if esma_new_count > 0:
                        st.success(f"🆕 Found {esma_new_count} new ESMA item(s)!")
                    else:
                        st.info("✅ No new ESMA items")
            except Exception as e:
                st.error(f"ESMA refresh failed: {str(e)}")
    
    # Display ESMA feed entries
    if st.session_state.rss_entries:
        # Filter ESMA entries
        esma_entries = [entry for entry in st.session_state.rss_entries if 'ESMA' in entry.get('feed_source', '')]
        
        if esma_entries:
            st.markdown("#### 🏦 ESMA Publications")
            
            # ESMA feed statistics
            esma_results = st.session_state.feed_results.get('ESMA Feed', {'entries': [], 'new_count': 0})
            esma_metric_col1, esma_metric_col2, esma_metric_col3 = st.columns([1, 1, 2])
            
            with esma_metric_col1:
                st.metric(
                    label="ESMA Feed",
                    value=f"{len(esma_results.get('entries', []))} items",
                    delta=f"+{esma_results.get('new_count', 0)} new" if esma_results.get('new_count', 0) > 0 else None
                )
            
            # ESMA entries display
            with st.expander(f"📄 {len(esma_entries)} ESMA Items", expanded=False):
                # Add MiFIR analysis button
                if st.button("🎯 Analyze ESMA for MiFIR Keywords", key="analyze_esma_mifir", help="Use Gemini to analyze ESMA documents for MiFIR-related content"):
                    with st.spinner("Analyzing ESMA entries for MiFIR content..."):
                        analysis_results = analyze_feed_content(esma_entries, "ESMA")
                        st.session_state.esma_analysis = analysis_results
                
                # Display analysis summary if available
                if hasattr(st.session_state, 'esma_analysis') and st.session_state.esma_analysis:
                    results = st.session_state.esma_analysis
                    
                    # Summary metrics
                    analysis_col1, analysis_col2, analysis_col3 = st.columns(3)
                    with analysis_col1:
                        st.metric("Documents Analyzed", results["total_analyzed"])
                    with analysis_col2:
                        st.metric("MiFIR Relevant", results["mifir_relevant"])
                    with analysis_col3:
                        relevance_pct = (results["mifir_relevant"] / results["total_analyzed"] * 100) if results["total_analyzed"] > 0 else 0
                        st.metric("Relevance %", f"{relevance_pct:.1f}%")
                    
                    st.divider()
                
                # Display feed entries with MiFIR markings
                for entry in esma_entries[:15]:  # Show latest 15
                    with st.container():
                        col1, col2 = st.columns([4, 1])
                        
                        with col1:
                            # Check if entry has been analyzed and is MiFIR relevant
                            if entry.get('is_mifir_relevant', False):
                                st.markdown(f"🎯 **[MiFIR RELEVANT]** {entry['title'][:100]}{'...' if len(entry['title']) > 100 else ''}**")
                                # Show MiFIR analysis details
                                analysis = entry.get('mifir_analysis', {})
                                if analysis.get('found_keywords'):
                                    st.caption(f"🏷️ **MiFIR Keywords**: {', '.join(analysis['found_keywords'][:3])}{'...' if len(analysis['found_keywords']) > 3 else ''}")
                                st.caption(f"🔍 **Analysis**: {analysis.get('summary', 'No summary')} (Confidence: {analysis.get('confidence', 'unknown')})")
                            else:
                                st.markdown(f"**{entry['title'][:100]}{'...' if len(entry['title']) > 100 else ''}**")
                            
                            st.caption(f"📡 Source: {entry.get('feed_source', 'Unknown Feed')}")
                            if entry['summary'] and not entry.get('is_mifir_relevant', False):  # Only show summary if not MiFIR (to save space)
                                clean_summary = clean_html_text(entry['summary'])
                                st.caption(clean_summary[:200] + ('...' if len(clean_summary) > 200 else ''))
                        
                        with col2:
                            st.caption(f"📅 {entry['published_str'][:10] if entry['published_str'] else 'Unknown'}")
                            if entry['link']:
                                st.link_button("🔗 View", entry['link'], use_container_width=True)
                                # Check if this document is currently selected
                                is_selected = (st.session_state.selected_document and 
                                             st.session_state.selected_document.get('link') == entry['link'])
                                
                                if is_selected:
                                    st.success("Selected", icon="✅")
                                else:
                                    # Add Select button under View button
                                    if st.button("📌 Select", key=f"select_esma_{hash(entry.get('link', '') + entry.get('title', ''))}", use_container_width=True, help="Select this document for comparison in Tab 2"):
                                        st.session_state.selected_document = {
                                            'title': entry['title'],
                                            'link': entry['link'],
                                            'summary': entry.get('summary', ''),
                                            'feed_source': entry.get('feed_source', ''),
                                            'published_str': entry.get('published_str', ''),
                                            'is_mifir_relevant': entry.get('is_mifir_relevant', False),
                                            'mifir_analysis': entry.get('mifir_analysis', {})
                                        }
                                        st.rerun()  # Rerun to show selection immediately
                        
                        st.divider()
        else:
            st.info("No ESMA entries available. Click 'Refresh Feeds' above to load data.")
    else:
        st.info("Click 'Refresh Feeds' above to load ESMA publications")
    
    st.write("---")
    
    # Original horizon scanning workflow continues here
    if "horizon_scan_completed" not in st.session_state:
        st.session_state.horizon_scan_completed = False
            
    # Display Results & HITL Refinement
    if st.session_state.changes_summary:
        st.markdown("### 📊 Horizon Scan Results")
        st.markdown(st.session_state.changes_summary)
        
        st.write("---")
        st.markdown("#### 🗣️ Refine Agent Output (Human-in-the-Loop)")
        hitl_col1, hitl_col2 = st.columns([4, 1])
        with hitl_col1:
            tab1_feedback = st.text_input("Instruct AI to adjust (e.g., 'Expand the impact column for Level 3 changes'):", key="tab1_hitl")
        with hitl_col2:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🔄 Apply Refinement", use_container_width=True) and tab1_feedback:
                with st.spinner("AI is applying refinements..."):
                    refine_prompt = f"""
                    You previously drafted this regulatory change summary:
                    {st.session_state.changes_summary}
                    
                    The Compliance Manager provided this feedback: "{tab1_feedback}"
                    
                    Update the summary based strictly on this feedback. 
                    Maintain the exact Markdown table structure:
                    | Regulatory Level | Article/Section | Previous Obligation | New Obligation | Impact on Financial Markets (Who/What/When) |
                    """
                    st.session_state.changes_summary = gemini_model.generate_content(refine_prompt).text
                    
        
    with st.expander("⚙️ Manual Ad-Hoc Upload"):
        st.write("Upload offline PDFs. We use programmatic diffing to save LLM tokens.")
        m_col1, m_col2 = st.columns(2)
        old_pdf = m_col1.file_uploader("Previous Regulation (PDF)", type=["pdf"])
        new_pdf = m_col2.file_uploader("New Publication (PDF)", type=["pdf"])
        
        if st.button("Run Programmatic Diff"):
            if old_pdf and new_pdf:
                with st.spinner("Step 1: Document AI extracting text..."):
                    old_text = extract_text_with_docai(old_pdf.getvalue())
                    new_text = extract_text_with_docai(new_pdf.getvalue())
                
                with st.spinner("Step 2: Programmatic Difflib comparing lines..."):
                    diff_text = compute_smart_diff(old_text, new_text)
                    st.info(f"Filtered down to {len(diff_text.splitlines())} modified lines out of whole document.")
                    
                with st.spinner("Step 3: Gemini translating diffs into business impact..."):
                    prompt = f"""
                    You are a regulatory change agent. I have programmatically diffed an old vs new regulation.
                    '-' means removed from old doc. '+' means added to new doc.
                    
                    RAW DIFF DATA:
                    {diff_text}
                    
                    Identify material changes. Classify them by Level (Level 1/2/3). 
                    Format strictly as a clean Markdown table:
                    | Regulatory Level | Article/Section | Previous Obligation | New Obligation | Impact on Financial Markets |
                    
                    {agent_context}
                    """
                    st.session_state.changes_summary = gemini_model.generate_content(prompt).text
                

# ------------------------------------------
# TAB 2: Document Comparison & Change Analysis
# ------------------------------------------
with tab2:
    st.header("📊 Document Comparison & Change Analysis")
    
    # Display selected document information
    if st.session_state.selected_document:
        st.success(f"✅ **Selected Document**: {st.session_state.selected_document['title']}")
        
        # Display document details
        with st.expander("📄 Selected Document Details", expanded=False):
            st.write(f"**Source**: {st.session_state.selected_document.get('feed_source', 'Unknown')}")
            st.write(f"**Published**: {st.session_state.selected_document.get('published_str', 'Unknown')}")
            st.write(f"**Link**: {st.session_state.selected_document.get('link', 'N/A')}")
            if st.session_state.selected_document.get('summary'):
                clean_summary = clean_html_text(st.session_state.selected_document['summary'])
                st.write(f"**Summary**: {clean_summary}")
            if st.session_state.selected_document.get('is_mifir_relevant'):
                st.write("🎯 **MiFIR Relevant**: Yes")
                if st.session_state.selected_document.get('mifir_analysis', {}).get('found_keywords'):
                    st.write(f"**MiFIR Keywords**: {', '.join(st.session_state.selected_document['mifir_analysis']['found_keywords'])}")
    else:
        st.info("💡 **No document selected**. Go to Tab 1 and click the '📌 Select' button under any document you want to analyze.")
        st.stop()
    
    # Check if internal knowledge base is available
    if not st.session_state.internal_vectorstore:
        st.warning("⚠️ **Internal Knowledge Base not loaded**. Please upload and build your knowledge base in the sidebar first.")
        st.stop()
    
    st.write("---")
    
    # Document comparison section
    st.markdown("### 🔄 Compare Selected Document with Internal Knowledge Base")
    
    comparison_col1, comparison_col2 = st.columns([3, 1])
    
    with comparison_col1:
        st.info("This will fetch the selected document content and compare it with your internal policies to identify changes and gaps.")
    
    with comparison_col2:
        if st.button("🔍 Run Comparison", use_container_width=True, type="primary"):
            # Start comparison process
            with st.spinner("Step 1: Fetching document content..."):
                # Fetch the document content from the web
                document_content = fetch_webpage_content(st.session_state.selected_document['link'])
                
                if document_content.startswith("Error"):
                    st.error(f"Failed to fetch document: {document_content}")
                    st.stop()
                
                st.success(f"✅ Fetched {len(document_content)} characters from document")
            
            with st.spinner("Step 2: Retrieving comprehensive internal knowledge base content..."):
                # Instead of keyword search, retrieve more comprehensive content from internal KB
                # Use multiple search strategies to get broader coverage
                
                # Strategy 1: Search using document title
                title_retriever = st.session_state.internal_vectorstore.as_retriever(search_kwargs={"k": 5})
                title_results = title_retriever.invoke(st.session_state.selected_document['title'])
                
                # Strategy 2: Search using document summary if available
                summary_results = []
                if st.session_state.selected_document.get('summary'):
                    clean_summary = clean_html_text(st.session_state.selected_document['summary'])
                    summary_retriever = st.session_state.internal_vectorstore.as_retriever(search_kwargs={"k": 5})
                    summary_results = summary_retriever.invoke(clean_summary)
                
                # Strategy 3: Search using regulatory framework keywords
                framework_keywords = f"{selected_framework} {selected_region} regulatory requirements obligations"
                framework_retriever = st.session_state.internal_vectorstore.as_retriever(search_kwargs={"k": 5})
                framework_results = framework_retriever.invoke(framework_keywords)
                
                # Combine and deduplicate results
                all_docs = title_results + summary_results + framework_results
                unique_docs = []
                seen_content = set()
                
                for doc in all_docs:
                    # Use first 100 characters as a simple deduplication key
                    content_key = doc.page_content[:100]
                    if content_key not in seen_content:
                        unique_docs.append(doc)
                        seen_content.add(content_key)
                        if len(unique_docs) >= 10:  # Limit to top 10 unique documents
                            break
                
                # Combine internal documents with more comprehensive content
                internal_content = ""
                for i, doc in enumerate(unique_docs):
                    internal_content += f"### Internal Document {i+1} ({doc.metadata.get('source', 'Unknown')}):\n"
                    internal_content += doc.page_content + "\n\n"
                
                st.success(f"✅ Retrieved {len(unique_docs)} comprehensive internal documents using multiple search strategies")
                st.info(f"📄 Total internal content: {len(internal_content):,} characters")
            
            with st.spinner("Step 3: Generating comprehensive comparison analysis..."):
                # Generate comprehensive comparison using Gemini with expanded content
                comparison_prompt = f"""
                You are a regulatory compliance expert. Compare the NEW REGULATORY DOCUMENT with the COMPREHENSIVE INTERNAL POLICIES to identify what changes need to be made.

                **NEW REGULATORY DOCUMENT:**
                Title: {st.session_state.selected_document['title']}
                Source: {st.session_state.selected_document.get('feed_source', 'Unknown')}
                Content: {document_content[:5000]}  # Increased content limit for better analysis
                
                **COMPREHENSIVE INTERNAL POLICIES/KNOWLEDGE BASE:**
                {internal_content[:8000]}  # Significantly increased content limit for thorough comparison
                
                **ANALYSIS REQUIRED:**
                1. Thoroughly review the new regulatory document for specific obligations and requirements
                2. Cross-reference these requirements against the comprehensive internal policies provided
                3. Identify gaps where internal policies don't address new regulatory requirements
                4. Determine specific changes needed to bring internal policies into compliance
                5. Assess the business impact and implementation requirements
                4. Assess the impact on financial markets
                
                **OUTPUT FORMAT:**
                Provide your analysis in this EXACT Markdown table structure:
                
                | Article/Section | Previous Obligation | New Obligation | Impact on Financial Markets (Who/What/When) |
                |----------------|-------------------|----------------|-------------------------------------------|
                | [Specific article/section reference] | [Current requirement in internal docs] | [New requirement from regulatory document] | [Who is affected / What needs to change / When it takes effect] |
                
                **INSTRUCTIONS:**
                - Include at least 3-5 meaningful rows
                - Be specific about article numbers, sections, or regulatory references
                - Previous Obligation should reflect what's currently in the internal policies
                - New Obligation should reflect the new requirements
                - Impact should specify WHO (which business units/functions), WHAT (specific actions required), WHEN (timeline/effective date)
                - If no specific previous obligation exists, write "Not previously addressed" or "New requirement"
                - Focus on material changes that require action
                
                **CONTEXT:**
                - Regulatory Framework: {selected_framework}
                - Jurisdiction: {selected_region}
                {agent_context}
                """
                
                comparison_result = gemini_model.generate_content(comparison_prompt).text
                st.session_state.document_comparison_result = comparison_result
            
            st.success("✅ **Comparison Complete!**")
    
    # Display comparison results
    if hasattr(st.session_state, 'document_comparison_result') and st.session_state.document_comparison_result:
        st.write("---")
        st.markdown("### 📋 **Comparison Results: Required Changes**")
        st.markdown(st.session_state.document_comparison_result)
        
        # Add refinement section
        st.write("---")
        st.markdown("#### 🛠️ **Refine Analysis** (Human-in-the-Loop)")
        
        refinement_col1, refinement_col2 = st.columns([4, 1])
        
        with refinement_col1:
            refinement_feedback = st.text_input(
                "Provide feedback to improve the analysis:",
                placeholder="e.g., 'Add more detail about timeline implications' or 'Focus on trading desk impacts'",
                key="tab2_refinement"
            )
        
        with refinement_col2:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🔄 Refine Analysis", use_container_width=True) and refinement_feedback:
                with st.spinner("Refining analysis based on your feedback..."):
                    refine_prompt = f"""
                    You previously created this regulatory comparison analysis:
                    {st.session_state.document_comparison_result}
                    
                    The compliance expert provided this feedback: "{refinement_feedback}"
                    
                    Update the analysis based strictly on this feedback while maintaining the exact Markdown table structure:
                    | Article/Section | Previous Obligation | New Obligation | Impact on Financial Markets (Who/What/When) |
                    
                    Keep the same format and improve the content based on the feedback provided.
                    """
                    
                    st.session_state.document_comparison_result = gemini_model.generate_content(refine_prompt).text
        
        # Export option
        st.write("---")
        if st.button("📤 **Export Analysis**", help="Copy the analysis to clipboard"):
            st.text_area(
                "Copy the analysis below:",
                value=st.session_state.document_comparison_result,
                height=200,
                key="export_comparison"
            )
            st.success("✅ Analysis ready for export!")
    
    # Legacy policy mapping section (keep as alternative)
    st.write("---")
    st.markdown("### 🔗 **Alternative: Legacy Policy Mapping**")
    
    with st.expander("💼 Run Traditional Policy Mapping (from Tab 1 changes)", expanded=False):
        if st.button("Run Policy Mapping", key="legacy_mapping"):
            if not st.session_state.changes_summary or not st.session_state.internal_vectorstore:
                st.warning("Please build KB and run Tab 1 first for this option.")
            else:
                with st.spinner("Mapping requirements..."):
                    query_prompt = f"Extract exactly 3 crucial keywords from this text: {st.session_state.changes_summary}"
                    search_query = gemini_model.generate_content(query_prompt).text
                    
                    retriever = st.session_state.internal_vectorstore.as_retriever(search_kwargs={"k": 2})
                    relevant_docs = retriever.invoke(search_query)
                    
                    evidence = ""
                    for i, doc in enumerate(relevant_docs):
                        evidence += f"### 🔗 Traceability Link {i+1}\n"
                        evidence += f"**Regulation ({selected_framework})** ➔ **{doc.metadata.get('source', 'Policy')}**\n"
                        evidence += f"> *Extracted via Document AI:* {doc.page_content}\n\n"
                    st.session_state.matched_evidence = evidence
                st.markdown(st.session_state.matched_evidence)
        elif st.session_state.matched_evidence:
            st.markdown(st.session_state.matched_evidence)

# ------------------------------------------
# TAB 3: Draft Deliverables (formerly TAB 4)
# ------------------------------------------
with tab3:
    st.header("Deliverables Generator")
    
    # Check if comparison analysis is available
    if not hasattr(st.session_state, 'document_comparison_result') or not st.session_state.document_comparison_result:
        st.warning("⚠️ **No comparison analysis available**. Please complete the document comparison in Tab 2 first.")
        st.info("💡 **Steps to generate deliverables:**")
        st.markdown("""
        1. Go to **Tab 1** and select a document using the '📌 Select' button
        2. Go to **Tab 2** and run the document comparison analysis
        3. Return here to generate deliverables based on the comparison results
        """)
        st.stop()
    
    # Display selected document info
    if st.session_state.selected_document:
        st.success(f"✅ **Source Document**: {st.session_state.selected_document['title'][:80]}...")
    
    # Deliverable type selection
    doc_type = st.selectbox(
        "Select Deliverable Type", 
        [
            "Impact Assessment Memo", 
            "Proposed Policy Amendment Text", 
            "Change Request JIRA Ticket",
            "Executive Summary Report",
            "Implementation Timeline"
        ]
    )
    
    if st.button("📄 Draft Document", type="primary", use_container_width=True, key="draft_document_btn"):
        if not st.session_state.document_comparison_result:
            st.error("No comparison analysis found. Please run the comparison in Tab 2 first.")
        else:
            with st.spinner(f"Drafting {doc_type}..."):
                # Create comprehensive prompt using comparison results
                prompt = f"""
                You are a regulatory compliance expert drafting a professional {doc_type}.
                
                **CONTEXT:**
                - Regulatory Framework: {selected_framework}
                - Jurisdiction: {selected_region}
                - Source Document: {st.session_state.selected_document['title'] if st.session_state.selected_document else 'Unknown'}
                - Document Source: {st.session_state.selected_document.get('feed_source', 'Unknown') if st.session_state.selected_document else 'Unknown'}
                
                **COMPARISON ANALYSIS RESULTS:**
                {st.session_state.document_comparison_result}
                
                **DOCUMENT REQUIREMENTS:**
                - Document Type: {doc_type}
                
                **INSTRUCTIONS:**
                1. Base the document entirely on the comparison analysis results above
                2. Focus on the specific changes identified in the "New Obligation" column
                3. Reference the "Impact on Financial Markets" for business justification
                4. Use professional regulatory compliance language
                5. Include specific article/section references from the analysis
                6. Structure the document appropriately for the selected type
                
                **USER FEEDBACK TO CONSIDER:**
                {agent_context}
                
                **OUTPUT FORMAT:**
                Create a well-structured, professional document that compliance teams can use directly.
                Include clear headings, bullet points where appropriate, and actionable recommendations.
                Do not give any disclaimers or mention that this is AI-generated. Make it ready for immediate use by compliance professionals.
                """
                
                response = gemini_model.generate_content(prompt).text
                st.markdown("### 📄 Generated Document")
                st.markdown(response)
                
                # Save to session state for potential export
                st.session_state.generated_deliverable = response
                
                # Export options
                st.write("---")
                st.markdown("#### 📤 Export Options")
                
                export_col1, export_col2 = st.columns(2)
                
                with export_col1:
                    if st.button("📋 Copy to Clipboard", use_container_width=True):
                        st.text_area(
                            "Copy the document below:",
                            value=response,
                            height=200,
                            key="export_deliverable"
                        )
                        st.success("✅ Document ready for copying!")
                
                with export_col2:
                    # Create downloadable content
                    st.download_button(
                        label="💾 Download as Text",
                        data=response,
                        file_name=f"{doc_type.lower().replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                        mime="text/plain",
                        use_container_width=True
                    )