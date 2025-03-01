import streamlit as st
import hashlib
import os
import base64
from pyairtable import Table
import requests
import stripe
from datetime import datetime, timedelta, timezone
from dateutil.relativedelta import relativedelta
import logging
import pdfplumber

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Streamlit configuration (unchanged)
st.set_page_config(page_title="AI Toolbox", page_icon="🛠️", layout="wide")
st.markdown("""
    <style>
    .stApp {
        background-color: #F7FAFC;
        color: #1E293B;
        font-family: 'Inter', sans-serif;
    }
    .stTextInput > div > div > input, .stTextArea > div > div > textarea {
        background-color: #FFFFFF;
        color: #1E293B;
        border: 1px solid #CBD5E1;
        border-radius: 6px;
        padding: 10px;
        box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.05);
    }
    .stButton > button {
        background-color: #3B82F6;
        color: white;
        border-radius: 6px;
        padding: 8px 16px;
        font-weight: 500;
        transition: background-color 0.2s, transform 0.1s;
    }
    .stButton > button:hover {
        background-color: #2563EB;
        transform: translateY(-1px);
    }
    .stButton > button[type="secondary"] {
        background-color: #64748B;
    }
    .stButton > button[type="secondary"]:hover {
        background-color: #475569;
    }
    .stButton > button.cancel-btn {
        background-color: #EF4444;
    }
    .stButton > button.cancel-btn:hover {
        background-color: #DC2626;
    }
    .stSelectbox > div > div {
        background-color: #FFFFFF;
        color: #1E293B;
        border: 1px solid #CBD5E1;
        border-radius: 6px;
    }
    .popup-container {
        background-color: #FFFFFF;
        padding: 20px;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
        text-align: center;
        max-width: 400px;
        margin: 20px auto;
    }
    .content-card {
        background-color: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 6px;
        padding: 0;
        margin-bottom: 12px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        transition: box-shadow 0.2s;
    }
    .content-card:hover {
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    }
    .content-card > button {
        padding: 14px;
        display: block;
        width: 100%;
        text-align: left;
    }
    .sidebar .sidebar-content {
        background-color: #FFFFFF;
        padding: 20px;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
    }
    h1, h2, h3 {
        color: #1E293B;
    }
    .stats-card {
        background-color: #FFFFFF;
        padding: 15px;
        border-radius: 6px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        text-align: center;
        min-width: 150px;
        margin: 0 10px 20px 0;
    }
    .stats-title {
        font-size: 14px;
        color: #64748B;
        margin-bottom: 8px;
    }
    .stats-value {
        font-size: 18px;
        font-weight: 600;
        color: #1E293B;
    }
    .preview-container {
        background-color: #FFFFFF;
        padding: 20px;
        border-radius: 6px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        margin-top: 20px;
    }
    .tool-icon {
        margin-right: 8px;
        vertical-align: middle;
    }
    </style>
""", unsafe_allow_html=True)

# Secrets (unchanged)
try:
    AIRTABLE_TOKEN = st.secrets["airtable"]["token"]
    AIRTABLE_BASE_ID = st.secrets["airtable"]["base_id"]
    AIRTABLE_USERS_TABLE = st.secrets["airtable"]["users_table"]
    AIRTABLE_CONTENT_TABLE = st.secrets["airtable"]["content_table"]
    AIRTABLE_RESUMES_TABLE = st.secrets["airtable"]["resumes_table"]
    stripe.api_key = st.secrets["stripe"]["secret_key"]
except KeyError as e:
    st.error(f"Missing secret: {str(e)}. Please check your secrets configuration.")
    st.stop()

# Airtable clients (unchanged)
users_table = Table(AIRTABLE_TOKEN, AIRTABLE_BASE_ID, AIRTABLE_USERS_TABLE)
content_table = Table(AIRTABLE_TOKEN, AIRTABLE_BASE_ID, AIRTABLE_CONTENT_TABLE)
resumes_table = Table(AIRTABLE_TOKEN, AIRTABLE_BASE_ID, AIRTABLE_RESUMES_TABLE)

