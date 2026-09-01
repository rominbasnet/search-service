import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SearchEvent, ClickEvent
from app.ranking import normalize_query


async def record_impression(session: AsyncSession, raw_query: str, result_ids: list[str]) -> uuid.UUID:
    event = SearchEvent(
        raw_query=raw_query,
        normalized_query=normalize_query(raw_query),
        result_ids=result_ids,
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return event.id


async def record_click(
    session: AsyncSession, search_id: uuid.UUID, product_id: uuid.UUID, position: int
) -> None:
    click = ClickEvent(search_event_id=search_id, product_id=product_id, position=position)
    session.add(click)
    await session.commit()
