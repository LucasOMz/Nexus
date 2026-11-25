# =====================================================================
# Nexus — imagem da API
# =====================================================================
FROM python:3.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MEDIA_DIR=/app/media \
    BACKUP_DIR=/app/backups \
    NEXUS_SEGREDOS_DIR=/app/segredos

WORKDIR /app

# Cliente do PostgreSQL — o `pg_dump` do backup.
#
# ## Por que isto faltava, e o que custava
#
# `backup_service` executa `pg_dump -Fc` para gravar o dump. A imagem não
# tinha esse binário: o processo levantava `FileNotFoundError`.
#
# O efeito não era só "backup não funciona":
#
#   * a **importação de CSV** exige backup antes, e cancelava inteira
#   * a **exclusão em lote** exige backup antes, e cancelava
#   * a tela de Backups nunca produziu arquivo nenhum
#
# E o sintoma enganava: a importação "carregava alguns segundos e não
# importava", sem apontar para a falta de um binário do sistema.
#
# ## A versão precisa casar com o servidor
#
# `pg_dump` **recusa** servidor mais novo que ele. O Debian desta imagem
# (bookworm) traz a 15; por isso o `docker-compose.yml` usa `postgres:15`.
# Se um dia subir o servidor para 16, o cliente também precisa subir — e aí
# é repositório PGDG, não o pacote do Debian.
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Camada de dependências (cacheável).
COPY requirements.txt requirements-snmp.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# SNMP — dependência do monitor de impressoras.
#
# Vive em `requirements-snmp.txt`, separado do principal para que uma falha
# ao instalá-lo não derrube a instalação de quem nunca vai usar SNMP. O
# `run.ps1` já o instalava no host, e por isso o monitor funcionava fora do
# Docker — **o Dockerfile é que nunca foi atualizado para fazer o mesmo.**
#
# É a única adição a este arquivo além do original. Não muda a imagem base,
# não busca repositório de sistema operacional, e não tem risco.
ARG SNMP=1
RUN if [ "$SNMP" = "1" ]; then \
        pip install --no-cache-dir -r requirements-snmp.txt; \
    fi

# Código da aplicação.
COPY app ./app
COPY frontend ./frontend
COPY alembic ./alembic
COPY alembic.ini .

RUN groupadd --gid 10001 nexus \
    && useradd --uid 10001 --gid 10001 --home-dir /tmp --no-create-home --shell /usr/sbin/nologin nexus \
    && install -d -o nexus -g nexus -m 0750 /app/media /app/backups \
    && install -d -o nexus -g nexus -m 0700 /app/segredos

FROM base AS testes
COPY requirements-dev.txt schema.sql pytest.ini ./
RUN pip install --no-cache-dir -r requirements-dev.txt
USER 10001:10001
CMD ["python", "-m", "pytest", "-q", "-o", "cache_dir=/tmp/nexus-pytest-cache"]

FROM base AS runtime
COPY scripts/iniciar_container.py /usr/local/bin/nexus-init.py
USER 10001:10001

EXPOSE 4545

ENTRYPOINT ["python", "/usr/local/bin/nexus-init.py"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "4545"]
