# =====================================================================
# Nexus — imagem da API
# =====================================================================
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

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

# A porta interna e a da porta publicada PRECISAM ser a mesma do
# `docker-compose.yml`. Quando divergiram (compose 5000, aqui 8000), o Docker
# publicava uma porta em que nada escutava — a conexão era aceita e fechada na
# hora, com `recv failure: conexão fechada pela outra ponta`.
EXPOSE 4545

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "4545"]
