"""
THE feedback loop. Run this on a schedule (cron every N minutes, or
Celery beat in prod). It reads click/impression history from Postgres
and produces two outputs:

  1. Per-product global popularity_score -> written into Elasticsearch,
     used by query_builder.py's function_score as a general quality signal.
  2. Per-(normalized_query, product) boost -> upserted into Postgres
     query_boosts, used by query_builder.py to add query-specific
     `should` boosts at search time.

Both use Bayesian-smoothed CTR (see app/ranking.py) so low-traffic
products/queries don't get wildly over- or under-boosted from noise.

Run: python scripts/recompute_ranking_signals.py
"""
import asyncio
import sys
from collections import defaultdict
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionFactory
from app.es_client import get_es
from app.indexing import update_popularity_scores
from app.models import ClickEvent, QueryBoost, SearchEvent
from app.ranking import position_bias_weight, smoothed_ctr

settings = get_settings()


async def compute_global_popularity(session) -> dict[str, float]:
    """
    Impressions per product: count how many times a product id appeared
    anywhere in any search_event.result_ids. Clicks per product: count of
    click_events, weighted down for late-position clicks (position bias).
    """
    impressions_by_product: dict[str, int] = defaultdict(int)
    clicks_by_product: dict[str, float] = defaultdict(float)

    search_events = (await session.execute(select(SearchEvent.result_ids))).scalars().all()
    for result_ids in search_events:
        for pid in result_ids:
            impressions_by_product[pid] += 1

    click_events = (await session.execute(select(ClickEvent.product_id, ClickEvent.position))).all()
    total_clicks = 0
    for product_id, position in click_events:
        clicks_by_product[str(product_id)] += position_bias_weight(position)
        total_clicks += 1

    total_impressions = sum(impressions_by_product.values())
    global_avg_ctr = (total_clicks / total_impressions) if total_impressions else 0.01

    popularity_scores: dict[str, float] = {}
    for product_id, impressions in impressions_by_product.items():
        clicks = clicks_by_product.get(product_id, 0.0)
        popularity_scores[product_id] = smoothed_ctr(
            clicks=clicks,
            impressions=impressions,
            global_avg_ctr=global_avg_ctr,
            virtual_impressions=settings.ctr_smoothing_virtual_impressions,
        )
    return popularity_scores


async def compute_query_specific_boosts(session) -> list[dict]:
    """
    For each (normalized_query, product) pair, compute a smoothed CTR
    specific to that query -- this is what lets "trainers" learn to boost
    a specific popular sneaker even if a differently-worded product
    technically text-matches slightly better.
    """
    impressions: dict[tuple[str, str], int] = defaultdict(int)
    clicks: dict[tuple[str, str], float] = defaultdict(float)

    search_events = (
        await session.execute(select(SearchEvent.id, SearchEvent.normalized_query, SearchEvent.result_ids))
    ).all()
    search_id_to_query: dict[UUID, str] = {}
    for search_id, normalized_query, result_ids in search_events:
        search_id_to_query[search_id] = normalized_query
        for pid in result_ids:
            impressions[(normalized_query, pid)] += 1

    click_events = (
        await session.execute(select(ClickEvent.search_event_id, ClickEvent.product_id, ClickEvent.position))
    ).all()
    total_clicks = 0
    for search_event_id, product_id, position in click_events:
        normalized_query = search_id_to_query.get(search_event_id)
        if normalized_query is None:
            continue
        key = (normalized_query, str(product_id))
        clicks[key] += position_bias_weight(position)
        total_clicks += 1

    total_impressions = sum(impressions.values())
    global_avg_ctr = (total_clicks / total_impressions) if total_impressions else 0.01

    rows = []
    for (normalized_query, product_id), impression_count in impressions.items():
        click_count = clicks.get((normalized_query, product_id), 0.0)
        ctr = smoothed_ctr(
            clicks=click_count,
            impressions=impression_count,
            global_avg_ctr=global_avg_ctr,
            virtual_impressions=settings.ctr_smoothing_virtual_impressions,
        )
        # Only worth storing (and querying at search time) if it's
        # meaningfully above baseline -- keeps the query_boosts table
        # from filling up with noise-level entries.
        if ctr > global_avg_ctr * 1.2:
            rows.append(
                dict(
                    normalized_query=normalized_query,
                    product_id=product_id,
                    boost_score=round(ctr * 10, 4),  # scaled for use as an ES boost weight
                    impressions=impression_count,
                    clicks=int(click_count),
                )
            )
    return rows


async def upsert_query_boosts(session, rows: list[dict]) -> None:
    for row in rows:
        existing = (
            await session.execute(
                select(QueryBoost).where(
                    QueryBoost.normalized_query == row["normalized_query"],
                    QueryBoost.product_id == row["product_id"],
                )
            )
        ).scalar_one_or_none()
        if existing:
            existing.boost_score = row["boost_score"]
            existing.impressions = row["impressions"]
            existing.clicks = row["clicks"]
        else:
            session.add(QueryBoost(**row))
    await session.commit()


async def main():
    async with SessionFactory() as session:
        popularity_scores = await compute_global_popularity(session)
        query_boost_rows = await compute_query_specific_boosts(session)
        await upsert_query_boosts(session, query_boost_rows)

    es = get_es()
    await update_popularity_scores(es, popularity_scores)
    await es.close()

    print(f"Updated popularity_score for {len(popularity_scores)} products.")
    print(f"Upserted {len(query_boost_rows)} query-specific boosts.")


if __name__ == "__main__":
    asyncio.run(main())
