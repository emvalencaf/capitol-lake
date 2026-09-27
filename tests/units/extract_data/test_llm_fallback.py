"""LLM fallback stage (#41): eligibility gating and structured-output application.

`complete_text`/`complete_vision` are always canned/injected here, per this
codebase's convention for network dependencies (`test_ticker_resolve.py`):
the stage's decision logic is exercised against fixed responses, never a
real provider call.
"""

from datetime import date

import pytest

from extract_data.llm_fallback import (
    FALLBACK_FIELDS,
    LLM_CONFIDENCE,
    apply_fallback_result,
    apply_text_fallback,
    apply_vision_fallback,
    eligible_fields_from_scores,
    fallback_schema,
    field_schema,
    fields_needing_fallback,
    needs_fallback,
)
from shared.schema import (
    AssetType,
    Owner,
    Provenance,
    Transaction,
    TransactionType,
    ValueRange,
)

PROVENANCE = Provenance(bronze_key="bronze/house/year=2025/1.pdf", extractor="house-digital-pdf")


def _transaction(**overrides) -> Transaction:
    defaults = dict(
        doc_id="1",
        line_no=1,
        owner=Owner.SELF,
        owner_raw="SP",
        transaction_type=TransactionType.PURCHASE,
        transaction_type_raw="P",
        asset_type=AssetType.STOCK,
        asset_description="Amgen Inc.",
        transaction_date=date(2025, 1, 15),
        filing_date=date(2025, 2, 1),
        value_range=ValueRange(1001, 15000),
        confidence=1.0,
        provenance=PROVENANCE,
        ticker="AMGN",
        notification_date=date(2025, 1, 16),
        filing_status="New",
        sub_owner="A Trust",
        description="a description",
        field_confidence={},
    )
    defaults.update(overrides)
    return Transaction(**defaults)


def _text_provider(response: dict):
    def _complete(prompt: str, source_text: str, schema: dict) -> dict:
        _complete.calls.append((prompt, source_text, schema))
        return response

    _complete.calls = []
    return _complete


def _vision_provider(response: dict):
    def _complete(prompt: str, page_image: bytes, schema: dict) -> dict:
        _complete.calls.append((prompt, page_image, schema))
        return response

    _complete.calls = []
    return _complete


def test_needs_fallback_true_for_null_field():
    transaction = _transaction(sub_owner=None)
    assert needs_fallback(transaction, "sub_owner") is True


def test_needs_fallback_true_for_low_confidence_field():
    transaction = _transaction(description="garbled", field_confidence={"description": 0.0})
    assert needs_fallback(transaction, "description") is True


def test_needs_fallback_false_for_confident_present_field():
    transaction = _transaction()
    assert needs_fallback(transaction, "asset_description") is False


def test_fields_needing_fallback_filters_to_eligible_and_actually_missing():
    # sub_owner is null (missing); asset_description is present and
    # confident even though it's passed in as "eligible" by field group.
    transaction = _transaction(sub_owner=None)

    fields = fields_needing_fallback(transaction, ["sub_owner", "asset_description"])

    assert fields == ["sub_owner"]


def test_fields_needing_fallback_ignores_unknown_field_names():
    transaction = _transaction()
    assert fields_needing_fallback(transaction, ["not_a_real_field"]) == []


def test_eligible_fields_from_scores_below_threshold():
    scores = {"sub_owner": 0.4, "description": 0.9, "owner": 1.0}

    eligible = eligible_fields_from_scores(scores, threshold=0.8)

    assert eligible == {"sub_owner"}


def test_eligible_fields_from_scores_field_absent_from_scores_is_not_eligible():
    assert eligible_fields_from_scores({}, threshold=0.99) == frozenset()


def test_field_schema_enum_field_lists_member_values():
    schema = field_schema("owner")
    assert schema["enum"] == [member.value for member in Owner]


def test_field_schema_date_field_uses_date_format():
    assert field_schema("transaction_date")["format"] == "date"


def test_field_schema_number_field():
    assert field_schema("value_min")["type"] == ["number", "null"]


def test_fallback_schema_covers_exactly_the_requested_fields():
    schema = fallback_schema(["owner", "value_min"])
    assert set(schema["properties"]) == {"owner", "value_min"}
    assert schema["required"] == ["owner", "value_min"]
    assert schema["additionalProperties"] is False


def test_apply_fallback_result_fills_enum_and_date_fields():
    transaction = _transaction(transaction_type=None, notification_date=None, field_confidence={})

    result = apply_fallback_result(
        transaction,
        ["transaction_type", "notification_date"],
        {"transaction_type": "purchase", "notification_date": "2025-01-20"},
    )

    assert result.transaction_type is TransactionType.PURCHASE
    assert result.notification_date == date(2025, 1, 20)
    assert result.field_confidence["transaction_type"] == LLM_CONFIDENCE
    assert result.field_confidence["notification_date"] == LLM_CONFIDENCE


