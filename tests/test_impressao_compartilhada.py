"""Impressão em FILA COMPARTILHADA (Windows), sem Raspberry e sem CUPS.

Cenário do usuário: em vez de um agente Linux, usar a fila compartilhada de uma
máquina Windows — por exemplo `\\\\DTAT7777\\SATO`.

O envio é a gravação dos bytes CRUS no caminho UNC: o spooler do Windows recebe
o fluxo exatamente como está (datatype RAW). É o mesmo caminho do clássico
`copy /b etiqueta.zpl \\\\DTAT7777\\SATO`.

O que estes testes cobrem: montagem dos bytes, cópias, validações e mensagens.
O roteamento até a impressora física depende do spooler e precisa ser conferido
no servidor, com o botão "Imprimir teste" (Administração → Impressão).
"""
from __future__ import annotations

import os
import subprocess

import pytest

from app.config import settings
from app.services import print_service
from app.services.print_service import (
    _unc_para_smb,
    _via_compartilhamento,
    send_print_job,
)


def _sem_janelas(monkeypatch):
    """Faz o código acreditar que está no Linux."""
    monkeypatch.setattr(print_service, "_eh_windows", lambda: False)


class DispositivoFalso:
    """Dispositivo de impressão apontando para um caminho do sistema de arquivos."""

    id = 1
    nome = "Fila compartilhada"
    tipo = "compartilhamento"
    formato = "zpl"
    padrao = True
    ativo = True
    compartilhamento = ""
    agente_url = None
    fila_cups = None
    hostname = None
    template_id = None


def test_grava_os_bytes_crus(tmp_path):
    destino = tmp_path / "etiqueta.zpl"
    etiqueta = b"^XA^FO50,50^FDATIVO 123^FS^XZ\n"

    resp = _via_compartilhamento(str(destino), "zpl", etiqueta, 1, "job1")

    assert resp["status"] == "ok", resp
    assert destino.read_bytes() == etiqueta


def test_copies_repetem_o_fluxo(tmp_path):
    """Impressão crua: repetir o fluxo é o que gera mais de uma etiqueta."""
    destino = tmp_path / "etiqueta.zpl"
    etiqueta = b"^XA^FO50,50^FDTESTE^FS^XZ\n"

    resp = _via_compartilhamento(str(destino), "zpl", etiqueta, 3, "job2")

    assert resp["status"] == "ok", resp
    assert destino.read_bytes() == etiqueta * 3
    assert "3 cópias" in resp["message"]


def test_pdf_e_recusado_com_explicacao(tmp_path):
    """Uma fila crua não entende PDF — a mensagem precisa dizer isso."""
    resp = _via_compartilhamento(str(tmp_path / "x.pdf"), "pdf", b"%PDF-1.7", 1, "job3")

    assert resp["status"] == "error"
    assert "CRUS" in resp["detail"]
    assert "ZPL" in resp["detail"]


def test_destino_vazio_e_recusado():
    resp = _via_compartilhamento("", "zpl", b"^XA^XZ", 1, "job4")

    assert resp["status"] == "error"
    assert "não configurado" in resp["detail"]


def test_falha_traz_dica_de_conferencia(tmp_path):
    """Caminho inválido no Windows deve orientar o que verificar."""
    inexistente = str(tmp_path / "pasta_que_nao_existe" / "fila")

    resp = _via_compartilhamento(inexistente, "zpl", b"^XA^XZ", 1, "job6")

    assert resp["status"] == "error"
    assert "Falha ao enviar" in resp["detail"]


def test_send_print_job_usa_o_compartilhamento(tmp_path):
    """Caminho completo: send_print_job -> dispositivo tipo compartilhamento."""
    destino = tmp_path / "saida.zpl"
    dispositivo = DispositivoFalso()
    dispositivo.compartilhamento = str(destino)

    resp = send_print_job(
        layout={"largura_mm": 100, "altura_mm": 50, "dpi": 203, "elementos": []},
        formato="zpl",
        dispositivo=dispositivo,
    )

    assert resp["status"] == "ok", resp
    conteudo = destino.read_bytes()
    assert conteudo.startswith(b"^XA")
    assert conteudo.rstrip().endswith(b"^XZ")
    # Largura em dots = mm / 25,4 * dpi  →  100 mm a 203 dpi = 799 dots.
    largura_esperada = round(100 * 203 / 25.4)
    assert f"^PW{largura_esperada}".encode() in conteudo


