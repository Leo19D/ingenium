"""Document upload, listing, and deletion."""

from __future__ import annotations

import hashlib
import uuid as uuid_module
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_org_id, get_current_user
from app.db.models.document import Document
from app.db.models.user import User
from app.db.session import get_db

router = APIRouter()

UPLOAD_DIR = Path("uploads")
ALLOWED_MIME = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "text/csv",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
MAX_SIZE_MB = 25


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    filename: str
    mime_type: str | None = None
    size_bytes: int | None = None
    status: str
    source: str | None = None
    project_id: UUID | None = None
    created_at: str = ""

    @classmethod
    def from_doc(cls, d: Document) -> "DocumentResponse":
        return cls(
            id=d.id,
            filename=d.filename,
            mime_type=d.mime_type,
            size_bytes=d.size_bytes,
            status=d.status,
            source=d.source,
            project_id=d.project_id,
            created_at=d.created_at.isoformat() if d.created_at else "",
        )


@router.get("/", response_model=list[DocumentResponse])
async def list_documents(
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> list[DocumentResponse]:
    result = await db.execute(
        select(Document).where(Document.org_id == org_id).order_by(Document.created_at.desc())
    )
    return [DocumentResponse.from_doc(d) for d in result.scalars().all()]


@router.post("/upload", status_code=status.HTTP_201_CREATED, response_model=DocumentResponse)
async def upload_document(
    file: Annotated[UploadFile, File()],
    project_id: Annotated[str | None, Form()] = None,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
    current_user: User = Depends(get_current_user),
) -> DocumentResponse:
    """Upload PDF, XLSX, CSV, DOCX dokumenta."""
    content = await file.read()
    size = len(content)

    if size > MAX_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Fajl je prevelik. Maksimum je {MAX_SIZE_MB} MB.",
        )

    mime = file.content_type or "application/octet-stream"
    if mime not in ALLOWED_MIME:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Tip fajla nije podržan. Dozvoljeni: PDF, XLSX, CSV, DOCX.",
        )

    checksum = hashlib.sha256(content).hexdigest()
    file_id = uuid_module.uuid4()
    suffix = Path(file.filename or "upload").suffix or ".bin"
    storage_key = f"{org_id}_{file_id}{suffix}"

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (UPLOAD_DIR / storage_key).write_bytes(content)

    proj_id: UUID | None = None
    if project_id:
        try:
            proj_id = UUID(project_id)
        except ValueError:
            pass

    doc = Document(
        org_id=org_id,
        project_id=proj_id,
        uploaded_by=current_user.id,
        storage_key=storage_key,
        filename=file.filename or "upload",
        mime_type=mime,
        size_bytes=size,
        checksum=checksum,
        source="upload",
        status="received",
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return DocumentResponse.from_doc(doc)


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> None:
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.org_id == org_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Dokument nije pronađen.")
    local = UPLOAD_DIR / doc.storage_key
    if local.exists():
        local.unlink()
    await db.delete(doc)
    await db.commit()
