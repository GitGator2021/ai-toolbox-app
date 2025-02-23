import streamlit as st
import hashlib
from pyairtable import Table
import requests
import stripe
from datetime import datetime, timedelta

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
        color: rgb(41, 40, 40);  # Changed for better visibility
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
    </style>
""", unsafe_allow_html=True)

# Secrets
AIRTABLE_TOKEN = st.secrets["airtable"]["token"]
AIRTABLE_BASE_ID = st.secrets["airtable"]["base_id"]
AIRTABLE_USERS_TABLE = st.secrets["airtable"]["users_table"]
AIRTABLE_CONTENT_TABLE = st.secrets["airtable"]["content_table"]
stripe.api_key = st.secrets["stripe"]["secret_key"]

# Airtable clients
users_table = Table(AIRTABLE_TOKEN, AIRTABLE_BASE_ID, AIRTABLE_USERS_TABLE)
content_table = Table(AIRTABLE_TOKEN, AIRTABLE_BASE_ID, AIRTABLE_CONTENT_TABLE)

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
    users_table.create({"Email": email, "Password": hash_password(password), "Subscription": "Free"})
    return True, "Account created"

# Get subscription status
def get_subscription_status(user_id):
    record = users_table.get(user_id)
    sub_status = record['fields'].get('Subscription', 'Free')
    sub_end = record['fields'].get('SubscriptionEnd')
    if sub_status == "Premium" and sub_end:
        if datetime.strptime(sub_end, '%Y-%m-%d') < datetime.now():
            users_table.update(user_id, {"Subscription": "Free"})
            return "Free"
    return sub_status

# Update subscription
def update_subscription(user_id, status, end_date=None):
    fields = {"Subscription": status}
    if end_date:
        fields["SubscriptionEnd"] = end_date.strftime('%Y-%m-%d')
    users_table.update(user_id, fields)

# Request content
def request_content(user_id, content_type, details):
    webhook_url = st.secrets["make"]["webhook_url"]
    payload = {"user_id": user_id, "content_type": content_type, "details": details}
    response = requests.post(webhook_url, json=payload)
    return response.status_code == 200

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
    current_plan = get_subscription_status(user_id)
    st.write(f"Current Plan: {current_plan}")
    
    if current_plan in ["Free", "Expired"]:
        if st.button("Subscribe to Premium ($10/month)"):
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
                    success_url=f"https://ai-tool-box.streamlit.app/?success=true&session_id={{CHECKOUT_SESSION_ID}}",
                    cancel_url="https://ai-tool-box.streamlit.app/?cancel=true",
                    client_reference_id=user_id  # Pass user_id to webhook
                )
                st.markdown(f'<a href="{session.url}" target="_blank">Click here to pay</a>', unsafe_allow_html=True)
                st.write("Opening Stripe Checkout in a new tab...")
            except Exception as e:
                st.error(f"Error creating checkout session: {str(e)}")
    else:
        st.success("You’re on the Premium plan!")

def dashboard_page():
    st.title("Content Creation Dashboard")
    user_id = st.session_state['user_id']
    plan = get_subscription_status(user_id)
    if plan == "Premium":
        content_type = st.selectbox("Content Type", ["Blog Post", "SEO Article", "Social Media Post"])
        details = st.text_area("Content Details (e.g., topic, keywords)")
        if st.button("Generate Content"):
            if request_content(user_id, content_type, details):
                content_table.create({
                    "UserID": user_id,
                    "ContentType": content_type,
                    "Details": details,
                    "Status": "Requested"
                })
                st.success("Content generation requested!")
            else:
                st.error("Failed to request content")
    else:
        st.warning("Upgrade to Premium to generate content!")
        st.button("Go to Subscription", on_click=lambda: st.session_state.update({'page': 'Subscription'}))

# Main
def main():
    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False
        st.session_state['page'] = "Login"

    # Handle Stripe redirect
    query_params = st.query_params
    if "session_id" in query_params and st.session_state['logged_in']:
        session_id = query_params["session_id"]
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            if session.payment_status == "paid":
                user_id = session.client_reference_id
                update_subscription(user_id, "Premium", datetime.now() + timedelta(days=30))
                st.success("Subscription upgraded to Premium!")
                st.query_params.clear()
        except Exception as e:
            st.error(f"Error verifying payment: {str(e)}")
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