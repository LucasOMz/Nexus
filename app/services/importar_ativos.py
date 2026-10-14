"""Importação de ativos por CSV.

## As três etapas, e por que separadas

```
1. MODELO      a tela mostra as colunas e um exemplo preenchido
2. ANÁLISE     o arquivo é lido e validado — SEM gravar nada
3. IMPORTAÇÃO  backup, e só então a gravação
```

A etapa 2 existe porque **importação é a operação mais destrutiva do
sistema**. Um arquivo com 500 linhas erradas cria 500 ativos errados, e
desfazer isso à mão é pior que não ter importado.

Por isso a análise **não grava**: ela devolve exatamente o que aconteceria —
quantas linhas entram, quais falham e por quê — para a decisão ser tomada
olhando o resultado, e não imaginando.

## O backup antes de gravar

A etapa 3 cria um backup **automaticamente**, antes de tocar no banco. É a
única forma de desfazer uma importação errada — e o único momento em que
ainda dá para fazê-lo.

## As colunas de ligação vêm por NOME

`categoria`, `fornecedor`, `localizacao` e `departamento` são preenchidos com
o **nome**, não com o id. Quem monta a planilha no Excel conhece "Notebook",
não "categoria_id = 7".

O que não existir é **criado** na importação — e a análise avisa quais serão.
Sem isso, quem importa 500 linhas teria antes de cadastrar 30 categorias à
mão, e desistiria.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from app.models.enums import (
    Conectividade,
    Dominio,
    FormaAquisicao,
    StatusAtivo,
    TipoImpressao,
    TipoItem,
)

# ---------------------------------------------------------------------------
# As colunas
# ---------------------------------------------------------------------------
# Ordem em que aparecem no modelo. `obrigatoria` define o que a análise cobra.
# A descrição é o que a tela mostra antes de a pessoa abrir o Excel.
COLUNAS: list[tuple[str, bool, str]] = [
    ("patrimonio", True, "Identificação única do bem. É o que vai na etiqueta. Não pode repetir."),
    ("dominio", True, "`ti` ou `impressora`. Define qual ficha técnica a linha usa."),
    ("tipo_item", False, "`ativo` ou `consumivel`. Vazio assume `ativo`."),
    ("numero_serie", False, "Número de série do fabricante."),
    ("modelo", False, "Ex.: Latitude 3420, LaserJet M404."),
    ("marca", False, "Ex.: Dell, HP, Lenovo."),
    ("status", False, "estoque, em_uso, manutencao, reservado, descartado. Vazio assume estoque."),
    ("categoria", False, "NOME da categoria. Se não existir, é criada."),
    ("fornecedor", False, "NOME do fornecedor. Se não existir, é criado."),
    ("localizacao", False, "NOME do local. Se não existir, é criado."),
    ("departamento", False, "NOME do departamento. Se não existir, é criado."),
    ("data_aquisicao", False, "Data da compra, no formato AAAA-MM-DD."),
    ("data_garantia", False, "Fim da garantia, AAAA-MM-DD."),
    ("valor", False, "Valor de compra. Use ponto como decimal: 3499.90"),
    ("forma_aquisicao", False, "comprado, locado ou assinatura."),
    ("observacoes", False, "Texto livre."),
    ("foto", False, "NÚMERO da foto, como aparece no sistema. Use o id da imagem já enviada. Vazio deixa o ativo sem foto."),
    # --- ficha de TI (só quando dominio = ti) ---
    ("hostname", False, "[TI] Nome da máquina na rede."),
    ("mac_address", False, "[TI] Endereço MAC."),
    ("ip", False, "[TI] Endereço IP."),
    ("so", False, "[TI] Sistema operacional."),
    ("cpu", False, "[TI] Processador."),
    ("ram_gb", False, "[TI] Memória em GB."),
    ("armazenamento_gb", False, "[TI] Disco em GB."),
    # --- ficha de impressora (só quando dominio = impressora) ---
    ("tipo_impressao", False, "[Impressora] laser, jato_tinta, termica, matricial."),
    ("colorida", False, "[Impressora] sim ou nao."),
    ("contador_paginas", False, "[Impressora] Contador atual."),
    ("conectividade", False, "[Impressora] rede, usb, wifi."),
    ("driver", False, "[Impressora] Nome do driver."),
]

NOMES = [c[0] for c in COLUNAS]

# Linhas de exemplo do modelo — uma de cada domínio, para o arquivo baixado
# já mostrar os dois formatos sem precisar de explicação à parte.
EXEMPLOS = [
    {
        "patrimonio": "TI-0001", "dominio": "ti", "tipo_item": "ativo",
        "numero_serie": "SN-ABC123", "modelo": "Latitude 3420", "marca": "Dell",
        "status": "estoque", "categoria": "Notebook", "fornecedor": "Dell Brasil",
        "localizacao": "Escritório Central", "departamento": "TI",
        "data_aquisicao": "2024-03-15", "data_garantia": "2027-03-15",
        "valor": "5499.00", "forma_aquisicao": "comprado",
        "observacoes": "Comprado no lote de renovação",
        "foto": "https://exemplo.com/fotos/notebook.jpg",
        "hostname": "DESK-TI-001", "mac_address": "00:1A:2B:3C:4D:5E",
        "ip": "10.0.0.10", "so": "Windows 11 Pro", "cpu": "i5-1235U",
        "ram_gb": "16", "armazenamento_gb": "512",
    },
    {
        "patrimonio": "IMP-0001", "dominio": "impressora", "tipo_item": "ativo",
        "numero_serie": "SN-PRN456", "modelo": "LaserJet M404dn", "marca": "HP",
        "status": "em_uso", "categoria": "Impressora", "fornecedor": "HP Brasil",
        "localizacao": "Escritório Central", "departamento": "Administrativo",
        "data_aquisicao": "2023-08-01", "valor": "2199.90",
        "forma_aquisicao": "comprado", "foto": "",
        "ip": "10.0.0.42", "tipo_impressao": "laser", "colorida": "nao",
        "contador_paginas": "48210", "conectividade": "rede",
    },
]


def modelo_csv() -> str:
    """O arquivo de exemplo, pronto para abrir no Excel.

    Separador `;` e BOM — o mesmo cuidado dos outros relatórios do sistema:
    com vírgula, o Excel em português junta tudo numa coluna só, e quem
    recebe conclui que o modelo está errado.

    A **segunda linha** é o exemplo preenchido, e não um comentário: quem
    abre o arquivo vê o formato certo sem precisar ler instrução.
    """
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=NOMES, delimiter=";",
                       extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for linha in EXEMPLOS:
        w.writerow(linha)
    return "\ufeff" + buf.getvalue()


def modelo_texto() -> str:
    """O modelo em texto, para a tela mostrar sem precisar baixar."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=NOMES, delimiter=";",
                       extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    w.writerow(EXEMPLOS[0])
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Leitura e validação
# ---------------------------------------------------------------------------
@dataclass
class LinhaAnalisada:
    numero: int                       # linha do arquivo (1 = primeira após o cabeçalho)
    dados: dict[str, Any] = field(default_factory=dict)
    erros: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    # O que será criado por não existir — mostrado ANTES de gravar.
    criar: list[str] = field(default_factory=list)
    foto_url: str | None = None

    @property
    def ok(self) -> bool:
        return not self.erros


