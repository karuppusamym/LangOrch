"""Project CRUD service."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project


async def list_projects(db: AsyncSession) -> list[Project]:
    result = await db.execute(select(Project).order_by(Project.name))
    return list(result.scalars().all())


async def get_project(db: AsyncSession, project_id: str) -> Project | None:
    result = await db.execute(
        select(Project).where(Project.project_id == project_id)
    )
    return result.scalar_one_or_none()


async def create_project(db: AsyncSession, name: str, description: str | None = None) -> Project:
    proj = Project(name=name, description=description)
    db.add(proj)
    await db.flush()
    await db.refresh(proj)
    return proj


async def update_project(
    db: AsyncSession,
    project_id: str,
    name: str | None = None,
    description: str | None = None,
) -> Project | None:
    proj = await get_project(db, project_id)
    if not proj:
        return None
    if name is not None:
        proj.name = name
    if description is not None:
        proj.description = description
    await db.flush()
    await db.refresh(proj)
    return proj


async def delete_project(db: AsyncSession, project_id: str) -> bool:
    proj = await get_project(db, project_id)
    if not proj:
        return False
    await db.delete(proj)
    await db.flush()
    return True
