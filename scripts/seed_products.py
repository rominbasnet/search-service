"""
Seed a small sample catalog into Postgres, then index it into Elasticsearch.
Run: python scripts/seed_products.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionFactory, Base, engine
from app.es_client import get_es
from app.indexing import create_index_if_missing, bulk_index_products
from app.models import Product

SAMPLE_PRODUCTS = [
    dict(name="Nike Air Zoom Pegasus", description="Lightweight running shoe with responsive cushioning",
         brand="Nike", category="footwear", price=129.99, in_stock=True, stock_qty=42, rating=4.6),
    dict(name="Adidas Ultraboost Trainer", description="Everyday trainer built for comfort and energy return",
         brand="Adidas", category="footwear", price=179.99, in_stock=True, stock_qty=15, rating=4.4),
    dict(name="Classic Canvas Sneaker", description="Timeless low-top sneaker for everyday wear",
         brand="Converse", category="footwear", price=59.99, in_stock=False, stock_qty=0, rating=4.1),
    dict(name="Samsung 55-inch 4K TV", description="Crisp 4K television with HDR support",
         brand="Samsung", category="electronics", price=549.99, in_stock=True, stock_qty=8, rating=4.5),
    dict(name="LG OLED Television 65in", description="Premium OLED TV with perfect blacks",
         brand="LG", category="electronics", price=1499.99, in_stock=True, stock_qty=3, rating=4.8),
    dict(name="Dell XPS Notebook Computer", description="Slim laptop for professionals, 16GB RAM",
         brand="Dell", category="electronics", price=1199.99, in_stock=True, stock_qty=20, rating=4.3),
    dict(name="Sony Wireless Headphones", description="Noise-cancelling over-ear headphones",
         brand="Sony", category="electronics", price=349.99, in_stock=True, stock_qty=60, rating=4.7),
    dict(name="Budget Earphones", description="Affordable wired earphones with decent sound",
         brand="Generic", category="electronics", price=14.99, in_stock=True, stock_qty=200, rating=3.4),
    dict(name="Mid-Century Sofa", description="Three-seat sofa with wooden legs and linen upholstery",
         brand="Article", category="furniture", price=899.0, in_stock=True, stock_qty=5, rating=4.2),
    dict(name="Compact Refrigerator", description="Energy-efficient fridge for small kitchens",
         brand="Frigidaire", category="appliances", price=249.99, in_stock=True, stock_qty=12, rating=4.0),
]


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionFactory() as session:
        products = [Product(**data) for data in SAMPLE_PRODUCTS]
        session.add_all(products)
        await session.commit()
        for p in products:
            await session.refresh(p)

    es = get_es()
    await create_index_if_missing(es)
    await bulk_index_products(es, products)
    await es.close()

    print(f"Seeded {len(products)} products into Postgres + Elasticsearch.")


if __name__ == "__main__":
    asyncio.run(main())
