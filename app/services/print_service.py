"""Serviço de impressão — gera etiquetas pelo template configurado e envia ao
DESTINO CADASTRADO.

A geração usa `app/services/label_layout.py` (geometria única) — o mesmo cálculo
alimenta ZPL, TSPL, PDF e a pré-visualização da tela de Administração.

Destinos suportados:
  * `agente`           → HTTP POST para o agente no Raspberry Pi (porta 9100)
  * `compartilhamento` → grava o job no compartilhamento (ex.: ``\\\\RTAT0001\\sip``)
  * `cups`             → envia para uma fila local do CUPS via `lp`
"""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from typing import Any

import httpx

from app.config import settings
from app.services.label_layout import (
    montar_layout,
    normalizar_config,
    render_pdf,
    render_tspl,
    render_zpl,
)

FORMATOS = {"zpl", "tspl", "pdf"}


def dados_do_ativo(ativo: Any, payload_qr: str | None = None) -> dict[str, str]:
    """Monta o dicionário de valores disponíveis para a etiqueta."""
    imp = getattr(ativo, "impressora", None)
    ti = getattr(ativo, "ti", None)
    dados: dict[str, str] = {
        "payload_qr": payload_qr or getattr(ativo, "qr_payload", "") or "",
        "patrimonio": ativo.patrimonio or "",
        "serie": ativo.numero_serie or "",
        "modelo": ativo.modelo or "",
        "marca": ativo.marca or "",
        "status": getattr(ativo.status, "value", ativo.status) or "",
        "dominio": "TI" if getattr(ativo.dominio, "value", ativo.dominio) == "ti" else "Impressora",
        "valor": f"R$ {float(ativo.valor):.2f}".replace(".", ",") if ativo.valor else "",
        "garantia": ativo.data_garantia.strftime("%d/%m/%Y") if ativo.data_garantia else "",
        "categoria": getattr(getattr(ativo, "categoria", None), "nome", "") or "",
        "localizacao": getattr(getattr(ativo, "localizacao", None), "nome", "") or "",
        "departamento": getattr(getattr(ativo, "departamento", None), "nome", "") or "",
        "hostname": (getattr(ti, "hostname", None) or getattr(imp, "hostname", None) or ""),
        "ip": (getattr(ti, "ip", None) or getattr(imp, "ip", None) or ""),
        "mac": getattr(ti, "mac_address", "") or "",
        "so": getattr(ti, "so", "") or "",
        "ram": f"{ti.ram_gb} GB" if getattr(ti, "ram_gb", None) else "",
        "contador": str(getattr(imp, "contador_paginas", "")) if getattr(imp, "contador_paginas", None) is not None else "",
    }
    return dados


def montar_label(template: Any, ativo: Any, payload_qr: str | None = None) -> dict:
    """Calcula a geometria da etiqueta para um ativo, usando o template dado."""
    cfg = dict(getattr(template, "config", None) or {})
    cfg["largura_mm"] = float(getattr(template, "largura_mm", 100) or 100)
    cfg["altura_mm"] = float(getattr(template, "altura_mm", 50) or 50)
    cfg["dpi"] = int(getattr(template, "dpi", 203) or 203)
    return montar_layout(normalizar_config(cfg), dados_do_ativo(ativo, payload_qr))


def montar_label_de_dados(config: dict, dados: dict[str, str]) -> dict:
    """Igual a `montar_label`, mas direto de uma configuração + dados (pré-visualização)."""
    return montar_layout(normalizar_config(config), dados)


def gerar_bytes(formato: str, layout: dict) -> bytes:
    """Renderiza a etiqueta no formato pedido a partir da geometria."""
    formato = (formato or "zpl").lower()
    if formato not in FORMATOS:
        raise ValueError(f"Formato inválido: {formato}. Use {sorted(FORMATOS)}")
    if formato == "pdf":
        return render_pdf(layout)
    if formato == "tspl":
        return render_tspl(layout)
    return render_zpl(layout)


def preview_base64(formato: str, layout: dict) -> str:
    return base64.b64encode(gerar_bytes(formato, layout)).decode("ascii")


