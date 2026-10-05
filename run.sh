#!/usr/bin/env bash
# Arranque de FinLens en Linux/macOS: crea el entorno, instala dependencias y lanza la app.
# Sin claves en .env arranca en modo demo.
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt
streamlit run app.py
