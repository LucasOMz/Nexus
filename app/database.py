"""Motor e sessão do SQLAlchemy 2.0.

A URL vem de `settings.database_url`. No dev usamos SQLite (arquivo local);
em produção, PostgreSQL 16 via docker-compose. O mesmo código funciona nos
dois bancos graças aos tipos portáteis definidos em `app.models.base`.
"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

# SQLite exige check_same_thread=False quando usado com FastAPI (threads).
_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


def caminho_sqlite() -> str | None:
    """Caminho do arquivo quando o banco é SQLite (None no PostgreSQL)."""
    if not settings.database_url.startswith("sqlite"):
        return None
    # sqlite:///./estoque.db  ->  ./estoque.db
    return settings.database_url.split("sqlite:///", 1)[-1]


def recriar_engine() -> None:
    """Recria o engine/conexões — usado depois de restaurar um backup.

    O `SessionLocal` é reconfigurado no lugar (e não recriado) para que as
    referências já importadas pelos outros módulos continuem válidas.
    """
    global engine
    engine.dispose()
    engine = create_engine(
        settings.database_url,
        connect_args=_connect_args,
        pool_pre_ping=True,
        future=True,
    )
    SessionLocal.configure(bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Dependência FastAPI que fornece uma sessão por request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _default_sql(coluna, dialeto: str) -> str:  # noqa: ANN001 - Column do SQLAlchemy
    """Valor DEFAULT para uma coluna nova que seja NOT NULL."""
    padrao = getattr(coluna, "default", None)
    arg = getattr(padrao, "arg", None)
    if arg is not None and not callable(arg):
        if isinstance(arg, bool):
            return "TRUE" if arg else "FALSE" if dialeto == "postgresql" else ("1" if arg else "0")
        if isinstance(arg, (int, float)):
            return str(arg)
        if isinstance(arg, str):
            return "'" + arg.replace("'", "''") + "'"
    # Fallback pelo tipo da coluna.
    tipo = type(coluna.type).__name__.lower()
    if "bool" in tipo:
        return "FALSE" if dialeto == "postgresql" else "0"
    if any(t in tipo for t in ("int", "float", "numeric", "decimal")):
        return "0"
    if "datetime" in tipo or "date" in tipo:
        return "CURRENT_TIMESTAMP"
    if "json" in tipo:
        return "'{}'::jsonb" if dialeto == "postgresql" else "'{}'"
    return "''"


def _adicionar_colunas_faltantes(bind) -> list[str]:  # noqa: ANN001
    """Adiciona colunas presentes nos modelos mas ausentes no banco.

    Permite evoluir o sistema **sem apagar o banco** (o que era necessário nas
    versões anteriores). Não substitui o Alembic em produção: só adiciona
    colunas novas, nunca altera tipo nem remove nada.
    """
    from sqlalchemy import inspect, text

    from app.models import Base

    inspetor = inspect(bind)
    dialeto = bind.dialect.name
    adicionadas: list[str] = []

    for nome_tabela, tabela in Base.metadata.tables.items():
        if not inspetor.has_table(nome_tabela):
            continue
        existentes = {col["name"] for col in inspetor.get_columns(nome_tabela)}
        for coluna in tabela.columns:
            if coluna.name in existentes:
                continue
            ddl = f'ALTER TABLE "{nome_tabela}" ADD COLUMN "{coluna.name}" {coluna.type.compile(dialect=bind.dialect)}'
            if not coluna.nullable:
                ddl += f" DEFAULT {_default_sql(coluna, dialeto)}"
            try:
                with bind.begin() as conn:
                    conn.execute(text(ddl))
                adicionadas.append(f"{nome_tabela}.{coluna.name}")
            except Exception:  # noqa: BLE001 - coluna problemática não deve impedir o boot
                continue
    return adicionadas


def _criar_indices_faltantes(bind) -> list[str]:  # noqa: ANN001
    """Cria índices presentes nos modelos mas ausentes no banco.

    `create_all` **não** adiciona índices a tabelas que já existem — então uma
    instalação antiga jamais receberia um índice novo, e continuaria lenta
    mesmo depois de atualizar o sistema. Este passo fecha essa lacuna.
    """
    from sqlalchemy import inspect

    from app.models import Base

    inspetor = inspect(bind)
    criados: list[str] = []

    for tabela in Base.metadata.tables.values():
        if not inspetor.has_table(tabela.name):
            continue
        existentes = {i["name"] for i in inspetor.get_indexes(tabela.name)}
        for indice in tabela.indexes:
            if indice.name in existentes:
                continue
            try:
                indice.create(bind, checkfirst=True)
                criados.append(indice.name)
            except Exception:  # noqa: BLE001 - índice problemático não deve impedir o boot
                continue
    return criados


def _tem_estatisticas(bind) -> bool:  # noqa: ANN001
    """Já existe `sqlite_stat1`? (o ANALYZE cria essa tabela)."""
    try:
        from sqlalchemy import inspect

        return inspect(bind).has_table("sqlite_stat1")
    except Exception:  # noqa: BLE001
        return False


def _analisar(bind) -> None:  # noqa: ANN001
    """Atualiza as estatísticas que o planejador usa para escolher os índices.

    No SQLite é o `ANALYZE`; em outros bancos o equivalente seria o `VACUUM
    ANALYZE`/`pg_statistic`. Silencioso se o banco não suportar.
    """
    from sqlalchemy import text

    if bind.dialect.name != "sqlite":
        return
    with bind.begin() as conn:
        conn.execute(text("ANALYZE"))


def init_db() -> None:
    """Cria/atualiza o schema e garante o usuário administrador inicial.

    `create_all` cria tabelas novas; `_adicionar_colunas_faltantes` cobre as
    colunas novas em tabelas que já existiam — assim uma atualização do sistema
    não exige apagar o banco. Em produção recomenda-se o Alembic.
    """
    # Importa os modelos para registrá-los no metadata.
    import logging

    from app.models import Base

    Base.metadata.create_all(bind=engine)
    novas = _adicionar_colunas_faltantes(engine)
    if novas:
        logging.getLogger("app").info("Colunas adicionadas automaticamente: %s", ", ".join(novas))

    indices = _criar_indices_faltantes(engine)
    if indices:
        logging.getLogger("app").info("Índices criados automaticamente: %s", ", ".join(indices))

    # Estatísticas do planejador. Medido com 50 mil ativos: sem ANALYZE o banco
    # escolhe planos ruins e os relatórios ficam ~3x mais lentos, mesmo com os
    # índices certos. Roda só quando algo mudou (índices novos ou banco novo).
    if indices or not _tem_estatisticas(engine):
        try:
            _analisar(engine)
            logging.getLogger("app").info("Estatísticas do banco atualizadas (ANALYZE).")
        except Exception as exc:  # noqa: BLE001 - não deve impedir o boot
            logging.getLogger("app").warning("ANALYZE falhou: %s", exc)

    # Seed do usuário administrador inicial.
    from app.core.security import hash_password
    from app.models.core import Ativo, DispositivoImpressao, Planta, QRZerado, Usuario

    with SessionLocal() as db:
        # --- Planta padrão ---------------------------------------------------
        # Todo ativo pertence a uma planta. Uma instalação nova (ou que veio de
        # uma versão anterior, sem plantas) ganha a "Matriz", e todo registro
        # existente é vinculado a ela — sem perder nada.
        planta = db.query(Planta).order_by(Planta.id).first()
        if planta is None:
            planta = Planta(nome="Central-SP", sigla="Central-SP", ativa=True)
            db.add(planta)
            db.flush()
            logging.getLogger("app").info("Planta padrão criada: %s", planta.sigla)
        elif planta.sigla == "MAT" and planta.nome == "Matriz":
            # Banco que já subiu com o nome provisório: renomeia para o real.
            planta.nome = "Central-SP"
            planta.sigla = "Central-SP"
            logging.getLogger("app").info("Planta padrão renomeada para Central-SP")

        for modelo in (Ativo, QRZerado, DispositivoImpressao):
            atualizados = (
                db.query(modelo).filter(modelo.planta_id.is_(None)).update({"planta_id": planta.id})
            )
            if atualizados:
                logging.getLogger("app").info(
                    "%s registro(s) de %s vinculados à planta %s", atualizados, modelo.__tablename__, planta.sigla
                )

        # --- Usuário administrador inicial -----------------------------------
        admin = db.query(Usuario).filter(Usuario.email == settings.seed_admin_email).first()
        if not admin:
            db.add(
                Usuario(
                    nome="Administrador",
                    email=settings.seed_admin_email,
                    senha_hash=hash_password(settings.seed_admin_password),
                    papel="admin",
                    ativo=True,
                    origem="local",
                    # O admin fica SEM planta: assim enxerga todas e pode
                    # escolher qual acessar no seletor do topo.
                )
            )
        db.commit()
