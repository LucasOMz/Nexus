#!/usr/bin/env python3
"""Agente de impressão para Raspberry Pi (systemd-ready).

Recebe jobs autenticados do backend (POST /print, porta 9100) e encaminha
ao CUPS (`lp`). Suporta:
  - PDF: impressão normal via `lp`.
  - ZPL/TSPL: impressão raw (`lp -o raw`) ou socket TCP cru para impressoras
    térmicas sem driver CUPS (ex.: Zebra/TSC em rede).

Execução:
  RPI_PRINT_TOKEN=<segredo> python raspberry_print_agent.py  # 127.0.0.1:9100

systemd (exemplo de unit em README.md):
  ExecStart=/usr/bin/python3 /opt/estoque/raspberry_print_agent.py
"""
from __future__ import annotations

import base64
import binascii
import hmac
import os
import re
import socket
import subprocess
import tempfile
import time
from collections import deque
from threading import Lock
from typing import Optional
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, ValidationError

app = FastAPI(title="Raspberry Print Agent", version="1.0.0")

PORT = int(os.getenv("RPI_PRINT_PORT", "9100"))
bearer = HTTPBearer(auto_error=False)
# Impressoras conhecidas como "térmicas raw" (enviar via socket em vez de CUPS).
RAW_TCP_DEFAULT_PORT = 9100
MAX_JOB_BYTES = 12 * 1024 * 1024
MAX_JOBS_PER_MINUTE = 60
_jobs_recebidos: deque[float] = deque()
_jobs_lock = Lock()