def test_apply_fallback_result_combines_value_min_and_max_into_one_value_range():
    transaction = _transaction(value_range=None, field_confidence={})

    result = apply_fallback_result(
        transaction, ["value_min", "value_max"], {"value_min": 1001, "value_max": 15000}
    )

    assert result.value_range == ValueRange(1001, 15000)


def test_apply_fallback_result_null_value_min_yields_null_value_range():
    transaction = _transaction(value_range=None, field_confidence={})

    result = apply_fallback_result(
        transaction, ["value_min", "value_max"], {"value_min": None, "value_max": None}
    )

    assert result.value_range is None


def test_apply_fallback_result_leaves_untouched_fields_alone():
    transaction = _transaction(sub_owner=None, field_confidence={})

    result = apply_fallback_result(transaction, ["sub_owner"], {"sub_owner": "A Trust"})

    assert result.sub_owner == "A Trust"
    assert result.asset_description == transaction.asset_description
    assert result.doc_id == transaction.doc_id
    assert result.line_no == transaction.line_no


def test_apply_fallback_result_preserves_disclosure_lag():
    transaction = _transaction(sub_owner=None, field_confidence={})

    result = apply_fallback_result(transaction, ["sub_owner"], {"sub_owner": "A Trust"})

    assert result.disclosure_lag == transaction.disclosure_lag


def test_apply_fallback_result_lowers_confidence_and_tags_provenance():
    transaction = _transaction(sub_owner=None, confidence=1.0, field_confidence={})

    result = apply_fallback_result(transaction, ["sub_owner"], {"sub_owner": "A Trust"})

    assert result.confidence == LLM_CONFIDENCE
    assert result.provenance.extractor == "house-digital-pdf+llm-fallback"
    # The original transaction (and its provenance) is never mutated.
    assert transaction.confidence == 1.0
    assert transaction.provenance.extractor == "house-digital-pdf"


def test_apply_fallback_result_never_lowers_confidence_below_what_llm_confidence_already_set():
    transaction = _transaction(sub_owner=None, confidence=0.0, field_confidence={})

    result = apply_fallback_result(transaction, ["sub_owner"], {"sub_owner": "A Trust"})

    assert result.confidence == 0.0


def test_apply_text_fallback_calls_provider_only_for_missing_eligible_fields():
    transaction = _transaction(sub_owner=None, field_confidence={})
    complete = _text_provider({"sub_owner": "A Trust"})

    result = apply_text_fallback(
        transaction,
        FALLBACK_FIELDS,
        source_text="... filing text ...",
        complete_text=complete,
    )

    assert result.sub_owner == "A Trust"
    assert len(complete.calls) == 1
    _prompt, source_text, schema = complete.calls[0]
    assert source_text == "... filing text ..."
    assert set(schema["properties"]) == {"sub_owner"}


def test_apply_text_fallback_no_op_when_nothing_needs_recovering():
    transaction = _transaction()
    complete = _text_provider({})

    result = apply_text_fallback(
        transaction, FALLBACK_FIELDS, source_text="text", complete_text=complete
    )

    assert result is transaction
    assert complete.calls == []


def test_apply_text_fallback_restricted_to_eligible_field_group():
    # sub_owner is null but not in the eligible set (evaluation showed that
    # field group is fine) - the provider must never be asked about it.
    transaction = _transaction(sub_owner=None, description=None, field_confidence={})
    complete = _text_provider({"description": "some description"})

    result = apply_text_fallback(
        transaction, ["description"], source_text="text", complete_text=complete
    )

    assert result.description == "some description"
    assert result.sub_owner is None
    assert complete.calls[0][2]["properties"].keys() == {"description"}


def test_apply_vision_fallback_calls_provider_with_page_image():
    transaction = _transaction(value_range=None, field_confidence={})
    complete = _vision_provider({"value_min": 1001, "value_max": 15000})

    result = apply_vision_fallback(
        transaction, ["value_min", "value_max"], page_image=b"PNGDATA", complete_vision=complete
    )

    assert result.value_range == ValueRange(1001, 15000)
    assert complete.calls[0][1] == b"PNGDATA"


def test_apply_vision_fallback_no_op_when_nothing_needs_recovering():
    transaction = _transaction()
    complete = _vision_provider({})

    result = apply_vision_fallback(
        transaction, FALLBACK_FIELDS, page_image=b"PNGDATA", complete_vision=complete
    )

    assert result is transaction
    assert complete.calls == []


def test_fallback_fields_match_evaluation_scored_fields():
    from extract_data.evaluation import SCORED_FIELDS

    assert FALLBACK_FIELDS == SCORED_FIELDS


@pytest.mark.parametrize("field", list(FALLBACK_FIELDS))
def test_every_scored_field_has_a_schema_and_accessor(field):
    # Every field the eval harness scores must be a valid fallback target -
    # this stage's field vocabulary is defined as exactly that set.
    schema = field_schema(field)
    assert "type" in schema
    transaction = _transaction()
    fields_needing_fallback(transaction, [field])  # must not raise KeyError
