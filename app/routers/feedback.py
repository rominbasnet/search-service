from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.feedback import record_click
from app.schemas import ClickFeedback

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("/click", status_code=204)
async def click(payload: ClickFeedback, db: AsyncSession = Depends(get_db)):
    await record_click(db, payload.search_id, payload.product_id, payload.position)
