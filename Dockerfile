# =====================================================================
# API — Gestão Patrimonial Unificada
# =====================================================================
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Camada de dependências (cacheável).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código da aplicação.
COPY app ./app
COPY frontend ./frontend
COPY alembic ./alembic
COPY alembic.ini .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
