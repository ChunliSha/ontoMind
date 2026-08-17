from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.dashboard import DashboardActivity, DashboardSummary
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
svc = DashboardService()


@router.get("/summary", response_model=DashboardSummary)
async def summary(session: AsyncSession = Depends(get_session)):
    return await svc.summary(session)


@router.get("/activity", response_model=DashboardActivity)
async def activity(
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    return await svc.activity(session, limit=limit)