@dataclass
class Analise:
    linhas: list[LinhaAnalisada] = field(default_factory=list)
    erro_geral: str | None = None
    colunas_faltando: list[str] = field(default_factory=list)
    colunas_desconhecidas: list[str] = field(default_factory=list)

    @property
    def validas(self) -> list[LinhaAnalisada]:
        return [linha for linha in self.linhas if linha.ok]

    @property
    def invalidas(self) -> list[LinhaAnalisada]:
        return [linha for linha in self.linhas if not linha.ok]


def _achar_colunas(cabecalho: list[str]) -> tuple[dict[str, int], list[str], list[str]]:
    """Mapeia o cabeçalho do arquivo para as colunas conhecidas.

    Tolerante a acento, caixa e espaço — quem monta a planilha escreve
    `Número de Série` ou `numero_serie`, e as duas formas devem valer.
    """
    from app.services.conformidade import normalizar

    mapa: dict[str, int] = {}
    for i, bruto in enumerate(cabecalho):
        chave = normalizar(bruto).replace(" ", "_")
        if chave in NOMES:
            mapa[chave] = i

    faltando = [n for n, obrig, _ in COLUNAS if obrig and n not in mapa]
    desconhecidas = [
        h for i, h in enumerate(cabecalho)
        if h.strip() and normalizar(h).replace(" ", "_") not in NOMES
    ]
    return mapa, faltando, desconhecidas


