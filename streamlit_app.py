import streamlit as st
import hashlib
from pyairtable import Table
import requests
import stripe
from datetime import datetime, timedelta, timezone
from dateutil.relativedelta import relativedelta

# Streamlit configuration
st.set_page_config(page_title="SaaS Content Dashboard", page_icon="📝", layout="wide")
st.markdown("""
    <style>
    .stApp {
        background-color: #F0F2F6;
        color: #2E2E2E;
        font-family: 'Arial', sans-serif;
    }
    .stTextInput > div > div > input, .stTextArea > div > div > textarea {
        background-color: #FFFFFF;
        color: #2E2E2E;
        border: 1px solid #D1D5DB;
        border-radius: 8px;
        padding: 8px;
    }
    .stButton > button {
        background-color: #10B981;
        color: white;
        border-radius: 8px;
        padding: 8px 16px;
        font-weight: 500;
        transition: background-color 0.3s;
    }
    .stButton > button:hover {
        background-color: #059669;
    }
    .stButton > button[type="secondary"] {
        background-color: #6B7280;
    }
    .stButton > button[type="secondary"]:hover {
        background-color: #4B5563;
    }
    .stButton > button.cancel-btn {
        background-color: #EF4444;
    }
    .stButton > button.cancel-btn:hover {
        background-color: #DC2626;
    }
    .stSelectbox > div > div {
        background-color: #FFFFFF;
        color: #2E2E2E;
        border: 1px solid #D1D5DB;
        border-radius: 8px;
    }
    .popup-container {
        background-color: #FFFFFF;
        padding: 20px;
        border-radius: 10px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        text-align: center;
        max-width: 400px;
        margin: 20px auto;
    }
    .content-card {
        background-color: #FFFFFF;
        border: 1px solid #E5E7EB;
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 12px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
        transition: box-shadow 0.3s;
    }
    .content-card:hover {
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
    }
    .content-title {
        font-size: 18px;
        font-weight: 600;
        color: #1F2937;
        margin-bottom: 8px;
    }
    .content-meta {
        font-size: 14px;
        color: #6B7280;
    }
    .sidebar .sidebar-content {
        background-color: #FFFFFF;
        padding: 20px;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
    }
    h1, h2, h3 {
        color: #1F2937;
    }
    .stats-box {
        background-color: #FFFFFF;
        padding: 15px;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
        margin-bottom: 20px;
    }
    </style>
""", unsafe_allow_html=True)

# Secrets
try:
    AIRTABLE_TOKEN = st.secrets["airtable"]["token"]
    AIRTABLE_BASE_ID = st.secrets["airtable"]["base_id"]
    AIRTABLE_USERS_TABLE = st.secrets["airtable"]["users_table"]
    AIRTABLE_CONTENT_TABLE = st.secrets["airtable"]["content_table"]
    stripe.api_key = st.secrets["stripe"]["secret_key"]
except KeyError as e:
    st.error(f"Missing secret: {str(e)}. Please check your secrets configuration.")
    st.stop()

# Airtable clients
users_table = Table(AIRTABLE_TOKEN, AIRTABLE_BASE_ID, AIRTABLE_USERS_TABLE)
content_table = Table(AIRTABLE_TOKEN, AIRTABLE_BASE_ID, AIRTABLE_CONTENT_TABLE)

# Token costs
TOKEN_COSTS = {
    "Blog Post": 5,
    "SEO Article": 7,
    "Social Media Post": 2
}

# Hash password
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Verify user
def verify_user(email, password):
    records = users_table.all(formula=f"{{Email}}='{email}'")
    if records and records[0]['fields'].get('Password') == hash_password(password):
        return True, records[0]['id']
    return False, None

# Create user
def create_user(email, password):
    if users_table.all(formula=f"{{Email}}='{email}'"):
        return False, "Email already exists"
    users_table.create({
        "Email": email,
        "Password": hash_password(password),
        "Subscription": "Free",
        "Tokens": 10,
        "LastReset": datetime.now(timezone.utc).isoformat()
    })
    return True, "Account created"