# Token costs (unchanged)
TOKEN_COSTS = {
    "Blog Post": lambda word_count: max(1, word_count // 500),
    "SEO Article": lambda word_count: max(1, word_count // 500),
    "Social Media Post": 2,
    "Resume Enhancement": 5
}

# Improved password hashing with salt
def hash_password(password):
    salt = os.urandom(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)
    return base64.b64encode(salt + hashed).decode()

def verify_password(stored_hash, password):
    decoded = base64.b64decode(stored_hash)
    salt, stored_hash = decoded[:16], decoded[16:]
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)
    return hashed == stored_hash

# Verify user
def verify_user(email, password):
    records = users_table.all(formula=f"{{Email}}='{email}'")
    if records and verify_password(records[0]['fields'].get('Password'), password):
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

# Get subscription status (unchanged)
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

# Cached user data
def get_user_data(user_id):
    if 'user_data' not in st.session_state or st.session_state['user_data']['id'] != user_id:
        record = users_table.get(user_id)
        sub_status = get_subscription_status(user_id)
        tokens = record['fields'].get('Tokens', 0)
        last_reset = record['fields'].get('LastReset')
        name = record['fields'].get('Name', '')
        phone = record['fields'].get('Phone', '')
        company_name = record['fields'].get('CompanyName', '')
        website = record['fields'].get('Website', '')
        
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
        st.session_state['user_data'] = {
            'id': user_id,
            'sub_status': sub_status,
            'tokens': tokens,
            'name': name,
            'phone': phone,
            'company_name': company_name,
            'website': website
        }
    return (st.session_state['user_data']['sub_status'], st.session_state['user_data']['tokens'],
            st.session_state['user_data']['name'], st.session_state['user_data']['phone'],
            st.session_state['user_data']['company_name'], st.session_state['user_data']['website'])

# Update subscription with logging
def update_subscription(user_id, status, end_date=None):
    fields = {"Subscription": status}
    if end_date:
        fields["SubscriptionEnd"] = end_date.isoformat()
    try:
        users_table.update(user_id, fields)
        if 'user_data' in st.session_state and st.session_state['user_data']['id'] == user_id:
            st.session_state['user_data']['sub_status'] = status
    except Exception as e:
        logger.error(f"Failed to update subscription for user_id {user_id}: {str(e)}")
        raise

# Update tokens
def update_tokens(user_id, token_change):
    current_tokens = get_user_data(user_id)[1]
    new_tokens = max(0, current_tokens + token_change)
    users_table.update(user_id, {"Tokens": new_tokens})
    if 'user_data' in st.session_state and st.session_state['user_data']['id'] == user_id:
        st.session_state['user_data']['tokens'] = new_tokens
    return new_tokens

# Fetch user content using UserEmail
def get_user_content(user_email, content_type_filter=None):
    try:
        formula = f"{{UserEmail}}='{user_email}'"
        all_user_content = content_table.all(formula=formula)

        if content_type_filter:
            filtered_content = [
                item for item in all_user_content
                if item['fields'].get('ContentType') == content_type_filter
            ]
        else:
            filtered_content = all_user_content

        if not filtered_content:
            all_items = content_table.all()

        return filtered_content

    except Exception as e:
        logger.error(f"Error fetching/filtering user content for user {user_email}: {str(e)}", exc_info=True)
        return []

# Fetch user resumes using UserEmail
def get_user_resumes(user_email):
    try:
        formula = f"{{UserEmail}}='{user_email}'"
        items = resumes_table.all(formula=formula)
        if not items:
            all_items = resumes_table.all()
        return items
    except Exception as e:
        logger.error(f"Error fetching resumes for user {user_email}: {str(e)}", exc_info=True)
        return []

# Get usage stats with corrected formula
def get_usage_stats(user_email, months_back=6):
    formula = f"{{UserEmail}}='{user_email}'"
    records = content_table.all(formula=formula)
    current_date = datetime.now(timezone.utc)
    stats = {i: {"Blog Post": 0, "SEO Article": 0, "Social Media Post": 0, "Tokens Used": 0} 
             for i in range(months_back + 1)}
    start_date = current_date - relativedelta(months=months_back)
    
    for record in records:
        created_time = datetime.fromisoformat(record['createdTime']).replace(tzinfo=timezone.utc)
        if record['fields'].get('Status') == "Completed" and created_time >= start_date:
            months_ago = (current_date.year - created_time.year) * 12 + current_date.month - created_time.month
            if 0 <= months_ago <= months_back:
                content_type = record['fields'].get('ContentType', 'Unknown')
                if content_type in TOKEN_COSTS:
                    stats[months_ago][content_type] += 1
                    details = record['fields'].get('Details', '')
                    word_count = 500
                    if 'word_count' in details:
                        try:
                            word_count = int(details.split('word_count')[1].split('}')[0].split(':')[1])
                        except:
                            pass
                    if callable(TOKEN_COSTS[content_type]):
                        stats[months_ago]["Tokens Used"] += TOKEN_COSTS[content_type](word_count)
                    else:
                        stats[months_ago]["Tokens Used"] += TOKEN_COSTS[content_type]
    return stats

# Fixed file upload response handling
def upload_file_to_airtable(base_id, record_id, field_name, file_content, file_name, content_type):
    url = f"https://content.airtable.com/v0/{base_id}/{record_id}/{field_name}/uploadAttachment"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "contentType": content_type,
        "file": base64.b64encode(file_content).decode("utf-8"),
        "filename": file_name
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        response_data = response.json()
        if "fields" in response_data:
            for field_values in response_data["fields"].values():
                if isinstance(field_values, list) and len(field_values) > 0 and "url" in field_values[0]:
                    return field_values[0]["url"]
        raise ValueError(f"Unexpected response format: {response_data}")
    except requests.RequestException as e:
        st.error(f"Failed to upload file to Airtable: {str(e)} - Response: {response.text}")
        raise
    except ValueError as e:
        st.error(f"Invalid response from Airtable: {str(e)}")
        raise

# Pages (updated to use user_email)
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

def create_stripe_session(user_id, amount, description, recurring=False, tokens=None):
    try:
        line_item = {
            'price_data': {
                'currency': 'usd',
                'product_data': {'name': description},
                'unit_amount': amount * 100,
            },
            'quantity': 1,
        }
        if recurring:
            line_item['price_data']['recurring'] = {'interval': 'month'}
        success_url = f"https://ai-tool-box.streamlit.app/?{'success' if recurring else 'token_success'}=true&user_id={user_id}&email={st.session_state['user_email']}"
        if tokens:
            success_url += f"&tokens={tokens}"
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[line_item],
            mode='subscription' if recurring else 'payment',
            success_url=success_url,
            cancel_url=f"https://ai-tool-box.streamlit.app/?cancel=true&email={st.session_state['user_email']}",
            client_reference_id=user_id
        )
        return session
    except Exception as e:
        st.error(f"Error creating checkout session: {str(e)}")
        return None

