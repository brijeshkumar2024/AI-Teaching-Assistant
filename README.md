# 🎓 AI Teaching Assistant

> An ultra-premium, production-grade AI Teaching Assistant for programming courses.
> Personalised 24/7 tutoring · Secure code review · Adaptive quizzes · Instructor analytics

---

## ✨ Features

| Feature | Description |
|---|---|
| 💬 **RAG Q&A** | Answers student questions using your actual course PDFs via FAISS vector search |
| 🐍 **Code Review** | Executes student code in an isolated Docker sandbox, then gives constructive LLM feedback |
| 🎯 **Adaptive Quizzes** | Generates MCQ / True-False / short-answer questions that auto-adjust difficulty per student |
| 🔍 **Plagiarism Detection** | Two-layer check: structural fingerprint similarity + LLM-based AI-generation detection |
| 🧠 **Multi-turn Memory** | Every student gets their own conversation memory per course |
| 🎤 **Voice Input** | Students can ask questions by voice via OpenAI Whisper transcription |
| 📊 **Instructor Dashboard** | Real-time topic heatmaps, at-risk alerts, misconception extraction, per-student drilldown |
| 📄 **PDF Reports** | One-click exportable weekly instructor reports with full analytics |
| 🔀 **LLM Hot-swap** | Switch between Gemini and GPT-4o by changing one env variable — zero code changes |
| 🐳 **Docker Sandbox** | Isolated, network-free, memory-capped code execution — safe for untrusted student code |

---

## 🏗️ Architecture

```
Student / Instructor (Streamlit UI)
            │
    LangGraph Orchestrator
    ┌───────┴────────────────────────────┐
    │                                    │
  Classify intent                  Session state
    │
    ├── conceptual_qa  →  RAG Q&A Agent     (FAISS + Gemini/GPT-4o)
    ├── code_submission →  Code Review Agent (Docker Sandbox + LLM)
    ├── quiz_request   →  Quiz Agent         (Adaptive difficulty)
    ├── quiz_answer    →  Quiz Evaluator     (Score + feedback)
    └── smalltalk      →  Smalltalk Handler  (Warm redirect)
            │
    Shared Services
    ├── Memory      (per-student, per-course ConversationBufferWindowMemory)
    ├── Analytics   (topic heatmap, at-risk detection, misconceptions)
    ├── Plagiarism  (fingerprint + AI-detect)
    └── PostgreSQL  (interactions, submissions, quiz attempts, at-risk flags)
```

---

## 🚀 Quick Start (Local)

### 1. Clone & install

```bash
git clone https://github.com/your-username/ai-teaching-assistant
cd ai-teaching-assistant
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env .env.local
# Edit .env and add your Gemini API key:
# GEMINI_API_KEY=your_key_here
# LLM_PROVIDER=gemini
```

### 3. Build the sandbox image

```bash
docker build -f sandbox/Dockerfile -t ai-ta-sandbox .
```

### 4. Run the app

```bash
streamlit run app/main.py
```

Open [http://localhost:8501](http://localhost:8501)

---

## 🐳 Docker Compose (Production)

```bash
# Set your secrets
echo "POSTGRES_PASSWORD=yourpassword" >> .env
echo "GEMINI_API_KEY=yourkey"         >> .env

# Build & launch
docker compose up --build -d

# View logs
docker compose logs -f app
```

---

## 🔑 Environment Variables

| Variable | Description | Default |
|---|---|---|
| `LLM_PROVIDER` | `gemini` or `openai` | `gemini` |
| `GEMINI_API_KEY` | Google AI Studio key | — |
| `OPENAI_API_KEY` | OpenAI key (when ready) | — |
| `GEMINI_MODEL` | Gemini model name | `gemini-1.5-flash` |
| `OPENAI_MODEL` | OpenAI model name | `gpt-4o` |
| `DATABASE_URL` | PostgreSQL connection string | SQLite fallback |
| `CHUNK_SIZE` | RAG chunk size (tokens) | `2048` |
| `CHUNK_OVERLAP` | RAG chunk overlap | `256` |
| `MAX_MEMORY_TURNS` | Conversation turns to keep | `20` |
| `SANDBOX_TIMEOUT` | Code execution limit (sec) | `10` |
| `INSTRUCTOR_PASSWORD` | Dashboard login password | `admin123` |

---

## 📁 Project Structure

```
ai-teaching-assistant/
├── app/
│   ├── main.py                  # Streamlit entry point + login
│   ├── student_ui.py            # Student chat interface
│   └── instructor_dashboard.py  # Ultra analytics dashboard
├── agents/
│   ├── orchestrator.py          # LangGraph routing brain
│   ├── rag_agent.py             # RAG Q&A pipeline
│   ├── code_review_agent.py     # Docker sandbox + LLM feedback
│   ├── quiz_agent.py            # Adaptive quiz generator
│   └── analytics_agent.py      # At-risk detection + heatmaps
├── core/
│   ├── llm_config.py            # Gemini / GPT-4o hot-swap
│   ├── embeddings.py            # Multi-course FAISS manager
│   ├── memory.py                # Per-student memory
│   └── plagiarism.py            # AI-detect + similarity check
├── sandbox/
│   ├── Dockerfile               # Isolated Python executor image
│   └── executor.py              # Safe exec inside container
├── database/
│   └── models.py                # SQLAlchemy ORM schema
├── reports/
│   └── pdf_generator.py         # ReportLab PDF exporter
├── data/
│   ├── courses/                 # Uploaded PDFs per course
│   └── vector_stores/           # FAISS indexes per course
├── .env                         # API keys & config
├── requirements.txt
├── Dockerfile.app               # Main app container
├── docker-compose.yml
└── README.md
```

---

## 🎓 Ingesting Course Materials

```python
from core.embeddings import ingest_course_materials

# Ingest PDFs for a course
ingest_course_materials(
    course_id = "python101",
    pdf_paths = ["lectures/week1.pdf", "lectures/week2.pdf"],
    extra_text= "Optional pasted syllabus text here"
)
```

Or use the **Upload Course Materials** panel in the Streamlit sidebar.

---

## 🔄 Switching LLM Provider

No code changes needed. Just update `.env`:

```bash
# Use Gemini (free, default)
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_key

# Switch to OpenAI GPT-4o
LLM_PROVIDER=openai
OPENAI_API_KEY=your_openai_key
```

Restart the app — all agents pick up the new provider automatically.

---

## 🛡️ Security

- Student code runs in a **Docker container** with:
  - No network access (`--network none`)
  - Read-only filesystem
  - 128MB RAM cap
  - 50% CPU cap
  - 10 second hard timeout
  - Blocked dangerous builtins (`open`, `__import__`, `eval`, etc.)
  - Module import whitelist

---

## 📄 License

MIT License — free to use, modify, and deploy.

---

## 🤝 Acknowledgements

Built with: LangChain · LangGraph · FAISS · Streamlit · ReportLab · Docker · Gemini · OpenAI Whisper