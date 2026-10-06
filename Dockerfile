# FinLens - imagen para ejecutar la app. Sin claves arranca en modo demo.
# Uso:  docker build -t finlens . && docker run -p 8501:8501 --env-file .env finlens
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLBACKEND=Agg

WORKDIR /app

# Dependencias primero: la capa se reutiliza mientras no cambie requirements.txt
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py ./
COPY .streamlit ./.streamlit
COPY src ./src
COPY scripts ./scripts
COPY samples ./samples

# Sin privilegios de root
RUN useradd --create-home app && chown -R app:app /app
USER app

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
