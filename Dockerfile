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
# ## Por que só o repositório Debian
#
# A primeira versão buscava o cliente 16 em `apt.postgresql.org` — um
# **repositório de terceiro**, com `curl` e chave GPG próprios.
#
# Em rede corporativa isso derruba o build inteiro: proxy que não responde,
# inspeção TLS que quebra a chave, ou firewall que bloqueia o host. E como
# esta camada vem ANTES do `pip install`, a falha aqui **impede a imagem de
# existir** — inclusive as correções que não têm nada a ver com backup.
#
# Agora usa o repositório da própria Debian, que a rede já precisa permitir
# para o `apt` funcionar.
#
# ## ⚠️ O que se perde, e é importante
#
# A Debian (bookworm) entrega o **cliente 15**, e o seu banco é **16**.
#
# **`pg_dump` recusa dumpar um servidor mais novo que ele:**
#
#     pg_dump: error: server version: 16.x; pg_dump version: 15.x
#     pg_dump: error: aborting because of server version mismatch
#
# Ou seja: **o deploy sobe, e o backup continua não funcionando** — agora por
# incompatibilidade de versão, e não por ausência do binário.
#
# O script `scripts/verificar_backup.py` detecta isso: ele cria E restaura um
# backup, então acusa a incompatibilidade antes de alguém confiar nela.
#
# Quando a rede permitir, a solução definitiva não é voltar ao repositório
# externo: é **copiar o binário da imagem oficial** `postgres:16`, que o
# Portainer já baixa por causa do serviço `db`. Ver `Dockerfile.pg16` no
# repositório.
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
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
