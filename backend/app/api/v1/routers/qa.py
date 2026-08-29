"""Knowledge QA REST API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session as get_db
from app.qa.agent import QaAgent
from app.schemas.common import PageResponse
from app.schemas.qa import (
    QaChatRequest,
    QaChatResponse,
    QaSessionCreate,
    QaSessionRead,
    QaSessionSummary,
    QaSessionUpdate,
)

router = APIRouter(prefix="/ontology-apps/qa", tags=["ontology-apps-qa"])
agent = QaAgent()


class QaChatBody(BaseModel):
    ontology_model_id: str
    question: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None
    model_id: str | None = None


@router.post("/sessions", response_model=QaSessionRead)
async def create_session(body: QaSessionCreate, db: AsyncSession = Depends(get_db)):
    return await agent.create_session(db, body.ontology_model_id, model_id=body.model_id)


@router.get("/sessions", response_model=PageResponse[QaSessionSummary])
async def list_sessions(
    ontology_model_id: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    return await agent.list_sessions(
        db, ontology_model_id=ontology_model_id, page=page, page_size=page_size
    )


@router.get("/sessions/{id}", response_model=QaSessionRead)
async def get_qa_session(id: str, db: AsyncSession = Depends(get_db)):
    return await agent.get_session(db, id)


@router.patch("/sessions/{id}", response_model=QaSessionRead)
async def update_session(id: str, body: QaSessionUpdate, db: AsyncSession = Depends(get_db)):
    return await agent.update_session(db, id, title=body.title)


@router.delete("/sessions/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(id: str, db: AsyncSession = Depends(get_db)):
    await agent.delete_session(db, id)


@router.post("/sessions/{id}/messages", response_model=QaChatResponse)
async def post_message(
    id: str, body: QaChatRequest, db: AsyncSession = Depends(get_db)
):
    return await agent.chat(db, id, body.question, model_id=body.model_id)


@router.post("/chat", response_model=QaChatResponse)
async def chat(body: QaChatBody, db: AsyncSession = Depends(get_db)):
    sid = body.session_id
    if not sid:
        created = await agent.create_session(
            db, body.ontology_model_id, model_id=body.model_id
        )
        sid = created.id
    return await agent.chat(db, sid, body.question, model_id=body.model_id)
