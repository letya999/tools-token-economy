@echo off
cd /d %~dp0..
.venv\Scripts\streamlit.exe run streamlit_app.py --server.port 8501 --server.address 127.0.0.1 --server.headless true
