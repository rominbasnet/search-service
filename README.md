# Search-as-a-Service — FastAPI + Elasticsearch

A small search service built with **FastAPI, Elasticsearch, and PostgreSQL**, focused on relevance rather than simply returning text matches.

The project includes:

* Synonym expansion
* Typo-tolerant search
* Business-aware ranking
* Click-through feedback
* Query-specific ranking signals
* A scheduled job that learns from search behavior over time

The goal is to have a search engine that gets better as users interact with it.

---

## Why Elasticsearch?

For a simple search box, something like Meilisearch is often the better choice. It's fast, easy to run, and requires very little configuration.

This project needs more control over ranking, though.

Elasticsearch gives us access to things like:

* `function_score` with multiple independent ranking signals
* `synonym_graph` for multi-word synonyms
* Search-time synonym expansion
* Fuzzy matching
* Per-query boosting
* Custom ranking logic based on user feedback

For example, we can combine product rating, stock availability, recency, and click-through popularity without having to build workarounds around the search engine.

If your application doesn't need that level of relevance tuning, I'd still recommend the simpler tool.

---

## How it works

PostgreSQL is the **source of truth**. Elasticsearch is a **derived search index**.

```text
                 PostgreSQL
              (source of truth)
                    |
                    | index / reindex
                    v
              Elasticsearch
               (search index)
                    |
                    v
                  Search

PostgreSQL also stores:

  search_events
  click_events
  query_boosts
```

Product data lives in PostgreSQL.

Search events and clicks also live in PostgreSQL. Elasticsearch never becomes the authoritative store for that data.

The Elasticsearch product index is disposable. If it gets deleted, we can rebuild it completely from PostgreSQL using:

```bash
python scripts/reindex.py
```

This keeps the architecture simple: **Postgres owns the data, Elasticsearch makes it searchable.**

---

## Relevance

The interesting part of this project is the ranking pipeline.

### 1. Synonyms

Search uses Elasticsearch's `synonym_graph` token filter.

The synonyms live in:

```text
es/synonyms.txt
```

They're applied at **search time**, rather than index time.

That means we can add or change synonyms without having to reindex every product.

For example:

```text
sneaker, running shoe, trainer
```

A search for:

```text
trainer
```

can therefore find products that are relevant to:

```text
sneaker
running shoe
```

Multi-word synonyms are handled correctly by the synonym graph analyzer.

---

### 2. Typo tolerance

The main `multi_match` query uses:

```text
fuzziness: AUTO
```

This gives us useful typo tolerance without making every short query aggressively fuzzy.

For example:

```text
runing shose
```

can still find:

```text
running shoes
```

`AUTO` adjusts the allowed edit distance based on the length of the search term. Short words get less fuzziness, which helps avoid turning a three-letter query into a completely unrelated result.

There's also a phrase suggester that can provide a "Did you mean?" style suggestion when appropriate.

---

### 3. Business-aware ranking

Text relevance isn't always enough.

A product that matches the query well isn't necessarily the product we want at the top of the results.

The search query therefore uses Elasticsearch's `function_score` to combine several signals:

#### Rating

Product ratings contribute to the score using a dampened `field_value_factor`.

The idea is that a product rated 5.0 shouldn't automatically dominate a product rated 4.8.

#### Stock

In-stock products receive a multiplicative boost.

This lets us prioritize products that customers can actually buy.

#### Recency

A `gauss` decay function gives newer products a mild advantage.

It's deliberately a small signal rather than something that completely overrides text relevance.

#### Popularity

Products also have a `popularity_score`.

This value comes from actual user behavior and is periodically recalculated by the feedback pipeline.

So, over time, the ranking can learn which products users actually click.

---

## Learning from clicks

The search service records both impressions and clicks.

When a user performs a search, we store:

* The search query
* The ordered list of returned product IDs
* A unique `search_id`

For example:

```text
search_id: abc123
query: running shoes

results:
1. product_a
2. product_b
3. product_c
4. product_d
```

If the user clicks the third result, the click event references the same `search_id`:

```text
search_id: abc123
product_id: product_c
position: 3
```

This gives us enough information to connect clicks back to the exact search and result position.

---

## Ranking feedback loop

The feedback data is processed periodically by:

```bash
python scripts/recompute_ranking_signals.py
```

In production, this could run from cron, Celery Beat, or another scheduler.

The job calculates two types of signals.

### Global popularity

For each product, we calculate a click-through rate based on its impressions and clicks.

