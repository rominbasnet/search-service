"""
The math behind the feedback loop. Two distinct signals get computed here,
both by scripts/recompute_ranking_signals.py:

  1. Global popularity_score per product (written into ES) -- "is this
     product generally good, across all queries it appears in".
  2. Per-(query, product) boost (written into Postgres query_boosts,
     applied at query time by query_builder.py) -- "for THIS query
     specifically, do people click this product disproportionately".

Both use Bayesian-smoothed CTR, not raw click count and not raw CTR:

  - Raw click count favors high-traffic products regardless of whether
    people actually wanted them (they were just shown a lot).
  - Raw CTR (clicks/impressions) is unstable at low sample sizes: a
    product shown twice and clicked once has a "100% CTR" that means
    nothing statistically.
  - Bayesian smoothing pulls low-sample-size CTRs toward a global prior
    (the site-wide average CTR) and only lets a product's own data
    dominate once it has enough impressions to trust. This is the same
    trick Reddit/IMDB "true rating" algorithms use.
"""


def normalize_query(raw_query: str) -> str:
    return " ".join(raw_query.strip().lower().split())


def smoothed_ctr(
    clicks: int,
    impressions: int,
    global_avg_ctr: float,
    virtual_impressions: int,
) -> float:
    """
    Bayesian average: treat the prior as `virtual_impressions` extra
    impressions at the site-wide average CTR, blended with the observed
    data. As impressions grows, this converges to the real CTR; at
    impressions=0 it returns exactly global_avg_ctr.
    """
    numerator = clicks + virtual_impressions * global_avg_ctr
    denominator = impressions + virtual_impressions
    return numerator / denominator if denominator > 0 else 0.0


def position_bias_weight(position: int) -> float:
    """
    Down-weights clicks at high (later) positions when computing signal
    strength, since a click at position 1 is a much weaker relevance
    signal than a click at position 10 (users skim top-down, so position 1
    gets clicked "for free" more often regardless of quality). We use a
    simple inverse-position weighting; production systems often use a
    more rigorously fitted click model (e.g. cascade model), but this
    captures the core idea cheaply.
    """
    return 1.0 / (position + 1)
