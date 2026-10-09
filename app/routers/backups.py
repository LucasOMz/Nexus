"""Backups e exportação/importação CSV (Administração)."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.core.security import verify_password
from app.database import get_db
from app.models.core import Usuario
from app.services import backup_service, csv_service
from app.services.audit_service import audit

router = APIRouter(prefix="/admin", tags=["backups"])


class RestaurarRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arquivo: str = Field(min_length=1)
    senha: str = Field(min_length=1)
    confirmacao: str = Field(min_length=1)


class ValidarRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arquivo: str = Field(min_length=1)


class BackupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    motivo: str = "manual"


# ---------------------------------------------------------------------------
# Backups
# ---------------------------------------------------------------------------
@router.get("/backups")
def listar_backups(_: Usuario = Depends(require_admin)) -> dict:
    """Status + lista dos backups encontrados na pasta configurada."""
    return {"status": backup_service.status_backup(), "itens": backup_service.listar_backups()}


@router.post("/backups")
def criar_backup(
    body: BackupRequest, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_admin)
) -> dict:
    """Cria um backup agora (útil antes de uma manutenção)."""
    try:
        meta = backup_service.criar_backup(motivo=body.motivo or "manual")
    except (OSError, RuntimeError) as exc:
        raise HTTPException(500, f"Falha ao gerar o backup: {exc}")
    audit(db, user, "backup", "sistema", None, ip=request.client.host if request.client else None,
          diff={"arquivo": meta.get("arquivo")})
    db.commit()
    return meta


@router.get("/backups/{nome}/download")
def baixar_backup(nome: str, _: Usuario = Depends(require_admin)) -> FileResponse:
    try:
        arquivo, _meta = backup_service._resolver(nome)  # noqa: SLF001 - acesso interno proposital
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    return FileResponse(str(arquivo), media_type="application/octet-stream", filename=arquivo.name)


@router.post("/backups/validar")
def validar_backup(body: ValidarRequest, _: Usuario = Depends(require_admin)) -> dict:
    """Valida o backup restaurando num banco TEMPORÁRIO — não altera nada."""
    try:
        return backup_service.validar_backup(body.arquivo)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except (OSError, RuntimeError) as exc:
        raise HTTPException(500, f"Falha na validação: {exc}")


@router.post("/backups/restaurar")
def restaurar_backup(
    body: RestaurarRequest, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_admin)
) -> dict:
    """Restaura um backup, com todas as travas de segurança.

    Exige a senha do administrador e a palavra RESTAURAR. Antes de qualquer
    coisa, gera um backup do estado atual (permite voltar atrás).
    """
    if body.confirmacao.strip().upper() != "RESTAURAR":
        raise HTTPException(400, 'Digite exatamente "RESTAURAR" para confirmar.')
    if not verify_password(body.senha, user.senha_hash):
        raise HTTPException(403, "Senha incorreta.")

    try:
        resultado = backup_service.restaurar_backup(body.arquivo)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except (OSError, RuntimeError) as exc:
        raise HTTPException(500, f"Falha na restauração: {exc}")

    # Auditoria: registrado no banco restaurado (o usuário pode não existir mais lá).
    try:
        audit(db, user, "restaurar_backup", "sistema", None,
              ip=request.client.host if request.client else None,
              diff={"arquivo": body.arquivo, "ok": resultado.get("ok")})
        db.commit()
    except Exception:  # noqa: BLE001 - a restauração já ocorreu; auditoria é best-effort
        db.rollback()
    return resultado


# ---------------------------------------------------------------------------
# CSV total (exportar / importar)
# ---------------------------------------------------------------------------
@router.get("/exportar")
def exportar(db: Session = Depends(get_db), _: Usuario = Depends(require_admin)) -> Response:
    """Exporta TODAS as tabelas em um ZIP com um CSV por tabela."""
    conteudo = csv_service.exportar_zip(db)
    return Response(
        content=conteudo,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="gestao-patrimonial-csv.zip"'},
    )


@router.post("/importar")
async def importar(
    request: Request,
    file: UploadFile = File(...),
    dry_run: bool = True,
    atualizar: bool = False,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    """Importa o ZIP do CSV total, validando e removendo duplicados.

    Por padrão roda em **simulação** (`dry_run=true`), devolvendo o relatório do
    que seria feito. Para aplicar de verdade, envie `dry_run=false`.
    """
    conteudo = await file.read()
    if not conteudo:
        raise HTTPException(400, "Arquivo vazio.")
    try:
        resultado = csv_service.importar_zip(db, conteudo, dry_run=dry_run, atualizar=atualizar)
    except Exception as exc:  # noqa: BLE001 - devolve erro claro ao operador
        db.rollback()
        raise HTTPException(400, f"Não foi possível importar: {exc}")

    if not dry_run:
        audit(db, user, "importar_csv", "sistema", None,
              ip=request.client.host if request.client else None, diff=resultado.get("totais"))
        db.commit()
    return resultado


@router.get("/exportar/tamanho")
def tamanho_export(_: Usuario = Depends(require_admin)) -> dict:
    """Informação auxiliar: pasta de backups configurada e retenção."""
    return {
        "pasta_backups": backup_service.pasta_backups().as_posix(),
        "retencao": backup_service.settings.backup_reter,
        "grava_em_rede": os.path.sep not in backup_service.settings.backup_path.rstrip("/\\"),
    }
