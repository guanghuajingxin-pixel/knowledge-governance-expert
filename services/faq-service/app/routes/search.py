from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from app.deps import get_current_user
from app.services import faq_search
import uuid

router = APIRouter(prefix="/api/v1/faq/search", tags=["faq-search"])

class Q(BaseModel):
    kb_id: str
    query: str
    top_k: int = 5

@router.post("")
async def do(body: Q, u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    return await faq_search.search(s, body.kb_id, body.query, body.top_k)
