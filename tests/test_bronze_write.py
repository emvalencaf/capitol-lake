import hashlib

import pytest

from capitol_lake.stages.bronze_write import bronze_write

HOUSE_DOC = {"chamber": "house", "doc_id": "20012345", "ext": "pdf"}
SENATE_DOC = {
    "chamber": "senate",
    "doc_id": "8f14e45f-ceea-467e-9575-83fbc8a6d3e2",
    "ext": "html",
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize("doc", [HOUSE_DOC, SENATE_DOC], ids=["house", "senate"])
def test_first_write_uses_original_key(doc):
    result = bronze_write(
        chamber=doc["chamber"],
        year=2024,
        doc_id=doc["doc_id"],
        ext=doc["ext"],
        candidate_bytes=b"original-bytes",
        existing_sha256=None,
        source_url="https://example.gov/filing",
        fetched_at="2024-01-15T00:00:00Z",
        index_row=3,
    )

    original_key = f"bronze/{doc['chamber']}/year=2024/{doc['doc_id']}.{doc['ext']}"
    assert result["action"] == "write"
    assert result["key"] == original_key
    assert result["meta_key"] == original_key + ".meta.json"
    assert result["sha256"] == _sha256(b"original-bytes")
    assert result["meta"] == {
        "source_url": "https://example.gov/filing",
        "fetched_at": "2024-01-15T00:00:00Z",
        "sha256": result["sha256"],
        "chamber": doc["chamber"],
        "doc_id": doc["doc_id"],
        "year": 2024,
        "ext": doc["ext"],
        "index_row": 3,
    }


@pytest.mark.parametrize("doc", [HOUSE_DOC, SENATE_DOC], ids=["house", "senate"])
def test_identical_hash_is_noop(doc):
    candidate = b"original-bytes"
    result = bronze_write(
        chamber=doc["chamber"],
        year=2024,
        doc_id=doc["doc_id"],
        ext=doc["ext"],
        candidate_bytes=candidate,
        existing_sha256=_sha256(candidate),
        source_url="https://example.gov/filing",
        fetched_at="2024-01-15T00:00:00Z",
        index_row=3,
    )

    original_key = f"bronze/{doc['chamber']}/year=2024/{doc['doc_id']}.{doc['ext']}"
    assert result == {"action": "noop", "key": original_key, "sha256": _sha256(candidate)}


@pytest.mark.parametrize("doc", [HOUSE_DOC, SENATE_DOC], ids=["house", "senate"])
def test_different_hash_writes_versioned_key_not_original(doc):
    result = bronze_write(
        chamber=doc["chamber"],
        year=2024,
        doc_id=doc["doc_id"],
        ext=doc["ext"],
        candidate_bytes=b"amended-bytes",
        existing_sha256=_sha256(b"original-bytes"),
        source_url="https://example.gov/filing",
        fetched_at="2024-03-01T00:00:00Z",
        index_row=3,
    )

    original_key = f"bronze/{doc['chamber']}/year=2024/{doc['doc_id']}.{doc['ext']}"
    new_sha256 = _sha256(b"amended-bytes")
    versioned_key = (
        f"bronze/{doc['chamber']}/year=2024/{doc['doc_id']}.{new_sha256[:8]}.{doc['ext']}"
    )

    assert result["action"] == "write"
    assert result["key"] == versioned_key
    assert result["key"] != original_key
    assert result["meta_key"] == versioned_key + ".meta.json"
    assert result["sha256"] == new_sha256
    assert result["meta"]["sha256"] == new_sha256
