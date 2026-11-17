"""Mapa 3D do parque: projeto por planta e posicao de cada ativo.

## O que este modulo guarda, e por que separado

**O projeto** (planta baixa, escala, paredes) e **um por planta** — muda quando
alguem reforma o predio, nao quando troca um computador.

**A posicao** e **por ativo** e muda toda semana — chega notebook, sai
impressora, o tecnico arrasta.

Guardar as duas coisas no mesmo lugar obrigaria a rescrever o projeto inteiro
para mover uma cadeira. Separadas, arrastar um ativo e um `UPDATE` de tres
colunas.

## Por que a posicao fica no `Ativo` e nao numa tabela propria

`mapa_x`, `mapa_z` e `mapa_rotacao` sao nulos para quem ainda nao foi
posicionado. Uma tabela a mais custaria um `JOIN` em toda listagem de ativos —
e o mapa le exatamente os mesmos ativos da tela normal.
"""
from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BaseModel


class MapaProjeto(BaseModel, Base):
    """A planta de uma unidade: imagem de fundo, escala e paredes.

    ## Escala

    `escala_metros_por_pixel` e o que transforma a imagem em metros. Sem ela o
    mapa e um desenho: nao da para medir distancia nem dimensionar uma
    impressora em relacao a mesa.

    A calibracao e por **linha conhecida**: o usuario desenha sobre uma parede
    de medida sabida e o sistema calcula a razao.

    ## Paredes

    Lista de segmentos em metros: `[{x1, z1, x2, z2, altura, espessura}]`.
    Fica em `Text` com JSON, e nao em tabela propria, porque **nunca e
    consultada por dentro** — so lida e gravada inteira.
    """

    __tablename__ = "mapas_projeto"

    id: Mapped[int] = mapped_column(primary_key=True)
    planta_id: Mapped[int] = mapped_column(
        ForeignKey("plantas.id", ondelete="CASCADE"), unique=True, index=True
    )

    # Caminho relativo em MEDIA_DIR. Nulo = planta ainda sem planta baixa.
    imagem: Mapped[str | None] = mapped_column(String(300))
    largura_px: Mapped[int | None] = mapped_column(Integer)
    altura_px: Mapped[int | None] = mapped_column(Integer)

    # Quantos metros vale um pixel da imagem.
    escala_metros_por_pixel: Mapped[float] = mapped_column(Float, default=0.02)

    paredes: Mapped[str | None] = mapped_column(Text)
    observacoes: Mapped[str | None] = mapped_column(Text)

    planta = relationship("Planta", lazy="joined")
