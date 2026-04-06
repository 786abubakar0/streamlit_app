import streamlit as st
from supabase import create_client
import os
from streamlit_js_eval import streamlit_js_eval
import hashlib
from thefuzz import fuzz
import re
import itertools
from datetime import datetime, timezone 

# 1. Setup Supabase
@st.cache_resource
def get_supabase():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_SERVICE_ROLE_KEY"])

supabase = get_supabase()

@st.cache_data(ttl=3600)
def get_branches():
    """Fetches and caches the branch list to prevent database hits on every rerun."""
    try:
        res = supabase.table("unique_branches").select("branch_name").execute()
        return sorted([row['branch_name'] for row in res.data]) if res.data else []
    except Exception:
        return []
# 2. UI Configuration
st.set_page_config(page_title="Price Comparison PK", layout="wide", page_icon="🛒")

# --- Initialize Session States ---
if "compare_basket" not in st.session_state:
    st.session_state.compare_basket = {}

if "cached_results" not in st.session_state:
    st.session_state.cached_results = None

# 3. Device Security
def verify_device():
    ua = streamlit_js_eval(js_expressions="navigator.userAgent", key="ua")
    screen = streamlit_js_eval(js_expressions="screen.width + 'x' + screen.height", key="res")
    cores = streamlit_js_eval(js_expressions="navigator.hardwareConcurrency", key="cores")
    timezone_val = streamlit_js_eval(js_expressions="Intl.DateTimeFormat().resolvedOptions().timeZone", key="tz")
    canvas_js = """(function(){var canvas = document.createElement('canvas');var ctx = canvas.getContext('2d');ctx.textBaseline = "top";ctx.font = "14px 'Arial'";ctx.fillText("PriceCheck-Auth-99", 2, 2);return canvas.toDataURL();})()"""
    canvas_fp = streamlit_js_eval(js_expressions=canvas_js, key="canvas")

    if not all([ua, screen, cores, canvas_fp]):
        return False 

    signature = hashlib.sha256(f"{ua}|{screen}|{cores}|{timezone_val}|{canvas_fp}".encode()).hexdigest()

    if "auth_token" not in st.session_state:
        st.markdown("### 🔐 Device Verification Required")
        token = st.text_input("Enter Access Token", type="password")
        if st.button("Verify Device"):
            res = supabase.table("authorized_devices").select("*").eq("token", token).execute()
            if res.data:
                device = res.data[0]
                if not device["is_active"]: return False
                if device["device_signature"] and device["device_signature"] != signature: return False
                if not device["device_signature"]:
                    supabase.table("authorized_devices").update({"device_signature": signature}).eq("token", token).execute()
                st.session_state.auth_token = token
                st.rerun()
            else: st.error("Invalid Token.")
        return False
    return True

# --- Internal Logic Helpers ---
def format_time_ago(timestamp_str):
    if not timestamp_str: return "Unknown"
    try:
        clean_ts = timestamp_str.replace('Z', '+00:00')
        dt_fetched = datetime.fromisoformat(clean_ts)
        now_utc = datetime.now(timezone.utc)
        diff = now_utc - dt_fetched
        seconds = diff.total_seconds()
        if seconds < 0: return "Just now"
        if seconds < 60: return f"{int(seconds)}s ago"
        elif seconds < 3600: return f"{int(seconds // 60)}m ago"
        elif seconds < 86400: return f"{int(seconds // 3600)}h ago"
        else: return f"{int(seconds // 86400)}d ago"
    except: return "Recently"

def normalize_text(text):
    if not text: return ""
    text = text.lower()
    text = re.sub(r'[^\w\s]', '', text) 
    words = text.split()
    normalized = [w[:-1] if w.endswith('s') and len(w) > 3 else w for w in words]
    return " ".join(normalized)

def safe_float(val):
    if val is None or val == "": return None
    try: return float(val)
    except: return None

def calculate_display_price(item):
    b_name = item.get('branch_name', '').lower()
    s_p, o_p = safe_float(item.get('sale_price')), safe_float(item.get('original_price'))
    if 'alfatah' in b_name: return s_p or o_p
    elif 'metro' in b_name: return s_p if item.get('is_sale') else o_p
    return s_p or o_p

def check_stock_status(item):
    if item.get('is_available') is False: return False
    stock, limit = safe_float(item.get('total_stock')), safe_float(item.get('max_allow_per_order'))
    if stock is not None and stock <= 0: return False
    if limit is not None and limit <= 0: return False
    return True

# Helper to render row (Exactly same UI for all tabs)
def render_product_row(item, is_comparison=False):
    item_id = hashlib.md5(f"{item['title']}{item['branch_name']}".encode()).hexdigest()
    cols = st.columns([0.5, 3, 1, 1, 1])
    in_basket = item_id in st.session_state.compare_basket
    
    # Checkbox logic
    key_prefix = "c" if is_comparison else "t"
    check = cols[0].checkbox(" ", key=f"{key_prefix}_{item_id}", value=in_basket)
    
    if check != in_basket:
        if check: st.session_state.compare_basket[item_id] = item
        else: 
            if item_id in st.session_state.compare_basket:
                del st.session_state.compare_basket[item_id]
        st.rerun()

    with cols[1]:
        st.markdown(f"**{item['title']}**")
        st.caption(f"🏪 {item['branch_name']} | 🕒 {item['time_ago']}")
    
    price = item['display_price']
    cols[2].markdown(f"#### Rs. {int(price)}" if price else "N/A")
    cols[3].markdown(f"### {'✅' if item['is_actually_in_stock'] else '❌'}")
    
    if item.get('url'):
        cols[4].link_button("Visit", item['url'], use_container_width=True)
    
    with st.expander("🔍 Details"):
        e1, e2 = st.columns(2)
        e1.write(f"📦 Stock: {item.get('total_stock') or 'N/A'}")
        e2.write(f"🚫 Limit: {item.get('max_allow_per_order') or 'N/A'}")
        if item.get('is_sale'): st.info("🔥 Sale Active")
    st.divider()