def _texto(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


def _data(v: str | None) -> date | None:
    v = _texto(v)
    if not v:
        return None
    # Aceita o que o Excel costuma produzir, além do ISO que pedimos.
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"data inválida: {v!r} (use AAAA-MM-DD)")


def _decimal(v: str | None) -> Decimal | None:
    v = _texto(v)
    if not v:
        return None
    # `1.234,56` é o que sai do Excel em português; `1234.56` é o que pedimos.
    # Aceitar os dois evita que o valor entre errado por causa de separador.
    if "," in v and "." in v:
        v = v.replace(".", "").replace(",", ".")
    elif "," in v:
        v = v.replace(",", ".")
    try:
        return Decimal(v)
    except InvalidOperation as exc:
        raise ValueError(f"valor inválido: {v!r}") from exc


def _inteiro(v: str | None) -> int | None:
    d = _decimal(v)
    return int(d) if d is not None else None


def _booleano(v: str | None) -> bool | None:
    v = _texto(v)
    if v is None:
        return None
    return v.lower() in ("sim", "s", "true", "1", "yes", "y")


def _enum_seguro(enum_cls: Any, valor: str | None, padrao: Any = None) -> Any:
    if valor is None:
        return padrao
    from app.services.conformidade import normalizar

    alvo = normalizar(valor).replace(" ", "_").replace("-", "_")
    for membro in enum_cls:
        if normalizar(membro.value) == alvo:
            return membro
    raise ValueError(f"valor não reconhecido: {valor!r}")


