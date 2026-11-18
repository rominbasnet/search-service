from math import isclose

from app.ranking import normalize_query, smoothed_ctr


def test_case_and_whitespace_share_a_query_feedback_key():
    assert normalize_query("  Running\tSHOES\n") == normalize_query("running shoes")
    assert normalize_query("running shoes") == "running shoes"


def test_product_without_impressions_starts_at_the_catalog_click_rate():
    score = smoothed_ctr(
        clicks=0, impressions=0, global_avg_ctr=0.1, virtual_impressions=50
    )
    assert isclose(score, 0.1)


def test_one_click_in_one_impression_has_limited_influence():
    score = smoothed_ctr(
        clicks=1, impressions=1, global_avg_ctr=0.1, virtual_impressions=50
    )
    # The prior contributes five clicks across fifty impressions.
    assert isclose(score, 6 / 51)


def test_more_traffic_brings_the_score_closer_to_the_observed_rate():
    # Both products have a 30% observed click rate.
    small_sample = smoothed_ctr(
        clicks=3, impressions=10, global_avg_ctr=0.1, virtual_impressions=50
    )
    large_sample = smoothed_ctr(
        clicks=300, impressions=1000, global_avg_ctr=0.1, virtual_impressions=50
    )
    assert 0.1 < small_sample < large_sample < 0.3
