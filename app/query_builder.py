"""
THE relevance logic lives here.

Layered approach (each layer solves one distinct relevance problem):

  1. Text matching (multi_match, fuzziness) -- find candidates, tolerate typos.
  2. Synonym expansion -- happens automatically inside multi_match because
     the field's search_analyzer applies the synonym_graph filter (see
     es/index_settings.json) -- no special query-time code needed for it.
  3. function_score -- re-scores candidates using BUSINESS signals that
     text relevance alone doesn't know about (stock, rating, recency,
     click-derived popularity).
  4. Query-specific learned boosts -- additional `should` clauses built
     from query_boosts (Postgres), added as constant_score bumps for
     products that historically get clicked for this exact query.

Splitting these into layers (rather than one giant scored expression) is
what makes relevance tunable in production: you can turn off layer 4
(e.g. for a brand-new query with no click history) without touching 1-3,
or A/B test different function_score weights without touching the text
matching at all.
"""
from typing import Any


def build_search_query(
    query: str,
    in_stock_only: bool = False,
    category: str | None = None,
    max_price: float | None = None,
    query_boosts: dict[str, float] | None = None,
    size: int = 20,
) -> dict[str, Any]:
    query_boosts = query_boosts or {}

    # --- Layer 1+2: text matching with typo tolerance + synonym expansion ---
    # `best_fields` picks the single best-matching field's score rather than
    # summing across fields, which avoids a product that weakly matches on
    # name AND description outranking one that matches name perfectly.
    # fuzziness AUTO scales edit distance with term length so short queries
    # don't get destroyed by over-eager fuzzy matching.
    text_query: dict[str, Any] = {
        "multi_match": {
            "query": query,
            "fields": ["name^3", "brand^2", "description"],
            "type": "best_fields",
            "fuzziness": "AUTO",
            "prefix_length": 1,  # don't fuzz-match on the first letter -- cuts noise
            "minimum_should_match": "75%",
        }
    }

    filters: list[dict[str, Any]] = []
    if in_stock_only:
        filters.append({"term": {"in_stock": True}})
    if category:
        filters.append({"term": {"category": category}})
    if max_price is not None:
        filters.append({"range": {"price": {"lte": max_price}}})

    # --- Layer 4: query-specific learned boosts -----------------------------
    # For products with click-derived history for THIS query, add a should
    # clause matching that exact product id with a constant score bump.
    # These are additive with the main text score (should clauses inside a
    # bool query sum into the overall score), not a replacement for it --
    # a learned boost can push a decent text match ahead of a slightly
    # better one, but can't surface something with zero text relevance.
    should_clauses: list[dict[str, Any]] = []
    for product_id, boost in query_boosts.items():
        should_clauses.append(
            {
                "constant_score": {
                    "filter": {"term": {"id": product_id}},
                    "boost": boost,
                }
            }
        )

    bool_query: dict[str, Any] = {
        "bool": {
            "must": [text_query],
            "filter": filters,
        }
    }
    if should_clauses:
        bool_query["bool"]["should"] = should_clauses

    # --- Layer 3: business-logic boosting via function_score -----------------
    function_score_query: dict[str, Any] = {
        "function_score": {
            "query": bool_query,
            "score_mode": "sum",     # combine all function outputs
            "boost_mode": "multiply",  # then multiply into the text relevance score
            "functions": [
                # In-stock items rank higher -- a hard, explicit business rule,
                # not left to correlate accidentally with something else.
                {
                    "filter": {"term": {"in_stock": True}},
                    "weight": 1.5,
                },
                {
                    "filter": {"term": {"in_stock": False}},
                    "weight": 0.4,
                },
                # Higher-rated products get a modest, log-dampened boost --
                # log1p means the jump from 0->1 star matters more than
                # 4->5, which matches how people actually perceive ratings.
                {
                    "field_value_factor": {
                        "field": "rating",
                        "factor": 1.0,
                        "modifier": "log1p",
                        "missing": 0,
                    },
                    "weight": 1.0,
                },
                # Click-derived popularity (written by the feedback loop --
                # see ranking.py / recompute_ranking_signals.py). This is
                # the field that makes the engine "learn" over time.
                {
                    "field_value_factor": {
                        "field": "popularity_score",
                        "factor": 1.0,
                        "modifier": "log1p",
                        "missing": 0,
                    },
                    "weight": 1.5,
                },
                # Mild recency preference -- decays smoothly rather than a
                # hard cutoff, so a great 6-month-old product doesn't fall
                # off a cliff against a mediocre brand-new one.
                {
                    "gauss": {
                        "created_at": {
                            "origin": "now",
                            "scale": "180d",
                            "decay": 0.5,
                        }
                    },
                    "weight": 0.5,
                },
            ],
        }
    }

    return {
        "size": size,
        "query": function_score_query,
        "suggest": {
            "did_you_mean": {
                "text": query,
                "phrase": {
                    "field": "name",
                    "size": 1,
                    "gram_size": 2,
                    "direct_generator": [
                        {"field": "name", "suggest_mode": "always", "max_edits": 2}
                    ],
                    "highlight": {"pre_tag": "", "post_tag": ""},
                },
            }
        },
    }
