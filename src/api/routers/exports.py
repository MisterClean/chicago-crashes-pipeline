"""Authenticated durable exports; the browser downloads directly from the bucket."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.routers.dashboard import LocationReportExportRequest
from src.models.base import get_db
from src.models.exports import ExportJob
from src.services.export_service import submit_export, utcnow
from src.services.object_storage import ExportSettings, ObjectStorage

router = APIRouter(prefix="/exports", tags=["exports"])


def _status(job: ExportJob) -> dict:
    expired = job.expires_at <= utcnow()
    return {
        "id": job.id,
        "status": "expired" if expired else job.status,
        "created_at": job.created_at,
        "expires_at": job.expires_at,
        "error": job.error,
        "manifest": job.manifest,
        "download_url": f"/exports/{job.id}/download"
        if not expired and job.status == "completed"
        else None,
    }


@router.post("", status_code=202)
def create_export(
    request: LocationReportExportRequest, db: Session = Depends(get_db)
) -> dict:
    settings = ExportSettings()
    if not settings.configured():
        raise HTTPException(503, "Export storage is not configured")
    try:
        return _status(submit_export(db, request, settings))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc


@router.get("/{export_id}")
def export_status(export_id: str, db: Session = Depends(get_db)) -> dict:
    job = db.get(ExportJob, export_id)
    if job is None:
        raise HTTPException(404, "Export not found")
    return _status(job)


@router.get("/{export_id}/download")
def download_export(export_id: str, db: Session = Depends(get_db)) -> dict:
    job = db.get(ExportJob, export_id)
    if job is None:
        raise HTTPException(404, "Export not found")
    if job.expires_at <= utcnow() or job.status == "expired":
        raise HTTPException(410, "Export expired; create another export")
    if job.status != "completed" or job.object_key is None:
        raise HTTPException(409, "Export is not ready")
    remaining = max(1, int((job.expires_at - utcnow()).total_seconds()))
    return {
        "url": ObjectStorage(ExportSettings()).signed_download(
            job.object_key, expires_seconds=min(300, remaining)
        )
    }
