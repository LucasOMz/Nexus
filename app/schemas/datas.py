"""Datas com fuso explícito na API.

O banco (SQLite) grava `func.now()` sem fuso, e o valor é **UTC**. Enviar isso
"cru" no JSON (`2026-10-06T00:12:04`) faz o navegador interpretar como hora
LOCAL — no horário de Brasília a tela mostrava 3 horas à frente do relógio.

Marcando o fuso (`+00:00`), o navegador converte sozinho para a hora do
equipamento e o horário exibido passa a bater com o relógio.
"""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, field_serializer


class DatasComFuso(BaseModel):
    """Mixin para schemas de SAÍDA: todo datetime sai com fuso (UTC).

    Usa o serializador curinga para valer em qualquer campo de data, inclusive
    os que forem adicionados depois — sem precisar lembrar de anotar cada um.
    """

    @field_serializer("*", check_fields=False)
    def _serializar_datas_em_utc(self, valor, _info):  # noqa: ANN001
        if isinstance(valor, datetime):
            # Datas sem fuso vindas do banco são UTC por convenção do sistema.
            if valor.tzinfo is None:
                valor = valor.replace(tzinfo=timezone.utc)
            return valor.isoformat()
        # Qualquer outro tipo segue o caminho normal do Pydantic.
        return valor
