import uuid
from datetime import datetime

from sqlalchemy import String, Float, Integer, Boolean, DateTime, ForeignKey, func, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Product(Base):
    """
    System of record for product data. The Elasticsearch document is a
    derived projection of this row (plus popularity_score, which is
    computed FROM click data and lives authoritatively... also in Postgres,
    in query_boosts/aggregate form -- ES just holds the latest computed
    value for fast scoring at query time).
    """
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(String(4000), nullable=True)
    brand: Mapped[str] = mapped_column(String(255), nullable=True)
    category: Mapped[str] = mapped_column(String(255), nullable=True)
    price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    in_stock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    stock_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rating: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SearchEvent(Base):
    """
    One row per search request -- an "impression" of the ranked result
    list. `result_ids` preserves the exact order shown, so later click
    events can be tied back to a rank position for CTR-by-position analysis
    (position bias is real: position 1 gets clicked more even when it's
    not more relevant, so naive raw-click-count ranking would just
    reinforce whatever was already on top).
    """
    __tablename__ = "search_events"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    raw_query: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_query: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    result_ids: Mapped[list] = mapped_column(JSONB, nullable=False)  # ordered list of product id strings
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClickEvent(Base):
    __tablename__ = "click_events"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    search_event_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("search_events.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QueryBoost(Base):
    """
    Feedback-loop output #1: per-(query, product) learned relevance boost.
    Recomputed periodically by scripts/recompute_ranking_signals.py from
    click_events, and applied at search time in query_builder.py as extra
    `should` clauses -- "people who searched this query tended to click
    this product, even if it's not the best text match".
    """
    __tablename__ = "query_boosts"
    __table_args__ = (UniqueConstraint("normalized_query", "product_id", name="uq_query_product"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    normalized_query: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    boost_score: Mapped[float] = mapped_column(Float, nullable=False)
    impressions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
