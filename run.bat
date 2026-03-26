@echo off
cd /d "E:\6th Sem\ai-teaching-assistant"
call .venv\Scripts\activate
python -m streamlit run app/main.py
pause