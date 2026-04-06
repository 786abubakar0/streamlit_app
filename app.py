import streamlit as st
from supabase import create_client
import os
from streamlit_js_eval import streamlit_js_eval
import hashlib
from thefuzz import fuzz
import re
import itertools
from datetime import datetime, timezone, timedelta
import extra_streamlit_components as stx
import time

# 1. Setup Supabase
@st.cache_resource
def get_supabase():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_SERVICE_ROLE_KEY"])

supabase = get_supabase()

@st.cache_data(ttl=3600)
def get_branches():
    """Fetches and caches the branch list to prevent database hits."""
    try:
        res = supabase.table("unique_branches").select("branch_name").execute()
        return sorted([row['branch_name'] for row in res.data]) if res.data else []
    except Exception:
        return []

# 2. UI Configuration
st.set_page_config(page_title="Price Comparison PK", layout="wide", page_icon="🛒")

# --- HIDE STREAMLIT ELEMENTS ---
hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            .st-emotion-cache-1639syv {display: none;}
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

# --- Initialize Session States ---
if "compare_basket" not in st.session_state:
    st.session_state.compare_basket = {}
if "cached_results" not in st.session_state:
    st.session_state.cached_results = None
if "auth_token" not in st.session_state:
    st.session_state.auth_token = None
if "searching" not in st.session_state:
    st.session_state.searching = False
if "current_query" not in st.session_state:
    st.session_state.current_query = ""

# 3. Device Security
def verify_device():
    if st.session_state.auth_token:
        return True
    cookie_manager = stx.CookieManager()
    saved_token = None
    for _ in range(5):
        saved_token = cookie_manager.get('auth_token_pk')
        if saved_token: break
        time.sleep(0.1) 

    if not saved_token:
        st.markdown("### 🔐 Device Verification Required")
        ua = streamlit_js_eval(js_expressions="navigator.userAgent", key="ua")
        screen = streamlit_js_eval(js_expressions="screen.width + 'x' + screen.height", key="res")
        cores = streamlit_js_eval(js_expressions="navigator.hardwareConcurrency", key="cores")
        timezone_val = streamlit_js_eval(js_expressions="Intl.DateTimeFormat().resolvedOptions().timeZone", key="tz")
        canvas_js = """(function(){var canvas = document.createElement('canvas');var ctx = canvas.getContext('2d');ctx.textBaseline = "top";ctx.font = "14px 'Arial'";ctx.fillText("PriceCheck-Auth-99", 2, 2);return canvas.toDataURL();})()"""
        canvas_fp = streamlit_js_eval(js_expressions=canvas_js, key="canvas")

        if not all([ua, screen, cores, canvas_fp]):
            with st.spinner("Securely connecting..."):
                time.sleep(0.1)
            return False 

        signature = hashlib.sha256(f"{ua}|{screen}|{cores}|{timezone_val}|{canvas_fp}".encode()).hexdigest()
        token_input = st.text_input("Enter Access Token", type="password", key="login_input")
        btn_place = st.empty()
        
        if btn_place.button("Verify & Save Device", use_container_width=True):
            btn_place.info("⏳ Authenticating...")
            res = supabase.table("authorized_devices").select("*").eq("token", token_input).execute()
            if res.data:
                device = res.data[0]
                if not device["is_active"]: st.error("🚫 Token deactivated.")
                elif device["device_signature"] and device["device_signature"] != signature:
                    st.error("🔒 Token locked to another device.")
                else:
                    cookie_manager.set('auth_token_pk', token_input, expires_at=datetime.now() + timedelta(days=30))
                    st.session_state.auth_token = token_input
                    st.success("✅ Access Granted!")
                    time.sleep(0.6) 
                    st.rerun()
            else:
                st.error("❌ Invalid Token.")
        return False
    st.session_state.auth_token = saved_token
    return True

# --- Helpers ---
def format_time_ago(timestamp_str):
    if not timestamp_str: return "Unknown"
    try:
        dt_fetched = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        diff = datetime.now(timezone.utc) - dt_fetched
        s = diff.total_seconds()
        if s < 60: return f"{int(s)}s ago"
        elif s < 3600: return f"{int(s // 60)}m ago"
        elif s < 86400: return f"{int(s // 3600)}h ago"
        else: return f"{int(s // 86400)}d ago"
    except: return "Recently"

