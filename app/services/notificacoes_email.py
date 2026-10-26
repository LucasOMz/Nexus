"""Notificações por e-mail — catálogo, coleta e despacho.

## Como isto se liga ao que já existe

O Nexus **já calculava** notificações para o sino (`routers/notificacoes.py`),
montando a lista na hora a partir dos dados. Este módulo faz o mesmo cálculo e
**entrega por e-mail** — em vez de duplicar a regra, reaproveita a mesma
consulta.

A diferença é que o sino mostra o que está acontecendo; o e-mail precisa
decidir **o que ainda não foi dito** — daí o histórico.

## O catálogo é a fonte da verdade

`CATALOGO` descreve cada aviso: nome, variáveis, texto padrão e frequência
sugerida. A tela de administração o lê para montar a lista de opções, para
mostrar as variáveis disponíveis e para saber o que o técnico pode escolher.

Acrescentar um aviso novo é acrescentar uma entrada aqui — **a tela se
atualiza sozinha**, sem lista paralela para manter em sincronia.

## As três decisões que fazem isto ser útil, e não spam

1. **Não repetir** — o mesmo aviso sobre o mesmo objeto não é reenviado no
   mesmo período (toner baixo é um estado contínuo, não um evento)
2. **Frequência por aviso** — devolução atrasada é diária; contrato vencendo
   é semanal
3. **Janela de horário** — e-mail às 3h não é lido; vira ruído e treina a
   pessoa a ignorar
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.models.contrato import Contrato
from app.models.core import Ativo, Transferencia, Usuario
from app.models.enums import StatusAtivo
from app.models.impressora import AtivoImpressora, SuprimentoImpressora
from app.models.notificacao import EmailEnviado, PreferenciaNotificacao, TemplateNotificacao
from app.services import email_service

log = logging.getLogger("app.notificacoes")

# Quantos dias antes do vencimento o aviso começa.
DIAS_DEVOLUCAO = 3
DIAS_CONTRATO = 30

FREQUENCIAS = ("imediata", "diaria", "semanal")

# Teto de e-mails por ciclo.
#
# ## Por que existe
#
# Na primeira execução com o SMTP ligado, **todos** os avisos acumulados
# disparam de uma vez. Na base atual há 8.827 suprimentos abaixo do mínimo —
# seriam 8.827 e-mails numa única rodada.
#
# O limite não é cosmético: além de inundar a caixa de entrada, servidores
# SMTP aplicam throttle e passam a **recusar** a conexão depois de algumas
# dezenas por minuto. O resultado seria uma pilha de falhas, e o sistema
# pareceria quebrado.
#
# O que passa do teto **não se perde**: fica sem registro em `emails_enviados`
# e é enviado nos ciclos seguintes.
MAXIMO_POR_CICLO = 50


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------
#
# Cada entrada:
#   nome        — como aparece na tela
#   descricao   — o que dispara, em uma frase
#   nivel       — "erro" | "urgente" | "info" (mesma escala do sino)
#   padrao      — frequência sugerida, escolhida por ser a que resolve o caso
#   variaveis   — os campos que o template pode usar
#   assunto     — texto padrão do assunto (aceita {{variavel}})
#   corpo       — texto padrão do corpo
#
CATALOGO: dict[str, dict] = {
    "emprestimo_atrasado": {
        "nome": "Devolução atrasada",
        "descricao": "Equipamento com data de devolução já vencida.",
        "nivel": "erro",
        "padrao": "diaria",
        "variaveis": ["patrimonio", "numero_serie", "modelo", "planta", "quem",
                      "chamado", "dias_atraso", "devolucao_prevista"],
        "assunto": "Devolução atrasada — {{patrimonio}}",
        "corpo": (
            "O equipamento {{patrimonio}} ({{modelo}}) está com devolução "
            "atrasada há {{dias_atraso}} dia(s).\n\n"
            "Planta: {{planta}}\n"
            "Com: {{quem}}\n"
            "Chamado: {{chamado}}\n"
            "Data prevista: {{devolucao_prevista}}\n"
        ),
    },
    "emprestimo_hoje": {
        "nome": "Devolução é hoje",
        "descricao": "O equipamento precisa voltar hoje.",
        "nivel": "urgente",
        "padrao": "imediata",
        "variaveis": ["patrimonio", "numero_serie", "modelo", "planta", "quem",
                      "chamado", "devolucao_prevista"],
        "assunto": "Devolução é hoje — {{patrimonio}}",
        "corpo": (
            "O equipamento {{patrimonio}} ({{modelo}}) precisa ser devolvido hoje.\n\n"
            "Planta: {{planta}}\n"
            "Com: {{quem}}\n"
            "Chamado: {{chamado}}\n"
        ),
    },
    "emprestimo_proximo": {
        "nome": "Devolução próxima",
        "descricao": "Faltam poucos dias para a devolução.",
        "nivel": "info",
        "padrao": "diaria",
        "variaveis": ["patrimonio", "numero_serie", "modelo", "planta", "quem",
                      "chamado", "dias_restantes", "devolucao_prevista"],
        "assunto": "Devolução em {{dias_restantes}} dia(s) — {{patrimonio}}",
        "corpo": (
            "O equipamento {{patrimonio}} ({{modelo}}) deve ser devolvido em "
            "{{dias_restantes}} dia(s).\n\n"
            "Planta: {{planta}}\n"
            "Com: {{quem}}\n"
            "Chamado: {{chamado}}\n"
            "Data prevista: {{devolucao_prevista}}\n"
        ),
    },
    "transferencia_pendente": {
        "nome": "Transferência aguardando aprovação",
        "descricao": "Há transferência de ativo esperando decisão.",
        "nivel": "urgente",
        "padrao": "diaria",
        "variaveis": ["patrimonio", "numero_serie", "modelo", "origem", "destino",
                      "solicitante", "motivo"],
        "assunto": "Transferência aguardando aprovação — {{patrimonio}}",
        "corpo": (
            "A transferência do equipamento {{patrimonio}} ({{modelo}}) está "
            "aguardando aprovação.\n\n"
            "Origem: {{origem}}\n"
            "Destino: {{destino}}\n"
            "Solicitante: {{solicitante}}\n"
            "Motivo: {{motivo}}\n"
        ),
    },
    "contrato_vencendo": {
        "nome": "Contrato perto do fim",
        "descricao": "Contrato de locação ou serviço vence em breve.",
        "nivel": "info",
        "padrao": "semanal",
        "variaveis": ["numero", "tipo", "fornecedor", "planta", "fim",
                      "dias_restantes", "valor_mensal"],
        "assunto": "Contrato {{numero}} vence em {{dias_restantes}} dia(s)",
        "corpo": (
            "O contrato {{numero}} ({{tipo}}) vence em {{dias_restantes}} dia(s).\n\n"
            "Fornecedor: {{fornecedor}}\n"
            "Planta: {{planta}}\n"
            "Fim: {{fim}}\n"
            "Valor mensal: {{valor_mensal}}\n"
        ),
    },
    "toner_baixo": {
        "nome": "Toner acabando",
        "descricao": "Suprimento de impressora no nível mínimo ou abaixo.",
        "nivel": "aviso",
        "padrao": "semanal",
        "variaveis": ["patrimonio", "modelo_impressora", "planta", "ip",
                      "suprimento", "cor", "estoque_atual", "estoque_minimo"],
        "assunto": "Toner acabando — {{patrimonio}} ({{suprimento}})",
        "corpo": (
            "A impressora {{patrimonio}} está com o suprimento abaixo do mínimo.\n\n"
            "Suprimento: {{suprimento}} {{cor}}\n"
            "Em estoque: {{estoque_atual}} (mínimo {{estoque_minimo}})\n"
            "Modelo: {{modelo_impressora}}\n"
            "Planta: {{planta}}\n"
            "IP: {{ip}}\n"
        ),
    },
}


# ---------------------------------------------------------------------------
# Evento
# ---------------------------------------------------------------------------
@dataclass
class Evento:
    """Um aviso concreto, pronto para ser entregue.

    `referencia` é o que torna o aviso único: o id do empréstimo, do contrato,
    do suprimento. Sem ela, "já avisei sobre atraso" bloquearia o **segundo**
    empréstimo atrasado da mesma pessoa.
    """

    chave: str
    referencia: str
    contexto: dict[str, str]
    planta_id: int | None = None
    usuario_id: int | None = None      # destinatário único, quando houver
    resumo: str = ""


def _texto_dias(dias: int) -> str:
    if dias == 0:
        return "hoje"
    if dias == 1:
        return "amanhã"
    return f"em {dias} dias"


def _moeda(valor) -> str:
    if valor is None:
        return "—"
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return str(valor)


# ---------------------------------------------------------------------------
# Coleta
# ---------------------------------------------------------------------------
def coletar(db: Session) -> list[Evento]:
    """Monta os avisos de agora, a partir do estado do banco.

    Não envia nada — só descreve o que **está acontecendo**. A separação
    importa: assim a tela de prévia consegue mostrar o que seria enviado sem
    enviar.
    """
    hoje = date.today()
    eventos: list[Evento] = []

    # --- empréstimos ------------------------------------------------------
    #
    # Mesma consulta do sino: `Ativo` com data de devolução dentro da janela.
    # O `em_uso` (retirado) entra também: a reserva ainda não saiu, mas já
    # tem data, e atraso de reserva também precisa ser avisado.
    consulta = (
        db.query(Ativo)
        .options(selectinload(Ativo.planta), selectinload(Ativo.emprestado_para))
        .filter(
            Ativo.deleted_at.is_(None),
            Ativo.devolucao_prevista.isnot(None),
            Ativo.devolucao_prevista <= hoje + timedelta(days=DIAS_DEVOLUCAO),
            Ativo.status.in_([StatusAtivo.EMPRESTADO, StatusAtivo.RESERVADO]),
        )
    )

    for a in consulta.order_by(Ativo.devolucao_prevista).all():
        dias = (a.devolucao_prevista - hoje).days
        comum = {
            "patrimonio": a.patrimonio or a.numero_serie or f"#{a.id}",
            "numero_serie": a.numero_serie or "—",
            "modelo": a.modelo or "sem modelo",
            "planta": a.planta_sigla or "—",
            "quem": a.emprestado_para_nome or "—",
            "chamado": a.numero_chamado or "sem chamado",
            "devolucao_prevista": a.devolucao_prevista.strftime("%d/%m/%Y"),
        }

        if dias < 0:
            eventos.append(Evento(
                chave="emprestimo_atrasado",
                referencia=str(a.id),
                contexto={**comum, "dias_atraso": str(abs(dias))},
                planta_id=a.planta_id,
                resumo=f"{comum['patrimonio']} atrasado {abs(dias)}d",
            ))
        elif dias == 0:
            eventos.append(Evento(
                chave="emprestimo_hoje",
                referencia=str(a.id),
                contexto=comum,
                planta_id=a.planta_id,
                resumo=f"{comum['patrimonio']} vence hoje",
            ))
        else:
            eventos.append(Evento(
                chave="emprestimo_proximo",
                referencia=str(a.id),
                contexto={**comum, "dias_restantes": str(dias)},
                planta_id=a.planta_id,
                resumo=f"{comum['patrimonio']} vence {_texto_dias(dias)}",
            ))

    # --- transferências pendentes ----------------------------------------
    pendentes = (
        db.query(Transferencia)
        .options(selectinload(Transferencia.ativo))
        .filter(
            Transferencia.deleted_at.is_(None),
            Transferencia.status == "aguardando_destino",
        )
        .all()
    )
    for t in pendentes:
        ativo = t.ativo
        if ativo is None:
            continue
        eventos.append(Evento(
            chave="transferencia_pendente",
            referencia=str(t.id),
            contexto={
                "patrimonio": ativo.patrimonio or ativo.numero_serie or f"#{ativo.id}",
                "numero_serie": ativo.numero_serie or "—",
                "modelo": ativo.modelo or "sem modelo",
                "origem": str(t.planta_origem_id or "—"),
                "destino": str(t.planta_destino_id or "—"),
                "solicitante": str(t.solicitado_por_id or "—"),
                "motivo": t.motivo_detalhe or t.motivo or "—",
            },
            planta_id=t.planta_destino_id,
            resumo=f"transferência #{t.id} pendente",
        ))

    # --- contratos --------------------------------------------------------
    limite = hoje + timedelta(days=DIAS_CONTRATO)
    contratos = (
        db.query(Contrato)
        .filter(
            Contrato.deleted_at.is_(None),
            Contrato.fim.isnot(None),
            Contrato.fim >= hoje,
            Contrato.fim <= limite,
        )
        .all()
    )
    for c in contratos:
        dias = (c.fim - hoje).days
        eventos.append(Evento(
            chave="contrato_vencendo",
            referencia=str(c.id),
            contexto={
                "numero": c.numero or f"#{c.id}",
                "tipo": str(c.tipo or "—"),
                "fornecedor": str(c.fornecedor_id or "—"),
                "planta": str(c.planta_id or "—"),
                "fim": c.fim.strftime("%d/%m/%Y"),
                "dias_restantes": str(dias),
                "valor_mensal": _moeda(c.valor_mensal),
            },
            planta_id=c.planta_id,
            resumo=f"contrato {c.numero} vence em {dias}d",
        ))

    # --- suprimentos de impressora ---------------------------------------
    suprimentos = (
        db.query(SuprimentoImpressora)
        .options(selectinload(SuprimentoImpressora.ativo))
        .filter(
            SuprimentoImpressora.deleted_at.is_(None),
            SuprimentoImpressora.estoque_minimo.isnot(None),
            SuprimentoImpressora.estoque_atual <= SuprimentoImpressora.estoque_minimo,
        )
        .all()
    )
    for s in suprimentos:
        ativo = s.ativo
        if ativo is None:
            continue
        ficha = db.get(AtivoImpressora, ativo.id)
        eventos.append(Evento(
            chave="toner_baixo",
            referencia=str(s.id),
            contexto={
                "patrimonio": ativo.patrimonio or ativo.numero_serie or f"#{ativo.id}",
                "modelo_impressora": ativo.modelo or "—",
                "planta": ativo.planta_sigla or "—",
                "ip": (ficha.ip if ficha else None) or "—",
                "suprimento": str(s.tipo or "suprimento"),
                "cor": s.cor or "",
                "estoque_atual": str(s.estoque_atual),
                "estoque_minimo": str(s.estoque_minimo),
            },
            planta_id=ativo.planta_id,
            resumo=f"toner baixo em {ativo.patrimonio}",
        ))

    return eventos


# ---------------------------------------------------------------------------
# Destinatários e preferências
# ---------------------------------------------------------------------------
def _usuarios_elegiveis(db: Session, evento: Evento) -> list[Usuario]:
    """Quem pode receber este aviso.

    Regra: usuário **ativo**, **com e-mail**, e — fora do administrador —
    **da mesma planta do evento**. Um aviso de outra unidade não é assunto
    dele, e mandar isso treina a pessoa a ignorar os avisos.

    A permissão de módulo **não** é checada aqui: quem decide receber é a
    preferência pessoal, e o aviso não expõe dado que o usuário já não veja
    na tela. Filtrar por módulo exigiria recalcular a matriz a cada aviso, e
    o ganho seria esconder o próprio objeto do trabalho.
    """
    q = db.query(Usuario).filter(
        Usuario.deleted_at.is_(None),
        Usuario.ativo.is_(True),
        Usuario.email.isnot(None),
        Usuario.email != "",
    )
    if evento.usuario_id is not None:
        q = q.filter(Usuario.id == evento.usuario_id)
    elif evento.planta_id is not None:
        q = q.filter(or_(
            Usuario.papel == "admin",
            Usuario.planta_id == evento.planta_id,
        ))
    return q.all()


def _preferencia(db: Session, usuario_id: int, chave: str) -> PreferenciaNotificacao | None:
    return (
        db.query(PreferenciaNotificacao)
        .filter(
            PreferenciaNotificacao.usuario_id == usuario_id,
            PreferenciaNotificacao.chave == chave,
        )
        .first()
    )


def _pode_enviar_agora(
    pref_ativo: bool,
    frequencia: str,
    hora: int,
    dias_semana: str | None,
    agora: datetime,
) -> bool:
    """A janela de frequência permite enviar neste ciclo?

    ## Por que a hora importa

    "Diária" não significa "a qualquer momento": significa **uma vez por dia,
    no horário que a pessoa escolheu**. Sem o horário, o resumo sairia quando
    o agendador rodasse — às 3h da manhã, para quem trabalha de dia.
    """
    if not pref_ativo or frequencia == "desligada":
        return False

    if frequencia == "imediata":
        return True

    if agora.hour != hora:
        return False

    if frequencia == "semanal":
        if not dias_semana:
            return agora.weekday() == 0      # sem escolha: segunda-feira
        try:
            dias = {int(d) for d in dias_semana.split(",") if d.strip()}
        except ValueError:
            dias = {1}
        # ISO: 1 = segunda. `weekday()` do Python: 0 = segunda.
        return (agora.weekday() + 1) in dias

    return True  # diaria


def _ja_enviado(
    db: Session,
    usuario_id: int,
    evento: Evento,
    frequencia: str,
    agora: datetime,
) -> bool:
    """O mesmo aviso já saiu dentro do período?

    A janela depende da frequência:

    | Frequência | Não repete por |
    |---|---|
    | imediata | para sempre (uma vez por objeto) |
    | diaria | 1 dia |
    | semanal | 7 dias |
    """
    q = db.query(EmailEnviado).filter(
        EmailEnviado.usuario_id == usuario_id,
        EmailEnviado.chave == evento.chave,
        EmailEnviado.referencia == evento.referencia,
        EmailEnviado.ok.is_(True),
    )

    if frequencia == "imediata":
        # Nunca repete: o objeto mudou de estado, então muda a referência.
        return db.query(q.exists()).scalar()

    janela = timedelta(days=1 if frequencia == "diaria" else 7)
    return db.query(q.filter(EmailEnviado.enviado_em >= agora - janela).exists()).scalar()


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------
def renderizar(texto: str, contexto: dict[str, str]) -> str:
    """Troca `{{variavel}}` pelo valor.

    Substituição literal, e não um motor de template. Um motor traria
    expressões, laços e acesso a atributos — e o texto é editado pelo
    administrador pela interface, então não pode ser código.

    Variável desconhecida vira `—` em vez de erro: o aviso ainda sai, com uma
    lacuna visível, o que é melhor que o aviso não sair nada.
    """
    if not texto:
        return ""
    saida = texto
    for chave, valor in contexto.items():
        saida = saida.replace("{{" + chave + "}}", str(valor))
    # Sobrou alguma? Marca para ficar óbvio na revisão do template.
    import re

    return re.sub(r"\{\{\s*\w+\s*\}\}", "—", saida)


def _template(db: Session, evento: Evento) -> tuple[str, str]:
    """Assunto e corpo: o personalizado, se existir; senão o do catálogo."""
    meta = CATALOGO.get(evento.chave, {})
    assunto = meta.get("assunto", "")
    corpo = meta.get("corpo", "")

    custom = db.query(TemplateNotificacao).filter(
        TemplateNotificacao.chave == evento.chave
    ).first()
    if custom is not None:
        assunto = custom.assunto or assunto
        corpo = custom.corpo or corpo

    return (
        renderizar(assunto, evento.contexto),
        renderizar(corpo, evento.contexto),
    )


# ---------------------------------------------------------------------------
# Despacho
# ---------------------------------------------------------------------------
@dataclass
class Resultado:
    enviados: int = 0
    pulados: int = 0
    falhas: int = 0
    detalhes: list[str] = field(default_factory=list)

    def como_dict(self) -> dict:
        return {
            "enviados": self.enviados,
            "pulados": self.pulados,
            "falhas": self.falhas,
            "detalhes": self.detalhes[:50],
        }


def despachar(db: Session, agora: datetime | None = None) -> Resultado:
    """Percorre os avisos e envia o que couber agora.

    ## A ordem das verificações importa

    1. SMTP configurado? — sem isso, não há o que fazer
    2. Janela de horário do sistema — e-mail fora dela espera
    3. Para cada evento, para cada destinatário: preferência → frequência →
       já enviado?

    A checagem de `já enviado` é a **última** de propósito: as anteriores são
    baratas (sem consulta pesada), e inverter a ordem faria o banco trabalhar
    para descobrir que o aviso estava desligado.
    """
    resultado = Resultado()
    agora = agora or datetime.now(timezone.utc)

    ok, motivo = email_service.pronto(db)
    if not ok:
        resultado.detalhes.append(f"SMTP indisponível: {motivo}")
        return resultado

    from app.models.notificacao import ConfiguracaoSMTP

    cfg = db.query(ConfiguracaoSMTP).filter(ConfiguracaoSMTP.id == 1).first()
    # Janela de horário do sistema. O agendador pode chamar a qualquer hora;
    # quem decide se é hora de incomodar é a configuração.
    if cfg is not None:
        hora_local = agora.hour
        inicio, fim = cfg.hora_inicio or 0, cfg.hora_fim or 23
        if inicio <= fim:
            dentro = inicio <= hora_local <= fim
        else:                                   # janela que vira o dia
            dentro = hora_local >= inicio or hora_local <= fim
        if not dentro:
            resultado.detalhes.append(
                f"Fora da janela de envio ({inicio}h–{fim}h)."
            )
            return resultado

    eventos = coletar(db)
    if not eventos:
        resultado.detalhes.append("Nenhum aviso no momento.")
        return resultado

    for evento in eventos:
        meta = CATALOGO.get(evento.chave)
        if meta is None:
            continue

        # Teto por ciclo: a primeira execução com SMTP ligado dispara tudo o
        # que estava acumulado. O que passa do limite não se perde — sem
        # registro em `emails_enviados`, volta no próximo ciclo.
        if resultado.enviados >= MAXIMO_POR_CICLO:
            resultado.detalhes.append(
                f"Teto de {MAXIMO_POR_CICLO} e-mails por ciclo atingido; "
                "o restante segue nos próximos ciclos."
            )
            break

        for usuario in _usuarios_elegiveis(db, evento):
            pref = _preferencia(db, usuario.id, evento.chave)

            # Sem preferência registrada, vale o padrão do catálogo: quem
            # nunca abriu a tela recebe o que é importante, e não silêncio.
            pref_ativo = pref.ativo if pref is not None else True
            frequencia = (pref.frequencia if pref is not None else meta["padrao"])
            hora = pref.hora if pref is not None else 8
            dias = pref.dias_semana if pref is not None else None

            if not _pode_enviar_agora(pref_ativo, frequencia, hora, dias, agora):
                resultado.pulados += 1
                continue

            if _ja_enviado(db, usuario.id, evento, frequencia, agora):
                resultado.pulados += 1
                continue

            assunto, corpo = _template(db, evento)

            try:
                email_service.enviar(db, usuario.email, assunto, corpo)
                db.add(EmailEnviado(
                    usuario_id=usuario.id,
                    chave=evento.chave,
                    referencia=evento.referencia,
                    destinatario=usuario.email,
                    assunto=assunto[:300],
                    resumo=evento.resumo or None,
                    enviado_em=agora,
                    ok=True,
                ))
                db.commit()
                resultado.enviados += 1
            except Exception as e:
                db.rollback()
                db.add(EmailEnviado(
                    usuario_id=usuario.id,
                    chave=evento.chave,
                    referencia=evento.referencia,
                    destinatario=usuario.email,
                    assunto=assunto[:300],
                    resumo=evento.resumo or None,
                    enviado_em=agora,
                    ok=False,
                    erro=str(e)[:2000],
                ))
                db.commit()
                resultado.falhas += 1
                resultado.detalhes.append(f"{usuario.email}: {e}")
                log.warning("Falha ao enviar para %s: %s", usuario.email, e)

    return resultado


def previa(db: Session, limite: int = 20) -> list[dict]:
    """O que seria enviado agora, por destinatário.

    A tela usa isto para o administrador **conferir o texto** antes de ligar o
    envio — ver o e-mail montado é diferente de confiar no template.
    """
    # A prévia não aplica janela de horário nem frequência: mostra tudo o que
    # existe agora, para o administrador conferir o texto. Quem filtra é o
    # despacho — aqui, filtrar esconderia justamente o que se quer revisar.
    saida: list[dict] = []
    for evento in coletar(db):
        for usuario in _usuarios_elegiveis(db, evento):
            if len(saida) >= limite:
                return saida
            assunto, corpo = _template(db, evento)
            saida.append({
                "chave": evento.chave,
                "destinatario": usuario.email,
                "nome": usuario.nome,
                "assunto": assunto,
                "corpo": corpo,
                "referencia": evento.referencia,
            })
    return saida
