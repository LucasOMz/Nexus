"""Mede cada consulta SQL executada pelo endpoint de gráficos."""
from __future__ import annotations

import os
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.environ["DATABASE_URL"] = "sqlite:///./loadtest50.db"

from sqlalchemy import event  # noqa: E402

from app.database import SessionLocal, engine  # noqa: E402

CUSTOS: list[tuple[float, str]] = []


@event.listens_for(engine, "before_cursor_execute")
def _antes(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
    context._t0 = time.perf_counter()


@event.listens_for(engine, "after_cursor_execute")
def _depois(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
    CUSTOS.append(((time.perf_counter() - context._t0) * 1000, " ".join(statement.split())))


db = SessionLocal()
# Usuário administrador real do banco de teste.
from app.models.core import Usuario  # noqa: E402
from app.models.enums import Dominio  # noqa: E402

admin = db.query(Usuario).filter(Usuario.papel == "admin").first()

from app.routers.graficos import graficos  # noqa: E402

CUSTOS.clear()
t = time.perf_counter()
graficos(dominio=Dominio.TI, meses=6, db=db, user=admin)
total = (time.perf_counter() - t) * 1000

print(f"=== ENDPOINT /relatorios/graficos: {total:.0f}ms em {len(CUSTOS)} consultas ===\n")
print(f"{'ms':>8}  consulta")
print("-" * 100)
for ms, sql in sorted(CUSTOS, reverse=True)[:12]:
    print(f"{ms:>7.0f}  {sql[:92]}")

soma = sum(ms for ms, _ in CUSTOS)
print(f"\nSoma das consultas: {soma:.0f}ms    resto (Python/serialização): {total - soma:.0f}ms")
db.close()
