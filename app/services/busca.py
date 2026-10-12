"""Busca global — acha ativo, produto, usuário e planta num só lugar.

## Por que um serviço separado

A busca é a mesma para qualquer origem; o que muda é **quais campos** de cada
tabela valem a pena pesquisar. Manter isso aqui permite testar a regra sem
subir a API, e deixa o router só com o transporte.

## Por que não usar um `LIKE` gigante

Cada entidade tem campos que fazem sentido (patrimônio, número de série) e
outros que não (o texto de uma observação). Buscar em tudo devolveria ruído —
o objetivo é achar em poucos resultados, não listar meia tabela.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import String, cast, or_
from sqlalchemy.orm import Session

from app.models.core import Ativo, Planta, Produto, Usuario
from app.models.impressora import AtivoImpressora
from app.models.software import Software
from app.models.ti import AtivoTI

# Quantos resultados por grupo. A busca mostra os primeiros de cada tipo; quem
# quer a lista completa vai para a tela do módulo.
POR_GRUPO = 5

# Abaixo disto a busca não roda: uma letra sozinha casaria com quase tudo e
# devolveria uma lista inútil, além de varrer a tabela à toa.
MINIMO = 2


@dataclass
class Achado:
    """Um resultado. `rota` é o endereço para onde clicar leva."""

    grupo: str
    titulo: str
    detalhe: str
    rota: str


@dataclass
class Resultado:
    termo: str
    grupos: dict[str, list[Achado]] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(len(v) for v in self.grupos.values())

    def para_dict(self) -> dict[str, Any]:
        return {
            "termo": self.termo,
            "total": self.total,
            "grupos": [
                {
                    "nome": nome,
                    "itens": [
                        {"titulo": a.titulo, "detalhe": a.detalhe, "rota": a.rota}
                        for a in itens
                    ],
                }
                for nome, itens in self.grupos.items()
                if itens
            ],
        }


def _contem(coluna, termo: str):
    """`LIKE %termo%` que funciona em texto e em número.

    Alguns campos são numéricos (o patrimônio pode virar int em alguns
    bancos). `cast` para texto evita erro de tipo — sem ele, buscar "123"
    estoura no Postgres.
    """
    return cast(coluna, String).ilike(f"%{termo}%")


def _detalhe_do_ativo(a, termo: str) -> str:
    """Linha de apoio do resultado, com o hostname em primeiro quando casou.

    A ordem responde à pergunta que a pessoa faz ao olhar a lista: "por que
    este apareceu?". Se ela digitou o hostname, ele tem que estar à vista —
    caso contrário o resultado parece aleatório, mesmo estando certo.
    """
    host = (getattr(a, "hostname", None) or "").strip()
    alvo = (termo or "").strip().lower()
    casou_no_host = bool(alvo and host and alvo in host.lower())

    campos = [host, a.modelo, a.numero_serie, a.marca] if casou_no_host else [
        a.modelo, a.numero_serie, a.marca, host,
    ]
    return " · ".join(x for x in campos if x)


def buscar(db: Session, termo: str, planta_id: int | None = None) -> Resultado:
    """Procura o termo nas entidades visíveis.

    `planta_id` restringe aos ativos da planta do usuário. `None` = todas
    (administrador). Sem este filtro, alguém de uma planta veria o patrimônio
    de outra pela busca — que é justamente o que o multi-tenant evita.
    """
    limpo = (termo or "").strip()
    r = Resultado(termo=limpo)
    if len(limpo) < MINIMO:
        return r

    # --- Ativos -----------------------------------------------------------
    q = db.query(Ativo).filter(Ativo.deleted_at.is_(None))
    if planta_id is not None:
        q = q.filter(Ativo.planta_id == planta_id)
    ativos = (
        q.outerjoin(AtivoTI, AtivoTI.ativo_id == Ativo.id)
        .outerjoin(AtivoImpressora, AtivoImpressora.ativo_id == Ativo.id)
        .filter(
            or_(
                _contem(Ativo.patrimonio, limpo),
                _contem(Ativo.numero_serie, limpo),
                _contem(Ativo.modelo, limpo),
                _contem(Ativo.marca, limpo),
                # O HOSTNAME não está no ativo: vive na ficha técnica, em TI
                # ou em impressora. Sem as duas junções, buscar "NTAT" não
                # achava nada — e é por esse nome que a máquina é conhecida
                # na rede, mais do que pelo patrimônio.
                _contem(AtivoTI.hostname, limpo),
                _contem(AtivoImpressora.hostname, limpo),
                _contem(AtivoTI.ip, limpo),
                _contem(AtivoImpressora.ip, limpo),
            )
        )
        .order_by(Ativo.patrimonio)
        .limit(POR_GRUPO)
        .all()
    )
    r.grupos["Ativos"] = [
        Achado(
            grupo="Ativos",
            # O patrimônio identifica; sem ele, o hostname é o que sobra.
            titulo=a.patrimonio or getattr(a, "hostname", None) or f"Ativo {a.id}",
            # O detalhe mostra o que ajuda a escolher entre parecidos — e o
            # hostname vem PRIMEIRO quando foi ele que casou, senão a pessoa
            # não entende por que aquele resultado apareceu.
            detalhe=_detalhe_do_ativo(a, limpo),
            rota=f"#/ativos/{a.id}",
        )
        for a in ativos
    ]

    # --- Produtos ---------------------------------------------------------
    # `sku` é o código do produto; `nome` é o que se digita no dia a dia.
    produtos = (
        db.query(Produto)
        .filter(
            Produto.deleted_at.is_(None),
            or_(_contem(Produto.nome, limpo), _contem(Produto.sku, limpo)),
        )
        .order_by(Produto.nome)
        .limit(POR_GRUPO)
        .all()
    )
    r.grupos["Produtos"] = [
        Achado(
            grupo="Produtos",
            titulo=p.nome,
            detalhe=f"SKU {p.sku}" if p.sku else "",
            rota=f"#/produtos/{p.id}",
        )
        for p in produtos
    ]

    # --- Software e licenças ---------------------------------------------
    # ## O que NÃO é pesquisado
    #
    # A chave da licença **não entra**. Indexá-la transformaria a busca num
    # vazamento: bastaria digitar quatro caracteres para descobrir a chave de
    # qualquer licença, sem passar pelo endpoint de revelação, sem exigir a
    # permissão e **sem deixar rastro na auditoria**.
    #
    # Busca-se o nome do produto e o fabricante — que é o que a pessoa sabe.
    softwares = (
        db.query(Software)
        .filter(
            Software.deleted_at.is_(None),
            or_(
                _contem(Software.nome, limpo),
                _contem(Software.fabricante, limpo),
                _contem(Software.categoria, limpo),
            ),
        )
        .order_by(Software.nome)
        .limit(POR_GRUPO)
        .all()
    )
    r.grupos["Software"] = [
        Achado(
            grupo="Software",
            titulo=s.nome,
            detalhe=s.fabricante or "",
            rota="#/software",
        )
        for s in softwares
    ]

    # --- Usuários ---------------------------------------------------------
    usuarios = (
        db.query(Usuario)
        .filter(
            Usuario.deleted_at.is_(None),
            or_(_contem(Usuario.nome, limpo), _contem(Usuario.email, limpo)),
        )
        .order_by(Usuario.nome)
        .limit(POR_GRUPO)
        .all()
    )
    r.grupos["Usuários"] = [
        Achado(
            grupo="Usuários",
            titulo=u.nome,
            detalhe=u.email or "",
            rota=f"#/admin/usuarios?busca={u.email}",
        )
        for u in usuarios
    ]

    # --- Plantas (só para quem vê todas) ---------------------------------
    # Quem está preso a uma planta não ganha resultado de planta: não teria o
    # que fazer com ele.
    if planta_id is None:
        plantas = (
            db.query(Planta)
            .filter(
                Planta.deleted_at.is_(None),
                or_(_contem(Planta.nome, limpo), _contem(Planta.sigla, limpo)),
            )
            .order_by(Planta.sigla)
            .limit(POR_GRUPO)
            .all()
        )
        r.grupos["Plantas"] = [
            Achado(
                grupo="Plantas",
                titulo=f"{p.sigla} — {p.nome}",
                detalhe="",
                rota="#/admin/plantas",
            )
            for p in plantas
        ]

    return r
