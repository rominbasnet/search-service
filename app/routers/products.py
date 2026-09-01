from uuid import UUID

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.es_client import get_es
from app.indexing import bulk_index_products
from app.models import Product
from app.schemas import ProductCreate, ProductOut

router = APIRouter(prefix="/products", tags=["products"])


@router.post("", response_model=ProductOut, status_code=201)
async def create_product(
    payload: ProductCreate,
    db: AsyncSession = Depends(get_db),
    es: AsyncElasticsearch = Depends(get_es),
):
    product = Product(**payload.model_dump())
    db.add(product)
    await db.commit()
    await db.refresh(product)

    # NOTE: indexing synchronously on write is simple and fine for a demo /
    # moderate-volume catalog. At real scale you'd decouple this with an
    # outbox table + a worker (or Debezium/CDC off Postgres) so a slow or
    # down Elasticsearch never blocks product writes. Keeping the coupling
    # explicit here rather than hiding a queue makes the tradeoff visible.
    await bulk_index_products(es, [product])

    return product


@router.get("/{product_id}", response_model=ProductOut)
async def get_product(product_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.patch("/{product_id}/stock", response_model=ProductOut)
async def update_stock(
    product_id: UUID,
    in_stock: bool,
    stock_qty: int,
    db: AsyncSession = Depends(get_db),
    es: AsyncElasticsearch = Depends(get_es),
):
    """
    Dedicated endpoint for the most common high-frequency write (stock
    level changes) so it's obvious where the ES resync happens for the
    field that most directly affects the "in-stock ranks higher" boost.
    """
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    product.in_stock = in_stock
    product.stock_qty = stock_qty
    await db.commit()
    await db.refresh(product)

    await bulk_index_products(es, [product])
    return product
