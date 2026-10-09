"""Schemas comuns: envelope de paginação e entidades de cadastro (lookups)."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models.enums import Dominio, PapelUsuario
from app.schemas.datas import DatasComFuso

T = TypeVar("T")


class SemVazios(BaseModel):
    """Converte strings vazias em `None` antes da validação.

    Formulários HTML enviam `""` para campos não preenchidos. Sem isso, um campo
    opcional tipado (e-mail, número, enum, data) falha na validação com um erro
    confuso — foi a causa do "email" vazio nos fornecedores.
    """

    @model_validator(mode="before")
    @classmethod
    def _strings_vazias_para_none(cls, dados: object) -> object:
        if isinstance(dados, dict):
            return {chave: (None if valor == "" else valor) for chave, valor in dados.items()}
        return dados


class Page(BaseModel, Generic[T]):
    """Envelope de paginação padronizado."""

    items: list[T]
    total: int
    page: int
    size: int
    pages: int


# ---------------------------------------------------------------------------
# Lookups (departamentos, localizações, fornecedores, categorias)
# ---------------------------------------------------------------------------
class DepartamentoBase(SemVazios):
    model_config = ConfigDict(extra="forbid")

    nome: str = Field(min_length=1, max_length=120)
    sigla: str | None = Field(default=None, max_length=20)


class DepartamentoCreate(DepartamentoBase):
    pass


class DepartamentoOut(DepartamentoBase, DatasComFuso):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class LocalizacaoBase(SemVazios):
    model_config = ConfigDict(extra="forbid")

    nome: str = Field(min_length=1, max_length=120)
    descricao: str | None = None


class LocalizacaoCreate(LocalizacaoBase):
    pass


class LocalizacaoOut(LocalizacaoBase, DatasComFuso):
    model_config = ConfigDict(from_attributes=True)

    id: int


class FornecedorBase(SemVazios):
    model_config = ConfigDict(extra="forbid")

    nome: str = Field(min_length=1, max_length=160)
    cnpj: str | None = Field(default=None, max_length=18)
    contato: str | None = Field(default=None, max_length=120)
    telefone: str | None = Field(default=None, max_length=30)
    email: EmailStr | None = None


class FornecedorCreate(FornecedorBase):
    pass


class FornecedorOut(FornecedorBase, DatasComFuso):
    model_config = ConfigDict(from_attributes=True)

    id: int


class CategoriaBase(SemVazios):
    model_config = ConfigDict(extra="forbid")

    nome: str = Field(min_length=1, max_length=120)
    dominio: Dominio | None = None
    descricao: str | None = None


class CategoriaCreate(CategoriaBase):
    pass


class CategoriaOut(CategoriaBase, DatasComFuso):
    model_config = ConfigDict(from_attributes=True)

    id: int


# ---------------------------------------------------------------------------
# Usuários (colaboradores do sistema) e permissões
# ---------------------------------------------------------------------------
class Permissoes(BaseModel):
    """Permissões granulares de um usuário."""

    model_config = ConfigDict(extra="forbid")

    inventarios: list[str] = []
    modulos: list[str] = []
    pode_escrever: bool = False
    pode_excluir: bool = False


class UsuarioBase(SemVazios):
    model_config = ConfigDict(extra="forbid")

    nome: str = Field(min_length=1, max_length=160)
    email: EmailStr
    papel: PapelUsuario = PapelUsuario.LEITOR
    departamento_id: int | None = None
    # Planta do usuário: tudo o que ele cadastrar fica nela.
    # None = acesso a TODAS as plantas (uso típico do administrador).
    planta_id: int | None = None
    ativo: bool = True
    permissoes: Permissoes | None = None
    # Usuário de logon no AD (`sAMAccountName`), quando a conta é de rede.
    # É por ele que a pessoa entra — o e-mail costuma ser diferente.
    login_ad: str | None = Field(default=None, max_length=120)


class UsuarioCreate(UsuarioBase):
    # Opcional quando a conta é do AD: a senha de rede é validada no diretório,
    # não aqui. Para contas locais continua obrigatória.
    senha: str | None = Field(default=None, min_length=6, max_length=128)


class UsuarioUpdate(SemVazios):
    model_config = ConfigDict(extra="forbid")

    nome: str | None = Field(default=None, min_length=1, max_length=160)
    email: EmailStr | None = None
    papel: PapelUsuario | None = None
    departamento_id: int | None = None
    planta_id: int | None = None
    ativo: bool | None = None
    senha: str | None = Field(default=None, min_length=6, max_length=128)
    permissoes: Permissoes | None = None
    login_ad: str | None = Field(default=None, max_length=120)


class UsuarioOut(DatasComFuso):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nome: str
    email: EmailStr
    papel: PapelUsuario
    departamento_id: int | None
    planta_id: int | None = None
    planta_sigla: str | None = None
    ativo: bool
    # 'local' (senha no sistema, inclui o root) ou 'ad' (autentica no AD).
    origem: str = "local"
    # Usuario de logon no AD (sAMAccountName). Separado do e-mail porque
    # costuma ser diferente dele.
    login_ad: str | None = None
    # Módulos favoritos na barra lateral — vêm como LISTA, não como o JSON
    # cru que fica guardado no banco.
    barra_favoritos: list[str] = []
    # Ordem da lista INTEIRA da gaveta (também como lista). Separada dos
    # favoritos porque quem reordena mexe em todas as linhas, não só nas
    # marcadas.
    barra_ordem: list[str] = []
    permissoes: dict | None = None
    # Calculado pelo backend (papel + customizações) — usado pelo frontend.
    permissoes_efetivas: dict = {}

    @field_validator("barra_favoritos", "barra_ordem", mode="before")
    @classmethod
    def _ler_lista_json(cls, valor):
        """O banco guarda um texto JSON; a API entrega uma lista.

        Aceita também `None` (usuário que nunca escolheu nada) e um JSON
        inválido — nesses casos devolve lista vazia em vez de estourar.
        """
        if valor is None or valor == "":
            return []
        if isinstance(valor, list):
            return [str(v) for v in valor if isinstance(v, str)]
        try:
            dados = json.loads(valor)
        except (ValueError, TypeError):
            return []
        return [str(v) for v in dados if isinstance(v, str)] if isinstance(dados, list) else []
