"""
Unit tests against the query DSL shape itself -- these don't need a live
Elasticsearch, they just assert build_search_query() produces the correct
structure for each relevance feature. (Integration tests that actually hit
ES belong in a separate test_search_integration.py using a real/testcontainer
Elasticsearch -- omitted here to keep this runnable with zero infra.)
"""
from app.query_builder import build_search_query


def _function_score(body):
    return body["query"]["function_score"]


def test_typo_tolerance_uses_fuzziness_auto():
    body = build_search_query(query="runing shose")
    must = _function_score(body)["query"]["bool"]["must"][0]
    assert must["multi_match"]["fuzziness"] == "AUTO"
    assert must["multi_match"]["query"] == "runing shose"


def test_multi_match_searches_correct_fields_with_boosts():
    body = build_search_query(query="nike")
    must = _function_score(body)["query"]["bool"]["must"][0]
    fields = must["multi_match"]["fields"]
    assert "name^3" in fields
    assert "brand^2" in fields
    assert "description" in fields


def test_in_stock_only_adds_filter():
    body = build_search_query(query="tv", in_stock_only=True)
    filters = _function_score(body)["query"]["bool"]["filter"]
    assert {"term": {"in_stock": True}} in filters


def test_no_in_stock_filter_when_not_requested():
    body = build_search_query(query="tv", in_stock_only=False)
    filters = _function_score(body)["query"]["bool"]["filter"]
    assert {"term": {"in_stock": True}} not in filters


def test_category_and_price_filters():
    body = build_search_query(query="tv", category="electronics", max_price=500)
    filters = _function_score(body)["query"]["bool"]["filter"]
    assert {"term": {"category": "electronics"}} in filters
    assert {"range": {"price": {"lte": 500}}} in filters


def test_business_boost_functions_present():
    body = build_search_query(query="tv")
    functions = _function_score(body)["functions"]
    field_names = [
        f["field_value_factor"]["field"] for f in functions if "field_value_factor" in f
    ]
    assert "rating" in field_names
    assert "popularity_score" in field_names
    # in_stock has two weighted filter functions (boost when true, penalize when false)
    in_stock_filters = [f for f in functions if f.get("filter") == {"term": {"in_stock": True}}]
    assert len(in_stock_filters) == 1
    assert in_stock_filters[0]["weight"] > 1.0


def test_query_specific_boosts_added_as_should_clauses():
    boosts = {"prod-123": 4.5, "prod-456": 2.1}
    body = build_search_query(query="sneaker", query_boosts=boosts)
    should = _function_score(body)["query"]["bool"]["should"]
    boosted_ids = {s["constant_score"]["filter"]["term"]["id"] for s in should}
    assert boosted_ids == {"prod-123", "prod-456"}
    boost_values = {s["constant_score"]["boost"] for s in should}
    assert boost_values == {4.5, 2.1}


def test_no_should_clause_when_no_query_boosts():
    body = build_search_query(query="sneaker", query_boosts={})
    assert "should" not in _function_score(body)["query"]["bool"]


def test_did_you_mean_suggester_present():
    body = build_search_query(query="runing")
    assert "suggest" in body
    assert body["suggest"]["did_you_mean"]["text"] == "runing"
