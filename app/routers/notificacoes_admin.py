"""Notificações por e-mail — configuração e preferências.

## Quem pode o quê

| Rota | Quem |
|---|---|
| `smtp`, `templates`, `previa`, `enviar-agora`, `historico` | **administrador** |
| `preferencias` | **cada usuário** — só as suas |

A separação é de propósito. O técnico não configura o servidor de e-mail (é
um recurso de infraestrutura) nem edita o texto dos avisos (é comunicação da
empresa). Ele decide **o que recebe e com que frequência** — e é isso que
resolve o problema dele.

## O que a tela precisa, e por que está aqui

- **catálogo**: para montar a lista sem uma segunda lista no frontend
- **variáveis de cada aviso**: para o editor de template saber o que sugerir
- **prévia**: para o administrador **ver o e-mail montado** antes de ligar
- **histórico**: para provar o que saiu e diagnosticar falha
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core import segredos
from app.core.deps import get_current_user, require_admin
from app.database import get_db
from app.models.core import Usuario
from app.models.notificacao import (
    ConfiguracaoSMTP,
    EmailEnviado,
    PreferenciaNotificacao,
    TemplateNotificacao,
)
from app.services import email_service, notificacoes_email

router = APIRouter(prefix="/notificacoes-email", tags=["notificacoes-email"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class SMTPIn(BaseModel):
    ativo: bool = False
    host: str | None = None
    porta: int = Field(default=587, ge=1, le=65535)
    seguranca: str = Field(default="tls", pattern="^(tls|ssl|nenhuma)$")
    usuario: str | None = None
    # `None` = não mexer na senha guardada. String vazia = apagar.
    senha: str | None = None
    remetente_email: str | None = None
    remetente_nome: str = "Nexus"
    responder_para: str | None = None
    assunto_prefixo: str = "[Nexus]"
    hora_inicio: int = Field(default=7, ge=0, le=23)
    hora_fim: int = Field(default=19, ge=0, le=23)


class SMTPOut(BaseModel):
    ativo: bool
    host: str | None
    porta: int
    seguranca: str
    usuario: str | None
    tem_senha: bool
    remetente_email: str | None
    remetente_nome: str
    responder_para: str | None
    assunto_prefixo: str
    hora_inicio: int
    hora_fim: int
    pronto: bool
    motivo: str


class TesteIn(BaseModel):
    destinatario: str


class TemplateIn(BaseModel):
    assunto: str | None = None
    corpo: str | None = None


class PreferenciaIn(BaseModel):
    chave: str
    ativo: bool = True
    frequencia: str = Field(default="diaria", pattern="^(imediata|diaria|semanal|desligada)$")
    hora: int = Field(default=8, ge=0, le=23)
    dias_semana: str | None = None


class PreferenciasIn(BaseModel):
    itens: list[PreferenciaIn]
    # Só o administrador usa: configura as preferências de outro técnico.
    usuario_id: int | None = None


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------
@router.get("/catalogo")
def catalogo(_: Usuario = Depends(get_current_user)) -> dict:
    """Os avisos que existem, com as variáveis de cada um.

    Vem do `CATALOGO` do serviço — a mesma estrutura que o despacho usa. Não
    há lista paralela: acrescentar um aviso no serviço o faz aparecer aqui e
    na tela de preferências.
    """
    return {
        "itens": [
            {
                "chave": chave,
                "nome": meta["nome"],
                "descricao": meta["descricao"],
                "nivel": meta["nivel"],
                "frequencia_padrao": meta["padrao"],
                "variaveis": meta["variaveis"],
                "assunto_padrao": meta["assunto"],
                "corpo_padrao": meta["corpo"],
            }
            for chave, meta in notificacoes_email.CATALOGO.items()
        ],
        "frequencias": [
            {"valor": "imediata", "rotulo": "Imediata", "ajuda": "Assim que o fato acontece."},
            {"valor": "diaria", "rotulo": "Diária", "ajuda": "Um resumo por dia, no horário escolhido."},
            {"valor": "semanal", "rotulo": "Semanal", "ajuda": "Um resumo por semana, nos dias escolhidos."},
            {"valor": "desligada", "rotulo": "Desligada", "ajuda": "Não receber este aviso."},
        ],
    }


# ---------------------------------------------------------------------------
# SMTP (administrador)
# ---------------------------------------------------------------------------
def _config_ou_404(db: Session) -> ConfiguracaoSMTP:
    cfg = email_service.configuracao(db)
    if cfg is None:
        raise HTTPException(404, "SMTP não configurado.")
    return cfg


@router.get("/smtp", response_model=SMTPOut)
def obter_smtp(db: Session = Depends(get_db), _: Usuario = Depends(require_admin)) -> SMTPOut:
    """A configuração atual.

    A senha **nunca** volta — só o booleano `tem_senha`. Devolver o valor
    cifrado daria a quem lê a resposta uma cópia para quebrar offline.
    """
    cfg = email_service.configuracao(db)
    ok, motivo = email_service.pronto(db)

    if cfg is None:
        return SMTPOut(
            ativo=False, host=None, porta=587, seguranca="tls", usuario=None,
            tem_senha=False, remetente_email=None, remetente_nome="Nexus",
            responder_para=None, assunto_prefixo="[Nexus]", hora_inicio=7,
            hora_fim=19, pronto=False, motivo=motivo,
        )

    return SMTPOut(
        ativo=cfg.ativo,
        host=cfg.host,
        porta=cfg.porta,
        seguranca=cfg.seguranca,
        usuario=cfg.usuario,
        tem_senha=bool(cfg.senha_cifrada),
        remetente_email=cfg.remetente_email,
        remetente_nome=cfg.remetente_nome or "Nexus",
        responder_para=cfg.responder_para,
        assunto_prefixo=cfg.assunto_prefixo or "",
        hora_inicio=cfg.hora_inicio,
        hora_fim=cfg.hora_fim,
        pronto=ok,
        motivo=motivo,
    )


@router.put("/smtp", response_model=SMTPOut)
def salvar_smtp(
    body: SMTPIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
) -> SMTPOut:
    """Grava a configuração.

    ## A senha tem três estados

    - **ausente** (`None`) — mantém a guardada
    - **vazia** (`""`) — apaga
    - **com valor** — substitui, cifrada

    Sem essa distinção, abrir a tela e salvar apagaria a senha — porque ela
    nunca é enviada de volta ao navegador.
    """
    cfg = email_service.configuracao(db)
    if cfg is None:
        cfg = ConfiguracaoSMTP(id=1)
        db.add(cfg)

    cfg.ativo = body.ativo
    cfg.host = (body.host or "").strip() or None
    cfg.porta = body.porta
    cfg.seguranca = body.seguranca
    cfg.usuario = (body.usuario or "").strip() or None
    cfg.remetente_email = (body.remetente_email or "").strip() or None
    cfg.remetente_nome = (body.remetente_nome or "Nexus").strip()
    cfg.responder_para = (body.responder_para or "").strip() or None
    cfg.assunto_prefixo = (body.assunto_prefixo or "").strip()
    cfg.hora_inicio = body.hora_inicio
    cfg.hora_fim = body.hora_fim
    cfg.atualizado_em = datetime.now()
    cfg.atualizado_por_id = user.id

    if body.senha is not None:
        if body.senha == "":
            cfg.senha_cifrada = None
            cfg.senha_versao = None
        else:
            try:
                segredo = segredos.cifrar(body.senha)
            except segredos.ChaveMestraAusente as e:
                raise HTTPException(
                    400,
                    "A chave mestra não está configurada (NEXUS_CHAVE_LICENCAS). "
                    "Sem ela a senha não pode ser guardada com segurança.",
                ) from e
            if segredo is not None:
                cfg.senha_cifrada = segredo.cifrado
                cfg.senha_versao = segredo.versao

    db.commit()
    db.refresh(cfg)
    return obter_smtp(db, user)


@router.post("/smtp/testar")
def testar_smtp(
    body: TesteIn,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
) -> dict:
    """Envia uma mensagem de teste para o endereço informado.

    O erro volta com a mensagem do serviço, e não como 500: quem está
    configurando precisa saber **o que** falhou — credencial, porta ou DNS.
    """
    destinatario = (body.destinatario or "").strip()
    if not destinatario or "@" not in destinatario:
        raise HTTPException(400, "Informe um e-mail válido para o teste.")

    try:
        email_service.testar(db, destinatario)
    except email_service.SMTPNaoConfigurado as e:
        raise HTTPException(400, str(e)) from e
    except email_service.FalhaEnvio as e:
        raise HTTPException(400, str(e)) from e

    return {"ok": True, "mensagem": f"Teste enviado para {destinatario}."}


# ---------------------------------------------------------------------------
# Templates (administrador)
# ---------------------------------------------------------------------------
@router.get("/templates")
def listar_templates(
    db: Session = Depends(get_db), _: Usuario = Depends(require_admin)
) -> dict:
    """Assunto e corpo efetivos de cada aviso — personalizado ou padrão."""
    custom = {t.chave: t for t in db.query(TemplateNotificacao).all()}
    itens = []
    for chave, meta in notificacoes_email.CATALOGO.items():
        t = custom.get(chave)
        itens.append({
            "chave": chave,
            "nome": meta["nome"],
            "variaveis": meta["variaveis"],
            "assunto": (t.assunto if t and t.assunto else meta["assunto"]),
            "corpo": (t.corpo if t and t.corpo else meta["corpo"]),
            "personalizado": t is not None,
            "assunto_padrao": meta["assunto"],
            "corpo_padrao": meta["corpo"],
        })
    return {"itens": itens}


@router.put("/templates/{chave}")
def salvar_template(
    chave: str,
    body: TemplateIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
) -> dict:
    """Grava o texto de um aviso. Enviar `null` volta ao padrão.

    Voltar ao padrão é uma operação, e não um efeito colateral: sem ela, um
    template mal editado não teria como ser recuperado sem lembrar o texto
    original.
    """
    if chave not in notificacoes_email.CATALOGO:
        raise HTTPException(404, f"Aviso desconhecido: {chave}")

    t = db.query(TemplateNotificacao).filter(TemplateNotificacao.chave == chave).first()

    if body.assunto is None and body.corpo is None:
        if t is not None:
            db.delete(t)
            db.commit()
        return {"ok": True, "restaurado": True}

    if t is None:
        t = TemplateNotificacao(chave=chave)
        db.add(t)

    t.assunto = body.assunto
    t.corpo = body.corpo
    t.atualizado_em = datetime.now()
    t.atualizado_por_id = user.id
    db.commit()
    return {"ok": True, "restaurado": False}


# ---------------------------------------------------------------------------
# Preferências (cada usuário)
# ---------------------------------------------------------------------------
@router.get("/preferencias")
def minhas_preferencias(
    usuario_id: int | None = Query(default=None, description="admin escolhe o tecnico"),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> dict:
    """As preferências de um técnico, uma entrada por aviso.

    ## Por que o administrador escolhe o usuário

    A tela vive na Administração, que é área restrita. Se esta rota só
    devolvesse as preferências de quem chamou, o administrador configuraria
    apenas as próprias — e o técnico, que é quem recebe os avisos, ficaria
    sem nenhuma.

    **Um usuário comum só vê as suas**: pedir o id de outro devolve a própria
    lista, em vez de erro. Um 403 confirmaria que o id existe.

    Aviso sem preferência registrada aparece com o **padrão do catálogo** —
    assim a tela mostra exatamente o que o despacho fará, em vez de exibir
    "desligado" para algo que ainda será enviado.
    """
    alvo = user
    if usuario_id is not None and usuario_id != user.id and user.papel == "admin":
        outro = db.get(Usuario, usuario_id)
        if outro is not None and outro.deleted_at is None:
            alvo = outro

    minhas = {
        p.chave: p
        for p in db.query(PreferenciaNotificacao)
        .filter(PreferenciaNotificacao.usuario_id == alvo.id)
        .all()
    }

    itens = []
    for chave, meta in notificacoes_email.CATALOGO.items():
        p = minhas.get(chave)
        itens.append({
            "chave": chave,
            "nome": meta["nome"],
            "descricao": meta["descricao"],
            "nivel": meta["nivel"],
            "ativo": p.ativo if p is not None else True,
            "frequencia": p.frequencia if p is not None else meta["padrao"],
            "hora": p.hora if p is not None else 8,
            "dias_semana": p.dias_semana if p is not None else None,
            "personalizado": p is not None,
        })

    return {
        "usuario_id": alvo.id,
        "usuario_nome": alvo.nome,
        "email": alvo.email,
        "tem_email": bool(alvo.email),
        "itens": itens,
    }


@router.put("/preferencias")
def salvar_preferencias(
    body: PreferenciasIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> dict:
    """Grava preferências.

    ## Quem pode o quê

    - **administrador**: grava para o `usuario_id` do corpo (qualquer técnico)
    - **usuário comum**: grava só as suas — o `usuario_id` do corpo é ignorado

    A distinção é no servidor, e não na tela. Esconder o campo não impede uma
    chamada direta à API, e aqui o efeito seria desligar o aviso de outra
    pessoa.
    """
    alvo_id = user.id
    if body.usuario_id is not None and body.usuario_id != user.id and user.papel == "admin":
        outro = db.get(Usuario, body.usuario_id)
        if outro is None or outro.deleted_at is not None:
            raise HTTPException(404, "Usuário não encontrado.")
        alvo_id = outro.id

    existentes = {
        p.chave: p
        for p in db.query(PreferenciaNotificacao)
        .filter(PreferenciaNotificacao.usuario_id == alvo_id)
        .all()
    }

    gravados = 0
    for item in body.itens:
        if item.chave not in notificacoes_email.CATALOGO:
            continue
        p = existentes.get(item.chave)
        if p is None:
            p = PreferenciaNotificacao(usuario_id=alvo_id, chave=item.chave)
            db.add(p)
        p.ativo = item.ativo
        p.frequencia = item.frequencia
        p.hora = item.hora
        p.dias_semana = item.dias_semana
        p.atualizado_em = datetime.now()
        gravados += 1

    db.commit()
    return {"ok": True, "gravados": gravados, "usuario_id": alvo_id}


# ---------------------------------------------------------------------------
# Prévia, envio e histórico (administrador)
# ---------------------------------------------------------------------------
@router.get("/previa")
def previa(
    limite: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
) -> dict:
    """O que seria enviado agora — sem enviar.

    É o teste que não incomoda ninguém: o administrador confere o texto, as
    variáveis substituídas e os destinatários antes de ligar o envio.
    """
    itens = notificacoes_email.previa(db, limite)
    return {"total": len(itens), "itens": itens}


@router.post("/enviar-agora")
def enviar_agora(
    db: Session = Depends(get_db), _: Usuario = Depends(require_admin)
) -> dict:
    """Roda o despacho neste instante, ignorando o agendador.

    Existe para conferir a configuração sem esperar o próximo ciclo — e para
    o caso em que o agendador está parado.
    """
    resultado = notificacoes_email.despachar(db)
    return resultado.como_dict()


@router.get("/historico")
def historico(
    limite: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
) -> dict:
    """Os últimos envios, com o motivo de quem falhou."""
    linhas = (
        db.query(EmailEnviado, Usuario)
        .outerjoin(Usuario, Usuario.id == EmailEnviado.usuario_id)
        .order_by(EmailEnviado.enviado_em.desc())
        .limit(limite)
        .all()
    )
    return {
        "itens": [
            {
                "id": e.id,
                "destinatario": e.destinatario,
                "nome": u.nome if u is not None else None,
                "chave": e.chave,
                "referencia": e.referencia,
                "assunto": e.assunto,
                "resumo": e.resumo,
                "enviado_em": e.enviado_em.isoformat() if e.enviado_em else None,
                "ok": e.ok,
                "erro": e.erro,
            }
            for e, u in linhas
        ]
    }
