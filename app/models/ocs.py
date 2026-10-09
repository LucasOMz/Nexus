"""Modelos da integração com o OCS Inventory.

Fica separado de `ConfiguracaoSistema` (que guarda o login/AD) de propósito:
são assuntos diferentes, e assim a integração pode ser removida sem tocar na
configuração de autenticação.
"""
from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BaseModel, CreatedAtModel


class ConfiguracaoOCS(BaseModel, Base):
    """Configuração da integração (linha única, id=1)."""

    __tablename__ = "ocs_config"

    id: Mapped[int] = mapped_column(primary_key=True)

    # --- Conexão ---
    ativo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    servidor: Mapped[str | None] = mapped_column(String(300))  # http://ocs/ocsinventory
    token: Mapped[str | None] = mapped_column(String(500))  # CIFRADO
    verificar_ssl: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    timeout_s: Mapped[int] = mapped_column(Integer, default=30, nullable=False)

    # --- Sincronização automática ---
    sync_automatica: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Intervalo em MINUTOS: permite 15 min e 30 min, que em horas não caberiam.
    sync_intervalo_minutos: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    # LEGADO: a primeira versão media o intervalo em horas. Não aparece em tela
    # nem na API — existe para (a) converter o valor de quem já configurou e
    # (b) satisfazer a restrição NOT NULL que a tabela antiga criou. O `default`
    # é o que garante que a inserção mande um valor.
    sync_intervalo_horas: Mapped[int | None] = mapped_column(Integer, default=0)

    # --- Comportamento da importação ---
    criar_novos: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    atualizar_existentes: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ignorar_sem_serial: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    dominio_padrao: Mapped[str] = mapped_column(String(20), default="ti", nullable=False)
    status_padrao: Mapped[str] = mapped_column(String(30), default="estoque", nullable=False)
    # Regex opcional: só importa hostnames que casarem.
    filtrar_hostname: Mapped[str | None] = mapped_column(String(300))

    # Lista JSON: [{"prefixo": "BNT-", "planta_id": 2}, ...]
    regras_planta: Mapped[str | None] = mapped_column(Text)

    # --- Últimos resultados ---
    ultimo_teste_ok: Mapped[str | None] = mapped_column(String(40))
    ultimo_teste_msg: Mapped[str | None] = mapped_column(Text)
    ultima_sync_em: Mapped[str | None] = mapped_column(String(40))
    ultima_sync_resumo: Mapped[str | None] = mapped_column(Text)

    # --- Falhas (alimentam o aviso no sino) ---
    ultimo_erro_em: Mapped[str | None] = mapped_column(String(40))
    ultimo_erro_msg: Mapped[str | None] = mapped_column(Text)
    # Falhas seguidas: uma oscilação isolada não precisa virar alarme.
    falhas_consecutivas: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class SincronizacaoOCS(CreatedAtModel, Base):
    """Histórico de sincronizações — o que cada execução fez."""

    __tablename__ = "ocs_sincronizacoes"

    id: Mapped[int] = mapped_column(primary_key=True)
    # manual | automatico | simulacao
    origem: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    sucesso: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    novas: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    atualizadas: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ignoradas: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sem_planta: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    erros: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duracao_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mensagem: Mapped[str | None] = mapped_column(Text)