# ---------------------------------------------------------------------------
# Transportes
# ---------------------------------------------------------------------------
def pdf_de_layouts(layouts: list[dict], titulo: str = "Etiquetas") -> bytes:
    """PDF com uma etiqueta por página, a partir de várias geometrias.

    Usado pelo lote de etiquetas em branco e pela impressão em massa.
    """
    import io as _io

    from reportlab.lib.units import mm as mm_unit
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    from app.services.qr_service import qr_png_bytes

    if not layouts:
        raise ValueError("Nenhuma etiqueta para gerar.")

    primeiro = layouts[0]
    buf = _io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(primeiro["largura_mm"] * mm_unit, primeiro["altura_mm"] * mm_unit))
    c.setTitle(titulo)

    for layout in layouts:
        altura_pag = layout["altura_mm"] * mm_unit
        for elemento in layout["elementos"]:
            if elemento["tipo"] == "qr":
                img = _io.BytesIO(qr_png_bytes(elemento["payload"], box_size=6, ecc=elemento.get("ecc", "M")))
                lado = elemento["tamanho_mm"] * mm_unit
                c.drawImage(
                    ImageReader(img),
                    elemento["x_mm"] * mm_unit,
                    altura_pag - elemento["y_mm"] * mm_unit - lado,
                    width=lado,
                    height=lado,
                )
            elif elemento["tipo"] == "texto":
                c.setFont("Helvetica-Bold" if elemento["negrito"] else "Helvetica", elemento["altura_mm"] * 2.83)
                c.drawString(
                    elemento["x_mm"] * mm_unit,
                    altura_pag - elemento["y_mm"] * mm_unit - elemento["altura_mm"] * mm_unit,
                    elemento["texto"],
                )
            elif elemento["tipo"] == "borda":
                c.setLineWidth(0.6)
                c.rect(
                    elemento["x_mm"] * mm_unit,
                    altura_pag - elemento["y_mm"] * mm_unit - elemento["altura_mm"] * mm_unit,
                    elemento["largura_mm"] * mm_unit,
                    elemento["altura_mm"] * mm_unit,
                )
        c.showPage()

    c.save()
    return buf.getvalue()


def _erro(detail: str, job_id: str) -> dict[str, Any]:
    return {"job_id": job_id, "status": "error", "detail": detail, "retryable": True}


def _via_agente(url: str, formato: str, label: bytes, printer: str, copies: int, job_id: str) -> dict[str, Any]:
    body = {
        "job_id": job_id,
        "format": formato,
        "data": base64.b64encode(label).decode("ascii"),
        "printer": printer,
        "copies": copies,
    }
    destino = url.rstrip("/") + "/print"
    ultimo_erro = ""
    for tentativa in range(3):
        try:
            resp = httpx.post(destino, json=body, timeout=settings.print_agent_timeout)
            resp.raise_for_status()
            data = resp.json()
            data["job_id"] = job_id
            data["attempts"] = tentativa + 1
            return data
        except httpx.HTTPError as exc:
            ultimo_erro = str(exc)
    return _erro(f"Agente de impressão indisponível ({ultimo_erro})", job_id)


def _eh_windows() -> bool:
    """Isolado numa função para poder ser testado (o caminho UNC é só Windows)."""
    return os.name == "nt"


def _unc_para_smb(share: str) -> tuple[str, str] | None:
    """Converte ``\\\\servidor\\impressora`` em ``("servidor", "impressora")``."""
    limpo = (share or "").strip().replace("/", "\\")
    if not limpo.startswith("\\\\"):
        return None
    partes = [p for p in limpo[2:].split("\\") if p]
    if len(partes) < 2:
        return None
    return partes[0], partes[1]


