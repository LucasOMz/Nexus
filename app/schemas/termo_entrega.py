from datetime import date
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


class CampoEntrega(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,50}$")
    rotulo: str = Field(min_length=1, max_length=85)
    tipo: Literal["leitura", "texto", "matricula", "nome", "patrimonio", "data", "assinatura"]
    pagina: int = Field(ge=1, le=12)
    x: float = Field(ge=0, le=99)
    y: float = Field(ge=0, le=99)
    largura: float = Field(ge=1, le=100)
    altura: float = Field(ge=1, le=100)
    obrigatorio: bool = True

    @model_validator(mode="after")
    def dentro_da_pagina(self):
        if self.x + self.largura > 100.001 or self.y + self.altura > 100.001:
            raise ValueError("Posicione todo o campo dentro da página.")
        return self


class ConfigEntrega(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    nome: str = Field(min_length=1, max_length=120)
    url_publica: str = Field(min_length=9, max_length=300)
    prazo_horas: int = Field(ge=1, le=720)
    exigir_agente: bool = False
    campos: list[CampoEntrega] = Field(min_length=2, max_length=80)

    @field_validator("url_publica")
    @classmethod
    def validar_url_publica(cls, valor):
        try:
            partes = urlsplit(valor)
            if (partes.scheme != "https" or not partes.hostname or partes.username or partes.password
                    or partes.query or partes.fragment or partes.path not in ("", "/") or partes.port == 0
                    or any(c.isspace() or ord(c) < 32 or c == "\\" for c in valor)):
                raise ValueError
        except ValueError:
            raise ValueError("Informe a origem HTTPS do Nexus, como https://nexus.empresa.com.") from None
        host = partes.hostname.encode("idna").decode("ascii")
        if ":" in host:
            host = f"[{host}]"
        porta = f":{partes.port}" if partes.port not in (None, 443) else ""
        return f"https://{host}{porta}"

    @model_validator(mode="after")
    def validar_campos(self):
        if len({c.id for c in self.campos}) != len(self.campos):
            raise ValueError("Há campos duplicados.")
        obrigatorios = {c.tipo for c in self.campos if c.obrigatorio}
        if not {"leitura", "assinatura"} <= obrigatorios:
            raise ValueError("Inclua um aceite de leitura e uma assinatura obrigatórios.")
        return self


class ConfirmarEnvioEntrega(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr


class IdentidadeEntrega(BaseModel):
    model_config = ConfigDict(extra="forbid")
    login: str = Field(min_length=1, max_length=120)
    senha: str = Field(min_length=1, max_length=256, repr=False)


class AceiteEntrega(BaseModel):
    model_config = ConfigDict(extra="forbid")
    campos: dict[str, str | bool] = Field(max_length=80)
    fonte: Literal["classica", "inclinada", "manuscrita"] = "classica"
    assinatura_png: str | None = Field(default=None, max_length=720000, repr=False)
    confirmar_no_agente: bool = False


class ConfirmacaoAgenteEntrega(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    codigo: str = Field(pattern=r"^[A-Z2-9]{10}$", repr=False)
    usuario_windows: str = Field(min_length=1, max_length=180)
    assinatura: str = Field(pattern=r"^[a-f0-9]{64}$", repr=False)
