"""
app/instructor_dashboard.py — Ultra Premium Instructor Dashboard
"""

import time
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime

from agents.analytics_agent import get_dashboard_data, generate_weekly_summary
from reports.pdf_generator  import generate_pdf_report

PLOT_CFG = dict(
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Cabinet Grotesk, DM Sans, sans-serif", color="#7878aa", size=12),
    margin=dict(l=10, r=10, t=36, b=10),
    xaxis=dict(gridcolor="rgba(255,255,255,0.04)", linecolor="rgba(255,255,255,0.06)"),
    yaxis=dict(gridcolor="rgba(255,255,255,0.04)", linecolor="rgba(255,255,255,0.06)"),
)


def render_instructor_dashboard():
    cid  = st.session_state.course_id
    data = get_dashboard_data(cid)

    # ── Header ────────────────────────────────────────────────────────
    c1, c2, c3 = st.columns([4,1,1])
    with c1:
        st.markdown(f"""
        <div class='hero-wrap'>
            <div class='hero-title'>Mission Control 📊</div>
            <div class='hero-sub'>{cid.upper()} · Real-time student analytics & insights</div>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown("<br>", unsafe_allow_html=True)
        auto = st.toggle("Auto-refresh", value=False, key="auto_ref")
    with c3:
        st.markdown(f"<br><div style='font-size:11px;color:#333355;text-align:right;'>"
                    f"Updated<br><span style='color:#7878aa;'>{datetime.now().strftime('%H:%M:%S')}</span></div>",
                    unsafe_allow_html=True)

    # ── KPIs ──────────────────────────────────────────────────────────
    at_risk = len(data["at_risk_students"])
    high    = sum(1 for s in data["at_risk_students"] if s["severity"]=="high")
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("👥 Students",    data["total_students"])
    c2.metric("💬 Interactions",data["total_interactions"])
    c3.metric("⚠️ At-Risk",     at_risk,
              delta=f"{high} critical" if high else None, delta_color="inverse")
    c4.metric("📚 Topics",      len(data["topic_heatmap"]))

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # ── Tabs ──────────────────────────────────────────────────────────
    t1,t2,t3,t4,t5,t6 = st.tabs([
        "🔥 Heatmap","⚠️ At-Risk","🏆 Leaderboard",
        "🤔 Misconceptions","👤 Drilldown","📋 Report"
    ])

    with t1:
        hmap = data["topic_heatmap"]
        if hmap:
            df = pd.DataFrame(list(hmap.items()), columns=["Topic","Count"]).sort_values("Count")
            df["Topic"] = df["Topic"].str.replace("_"," ").str.title()
            fig = px.bar(df, x="Count", y="Topic", orientation="h",
                color="Count",
                color_continuous_scale=[[0,"#0c0c22"],[0.4,"#1a1a5e"],[1,"#4f8ef7"]])
            fig.update_layout(**PLOT_CFG, height=max(260, len(df)*46),
                showlegend=False, coloraxis_showscale=False,
                title=dict(text="Question Frequency by Topic", font=dict(color="#eeeeff",size=14,family="Clash Display, Syne, sans-serif")))
            fig.update_traces(marker_line_width=0)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.markdown("<div style='text-align:center;padding:40px;color:#333355;'>No data yet — students need to ask questions first.</div>", unsafe_allow_html=True)

    with t2:
        students = data["at_risk_students"]
        if not students:
            st.markdown("""
            <div style='background:rgba(16,185,129,0.07);border:1px solid rgba(16,185,129,0.2);
                 border-radius:12px;padding:24px;text-align:center;'>
                <div style='font-size:28px;margin-bottom:8px;'>✅</div>
                <div style='color:#6ee7b7;font-weight:600;'>All students are on track!</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            sev_map = {"high":"#fb7185","medium":"#f59e0b","low":"#4f8ef7"}
            for s in students:
                sev = s["severity"]
                c = sev_map.get(sev,"#4f8ef7")
                with st.expander(
                    f"{'🔴' if sev=='high' else '🟡' if sev=='medium' else '🔵'} "
                    f"**{s['student_id'].replace('_',' ').title()}** — {sev.upper()}",
                    expanded=(sev=="high")
                ):
                    col1, col2 = st.columns([3,1])
                    with col1:
                        for flag in s["flags"]:
                            st.markdown(
                                f"<div class='risk-{sev}'>"
                                f"<div style='font-size:13px;color:#eeeeff;'>• {flag['reason']}</div>"
                                f"</div>", unsafe_allow_html=True)
                        if s.get("last_activity"):
                            st.markdown(
                                f"<div style='margin-top:8px; font-size:11px; color:#7878aa;'>"
                                f"Last activity: {s['last_activity']}"
                                f"</div>",
                                unsafe_allow_html=True,
                            )
                        st.markdown(f"**💡 Recommendation:** {s['recommendation']}")
                    with col2:
                        m = data["student_metrics"].get(s["student_id"],{})
                        st.metric("Questions",    m.get("total_questions",0))
                        st.metric("Quiz acc.",    f"{m.get('quiz_accuracy',0):.0%}")
                        st.metric("Failed sub.",  m.get("failed_submissions",0))

    with t3:
        metrics = data.get("student_metrics",{})
        if metrics:
            rows = sorted([{
                "name" : sid.replace("_"," ").title(),
                "score": round(m.get("quiz_accuracy",0)*50 + min(m.get("total_questions",0),20)*1.5 + m.get("code_submissions",0)*3, 1),
                "acc"  : m.get("quiz_accuracy",0),
                "q"    : m.get("total_questions",0),
            } for sid,m in metrics.items()], key=lambda x:-x["score"])

            for i, r in enumerate(rows[:10], 1):
                rc  = f"lb-r{i}" if i<=3 else "lb-rn"
                bar = int((r["score"] / max(rows[0]["score"],1)) * 100)
                st.markdown(f"""
                <div class='lb-row'>
                    <div class='lb-rank {rc}'>{i}</div>
                    <div style='flex:1;'>
                        <div style='font-weight:700;font-size:14px;'>{r['name']}</div>
                        <div style='font-size:11px;color:#333355;margin-top:2px;'>
                            Quiz: {r['acc']:.0%} · Questions: {r['q']}
                        </div>
                        <div class='lb-bar' style='margin-top:6px;'>
                            <div class='lb-fill' style='width:{bar}%;'></div>
                        </div>
                    </div>
                    <div class='lb-score'>{r['score']}</div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No student data yet.")

    with t4:
        items = data.get("misconceptions",[])
        if items:
            df = pd.DataFrame(items)
            if not df.empty:
                st.dataframe(
                    df[["topic","misconception","frequency","fix"]].rename(columns={
                        "topic":"Topic","misconception":"Misconception",
                        "frequency":"Freq","fix":"Suggested Fix"
                    }),
                    use_container_width=True, hide_index=True
                )
        else:
            st.markdown("<div style='color:#333355;text-align:center;padding:30px;font-size:14px;'>Need more student interactions to detect patterns.</div>", unsafe_allow_html=True)

    with t5:
        metrics = data["student_metrics"]
        if metrics:
            names  = [s.replace("_"," ").title() for s in metrics]
            sel    = st.selectbox("Select student", names, label_visibility="collapsed", key="drill_sel")
            sid    = sel.lower().replace(" ","_")
            m      = metrics.get(sid, {})

            c1,c2,c3,c4 = st.columns(4)
            c1.metric("Questions",    m.get("total_questions",0))
            c2.metric("Submissions",  m.get("code_submissions",0))
            c3.metric("Quiz att.",    m.get("quiz_attempts",0))
            c4.metric("Accuracy",     f"{m.get('quiz_accuracy',0):.0%}")

            acc = m.get("quiz_accuracy", 0)
            fig = go.Figure(go.Indicator(
                mode="gauge+number+delta",
                value=acc*100,
                delta={"reference":60,"valueformat":".0f"},
                title={"text":"Quiz Accuracy %","font":{"color":"#7878aa","size":13,"family":"Cabinet Grotesk, sans-serif"}},
                number={"suffix":"%","font":{"color":"#4f8ef7","size":40,"family":"Clash Display, sans-serif"}},
                gauge={
                    "axis":{"range":[0,100],"tickcolor":"#333355","tickfont":{"color":"#333355"}},
                    "bar":{"color":"#4f8ef7" if acc>=0.6 else "#fb7185","thickness":0.3},
                    "bgcolor":"rgba(0,0,0,0)","borderwidth":0,
                    "steps":[
                        {"range":[0,40],"color":"rgba(251,113,133,0.06)"},
                        {"range":[40,70],"color":"rgba(245,158,11,0.06)"},
                        {"range":[70,100],"color":"rgba(16,185,129,0.06)"},
                    ],
                    "threshold":{"line":{"color":"rgba(255,255,255,0.15)","width":2},"value":60},
                }
            ))
            fig.update_layout(**PLOT_CFG, height=240)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No students yet.")

    with t6:
        c1, c2 = st.columns([3,1])
        with c2:
            if st.button("🔄 Generate", use_container_width=True, key="gen_rpt"):
                with st.spinner("Generating AI weekly summary…"):
                    st.session_state.weekly_summary = generate_weekly_summary(cid)

        if "weekly_summary" in st.session_state:
            st.markdown(f"""
            <div class='neon-card' style='margin-bottom:16px;'>
                <div style='font-size:10px;color:#4f8ef7;text-transform:uppercase;
                     letter-spacing:1.5px;font-weight:700;margin-bottom:12px;'>
                    AI Weekly Summary · {datetime.now().strftime('%B %d, %Y')}
                </div>
                <div style='color:#a0a0cc;font-size:14px;line-height:1.8;'>
                    {st.session_state.weekly_summary.replace(chr(10),'<br>')}
                </div>
            </div>
            """, unsafe_allow_html=True)

            if st.button("📄 Export PDF Report", use_container_width=True, key="export_pdf"):
                with st.spinner("Generating PDF…"):
                    pdf = generate_pdf_report(cid, data, st.session_state.weekly_summary)
                    st.download_button(
                        "⬇️ Download PDF Report", data=pdf,
                        file_name=f"report_{cid}_{datetime.now().strftime('%Y%m%d')}.pdf",
                        mime="application/pdf", use_container_width=True
                    )
        else:
            st.markdown("<div style='color:#333355;text-align:center;padding:30px;font-size:14px;'>Click Generate to create your AI-powered weekly summary.</div>", unsafe_allow_html=True)

    if auto:
        time.sleep(30)
        st.rerun()