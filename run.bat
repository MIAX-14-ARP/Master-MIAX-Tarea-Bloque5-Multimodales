@echo off
REM Arranque de FinLens en Windows: crea el entorno, instala dependencias y lanza la app.
REM Sin claves en .env arranca en modo demo.
cd /d "%~dp0"
if not exist .venv (
    python -m venv .venv || exit /b 1
)
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt || exit /b 1
streamlit run app.py
