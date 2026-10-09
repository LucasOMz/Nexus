"""Serviço de contador de páginas (domínio Impressora)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.core import Ativo
from app.models.impressora import LeituraContador


def register_leitura(
    db: Session,
    ativo: Ativo,
    contador: int,
    observacoes: str | None = None,
) -> LeituraContador:
    """Registra uma leitura e atualiza o contador atual da impressora."""
    leitura = LeituraContador(ativo_id=ativo.id, contador=contador, observacoes=observacoes)
    db.add(leitura)
    if ativo.impressora is not None:
        ativo.impressora.contador_paginas = contador
    db.flush()
    return leitura


def custo_por_pagina(total_custo: float, total_paginas: int) -> float:
    """Calcula custo por página (divisão segura)."""
    if total_paginas <= 0:
        return 0.0
    return round(total_custo / total_paginas, 4)