def exigir_token(credencial: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
    token = os.getenv("RPI_PRINT_TOKEN", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,}", token):
        raise HTTPException(503, "Credencial do agente não configurada.")
    if not credencial or not hmac.compare_digest(credencial.credentials.encode(), token.encode()):
        raise HTTPException(401, "Credencial do agente inválida.", headers={"WWW-Authenticate": "Bearer"})


class PrintJob(BaseModel):
    job_id: str = Field(min_length=1, max_length=120)
    format: str = Field(default="zpl", max_length=4)
    data: str  # conteúdo da etiqueta em base64
    printer: str = Field(default="zebra", min_length=1, max_length=255)
    copies: int = Field(default=1, ge=1, le=10)
    patrimonio: Optional[str] = None
    dominio: Optional[str] = None


async def ler_trabalho(request: Request) -> PrintJob:
    with _jobs_lock:
        agora = time.monotonic()
        while _jobs_recebidos and agora - _jobs_recebidos[0] >= 60:
            _jobs_recebidos.popleft()
        if len(_jobs_recebidos) >= MAX_JOBS_PER_MINUTE:
            espera = max(1, 60 - int(agora - _jobs_recebidos[0]))
            raise HTTPException(429, "Limite de trabalhos por minuto atingido.", headers={"Retry-After": str(espera)})
        _jobs_recebidos.append(agora)

    conteudo = bytearray()
    async for bloco in request.stream():
        if len(conteudo) + len(bloco) > MAX_JOB_BYTES:
            raise HTTPException(413, "Trabalho de impressão acima de 12 MiB.")
        conteudo.extend(bloco)
    try:
        return PrintJob.model_validate_json(conteudo)
    except ValidationError as exc:
        raise HTTPException(422, "Trabalho de impressão inválido.") from exc


def destinos_permitidos(variavel: str, padrao: str = "") -> set[str]:
    return {valor.strip() for valor in os.getenv(variavel, padrao).split(",") if valor.strip()}


def _cups_print(printer: str, copies: int, raw: bool, content: bytes) -> tuple[bool, str]:
    """Envia conteúdo ao CUPS via `lp`. `raw=True` usa o driver raw (ZPL/TSPL)."""
    with tempfile.NamedTemporaryFile(suffix=f".{content[:4]!r}".replace("b'", "").strip("'"), delete=False) as tmp:
        tmp.write(content)
        path = tmp.name
    try:
        cmd = ["lp", "-d", printer, "-n", str(copies)]
        if raw:
            cmd += ["-o", "raw"]
        cmd.append(path)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode == 0:
            return True, proc.stdout.strip()
        return False, proc.stderr.strip() or "lp falhou"
    finally:
        os.unlink(path)


def _raw_socket_print(host: str, port: int, content: bytes) -> tuple[bool, str]:
    """Envia bytes crus via socket TCP (impressora térmica em rede)."""
    try:
        with socket.create_connection((host, port), timeout=10) as sock:
            sock.sendall(content)
        return True, "enviado via socket"
    except OSError as exc:
        return False, str(exc)


def _destino_raw(printer: str) -> tuple[str, int] | None:
    """Interpreta um destino de rede já autorizado na configuração local."""
    try:
        url = urlsplit(f"//{printer}")
        host, port = url.hostname, url.port
    except ValueError:
        return None
    if not host or url.path or url.query or url.fragment or url.username is not None or port == 0:
        return None
    return host, port or RAW_TCP_DEFAULT_PORT


@app.get("/health", dependencies=[Depends(exigir_token)])
def health() -> dict:
    """Heartbeat consumido pelo backend para monitorar o agente."""
    printers: list[str] = []
    try:
        out = subprocess.run(["lpstat", "-p"], capture_output=True, text=True, timeout=10)
        for line in out.stdout.splitlines():
            if line.startswith("printer "):
                printers.append(line.split()[1])
    except Exception:  # pragma: no cover - lpstat ausente não é fatal
        printers = []
    return {"status": "ok", "time": time.time(), "printers": printers}


@app.post("/print", dependencies=[Depends(exigir_token)])
def print_job(job: PrintJob = Depends(ler_trabalho)) -> dict:
    """Processa e imprime uma etiqueta."""
    try:
        content = base64.b64decode(job.data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(400, "dados base64 inválidos") from exc

    formato = job.format.lower()
    if formato not in ("zpl", "tspl", "pdf"):
        raise HTTPException(400, "formato inválido (use zpl, tspl ou pdf)")

    raw = formato in ("zpl", "tspl")

    # 1) Impressora raw em rede (ex.: Zebra/TSC sem CUPS).
    if raw and job.printer in destinos_permitidos("RPI_PRINT_RAW_DESTINATIONS"):
        host_port = _destino_raw(job.printer)
        if host_port is None:
            raise HTTPException(503, "Destino de impressão em rede inválido na configuração do agente.")
        ok, msg = _raw_socket_print(host_port[0], host_port[1], content)
        if ok:
            return {"job_id": job.job_id, "status": "ok", "message": msg, "printer": job.printer}
        return {"job_id": job.job_id, "status": "error", "detail": msg, "retryable": True}

    # 2) Fallback CUPS (lp).
    if job.printer not in destinos_permitidos("RPI_PRINT_QUEUES", "zebra"):
        raise HTTPException(403, "Destino de impressão não autorizado.")
    ok, msg = _cups_print(job.printer, job.copies, raw, content)
    if ok:
        return {"job_id": job.job_id, "status": "ok", "message": msg or "enviado ao CUPS", "printer": job.printer}
    return {"job_id": job.job_id, "status": "error", "detail": msg, "retryable": True}


if __name__ == "__main__":
    import uvicorn

    # OPCIONAL: se rodar como script, sobe o servidor na porta 9100.
    host = os.getenv("RPI_PRINT_HOST", "127.0.0.1")
    cert = os.getenv("RPI_PRINT_TLS_CERT")
    key = os.getenv("RPI_PRINT_TLS_KEY")
    if bool(cert) != bool(key) or (host not in {"127.0.0.1", "::1"} and not cert):
        raise SystemExit("Configure o certificado e a chave TLS para escutar fora do loopback.")
    uvicorn.run(app, host=host, port=PORT, ssl_certfile=cert, ssl_keyfile=key, log_level="info")
