#!/usr/bin/env python3
"""Agente de impressão para Raspberry Pi (systemd-ready).

Recebe jobs de etiquetas do backend (HTTP POST /print, porta 9100) e encaminha
ao CUPS (`lp`). Suporta:
  - PDF: impressão normal via `lp`.
  - ZPL/TSPL: impressão raw (`lp -o raw`) ou socket TCP cru para impressoras
    térmicas sem driver CUPS (ex.: Zebra/TSC em rede).

Execução:
  python raspberry_print_agent.py                 # escuta em 0.0.0.0:9100
  RPI_PRINT_PORT=9100 RPI_PRINT_ALLOWED_HOSTS=...  # config opcional

systemd (exemplo de unit em README.md):
  ExecStart=/usr/bin/python3 /opt/estoque/raspberry_print_agent.py
"""
from __future__ import annotations

import base64
import os
import socket
import subprocess
import tempfile
import time
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Raspberry Print Agent", version="1.0.0")

PORT = int(os.getenv("RPI_PRINT_PORT", "9100"))
# Impressoras conhecidas como "térmicas raw" (enviar via socket em vez de CUPS).
RAW_TCP_DEFAULT_PORT = 9100


class PrintJob(BaseModel):
    job_id: str
    format: str = "zpl"  # zpl | tspl | pdf
    data: str  # conteúdo da etiqueta em base64
    printer: str = "zebra"
    copies: int = Field(default=1, ge=1, le=10)
    patrimonio: Optional[str] = None
    dominio: Optional[str] = None


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


def _looks_like_host(printer: str) -> Optional[tuple[str, int]]:
    """Se `printer` for host[:porta], trata como impressora raw em rede."""
    if not printer:
        return None
    host = printer
    port = RAW_TCP_DEFAULT_PORT
    if ":" in printer and not printer.startswith("["):
        host, _, port_s = printer.rpartition(":")
        if port_s.isdigit():
            port = int(port_s)
    if host.replace(".", "").replace("-", "").isalnum() and "." in host:
        return host, port
    return None


@app.get("/health")
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


@app.post("/print")
def print_job(job: PrintJob) -> dict:
    """Processa e imprime uma etiqueta."""
    try:
        content = base64.b64decode(job.data)
    except Exception:
        raise HTTPException(400, "dados base64 inválidos")

    formato = job.format.lower()
    if formato not in ("zpl", "tspl", "pdf"):
        raise HTTPException(400, "formato inválido (use zpl, tspl ou pdf)")

    raw = formato in ("zpl", "tspl")

    # 1) Impressora raw em rede (ex.: Zebra/TSC sem CUPS).
    host_port = _looks_like_host(job.printer)
    if raw and host_port is not None:
        ok, msg = _raw_socket_print(host_port[0], host_port[1], content)
        if ok:
            return {"job_id": job.job_id, "status": "ok", "message": msg, "printer": job.printer}
        return {"job_id": job.job_id, "status": "error", "detail": msg, "retryable": True}

    # 2) Fallback CUPS (lp).
    ok, msg = _cups_print(job.printer, job.copies, raw, content)
    if ok:
        return {"job_id": job.job_id, "status": "ok", "message": msg or "enviado ao CUPS", "printer": job.printer}
    return {"job_id": job.job_id, "status": "error", "detail": msg, "retryable": True}


if __name__ == "__main__":
    import uvicorn

    # OPCIONAL: se rodar como script, sobe o servidor na porta 9100.
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
