"""
app/course_manager.py
──────────────────────
Course management panel.
- Instructors: create, delete, upload materials to any course
- Students: view and select available courses only
"""

import os
import tempfile
import streamlit as st

from core.embeddings  import ingest_course_materials, list_courses, delete_course
from database.models  import upsert_course


def render_course_manager_instructor():
    """
    Full course management panel for instructors.
    Shown in instructor dashboard sidebar.
    """
    st.markdown("""
    <p style='font-size:11px; letter-spacing:1.5px; text-transform:uppercase; color:#8892b0;'>
        Course Management
    </p>
    """, unsafe_allow_html=True)

    courses = list_courses()

    # ── Create new course ─────────────────────────────────────────────
    with st.expander("➕ Create New Course", expanded=False):
        new_id   = st.text_input("Course ID",   placeholder="e.g. python101",    key="new_course_id")
        new_name = st.text_input("Course Name", placeholder="e.g. Intro to Python", key="new_course_name")
        new_desc = st.text_area("Description",  placeholder="Short description...", height=60, key="new_course_desc")

        if st.button("✅ Create Course", use_container_width=True, key="create_course_btn"):
            if new_id and new_name:
                cid = new_id.strip().lower().replace(" ","_")
                try:
                    upsert_course(cid, new_name, new_desc)
                    st.success(f"✅ Course '{cid}' created! Now upload PDF materials for it.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")
            else:
                st.warning("Course ID and name are required.")

    # ── Upload materials to existing course ───────────────────────────
    with st.expander("📁 Upload Course Materials", expanded=False):
        if courses:
            target_course = st.selectbox("Upload to course", courses, key="upload_target")
        else:
            target_course = st.text_input("Course ID", placeholder="python101", key="upload_target_manual")

        uploaded   = st.file_uploader("PDFs", type=["pdf"],
                        accept_multiple_files=True, label_visibility="collapsed",
                        key="instructor_pdf_upload")
        extra_text = st.text_area("Or paste text", height=80,
                        label_visibility="collapsed",
                        placeholder="Paste syllabus, notes, or any text...",
                        key="instructor_extra_text")

        if st.button("⚡ Ingest Materials", use_container_width=True, key="ingest_btn"):
            if target_course and (uploaded or extra_text):
                with st.spinner("Processing..."):
                    pdf_paths = []
                    for f in uploaded:
                        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                            tmp.write(f.read())
                            pdf_paths.append(tmp.name)
                    try:
                        n = ingest_course_materials(
                            course_id  = target_course,
                            pdf_paths  = pdf_paths,
                            extra_text = extra_text or None,
                        )
                        st.success(f"✅ {n} chunks ingested into '{target_course}'!")
                    except Exception as e:
                        st.error(f"Error: {e}")
                    finally:
                        for p in pdf_paths:
                            if os.path.exists(p): os.unlink(p)
            else:
                st.warning("Select a course and provide materials.")

    # ── Available courses list ────────────────────────────────────────
    if courses:
        st.markdown(f"""
        <p style='font-size:11px; color:#8892b0; margin-top:12px;'>
            {len(courses)} course{"s" if len(courses)>1 else ""} available
        </p>
        """, unsafe_allow_html=True)
        for c in courses:
            col1, col2 = st.columns([3,1])
            col1.markdown(f"<div style='padding:6px 0; font-size:13px;'>📚 {c}</div>", unsafe_allow_html=True)
            if col2.button("🗑️", key=f"del_{c}", help=f"Delete {c}"):
                delete_course(c)
                st.success(f"Deleted '{c}'")
                st.rerun()
    else:
        st.markdown("<p style='font-size:12px; color:#8892b0;'>No courses yet — create one above.</p>", unsafe_allow_html=True)


def render_course_selector_student():
    """
    Course selector for students — read only, just pick from available courses.
    Used in the student login sidebar.
    """
    courses = list_courses()
    if courses:
        return st.selectbox("Select your course", courses,
                            label_visibility="collapsed", key="student_course_select")
    else:
        return st.text_input("Course ID", placeholder="e.g. python101",
                             label_visibility="collapsed", key="student_course_manual")