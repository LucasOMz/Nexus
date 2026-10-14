# =====================================================================
# Nexus — imagem da API
# =====================================================================
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# --- Cliente do PostgreSQL (pg_dump) ---------------------------------
#
# ## Por que é obrigatório, e não opcional
#
# O serviço de backup chama `pg_dump` direto. A imagem `python:3.12-slim`
# **não traz** o cliente — então o backup falhava dentro do container,
# enquanto o compose anuncia `BACKUP_DIR` e `BACKUP_RETER` como se
# funcionasse.
#
# **Backup que falha em silêncio é pior que backup que não existe:** dá a
# impressão de estar protegido.
#
# ## Por que a versão 16 vem do repositório oficial
#
# O Debian desta imagem traz o cliente 15. **`pg_dump` recusa dumpar um
# servidor mais novo que ele** — então um cliente 15 contra o PostgreSQL 16
# do compose falharia na hora de usar. As versões precisam acompanhar.
#
# `--no-install-recommends` evita arrastar o servidor inteiro junto.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg lsb-release \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-16 \
    && apt-get purge -y --auto-remove curl gnupg lsb-release \
    && rm -rf /var/lib/apt/lists/*

# Camada de dependências (cacheável).
#
# Os dois arquivos vão juntos de propósito: `COPY` separado invalidaria o
# cache da instalação a cada mudança no outro arquivo, e a camada mais cara
# do build seria refeita à toa.
COPY requirements.txt requirements-snmp.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# --- SNMP: dependência do monitor de impressoras ---------------------
#
# ## Por que estava faltando
#
# `pysnmp` vive em `requirements-snmp.txt`, separado do principal para que
# uma falha ao instalá-lo não derrube a instalação de quem nunca vai usar
# SNMP. O `run.ps1` / `run.sh` tentam instalá-lo no host — e por isso o
# monitor funcionava fora do Docker.
#
# **O Dockerfile nunca foi atualizado para fazer o mesmo.** Resultado: em
# container, o monitor de impressoras respondia "leitura por SNMP não
# disponível" e só aceitava contador à mão — enquanto na máquina local
# funcionava. Duas instalações do mesmo sistema com comportamentos
# diferentes, e a diferença invisível no código.
#
# ## Por que NÃO usa `|| echo` para não falhar
#
# Seria fiel à intenção do arquivo separado, mas reproduziria exatamente o
# problema: **um aviso no meio de centenas de linhas de build passa
# despercebido**, e a funcionalidade some sem ninguém notar.
#
# O padrão é instalar, e falhar alto se não conseguir. Quem precisa de uma
# imagem menor — ou não usa impressora — constrói com `--build-arg SNMP=0`.
ARG SNMP=1
RUN if [ "$SNMP" = "1" ]; then \
        pip install --no-cache-dir -r requirements-snmp.txt; \
    else \
        echo "SNMP desativado no build (SNMP=0): o monitor usara contador manual."; \
    fi

# Código da aplicação.
COPY app ./app
COPY frontend ./frontend
COPY alembic ./alembic
COPY alembic.ini .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