def normalize_text(text):
    if not text: return ""
    text = re.sub(r'[^\w\s]', '', text.lower()) 
    return " ".join([w[:-1] if w.endswith('s') and len(w) > 3 else w for w in text.split()])

def safe_float(val):
    try: return float(val) if val else None
    except: return None

def calculate_display_price(item):
    b = item.get('branch_name', '').lower()
    s, o = safe_float(item.get('sale_price')), safe_float(item.get('original_price'))
    if 'alfatah' in b: return s or o
    if 'metro' in b: return s if item.get('is_sale') else o
    return s or o

def check_stock_status(item):
    if item.get('is_available') is False: return False
    s, l = safe_float(item.get('total_stock')), safe_float(item.get('max_allow_per_order'))
    if s is not None and s <= 0: return False
    if l is not None and l <= 0: return False
    return True

def render_product_row(item, is_comparison=False):
    # 1. Create a truly unique ID using Title + Branch
    unique_id = hashlib.md5(f"{item['title']}{item['branch_name']}".encode()).hexdigest()
    
    # 2. Add a prefix based on WHERE it is being rendered
    prefix = "comp" if is_comparison else "search"
    cb_key = f"{prefix}_{unique_id}_{item['branch_name']}"

    def toggle_basket():
        if st.session_state[cb_key]:
            st.session_state.compare_basket[unique_id] = item
        else:
            st.session_state.compare_basket.pop(unique_id, None)

    # --- MAIN ROW ---
    cols = st.columns([0.5, 3, 1, 1, 1])
    in_basket = unique_id in st.session_state.compare_basket
    
    cols[0].checkbox(
        " ", 
        key=cb_key, 
        value=in_basket, 
        on_change=toggle_basket
    )

    with cols[1]:
        st.markdown(f"**{item['title']}**")
        st.caption(f"🏪 {item['branch_name']} | 🕒 {item['time_ago']}")
    
    p = item['display_price']
    cols[2].markdown(f"#### Rs. {int(p)}" if p else "N/A")
    cols[3].markdown(f"### {'✅' if item['is_actually_in_stock'] else '❌'}")
    
    if item.get('url'): 
        cols[4].link_button("Visit", item['url'], use_container_width=True)

    # --- SHOW DETAILS (The missing part) ---
    with st.expander("📦 View Stock Details"):
        d_cols = st.columns(2)
        
        # Total Stock info
        stock = item.get('total_stock', 'N/A')
        d_cols[0].write(f"**Total Stock:** {stock}")
        
        # Per Order Limit info
        limit = item.get('max_allow_per_order', 'N/A')
        d_cols[1].write(f"**Limit per Order:** {limit}")
        
        # Check if actually out of stock based on backend logic
        if not item['is_actually_in_stock']:
            st.warning("⚠️ This item is currently unavailable at this branch.")

    st.divider()
