"""Projects — CRUD."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_org_id
from app.db.models.project import Project
from app.db.session import get_db

router = APIRouter()


class ProjectCreate(BaseModel):
    name: str
    client_id: UUID | None = None
    project_type: str | None = None
    estimated_value: Decimal | None = None
    estimated_value_ccy: str = "EUR"
    deadline_at: datetime | None = None
    site_country: str | None = None
    urgency: str = "normal"


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    status: str
    project_type: str | None = None
    client_id: UUID | None = None
    estimated_value: Decimal | None = None
    estimated_value_ccy: str | None = None
    deadline_at: datetime | None = None
    urgency: str | None = None
    created_at: datetime


class ProjectUpdate(BaseModel):
    name: str | None = None
    status: str | None = None
    project_type: str | None = None
    estimated_value: Decimal | None = None
    urgency: str | None = None


@router.get("/", response_model=list[ProjectResponse])
async def list_projects(
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> list[Project]:
    result = await db.execute(
        select(Project).where(Project.org_id == org_id).order_by(Project.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    req: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> Project:
    project = Project(
        org_id=org_id,
        name=req.name,
        client_id=req.client_id,
        project_type=req.project_type,
        estimated_value=req.estimated_value,
        estimated_value_ccy=req.estimated_value_ccy,
        deadline_at=req.deadline_at,
        site_country=req.site_country,
        urgency=req.urgency,
        status="draft",
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> Project:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.org_id == org_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Projekt nije pronađen.")
    return project


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    req: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> Project:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.org_id == org_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Projekt nije pronađen.")
    for field, value in req.model_dump(exclude_none=True).items():
        setattr(project, field, value)
    await db.commit()
    await db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> None:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.org_id == org_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Projekt nije pronađen.")
    await db.delete(project)
    await db.commit()