def subscription_page():
    user_id = st.session_state['user_id']
    user_email = st.session_state['user_email']
    sub_status, tokens, _, _, _, _ = get_user_data(user_id)

    col1, col2 = st.columns([2, 1])
    with col1:
        st.title("Subscription")
    with col2:
        if sub_status in ["Free", "Expired"]:
            if st.button("Upgrade to Premium ($10/month)", key="upgrade_button"):
                session = create_stripe_session(user_id, 10, "Premium Plan", recurring=True)
                if session:
                    with st.container():
                        st.markdown('<div class="popup-container">', unsafe_allow_html=True)
                        st.write("Click below to proceed to Stripe Checkout.")
                        if st.button("Proceed to Payment", key="checkout_button"):
                            st.markdown(f"""
                                <script>
                                window.location.href = '{session.url}';
                                </script>
                            """, unsafe_allow_html=True)
                        st.markdown(f'<a href="{session.url}" target="_blank">Open Checkout in New Tab</a>', unsafe_allow_html=True)
                        st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.success("You’re on the Premium plan!", icon="✅")

    st.subheader("This Month's Usage")
    stats = get_usage_stats(user_email, months_back=0)
    current_month_stats = stats[0]
    cols = st.columns(4)
    with cols[0]:
        st.markdown(f'<div class="stats-card"><div class="stats-title">Blog Posts</div><div class="stats-value">{current_month_stats["Blog Post"]}</div></div>', unsafe_allow_html=True)
    with cols[1]:
        st.markdown(f'<div class="stats-card"><div class="stats-title">SEO Articles</div><div class="stats-value">{current_month_stats["SEO Article"]}</div></div>', unsafe_allow_html=True)
    with cols[2]:
        st.markdown(f'<div class="stats-card"><div class="stats-title">Social Media Posts</div><div class="stats-value">{current_month_stats["Social Media Post"]}</div></div>', unsafe_allow_html=True)
    with cols[3]:
        st.markdown(f'<div class="stats-card"><div class="stats-title">Tokens Used</div><div class="stats-value">{current_month_stats["Tokens Used"]}</div></div>', unsafe_allow_html=True)

    st.subheader("Token Usage History")
    stats = get_usage_stats(user_email, months_back=6)
    for months_ago, data in stats.items():
        month_name = (datetime.now(timezone.utc) - relativedelta(months=months_ago)).strftime("%B %Y")
        if any(data.values()):
            with st.expander(f"{month_name}"):
                st.write(f"Blog Posts: {data['Blog Post']}")
                st.write(f"SEO Articles: {data['SEO Article']}")
                st.write(f"Social Media Posts: {data['Social Media Post']}")
                st.write(f"Tokens Used: {data['Tokens Used']}")

    st.subheader("Buy Additional Tokens")
    col1, col2 = st.columns(2)
    with col1:
        token_amount = st.selectbox("Select tokens", [10, 50, 100], key="token_amount")
        token_cost = token_amount // 10
        if st.button(f"Buy {token_amount} Tokens (${token_cost})"):
            session = create_stripe_session(user_id, token_cost, f"{token_amount} Tokens", recurring=False, tokens=token_amount)
            if session:
                with st.container():
                    st.markdown('<div class="popup-container">', unsafe_allow_html=True)
                    st.write("Click below to purchase tokens.")
                    if st.button("Proceed to Payment (Tokens)", key="token_checkout_button"):
                        st.markdown(f"""
                            <script>
                            window.location.href = '{session.url}';
                            </script>
                        """, unsafe_allow_html=True)
                    st.markdown(f'<a href="{session.url}" target="_blank">Open Checkout in New Tab</a>', unsafe_allow_html=True)
                    st.markdown('</div>', unsafe_allow_html=True)

