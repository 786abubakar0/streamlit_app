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
# Initialize CookieManager GLOBALLY to ensure browser persistence
cookie_manager = stx.CookieManager(key="main_cookie_manager")

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
# --- HIDE STREAMLIT ELEMENTS (Improved) ---
hide_st_style = """
            <style>
            /* Hide the Main Menu and Footer */
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            
            /* DO NOT hide the header entirely, just the parts we don't want */
            /* This ensures the sidebar toggle button stays visible on mobile */
            header[data-testid="stHeader"] {
                background: rgba(0,0,0,0);
            }
            
            /* Remove the 'Made with Streamlit' link specifically */
            div[data-testid="stStatusWidget"] {display: none;}

/* 1. The Outer Container (Red Box) */
    [data-testid="stCheckbox"] {
        display: flex !important;
        justify-content: center !important; 
        align-items: center !important;     
        padding: 5px !important; 
        background-color: rgba(255, 75, 75, 0.6) !important;
        border-radius: 8px;
        width: fit-content !important;
        margin: 0 auto !important; /* Centers the red box in the column */
    }

    /* 2. Target the Label (The immediate child) */
    [data-testid="stCheckbox"] > label {
        display: flex !important;
        justify-content: center !important;
        align-items: center !important;
        width: 100% !important;
        margin: 0 !important;
        padding: 0 !important;
        gap: 0px !important; /* Removes gap between box and ghost label */
    }

    /* 3. Target the Span (The actual Checkbox square) */
    [data-testid="stCheckbox"] span {
        margin: 0 !important; /* Removes Streamlit's default right margin */
        flex-shrink: 0 !important;
    }

    /* 4. Hide the internal label div that takes up space */
    [data-testid="stCheckbox"] label > div {
        display: none !important;
        width: 0px !important;
    }



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
# Global counter to prevent duplicate Streamlit keys in a single run
if "key_counter" not in st.session_state:
    st.session_state.key_counter = 0
if "auth_loading" not in st.session_state:
    st.session_state.auth_loading = False
    
# 4. Security Guard (Fixed Retry & Persistence)
SESSION_EXPIRY_DAYS = 1 

def verify_device():
    if st.session_state.get('auth_token'): return True

    saved_data = cookie_manager.get('auth_token_v2')
    if saved_data and "|" in saved_data:
        try:
            saved_token, saved_ts = saved_data.split("|")
            if (datetime.now() - datetime.fromisoformat(saved_ts)) < timedelta(days=SESSION_EXPIRY_DAYS):
                st.session_state.auth_token = saved_token
                return True
        except: cookie_manager.delete('auth_token_v2')
            
    st.markdown("### 🔐 Device Verification Required")
    ua = streamlit_js_eval(js_expressions="navigator.userAgent", key="ua")
    screen = streamlit_js_eval(js_expressions="screen.width + 'x' + screen.height", key="res")
    cores = streamlit_js_eval(js_expressions="navigator.hardwareConcurrency", key="cores")
    tz = streamlit_js_eval(js_expressions="Intl.DateTimeFormat().resolvedOptions().timeZone", key="tz")
    canvas = streamlit_js_eval(js_expressions="(function(){var canvas = document.createElement('canvas');var ctx = canvas.getContext('2d');ctx.textBaseline='top';ctx.font='14px Arial';ctx.fillText('PriceCheck-Auth-99',2,2);return canvas.toDataURL();})()", key="canvas")

    if not all([ua, screen, cores, canvas]):
        st.info("🔄 Establishing secure connection...")
        return False 

    signature = hashlib.sha256(f"{ua}|{screen}|{cores}|{tz}|{canvas}".encode()).hexdigest()
    token_input = st.text_input("Enter Access Token", type="password", key="login_input", disabled=st.session_state.auth_loading)
    btn_place = st.empty()
    
    if not st.session_state.auth_loading:
        if btn_place.button("Verify & Save Device", use_container_width=True, type="primary"):
            st.session_state.auth_loading = True
            st.rerun()
    else:
        btn_place.info("⏳ Authenticating...")
        try:
            res = supabase.table("authorized_devices").select("*").eq("token", st.session_state.login_input).execute()
            if res.data:
                device = res.data[0]
                if not device["is_active"]: st.error("🚫 Token deactivated.")
                elif device["device_signature"] and device["device_signature"] != signature:
                    st.error("🔒 Token locked to another device.")
                else:
                    if not device["device_signature"]:
                        supabase.table("authorized_devices").update({"device_signature": signature}).eq("token", st.session_state.login_input).execute()
                    
                    cookie_manager.set('auth_token_v2', f"{st.session_state.login_input}|{datetime.now().isoformat()}", expires_at=datetime.now() + timedelta(days=SESSION_EXPIRY_DAYS))
                    st.session_state.auth_token = st.session_state.login_input
                    st.session_state.auth_loading = False
                    st.success("✅ Access Granted!")
                    time.sleep(1)
                    st.rerun()
            else: st.error("❌ Invalid Token.")
        except Exception as e: st.error(f"⚠️ Error: {e}")
        
        st.session_state.auth_loading = False
        if st.button("🔄 Try Again", use_container_width=True): st.rerun()
    return False

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
    s = safe_float(item.get('sale_price'))
    o = safe_float(item.get('original_price'))
    is_sale_flag = item.get('is_sale') # Usually a boolean True/False

    # 1. METRO RULE: Strict check on the 'is_sale' flag
    if 'metro' in b:
        return s if is_sale_flag is True else o

    # 2. FOODPANDA & AL-FATAH RULE: If sale exists, show it; else original
    # (This also covers any other branches you might add later)
    if s is not None:
        return s
    
    return o

def check_stock_status(item):
    # 1. Immediate exit if explicitly marked unavailable
    if item.get('is_available') is False: 
        return False
    
    # 2. Get values and convert to float, default to None if conversion fails
    s_raw = item.get('total_stock')
    l_raw = item.get('max_allow_per_order')
    
    s = safe_float(s_raw)
    l = safe_float(l_raw)
    
    # 3. STRICT CHECK: If it is a number and it is 0 or less, it's out of stock
    # We use 'is not None' to make sure we don't accidentally block products
    # that simply don't have stock data in the DB.
    if s is not None and s <= 0: 
        return False
        
    if l is not None and l <= 0: 
        return False
        
    # 4. TRAP FOR STRINGS: Sometimes '0' comes as a string "0"
    if str(s_raw).strip() == "0" or str(l_raw).strip() == "0":
        return False

    return True

def render_product_row(item, is_comparison=False):
    # Increment counter for every row rendered to ensure absolute key uniqueness
    st.session_state.key_counter += 1
    count = st.session_state.key_counter

    # 1. Generate a ID for the product data itself
    unique_string = f"{item['title']}{item['branch_name']}{item.get('url', '')}"
    unique_id = hashlib.md5(unique_string.encode()).hexdigest()
    
    # 2. Define specific keys using the counter to prevent DuplicateKey errors
    prefix = "comp" if is_comparison else "search"
    cb_key = f"{prefix}_{unique_id}_{count}"

    def toggle_basket():
        # 1. Get the new value from the checkbox just clicked
        new_val = st.session_state[cb_key]
        
        # 2. Update the Comparison Basket (The Source of Truth)
        if new_val:
            st.session_state.compare_basket[unique_id] = item
        else:
            st.session_state.compare_basket.pop(unique_id, None)
        
        # 3. Synchronize all other checkbox keys associated with this product
        # This ensures if you click it in the Store Tab, it updates in Comparison, and vice versa
        prefix_to_sync = "comp" if not is_comparison else "search"
        
        # We look for any keys in session_state that match this product's unique_id
        for key in st.session_state.keys():
            if key.startswith(prefix_to_sync) and unique_id in key:
                st.session_state[key] = new_val
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
        stock = item.get('total_stock', 'N/A')
        limit = item.get('max_allow_per_order', 'N/A')
        st.markdown(f"**{item['title']}**")
        st.caption(f"🏪 {item['branch_name']} | 🕒 {item['time_ago']} | 📦 Stock: {stock} | 🚫 Limit: {limit}")
        # st.caption(f"📦 Stock: {stock} | 🚫 Limit: {limit}")
    p = item['display_price']
    cols[2].markdown(f"#### Rs. {int(p)}" if p else "N/A")
    cols[3].markdown(f"### {'✅' if item['is_actually_in_stock'] else '❌'}")
    
    if item.get('url'): 
        cols[4].link_button("Visit", item['url'], use_container_width=True)

    st.divider()
# 4. Main App Logic
if verify_device():
    st.session_state.key_counter = 0  # Reset counter at start of every rerun
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
        if st.sidebar.button("🗑️ Clear Basket", disabled=st.session_state.searching):
            # 1. Clear the source of truth
            st.session_state.compare_basket = {}
            
            # 2. Reset all visual checkbox states in session_state
            # This finds every checkbox key (search_ and comp_) and sets it to False
            for key in list(st.session_state.keys()):
                if key.startswith("search_") or key.startswith("comp_"):
                    st.session_state[key] = False
            
            # 3. Force refresh to update the UI
            st.rerun()
    else:
        st.sidebar.info("Select items to compare.")

    # --- SEARCH FORM (With doubling fix) ---
    # --- SEARCH FORM (Improved doubling fix) ---
    search_placeholder = st.empty()

    if not st.session_state.searching:
        with search_placeholder.container():
            with st.form("search_form"):
                search_input = st.text_input("Search products...", value=st.session_state.current_query)
                if st.form_submit_button("Search", use_container_width=True, type="primary"):
                    if search_input:
                        st.session_state.searching = True
                        st.session_state.current_query = search_input
                        st.rerun()
    else:
        # This replaces the entire form area with an info box during the process
        search_placeholder.info(f"🔎 Searching for: **{st.session_state.current_query}**")

    # --- SEARCH PROCESSING (Phase 2) ---
    if st.session_state.searching:
        # Immediately clear the form placeholder to prevent visual doubling
        # search_placeholder.empty()
        
        all_candidates = []
        with st.status("🔍 Searching Database...", expanded=True) as status:
            raw_q = st.session_state.current_query
            clean_q = normalize_text(raw_q)
            words = [w for w in clean_q.split() if len(w) >= 2]
            fields = "title, url, original_price, is_sale, sale_price, total_stock, max_allow_per_order, is_available, branch_name, fetched_at"
            
            try:
                # Use the optimized RPC function instead of manual table filtering [cite: 91, 95]
                res = supabase.rpc(
                    "foodpanda_search_v5", 
                    {
                        "search_term": raw_q, 
                        "selected_branches": selected_branches
                    }
                ).execute()

                if res.data:
                    all_candidates = res.data
                
                status.update(label=f"✅ Found {len(all_candidates)} candidates", state="complete", expanded=False)
            except Exception as e:
                status.update(label="❌ Error", state="error")
                st.error(str(e))

        if all_candidates:
            branch_buckets = {b: [] for b in selected_branches}
            
            for item in all_candidates:
                # Still check freshness in Python to ensure 20-hour rule [cite: 98, 99]
                fetched_at = item.get('fetched_at')
                is_fresh = True
                if fetched_at:
                    dt_fetched = datetime.fromisoformat(fetched_at.replace('Z', '+00:00'))
                    age_hours = (datetime.now(timezone.utc) - dt_fetched).total_seconds() / 3600
                    if age_hours >= 20:
                        is_fresh = False
                
                if is_fresh:
                    # Apply helper formatting [cite: 77, 78, 80]
                    item['display_price'] = calculate_display_price(item)
                    item['is_actually_in_stock'] = check_stock_status(item)
                    item['time_ago'] = format_time_ago(item.get('fetched_at'))
                    
                    b_n = item['branch_name']
                    if b_n in branch_buckets:
                        branch_buckets[b_n].append(item)
            
            # The RPC already sorts by relevance, so we just take the top 50 per branch [cite: 104]
            for b in branch_buckets:
                branch_buckets[b] = branch_buckets[b][:50]
                
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
