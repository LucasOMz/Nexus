"""Envio de e-mail pelo SMTP configurado.

## Por que `smtplib`, e não um provedor

`smtplib` está na biblioteca padrão: nenhuma dependência nova, nenhuma
biblioteca de terceiro para auditar, e funciona com qualquer servidor —
Exchange da empresa, Gmail, Postfix do próprio servidor.

Um SDK de provedor (SendGrid, SES) resolveria o mesmo problema e criaria uma
dependência comercial no meio de um sistema que roda em rede interna.

## A regra que evita a pior falha

**Nunca engolir o erro de envio.** O chamador precisa saber se foi enviado,
para decidir entre registrar e tentar de novo. Um `except: pass` aqui viraria
"o sistema diz que avisou e ninguém recebeu" — a pior forma de falhar num
sistema de notificação.

## Sobre o TLS

Três modos, porque os servidores corporativos variam:

| Modo | Porta típica | O que faz |
|---|---|---|
| `tls` | 587 | conecta em claro, sobe para TLS com STARTTLS |
| `ssl` | 465 | TLS desde o primeiro byte |
| `nenhuma` | 25 | em claro — só aceitável em rede confiável |
"""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from sqlalchemy.orm import Session

from app.core import segredos
from app.models.notificacao import ConfiguracaoSMTP

# Curto de propósito: se o servidor de e-mail não responde em 15 segundos, a
# tentativa seguinte também não vai ajudar, e o agendador não pode ficar preso.
TIMEOUT = 15


class SMTPNaoConfigurado(RuntimeError):
    """Não há conta de envio configurada, ou ela está desligada."""


class FalhaEnvio(RuntimeError):
    """O servidor recusou, não respondeu, ou a credencial está errada."""


def configuracao(db: Session) -> ConfiguracaoSMTP | None:
    """A configuração de envio, se existir."""
    return db.query(ConfiguracaoSMTP).filter(ConfiguracaoSMTP.id == 1).first()


def pronto(db: Session) -> tuple[bool, str]:
    """Dá para enviar? Devolve o motivo quando não.

    A tela usa isto para explicar **por que** o botão de teste está apagado,
    em vez de deixar o administrador adivinhar qual campo falta.
    """
    cfg = configuracao(db)
    if cfg is None:
        return False, "SMTP ainda não configurado."
    if not cfg.ativo:
        return False, "O envio de e-mail está desligado."
    if not cfg.host:
        return False, "Falta o servidor (host)."
    if not cfg.remetente_email:
        return False, "Falta o e-mail do remetente."
    return True, ""


def _senha(cfg: ConfiguracaoSMTP) -> str | None:
    """Decifra a senha guardada.

    Sem a chave mestra, a senha é irrecuperável — é o mesmo contrato das
    licenças de software, e vale aqui pelo mesmo motivo: quem copia o banco
    não leva a credencial de e-mail junto.
    """
    if not cfg.senha_cifrada:
        return None
    try:
        return segredos.decifrar(cfg.senha_cifrada, cfg.senha_versao)
    except Exception as e:
        raise FalhaEnvio(
            "A senha do SMTP não pôde ser decifrada. A chave mestra mudou sem "
            f"rotação? ({type(e).__name__})"
        ) from e


def _montar(
    cfg: ConfiguracaoSMTP,
    destinatario: str,
    assunto: str,
    corpo_texto: str,
    corpo_html: str | None = None,
) -> EmailMessage:
    msg = EmailMessage()
    prefixo = (cfg.assunto_prefixo or "").strip()
    msg["Subject"] = f"{prefixo} {assunto}".strip() if prefixo else assunto
    msg["From"] = formataddr((cfg.remetente_nome or "Nexus", cfg.remetente_email))
    msg["To"] = destinatario
    if cfg.responder_para:
        msg["Reply-To"] = cfg.responder_para
    msg["Message-ID"] = make_msgid(domain=(cfg.remetente_email or "").split("@")[-1] or None)

    msg.set_content(corpo_texto)
    if corpo_html:
        msg.add_alternative(corpo_html, subtype="html")
    return msg


def enviar(
    db: Session,
    destinatario: str,
    assunto: str,
    corpo_texto: str,
    corpo_html: str | None = None,
) -> None:
    """Entrega a mensagem. Levanta `FalhaEnvio` com o motivo quando não dá.

    ## A ordem das exceções

    `SMTPAuthenticationError` antes de `SMTPException`: credencial errada é o
    erro mais comum e merece mensagem própria — o administrador precisa saber
    que o problema é a senha, e não a rede.
    """
    ok, motivo = pronto(db)
    if not ok:
        raise SMTPNaoConfigurado(motivo)

    cfg = configuracao(db)
    assert cfg is not None  # `pronto` já garantiu

    msg = _montar(cfg, destinatario, assunto, corpo_texto, corpo_html)

    try:
        if cfg.seguranca == "ssl":
            contexto = ssl.create_default_context()
            with smtplib.SMTP_SSL(cfg.host, cfg.porta, timeout=TIMEOUT, context=contexto) as s:
                if cfg.usuario:
                    s.login(cfg.usuario, _senha(cfg) or "")
                s.send_message(msg)
        else:
            with smtplib.SMTP(cfg.host, cfg.porta, timeout=TIMEOUT) as s:
                s.ehlo()
                if cfg.seguranca == "tls":
                    contexto = ssl.create_default_context()
                    s.starttls(context=contexto)
                    s.ehlo()
                if cfg.usuario:
                    s.login(cfg.usuario, _senha(cfg) or "")
                s.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise FalhaEnvio(
            "O servidor recusou o usuário ou a senha. "
            "Confira as credenciais e, se for Gmail/Outlook, a senha de aplicativo."
        ) from e
    except smtplib.SMTPRecipientsRefused as e:
        raise FalhaEnvio(f"O servidor recusou o destinatário {destinatario}.") from e
    except smtplib.SMTPSenderRefused as e:
        raise FalhaEnvio(
            "O servidor recusou o remetente. Ele costuma exigir que o remetente "
            "seja o mesmo usuário autenticado."
        ) from e
    except smtplib.SMTPConnectError as e:
        raise FalhaEnvio(
            f"Não foi possível conectar em {cfg.host}:{cfg.porta}. "
            "Porta bloqueada, ou serviço não está nesse endereço."
        ) from e
    except (TimeoutError, OSError) as e:
        raise FalhaEnvio(
            f"O servidor {cfg.host}:{cfg.porta} não respondeu em {TIMEOUT}s."
        ) from e
    except smtplib.SMTPException as e:
        raise FalhaEnvio(f"Falha no protocolo SMTP: {e}") from e


def testar(db: Session, destinatario: str) -> None:
    """Envia uma mensagem de teste. Usado pelo botão da tela de configuração.

    O texto é curto e explícito de propósito: quem recebe precisa entender que
    é um teste e que pode ignorar. Um "teste" genérico vira dúvida.
    """
    enviar(
        db,
        destinatario,
        "Teste de configuração de e-mail",
        "Este é um teste de configuração do Nexus.\n\n"
        "Se você recebeu esta mensagem, o envio de e-mail está funcionando.\n"
        "Nenhuma ação é necessária — pode ignorar.\n",
    )
