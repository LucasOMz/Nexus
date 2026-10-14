#!/usr/bin/env bash
# =====================================================================
# Instala as dependências do Nexus FORA do build, para ver o erro real.
#
# ## Por que existe
#
# O build falha com `runc did not terminate successfully` — uma moldura, não
# um erro. Ela não diz *o que* falhou, e o Portainer mostra só essa linha.
#
# Aqui a instalação roda no terminal, onde **a mensagem de verdade aparece**:
# o pacote exato, e o motivo.
#
# ## O que ele faz
#
#   1. confere o ambiente (docker, memória, disco)
#   2. testa o PyPI com UM pacote pequeno — separa rede de memória
#   3. instala os requisitos reais, **em lotes**, vigiando a memória
#   4. se der certo, salva o resultado como imagem reutilizável
#
# ## Como usar
#
#   cd /data/compose/2          # a pasta do compose, no servidor
#   bash scripts/instalar_dependencias.sh
#
# Para usar a imagem depois de pronta, troque a primeira linha do Dockerfile:
#
#   FROM nexus-deps:ok
#
# ...e **remova** o `RUN pip install -r requirements.txt` de lá.
# =====================================================================

set -uo pipefail

PROJETO="${1:-$(pwd)}"
IMAGEM_BASE="python:3.12-slim"
NOME_CONTAINER="nexus-deps"
IMAGEM_SAIDA="nexus-deps:ok"

# Lotes: a instalação inteira de uma vez é o maior pico de memória do build.
# Separar reduz o pico e mostra qual grupo falha.
LOTE_1="fastapi uvicorn[standard] sqlalchemy pydantic pydantic-settings python-multipart"
LOTE_2="PyJWT bcrypt email-validator httpx"
LOTE_3="cryptography bcrypt reportlab psycopg[binary] qrcode[pil]"
LOTE_4="alembic ldap3 pymysql"

amarelo() { printf '\033[33m%s\033[0m\n' "$*"; }
verde()   { printf '\033[32m%s\033[0m\n' "$*"; }
vermelho(){ printf '\033[31m%s\033[0m\n' "$*"; }

# ---------------------------------------------------------------------
echo "======================================================"
echo " 1. Ambiente"
echo "======================================================"

if ! command -v docker >/dev/null 2>&1; then
    vermelho "  docker nao encontrado. Este script roda NO SERVIDOR."
    exit 1
fi
verde "  docker: $(docker --version)"

echo
echo "  --- memoria ---"
free -h 2>/dev/null || echo "  (free indisponivel)"

echo
echo "  --- disco ---"
df -h /var/lib/docker 2>/dev/null || df -h /

echo
echo "  --- projeto ---"
if [ ! -f "$PROJETO/requirements.txt" ]; then
    vermelho "  requirements.txt nao encontrado em $PROJETO"
    echo "  Uso: bash $0 /caminho/do/projeto"
    exit 1
fi
verde "  requirements.txt encontrado"

# ---------------------------------------------------------------------
echo
echo "======================================================"
echo " 2. O PyPI responde? (um pacote pequeno)"
echo "======================================================"
echo
echo "  Este teste separa REDE de MEMORIA. Se falhar aqui com"
echo "  'Connection timed out', o problema nao e o projeto —"
echo "  e a rede, e a correcao e um mirror interno do PyPI."
echo

if docker run --rm "$IMAGEM_BASE" \
        pip install --no-cache-dir --quiet fastapi 2>&1 | tail -20; then
    verde "  PyPI OK — o pip alcanca o repositorio"
else
    vermelho "  FALHOU no teste simples."
    echo
    echo "  Causas provaveis, em ordem:"
    echo "    - PyPI bloqueado pela rede  -> mirror interno"
    echo "    - memoria insuficiente      -> swap (ver abaixo)"
    echo "    - proxy nao configurado     -> /etc/docker/daemon.json"
    echo
    echo "  Para ver o erro exato, rode sem o --quiet:"
    echo "    docker run --rm $IMAGEM_BASE pip install fastapi"
    exit 1
fi

# ---------------------------------------------------------------------
echo
echo "======================================================"
echo " 3. Monitor de memoria em segundo plano"
echo "======================================================"

MONITOR_LOG=$(mktemp)
(
    while true; do
        printf '%s ' "$(date +%H:%M:%S)"
        free -m 2>/dev/null | awk '/^Mem:/ {print "livre="$7"MB swap_livre="$4"MB"}'
        sleep 3
    done
) > "$MONITOR_LOG" 2>&1 &
MONITOR_PID=$!
echo "  registrando em $MONITOR_LOG"

