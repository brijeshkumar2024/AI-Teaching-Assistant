PREMIUM_CSS = """
<style>
@import url("https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap");

:root {{
  --void: #050510;
  --navy: #0a0a1a;
  --violet: #7C3AED;
  --cyan: #06B6D4;
  --gold: #F59E0B;
  --glass: rgba(255,255,255,0.05);
  --glass2: rgba(255,255,255,0.08);
  --glass3: rgba(255,255,255,0.12);
  --border-glass: rgba(255,255,255,0.1);
  --text0: #eeeeff;
  --text1: #b8b8cc;
  --text2: #6b6b88;
  --r: 16px;
  --font: 'DM Sans', sans-serif;
  --display: 'Syne', sans-serif;
  --mono: 'JetBrains Mono', monospace;
}}

.stApp {{
  background: linear-gradient(-45deg, #050510 0%, #1a0a2e 25%, #2a1a4a 50%, #0a0a1a 75%, #050510 100%),
              radial-gradient(ellipse 80% 60% at 20% 20%, rgba(124,58,237,0.15) 0%, transparent 50%),
              radial-gradient(ellipse 60% 40% at 80% 80%, rgba(6,182,212,0.12) 0%, transparent 50%);
  background-size: 400% 400%;
  animation: gradientShift 20s ease infinite;
}}

@keyframes gradientShift {{
  0%, 100% {{ background-position: 0% 50%; }}
  50% {{ background-position: 100% 50%; }}
}}

.main .block-container {{ padding: 2rem !important; max-width: 1400px !important; }}

#MainMenu, footer, [data-testid="stToolbar"] {{ display:none !important; }}

.glass-pro {{
  background: var(--glass);
  border: 1px solid var(--border-glass);
  border-radius: var(--r);
  backdrop-filter: blur(20px) saturate(1.3);
  box-shadow: 0 12px 40px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.12);
}}

.glass-pro::before {{
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, rgba(124,58,237,0.05), rgba(6,182,212,0.04));
  opacity: 0;
  transition: opacity 0.3s;
}}

.glass-pro:hover::before {{ opacity: 1; }}

.stButton > button {{
  background: linear-gradient(135deg, var(--glass2), var(--glass)) !important;
  border: 1px solid var(--border-glass) !important;
  color: var(--text0) !important;
  backdrop-filter: blur(20px) !important;
  position: relative;
  overflow: hidden;
}}

.stButton > button:hover {{
  border-color: var(--violet) !important;
  box-shadow: 0 0 25px rgba(124,58,237,0.4);
  transform: translateY(-1px);
}}

.stButton > button:active {{
  transform: translateY(0);
}}

.bubble-user, .bubble-ai {{
  max-width: 60% !important;
  animation: fadeInChat 0.4s cubic-bezier(0.34,1.56,0.64,1);
}}

@keyframes fadeInChat {{
  from {{ opacity: 0; transform: translateY(12px) scale(0.97); }}
  to {{ opacity: 1; transform: translateY(0) scale(1); }}
}}

.neon-toast {{
  display: flex; align-items: center; gap: 8px; padding: 12px 16px; margin: 8px 0;
  border-radius: 12px; font-size: 14px; max-width: 400px; max-height: 80px; overflow: hidden;
}}

.neon-toast.error {{ background: rgba(251,113,133,0.15); border: 1px solid rgba(251,113,133,0.4); color: #fca5a5; }}
.neon-toast.success {{ background: rgba(124,58,237,0.15); border: 1px solid rgba(124,58,237,0.4); color: #e879f9; }}
.neon-toast.warning {{ background: rgba(251,191,36,0.15); border: 1px solid rgba(251,191,36,0.4); color: #facc15; }}

.neon-toast::before {{ content: '❌'; }}
.neon-toast.success::before {{ content: '✅'; }}
.neon-toast.warning::before {{ content: '⚠️'; }}

.stSlider > div > div > div {{
  height: 20px !important;
}}

.stSelectbox > div > div > select {{
  background: var(--glass2) !important;
  border: 1px solid var(--border-glass) !important;
  backdrop-filter: blur(20px) !important;
}}

[data-testid="stTab"] > div > button {{
  border-radius: 12px !important;
  margin: 0 2px !important;
}}

[data-testid="stTab"] > div > button[aria-selected="true"] {{
  background: linear-gradient(135deg, var(--violet), var(--cyan)) !important;
  box-shadow: 0 0 20px rgba(124,58,237,0.5) !important;
}}

.quiz-card {{
  background: var(--glass2);
  border: 1px solid var(--border-glass);
  border-radius: 14px;
  padding: 20px;
  margin: 12px 0;
}}

.code-section {{
  margin: 12px 0;
  padding: 16px;
  border-radius: 12px;
  backdrop-filter: blur(15px);
  border-left: 4px solid var(--gold);
}}

.st-expander {{
  background: var(--glass2) !important;
  border: 1px solid var(--border-glass) !important;
  border-radius: 14px !important;
}}

</style>
"""

# Apply the premium theme





