# =====================================================================
# Nexus — imagem da API
#
# ## Sem `apt`, por necessidade
#
# Esta imagem **não chama `apt-get`**. Não é preferência de estilo: numa rede
# corporativa o `apt` costuma não funcionar — o registry do Docker e o PyPI
# são liberados (ou espelhados), e os repositórios da Debian não.
#
# Foi exatamente o que aconteceu na implantação: o build morria em
# `apt-get install postgresql-client` com `runc did not terminate
# successfully` — e o `runc` não diz por quê. Só a linha acima dele diz, e
# ela não estava no log que chegou.
#
# Como esta camada vem ANTES do `pip install`, uma falha aqui **impede a
# imagem inteira de existir** — inclusive as correções que nada têm a ver com
# o PostgreSQL.
#
# ## O que a imagem precisa, e de onde vem
#
# | precisa | vem de |
# |---|---|
# | Python 3.12 + pip | imagem `python:3.12-slim` (registry) |
# | dependências Python | PyPI (funciona — é o que o build já usava) |
# | `pg_dump` 16 | **copiado** de `postgres:16` (registry) |
#
# Nenhuma requisição fora do registry e do PyPI.
# =====================================================================

# --- Estágio 1: a imagem oficial do PostgreSQL, só como FONTE ----------
#
# Este estágio não é construído: o Docker só precisa da imagem para copiar
# arquivos dela. É mais rápido que instalar o cliente por pacote, e não
# depende de repositório de sistema operacional.
#
# Precisa ser a versão **Debian**, e não `-alpine`: o binário copiado roda no
# estágio 2, que é Debian, e um binário musl (Alpine) não carrega em glibc.
FROM postgres:16 AS origem

# --- Estágio 2: a aplicação -------------------------------------------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# O `pg_dump` procura as bibliotecas nos caminhos registrados no `ldconfig`.
ENV LD_LIBRARY_PATH=/opt/pg-libs

WORKDIR /app

# --- Cliente PostgreSQL 16, copiado da imagem oficial -----------------
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
# ## Por que a versão precisa acompanhar o servidor
#
# `pg_dump` **recusa** dumpar um servidor mais novo que ele:
#
#     pg_dump: error: server version: 16.x; pg_dump version: 15.x
#     pg_dump: error: aborting because of server version mismatch
#
# A Debian da base traz o cliente 15, e o compose usa PostgreSQL 16. Copiar
# da imagem oficial resolve as duas coisas de uma vez: versão certa e zero
# dependência de rede de sistema operacional.
#
# ## Por que copiar a pasta de bibliotecas inteira
#
# `pg_dump` não é autossuficiente: carrega `libpq.so.5`, `libssl`,
# `libcrypto` e mais. Copiar só o executável dá
# `error while loading shared libraries`.
#
# As bibliotecas vão para uma pasta **própria** (`/opt/pg-libs`), e não por
# cima das do sistema — sobrescrever `libssl` da base com a versão da imagem
# do Postgres quebraria o Python.
COPY --from=origem /usr/lib/postgresql/16/bin/ /opt/pg16/bin/
COPY --from=origem /usr/lib/postgresql/16/lib/ /opt/pg16/lib/
COPY --from=origem /usr/lib/x86_64-linux-gnu/ /opt/pg-libs/

# Registra as pastas e confere na hora do build.
#
# O `pg_dump --version` no fim é deliberado: se a cópia falhar, **o build
# para aqui** — em vez de gerar uma imagem que só descobre o problema na hora
# de restaurar um backup.
RUN echo "/opt/pg-libs" > /etc/ld.so.conf.d/pg16.conf \
    && echo "/opt/pg16/lib" >> /etc/ld.so.conf.d/pg16.conf \
    && ldconfig \
    && ln -sf /opt/pg16/bin/pg_dump /usr/local/bin/pg_dump \
    && ln -sf /opt/pg16/bin/pg_restore /usr/local/bin/pg_restore \
    && ln -sf /opt/pg16/bin/psql /usr/local/bin/psql \
    && ln -sf /opt/pg16/bin/createdb /usr/local/bin/createdb \
    && ln -sf /opt/pg16/bin/dropdb /usr/local/bin/dropdb \
    && pg_dump --version

# --- Camada de dependências Python (cacheável) ------------------------
#
# Os dois arquivos vão juntos de propósito: `COPY` separado invalidaria o
# cache da instalação a cada mudança no outro arquivo, e a camada mais cara
# do build seria refeita à toa.
COPY requirements.txt requirements-snmp.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# --- SNMP: dependência do monitor de impressoras ----------------------
#
# ## Por que estava faltando
#
# `pysnmp` vive em `requirements-snmp.txt`, separado do principal para que
# uma falha ao instalá-lo não derrube a instalação de quem nunca vai usar
# SNMP. O `run.ps1` / `run.sh` tentam instalá-lo no host — e por isso o
# monitor funcionava fora do Docker.
#
# **O Dockerfile nunca foi atualizado para fazer o mesmo.** Em container, o
# monitor respondia "leitura por SNMP não disponível" e só aceitava contador
# à mão, enquanto na máquina local funcionava.
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

# --- Código da aplicação ----------------------------------------------
COPY app ./app
COPY frontend ./frontend
COPY alembic ./alembic
COPY alembic.ini .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
