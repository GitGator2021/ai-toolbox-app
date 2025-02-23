import streamlit as st
import hashlib
from pyairtable import Table
import requests
import stripe

# Streamlit configuration for dark theme
st.set_page_config(page_title="SaaS Content Dashboard", page_icon="📝", layout="wide")
st.markdown("""
    <style>
    .stApp {
        background-color: #1E1E1E;
        color: #FFFFFF;
    }
    .stTextInput > div > div > input {
        background-color: #2E2E2E;
        color: #FFFFFF;
        border-radius: 8px;
    }
    .stButton > button {
        background-color: #4CAF50;
        color: white;
        border-radius: 8px;
    }
    </style>
""", unsafe_allow_html=True)

# Airtable configuration (using secrets)
AIRTABLE_TOKEN = st.secrets["airtable"]["token"]
AIRTABLE_BASE_ID = st.secrets["airtable"]["base_id"]
AIRTABLE_USERS_TABLE = st.secrets["airtable"]["users_table"]
AIRTABLE_CONTENT_TABLE = st.secrets["airtable"]["content_table"]

# Stripe configuration
stripe.api_key = st.secrets["stripe"]["secret_key"]

# Initialize Airtable clients
users_table = Table(AIRTABLE_TOKEN, AIRTABLE_BASE_ID, AIRTABLE_USERS_TABLE)
content_table = Table(AIRTABLE_TOKEN, AIRTABLE_BASE_ID, AIRTABLE_CONTENT_TABLE)

# Hash password function
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

# Check subscription status
def get_subscription_status(user_id):
    record = users_table.get(user_id)
    return record['fields'].get('Subscription', 'Free')

# Update subscription
def update_subscription(user_id, status):
    users_table.update(user_id, {"Subscription": status})

# Request content via Make.com webhook
def request_content(user_id, content_type, details):
    webhook_url = st.secrets["make"]["webhook_url"]
    payload = {
        "user_id": user_id,
        "content_type": content_type,
        "details": details
    }
    response = requests.post(webhook_url, json=payload)
    return response.status_code == 200

# Login page
def login_page():
    st.title("Login")
    with st.form(key='login_form'):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Login"):
            success, user_id = verify_user(email, password)
            if success:
                st.session_state['logged_in'] = True
                st.session_state['user_id'] = user_id
                st.session_state['user_email'] = email
                st.success("Login successful!")
                st.rerun()
            else:
                st.error("Invalid credentials")

# Create account page
def create_account_page():
    st.title("Create Account")
    with st.form(key='create_form'):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        confirm_password = st.text_input("Confirm Password", type="password")
        if st.form_submit_button("Sign Up"):
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

# Subscription page
def subscription_page():
    st.title("Upgrade Your Plan")
    user_id = st.session_state['user_id']
    current_plan = get_subscription_status(user_id)
    st.write(f"Current Plan: {current_plan}")
    
    if current_plan == "Free":
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
                    success_url='https://ai-tool-box.streamlit.app/?success=true',
                    cancel_url='https://ai-tool-box.streamlit.app/?cancel=true'
                )
                st.markdown(f'<a href="{session.url}" target="_blank">Click here to pay</a>', unsafe_allow_html=True)
                st.write("Opening Stripe Checkout in a new tab...")
            except Exception as e:
                st.error(f"Error creating checkout session: {str(e)}")
    else:
        st.success("You’re already on the Premium plan!")

# Dashboard page
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

# Main function
def main():
    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False
    # Handle Stripe redirect
    query_params = st.query_params
    if query_params.get("success") == "true" and st.session_state['logged_in']:
        update_subscription(st.session_state['user_id'], "Premium")
        st.success("Subscription upgraded to Premium!")
    elif query_params.get("cancel") == "true":
        st.warning("Payment cancelled.")

    if not st.session_state['logged_in']:
        tab1, tab2 = st.tabs(["Login", "Create Account"])
        with tab1:
            login_page()
        with tab2:
            create_account_page()
    else:
        st.sidebar.title(f"Welcome, {st.session_state['user_email']}")
        page = st.sidebar.radio("Navigate", ["Dashboard", "Subscription", "Logout"])
        
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