# 4. Main App Logic
if verify_device():
    st.title("🛒 Price Comparison PK")

    # --- SIDEBAR ---
    st.sidebar.header("Search Settings")
    all_branches = get_branches()
    selected_branches = st.sidebar.multiselect(
        "Branches", 
        all_branches, 
        default=all_branches, 
        disabled=st.session_state.searching
    )
    
    st.sidebar.divider()
    st.sidebar.subheader("⚖️ Comparison Basket")
    basket_count = len(st.session_state.compare_basket)
    st.sidebar.metric("Items Selected", basket_count)
    
    if basket_count > 0:
        if st.sidebar.button("🗑️ Clear All Selected", disabled=st.session_state.searching):
            st.session_state.compare_basket = {}
            st.rerun()
    else:
        st.sidebar.info("Select items to compare.")

    # --- SEARCH FORM (With doubling fix) ---
    search_placeholder = st.empty()

    with search_placeholder.container():
        with st.form("search_form"):
            search_input = st.text_input("Search products...", disabled=st.session_state.searching)
            if st.form_submit_button("Search", disabled=st.session_state.searching, use_container_width=True):
                if search_input:
                    st.session_state.searching = True
                    st.session_state.current_query = search_input
                    st.rerun()

    # --- SEARCH PROCESSING (Phase 2) ---
    if st.session_state.searching:
        # Immediately clear the form placeholder to prevent visual doubling
        search_placeholder.empty()
        
        all_candidates = []
        with st.status("🔍 Searching Database...", expanded=True) as status:
            raw_q = st.session_state.current_query
            clean_q = normalize_text(raw_q)
            words = [w for w in clean_q.split() if len(w) >= 2]
            fields = "title, url, original_price, is_sale, sale_price, total_stock, max_allow_per_order, is_available, branch_name, fetched_at"
            
            try:
                # 1. Primary Pair Match
                if len(words) >= 2:
                    prefs = [w[:3] for w in words]
                    conds = [f"and(title.ilike.%{p1}%,title.ilike.%{p2}%)" for p1, p2 in itertools.combinations(prefs, 2)]
                    for b in selected_branches:
                        res = supabase.table("products").select(fields).eq("branch_name", b).or_(",".join(conds)).limit(80).execute()
                        if res.data: all_candidates.extend(res.data)
                
                # 2. Fallback (Mezan2 fix)
                if not all_candidates:
                    search_term = words[0] if words else clean_q
                    pref = search_term[:3] 
                    for b in selected_branches:
                        res = supabase.table("products").select(fields).eq("branch_name", b).ilike('title', f"%{pref}%").limit(100).execute()
                        if res.data: all_candidates.extend(res.data)
                
                status.update(label=f"✅ Found {len(all_candidates)} candidates", state="complete", expanded=False)
            except Exception as e:
                status.update(label="❌ Error", state="error")
                st.error(str(e))

        if all_candidates:
            branch_buckets = {b: [] for b in selected_branches}
            
            # 1. CLEAN THE QUERY for the Distance Calculation
            # This removes numbers/symbols so "Mezan2" -> "mezan"
            # This ensures the distance to "Mezan Oil" stays as small as possible
            clean_q_for_dist = raw_q.lower().strip()
            
            for item in all_candidates:
                item['display_price'] = calculate_display_price(item)
                item['is_actually_in_stock'] = check_stock_status(item)
                item['time_ago'] = format_time_ago(item.get('fetched_at'))
                
                # 2. CALCULATE DISTANCE SCORE (0 to 100)
                # fuzz.ratio is the direct implementation of Levenshtein Distance
                # turned into a percentage: 100 = 0 distance, 0 = maximum distance.
                # item['match_score'] = fuzz.ratio(clean_q_for_dist, item['title'].lower()[:len(clean_q_for_dist)])
                item['match_score'] = fuzz.partial_ratio(clean_q_for_dist, item['title'].lower())
                # We use a threshold of 20 just to filter out completely unrelated text
                if item['match_score'] >= 20:
                    b_n = item['branch_name']
                    if b_n in branch_buckets:
                        branch_buckets[b_n].append(item)
            
            # 3. SORT BY DISTANCE & PICK TOP 50
            for b in branch_buckets:
                # Sort: Highest score (Lowest Levenshtein Distance) first
                sorted_list = sorted(branch_buckets[b], key=lambda x: x['match_score'], reverse=True)
                # Display only the 50 most relevant
                branch_buckets[b] = sorted_list[:50]
                
            st.session_state.cached_results = branch_buckets
        else:
            st.session_state.cached_results = None
        
        st.session_state.searching = False
        st.rerun()

    # --- DISPLAY ---
    if st.session_state.cached_results or st.session_state.compare_basket:
        tab_list = list(selected_branches) + ["📊 COMPARE SELECTED"]
        tabs = st.tabs(tab_list)
        for i, b in enumerate(selected_branches):
            with tabs[i]:
                items = st.session_state.cached_results.get(b, []) if st.session_state.cached_results else []
                if not items: st.info(f"No results for {b}.")
                else:
                    for item in items: render_product_row(item)
        with tabs[-1]:
            if not st.session_state.compare_basket: st.warning("No items selected.")
            else:
                st.subheader(f"⚖️ Comparing {len(st.session_state.compare_basket)} items")
                sorted_b = sorted(st.session_state.compare_basket.values(), key=lambda x: x['display_price'] or 999999)
                for item in sorted_b: render_product_row(item, is_comparison=True)
