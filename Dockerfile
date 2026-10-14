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
# ## Por que `-bullseye`, e não a padrão
#
# A tag `postgres:16` é **bookworm** (Debian 12, glibc 2.36). O estágio 2 é
# **bullseye** (Debian 11, glibc 2.31) — e o `pg_dump` copiado **não roda**
# com uma glibc mais nova do que a do sistema que o executa:
#
#     pg_dump: /lib/x86_64-linux-gnu/libc.so.6: version `GLIBC_2.36' not found
#
# Copiar as bibliotecas junto (o que fazemos abaixo) **não resolve** isso:
# `libc.so.6` é o próprio núcleo do sistema, e misturar versões dele quebra
# tudo. A saída é a imagem de origem ter a **mesma base** do destino.
#
# ## Por que Debian, e não `-alpine`
#
# Um binário musl (Alpine) não carrega em glibc. As duas pontas são Debian.
FROM postgres:16-bullseye AS origem

# --- Estágio 2: a aplicação -------------------------------------------
#
# ## Por que `bullseye`, e não `bookworm`
#
# O servidor de destino roda **CentOS 7**, com kernel 3.10 e **Docker
# 19.03.12** — de julho de 2020.
#
# O `python:3.12-slim` é bookworm, com **glibc 2.36**. A partir do glibc
# 2.34, criar thread usa a chamada **`clone3`** — que o kernel 3.10 não tem.
#
# O certo seria o Docker responder "não conheço essa chamada" (`ENOSYS`) e o
# Python cair na antiga. O seccomp profile do 19.03.12 responde **`EPERM`**
# ("proibido"), e o Python conclui:
#
#     RuntimeError: can't start new thread
#
# Era a causa de TODOS os erros desta implantação — inclusive dos
# `runc did not terminate successfully`, que eram o `pip` (Python, e abre
# threads) sendo morto no mesmo ponto.
#
# A correção do Docker veio na **20.10.10**. Como o servidor tem containers
# rodando e uma atualização de 1.13 para 24.x no CentOS 7 mexeria no storage
# driver, a saída é **não tocar no host**:
#
#     bullseye = glibc 2.31 → não usa `clone3` → funciona no kernel 3.10
#
# ## O que muda junto
#
# Python **3.11** em vez de 3.12. Os wheels em `wheels/` já foram baixados
# para `cp311` — trocar a base sem trocá-los daria
# `No matching distribution found` para todo pacote com extensão compilada.
FROM python:3.11-slim-bullseye

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

# --- Dependências Python, dos pacotes que estão NO PROJETO -------------
#
# ## Por que os pacotes vêm junto, e não do PyPI
#
# Numa rede corporativa o build não alcança o PyPI, e falhava com
# `runc did not terminate successfully` — a moldura genérica de "o processo
# foi morto", que não diz nada.
#
# Em vez de negociar exceção de firewall, os pacotes ficam **no
# repositório**: `wheels/` tem os 47 arquivos `.whl` para Linux x86_64 e
# Python 3.12, somando ~31 MB.
#
# ## O `--no-index` é a parte que importa
#
# Ele diz ao pip para **não consultar o PyPI** — só a pasta local. Sem isso,
# o pip ainda tentaria a rede para conferir versões, e o build continuaria
# dependendo dela.
#
# Com `--no-index --find-links`, o build funciona **sem rede nenhuma**.
#
# ## Como atualizar os pacotes
#
# Ao mudar o `requirements.txt`:
#
#     python -m pip download --dest wheels \
#         --python-version 312 --only-binary=:all: \
#         --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 \
#         --platform manylinux_2_28_x86_64 --platform linux_x86_64 \
#         -r requirements.txt -r requirements-snmp.txt
#
# Depois `git add wheels` — os arquivos vão versionados.
COPY requirements.txt requirements-snmp.txt ./
COPY wheels ./wheels
RUN pip install --no-cache-dir --no-index --find-links=./wheels \
        --progress-bar off -r requirements.txt

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
        pip install --no-cache-dir --no-index --find-links=./wheels \
            --progress-bar off -r requirements-snmp.txt; \
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