def _enviar_smbclient(share: str, dados: bytes) -> tuple[bool, str]:
    """Linux: envia para a fila do Windows pelo `smbclient`.

    É o equivalente Linux do `copy /b \\\\servidor\\impressora` do Windows: o
    arquivo cru vai pela porta de impressão (SPOOLSS), não por compartilhamento
    de arquivos. O `open()` do Python NÃO serve aqui — não existe caminho UNC.

    Requer o pacote de cliente Samba. Se as credenciais não estiverem
    configuradas, tenta acesso anônimo (`-N`).
    """
    exe = shutil.which("smbclient")
    if not exe:
        return False, (
            "smbclient não encontrado. Instale o cliente Samba "
            "(Debian/Ubuntu: 'apt install smbclient'; RHEL/Fedora: 'dnf install samba-client') "
            "ou cadastre uma fila do CUPS com a URI smb:// e use o tipo 'cups'."
        )

    alvo = _unc_para_smb(share)
    if alvo is None:
        return False, f"Endereço inválido: {share}. Use o formato \\\\servidor\\impressora."
    host, fila = alvo

    tmp = tempfile.NamedTemporaryFile(suffix=".raw", delete=False)
    try:
        tmp.write(dados)
        tmp.close()

        cmd = [exe, f"//{host}/{fila}"]
        if settings.print_smb_usuario:
            credencial = settings.print_smb_usuario
            if settings.print_smb_senha:
                credencial = f"{credencial}%{settings.print_smb_senha}"
            cmd += ["-U", credencial]
        else:
            cmd += ["-N"]  # acesso anônimo
        # Aspas para o caso de o caminho temporário conter espaços.
        cmd += ["-c", f'print "{tmp.name}"']

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if proc.returncode == 0:
            return True, ""
        detalhe = (proc.stderr or proc.stdout or "").strip()
        return False, detalhe[:300] or "smbclient retornou erro"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Falha ao executar o smbclient: {exc}"
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def _gravar_cru(destino: str, dados: bytes) -> tuple[bool, str]:
    """Grava os bytes CRUS no destino (fila de impressora compartilhada).

    No Windows, `\\\\servidor\\impressora` é resolvido pelo **spooler**, não pelo
    compartilhamento de arquivos: os bytes chegam à impressora exatamente como
    enviados (datatype RAW). É o mesmo caminho do clássico
    `copy /b etiqueta.zpl \\\\servidor\\impressora`.

    Devolve `(ok, mensagem_de_erro)`.
    """
    try:
        with open(destino, "wb") as fh:
            fh.write(dados)
        return True, ""
    except OSError as exc:
        erro_direto = str(exc)

    # Fallback no Windows: alguns drivers/antivírus tratam o handle direto de
    # forma diferente, e o `copy /b` passa. Vale a pena tentar antes de desistir.
    if _eh_windows():
        tmp = tempfile.NamedTemporaryFile(suffix=".raw", delete=False)
        try:
            tmp.write(dados)
            tmp.close()
            proc = subprocess.run(
                ["cmd", "/c", "copy", "/b", tmp.name, destino],
                capture_output=True, text=True, timeout=60,
            )
            if proc.returncode == 0:
                return True, ""
            detalhe = (proc.stderr or proc.stdout or "").strip()
            return False, f"{erro_direto} | copy /b: {detalhe}"
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"{erro_direto} | copy /b: {exc}"
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    return False, erro_direto


def _via_compartilhamento(
    share: str, formato: str, label: bytes, copies: int, job_id: str
) -> dict[str, Any]:
    """Envia a etiqueta para uma FILA COMPARTILHADA (ex.: ``\\\\DTAT7777\\SATO``).

    Serve para o cenário "Windows com impressora compartilhada": o próprio
    servidor onde a API roda escreve os bytes na fila, sem Raspberry e sem CUPS.
    """
    if not share:
        return _erro("Compartilhamento de impressora não configurado", job_id)

    share = share.strip()
    eh_unc = share.startswith("\\\\") or share.startswith("//")

    # O caminho UNC de UMA IMPRESSORA não é acesso a arquivo por SMB.
    #   Windows → o spooler resolve \\servidor\impressora (gravação crua).
    #   Linux   → não existe esse caminho; usa-se o smbclient (protocolo de
    #             impressão) ou uma fila do CUPS com URI smb://.
    if not eh_unc and not _eh_windows():
        return _erro(
            f"Endereço inválido para fila compartilhada no Linux: {share}. "
            "Use \\\\servidor\\impressora (ex.: \\\\DTAT7777\\SATO).",
            job_id,
        )

    if formato == "pdf":
        return _erro(
            "Este destino recebe comandos CRUS (ZPL/TSPL) e não aceita PDF. "
            "Escolha o formato ZPL ou TSPL — ou baixe o PDF para imprimir manualmente.",
            job_id,
        )

    # `copies` era ignorado aqui: em impressão crua, repetir o fluxo é o que
    # gera mais de uma etiqueta.
    dados = label * max(1, copies)

    # O spooler fica ocupado e o compartilhamento pode oscilar; 3 tentativas
    # resolvem a maior parte dos casos reais.
    ultimo_erro = ""
    for tentativa in range(3):
        if _eh_windows():
            ok, erro = _gravar_cru(share, dados)
        else:
            ok, erro = _enviar_smbclient(share, dados)
        if ok:
            return {
                "job_id": job_id,
                "status": "ok",
                "message": f"Enviado para {share}" + (f" ({copies} cópias)" if copies > 1 else ""),
                "printer": share,
                "attempts": tentativa + 1,
            }
        ultimo_erro = erro
        # Falta de smbclient / endereço inválido não melhora com retentativa.
        if not _eh_windows() and ("não encontrado" in erro or "inválido" in erro):
            return _erro(erro, job_id)
        if tentativa < 2:
            time.sleep(0.6 * (tentativa + 1))

    dica = ""
    if eh_unc and _eh_windows():
        dica = (
            " Confira: (1) a impressora está compartilhada no servidor de origem; "
            "(2) a conta que roda o sistema tem permissão de impressão; "
            "(3) o nome da fila está correto (Testar impressão em Administração → Impressão)."
        )
    elif eh_unc:
        dica = (
            " Confira: (1) o pacote smbclient está instalado; "
            "(2) as credenciais (PRINT_SMB_USUARIO/PRINT_SMB_SENHA) têm acesso à fila; "
            "(3) o servidor de impressão está acessível pela rede. "
            "Alternativa no Linux: fila do CUPS com URI smb:// e tipo 'cups'."
        )
    return _erro(f"Falha ao enviar para {share}: {ultimo_erro}.{dica}", job_id)


