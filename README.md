# Search-as-a-Service — FastAPI + Elasticsearch

Relevance engineering, not just "hook up a search box": synonym expansion,
typo tolerance, business-logic boosting, and a real click-through feedback
loop that retrains ranking signals over time.

## Why Elasticsearch over Meilisearch here

Meilisearch is excellent for "fast, good-enough, minimal config" search.
This project specifically needs things Meilisearch doesn't expose:
`function_score` with multiple independent boost functions (stock, rating,
recency, click-derived popularity, all combined with different modifiers),
a synonym *graph* analyzer (multi-word synonyms, not just 1:1 word swaps),
and per-query result reranking driven by a feedback table. Elasticsearch
gives you all of that as first-class query DSL; Meilisearch would need
workarounds for most of it. If your relevance needs are simpler, Meilisearch
is genuinely the better ops tradeoff (single binary, near-zero config) — it's
a real "use the boring tool" call, just not this one.

## Architecture

```
Postgres = system of record          Elasticsearch = query engine (derived)
  products table         --index-->    products index
  search_events (impressions)
  click_events
  query_boosts (feedback-derived)  --update_by_query-->  popularity_score field
```

Postgres stays authoritative for product data and all click/impression
history. Elasticsearch holds a derived, denormalized copy built for query
speed — if the ES index is ever lost, `scripts/reindex.py` rebuilds it
entirely from Postgres. Never write click/impression data to ES only.

## Relevance features implemented

1. **Synonym handling** — `synonym_graph` token filter (`es/synonyms.txt`),
   applied at *search* time only (not index time), so adding a synonym
   doesn't require reindexing. Multi-word synonyms work correctly
   (`"sneaker, running shoe, trainer"`).

2. **Typo tolerance** — `fuzziness: AUTO` on the main `multi_match` (0 edits
   for short terms, 1 for medium, 2 for long — avoids "fuzzy-matching" a
   3-letter query into nonsense), plus a phrase suggester for "did you mean".

3. **Business-logic boosting** — a `function_score` query combining:
   - `field_value_factor` on `rating` (log-dampened, so a 5.0 vs 4.8 isn't
     wildly different)
   - a hard multiplicative boost when `in_stock: true`
   - a `gauss` decay on `created_at` (mild recency preference)
   - `field_value_factor` on `popularity_score` — the field the feedback
     loop below actually updates over time

4. **Click-through feedback loop** — every search logs an *impression*
   (query + ordered result IDs + a `search_id`). Every click references
   that `search_id` + position. `scripts/recompute_ranking_signals.py`
   (run on a schedule — cron/Celery beat in prod) aggregates:
   - **global popularity** per product → written back into ES as
     `popularity_score`, using a Bayesian-smoothed CTR so a product with
     3 impressions and 1 click doesn't outrank one with 50,000 impressions
     and a healthy real CTR.
   - **query-specific boosts** — which products get clicked for *this
     specific query* → stored in Postgres `query_boosts`, applied at
     search time as extra `should` clauses. This is what lets the engine
     learn "when people search 'trainers', they usually click product
     X" even if X doesn't textually match best.

## Layout

```
app/
  config.py, es_client.py, database.py, models.py, schemas.py
  query_builder.py   THE relevance logic — read this first
  ranking.py           normalization + Bayesian smoothing math
  feedback.py           impression/click recording
  indexing.py            ES mapping/analyzer setup + bulk indexing
  routers/
    search.py, products.py, feedback.py
es/
  index_settings.json   mapping + analyzers (synonyms, fuzziness config lives in query, not here)
  synonyms.txt
scripts/
  seed_products.py
  reindex.py                          rebuild ES fully from Postgres
  recompute_ranking_signals.py        the retraining job
tests/
  test_query_builder.py               asserts the query DSL shape itself
```

## Running it

```bash
docker compose up -d          # elasticsearch + postgres
cp .env.example .env
pip install -r requirements.txt
python -m app.db_init          # create Postgres tables
python scripts/seed_products.py     # sample catalog -> Postgres + ES
uvicorn app.main:app --reload
```

Search:
```bash
curl "localhost:8000/search?q=runing shose&in_stock_only=false"
```
(Note the typos — fuzziness handles them. Try `q=sneaker` vs `q=trainer`
vs `q=running shoe` to see the synonym graph collapsing them to the same
results.)

Click feedback:
```bash
curl -X POST localhost:8000/feedback/click \
  -H 'content-type: application/json' \
  -d '{"search_id": "<from search response>", "product_id": "...", "position": 2}'
```

Retrain ranking signals (run this on a schedule in prod):
```bash
python scripts/recompute_ranking_signals.py
```
