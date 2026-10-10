#!/usr/bin/env bash
# run.sh — sobe o sistema em Linux/macOS (ou Raspberry Pi).
# Uso:  ./run.sh   |   PORT=9000 ./run.sh   |   ./run.sh --setup
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8000}"
PY=".venv/bin/python"

# As bibliotecas essenciais estão instaladas neste interpretador?
#
# Verificar só se a pasta `.venv` existe NÃO basta: uma instalação interrompida
# (ou um venv criado sem instalar nada) deixa a pasta pronta e as dependências
# faltando. O sintoma é o pior possível — o sistema anuncia que vai subir e
# falha no final com "No module named uvicorn".
tem_dependencias() {
  "$1" -c 'import fastapi, uvicorn, sqlalchemy, pydantic' >/dev/null 2>&1
}

dica_de_instalacao() {
  echo ""
  echo "  [erro] Não foi possível instalar as dependências."
  echo ""
  echo "  No Raspberry Pi / Debian, as causas mais comuns são a falta do"
  echo "  módulo venv e de ferramentas de compilação. Instale com:"
  echo ""
  echo "      sudo apt update"
  echo "      sudo apt install -y python3-venv python3-dev build-essential libffi-dev libssl-dev"
  echo ""
  echo "  Depois rode novamente:  ./run.sh"
  echo ""
}

# Instala as dependências. Se a lista completa falhar, tenta sem os extras do
# uvicorn: `uvicorn[standard]` traz uvloop e httptools, que precisam COMPILAR e
# são o que mais quebra no Raspberry Pi (principalmente em 32 bits). O uvicorn
# puro atende perfeitamente — o sistema não depende desses extras.
instalar_dependencias() {
  if "$PY" -m pip install -r requirements.txt; then
    return 0
  fi
  echo ""
  echo "  [aviso] A instalação completa falhou."
  echo "          Tentando sem os extras do uvicorn (uvloop/httptools)..."
  echo ""
  "$PY" -m pip install \
    "fastapi>=0.115" "uvicorn>=0.32" "sqlalchemy>=2.0.36" "pydantic>=2.9" \
    "pydantic-settings>=2.6" "python-multipart>=0.0.17" "PyJWT>=2.9" \
    "bcrypt>=4.2" "qrcode[pil]>=8.0" "reportlab>=4.2" "httpx>=0.27" \
    "alembic>=1.14" "email-validator>=2.2" "ldap3>=2.9" "cryptography>=43"
}

# Dependências OPCIONAIS — a falha NÃO interrompe nada.
#
# SNMP de impressoras: contador e tonner lidos direto da máquina. Não é
# Python puro e arrasta dependências; se falhar aqui, quem nunca vai usar
# SNMP não pode ficar sem sistema.
instalar_opcionais() {
  if [ -f requirements-snmp.txt ]; then
    echo "[setup] Instalando SNMP de impressoras (opcional) ..."
    if "$PY" -m pip install -r requirements-snmp.txt --quiet; then
      echo "        ok"
    else
      echo "        não instalado (opcional). O sistema funciona normalmente;"
      echo "        sem ele, o Monitor de impressoras avisa que o SNMP está indisponível."
      echo "        Para instalar depois:  $PY -m pip install -r requirements-snmp.txt"
    fi
  fi
  if [ -f requirements-drivers.txt ]; then
    echo "[setup] Instalando drivers opcionais de banco ..."
    if "$PY" -m pip install -r requirements-drivers.txt --quiet; then
      echo "        ok"
    else
      echo "        não instalados (opcional). O MySQL já funciona;"
      echo "        para SQL Server:  $PY -m pip install -r requirements-drivers.txt"
    fi
  fi
}

if [ ! -x "$PY" ]; then
  # Sem .venv: tenta aproveitar um .vendor que funcione NESTA máquina.
  # (o .vendor traz binários compilados para outra plataforma — por isso a
  #  verificação importa de verdade, não basta a pasta existir)
  if [ -d ".vendor" ] && PYTHONPATH="$PWD/.vendor" tem_dependencias "$(command -v python3)"; then
    PY="$(command -v python3)"
    export PYTHONPATH="$PWD/.vendor"
    echo "[run] Usando dependências locais .vendor"
  else
    echo "[setup] Criando ambiente virtual .venv ..."
    python3 -m venv .venv || { dica_de_instalacao; exit 1; }
    PY=".venv/bin/python"
    "$PY" -m pip install --upgrade pip >/dev/null 2>&1 || true
  fi
fi

# Instala (ou completa) as dependências sempre que faltarem — inclusive quando
# o .venv já existe.
if ! tem_dependencias "$PY"; then
  echo "[setup] Instalando as dependências (pode levar alguns minutos no Pi)..."
  if ! instalar_dependencias; then
    dica_de_instalacao
    exit 1
  fi
fi

# Opcionais: tentados DEPOIS que o essencial está garantido, e sem interromper.
instalar_opcionais

# Confere de novo: se ainda faltar, é melhor dizer agora do que falhar no fim.
if ! tem_dependencias "$PY"; then
  echo ""
  echo "  [erro] As dependências continuam faltando depois da instalação."
  echo "         Verifique a saída do pip acima."
  echo ""
  exit 1
fi

if [ "${1:-}" = "--setup" ]; then
  echo "[ok] Ambiente pronto. Rode: ./run.sh"
  exit 0
fi

echo ""
echo "  Gestao Patrimonial rodando em:  http://127.0.0.1:${PORT}"
echo "  Login inicial:  admin@empresa.com  /  admin123"
echo "  Encerrar: CTRL + C"
echo ""
exec "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