# Get subscription status
def get_subscription_status(user_id):
    record = users_table.get(user_id)
    sub_status = record['fields'].get('Subscription', 'Free')
    sub_end = record['fields'].get('SubscriptionEnd')
    if sub_status == "Premium" and sub_end:
        try:
            sub_end_date = datetime.fromisoformat(sub_end)
            if sub_end_date.tzinfo is None:
                sub_end_date = sub_end_date.replace(tzinfo=timezone.utc)
        except ValueError:
            sub_end_date = datetime.strptime(sub_end, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        if sub_end_date < datetime.now(timezone.utc):
            users_table.update(user_id, {"Subscription": "Free"})
            return "Free"
    return sub_status

# Get user data (subscription and tokens)
def get_user_data(user_id):
    record = users_table.get(user_id)
    sub_status = record['fields'].get('Subscription', 'Free')
    tokens = record['fields'].get('Tokens', 0)
    last_reset = record['fields'].get('LastReset')
    
    if last_reset:
        try:
            last_reset_date = datetime.fromisoformat(last_reset)
            if last_reset_date.tzinfo is None:
                last_reset_date = last_reset_date.replace(tzinfo=timezone.utc)
        except ValueError:
            last_reset_date = datetime.strptime(last_reset, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) >= last_reset_date + relativedelta(months=1):
            tokens = 10 if sub_status == "Free" else 100
            users_table.update(user_id, {
                "Tokens": tokens,
                "LastReset": datetime.now(timezone.utc).isoformat()
            })
    return sub_status, tokens

# Update subscription
def update_subscription(user_id, status, end_date=None):
    fields = {"Subscription": status}
    if end_date:
        fields["SubscriptionEnd"] = end_date.isoformat()
    users_table.update(user_id, fields)

# Update tokens
def update_tokens(user_id, token_change):
    current_tokens = get_user_data(user_id)[1]
    new_tokens = max(0, current_tokens + token_change)
    users_table.update(user_id, {"Tokens": new_tokens})
    return new_tokens

# Fetch user content with filters
def get_user_content(user_id, content_type_filter=None, status_filter=None, date_range=None):
    usr_email = st.session_state['user_email']
    formula = f"{{UserID}}='{usr_email}'"
    records = content_table.all(formula=formula)
    filtered_records = []
    
    # Default date range if None
    if date_range is None or len(date_range) == 0:
        start_date = datetime.min.replace(tzinfo=timezone.utc)
        end_date = datetime.max.replace(tzinfo=timezone.utc)
    else:
        start_date = datetime.combine(date_range[0], datetime.min.time(), tzinfo=timezone.utc)
        end_date = datetime.combine(date_range[1] if len(date_range) > 1 else date_range[0], datetime.max.time(), tzinfo=timezone.utc)

    for record in records:
        fields = record['fields']
        created_time = datetime.fromisoformat(record['createdTime']).replace(tzinfo=timezone.utc)
        matches = True
        
        if content_type_filter and content_type_filter != "All" and fields.get('ContentType') != content_type_filter:
            matches = False
        if status_filter and status_filter != "All" and fields.get('Status') != status_filter:
            matches = False
        if created_time < start_date or created_time > end_date:
            matches = False
        
        if matches:
            filtered_records.append(record)
    
    return filtered_records

# Get usage stats
def get_usage_stats(user_id):
    usr_email = st.session_state['user_email']
    records = content_table.all(formula=f"{{UserID}}='{usr_email}'")
    current_month = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    stats = {"Blog Post": 0, "SEO Article": 0, "Social Media Post": 0, "Tokens Used": 0}
    
    for record in records:
        created_time = datetime.fromisoformat(record['createdTime'])
        if created_time >= current_month and record['fields'].get('Status') == "Completed":
            content_type = record['fields'].get('ContentType', 'Unknown')
            if content_type in TOKEN_COSTS:
                stats[content_type] += 1
                stats["Tokens Used"] += TOKEN_COSTS[content_type]
    return stats

# Pages
def login_page():
    st.title("Login")
    with st.form(key='login_form'):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submit_button = st.form_submit_button("Login")
        if submit_button:
            success, user_id = verify_user(email, password)
            if success:
                st.session_state['logged_in'] = True
                st.session_state['user_id'] = user_id
                st.session_state['user_email'] = email
                st.success("Login successful!")
                st.rerun()
            else:
                st.error("Invalid credentials")

def create_account_page():
    st.title("Create Account")
    with st.form(key='create_form'):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        confirm_password = st.text_input("Confirm Password", type="password")
        submit_button = st.form_submit_button("Sign Up")
        if submit_button:
            if password != confirm_password:
                st.error("Passwords don’t match")
            elif len(password) < 6:
                st.error("Password must be at least 6 characters")
            else:
                success, message = create_user(email, password)
                if success:
                    st.success(message)
                else:
                    st.error(message)

def subscription_page():
    st.title("Subscription")
    user_id = st.session_state['user_id']
    sub_status, tokens = get_user_data(user_id)

    st.subheader("This Month's Usage")
    stats = get_usage_stats(user_id)
    st.markdown('<div class="stats-box">', unsafe_allow_html=True)
    st.write(f"**Blog Posts**: {stats['Blog Post']}")
    st.write(f"**SEO Articles**: {stats['SEO Article']}")
    st.write(f"**Social Media Posts**: {stats['Social Media Post']}")
    st.write(f"**Total Tokens Used**: {stats['Tokens Used']}")
    st.markdown('</div>', unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    
    with col1:
        if sub_status in ["Free", "Expired"]:
            if st.button("Upgrade to Premium ($10/month)"):
                try:
                    session = stripe.checkout.Session.create(
                        payment_method_types=['card'],
                        line_items=[{
                            'price_data': {
                                'currency': 'usd',
                                'product_data': {'name': 'Premium Plan'},
                                'unit_amount': 1000,
                                'recurring': {'interval': 'month'}
                            },
                            'quantity': 1,
                        }],
                        mode='subscription',
                        success_url=f"https://ai-tool-box.streamlit.app/?success=true&user_id={user_id}&email={st.session_state['user_email']}",
                        cancel_url=f"https://ai-tool-box.streamlit.app/?cancel=true&email={st.session_state['user_email']}",
                        client_reference_id=user_id
                    )
                    with st.container():
                        st.markdown('<div class="popup-container">', unsafe_allow_html=True)
                        st.write("Click below to proceed to Stripe Checkout.")
                        if st.button("Proceed to Payment", key="checkout_button"):
                            st.markdown(f"""
                                <script>
                                window.location.href = '{session.url}';
                                </script>
                            """, unsafe_allow_html=True)
                        st.markdown(f'<a href="{session.url}" target="_blank">Open Checkout in New Tab (if redirect fails)</a>', unsafe_allow_html=True)
                        st.markdown('</div>', unsafe_allow_html=True)
                except Exception as e:
                    st.error(f"Error creating checkout session: {str(e)}")
        else:
            st.success("You’re on the Premium plan!")

    with col2:
        st.subheader("Buy Additional Tokens")
        token_amount = st.selectbox("Select tokens", [10, 50, 100], key="token_amount")
        token_cost = token_amount // 10
        if st.button(f"Buy {token_amount} Tokens (${token_cost})"):
            try:
                session = stripe.checkout.Session.create(
                    payment_method_types=['card'],
                    line_items=[{
                        'price_data': {
                            'currency': 'usd',
                            'product_data': {'name': f"{token_amount} Tokens"},
                            'unit_amount': token_cost * 100,
                        },
                        'quantity': 1,
                    }],
                    mode='payment',
                    success_url=f"https://ai-tool-box.streamlit.app/?token_success=true&user_id={user_id}&tokens={token_amount}&email={st.session_state['user_email']}",
                    cancel_url=f"https://ai-tool-box.streamlit.app/?cancel=true&email={st.session_state['user_email']}",
                    client_reference_id=user_id
                )
                with st.container():
                    st.markdown('<div class="popup-container">', unsafe_allow_html=True)
                    st.write("Click below to purchase tokens.")
                    if st.button("Proceed to Payment (Tokens)", key="token_checkout_button"):
                        st.markdown(f"""
                            <script>
                            window.location.href = '{session.url}';
                            </script>
                        """, unsafe_allow_html=True)
                    st.markdown(f'<a href="{session.url}" target="_blank">Open Checkout in New Tab (if redirect fails)</a>', unsafe_allow_html=True)
                    st.markdown('</div>', unsafe_allow_html=True)
            except Exception as e:
                st.error(f"Error creating token purchase session: {str(e)}")

def dashboard_page():
    st.title("Content Creation Dashboard")
    user_id = st.session_state['user_id']
    sub_status = get_subscription_status(user_id)
    _, tokens = get_user_data(user_id)

    tab1, tab2 = st.tabs(["Create Content", "Content History"])

    with tab1:
        if tokens <= 0:
            st.warning("You have no tokens left. Upgrade your plan or buy more tokens.")
            if st.button("Go to Subscription"):
                st.session_state['page'] = "Subscription"
                st.rerun()
            return

        content_type = st.selectbox("Content Type", ["Blog Post", "SEO Article", "Social Media Post"])
        details = st.text_area("Content Details (e.g., topic, description)")

        if content_type == "Blog Post":
            keywords = st.text_input("Keywords (comma-separated, 3-5)", placeholder="e.g., AI, tech, tools")
            word_count = st.selectbox("Word Count", [500, 1000, 1500, 2000])
            content_details = {
                "keywords": keywords.split(",") if keywords else [],
                "word_count": word_count
            }
        elif content_type == "Social Media Post":
            platform = st.selectbox("Platform", ["Facebook", "Twitter", "Instagram", "LinkedIn"])
            content_details = {"platform": platform}
        else:  # SEO Article
            content_details = {}

        if st.button("Generate Content"):
            try:
                content_record = content_table.create({
                    "UserID": [user_id],
                    "ContentType": content_type,
                    "Details": f"{details}\n{str(content_details)}",
                    "Status": "Requested"
                })
                content_record_id = content_record['id']
                if request_content(user_id, content_type, details, content_record_id, content_details):
                    st.success("Content generation requested! Tokens will be deducted upon completion.")
                else:
                    st.error("Failed to request content from webhook.")
            except Exception as e:
                st.error(f"Error creating content record: {str(e)}")
            if st.button("Go to Subscription"):
                st.session_state['page'] = "Subscription"
                st.rerun()

    with tab2:
        st.subheader("Your Generated Content")
        
        # Filters
        col1, col2, col3 = st.columns(3)
        with col1:
            type_filter = st.selectbox("Filter by Type", ["All", "Blog Post", "SEO Article", "Social Media Post"])
        with col2:
            status_filter = st.selectbox("Filter by Status", ["All", "Requested", "In Progress", "Completed", "Failed", "Cancelled"])
        with col3:
            date_range = st.date_input("Filter by Date Range", [datetime.now(timezone.utc) - timedelta(days=30), datetime.now(timezone.utc)], key="date_range")

        # Handle date range safely
        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_date = datetime.combine(date_range[0], datetime.min.time(), tzinfo=timezone.utc)
            end_date = datetime.combine(date_range[1], datetime.max.time(), tzinfo=timezone.utc)
        else:
            # Default to a wide range if only one date or none selected
            start_date = datetime.min.replace(tzinfo=timezone.utc)
            end_date = datetime.max.replace(tzinfo=timezone.utc)
            if isinstance(date_range, tuple) and len(date_range) == 1:
                start_date = datetime.combine(date_range[0], datetime.min.time(), tzinfo=timezone.utc)
                end_date = datetime.combine(date_range[0], datetime.max.time(), tzinfo=timezone.utc)

        content_items = get_user_content(user_id, type_filter, status_filter, (start_date, end_date))
        
        if content_items:
            for item in content_items:
                fields = item['fields']
                content_id = item['id']
                st.markdown(f'<div class="content-card">', unsafe_allow_html=True)
                st.markdown(f'<div class="content-title">{fields.get("ContentType", "Untitled")} - {fields.get("Status", "N/A")}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="content-meta">Created: {item.get("createdTime", "N/A")}</div>', unsafe_allow_html=True)
                with st.expander("Details"):
                    st.write(f"**Type**: {fields.get('ContentType', 'N/A')}")
                    st.write(f"**Details**: {fields.get('Details', 'N/A')}")
                    st.write(f"**Status**: {fields.get('Status', 'N/A')}")
                    output = fields.get('Output')
                    if output:
                        st.write(f"**Generated Content**: {output}")
                    st.write(f"**Created**: {item.get('createdTime', 'N/A')}")
                    col1, col2, col3 = st.columns([1, 1, 1])
                    with col1:
                        if fields.get('Status') in ["Requested", "In Progress"]:
                            if st.button("Cancel", key=f"cancel_{content_id}", type="secondary", help="Cancel this request"):
                                content_table.update(content_id, {"Status": "Cancelled"})
                                st.success("Request cancelled!")
                                st.rerun()
                    with col2:
                        if fields.get('Status') == "Failed":
                            with st.form(key=f"edit_{content_id}"):
                                new_details = st.text_area("Edit Details", value=fields.get('Details', ''), key=f"edit_details_{content_id}")
                                if st.form_submit_button("Resubmit"):
                                    content_table.update(content_id, {
                                        "Details": new_details,
                                        "Status": "Requested"
                                    })
                                    if request_content(user_id, fields['ContentType'], new_details, content_id, content_details):
                                        st.success("Request resubmitted!")
                                    else:
                                        st.error("Failed to resubmit request.")
                                    st.rerun()
                    with col3:
                        if fields.get('Status') == "Completed" and fields.get('Output'):
                            st.download_button("Download", fields['Output'], file_name=f"{fields['ContentType']}_{content_id}.txt", key=f"download_{content_id}")
                st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.info("No content matches your filters.")

# Request content with additional details
def request_content(user_id, content_type, details, content_record_id, content_details):
    webhook_url = st.secrets["make"]["webhook_url"]
    payload = {
        "user_id": user_id,
        "content_type": content_type,
        "details": details,
        "content_record_id": content_record_id,
        "content_details": content_details
    }
    response = requests.post(webhook_url, json=payload)
    return response.status_code == 200

# Main
def main():
    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False
        st.session_state['page'] = "Login"

    query_params = st.query_params
    user_id_from_url = query_params.get("user_id")
    email_from_url = query_params.get("email")

    if user_id_from_url and email_from_url and not st.session_state['logged_in']:
        try:
            record = users_table.get(user_id_from_url)
            if record and record['fields'].get('Email') == email_from_url:
                st.session_state['logged_in'] = True
                st.session_state['user_id'] = user_id_from_url
                st.session_state['user_email'] = email_from_url
        except Exception as e:
            st.error(f"Error restoring session: {str(e)}")

    if query_params.get("success") == "true" and user_id_from_url:
        try:
            record = users_table.get(user_id_from_url)
            if record:
                update_subscription(user_id_from_url, "Premium", datetime.now(timezone.utc) + timedelta(days=30))
                update_tokens(user_id_from_url, 100 - 10)
                st.success("Subscription upgraded to Premium!")
                st.query_params.clear()
        except Exception as e:
            st.error(f"Error updating subscription: {str(e)}")
    elif query_params.get("token_success") == "true" and user_id_from_url:
        try:
            tokens_to_add = int(query_params.get("tokens"))
            record = users_table.get(user_id_from_url)
            if record:
                update_tokens(user_id_from_url, tokens_to_add)
                st.success(f"Added {tokens_to_add} tokens!")
                st.query_params.clear()
        except Exception as e:
            st.error(f"Error adding tokens: {str(e)}")
    elif query_params.get("cancel") == "true":
        st.warning("Payment cancelled.")
        st.query_params.clear()

    if not st.session_state['logged_in']:
        tab1, tab2 = st.tabs(["Login", "Create Account"])
        with tab1:
            login_page()
        with tab2:
            create_account_page()
    else:
        st.sidebar.markdown("<h2 style='color: rgb(41, 40, 40);'>Menu</h2>", unsafe_allow_html=True)
        page = st.sidebar.selectbox("Navigate", ["Dashboard", "Subscription", "Logout"], 
                                   format_func=lambda x: x.capitalize(), 
                                   label_visibility="collapsed")
        st.session_state['page'] = page
        
        user_id = st.session_state['user_id']
        sub_status, tokens = get_user_data(user_id)
        st.sidebar.write(f"**Plan**: {sub_status}")
        st.sidebar.write(f"**Tokens**: {tokens}")
        
        if page == "Dashboard":
            dashboard_page()
        elif page == "Subscription":
            subscription_page()
        elif page == "Logout":
            st.session_state['logged_in'] = False
            st.session_state.pop('user_id', None)
            st.session_state.pop('user_email', None)
            st.rerun()

if __name__ == "__main__":
    main()