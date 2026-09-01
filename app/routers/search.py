from uuid import UUID

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.es_client import get_es
from app.feedback import record_impression
from app.models import Product, QueryBoost
from app.query_builder import build_search_query
from app.ranking import normalize_query
from app.schemas import SearchHit, SearchResponse, ProductOut

router = APIRouter(prefix="/search", tags=["search"])
settings = get_settings()


async def _load_query_boosts(session: AsyncSession, normalized_query: str) -> dict[str, float]:
    stmt = select(QueryBoost.product_id, QueryBoost.boost_score).where(
        QueryBoost.normalized_query == normalized_query
    )
    rows = (await session.execute(stmt)).all()
    return {str(pid): score for pid, score in rows}


@router.get("", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=1),
    in_stock_only: bool = False,
    category: str | None = None,
    max_price: float | None = None,
    size: int = 20,
    es: AsyncElasticsearch = Depends(get_es),
    db: AsyncSession = Depends(get_db),
):
    normalized = normalize_query(q)
    query_boosts = await _load_query_boosts(db, normalized)

    body = build_search_query(
        query=q,
        in_stock_only=in_stock_only,
        category=category,
        max_price=max_price,
        query_boosts=query_boosts,
        size=size,
    )

    es_response = await es.search(index=settings.index_name, body=body)
    hits_raw = es_response["hits"]["hits"]
    total = es_response["hits"]["total"]["value"]

    # Fetch full product rows from Postgres (source of truth) for the ids
    # ES returned. In a very high-QPS system you might instead trust the ES
    # _source for display and only hit Postgres for writes -- a reasonable
    # tradeoff, but this project favors Postgres-as-truth for clarity.
    product_ids = [UUID(h["_source"]["id"]) for h in hits_raw]
    products_by_id: dict[UUID, Product] = {}
    if product_ids:
        result = await db.execute(select(Product).where(Product.id.in_(product_ids)))
        products_by_id = {p.id: p for p in result.scalars().all()}

    result_ids_ordered = [str(pid) for pid in product_ids]
    search_id = await record_impression(db, raw_query=q, result_ids=result_ids_ordered)

    hits: list[SearchHit] = []
    for position, h in enumerate(hits_raw):
        pid = UUID(h["_source"]["id"])
        product = products_by_id.get(pid)
        if product is None:
            continue  # ES/Postgres drifted -- skip rather than crash
        hits.append(
            SearchHit(
                product=ProductOut.model_validate(product),
                score=h["_score"],
                position=position,
            )
        )

    did_you_mean = None
    suggest = es_response.get("suggest", {}).get("did_you_mean", [])
    if suggest and suggest[0].get("options"):
        top_option = suggest[0]["options"][0]
        if top_option["text"].lower() != q.lower():
            did_you_mean = top_option["text"]

    return SearchResponse(
        search_id=search_id,
        query=q,
        total=total,
        hits=hits,
        did_you_mean=did_you_mean,
    )