parar_monitor() {
    kill "$MONITOR_PID" 2>/dev/null
    wait "$MONITOR_PID" 2>/dev/null
}

# ---------------------------------------------------------------------
echo
echo "======================================================"
echo " 4. Instalando, em lotes"
echo "======================================================"
echo
echo "  Em lotes porque a instalacao inteira de uma vez e o maior"
echo "  pico de memoria. Separado, o pico e menor e da para ver"
echo "  QUAL grupo falha."
echo

docker rm -f "$NOME_CONTAINER" >/dev/null 2>&1

FALHOU=""
# Cada lote parte do resultado do anterior.
#
# Sem isto, o lote 2 comecaria da imagem base e jogaria fora o lote 1 — o
# container novo nao enxerga o que foi instalado num container que ja morreu.
# O `commit` a cada lote e o que faz o trabalho acumular.
IMAGEM_ATUAL="$IMAGEM_BASE"

for n in 1 2 3 4; do
    var="LOTE_$n"
    pacotes="${!var}"
    echo
    amarelo "  --- lote $n ---"
    echo "  $pacotes"
    echo

    if ! docker run --name "$NOME_CONTAINER" \
            -v "$PROJETO:/app" -w /app \
            "$IMAGEM_ATUAL" \
            sh -c "pip install --no-cache-dir --prefer-binary $pacotes" 2>&1 | tail -15; then
        FALHOU="lote $n"
        break
    fi

    docker commit "$NOME_CONTAINER" "${IMAGEM_SAIDA}-parcial" >/dev/null 2>&1
    docker rm "$NOME_CONTAINER" >/dev/null 2>&1
    IMAGEM_ATUAL="${IMAGEM_SAIDA}-parcial"
    verde "  lote $n OK"
done

parar_monitor

echo
echo "  --- pico de memoria observado ---"
tail -6 "$MONITOR_LOG"

# ---------------------------------------------------------------------
echo
echo "======================================================"
echo " 5. Resultado"
echo "======================================================"

if [ -n "$FALHOU" ]; then
    vermelho "  Falhou no $FALHOU"
    echo
    echo "  Veja a mensagem ACIMA desta linha. Ela diz o pacote e o motivo."
    echo
    echo "  Se apareceu 'Killed' -> memoria. Adicione swap e repita:"
    echo "    sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile"
    echo "    sudo mkswap /swapfile && sudo swapon /swapfile"
    echo
    echo "  Pico observado:"
    sort -t= -k2 -n "$MONITOR_LOG" 2>/dev/null | head -1 || tail -3 "$MONITOR_LOG"
    exit 1
fi

echo "  Instalando os requisitos COMPLETOS por cima dos lotes..."
if docker run --name "$NOME_CONTAINER" \
        -v "$PROJETO:/app" -w /app \
        -e PIP_NO_CACHE_DIR=1 \
        "$IMAGEM_SAIDA-parcial" \
        sh -c "pip install --prefer-binary -r requirements.txt -r requirements-snmp.txt" 2>&1 | tail -12; then
    docker commit "$NOME_CONTAINER" "$IMAGEM_SAIDA" >/dev/null
    docker rm "$NOME_CONTAINER" >/dev/null 2>&1
    verde "  Imagem pronta: $IMAGEM_SAIDA"
else
    vermelho "  Falhou nos requisitos completos."
    docker rm -f "$NOME_CONTAINER" >/dev/null 2>&1
    exit 1
fi

# ---------------------------------------------------------------------
echo
echo "======================================================"
echo " 6. Conferindo"
echo "======================================================"
docker run --rm "$IMAGEM_SAIDA" python -c "
import fastapi, sqlalchemy, pydantic, cryptography, reportlab, jwt, bcrypt, httpx
print('  bibliotecas principais: OK')
try:
    import pysnmp; print('  pysnmp:', pysnmp.__version__)
except ImportError:
    print('  pysnmp: AUSENTE — o monitor de impressoras ficara sem SNMP')
"
docker run --rm "$IMAGEM_SAIDA" pg_dump --version 2>/dev/null \
    || echo "  pg_dump: ausente (esta imagem nao tem o cliente)"

echo
verde "  Pronto."
echo
echo "  Para usar no build, troque a primeira linha do Dockerfile:"
echo
echo "      FROM $IMAGEM_SAIDA"
echo
echo "  ...e APAGUE a linha 'RUN pip install -r requirements.txt'."
echo "  As dependencias ja estao na imagem — o build nao instala nada."
