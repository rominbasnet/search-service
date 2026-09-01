import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ProductCreate(BaseModel):
    name: str
    description: str | None = None
    brand: str | None = None
    category: str | None = None
    price: float = 0.0
    in_stock: bool = True
    stock_qty: int = 0
    rating: float = Field(default=0.0, ge=0.0, le=5.0)


class ProductOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    brand: str | None
    category: str | None
    price: float
    in_stock: bool
    stock_qty: int
    rating: float

    class Config:
        from_attributes = True


class SearchHit(BaseModel):
    product: ProductOut
    score: float
    position: int


class SearchResponse(BaseModel):
    search_id: uuid.UUID
    query: str
    total: int
    hits: list[SearchHit]
    did_you_mean: str | None = None


class ClickFeedback(BaseModel):
    search_id: uuid.UUID
    product_id: uuid.UUID
    position: int
