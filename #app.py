"""
Weekly Teacher Class Logging App
================================
Streamlit + Google Sheets (gspread).

Features:
  - Teacher view: Sign-in via Email + PIN/Password, weekly submission form.
  - Admin view: Locked by Admin Password. Contains:
      1. Register New Teacher (duplicate email prevention + plain text stored PIN/Password).
      2. Manage Teacher Credentials (Update Password, Sections, Subjects OR Delete Account).
      3. View Logs & Teachers Register.
  - Log format:
      [Day, Teacher Name, Class Name, Section, Subject, Topic, Time Duration, Date]
"""

import hashlib
import hmac
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

# ----------------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------------
st.set_page_config(page_title="Weekly Class Log", page_icon="📚", layout="centered")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

TEACHERS_TAB = "Teachers"
TEACHERS_HEADERS = ["Registered At", "Name", "Email", "Password / PIN", "Sections", "Subjects"]

LOG_TAB = "Log"
LOG_HEADERS = ["Day", "Teacher Name", "Class Name", "Section", "Subject", "Topic", "Time Duration", "Date"]

DEFAULT_SUBJECTS = [
    "English", "Urdu", "Mathematics", "Science", "Social Studies",
    "Islamiyat", "Computer Science", "Art", "Physical Education",
]

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def cfg(section: str, key: str, default=None):
    """Safe accessor for st.secrets[section][key]."""
    try:
        return st.secrets[section][key]
    except Exception:
        return default


TZ = ZoneInfo(cfg("app", "timezone", "Asia/Karachi"))
SUBJECTS = list(cfg("app", "subjects", DEFAULT_SUBJECTS))

# ---------------------------------------------------------------------------
# GRADE/SECTION -> GOOGLE SHEET ID MAPPING
# Loaded from [section_sheets] in secrets.toml
# ---------------------------------------------------------------------------
SECTION_SHEETS: dict[str, str] = dict(st.secrets.get("section_sheets", {})) if "section_sheets" in st.secrets else {}


# ----------------------------------------------------------------------------
# TIME / DEADLINE LOGIC
# ----------------------------------------------------------------------------
def now_local() -> datetime:
    return datetime.now(TZ)


def week_label(dt: datetime) -> str:
    """ISO week label, e.g. '2026-W41'."""
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def submissions_open(dt: datetime) -> bool:
    """
    Submissions are open Monday-Saturday and closed on Sunday (weekday() == 6).
    """
    return dt.weekday() != 6


CLOSED_MSG = "Submissions for this week closed on Saturday at 11:59 PM."


# ----------------------------------------------------------------------------
# GOOGLE SHEETS CONNECTION
# ----------------------------------------------------------------------------
@st.cache_resource
def get_client() -> gspread.Client:
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=SCOPES
    )
    return gspread.authorize(creds)


@st.cache_resource(ttl=3600)
def get_ws(sheet_id: str, tab: str, headers: tuple) -> gspread.Worksheet:
    """Open a worksheet, creating the tab and header row if missing."""
    sh = get_client().open_by_key(sheet_id)
    try:
        ws = sh.worksheet(tab)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab, rows=1000, cols=len(headers))
    if not ws.row_values(1):
        ws.append_row(list(headers), value_input_option="RAW")
    return ws


def teachers_ws() -> gspread.Worksheet:
    return get_ws(st.secrets["sheets"]["teachers_register_id"], TEACHERS_TAB, tuple(TEACHERS_HEADERS))


def log_ws(section: str) -> gspread.Worksheet:
    """Dynamic routing: pick the spreadsheet that belongs to this section."""
    sheet_id = SECTION_SHEETS.get(section)
    if not sheet_id:
        raise KeyError(f"No Google Sheet configured for '{section}'")
    return get_ws(sheet_id, LOG_TAB, tuple(LOG_HEADERS))


# ----------------------------------------------------------------------------
# AUTH & DATA HELPERS
# ----------------------------------------------------------------------------
def get_all_teachers_with_rows():
    """Retrieve all teacher records along with their actual 1-based row numbers."""
    all_recs = teachers_ws().get_all_records()
    teacher_list = []
    for idx, row in enumerate(all_recs, start=2):  # Header is Row 1
        teacher_list.append({
            "row_idx": idx,
            "data": row
        })
    return teacher_list


def find_teacher_by_email(email: str):
    """Find the first teacher record for sign-in."""
    email = email.strip().lower()
    for item in get_all_teachers_with_rows():
        if str(item["data"].get("Email", "")).strip().lower() == email:
            return item["data"]
    return None


def split_list(value: str) -> list[str]:
    return [v.strip() for v in str(value).split(";") if v.strip()]


# ----------------------------------------------------------------------------
# UI HEADER
# ----------------------------------------------------------------------------
st.title("📚 Weekly Class Log")
now = now_local()
st.caption(f"{now:%A, %d %b %Y %I:%M %p} · Current week: **{week_label(now)}**")

if not SECTION_SHEETS or "gcp_service_account" not in st.secrets:
    st.error("App is not configured yet. Add your secrets.")
    st.stop()

tab_teacher, tab_admin = st.tabs(["✏️ Teacher Portal", "🔒 Admin Dashboard"])

# ----------------------------------------------------------------------------
# TAB 1 - TEACHER PORTAL
# ----------------------------------------------------------------------------
with tab_teacher:
    st.subheader("Teacher Portal")
    teacher = st.session_state.get("teacher")

    if not teacher:
        st.info("Please sign in with your Email and Password/PIN.")
        with st.form("login_form"):
            l_email = st.text_input("Email")
            l_pin = st.text_input("Password / PIN", type="password")
            login = st.form_submit_button("Sign in")

        if login:
            if not l_email or not l_pin:
                st.error("Please enter both email and password/PIN.")
            else:
                try:
                    rec = find_teacher_by_email(l_email)
                    if rec and str(rec.get("Password / PIN", "")) == l_pin.strip():
                        st.session_state["teacher"] = {
                            "name": rec["Name"],
                            "email": rec["Email"],
                            "sections": split_list(rec["Sections"]),
                            "subjects": split_list(rec["Subjects"]),
                        }
                        st.success("Logged in successfully!")
                        st.rerun()
                    else:
                        st.error("Invalid email or Password/PIN.")
                except Exception as e:
                    st.error(f"Sign-in failed: {e}")
    else:
        c1, c2 = st.columns([3, 1])
        c1.write(f"Signed in as: **{teacher['name']}** (`{teacher['email']}`)")
        if c2.button("Sign out"):
            st.session_state.pop("teacher")
            st.rerun()

        st.divider()

        if not submissions_open(now_local()):
            st.warning(CLOSED_MSG)
        else:
            with st.form("log_form", clear_on_submit=True):
                section = st.selectbox("Grade / Section", teacher["sections"])
                
                class_name = section.split("-")[0].strip() if "-" in section else section
                sec_label = section.split("-")[1].strip() if "-" in section else "A"

                subject = st.selectbox("Subject", teacher["subjects"])
                topic = st.text_area(
                    "Topic / Lesson Taught",
                    height=120,
                    placeholder="e.g. Fractions: adding unlike denominators; Exercise 4.2",
                )
                duration = st.text_input("Time Duration", placeholder="e.g. 45 mins, 1 hour")

                submit = st.form_submit_button("Submit Log")

            if submit:
                ts = now_local()
                if not submissions_open(ts):
                    st.warning(CLOSED_MSG)
                elif not topic.strip():
                    st.error("Please enter the Topic / Lesson taught.")
                elif not duration.strip():
                    st.error("Please enter the Time Duration.")
                else:
                    try:
                        row_data = [
                            ts.strftime("%A"),          # Day
                            teacher["name"],            # Teacher name
                            class_name,                 # Class name
                            sec_label,                  # Section
                            subject,                    # Subject
                            topic.strip(),              # Topic
                            duration.strip(),           # Time Duration
                            ts.strftime("%Y-%m-%d"),    # Date
                        ]

                        log_ws(section).append_row(row_data, value_input_option="RAW")
                        st.success(f"Log submitted for {section}! ✅")
                    except Exception as e:
                        st.error(f"Could not save log: {e}")

# ----------------------------------------------------------------------------
# TAB 2 - ADMIN DASHBOARD
# ----------------------------------------------------------------------------
with tab_admin:
    st.subheader("Admin Dashboard")
    admin_pw = cfg("admin", "password")

    if not st.session_state.get("is_admin"):
        with st.form("admin_login_form"):
            pw = st.text_input("Enter Admin Password", type="password")
            ok = st.form_submit_button("Unlock Admin View")
        if ok:
            if admin_pw and hmac.compare_digest(pw, str(admin_pw)):
                st.session_state["is_admin"] = True
                st.rerun()
            else:
                st.error("Wrong admin password.")
    else:
        if st.button("Lock Admin View"):
            st.session_state["is_admin"] = False
            st.rerun()

        st.divider()

        admin_action = st.radio(
            "Admin Menu",
            ["➕ Register Teacher", "🔑 Manage Credentials / Delete", "📋 View Class Logs", "👥 Registered Teachers List"],
            horizontal=True,
        )

        # --------------------------------------------------------------------
        # ADMIN ACTION 1: REGISTER TEACHER
        # --------------------------------------------------------------------
        if admin_action == "➕ Register Teacher":
            st.write("### Create New Teacher Account")
            with st.form("admin_reg_form", clear_on_submit=True):
                name = st.text_input("Full Name")
                email = st.text_input("Email Address")
                pin = st.text_input("Set Password / PIN", type="password")
                sections = st.multiselect("Assigned Grade / Section(s)", list(SECTION_SHEETS.keys()))
                subjects = st.multiselect("Assigned Subject(s)", SUBJECTS)
                create_acc = st.form_submit_button("Create Account")

            if create_acc:
                clean_email = email.strip().lower()
                if not name.strip():
                    st.error("Please enter the teacher's name.")
                elif not EMAIL_RE.match(clean_email):
                    st.error("Please enter a valid email address.")
                elif not pin.strip():
                    st.error("Please set a password/PIN.")
                elif not sections or not subjects:
                    st.error("Select at least one section and subject.")
                else:
                    existing = find_teacher_by_email(clean_email)
                    if existing:
                        st.error(f"Duplicate Email! The email '{clean_email}' is already registered.")
                    else:
                        try:
                            teachers_ws().append_row(
                                [
                                    now_local().strftime("%Y-%m-%d %H:%M:%S"),
                                    name.strip(),
                                    clean_email,
                                    pin.strip(),
                                    "; ".join(sections),
                                    "; ".join(subjects),
                                ],
                                value_input_option="RAW",
                            )
                            st.cache_data.clear()
                            st.success(f"Account created successfully for {name.strip()}!")
                        except Exception as e:
                            st.error(f"Failed to create account: {e}")

        # --------------------------------------------------------------------
        # ADMIN ACTION 2: MANAGE CREDENTIALS & DELETE ACCOUNTS
        # --------------------------------------------------------------------
        elif admin_action == "🔑 Manage Credentials / Delete":
            st.write("### Update or Delete Teacher Account")
            try:
                teachers_list = get_all_teachers_with_rows()
                if not teachers_list:
                    st.info("No registered teachers found.")
                else:
                    # Create labels including row numbers so duplicates are individually selectable
                    options_map = {
                        f"{t['data'].get('Email', 'No Email')} - {t['data'].get('Name', '')} (Row {t['row_idx']})": t
                        for t in teachers_list
                    }

                    selected_label = st.selectbox("Select Teacher Account", list(options_map.keys()))
                    selected_item = options_map[selected_label]
                    row_idx = selected_item["row_idx"]
                    t_data = selected_item["data"]

                    col_update, col_delete = st.columns([2, 1])

                    with col_update:
                        st.markdown("#### Update Details")
                        with st.form("update_credentials_form"):
                            new_pass = st.text_input("Password / PIN", value=str(t_data.get("Password / PIN", "")))
                            new_sections = st.multiselect(
                                "Assigned Sections",
                                list(SECTION_SHEETS.keys()),
                                default=split_list(t_data.get("Sections", "")),
                            )
                            new_subjects = st.multiselect(
                                "Assigned Subjects",
                                SUBJECTS,
                                default=split_list(t_data.get("Subjects", "")),
                            )
                            update_btn = st.form_submit_button("Update Account Details")

                        if update_btn:
                            if not new_pass.strip():
                                st.error("Password/PIN cannot be empty.")
                            else:
                                try:
                                    ws = teachers_ws()
                                    ws.update_cell(row_idx, 4, new_pass.strip())
                                    ws.update_cell(row_idx, 5, "; ".join(new_sections))
                                    ws.update_cell(row_idx, 6, "; ".join(new_subjects))
                                    st.cache_data.clear()
                                    st.success(f"Updated account for {t_data.get('Name')}!")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Failed to update: {e}")

                    with col_delete:
                        st.markdown("#### Danger Zone")
                        st.warning("Deleting this account will remove it completely from the registry.")
                        if st.button("🗑️ Delete This Account", type="primary"):
                            try:
                                teachers_ws().delete_rows(row_idx)
                                st.cache_data.clear()
                                st.success(f"Successfully deleted {t_data.get('Email')} (Row {row_idx})!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Failed to delete row: {e}")

            except Exception as e:
                st.error(f"Could not fetch teacher records: {e}")

        # --------------------------------------------------------------------
        # ADMIN ACTION 3: VIEW LOGS
        # --------------------------------------------------------------------
        elif admin_action == "📋 View Class Logs":
            section = st.selectbox("Select Section", list(SECTION_SHEETS.keys()))
            try:
                df = pd.DataFrame(log_ws(section).get_all_records())
                if df.empty:
                    st.info("No log entries submitted for this section yet.")
                else:
                    st.dataframe(df, use_container_width=True, hide_index=True)
                    st.download_button("Download CSV", df.to_csv(index=False), f"{section}_logs.csv", "text/csv")
            except Exception as e:
                st.error(f"Could not load logs: {e}")

        # --------------------------------------------------------------------
        # ADMIN ACTION 4: REGISTERED TEACHERS LIST
        # --------------------------------------------------------------------
        else:
            try:
                df = pd.DataFrame(teachers_ws().get_all_records())
                if df.empty:
                    st.info("No registered teachers.")
                else:
                    st.dataframe(df, use_container_width=True, hide_index=True)
            except Exception as e:
                st.error(f"Could not load teachers list: {e}")