def settings_page():
    user_id = st.session_state['user_id']
    _, _, name, phone, company_name, website = get_user_data(user_id)

    with st.form(key='settings_form'):
        new_name = st.text_input("Full Name", value=name)
        new_phone = st.text_input("Phone Number", value=phone)
        new_company_name = st.text_input("Company Name", value=company_name)
        new_website = st.text_input("Website", value=website)
        submit_button = st.form_submit_button("Save Changes")
        
        if submit_button:
            try:
                users_table.update(user_id, {
                    "Name": new_name,
                    "Phone": new_phone,
                    "CompanyName": new_company_name,
                    "Website": new_website
                })
                if 'user_data' in st.session_state:
                    st.session_state['user_data'].update({
                        'name': new_name,
                        'phone': new_phone,
                        'company_name': new_company_name,
                        'website': new_website
                    })
                st.success("Settings updated successfully!")
            except Exception as e:
                st.error(f"Error updating settings: {str(e)}")

def content_tool_page(tool_type):
    st.title(f"{tool_type} Tool")
    user_id = st.session_state['user_id']
    user_email = st.session_state['user_email']
    _, tokens, _, _, _, _ = get_user_data(user_id)

    query_params = st.query_params
    content_id = query_params.get("content_id")

    if content_id:
        try:
            item = content_table.get(content_id)
            if item and st.session_state['user_email'] in item['fields'].get('UserEmail', ''):
                fields = item['fields']
                st.subheader(f"{fields.get('ContentType', 'Untitled')} - {fields.get('Status', 'N/A')}")
                
                tab1, tab2 = st.tabs(["Preview", "Edit"])
                
                with tab1:
                    st.markdown('<div class="preview-container">', unsafe_allow_html=True)
                    output = fields.get('Output', '')
                    if output:
                        st.subheader("Preview")
                        try:
                            st.markdown(output, unsafe_allow_html=True)
                        except:
                            st.text(output)
                    if fields.get('Status') in ["Requested", "In Progress"]:
                        st.spinner("Generating content...")
                    st.write(f"**Created**: {item.get('createdTime', 'N/A')}")
                    st.markdown('</div>', unsafe_allow_html=True)
                
                with tab2:
                    st.markdown('<div class="preview-container">', unsafe_allow_html=True)
                    if fields.get('Status') == "Completed":
                        with st.form(key=f"edit_content_{content_id}"):
                            edited_details = st.text_area("Edit Details", value=fields.get('Details', ''), key=f"edit_details_{content_id}")
                            edited_output = st.text_area("Edit Content", value=output, height=300)
                            col1, col2 = st.columns(2)
                            with col1:
                                if st.form_submit_button("Save Changes"):
                                    content_table.update(content_id, {"Output": edited_output, "Details": edited_details})
                                    st.success("Content updated successfully!")
                                    st.rerun()
                            with col2:
                                if st.form_submit_button("Save & Regenerate"):
                                    content_details = {}
                                    if '{' in edited_details:
                                        try:
                                            content_details = eval(edited_details.split('\n')[-1])
                                        except:
                                            pass
                                    content_table.update(content_id, {
                                        "Details": edited_details,
                                        "Output": "",
                                        "Status": "Requested"
                                    })
                                    request_content(user_id, fields['ContentType'], edited_details, content_id, content_details)
                                    st.success("Content resubmitted for generation!")
                                    st.rerun()
                    elif fields.get('Status') == "Failed":
                        with st.form(key=f"edit_{content_id}"):
                            new_details = st.text_area("Edit Details", value=fields.get('Details', ''), key=f"edit_details_{content_id}")
                            if st.form_submit_button("Resubmit"):
                                content_table.update(content_id, {
                                    "Details": new_details,
                                    "Status": "Requested"
                                })
                                content_details = {}
                                if request_content(user_id, fields['ContentType'], new_details, content_id, content_details):
                                    st.success("Request resubmitted!")
                                else:
                                    st.error("Failed to resubmit request.")
                                st.rerun()
                    st.markdown('</div>', unsafe_allow_html=True)
                
                col1, col2, col3 = st.columns([1, 1, 1])
                with col1:
                    if fields.get('Status') in ["Requested", "In Progress"]:
                        if st.button("Cancel", key=f"cancel_{content_id}", type="secondary"):
                            content_table.update(content_id, {"Status": "Cancelled"})
                            st.success("Request cancelled!")
                            st.query_params.clear()
                            st.rerun()
                with col2:
                    if fields.get('Status') == "Completed" and output:
                        st.download_button("Download Text", output, file_name=f"{fields['ContentType']}_{content_id}.txt", key=f"download_txt_{content_id}")
                with col3:
                    if st.button(f"Back to {tool_type} Tool", type="secondary"):
                        st.query_params.clear()
                        st.rerun()
            else:
                st.error("Content not found or unauthorized.")
        except Exception as e:
            st.error(f"Error loading content: {str(e)}")
    
    else:
        tab1, tab2 = st.tabs(["Generate New Content", f"Your {tool_type}s"])
        
        with tab1:
            st.subheader(f"Generate New {tool_type}")
            if tokens <= 0:
                st.warning("You have no tokens left. Upgrade your plan or buy more tokens.")
                if st.button("Go to Subscription"):
                    st.session_state['page'] = "Subscription"
                    st.rerun()
            else:
                details = st.text_area("Content Details", "", height=200, label_visibility="hidden")  # Fixed accessibility
                token_cost = 0
                platform = ""
                if tool_type in ["Blog Post", "SEO Article"]:
                    keywords = st.text_input("Keywords (comma-separated, 3-5)", placeholder="e.g., AI, tech, tools")
                    word_count = st.selectbox("Word Count", [500, 1000, 1500, 2000])
                    token_cost = TOKEN_COSTS[tool_type](word_count)
                elif tool_type == "Social Media Post":
                    keywords = ""
                    word_count = ""
                    platform = st.selectbox("Platform", ["Facebook", "Twitter", "Instagram", "LinkedIn"])
                    token_cost = TOKEN_COSTS[tool_type]

                st.write(f"Token Cost: {token_cost}")

                if st.button(f"Generate {tool_type}"):
                    if tokens >= token_cost:
                        try:
                            content_record = content_table.create({
                                "UserID": [user_id],
                                "ContentType": tool_type,
                                "Details": details,
                                "Status": "Requested",
                            })
                            content_record_id = content_record['id']
                            # Call webhook and log result
                            if request_content(user_id, tool_type, details, content_record_id, token_cost, keywords, word_count, platform):
                                st.success(f"{tool_type} generation requested! {token_cost} token(s) will be deducted upon completion.")
                            else:
                                st.error("Failed to request content generation. Check logs for details.")
                            st.rerun()  # Force rerun to update UI
                        except Exception as e:
                            st.error(f"Error creating content record: {str(e)}")
                    else:
                        st.error(f"Not enough tokens! Required: {token_cost}, Available: {tokens}")

        with tab2:
            st.subheader(f"Your {tool_type}s")
            content_items = get_user_content(user_email, tool_type)
            
            if content_items:
                status_filter = st.multiselect("Filter by Status", ["Requested", "In Progress", "Completed", "Failed", "Cancelled"], default=["Requested", "In Progress", "Completed", "Failed", "Cancelled"])
                filtered_items = [item for item in content_items if item['fields'].get('Status', 'N/A') in status_filter]
                
                if filtered_items:
                    selected_items = []
                    st.write("Select items for bulk actions:")
                    for item in filtered_items:
                        fields = item['fields']
                        content_id = item['id']
                        with st.container():
                            st.markdown(f'<div class="content-card">', unsafe_allow_html=True)
                            col1, col2 = st.columns([1, 5])
                            with col1:
                                if st.checkbox("", key=f"select_{content_id}"):
                                    selected_items.append(content_id)
                            with col2:
                                if st.button(f"{fields.get('ContentType', 'Untitled')} - {fields.get('Status', 'N/A')}\nCreated: {item.get('createdTime', 'N/A')}", 
                                             key=f"card_{content_id}", 
                                             type="secondary", 
                                             help="Click to view details", 
                                             use_container_width=True):
                                    st.query_params["content_id"] = content_id
                                    st.rerun()
                            st.markdown('</div>', unsafe_allow_html=True)

                    if selected_items:
                        col1, col2 = st.columns(2)
                        with col1:
                            if st.button("Cancel Selected"):
                                for cid in selected_items:
                                    item = content_table.get(cid)
                                    if item['fields'].get('Status') in ["Requested", "In Progress"]:
                                        content_table.update(cid, {"Status": "Cancelled"})
                                st.success(f"Cancelled {len(selected_items)} item(s)!")
                                st.rerun()
                        with col2:
                            if st.button("Resubmit Selected"):
                                for cid in selected_items:
                                    item = content_table.get(cid)
                                    if item['fields'].get('Status') == "Failed":
                                        content_table.update(cid, {"Status": "Requested"})
                                        st.success(f"Resubmitted {cid}!")
                                st.rerun()
                else:
                    st.info(f"No {tool_type.lower()}s match the selected filters.")
            else:
                st.info(f"No {tool_type.lower()}s found.")