def _via_cups(fila: str, formato: str, label: bytes, copies: int, job_id: str) -> dict[str, Any]:
    if not shutil.which("lp"):
        return _erro("CUPS (lp) não está disponível neste servidor", job_id)
    sufixo = ".pdf" if formato == "pdf" else f".{formato}"
    tmp = tempfile.NamedTemporaryFile(suffix=sufixo, delete=False)
    try:
        tmp.write(label)
        tmp.close()
        cmd = ["lp", "-d", fila, "-n", str(copies)]
        if formato != "pdf":
            cmd += ["-o", "raw"]
        cmd.append(tmp.name)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode == 0:
            return {"job_id": job_id, "status": "ok", "message": proc.stdout.strip() or "Enviado ao CUPS", "printer": fila}
        return _erro(proc.stderr.strip() or "lp falhou", job_id)
    except (OSError, subprocess.SubprocessError) as exc:
        return _erro(f"Falha no CUPS: {exc}", job_id)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Envio
# ---------------------------------------------------------------------------
def gerar_bytes_lote(formato: str, layouts: list[dict]) -> bytes:
    """Gera VÁRIAS etiquetas em um único fluxo.

    Para ZPL/TSPL basta concatenar: cada etiqueta já é um bloco fechado
    (`^XA…^XZ` / `SIZE…PRINT`), então a impressora imprime todas em sequência.
    Isso evita disparar um job HTTP por etiqueta em lotes grandes.
    """
    if not layouts:
        raise ValueError("Nenhuma etiqueta para imprimir.")
    formato = (formato or "zpl").lower()
    if formato == "pdf":
        return pdf_de_layouts(layouts)
    if len(layouts) == 1:
        return gerar_bytes(formato, layouts[0])
    return b"".join(gerar_bytes(formato, layout) for layout in layouts)


def send_print_job(
    *,
    layout: dict | None = None,
    layouts: list[dict] | None = None,
    formato: str = "zpl",
    printer: str = "",
    copies: int = 1,
    dispositivo: Any = None,
) -> dict[str, Any]:
    """Gera a etiqueta (ou um lote) da geometria e envia ao dispositivo cadastrado."""
    job_id = uuid.uuid4().hex
    tipo = (getattr(dispositivo, "tipo", None) or "agente").lower()
    formato = (getattr(dispositivo, "formato", None) or formato or "zpl").lower()

    if layouts:
        label = gerar_bytes_lote(formato, layouts)
    elif layout is not None:
        label = gerar_bytes(formato, layout)
    else:
        return _erro("Nenhuma etiqueta informada para impressão", job_id)

    if tipo == "compartilhamento":
        alvo = getattr(dispositivo, "compartilhamento", None) or printer
        return _via_compartilhamento(alvo, formato, label, copies, job_id)
    if tipo == "cups":
        fila = getattr(dispositivo, "fila_cups", None) or printer or settings.cups_printer_default
        return _via_cups(fila, formato, label, copies, job_id)

    url = getattr(dispositivo, "agente_url", None)
    if not url and getattr(dispositivo, "hostname", None):
        url = f"http://{dispositivo.hostname}:9100"
    if not url:
        url = settings.print_agent_url
    fila = getattr(dispositivo, "fila_cups", None) or printer or settings.cups_printer_default
    return _via_agente(url, formato, label, fila, copies, job_id)
