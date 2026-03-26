"""
app/student_ui.py — Ultra Premium Student Chat Interface
"""

import os, tempfile
import streamlit as st
from agents.orchestrator import chat_stream
from core.embeddings     import ingest_course_materials

BADGES = {
    "rag_qa"       : '<span class="badge badge-qa">💡 Knowledge Base</span>',
    "code_review"  : '<span class="badge badge-code">🔍 Code Review</span>',
    "quiz_generate": '<span class="badge badge-quiz">🎯 Quiz</span>',
    "quiz_evaluate": '<span class="badge badge-eval">✅ Evaluated</span>',
    "smalltalk"    : '<span class="badge badge-chat">💬 Assistant</span>',
    "unknown"      : '<span class="badge badge-chat">🤖 AI</span>',
}

def init_state():
    for k,v in {
        "messages":[],"quiz_active":False,"total_turns":0,
        "input_key":0,"submitted_input":"",
    }.items():
        if k not in st.session_state:
            st.session_state[k] = v


def render_sidebar_logged_in():
    """Sidebar for logged-in users."""
    from app.course_manager import render_course_manager_instructor
    student_id = st.session_state.get("student_id","")
    course_id  = st.session_state.get("course_id","")
    role       = st.session_state.get("role","student")
    name       = (student_id or "User").replace("_"," ").title()

    with st.sidebar:
        # Logo
        st.markdown("""
        <div style='padding:12px 0 16px; border-bottom:1px solid rgba(255,255,255,0.06);'>
            <div style='display:flex; align-items:center; gap:10px;'>
                <span style='font-size:24px; filter:drop-shadow(0 0 10px rgba(79,142,247,0.5));'>🎓</span>
                <div>
                    <div style='font-family:"Clash Display","Syne",sans-serif; font-size:17px; font-weight:700;
                         background:linear-gradient(135deg,#eeeeff,#4f8ef7);
                         -webkit-background-clip:text; -webkit-text-fill-color:transparent;
                         background-clip:text;'>EduAI</div>
                    <div style='font-size:9px; color:#333355; text-transform:uppercase; letter-spacing:1px;'>
                        {role.title()}
                    </div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # User card
        st.markdown(f"""
        <div class='glass-card' style='padding:14px; margin:12px 0;'>
            <div style='font-size:10px; color:#333355; text-transform:uppercase; letter-spacing:1px; margin-bottom:6px;'>
                {'Logged in as' if role=='student' else 'Instructor'}
            </div>
            <div style='font-weight:700; font-size:15px;'>{name}</div>
            <div style='font-size:12px; margin-top:3px;'>
                <span style='color:#4f8ef7;'>📚</span>
                <span style='color:#7878aa;'> {course_id.upper() if course_id else '—'}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        if role == "student":
            # Stats
            turns = st.session_state.get("total_turns", 0)
            quiz  = st.session_state.get("quiz_active", False)
            st.markdown(f"""
            <div style='display:flex; gap:8px; margin-bottom:12px;'>
                <div class='stat-mini' style='flex:1;'>
                    <div class='stat-mini-val'>{turns}</div>
                    <div class='stat-mini-lbl'>Turns</div>
                </div>
                <div class='stat-mini' style='flex:1;'>
                    <div class='stat-mini-val'>{"🎯" if quiz else "💬"}</div>
                    <div class='stat-mini-lbl'>{"Quiz" if quiz else "Chat"}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # Quick prompts
            st.markdown("<div class='section-label'>Quick Actions</div>", unsafe_allow_html=True)
            for q in ["What is recursion?","Quiz me on loops","Explain OOP","Quiz me on functions"]:
                icon = "🎯" if "Quiz" in q or "quiz" in q else "💡"
                if st.button(f"{icon} {q}", use_container_width=True, key=f"qk_{q}"):
                    st.session_state.pending_input = q

            st.markdown("<div class='neon-divider'></div>", unsafe_allow_html=True)

            # Upload
            with st.expander("📁 Upload Materials"):
                uploaded = st.file_uploader("PDFs", type=["pdf"],
                    accept_multiple_files=True, label_visibility="collapsed")
                extra = st.text_area("Paste text", height=60,
                    label_visibility="collapsed", placeholder="Paste notes…")
                if st.button("⚡ Ingest", use_container_width=True, key="ingest_side"):
                    if uploaded or extra:
                        with st.spinner("Processing…"):
                            paths = []
                            for f in uploaded:
                                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as t:
                                    t.write(f.read()); paths.append(t.name)
                            try:
                                n = ingest_course_materials(course_id, paths, extra or None)
                                st.markdown(f'<div class="neon-toast success">✅ {n} chunks ingested!</div>', unsafe_allow_html=True)
                            except Exception as e:
                                st.markdown(f'<div class="neon-toast error">❌ {str(e)}</div>', unsafe_allow_html=True)
                            finally:
                                for p in paths:
                                    if os.path.exists(p): os.unlink(p)

            st.markdown("<div class='neon-divider'></div>", unsafe_allow_html=True)
            if st.button("🗑️ Clear chat", use_container_width=True, key="clear_side"):
                st.session_state.messages    = []
                st.session_state.total_turns = 0
                st.rerun()

        elif role == "instructor":
            render_course_manager_instructor()

        # LLM badge + sign out
        st.markdown("<div class='neon-divider'></div>", unsafe_allow_html=True)
        try:
            from core.llm_config import get_provider_name
            prov = get_provider_name()
        except: prov = "AI"
        st.markdown(f"""
        <div style='background:rgba(79,142,247,0.06); border:1px solid rgba(79,142,247,0.15);
             border-radius:8px; padding:8px 12px; font-size:12px; margin-bottom:10px;
             display:flex; align-items:center; gap:8px;'>
            <span style='width:6px;height:6px;border-radius:50%;background:#10b981;
                  box-shadow:0 0 6px #10b981; display:inline-block;
                  animation:dotPulse 2s infinite;'></span>
            <span style='color:#7878aa;'>{prov}</span>
        </div>
        """, unsafe_allow_html=True)

        if st.button("⎋  Sign Out", use_container_width=True, key="signout"):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()


def render_student_ui():
    init_state()
    sid    = st.session_state.student_id
    cid    = st.session_state.course_id
    name   = sid.replace("_"," ").title()

    # ── Header ────────────────────────────────────────────────────────
    col1, col2 = st.columns([4,1])
    with col1:
        st.markdown(f"""
        <div class='hero-wrap'>
            <div class='hero-title'>Hey, {name}! 👋</div>
            <div class='hero-sub'>{cid.upper()} · Ask anything · Submit code · Take a quiz · Voice input</div>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.session_state.quiz_active:
            st.markdown('<div class="pill pill-quiz"><span class="pill-dot"></span>Quiz Active</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="pill pill-live"><span class="pill-dot"></span>Live</div>', unsafe_allow_html=True)

    # ── Chat history ──────────────────────────────────────────────────
    if not st.session_state.messages:
        st.markdown(f"""
        <div style='text-align:center; padding:64px 20px;'>
            <div style='font-size:52px; margin-bottom:16px;
                 filter:drop-shadow(0 0 20px rgba(79,142,247,0.3));'>🤖</div>
            <div style='font-family:"Clash Display","Syne",sans-serif; font-size:20px;
                 font-weight:700; color:#eeeeff; margin-bottom:8px;'>Ready to help you learn</div>
            <div style='font-size:14px; color:#7878aa; max-width:380px; margin:0 auto; line-height:1.7;'>
                Ask anything about your course, paste code for review, or type
                <strong style='color:#fcd34d;'>quiz me on loops</strong> to test yourself.
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        for msg in st.session_state.messages:
            if msg["role"] == "user":
                msg_content = msg['content'].replace('<','&lt;').replace('>','&gt;')
                st.markdown(f"""
                <div style='display:flex; justify-content:flex-end; margin:6px 0;'>
                    <div style='max-width:75%;'>
                        <div style='text-align:right; font-size:10px; color:#2e2e4a;
                             text-transform:uppercase; letter-spacing:1px; margin-bottom:4px;'>You</div>
                        <div class='bubble-user'>{msg_content}</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            else:
                badge       = BADGES.get(msg.get("agent","unknown"), BADGES["unknown"])
                import html
                ai_content  = html.escape(str(msg["content"])[:4000])
                st.markdown(badge, unsafe_allow_html=True)
                st.markdown(f"<div class='bubble-ai'>{ai_content}</div>", unsafe_allow_html=True)

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
    st.markdown("<div class='neon-divider'></div>", unsafe_allow_html=True)

    # ── Input tabs ────────────────────────────────────────────────────
    tab_chat, tab_code, tab_quiz, tab_plan, tab_voice = st.tabs([
        "💬 Chat", "🐍 Code Review", "📚 Quiz Set", "🗺️ Study Plan", "🎤 Voice"
    ])
    user_input = None

    with tab_chat:
        pending = st.session_state.pop("pending_input", None)
        if pending:
            st.session_state[f"ci_{st.session_state['input_key']}"] = pending

        def on_enter():
            val = st.session_state.get(f"ci_{st.session_state['input_key']}", "").strip()
            if val:
                st.session_state["submitted_input"] = val
                st.session_state["input_key"] += 1

        c1, c2 = st.columns([6, 1])
        with c1:
            st.text_input("Message",
                key=f"ci_{st.session_state['input_key']}",
                placeholder="Ask anything — press Enter to send ↵",
                label_visibility="collapsed",
                on_change=on_enter)
        with c2:
            if st.button("Send ➤", use_container_width=True, key="send_btn"):
                val = st.session_state.get(f"ci_{st.session_state['input_key']}", "").strip()
                if val:
                    st.session_state["submitted_input"] = val
                    st.session_state["input_key"] += 1

        if st.session_state.get("submitted_input"):
            user_input = st.session_state.pop("submitted_input")

    with tab_code:
        st.markdown("<p style='font-size:13px;color:#7878aa;margin-bottom:8px;'>Paste code for AI review — get hints, not answers.</p>", unsafe_allow_html=True)
        code_in  = st.text_area("Code", height=180,
            placeholder="def my_function():\n    pass",
            label_visibility="collapsed", key="code_in")
        topic_in = st.text_input("Topic", placeholder="e.g. Recursion, Sorting (optional)",
            label_visibility="collapsed", key="topic_in")
        if st.button("🔍 Review My Code", use_container_width=True, key="btn_code"):
            if code_in.strip():
                prefix     = f"Review this code for: {topic_in}\n\n" if topic_in else ""
                user_input = prefix + f"```python\n{code_in.strip()}\n```"

    with tab_quiz:
        st.markdown("<p style='font-size:13px;color:#7878aa;margin-bottom:8px;'>Auto-generate a full quiz from your uploaded course PDFs.</p>", unsafe_allow_html=True)
        q_topic = st.text_input("Topic", placeholder="e.g. recursion (blank = all topics)",
            key="qs_t", label_visibility="collapsed")
        c1, c2 = st.columns(2)
        q_count = c1.slider("Questions", 3, 10, 5, key="qs_n")
        q_diff  = c2.select_slider("Difficulty", ["easy","mixed","hard"], value="mixed", key="qs_d")

        c_gen, c_regen = st.columns([3,2])
        if c_gen.button("⚡ Generate Quiz Set", use_container_width=True, key="btn_qs"):
            with st.spinner("Generating from your course material…"):
                try:
                    from agents.quiz_set_agent import generate_quiz_set_from_pdf
                    qs = generate_quiz_set_from_pdf(cid, q_topic or None, q_count, q_diff)
                    # Safe Pydantic conversion for UI
                    if hasattr(qs, 'model_dump'):
                        qs = qs.model_dump()
                    elif hasattr(qs, 'dict'):
                        qs = qs.dict()
                    elif not isinstance(qs, dict):
                        qs = {'questions': [], 'total': 0, 'topic': 'Fallback', 'error': 'Invalid format'}
                    st.session_state["active_qs"]    = qs
                    st.session_state["qs_answers"]   = [""] * qs["total"]
                    st.session_state["qs_submitted"] = False
                    st.session_state["qs_params"]    = (q_topic, q_count, q_diff)
                    st.markdown(f'<div class="neon-toast success">✅ {qs["total"]} questions generated!</div>', unsafe_allow_html=True)
                    if qs.get("error"):
                        st.markdown('<div class="neon-toast warning">⚠️ Auto-corrected formatting. Regenerate if needed.</div>', unsafe_allow_html=True)
                except Exception as e:
                    st.markdown(f'<div class="neon-toast error">❌ {str(e)}</div>', unsafe_allow_html=True)

        if c_regen.button("🔄 Regenerate Quiz", use_container_width=True, key="btn_qs_regen"):
            params = st.session_state.get("qs_params") or (q_topic, q_count, q_diff)
            topic_prev, count_prev, diff_prev = params
            with st.spinner("Regenerating quiz…"):
                try:
                    from agents.quiz_set_agent import generate_quiz_set_from_pdf
                    qs = generate_quiz_set_from_pdf(cid, topic_prev or None, count_prev, diff_prev)
                    # Safe Pydantic conversion for UI
                    if hasattr(qs, 'model_dump'):
                        qs = qs.model_dump()
                    elif hasattr(qs, 'dict'):
                        qs = qs.dict()
                    elif not isinstance(qs, dict):
                        qs = {'questions': [], 'total': 0, 'topic': 'Fallback', 'error': 'Invalid format'}
                    st.session_state["active_qs"]    = qs
                    st.session_state["qs_answers"]   = [""] * qs["total"]
                    st.session_state["qs_submitted"] = False
                    st.markdown('<div class="neon-toast success">✅ New quiz ready!</div>', unsafe_allow_html=True)
                    if qs.get("error"):
                        st.markdown('<div class="neon-toast warning">⚠️ Auto-corrected. Regenerate for cleaner.</div>', unsafe_allow_html=True)
                except Exception as e:
                    st.markdown(f'<div class="neon-toast error">❌ {str(e)}</div>', unsafe_allow_html=True)

        if "active_qs" in st.session_state and not st.session_state.get("qs_submitted"):
            qs  = st.session_state["active_qs"]
            ans = st.session_state["qs_answers"]
            st.markdown(f"<div class='neon-card' style='margin:12px 0 16px;'><b>📚 {qs['topic']}</b> · {qs['total']} questions</div>", unsafe_allow_html=True)
            for i, q in enumerate(qs["questions"]):
                st.markdown(f"""
                <div class="quiz-card">
                    <div class="quiz-q">Q{i+1}. {q['question']}</div>
                </div>
                """, unsafe_allow_html=True)
                opts = q.get("options") or []
                if opts:
                    sel = st.radio(
                        f"a_{i}", opts, key=f"qa_{i}",
                        label_visibility="collapsed",
                        horizontal=False,
                    )
                    ans[i] = (sel[0] if sel else "").strip()
                else:
                    ans[i] = st.text_input(f"a_{i}", placeholder="Your answer…", key=f"qa_{i}", label_visibility="collapsed")
                st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

            if st.button("📝 Submit Quiz", use_container_width=True, key="btn_sub_qs"):
                with st.spinner("Evaluating…"):
                    from agents.quiz_set_agent import evaluate_quiz_set
                    res = evaluate_quiz_set(sid, cid, qs["questions"], ans)
                    # Safe Pydantic conversion for UI
                    if hasattr(res, 'model_dump'):
                        res = res.model_dump()
                    elif hasattr(res, 'dict'):
                        res = res.dict()
                    elif not isinstance(res, dict):
                        res = {'score': 0, 'correct': 0, 'total': len(qs["questions"]), 'results': [], 'feedback': 'Evaluation failed'}
                    st.session_state["qs_results"]   = res
                    st.session_state["qs_submitted"] = True
                    st.rerun()

        elif st.session_state.get("qs_submitted") and "qs_results" in st.session_state:
            r = st.session_state["qs_results"]
            color = "#10b981" if r["score"]>=70 else "#f59e0b" if r["score"]>=50 else "#fb7185"
            st.markdown(f"""
            <div class='neon-card' style='text-align:center; margin:12px 0;'>
                <div style='font-family:"Clash Display","Syne",sans-serif;
                     font-size:52px; font-weight:800; color:{color};
                     text-shadow:0 0 30px {color}50;'>{r["score"]}%</div>
                <div style='color:#7878aa; font-size:14px; margin-top:4px;'>{r["correct"]}/{r["total"]} correct</div>
                <div style='margin-top:12px; color:#a0a0cc; font-size:13px; line-height:1.6;'>{r["feedback"]}</div>
            </div>
            """, unsafe_allow_html=True)
            for res in r["results"]:
                icon = "✅" if res["is_correct"] else "❌"
                bg   = "rgba(16,185,129,0.08)" if res["is_correct"] else "rgba(251,113,133,0.08)"
                border = "rgba(16,185,129,0.25)" if res["is_correct"] else "rgba(251,113,133,0.25)"
                st.markdown(f"""
                <div style='border:1px solid {border}; background:{bg}; border-radius:12px; padding:12px 14px; margin:8px 0;'>
                    <div style='font-weight:700; color:#e5e7ff; margin-bottom:6px;'>{icon} {res['question']}</div>
                    <div style='font-size:13px; color:#a0a0cc;'>Your answer: <strong style="color:#fff;">{res['your_answer'] or '—'}</strong></div>
                    <div style='font-size:13px; color:#a0a0cc;'>Correct answer: <strong style="color:#93c5fd;">{res['correct_answer']}</strong></div>
                </div>
                """, unsafe_allow_html=True)
            if st.button("🔄 New Quiz", use_container_width=True, key="btn_new_qs"):
                for k in ["active_qs","qs_results"]: st.session_state.pop(k, None)
                st.session_state["qs_submitted"] = False
                st.rerun()

    with tab_plan:
        st.markdown("<p style='font-size:13px;color:#7878aa;margin-bottom:8px;'>Get a personalised 7-day study plan based on your quiz performance.</p>", unsafe_allow_html=True)
        goal = st.text_input("Your goal", placeholder="e.g. Master Python OOP, Ace the final exam",
            key="plan_g", label_visibility="collapsed")
        if st.button("🗺️ Generate Study Plan", use_container_width=True, key="btn_plan"):
            with st.spinner("Analysing your performance and crafting your plan…"):
                try:
                    from agents.study_plan_agent import generate_study_plan
                    plan = generate_study_plan(sid, cid, goal or "Master the course fundamentals")
                    # Safe Pydantic conversion for UI
                    if hasattr(plan, 'model_dump'):
                        plan = plan.model_dump()
                    elif hasattr(plan, 'dict'):
                        plan = plan.dict()
                    elif not isinstance(plan, dict):
                        plan = {'days': [], 'tips': [], 'summary': 'Plan generation failed'}
                    st.session_state["study_plan"] = plan
                except Exception as e:
                    st.markdown(f'<div class="neon-toast error">❌ {str(e)}</div>', unsafe_allow_html=True)

        if "study_plan" in st.session_state:
            plan = st.session_state["study_plan"]
            st.markdown(f"""
            <div class='neon-card' style='margin:12px 0 16px;'>
                <div style='font-size:10px; color:#4f8ef7; text-transform:uppercase;
                     letter-spacing:1px; margin-bottom:8px; font-weight:700;'>Your Personalised Plan</div>
                <div style='color:#a0a0cc; font-size:14px; line-height:1.7;'>{plan.get("summary","")}</div>
                <div style='font-size:11px; color:#333355; margin-top:8px;'>🎯 Goal: {plan.get("goal","")}</div>
            </div>
            """, unsafe_allow_html=True)
            for day in plan.get("days", []):
                with st.expander(f"📅 Day {day['day']} — {day['date']} · **{day['focus']}**", expanded=(day['day']==1)):
                    c1, c2 = st.columns([3,1])
                    with c1:
                        st.markdown(f"⏱️ **{day.get('duration','1-2 hours')}**")
                        for t in day.get("tasks",[]): st.markdown(f"- {t}")
                        st.markdown(f"📚 *{day.get('resources','')}*")
                    with c2:
                        st.markdown(f"""
                        <div class='glass-card' style='text-align:center;padding:12px;'>
                            <div style='font-size:10px;color:#333355;text-transform:uppercase;'>Quiz Topic</div>
                            <div style='font-weight:700;color:#fcd34d;margin-top:4px;font-size:13px;'>{day.get("quiz_topic","Practice")}</div>
                        </div>
                        """, unsafe_allow_html=True)
            if plan.get("tips"):
                st.markdown("**💡 Pro Tips:**")
                for t in plan["tips"]: st.markdown(f"- {t}")

    with tab_voice:
        st.markdown("<p style='font-size:13px;color:#7878aa;'>Record your question and it will be transcribed automatically.</p>", unsafe_allow_html=True)
        audio = st.audio_input("Record", label_visibility="collapsed")
        if audio and st.button("📝 Transcribe & Send", use_container_width=True, key="btn_voice"):
            with st.spinner("Transcribing…"):
                try:
                    import faster_whisper
                    model = faster_whisper.WhisperModel("base", device="cpu")
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                        f.write(audio.read()); tmp = f.name
                    segments, _ = model.transcribe(tmp, beam_size=5)
                    transcribed = " ".join(seg.text for seg in segments).strip()
                    os.unlink(tmp)
                    user_input = transcribed
                    st.markdown(f'<div class="neon-toast success">✅ Transcribed: <strong>{user_input}</strong></div>', unsafe_allow_html=True)
                except ImportError:
                    st.markdown('<div class="neon-toast warning">🎤 Voice disabled — <code>pip install faster-whisper</code></div>', unsafe_allow_html=True)
                except Exception as e:
                    st.markdown(f'<div class="neon-toast error">❌ Voice error: {str(e)}</div>', unsafe_allow_html=True)

    # ── Process ───────────────────────────────────────────────────────
    if user_input:
        # Save user message
        st.session_state.messages.append({
            "role": "user",
            "content": user_input
        })

        result = None
        error_note = None

        # Call AI
        token_gen, result_container = chat_stream(sid, cid, user_input)

        with st.spinner("AI is typing…"):
            try:
                st.write_stream(token_gen)
            except Exception as exc:
                error_note = str(exc)

        # ── FIX: read result from the background thread container ──
        result = result_container.get("result")

        # Safely convert Pydantic model to dict (handles v1/v2 + fallback)
        if result:
            if hasattr(result, "model_dump"):
                result = result.model_dump()
            elif hasattr(result, "dict"):
                result = result.dict()
            elif not isinstance(result, dict):
                result = {"response": str(result)[:1000]}

        # Safe response extraction (always str)
        response_text = result.get("response", "") if isinstance(result, dict) else ""
        response_text = str(response_text)[:5000]

        # Handle fallback
        if error_note or result is None or not response_text.strip():
            response_text = "⚠️ The assistant couldn't reply right now. Please try again."
            result = {"response": response_text, "agent_used": "error"}

        # Show error if any
        if result_container.get("error"):
            st.markdown(f'<div class="neon-toast error">AI reply failed: {result_container.get("error")}</div>', unsafe_allow_html=True)
        elif error_note:
            st.markdown(f'<div class="neon-toast error">AI reply failed: {error_note}</div>', unsafe_allow_html=True)

        # Save assistant response (safe str)
        st.session_state.messages.append({
            "role": "assistant",
            "content": response_text,
            "agent": result.get("agent_used", "unknown")
        })

        # Update state
        st.session_state.quiz_active = (result.get("agent_used") == "quiz_generate")
        st.session_state.total_turns += 1

        st.rerun()