def resume_enhancement_page():
    st.title("Resume Enhancement Tool")
    user_id = st.session_state['user_id']
    user_email = st.session_state['user_email']
    _, tokens, _, _, _, _ = get_user_data(user_id)

    query_params = st.query_params
    resume_id = query_params.get("resume_id")

    if resume_id:
        try:
            item = resumes_table.get(resume_id)
            if item and st.session_state['user_email'] in item['fields'].get('UserEmail', ''):
                fields = item['fields']
                st.title("Resume Details")
                st.subheader(fields.get('OriginalFileName', 'Untitled'))

                col_main, col_actions = st.columns([3, 1])

                with col_main:
                    if 'File' in fields and fields['File']:
                        file_url = fields['File'][0]['url']
                        file_name = fields.get('OriginalFileName', '').lower()
                        response = requests.get(file_url)
                        response.raise_for_status()

                        if file_name.endswith('.txt'):
                            content = response.text
                            st.text_area("", content, height=400, disabled=True)
                        elif file_name.endswith('.pdf'):
                            with requests.get(file_url, stream=True) as r:
                                r.raise_for_status()
                                with open("temp.pdf", "wb") as f:
                                    f.write(r.content)
                                with pdfplumber.open("temp.pdf") as pdf:
                                    text = "\n".join(page.extract_text() or "" for page in pdf.pages)
                                os.remove("temp.pdf")
                            st.text_area("", text, height=400, disabled=True)
                        else:
                            st.warning("Unsupported file format.")
                            st.markdown(f'<a href="{file_url}" target="_blank">Download Resume</a>', unsafe_allow_html=True)

                    output = fields.get('Output', '')
                    if output:
                        st.subheader("Enhanced Resume Content")
                        st.text_area("Enhanced Content", output, height=200, disabled=True)
                    st.write(f"**Created**: {item.get('createdTime', 'N/A')}")

                with col_actions:
                    st.markdown("### Actions")
                    if fields.get('Type') == "User Uploaded":
                        resume_token_cost = TOKEN_COSTS["Resume Enhancement"]
                        if st.button("Create Basic Enhanced", key=f"basic_{resume_id}"):
                            try:
                                # Fetch original file content
                                original_file_url = fields['File'][0]['url']
                                file_response = requests.get(original_file_url)
                                file_response.raise_for_status()
                                file_content = file_response.content
                                file_name = fields.get('OriginalFileName', 'Untitled')
                                content_type = "application/pdf" if file_name.endswith(".pdf") else "text/plain"

                                # Create new record without File initially
                                new_record = resumes_table.create({
                                    "UserID": [user_id],
                                    "OriginalFileName": file_name,
                                    "Type": "Basic Enhanced",
                                    "Status": "Requested"
                                })
                                new_record_id = new_record['id']

                                # Upload file to new record
                                file_url = upload_file_to_airtable(
                                    AIRTABLE_BASE_ID,
                                    new_record_id,
                                    "File",
                                    file_content,
                                    file_name,
                                    content_type
                                )

                                # Send webhook with token cost
                                payload = {
                                    "user_id": user_id,
                                    "content_type": "Resume Enhancement",
                                    "details": "Basic Enhanced",
                                    "content_record_id": new_record_id,
                                    "token_cost": resume_token_cost
                                }
                                webhook_url = st.secrets["make"]["resume_webhook_url"]
                                response = requests.post(webhook_url, json=payload)
                                if response.status_code == 200:
                                    st.success("Basic Enhanced resume generation requested!")
                                else:
                                    st.error(f"Failed to request Basic Enhanced: {response.text}")
                            except Exception as e:
                                logger.error(f"Error creating Basic Enhanced record: {str(e)}")
                                st.error(f"Error creating enhancement: {str(e)}")

                        job_url = st.text_input("Job Posting URL", key=f"job_url_{resume_id}")
                        if st.button("Create Targeted Enhanced", key=f"targeted_{resume_id}"):
                            if job_url:
                                try:
                                    # Fetch original file content
                                    original_file_url = fields['File'][0]['url']
                                    file_response = requests.get(original_file_url)
                                    file_response.raise_for_status()
                                    file_content = file_response.content
                                    file_name = fields.get('OriginalFileName', 'Untitled')
                                    content_type = "application/pdf" if file_name.endswith(".pdf") else "text/plain"

                                    # Create new record with JobTargetURL
                                    new_record = resumes_table.create({
                                        "UserID": [user_id],
                                        "OriginalFileName": file_name,
                                        "Type": "Targeted Enhanced",
                                        "Status": "Requested",
                                        "JobTargetURL": job_url
                                    })
                                    new_record_id = new_record['id']

                                    # Upload file to new record
                                    file_url = upload_file_to_airtable(
                                        AIRTABLE_BASE_ID,
                                        new_record_id,
                                        "File",
                                        file_content,
                                        file_name,
                                        content_type
                                    )

                                    # Send webhook with token cost
                                    payload = {
                                        "user_id": user_id,
                                        "content_type": "Resume Enhancement",
                                        "details": "Targeted Enhanced",
                                        "content_record_id": new_record_id,
                                        "token_cost": resume_token_cost,
                                        "job_url": job_url  # Keep job_url separate from content_details
                                    }
                                    webhook_url = st.secrets["make"]["resume_webhook_url"]
                                    response = requests.post(webhook_url, json=payload)
                                    if response.status_code == 200:
                                        st.success("Targeted Enhanced resume generation requested!")
                                    else:
                                        st.error(f"Failed to request Targeted Enhanced: {response.text}")
                                except Exception as e:
                                    logger.error(f"Error creating Targeted Enhanced record: {str(e)}")
                                    st.error(f"Error creating enhancement: {str(e)}")
                            else:
                                st.error("Please enter a job posting URL.")

                    if st.button("Back to Resume Tool", type="secondary"):
                        st.query_params.clear()
                        st.rerun()

            else:
                st.error("Resume not found or unauthorized.")
        except Exception as e:
            logger.error(f"Error loading resume: {str(e)}")
            st.error(f"Error loading resume: {str(e)}")
    
    else:
        st.subheader("Upload a Resume")
        if tokens < TOKEN_COSTS["Resume Enhancement"]:
            st.warning("You need at least 5 tokens to upload a resume. Upgrade your plan or buy more tokens.")
            if st.button("Go to Subscription"):
                st.session_state['page'] = "Subscription"
                st.rerun()
            return

        uploaded_file = st.file_uploader("Upload your resume (PDF or TXT)", type=["pdf", "txt"])
        if st.button("Upload Resume") and uploaded_file:
            cost = TOKEN_COSTS["Resume Enhancement"]
            if tokens >= cost:
                try:
                    file_content = uploaded_file.read()
                    file_name = uploaded_file.name
                    content_type = "application/pdf" if file_name.endswith(".pdf") else "text/plain"
                    resume_record = resumes_table.create({
                        "UserID": [user_id],
                        "OriginalFileName": file_name,
                        "Type": "User Uploaded",
                        "Status": "Uploaded"
                    })
                    resume_record_id = resume_record['id']
                    file_url = upload_file_to_airtable(
                        AIRTABLE_BASE_ID,
                        resume_record_id,
                        "File",
                        file_content,
                        file_name,
                        content_type
                    )
                    st.success(f"Resume uploaded! {cost} token(s) will be deducted upon completion.")
                except Exception as e:
                    logger.error(f"Error creating resume record: {str(e)}")
                    st.error(f"Error creating resume record: {str(e)}")
            else:
                st.error(f"Not enough tokens! Required: {cost}, Available: {tokens}")

        resume_items = get_user_resumes(user_email)
        
        if resume_items:
            col_left, col_right = st.columns(2)
            
            with col_left:
                st.write("### Uploaded Resumes")
                user_uploaded = [item for item in resume_items if item['fields'].get('Type') == "User Uploaded"]
                if user_uploaded:
                    for item in user_uploaded:
                        fields = item['fields']
                        resume_id = item['id']
                        with st.container():
                            st.markdown(f'<div class="content-card">', unsafe_allow_html=True)
                            if st.button(f"{fields.get('OriginalFileName', 'Untitled')} - {fields.get('Status', 'N/A')}\nCreated: {item.get('createdTime', 'N/A')}", 
                                         key=f"resume_card_{resume_id}", 
                                         type="secondary", 
                                         help="Click to view details", 
                                         use_container_width=True):
                                st.query_params["resume_id"] = resume_id
                                st.rerun()
                            st.markdown('</div>', unsafe_allow_html=True)
                else:
                    st.info("No uploaded resumes found.")

            with col_right:
                st.write("### Generated Resumes")
                generated = [item for item in resume_items if item['fields'].get('Type') in ["Basic Enhanced", "Targeted Enhanced"]]
                if generated:
                    for item in generated:
                        fields = item['fields']
                        resume_id = item['id']
                        with st.container():
                            st.markdown(f'<div class="content-card">', unsafe_allow_html=True)
                            if st.button(f"{fields.get('Type', 'Untitled')} - {fields.get('Status', 'N/A')}\nCreated: {item.get('createdTime', 'N/A')}", 
                                         key=f"resume_card_{resume_id}", 
                                         type="secondary", 
                                         help="Click to view details", 
                                         use_container_width=True):
                                st.query_params["resume_id"] = resume_id
                                st.rerun()
                            st.markdown('</div>', unsafe_allow_html=True)
                else:
                    st.info("No generated resumes found.")
        else:
            st.info("No resumes found.")
            
