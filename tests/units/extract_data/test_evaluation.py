from extract_data.evaluation import (
    SCORED_FIELDS,
    score_field,
    score_filing,
    score_gold_set,
    score_set,
    score_transaction,
    weakest_fields,
)


def test_score_field_exact_match():
    assert score_field("owner", "self", "self") == 1.0
    assert score_field("owner", "self", "spouse") == 0.0


def test_score_field_both_null_is_a_match():
    assert score_field("value_min", None, None) == 1.0


def test_score_field_one_null_is_a_total_miss():
    assert score_field("value_min", 1000, None) == 0.0
    assert score_field("value_min", None, 1000) == 0.0


def test_score_field_similarity_is_continuous_not_binary():
    gold_text = "Apple Inc. - Common Stock"
    exact = score_field("asset_description", gold_text, gold_text)
    near_miss = score_field("asset_description", gold_text, "Apple Inc Common Stock")
    wrong = score_field("asset_description", gold_text, "Totally different text")

    assert exact == 1.0
    assert 0.0 < near_miss < 1.0
    assert wrong < near_miss


def test_score_transaction_scores_every_field():
    gold = {"line_no": 1, "owner": "self", "asset_description": "Apple Inc."}
    predicted = {"line_no": 1, "owner": "self", "asset_description": "Apple Inc."}

    scores = score_transaction(gold, predicted)

    assert set(scores) == set(SCORED_FIELDS)
    assert scores["owner"] == 1.0


def test_score_transaction_with_no_matching_predicted_row_scores_zero_everywhere():
    gold = {"line_no": 1, "owner": "self"}

    scores = score_transaction(gold, None)

    assert all(score == 0.0 for score in scores.values())


def test_score_filing_averages_across_transactions_matched_by_line_no():
    gold_transactions = [
        {"line_no": 1, "owner": "self"},
        {"line_no": 2, "owner": "spouse"},
    ]
    # Row 2 is missing from the prediction entirely (extractor dropped it).
    predicted_transactions = [{"line_no": 1, "owner": "self"}]

    scores = score_filing(gold_transactions, predicted_transactions)

    assert scores["owner"] == 0.5


def test_score_filing_with_no_gold_transactions_scores_perfectly():
    scores = score_filing([], [])

    assert all(score == 1.0 for score in scores.values())


def test_score_filing_penalizes_a_hallucinated_row_on_an_empty_gold_filing():
    # A legitimate "nothing to report" PTR: no gold transactions, but the
    # extractor fabricated one anyway. This must not score perfectly.
    predicted_transactions = [{"line_no": 1, "owner": "self"}]

    scores = score_filing([], predicted_transactions)

    assert all(score == 0.0 for score in scores.values())


def test_score_filing_penalizes_an_extra_predicted_row_alongside_correct_ones():
    gold_transactions = [{"line_no": 1, "owner": "self"}]
    predicted_transactions = [
        {"line_no": 1, "owner": "self"},
        {"line_no": 2, "owner": "spouse"},  # hallucinated: no matching gold row
    ]

    scores = score_filing(gold_transactions, predicted_transactions)

    assert scores["owner"] == 0.5


def test_score_set_averages_filing_scores():
    filing_scores = [
        dict.fromkeys(SCORED_FIELDS, 1.0),
        dict.fromkeys(SCORED_FIELDS, 0.0),
    ]

    scores = score_set(filing_scores)

    assert scores["owner"] == 0.5


def test_score_gold_set_breaks_out_digital_and_scanned():
    filings = [
        {
            "doc_id": "d1",
            "kind": "digital",
            "gold_transactions": [{"line_no": 1, "owner": "self"}],
            "predicted_transactions": [{"line_no": 1, "owner": "self"}],
        },
        {
            "doc_id": "s1",
            "kind": "scanned",
            "gold_transactions": [{"line_no": 1, "owner": "self"}],
            "predicted_transactions": [{"line_no": 1, "owner": "spouse"}],
        },
    ]

    report = score_gold_set(filings)

    assert report["by_filing"]["d1"]["owner"] == 1.0
    assert report["by_filing"]["s1"]["owner"] == 0.0
    assert report["by_kind"]["digital"]["owner"] == 1.0
    assert report["by_kind"]["scanned"]["owner"] == 0.0
    assert report["overall"]["owner"] == 0.5


def test_weakest_fields_returns_lowest_scores_first():
    scores = {"owner": 1.0, "description": 0.2, "asset_type": 0.6}

    assert weakest_fields(scores, n=2) == [("description", 0.2), ("asset_type", 0.6)]