def test_banco_aceita_o_tipo_compartilhamento(client, auth_headers):
    """O cadastro de dispositivo aceita exatamente \\\\DTAT7777\\SATO."""
    resp = client.post(
        "/api/v1/admin/dispositivos",
        json={
            "nome": "SATO do DTAT7777",
            "tipo": "compartilhamento",
            "compartilhamento": "\\\\DTAT7777\\SATO",
            "formato": "zpl",
            "padrao": True,
            "ativo": True,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    corpo = resp.json()
    assert corpo["tipo"] == "compartilhamento"
    assert corpo["compartilhamento"] == "\\\\DTAT7777\\SATO"

    # E o dispositivo aparece para o operador escolher na tela de impressão.
    lista = client.get("/api/v1/print/dispositivos", headers=auth_headers).json()
    assert any(d["nome"] == "SATO do DTAT7777" for d in lista)


# ---------------------------------------------------------------------------
# LINUX — a fila compartilhada é alcançada pelo smbclient
# ---------------------------------------------------------------------------
class TestFilaCompartilhadaNoLinux:
    """No Linux não existe caminho UNC: o envio é pelo `smbclient`.

    É o mesmo papel do `copy /b` no Windows, mas pelo protocolo de impressão
    (SPOOLSS). Requer o pacote de cliente Samba.
    """

    @pytest.mark.parametrize(
        "entrada,esperado",
        [
            ("\\\\DTAT7777\\SATO", ("DTAT7777", "SATO")),
            ("\\\\DTAT7777\\SATO\\", ("DTAT7777", "SATO")),
            ("//DTAT7777/SATO", ("DTAT7777", "SATO")),
            ("\\\\servidor\\fila com espaco", ("servidor", "fila com espaco")),
            ("\\\\servidor", None),
            ("impressora-local", None),
            ("", None),
        ],
    )
    def test_converte_unc_para_smb(self, entrada, esperado):
        assert _unc_para_smb(entrada) == esperado

    def test_sem_smbclient_explica_como_instalar(self, monkeypatch):
        _sem_janelas(monkeypatch)
        monkeypatch.setattr(print_service.shutil, "which", lambda _n: None)

        resp = _via_compartilhamento("\\\\DTAT7777\\SATO", "zpl", b"^XA^XZ", 1, "j1")

        assert resp["status"] == "error"
        assert "smbclient" in resp["detail"]
        assert "apt install" in resp["detail"]  # diz como resolver
        assert "cups" in resp["detail"].lower()  # e a alternativa

    def test_envia_os_bytes_e_os_argumentos_certos(self, monkeypatch, tmp_path):
        """Verifica a linha de comando E o conteúdo entregue ao smbclient."""
        capturado = {}

        def falso_run(cmd, **_kw):
            capturado["cmd"] = list(cmd)
            alvo = cmd[cmd.index("-c") + 1]          # print "<arquivo>"
            caminho = alvo.split('print "', 1)[1].rstrip('"')
            with open(caminho, "rb") as fh:
                capturado["dados"] = fh.read()
            return subprocess.CompletedProcess(cmd, 0, "ok", "")

        _sem_janelas(monkeypatch)
        monkeypatch.setattr(print_service.shutil, "which", lambda _n: "/usr/bin/smbclient")
        monkeypatch.setattr(print_service.subprocess, "run", falso_run)

        etiqueta = b"^XA^FO50,50^FDLINUX^FS^XZ\n"
        resp = _via_compartilhamento("\\\\DTAT7777\\SATO", "zpl", etiqueta, 2, "j2")

        assert resp["status"] == "ok", resp
        assert capturado["cmd"][0] == "/usr/bin/smbclient"
        assert capturado["cmd"][1] == "//DTAT7777/SATO"
        assert "-N" in capturado["cmd"]                 # sem credenciais
        assert capturado["dados"] == etiqueta * 2       # cópias repetem o fluxo

    def test_usa_credenciais_quando_configuradas(self, monkeypatch):
        capturado = {}

        def falso_run(cmd, **_kw):
            capturado["cmd"] = list(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        _sem_janelas(monkeypatch)
        monkeypatch.setattr(print_service.shutil, "which", lambda _n: "smbclient")
        monkeypatch.setattr(print_service.subprocess, "run", falso_run)
        monkeypatch.setattr(settings, "print_smb_usuario", "DOMINIO\\svc_impressao")
        monkeypatch.setattr(settings, "print_smb_senha", "segredo")

        resp = _via_compartilhamento("\\\\DTAT7777\\SATO", "zpl", b"^XA^XZ", 1, "j3")

        assert resp["status"] == "ok", resp
        assert "-U" in capturado["cmd"]
        assert "DOMINIO\\svc_impressao%segredo" in capturado["cmd"]
        assert "-N" not in capturado["cmd"]

    def test_erro_do_smbclient_aparece_na_mensagem(self, monkeypatch):
        def falso_run(cmd, **_kw):
            return subprocess.CompletedProcess(cmd, 1, "", "NT_STATUS_LOGON_FAILURE")

        _sem_janelas(monkeypatch)
        monkeypatch.setattr(print_service.shutil, "which", lambda _n: "smbclient")
        monkeypatch.setattr(print_service.subprocess, "run", falso_run)

        resp = _via_compartilhamento("\\\\DTAT7777\\SATO", "zpl", b"^XA^XZ", 1, "j4")

        assert resp["status"] == "error"
        assert "NT_STATUS_LOGON_FAILURE" in resp["detail"]
        assert "PRINT_SMB_USUARIO" in resp["detail"]  # orienta a conferir credencial

    def test_endereco_invalido_no_linux(self, monkeypatch):
        _sem_janelas(monkeypatch)
        resp = _via_compartilhamento("impressora-sem-unc", "zpl", b"^XA^XZ", 1, "j5")

        assert resp["status"] == "error"
        assert "inválido" in resp["detail"]

    def test_executa_um_smbclient_de_verdade(self, monkeypatch, tmp_path):
        """Integração: um executável real no PATH é encontrado e chamado."""
        if os.name == "nt":
            exe = tmp_path / "smbclient.bat"
            exe.write_text(
                "@echo off\r\n"
                f'echo %* > "{tmp_path / "args.txt"}"\r\n'
                "exit /b 0\r\n",
                encoding="utf-8",
            )
        else:
            exe = tmp_path / "smbclient"
            exe.write_text(
                "#!/bin/sh\n"
                f'echo "$@" > "{tmp_path / "args.txt"}"\n'
                "exit 0\n",
                encoding="utf-8",
            )
            exe.chmod(0o755)

        _sem_janelas(monkeypatch)
        monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))
        # `which` precisa enxergar o falso antes de qualquer smbclient real.
        monkeypatch.setattr(
            print_service.shutil,
            "which",
            lambda nome, *a, **k: str(exe) if nome == "smbclient" else None,
        )

        resp = _via_compartilhamento("\\\\DTAT7777\\SATO", "zpl", b"^XA^XZ", 1, "j6")

        assert resp["status"] == "ok", resp
        chamada = (tmp_path / "args.txt").read_text(encoding="utf-8", errors="replace")
        assert "//DTAT7777/SATO" in chamada
        assert "print" in chamada

    def test_mesma_configuracao_serve_nos_dois_sistemas(self, monkeypatch, tmp_path):
        """O MESMO cadastro (\\\\DTAT7777\\SATO) funciona no Windows e no Linux."""
        # Windows: grava no caminho UNC.
        destino = tmp_path / "unc.zpl"
        resp_win = _via_compartilhamento(str(destino), "zpl", b"^XA^XZ", 1, "w")
        assert resp_win["status"] == "ok"
        assert destino.read_bytes() == b"^XA^XZ"

        # Linux: usa o smbclient para o mesmo endereço lógico.
        chamado = {}

        def falso_run(cmd, **_kw):
            chamado["cmd"] = list(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        _sem_janelas(monkeypatch)
        monkeypatch.setattr(print_service.shutil, "which", lambda _n: "smbclient")
        monkeypatch.setattr(print_service.subprocess, "run", falso_run)

        resp_linux = _via_compartilhamento("\\\\DTAT7777\\SATO", "zpl", b"^XA^XZ", 1, "l")
        assert resp_linux["status"] == "ok"
        assert chamado["cmd"][1] == "//DTAT7777/SATO"
