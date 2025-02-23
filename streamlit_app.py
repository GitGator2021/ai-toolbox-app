import streamlit as st
import hashlib
from pyairtable import Table
import requests
import stripe
from datetime import datetime, timedelta, timezone
from dateutil.relativedelta import relativedelta  # For monthly resets

# Streamlit configuration
st.set_page_config(page_title="SaaS Content Dashboard", page_icon="📝", layout="wide")
st.markdown("""
    <style>
    .stApp {
        background-color: rgb(231, 232, 231);
        color: rgb(41, 40, 40);
    }
    .stTextInput > div > div > input {
        background-color: rgb(255, 255, 255);
        color: rgb(41, 40, 40);
        border-radius: 8px;
    }
    .stButton > button {
        background-color: #4CAF50;
        color: white;
        border-radius: 8px;
    }
    .stSelectbox > div > div {
        background-color: rgb(252, 254, 255);
        color: rgb(0, 0, 0);
        border-radius: 8px;
    }
    .popup-container {
        background-color: #FFFFFF;
        padding: 20px;
        border-radius: 10px;
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
        text-align: center;
        max-width: 400px;
        margin: 20px auto;
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
        "Tokens": 10,  # Initial free tokens
        "LastReset": datetime.now(timezone.utc).isoformat()  # Full ISO format
    })
    return True, "Account created"

# Get subscription status
def get_subscription_status(user_id):
    record = users_table.get(user_id)
    sub_status = record['fields'].get('Subscription', 'Free')
    sub_end = record['fields'].get('SubscriptionEnd')
    if sub_status == "Premium" and sub_end:
        # Handle both naive (YYYY-MM-DD) and aware (ISO) formats
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
    
    # Reset tokens monthly
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
                "LastReset": datetime.now(timezone.utc).isoformat()  # Full ISO format
            })
    return sub_status, tokens

# Update subscription
def update_subscription(user_id, status, end_date=None):
    fields = {"Subscription": status}
    if end_date:
        fields["SubscriptionEnd"] = end_date.isoformat()  # Full ISO format
    users_table.update(user_id, fields)

# Update tokens
def update_tokens(user_id, token_change):
    current_tokens = get_user_data(user_id)[1]
    new_tokens = max(0, current_tokens + token_change)  # No negative tokens
    users_table.update(user_id, {"Tokens": new_tokens})
    return new_tokens

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
    st.write(f"Current Plan: {sub_status}")
    st.write(f"Token Balance: {tokens}")

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
        token_cost = token_amount // 10  # $1 per 10 tokens
        if st.button(f"Buy {token_amount} Tokens (${token_cost})"):
            try:
                session = stripe.checkout.Session.create(
                    payment_method_types=['card'],
                    line_items=[{
                        'price_data': {
                            'currency': 'usd',
                            'product_data': {'name': f"{token_amount} Tokens"},
                            'unit_amount': token_cost * 100,  # In cents
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
    _, tokens = get_user_data(user_id)  # Get tokens separately
    st.write(f"Token Balance: {tokens}")

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
        cost = TOKEN_COSTS[content_type]
        if tokens >= cost:
            try:
                content_record = content_table.create({
                    "UserID": [user_id],
                    "ContentType": content_type,
                    "Details": f"{details}\n{str(content_details)}",
                    "Status": "Requested"
                })
                content_record_id = content_record['id']
                if request_content(user_id, content_type, details, content_record_id, content_details):
                    update_tokens(user_id, -cost)  # Deduct tokens
                    st.success("Content generation requested!")
                else:
                    st.error("Failed to request content from webhook.")
            except Exception as e:
                st.error(f"Error creating content record: {str(e)}")
        else:
            st.error(f"Not enough tokens! Required: {cost}, Available: {tokens}")
        if st.button("Go to Subscription"):
            st.session_state['page'] = "Subscription"
            st.rerun()

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
                update_tokens(user_id_from_url, 100 - 10)  # Upgrade to 100 tokens
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