We use **Bayesian smoothing** rather than simply calculating:

```text
clicks / impressions
```

This matters because a product with:

```text
1 click / 3 impressions
```

shouldn't automatically outrank a product with:

```text
5,000 clicks / 50,000 impressions
```

The smoothed score is written back to Elasticsearch as:

```text
popularity_score
```

That score then becomes one of the ranking signals used during search.

---

### Query-specific boosts

Global popularity isn't always enough.

A product might not be generally popular but could be extremely relevant for a particular query.

For example:

```text
"trainers"
```

might consistently result in users clicking a specific product.

That relationship is stored in PostgreSQL as a query-specific boost.

At search time, these boosts are converted into additional `should` clauses.

This allows the search engine to learn things like:

> When people search for "trainers", they tend to click product X.

The product doesn't necessarily have to be the strongest textual match to benefit from that learned signal.

---

## Project structure

```text
app/
├── config.py
├── es_client.py
├── database.py
├── models.py
├── schemas.py
├── query_builder.py       # Main relevance logic
├── ranking.py             # Ranking and Bayesian smoothing
├── feedback.py            # Impression/click recording
├── indexing.py            # Elasticsearch setup and indexing
│
└── routers/
    ├── search.py
    ├── products.py
    └── feedback.py

es/
├── index_settings.json
└── synonyms.txt

scripts/
├── seed_products.py
├── reindex.py
└── recompute_ranking_signals.py

tests/
└── test_query_builder.py
```

If you're looking through the project for the interesting part, start with:

```text
app/query_builder.py
```

That's where the different relevance signals come together.

The query-builder tests also test the generated Elasticsearch DSL directly, so changes to ranking behavior are easier to catch.

---

## Running locally

Start Elasticsearch and PostgreSQL:

```bash
docker compose up -d
```

Create your environment file:

```bash
cp .env.example .env
```

Install the Python dependencies:

```bash
pip install -r requirements.txt
```

Create the PostgreSQL tables:

```bash
python -m app.db_init
```

Seed the sample catalog:

```bash
python scripts/seed_products.py
```

Start FastAPI:

```bash
uvicorn app.main:app --reload
```

---

## Try it out

Search with a typo:

```bash
curl "localhost:8000/search?q=runing%20shose&in_stock_only=false"
```

Try the same catalog with different queries:

```text
sneaker
trainer
running shoe
```

These should demonstrate the synonym handling.

The typo-tolerant search should also handle:

```text
runing shose
```

without requiring the user to type the exact product terminology.

---

## Sending click feedback

A search response contains a `search_id`.

Use that ID when recording a click:

```bash
curl -X POST localhost:8000/feedback/click \
  -H 'content-type: application/json' \
  -d '{
    "search_id": "<search_id>",
    "product_id": "...",
    "position": 2
  }'
```

The position is important because it lets the ranking pipeline understand not only what was clicked, but where it appeared in the result list.

---

## Recomputing ranking signals

Run the feedback aggregation manually with:

```bash
python scripts/recompute_ranking_signals.py
```

This updates the learned ranking signals based on the latest impression and click data.

In a production deployment, this would normally be scheduled rather than run manually.

---

## Design principles

A few decisions are intentional here:

**PostgreSQL remains authoritative.**
Search and feedback data can always be rebuilt or recomputed.

**Elasticsearch is treated as a derived index.**
Losing the index should be inconvenient, not catastrophic.

**Synonyms are applied at search time.**
This allows synonym changes without reindexing the catalog.

**Text relevance isn't the only signal.**
Availability, rating, freshness, and user behavior all contribute to ranking.

**Feedback is separated from the search index.**
Clicks and impressions belong in PostgreSQL, where they can be audited, aggregated, and recomputed.

**Ranking is measurable and testable.**
The query builder is tested at the Elasticsearch DSL level rather than only through API-level tests.

---

## The main idea

This project is less about building an endpoint like:

```text
GET /search?q=...
```

and more about building a search system that can **learn what good results look like**.

Elasticsearch handles the retrieval and ranking primitives.

PostgreSQL stores the history.

The feedback job turns that history into ranking signals.

And the search query brings everything together:

```text
query text
   +
synonyms
   +
fuzzy matching
   +
text relevance
   +
stock
   +
rating
   +
recency
   +
global popularity
   +
query-specific feedback
   ↓
ranked results
```

That's the part that makes this a relevance-engineering project rather than just another search box.
