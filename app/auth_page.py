"""
app/auth_page.py
─────────────────
Full-screen premium login & registration page.
Completely separate from sidebar — takes over the main area.
"""

import streamlit as st
from core.embeddings import list_courses
from core.auth       import register_student, login_student


def render_auth_page():
    """Renders the full-screen login/registration page."""

    # Hide sidebar completely on auth page
    st.markdown("""
    <style>
    [data-testid="stSidebar"] { display: none !important; }
    .main .block-container { max-width: 480px !important; margin: 0 auto !important; padding-top: 4rem !important; }
    </style>
    """, unsafe_allow_html=True)

    courses = list_courses()

    # ── Logo + Hero ───────────────────────────────────────────────────
    st.markdown("""
    <div style='text-align:center; margin-bottom:40px;'>
        <div style='font-size:48px; margin-bottom:12px;'>🎓</div>
        <div style='font-family:"Syne",sans-serif; font-size:32px; font-weight:800;
             background:linear-gradient(135deg,#f8f8ff 30%,#fbbf24);
             -webkit-background-clip:text; -webkit-text-fill-color:transparent;
             background-clip:text; letter-spacing:-1px;'>EduAI</div>
        <div style='color:#58586a; font-size:13px; margin-top:6px; letter-spacing:0.5px;'>
            AI-Powered Teaching Assistant
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Role selector ─────────────────────────────────────────────────
    role = st.radio("I am a", ["Student", "Instructor"],
                    horizontal=True, label_visibility="collapsed")

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    if role == "Student":
        _render_student_auth(courses)
    else:
        _render_instructor_auth(courses)

    # ── Footer ────────────────────────────────────────────────────────
    st.markdown("""
    <div style='text-align:center; margin-top:40px; color:#2e2e3a; font-size:12px;'>
        EduAI · Built with LangGraph + NVIDIA + MongoDB
    </div>
    """, unsafe_allow_html=True)


def _render_student_auth(courses):
    """Student login + register card."""

    # Tab switcher
    tab_login, tab_register = st.tabs(["🔑 Login", "✨ Register"])

    with tab_login:
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        st.markdown("""
        <div style='color:#a8a8c0; font-size:13px; margin-bottom:16px;'>
            Welcome back! Enter your credentials to continue.
        </div>
        """, unsafe_allow_html=True)

        login_id  = st.text_input("Student ID", placeholder="e.g. brijesh_2024",  key="l_id")
        login_pwd = st.text_input("Password",   placeholder="Your password",        key="l_pwd", type="password")

        if courses:
            login_course = st.selectbox("Select Course", courses, key="l_course")
        else:
            login_course = st.text_input("Course ID", placeholder="e.g. java301", key="l_course_manual")

        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
        col1, col2 = st.columns([3,2])

        with col1:
            if st.button("🚀 Login", use_container_width=True, key="do_login"):
                if login_id and login_pwd:
                    result = login_student(login_id, login_pwd)
                    if result["success"]:
                        _set_session("student", login_id, login_course)
                    else:
                        st.error(result["message"])
                else:
                    st.warning("Enter your ID and password.")

        with col2:
            if st.button("👤 Guest Mode", use_container_width=True, key="do_guest"):
                name = login_id.strip() or "guest"
                _set_session("student", name, login_course or (courses[0] if courses else "python101"))

        st.markdown("""
        <div style='margin-top:12px; padding:12px; background:rgba(251,191,36,0.05);
             border:1px solid rgba(251,191,36,0.1); border-radius:8px;
             font-size:12px; color:#78786a;'>
            💡 No account? Use <strong style='color:#fbbf24;'>Guest Mode</strong> to explore without registering.
        </div>
        """, unsafe_allow_html=True)

    with tab_register:
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        st.markdown("""
        <div style='color:#a8a8c0; font-size:13px; margin-bottom:16px;'>
            Create your account to track progress across sessions.
        </div>
        """, unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        with col1:
            reg_name = st.text_input("Full Name",   placeholder="Brijesh Kumar",  key="r_name")
        with col2:
            reg_id   = st.text_input("Student ID",  placeholder="brijesh_2024",   key="r_id")

        reg_email = st.text_input("Email (optional)", placeholder="your@email.com", key="r_email")

        col3, col4 = st.columns(2)
        with col3:
            reg_pwd  = st.text_input("Password",    placeholder="Min 6 chars",    key="r_pwd",  type="password")
        with col4:
            reg_pwd2 = st.text_input("Confirm",     placeholder="Repeat password", key="r_pwd2", type="password")

        if courses:
            reg_course = st.selectbox("Course", courses, key="r_course")
        else:
            reg_course = st.text_input("Course ID", placeholder="java301", key="r_course_manual")

        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

        if st.button("✅ Create Account", use_container_width=True, key="do_register"):
            if not (reg_name and reg_id and reg_pwd):
                st.warning("Fill in name, ID, and password.")
            elif len(reg_pwd) < 6:
                st.error("Password must be at least 6 characters.")
            elif reg_pwd != reg_pwd2:
                st.error("Passwords don't match.")
            else:
                result = register_student(reg_id, reg_name, reg_pwd, reg_email, reg_course)
                if result["success"]:
                    st.success(f"✅ Account created! Logging you in...")
                    _set_session("student", reg_id, reg_course)
                else:
                    st.error(result["message"])


def _render_instructor_auth(courses):
    """Instructor login card."""
    import os
    st.markdown("""
    <div style='color:#a8a8c0; font-size:13px; margin-bottom:16px;'>
        Instructor access — enter your password to view analytics.
    </div>
    """, unsafe_allow_html=True)

    pwd    = st.text_input("Instructor Password", type="password",
                           placeholder="Enter password", key="inst_pwd")
    course = st.selectbox("Course to manage", courses, key="inst_course") if courses else \
             st.text_input("Course ID", placeholder="python101", key="inst_course_manual")

    if st.button("📊 Open Dashboard", use_container_width=True, key="do_instructor"):
        if pwd == os.getenv("INSTRUCTOR_PASSWORD", "admin123"):
            st.session_state.role      = "instructor"
            st.session_state.course_id = course
            st.session_state.logged_in = True
            st.rerun()
        else:
            st.error("Incorrect password.")

    st.markdown("""
    <div style='margin-top:12px; padding:12px; background:rgba(56,189,248,0.05);
         border:1px solid rgba(56,189,248,0.1); border-radius:8px;
         font-size:12px; color:#58586a;'>
        🔐 Default password: <code style='color:#7dd3fc;'>admin123</code> — change in .env file
    </div>
    """, unsafe_allow_html=True)


def _set_session(role: str, student_id: str, course_id: str):
    """Set session state and rerun."""
    st.session_state.role       = role
    st.session_state.student_id = student_id.strip().lower().replace(" ", "_")
    st.session_state.course_id  = course_id
    st.session_state.logged_in  = True
    st.rerun()