# 4. Main App Logic
if verify_device():
    st.title("🛒 Price Comparison PK")

    # --- SIDEBAR ---
    st.sidebar.header("Search Settings")
    
    # branch_res = supabase.table("unique_branches").select("branch_name").execute()
    # all_branches = sorted([row['branch_name'] for row in branch_res.data]) if branch_res.data else []
    all_branches = get_branches()
    selected_branches = st.sidebar.multiselect("Select Branches", all_branches, default=all_branches)
    
    st.sidebar.divider()
    st.sidebar.subheader("⚖️ Comparison Basket")
    
    # Restored Count Feature
    basket_count = len(st.session_state.compare_basket)
    st.sidebar.metric("Items Selected", basket_count)
    
    if basket_count > 0:
        if st.sidebar.button("🗑️ Clear All Selected"):
            st.session_state.compare_basket = {}
            st.rerun()
    else:
        st.sidebar.info("Select items to compare prices.")

    # --- MAIN SEARCH FORM ---
    with st.form("search_form"):
        search_input = st.text_input("Search products...", placeholder="e.g. Olpers Milk")
        submit_search = st.form_submit_button("Search")

    if submit_search and search_input:
        print(f"DEBUG: Making a real database request for: {search_input}") # Check your terminal for this
        clean_query = normalize_text(search_input)
        search_words = [w for w in clean_query.split() if len(w) >= 3]
        all_candidates = []

        with st.spinner("Fetching data..."):
            fields = "title, url, original_price, is_sale, sale_price, total_stock, max_allow_per_order, is_available, branch_name, fetched_at"
            
            # Restoration of your prefix-based logic
            if len(search_words) >= 2:
                word_prefixes = [w[:3] for w in search_words]
                pairs = list(itertools.combinations(word_prefixes, 2))
                or_conditions = [f"and(title.ilike.%{p1}%,title.ilike.%{p2}%)" for p1, p2 in pairs]
                or_filter = ",".join(or_conditions)

                for branch in selected_branches:
                    res = supabase.table("products").select(fields).eq("branch_name", branch).or_(or_filter).limit(80).execute()
                    if res.data: all_candidates.extend(res.data)
            else:
                prefix = search_words[0][:3] if search_words else clean_query[:3]
                for branch in selected_branches:
                    res = supabase.table("products").select(fields).eq("branch_name", branch).ilike('title', f"%{prefix}%").limit(80).execute()
                    if res.data: all_candidates.extend(res.data)

        if all_candidates:
            INTERNAL_MATCH_LIMIT = 40
            MAX_AGE_SECONDS = 20 * 3600  # 20 hours in seconds
            branch_buckets = {b: [] for b in selected_branches}
            
            # 1. Create a list to hold only items that pass the age check
            fresh_items = []
            
            for item in all_candidates:
                try:
                    clean_ts = item.get('fetched_at').replace('Z', '+00:00')
                    dt_fetched = datetime.fromisoformat(clean_ts)
                    now_utc = datetime.now(timezone.utc)
                    age_seconds = (now_utc - dt_fetched).total_seconds()
                except:
                    age_seconds = float('inf')

                # Skip items older than 20 hours
                if age_seconds > MAX_AGE_SECONDS:
                    continue

                # 2. Process only fresh items (assign keys)
                item['display_price'] = calculate_display_price(item)
                item['is_actually_in_stock'] = check_stock_status(item)
                item['time_ago'] = format_time_ago(item.get('fetched_at'))
                item['match_score'] = fuzz.token_set_ratio(clean_query, normalize_text(item['title']))
                
                fresh_items.append(item)

            # 3. Sort and bucket ONLY the fresh items
            if fresh_items:
                # We sort fresh_items because we know they all have 'match_score'
                sorted_pool = sorted(fresh_items, key=lambda x: x['match_score'], reverse=True)
                
                for item in sorted_pool:
                    b_name = item['branch_name']
                    if b_name in branch_buckets and len(branch_buckets[b_name]) < 50:
                        if item['match_score'] >= INTERNAL_MATCH_LIMIT:
                            branch_buckets[b_name].append(item)
                
                st.session_state.cached_results = branch_buckets
            else:
                # Handle case where results were found but all were stale
                st.session_state.cached_results = None
                st.warning("All matching products found are older than 20 hours.")
        else:
            st.session_state.cached_results = None
            st.warning("No products found.")

    # --- DISPLAY RESULTS ---
    if st.session_state.cached_results or st.session_state.compare_basket:
        tab_list = list(selected_branches) + ["📊 COMPARE SELECTED"]
        tabs = st.tabs(tab_list)

        # Store Tabs
        for i, branch in enumerate(selected_branches):
            with tabs[i]:
                items = st.session_state.cached_results.get(branch, []) if st.session_state.cached_results else []
                if not items:
                    st.info(f"No active search results for {branch}.")
                else:
                    for item in items:
                        render_product_row(item)

        # Comparison Tab
        with tabs[-1]:
            if not st.session_state.compare_basket:
                st.warning("No items selected for comparison.")
            else:
                st.subheader(f"⚖️ Comparing {len(st.session_state.compare_basket)} items")
                # Sort basket by price
                sorted_basket = sorted(st.session_state.compare_basket.values(), 
                                      key=lambda x: x['display_price'] if x['display_price'] is not None else float('inf'))
                for item in sorted_basket:
                    render_product_row(item, is_comparison=True)