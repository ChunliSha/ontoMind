import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.business_logic import BusinessLogicRuleRead
from app.services.business_logic_service import BusinessLogicService

router = APIRouter(prefix="/business-logic-rules", tags=["business-logic"])
svc = BusinessLogicService()


@router.get("", response_model=list[BusinessLogicRuleRead])
async def list_rules(schema_id: str = Query(...), session: AsyncSession = Depends(get_session)):
    return await svc.list_by_schema(session, schema_id)


@router.get("/export")
async def export_rules(
    schema_id: str = Query(...),
    format: str = Query("json"),
    session: AsyncSession = Depends(get_session),
):
    data = await svc.export(session, schema_id)
    content = json.dumps(data.model_dump(), ensure_ascii=False, indent=2)
    return Response(
        content=content.encode("utf-8"),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="business_logic.json"'},
    )