def analisar(conteudo: bytes, db: Session, planta_id: int | None) -> Analise:
    """Lê e valida o arquivo **sem gravar nada**.

    É a etapa que torna a importação reversível na decisão: quem importa vê
    quantas linhas entram, quais falham e o que será criado — e desiste ainda
    a tempo.
    """
    a = Analise()

    try:
        texto = conteudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            texto = conteudo.decode("latin-1")
        except UnicodeDecodeError:
            a.erro_geral = (
                "Não foi possível ler o arquivo. Salve como CSV UTF-8 — no "
                "Excel: Salvar como → CSV UTF-8 (delimitado por vírgulas)."
            )
            return a

    # Detecta o separador: `;` no Excel em português, `,` no resto.
    primeira = texto.split("\n", 1)[0]
    sep = ";" if primeira.count(";") >= primeira.count(",") else ","

    leitor = csv.reader(io.StringIO(texto), delimiter=sep)
    try:
        cabecalho = next(leitor)
    except StopIteration:
        a.erro_geral = "O arquivo está vazio."
        return a

    mapa, faltando, desconhecidas = _achar_colunas(cabecalho)
    a.colunas_faltando = faltando
    a.colunas_desconhecidas = desconhecidas
    if faltando:
        a.erro_geral = (
            f"Faltam colunas obrigatórias: {', '.join(faltando)}. "
            "Baixe o modelo para ver o formato esperado."
        )
        return a

    # Patrimônios já existentes no banco — para acusar repetição ANTES de
    # tentar gravar e receber o erro do banco linha a linha.
    from app.models.core import Ativo

    existentes = {
        p for (p,) in db.query(Ativo.patrimonio)
        .filter(Ativo.deleted_at.is_(None)).all() if p
    }

    vistos: set[str] = set()

    # Ids de imagem que existem — para acusar foto inexistente na PRÉVIA, e
    # não no meio da importação, quando metade já entrou.
    from app.models.core import Imagem

    imagens_existentes = {
        i for (i,) in db.query(Imagem.id).filter(Imagem.deleted_at.is_(None)).all()
    }

    for numero, bruto in enumerate(leitor, start=1):
        # Linha em branco no fim do arquivo é comum e não é erro.
        if not any(c.strip() for c in bruto):
            continue

        linha = LinhaAnalisada(numero=numero)
        def col(nome, padrao=None):
            """Valor da coluna, ou o padrão quando ela não veio."""
            i = mapa.get(nome)
            return bruto[i] if i is not None and i < len(bruto) else padrao

        try:
            patrimonio = _texto(col("patrimonio"))
            if not patrimonio:
                linha.erros.append("`patrimonio` vazio")
            elif patrimonio in vistos:
                linha.erros.append(f"`{patrimonio}` repetido no próprio arquivo")
            elif patrimonio in existentes:
                linha.erros.append(f"`{patrimonio}` já existe no sistema")
            vistos.add(patrimonio or "")

            dominio = _enum_seguro(
                Dominio,
                _texto(col("dominio")),
            )
            if dominio is None:
                linha.erros.append("`dominio` vazio (use `ti` ou `impressora`)")

            linha.dados = {
                "patrimonio": patrimonio,
                "dominio": dominio,
                "tipo_item": _enum_seguro(
                    TipoItem,
                    _texto(col("tipo_item")),
                ),
                "status": _enum_seguro(
                    StatusAtivo,
                    _texto(col("status")),
                ),
                "numero_serie": _texto(col("numero_serie")),
                "modelo": _texto(col("modelo")),
                "marca": _texto(col("marca")),
                "data_aquisicao": _data(col("data_aquisicao")),
                "data_garantia": _data(col("data_garantia")),
                "valor": _decimal(col("valor")),
                "forma_aquisicao": _enum_seguro(
                    FormaAquisicao,
                    _texto(col("forma_aquisicao")),
                ),
                "observacoes": _texto(col("observacoes")),
            }
        except ValueError as e:
            linha.erros.append(str(e))

        # --- vínculos por nome -------------------------------------------
        if not linha.erros:
            linha.criar = _resolver_vinculos(linha, col, db, planta_id)

        # --- ficha técnica ------------------------------------------------
        if not linha.erros:
            try:
                linha.dados["ficha"] = _ficha(linha.dados.get("dominio"), col)
            except ValueError as e:
                linha.erros.append(str(e))

        # --- foto ----------------------------------------------------------
        #
        # `foto` é o **id de uma imagem que já está no banco** — o mesmo
        # número que o sistema mostra. Não é URL.
        #
        # A versão anterior tratava como endereço e a baixaria na importação.
        # Isso traria risco de SSRF (alguém apontaria para um serviço interno
        # da rede) e trabalho que não é necessário: as fotos já foram enviadas
        # pelo sistema antes de montar a planilha.
        foto = _texto(col("foto"))
        if foto:
            try:
                foto_id = int(str(foto).strip())
            except ValueError:
                linha.erros.append(
                    f"`foto` deve ser o NÚMERO da imagem ({foto!r} não é número)"
                )
            else:
                if foto_id not in imagens_existentes:
                    linha.erros.append(
                        f"foto {foto_id} não existe — envie a imagem no sistema antes"
                    )
                else:
                    linha.dados["foto_id"] = foto_id

        a.linhas.append(linha)

    return a


