"""Schemas da área administrativa: dispositivos de impressão e banco de fotos."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import Dominio
from app.schemas.common import SemVazios
from app.schemas.datas import DatasComFuso


# ---------------------------------------------------------------------------
# Dispositivos de impressão
# ---------------------------------------------------------------------------
class DispositivoImpressaoBase(SemVazios):
    model_config = ConfigDict(extra="forbid")

    nome: str = Field(min_length=1, max_length=160)
    tipo: str = Field(default="agente", pattern="^(agente|compartilhamento|cups)$")
    hostname: str | None = Field(default=None, max_length=160)
    compartilhamento: str | None = Field(default=None, max_length=300)  # \\RTAT0001\sip
    agente_url: str | None = Field(default=None, max_length=300)
    fila_cups: str | None = Field(default=None, max_length=160)
    formato: str = Field(default="zpl", pattern="^(zpl|tspl|pdf)$")
    dominio: Dominio | None = None
    padrao: bool = False
    ativo: bool = True
    observacoes: str | None = None
    # Template de etiqueta deste dispositivo (None = usa o padrão).
    template_id: int | None = None


class DispositivoImpressaoCreate(DispositivoImpressaoBase):
    # Planta dona da impressora. O ADMINISTRADOR pode escolher qualquer uma;
    # para o perfil TI este campo é ignorado (vale a planta dele).
    planta_id: int | None = None


class DispositivoImpressaoUpdate(DispositivoImpressaoBase):
    # O administrador pode mover a impressora de planta.
    planta_id: int | None = None


class DispositivoImpressaoOut(DispositivoImpressaoBase, DatasComFuso):
    model_config = ConfigDict(from_attributes=True)

    id: int
    # Planta dona da impressora (cada planta imprime na sua).
    planta_id: int | None = None
    planta_sigla: str | None = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Banco de fotos
# ---------------------------------------------------------------------------
class ImagemUpdate(SemVazios):
    model_config = ConfigDict(extra="forbid")

    nome: str | None = Field(default=None, min_length=1, max_length=160)
    descricao: str | None = None
    tags: str | None = Field(default=None, max_length=200)
    dominio: Dominio | None = None


class ImagemOut(DatasComFuso):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nome: str
    descricao: str | None = None
    tags: str | None = None
    dominio: Dominio | None = None
    mime_type: str | None = None
    tamanho: int | None = None
    created_at: datetime
    # URL para exibição (requer ?token= por ser rota autenticada).
    url: str = ""


class AtivoFotoRequest(BaseModel):
    """Vincula (ou remove, com null) a foto principal de um ativo."""

    model_config = ConfigDict(extra="forbid")

    foto_id: int | None = None
