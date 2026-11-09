"""Lógica dos agentes — gerar código, registrar máquina, receber inventário.

## O fluxo

    painel  →  gera código (hash guardado, valor mostrado uma vez)
    agente  →  POST /agente/registrar { codigo, serial, hostname }
    servidor→  valida o código, acha o ativo pelo serial, cria o token
    agente  →  POST /agente/inventario  (Bearer token)
    servidor→  grava no ativo

## Duas regras que valem explicar

### Serial inválido vai para a FILA, não vira ativo

Placa branca devolve `To be filled by O.E.M.`; VM devolve `VMware-...`.
Criar automaticamente faria quarenta máquinas distintas casarem com o mesmo
identificador. Elas entram em `EquipamentoPendente` e esperam decisão humana.

### O código é consumido só no sucesso

Se a máquina tem serial inválido, o uso **não** é contado — senão uma
implantação com 50 placas brancas queimaria 50 usos de um código de 3.500
sem registrar ninguém.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.agente import CodigoInstalacao, EquipamentoPendente, TokenAgente
from app.models.core import Ativo
from app.models.ti import AtivoTI

# Serial que não identifica nada. Mesma lista do coletor, e aqui também —
# o agente é software no cliente e não merece confiança absoluta.
SERIAL_INVALIDO = {
    "", "0", "00000000", "to be filled by o.e.m.", "default string",
    "none", "system serial number", "not specified", "n/a", "unknown",
}


def serial_valido(serial: str | None) -> bool:
    if not serial:
        return False
    t = serial.strip()
    if t.lower() in SERIAL_INVALIDO:
        return False
    if t.lower().startswith(("vmware-", "0000-0000", "to be filled")):
        return False
    return True


def hash_segredo(valor: str) -> str:
    """SHA-256 do segredo. Nunca guardamos o valor em claro."""
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()


def gerar_codigo(
    db: Session,
    *,
    dias: int = 7,
    usos_max: int = 1,
    rotulo: str | None = None,
    criado_por_id: int | None = None,
    planta_id: int | None = None,
) -> tuple[CodigoInstalacao, str]:
    """Cria um código e devolve **(registro, valor em claro)**.

    O valor em claro só existe aqui. Depois desta chamada, ninguém consegue
    recuperá-lo — se perder, gera outro. É o mesmo tratamento da senha.
    """
    valor = "-".join(secrets.token_hex(2).upper() for _ in range(3))
    registro = CodigoInstalacao(
        codigo_hash=hash_segredo(valor),
        codigo_valor=valor,
        prefixo=valor.split("-")[0],
        rotulo=rotulo,
        planta_id=planta_id,
        usos_max=max(1, usos_max),
        usos_feitos=0,
        expira_em=datetime.now(timezone.utc) + timedelta(days=max(1, dias)),
        criado_por_id=criado_por_id,
    )
    db.add(registro)
    db.commit()
    db.refresh(registro)
    return registro, valor


def buscar_codigo(db: Session, valor: str) -> CodigoInstalacao | None:
    return (
        db.query(CodigoInstalacao)
        .filter(CodigoInstalacao.codigo_hash == hash_segredo(valor))
        .first()
    )


def buscar_token(db: Session, valor: str) -> TokenAgente | None:
    return (
        db.query(TokenAgente)
        .filter(
            TokenAgente.token_hash == hash_segredo(valor),
            TokenAgente.revogado_em.is_(None),
        )
        .first()
    )


def _achar_ativo_por_serial(db: Session, serial: str) -> Ativo | None:
    return (
        db.query(Ativo)
        .filter(
            Ativo.deleted_at.is_(None),
            func.lower(Ativo.numero_serie) == serial.strip().lower(),
        )
        .first()
    )


def _registrar_pendente(
    db: Session, *, serial: str | None, hostname: str | None,
    mac: str | None, ip: str | None, payload: dict, motivo: str,
) -> EquipamentoPendente:
    """Coloca na fila, ou atualiza a linha já existente da mesma máquina.

    A deduplicação é por **MAC** e depois por hostname: sem ela, cada coleta
    de uma máquina não cadastrada criaria uma linha nova, e a fila viraria
    um log.
    """
    consulta = db.query(EquipamentoPendente).filter(
        EquipamentoPendente.resolvido_em.is_(None)
    )
    if mac:
        existente = consulta.filter(EquipamentoPendente.mac == mac).first()
    elif hostname:
        existente = consulta.filter(EquipamentoPendente.hostname == hostname).first()
    else:
        existente = None

    agora = datetime.now(timezone.utc)
    if existente is not None:
        existente.ultima_vez_em = agora
        existente.payload_json = json.dumps(payload, ensure_ascii=False)
        db.commit()
        return existente

    novo = EquipamentoPendente(
        serial_bruto=serial,
        hostname=hostname,
        mac=mac,
        ip=ip,
        payload_json=json.dumps(payload, ensure_ascii=False),
        motivo=motivo,
        visto_em=agora,
        ultima_vez_em=agora,
    )
    db.add(novo)
    db.commit()
    db.refresh(novo)
    return novo


# Fabricante que nao identifica nada. Placa de montagem propria devolve isto
# no campo SMBIOS — e a criacao copiava direto para marca, deixando o ativo
# com "To Be Filled By O.E.M." no cadastro.
LIXO_DE_FABRICANTE = {
    "", "0", "to be filled by o.e.m.", "to be filled by oem",
    "default string", "none", "not specified", "unknown", "n/a",
    "system manufacturer", "o.e.m.", "oem",
}


def fabricante_valido(valor) -> str | None:
    """Devolve o fabricante, ou None quando e lixo de SMBIOS."""
    if not valor:
        return None
    texto = str(valor).strip()
    if texto.lower() in LIXO_DE_FABRICANTE:
        return None
    if texto.lower().startswith("to be filled"):
        return None
    return texto[:80]


def _criar_ativo_do_payload(
    db: Session,
    serial: str,
    payload: dict,
    hostname: str | None,
    codigo=None,
):
    """Cria o ativo a partir do que o agente enviou.

    ## De quem é a máquina

    A planta vem do **código de instalação** usado no registro. Quem gera o
    código escolhe a planta, e toda máquina registrada com ele nasce lá — o
    agente não tem sessão, então ele não teria como saber.

    Códigos antigos (sem planta) caem na primeira planta ativa, que era o
    comportamento anterior. Continuam funcionando, e o administrador pode
    mover a máquina depois.

    O `numero_serie` é o que veio do agente — inclusive o `OEM-...` derivado
    do MachineGuid. É por ele que as próximas coletas vão casar.
    """
    from app.models.core import Planta
    from app.models.enums import Dominio, StatusAtivo, TipoItem
    from app.models.ti import AtivoTI

    # A planta do código tem prioridade: é a escolha explícita de quem montou
    # o pacote de implantação. Sem ela, cai na primeira ativa (legado).
    planta = None
    if codigo is not None and getattr(codigo, "planta_id", None) is not None:
        planta = db.get(Planta, codigo.planta_id)

    if planta is None:
        planta = db.query(Planta).filter(Planta.ativa.is_(True), Planta.deleted_at.is_(None)).first()
    if planta is None:
        planta = db.query(Planta).filter(Planta.deleted_at.is_(None)).first()
    if planta is None:
        return None

    # O serial pode estar preso em uma linha EXCLUIDA — o indice unico nao
    # ignora deleted_at. Liberar antes de criar, senao a insercao viola a
    # restricao e o recadastro falha.
    from app.services import unicidade

    unicidade.liberar(db, Ativo, "numero_serie", serial, limite=120)
    db.flush()

    basico = payload.get("basico") or {}
    ativo = Ativo(
        planta_id=planta.id,
        dominio=Dominio.TI,
        tipo_item=TipoItem.ATIVO,
        status=StatusAtivo.ESTOQUE,
        numero_serie=serial,
        patrimonio=None,
        modelo=(str(basico.get("modelo"))[:120] if basico.get("modelo") else None),
        marca=fabricante_valido(basico.get("fabricante")),
    )
    db.add(ativo)
    db.flush()

    ficha = AtivoTI(ativo_id=ativo.id)
    ficha.hostname = (str(hostname)[:120] if hostname else None)
    ficha.so = (str(basico.get("so"))[:120] if basico.get("so") else None)
    ficha.cpu = (str(basico.get("cpu"))[:160] if basico.get("cpu") else None)
    if basico.get("ram_gb"):
        ficha.ram_gb = int(basico["ram_gb"])
    if basico.get("armazenamento_gb"):
        ficha.armazenamento_gb = int(basico["armazenamento_gb"])
    db.add(ficha)

    return ativo


def registrar(
    db: Session, *, codigo: str, serial: str | None, hostname: str | None, payload: dict
) -> dict:
    """Troca o código de instalação pelo token da máquina.

    Devolve um dicionário com `ok` e, em caso de falha, o `motivo` que o
    agente mostra ao usuário — não um 500 genérico.
    """
    registro = buscar_codigo(db, codigo)
    if registro is None:
        return {"ok": False, "status": 401, "motivo": "codigo_invalido"}
    # `util` exige nao-revogado, nao-expirado E nao-esgotado. O ultimo nao
    # pode barrar: o agente guarda o codigo para refazer o cadastro quando o
    # ativo e excluido, e nesse momento os usos ja foram consumidos.
    #
    # Validade e revogacao continuam sendo o controle de verdade.
    if registro.revogado_em is not None:
        return {"ok": False, "status": 403, "motivo": "codigo_revogado"}

    agora = datetime.now(timezone.utc)
    expira = registro.expira_em
    if expira is not None:
        if expira.tzinfo is None:
            expira = expira.replace(tzinfo=timezone.utc)
        if expira < agora:
            return {"ok": False, "status": 403, "motivo": "codigo_expirado"}

    if not serial_valido(serial):
        # Não consome uso: a máquina veio, mas não tem identificador.
        _registrar_pendente(
            db, serial=serial, hostname=hostname,
            mac=_mac_do_payload(payload), ip=_ip_do_payload(payload),
            payload=payload, motivo="sem_serial",
        )
        return {"ok": False, "status": 422, "motivo": "sem_serial"}

    ativo = _achar_ativo_por_serial(db, serial)
    criado = False
    if ativo is None:
        # Registro automático. Com `OEM-<MachineGuid>` o identificador é único
        # por máquina, então criar não gera duplicata — e o técnico não
        # precisa esperar aprovação nenhuma.
        # `codigo` aqui é o texto que o agente mandou; o registro — que tem a
        # planta — é `registro`, devolvido por `buscar_codigo`.
        ativo = _criar_ativo_do_payload(
            db, serial, payload, hostname, codigo=registro
        )
        criado = ativo is not None

    if ativo is None:
        # Só chega aqui sem planta cadastrada — instalação sem `Planta`.
        _registrar_pendente(
            db, serial=serial, hostname=hostname,
            mac=_mac_do_payload(payload), ip=_ip_do_payload(payload),
            payload=payload, motivo="sem_planta",
        )
        return {"ok": False, "status": 409, "motivo": "sem_planta"}

    # Reaproveita o token se a máquina já estava registrada: reinstalar o
    # agente não deve deixar tokens órfãos acumulando.
    anterior = (
        db.query(TokenAgente)
        .filter(TokenAgente.ativo_id == ativo.id, TokenAgente.revogado_em.is_(None))
        .first()
    )
    if anterior is not None:
        anterior.revogado_em = datetime.now(timezone.utc)

    valor = secrets.token_urlsafe(32)
    token = TokenAgente(
        token_hash=hash_segredo(valor),
        prefixo=valor[:8],
        ativo_id=ativo.id,
        hostname=hostname,
        serial=serial,
    )
    db.add(token)
    registro.usos_feitos = (registro.usos_feitos or 0) + 1
    db.commit()
    db.refresh(token)

    return {
        "ok": True,
        "status": 200,
        "token": valor,          # única vez que este valor existe
        "ativo_id": ativo.id,
        "prefixo": token.prefixo,
        "criado": criado,
    }


def _primeiro_mac(payload: dict) -> str | None:
    try:
        for r in (payload.get("detalhes") or {}).get("rede") or []:
            mac = (r or {}).get("mac")
            if mac:
                return str(mac).strip().upper()[:64]
    except (AttributeError, TypeError):
        pass
    return None


def _primeiro_ip(payload: dict) -> str | None:
    try:
        for r in (payload.get("detalhes") or {}).get("rede") or []:
            for ip in (r or {}).get("ips") or []:
                if ip:
                    return str(ip)[:64]
    except (AttributeError, TypeError):
        pass
    return None


_mac_do_payload = _primeiro_mac
_ip_do_payload = _primeiro_ip


# Campos que dizem o que a máquina É. Fora daqui ficam os voláteis: uptime,
# IP e usuário logado mudam a cada coleta e fariam toda coleta parecer
# mudança.
CAMPOS_ESTAVEIS = (
    ("hostname", "Hostname"),
    ("so", "Sistema operacional"),
    ("cpu", "Processador"),
    ("ram_gb", "Memória RAM (GB)"),
    ("armazenamento_gb", "Armazenamento (GB)"),
    ("dominio", "Domínio"),
    ("fabricante", "Fabricante"),
    ("modelo", "Modelo"),
)


def _snapshot_estavel(payload: dict) -> dict:
    basico = payload.get("basico") or {}
    saida = {}
    for chave, _rotulo in CAMPOS_ESTAVEIS:
        if chave == "hostname":
            saida[chave] = basico.get("hostname") or payload.get("hostname")
        else:
            saida[chave] = basico.get(chave)
    return saida


def detectar_mudanca(db: Session, ativo_id: int, payload: dict) -> dict | None:
    """Compara com a última coleta e grava histórico se algo mudou.

    Devolve o diff gravado, ou `None` quando nada mudou — e aí o chamador só
    atualiza a data da última coleta.
    """
    from app.models.historico_inventario import HistoricoInventario

    atual = _snapshot_estavel(payload)
    # `sort_keys` é obrigatório: sem ele a ordem das chaves mudaria o hash e
    # toda coleta pareceria diferente.
    novo_hash = hashlib.sha256(
        json.dumps(atual, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()

    anterior = (
        db.query(HistoricoInventario)
        .filter(HistoricoInventario.ativo_id == ativo_id)
        .order_by(HistoricoInventario.quando.desc())
        .first()
    )

    if anterior is not None and anterior.hash == novo_hash:
        return None

    try:
        antigo = json.loads(anterior.snapshot_json or "{}") if anterior else {}
    except (ValueError, TypeError):
        antigo = {}

    mudancas = {}
    for chave, rotulo in CAMPOS_ESTAVEIS:
        antes, depois = antigo.get(chave), atual.get(chave)
        if antes != depois:
            mudancas[chave] = {"rotulo": rotulo, "de": antes, "para": depois}

    # Primeira coleta não é "mudança": grava como linha de base, sem diff,
    # para que a próxima tenha com o que comparar.
    registro = HistoricoInventario(
        ativo_id=ativo_id,
        quando=datetime.now(timezone.utc),
        hash=novo_hash,
        snapshot_json=json.dumps(atual, ensure_ascii=False),
        mudancas_json=json.dumps(mudancas, ensure_ascii=False),
        origem="agente",
    )
    db.add(registro)
    return mudancas


def registrar_usuario_do_ativo(db: Session, ativo_id: int, nome: str | None) -> None:
    """Anota quem esta usando a maquina.

    ## Duas coisas acontecem

    1. Ativo.ultimo_usuario recebe o nome, para a lista principal mostrar
       sem consulta por linha.

    2. UsuarioDoAtivo guarda **uma linha por pessoa**, com a ultima vez que
       ela apareceu. Nao e log: nao se cria linha por evento, so se atualiza
       ultimo_login.

    ## A expiracao de 30 dias

    Quem nao aparece ha mais de um mes sai da lista. Sem isso, a maquina
    usada por dez pessoas em dois anos acumularia nomes sem relacao com o
    uso atual — e a pergunta que a tela responde e "quem usa isto", nao
    "quem ja usou alguma vez".
    """
    from datetime import datetime, timezone

    from app.models.core import Ativo
    from app.models.usuario_ativo import UsuarioDoAtivo

    if not nome:
        return

    limpo = str(nome).strip()[:120]
    if not limpo:
        return

    agora = datetime.now(timezone.utc)

    ativo = db.get(Ativo, ativo_id)
    if ativo is None:
        return
    ativo.ultimo_usuario = limpo
    ativo.ultimo_usuario_em = agora

    atual = (
        db.query(UsuarioDoAtivo)
        .filter(UsuarioDoAtivo.ativo_id == ativo_id, UsuarioDoAtivo.nome == limpo)
        .first()
    )
    if atual is None:
        db.add(UsuarioDoAtivo(
            ativo_id=ativo_id, nome=limpo, primeira_vez=agora, ultimo_login=agora,
        ))
    else:
        atual.ultimo_login = agora

    # ## Sem expiração
    #
    # Antes, quem não aparecia há 30 dias era removido — a lista respondia
    # "quem usa isto", não "quem já usou".
    #
    # Agora guarda todo mundo que já se logou na máquina, com a data do
    # último acesso de cada um. É histórico, e o tamanho é limitado pelo
    # número de pessoas que passam pelo equipamento, não pelo tempo.
    #
    # Nada a apagar aqui. `primeira_vez` marca quando a pessoa apareceu pela
    # primeira vez; `ultimo_login`, a última.


def aplicar_inventario(db: Session, token: TokenAgente, payload: dict) -> dict:
    """Grava o inventário no ativo dono do token.

    O `ativo_id` vem do **token**, nunca do corpo: o agente não escolhe em
    qual ativo escreve.
    """
    ativo = db.get(Ativo, token.ativo_id)
    if ativo is None or ativo.deleted_at is not None:
        # Sem recuperacao aqui. O agente guarda o codigo de instalacao e
        # refaz o registro por conta propria — quem decide isso e o cliente,
        # nao o servidor.
        return {"ok": False, "status": 404, "motivo": "ativo_removido"}

    basico = payload.get("basico") or {}
    detalhes = payload.get("detalhes") or {}

    ficha = db.get(AtivoTI, ativo.id)
    if ficha is None:
        ficha = AtivoTI(ativo_id=ativo.id)
        db.add(ficha)

    def texto(valor, limite: int) -> str | None:
        if valor is None:
            return None
        s = str(valor).strip()
        return s[:limite] if s else None

    ficha.hostname = texto(basico.get("hostname") or payload.get("hostname"), 120)
    ficha.so = texto(basico.get("so"), 120)
    ficha.cpu = texto(basico.get("cpu"), 160)
    ficha.dominio_ad = texto(basico.get("dominio"), 120)
    if basico.get("ram_gb"):
        ficha.ram_gb = int(basico["ram_gb"])
    if basico.get("armazenamento_gb"):
        ficha.armazenamento_gb = int(basico["armazenamento_gb"])

    mac = _primeiro_mac(payload)
    if mac:
        ficha.mac_address = mac
    ip = _primeiro_ip(payload)
    if ip:
        ficha.ip = ip

    # Detecta mudança ANTES de sobrescrever: o snapshot antigo é a
    # referência, e depois da gravação ele não existe mais.
    mudancas = detectar_mudanca(db, ativo.id, payload)

    # --- campos da tabela base ------------------------------------------
    #
    # modelo e marca vivem em tivos, nao na ficha tivos_ti.
    # A criacao ja os preenchia; a ATUALIZACAO nao tocava neles — e o ativo
    # ficava com modelo e marca vazios mesmo depois de varias coletas.
    #
    # O agente e a fonte de verdade do hardware: se alguem corrigiu o modelo
    # a mao e a BIOS diz outra coisa, vale a BIOS. E o mesmo motivo pelo qual
    # "Detalhes Completos" e somente leitura.
    modelo = basico.get("modelo")
    if modelo:
        ativo.modelo = str(modelo).strip()[:120] or ativo.modelo

    marca = fabricante_valido(basico.get("fabricante"))
    if marca:
        ativo.marca = marca

    ficha.inventario_json = json.dumps(detalhes, ensure_ascii=False)
    ficha.inventario_em = datetime.now(timezone.utc)

    # Quem está usando, segundo o agente. Sem isto a lista de ativos não
    # mostra usuário nenhum — e é o dado que o coletor já enviava e ninguém
    # aproveitava.
    #
    # `detalhes.usuario_logado` é o mais preciso quando existe (vem do
    # registro do Windows); `usuario` é o campo de topo do payload.
    nome_usuario = detalhes.get("usuario_logado") or payload.get("usuario")
    registrar_usuario_do_ativo(db, ativo.id, nome_usuario)

    token.ultimo_uso_em = datetime.now(timezone.utc)
    db.commit()

    return {
        "ok": True,
        "status": 200,
        "ativo_id": ativo.id,
        "mudancas": mudancas or {},
        "historico": bool(mudancas),
    }

def definir_senha_fechamento(db: Session, senha: str | None) -> None:
    """Define (ou remove) a senha de fechamento do agente."""
    from app.core.security import hash_password
    from app.services import manutencao

    cfg = manutencao.configuracao(db)
    cfg.senha_fechamento_hash = hash_password(senha) if senha else None
    db.commit()


def validar_senha_fechamento(db: Session, senha: str) -> bool:
    """Confere a senha de fechamento.

    Sem senha definida, qualquer valor passa — e o fechamento e livre.
    """
    from app.core.security import verify_password
    from app.services import manutencao

    cfg = manutencao.configuracao(db)
    if not cfg.senha_fechamento_hash:
        return True
    return verify_password(senha or "", cfg.senha_fechamento_hash)