# Request content (unchanged)
def request_content(user_id, content_type, details, content_record_id, token_cost, keywords, word_count, platform):
    webhook_url = st.secrets["make"]["webhook_url"]
    payload = {
        "user_id": user_id,
        "content_type": content_type,  # Universal for all content types
        "details": details,
        "record_id": content_record_id,
        "token_cost": token_cost,
        "keywords": keywords,
        "word_count": word_count,
        "platform": platform
    }
    try:
        logger.debug(f"Sending webhook to {webhook_url} with payload: {payload}")
        response = requests.post(webhook_url, json=payload)
        if response.status_code == 200:
            logger.debug("Webhook fired successfully")
            return True
        else:
            logger.error(f"Webhook failed with status {response.status_code}: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Error firing webhook: {str(e)}")
        return False

# Main with enhanced logging
def main():
    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False
    if 'page' not in st.session_state:
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
            logger.error(f"Subscription update failed for {user_id_from_url}: {str(e)}")
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
        with st.sidebar:
            st.markdown("<h2 style='color: #1E293B;'>AI Toolbox</h2>", unsafe_allow_html=True)
            user_id = st.session_state['user_id']
            user_email = st.session_state['user_email']
            sub_status, tokens, name, _, _, _ = get_user_data(user_id)
            st.write(f"**User**: {name or 'N/A'}")
            st.write(f"**Plan**: {sub_status}")
            st.write(f"**Tokens**: {tokens}")

            with st.expander("📝 Content Generation", expanded=False):
                if st.button("✍️ Blog Post", key="nav_blog"):
                    st.session_state['page'] = "Blog Post"
                    st.rerun()
                if st.button("🔍 SEO Article", key="nav_seo"):
                    st.session_state['page'] = "SEO Article"
                    st.rerun()
                if st.button("📱 Social Media Post", key="nav_social"):
                    st.session_state['page'] = "Social Media Post"
                    st.rerun()

            with st.expander("🤖 AI Agents", expanded=False):
                if st.button("🎙️ Resume Enhancement", key="nav_resume"):
                    st.session_state['page'] = "Resume Enhancement"
                    st.rerun()
                st.write("More tools coming soon...")

            st.markdown("---")
            if st.button("⚙️ Settings", key="nav_settings"):
                st.session_state['page'] = "Settings"
                st.rerun()
            if st.button("💳 Subscription", key="nav_subscription"):
                st.session_state['page'] = "Subscription"
                st.rerun()
            if st.button("🚪 Logout", key="nav_logout"):
                st.session_state['logged_in'] = False
                st.session_state.pop('user_id', None)
                st.session_state.pop('user_email', None)
                st.session_state.pop('user_data', None)
                st.rerun()

        page = st.session_state.get('page', "Blog Post")
        if page in ["Blog Post", "SEO Article", "Social Media Post"]:
            content_tool_page(page)
        elif page == "Resume Enhancement":
            resume_enhancement_page()
        elif page == "Subscription":
            subscription_page()
        elif page == "Settings":
            settings_page()

if __name__ == "__main__":
    main()