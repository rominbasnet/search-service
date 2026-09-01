"""
Rebuild the Elasticsearch index entirely from Postgres (source of truth).
Use this after a mapping change, or to recover from a lost/corrupted index.
Run: python scripts/reindex.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionFactory
from app.es_client import get_es
from app.indexing import create_index_if_missing, bulk_index_products
from app.models import Product

settings = get_settings()


async def main():
    es = get_es()

    # Drop and recreate to pick up any mapping/analyzer changes cleanly.
    if await es.indices.exists(index=settings.index_name):
        await es.indices.delete(index=settings.index_name)
    await create_index_if_missing(es)

    async with SessionFactory() as session:
        result = await session.execute(select(Product))
        products = result.scalars().all()

    await bulk_index_products(es, products)
    await es.close()
    print(f"Reindexed {len(products)} products from Postgres.")


if __name__ == "__main__":
    asyncio.run(main())