def _resolver_vinculos(linha: LinhaAnalisada, col: Any, db: Session,
                       planta_id: int | None) -> list[str]:
    """Liga categoria/fornecedor/local/departamento por NOME.

    O que existir é vinculado; o que não existir entra na lista `criar`, que a
    tela mostra antes de gravar. Criar direto, sem avisar, encheria o cadastro
    de duplicata de digitação — `Notbook` e `Notebook` virariam duas
    categorias.
    """
    from app.models.core import Categoria, Departamento, Fornecedor, Localizacao

    criar: list[str] = []
    pares = [
        ("categoria", Categoria, Categoria.nome, "categoria_id"),
        ("fornecedor", Fornecedor, Fornecedor.nome, "fornecedor_id"),
        ("localizacao", Localizacao, Localizacao.nome, "localizacao_id"),
        ("departamento", Departamento, Departamento.nome, "departamento_id"),
    ]

    from app.services.conformidade import normalizar

    for chave, modelo, campo, destino in pares:
        nome = _texto(col(chave))
        if not nome:
            continue
        achado = (
            db.query(modelo)
            .filter(modelo.deleted_at.is_(None))
            .filter(campo == nome)
            .first()
        )
        if achado:
            linha.dados[destino] = achado.id
            continue
        # Procura sem diferenciar acento/caixa antes de decidir criar.
        for m in db.query(modelo).filter(modelo.deleted_at.is_(None)).all():
            if normalizar(getattr(m, "nome", "")) == normalizar(nome):
                linha.dados[destino] = m.id
                linha.avisos.append(
                    f"`{nome}` casou com `{m.nome}` já cadastrado (acento/caixa)"
                )
                achado = m
                break
        if not achado:
            linha.dados[f"novo_{chave}"] = (nome, planta_id)
            criar.append(f"{chave}: {nome}")

    return criar


def _ficha(dominio: Any, col: Any) -> dict[str, Any] | None:
    """Os campos da ficha técnica, conforme o domínio da linha."""

    nome = getattr(dominio, "value", dominio)

    if nome == "ti":
        return {
            "hostname": _texto(col("hostname")),
            "mac_address": _texto(col("mac_address")),
            "ip": _texto(col("ip")),
            "so": _texto(col("so")),
            "cpu": _texto(col("cpu")),
            "ram_gb": _inteiro(col("ram_gb")),
            "armazenamento_gb": _inteiro(col("armazenamento_gb")),
        }
    if nome == "impressora":
        return {
            "ip": _texto(col("ip")),
            "hostname": _texto(col("hostname")),
            "driver": _texto(col("driver")),
            "tipo_impressao": _enum_seguro(TipoImpressao, _texto(col("tipo_impressao"))),
            "colorida": _booleano(col("colorida")),
            "contador_paginas": _inteiro(col("contador_paginas")),
            "conectividade": _enum_seguro(Conectividade, _texto(col("conectividade"))),
        }
    return None


