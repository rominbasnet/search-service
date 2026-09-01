import json
from pathlib import Path

from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk

from app.config import get_settings
from app.models import Product

settings = get_settings()
ES_SETTINGS_PATH = Path(__file__).parent.parent / "es" / "index_settings.json"


async def create_index_if_missing(es: AsyncElasticsearch) -> None:
    exists = await es.indices.exists(index=settings.index_name)
    if exists:
        return
    body = json.loads(ES_SETTINGS_PATH.read_text())
    await es.indices.create(index=settings.index_name, **body)


def product_to_doc(product: Product, popularity_score: float = 0.0) -> dict:
    return {
        "id": str(product.id),
        "name": product.name,
        "description": product.description,
        "brand": product.brand,
        "category": product.category,
        "price": product.price,
        "in_stock": product.in_stock,
        "stock_qty": product.stock_qty,
        "rating": product.rating,
        "popularity_score": popularity_score,
        "created_at": product.created_at.isoformat() if product.created_at else None,
    }


async def bulk_index_products(es: AsyncElasticsearch, products: list[Product]) -> None:
    actions = [
        {
            "_index": settings.index_name,
            "_id": str(p.id),
            "_source": product_to_doc(p),
        }
        for p in products
    ]
    await async_bulk(es, actions)
    await es.indices.refresh(index=settings.index_name)


async def update_popularity_scores(es: AsyncElasticsearch, scores: dict[str, float]) -> None:
    """Bulk-update just the popularity_score field -- called by the
    feedback-loop retraining job, not the main indexing path."""
    if not scores:
        return
    actions = [
        {
            "_op_type": "update",
            "_index": settings.index_name,
            "_id": product_id,
            "doc": {"popularity_score": score},
        }
        for product_id, score in scores.items()
    ]
    await async_bulk(es, actions)
    await es.indices.refresh(index=settings.index_name)
