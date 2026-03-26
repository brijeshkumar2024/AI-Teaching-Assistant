import streamlit as st
import os
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="EduAI — AI Teaching Assistant",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ✅ IMPORT CSS
from app.styles import PREMIUM_CSS

# ✅ APPLY CSS (NO f-string, NO double style)
st.markdown(PREMIUM_CSS, unsafe_allow_html=True)

from app.styles import PREMIUM_CSS

from database.models import init_db

@st.cache_resource
def startup():
    try: init_db()
    except Exception as e: print(f"DB: {e}")
    return True

startup()

def init_session():
    for k,v in {
        "role":None,"student_id":None,"course_id":None,"logged_in":False
    }.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_session()

def _render_auth():
    """Full-screen glassmorphism auth page."""
    from core.embeddings import list_courses
    from core.auth       import register_student, login_student

    # Hide sidebar on auth page
    st.markdown("""
    <style>
    [data-testid="stSidebar"] { display:none !important; }
    .main .block-container { max-width:460px !important; padding-top:3rem !important; }
    </style>
    """, unsafe_allow_html=True)

    courses = list_courses()

    # Logo
    st.markdown("""
    <div style='text-align:center; margin-bottom:32px;'>
        <div style='font-size:52px; margin-bottom:10px;
             filter:drop-shadow(0 0 20px rgba(79,142,247,0.5));
             animation:float 3s ease-in-out infinite;'>🎓</div>
        <div style='font-family:"Clash Display","Syne",sans-serif; font-size:34px; font-weight:700;
             background:linear-gradient(135deg,#ffffff 0%,#b4c8ff 50%,#818cf8 100%);
             -webkit-background-clip:text; -webkit-text-fill-color:transparent;
             background-clip:text; letter-spacing:-1px;'>EduAI</div>
        <div style='color:#7878aa; font-size:13px; margin-top:4px; letter-spacing:0.5px;'>
            AI-Powered Teaching Assistant
        </div>
    </div>
    <style>
    @keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-8px)}}
    </style>
    """, unsafe_allow_html=True)

    # Role selector
    st.markdown("<div class='auth-card'>", unsafe_allow_html=True)
    role = st.radio("role", ["👤 Student", "👨‍🏫 Instructor"],
                    horizontal=True, label_visibility="collapsed", key="auth_role")

    st.markdown("<div class='neon-divider'></div>", unsafe_allow_html=True)

    if "Student" in role:
        tab_login, tab_reg = st.tabs(["🔑 Login", "✨ Register"])

        with tab_login:
            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
            lid  = st.text_input("Student ID", placeholder="e.g. brijesh_2024", key="l_id")
            lpwd = st.text_input("Password",   placeholder="Your password",      key="l_pwd", type="password")
            lcourse = st.selectbox("Course", courses, key="l_course") if courses else \
                      st.text_input("Course ID", placeholder="python101",         key="l_course_m")

            c1, c2 = st.columns([3,2])
            with c1:
                if st.button("🚀 Login", use_container_width=True, key="btn_login"):
                    if lid and lpwd:
                        from core.auth import login_student
                        r = login_student(lid, lpwd)
                        if r["success"]:
                            st.session_state.update({"role":"student","student_id":lid.strip().lower().replace(" ","_"),"course_id":lcourse,"logged_in":True})
                            st.rerun()
                        else: st.error(r["message"])
                    else: st.warning("Enter your ID and password.")
            with c2:
                if st.button("👤 Guest", use_container_width=True, key="btn_guest"):
                    sid = lid.strip() or "guest"
                    st.session_state.update({"role":"student","student_id":sid.lower().replace(" ","_"),"course_id":lcourse or (courses[0] if courses else "python101"),"logged_in":True})
                    st.rerun()

            st.markdown("""
            <div style='margin-top:12px; padding:10px 14px; background:rgba(79,142,247,0.06);
                 border:1px solid rgba(79,142,247,0.15); border-radius:8px;
                 font-size:12px; color:#7878aa; text-align:center;'>
                No account? <strong style='color:#93c5fd;'>Guest Mode</strong> lets you explore instantly
            </div>
            """, unsafe_allow_html=True)

        with tab_reg:
            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
            c1,c2 = st.columns(2)
            rname  = c1.text_input("Full Name",   placeholder="Brijesh Kumar",  key="r_n")
            rid    = c2.text_input("Student ID",  placeholder="brijesh_2024",   key="r_id")
            remail = st.text_input("Email",        placeholder="your@email.com (optional)", key="r_e")
            c3,c4  = st.columns(2)
            rpwd   = c3.text_input("Password",    placeholder="Min 6 chars",    key="r_p",  type="password")
            rpwd2  = c4.text_input("Confirm",     placeholder="Repeat",         key="r_p2", type="password")
            rcourse= st.selectbox("Course", courses, key="r_c") if courses else \
                     st.text_input("Course ID",   placeholder="python101",       key="r_cm")

            if st.button("✅ Create Account", use_container_width=True, key="btn_reg"):
                if not (rname and rid and rpwd):
                    st.warning("Fill in name, ID and password.")
                elif len(rpwd) < 6:
                    st.error("Password must be 6+ characters.")
                elif rpwd != rpwd2:
                    st.error("Passwords don't match.")
                else:
                    from core.auth import register_student
                    result = register_student(rid, rname, rpwd, remail, rcourse)
                    if result["success"]:
                        st.success("✅ Account created! Logging you in…")
                        st.session_state.update({"role":"student","student_id":rid.strip().lower().replace(" ","_"),"course_id":rcourse,"logged_in":True})
                        st.rerun()
                    else: st.error(result["message"])

    else:
        # Instructor
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        ipwd    = st.text_input("Password", placeholder="Instructor password", type="password", key="i_pwd")
        icourse = st.selectbox("Course", courses, key="i_c") if courses else \
                  st.text_input("Course ID", placeholder="python101", key="i_cm")

        if st.button("📊 Open Dashboard", use_container_width=True, key="btn_inst"):
            if ipwd == os.getenv("INSTRUCTOR_PASSWORD","admin123"):
                st.session_state.update({"role":"instructor","course_id":icourse,"logged_in":True})
                st.rerun()
            else: st.error("Incorrect password.")

        st.markdown("""
        <div style='margin-top:12px; padding:10px 14px; background:rgba(79,142,247,0.06);
             border:1px solid rgba(79,142,247,0.15); border-radius:8px;
             font-size:12px; color:#7878aa; text-align:center;'>
            Default password: <code style='color:#93c5fd;'>admin123</code>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)

# ── Sidebar for logged-in users ───────────────────────────────────────────
if st.session_state.logged_in:
    from app.student_ui import render_sidebar_logged_in
    render_sidebar_logged_in()

# ── Route ─────────────────────────────────────────────────────────────────
if not st.session_state.logged_in:
    _render_auth()
elif st.session_state.role == "student":
    from app.student_ui import render_student_ui
    render_student_ui()
elif st.session_state.role == "instructor":
    from app.instructor_dashboard import render_instructor_dashboard
    render_instructor_dashboard()


# Make _render_auth accessible at module level
import sys
sys.modules[__name__]._render_auth = _render_auth