# ---------------------------------------------------------------------------
# A gravação
# ---------------------------------------------------------------------------
def importar(conteudo: bytes, db: Session, planta_id: int | None,
             usuario: Any = None) -> dict[str, Any]:
    """Grava o arquivo, **criando um backup antes**.

    ## Por que o backup não é opcional

    Importação é a operação mais destrutiva do sistema: um arquivo com 500
    linhas erradas cria 500 ativos errados de uma vez, e desfazer à mão é pior
    que não ter importado.

    O backup é a única forma de voltar atrás — e este é o último instante em
    que dá para fazê-lo. Por isso ele acontece **antes** da primeira gravação,
    e não depois: se falhar, nada foi tocado.

    ## Por que reanalisa em vez de receber o resultado da análise

    Entre a prévia e a confirmação o mundo muda: alguém pode ter cadastrado o
    mesmo patrimônio noutra aba. Reanalisar garante que o que entra é o que
    foi validado **agora** — e não uma decisão tomada minutos antes.

    ## Uma transação só

    Tudo entra junto ou nada entra. Importação parcial é pior que importação
    nenhuma: quem importa não sabe onde parou, e reimportar duplicaria o que
    já passou.
    """
    from app.services import backup_service

    analise = analisar(conteudo, db, planta_id)
    if analise.erro_geral:
        return {"ok": False, "mensagem": analise.erro_geral, "criados": 0}

    validas = analise.validas
    if not validas:
        return {
            "ok": False, "criados": 0,
            "mensagem": "Nenhuma linha válida para importar.",
            "invalidas": len(analise.invalidas),
        }

    # --- backup ---------------------------------------------------------
    try:
        backup = backup_service.criar_backup(motivo="pre-importacao")
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False, "criados": 0,
            "mensagem": (
                f"Não foi possível criar o backup antes de importar "
                f"({type(e).__name__}). A importação foi cancelada — sem "
                "backup não há como desfazer."
            ),
        }

    from app.core.planta import exigir_planta
    from app.models.core import Ativo, Categoria, Departamento, Fornecedor, Localizacao
    from app.models.enums import StatusAtivo, TipoItem
    from app.models.impressora import AtivoImpressora
    from app.models.ti import AtivoTI

    MODELO_POR_CHAVE = {
        "categoria": Categoria, "fornecedor": Fornecedor,
        "localizacao": Localizacao, "departamento": Departamento,
    }

    criados: list[str] = []
    novos_vinculos: dict[str, int] = {}

    try:
        for linha in validas:
            d = dict(linha.dados)
            ficha = d.pop("ficha", None)
            d.pop("novo_categoria", None)
            d.pop("novo_fornecedor", None)
            d.pop("novo_localizacao", None)
            d.pop("novo_departamento", None)

            # --- cria o que não existia, uma vez só ----------------------
            for chave, modelo in MODELO_POR_CHAVE.items():
                novo = linha.dados.get(f"novo_{chave}")
                if not novo:
                    continue
                nome, planta = novo
                # Reaproveita o que outra LINHA do mesmo arquivo já criou —
                # sem isto, 40 ativos com "Notebook" criariam 40 categorias.
                if nome in novos_vinculos:
                    d[f"{chave}_id"] = novos_vinculos[nome]
                    continue
                obj = modelo(nome=nome, planta_id=planta)
                db.add(obj)
                db.flush()
                novos_vinculos[nome] = obj.id
                d[f"{chave}_id"] = obj.id

            d.setdefault("tipo_item", TipoItem.ATIVO)
            d.setdefault("status", StatusAtivo.ESTOQUE)
            d["planta_id"] = exigir_planta(db, planta_id, "importar ativos")

            ativo = Ativo(**{k: v for k, v in d.items() if hasattr(Ativo, k)})
            db.add(ativo)
            db.flush()

            if ficha:
                limpa = {k: v for k, v in ficha.items() if v is not None}
                if limpa:
                    if getattr(ativo.dominio, "value", ativo.dominio) == "ti":
                        db.add(AtivoTI(ativo_id=ativo.id, **limpa))
                    else:
                        db.add(AtivoImpressora(ativo_id=ativo.id, **limpa))

            criados.append(ativo.patrimonio)

        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        return {
            "ok": False, "criados": 0,
            "mensagem": (
                f"Falha ao gravar ({type(e).__name__}: {e}). Nada foi "
                "importado — o banco voltou ao estado anterior."
            ),
            "backup": backup.get("arquivo") or backup.get("nome"),
        }

    return {
        "ok": True,
        "criados": len(criados),
        "patrimonios": criados[:50],
        "ignoradas": len(analise.invalidas),
        "vinculos_criados": len(novos_vinculos),
        "backup": backup.get("arquivo") or backup.get("nome"),
        "mensagem": (
            f"{len(criados)} ativo(s) importado(s). "
            f"{len(analise.invalidas)} linha(s) inválida(s) foram ignoradas."
        ),
    }
