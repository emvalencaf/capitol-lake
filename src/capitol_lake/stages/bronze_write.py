"""Bronze contract: a pure, chamber-agnostic hash-gated idempotent writer.

Given candidate bytes for a `doc_id` and the sha256 already on record for it
(if any), decides whether writing those bytes is a no-op or produces a new,
versioned key. The original key is never overwritten: a different hash gets
its own `<doc_id>.<sha256[:8]>.<ext>` key alongside it. This function never
touches S3 or the network; the actual write (and the read of the prior
hash) is the caller's job.
"""

import hashlib

from capitol_lake.keys import bronze_key, bronze_meta_key, bronze_versioned_key


def bronze_write(
    *,
    chamber: str,
    year: int,
    doc_id: str,
    ext: str,
    candidate_bytes: bytes,
    existing_sha256: str | None,
    source_url: str,
    fetched_at: str,
    index_row: int,
) -> dict:
    """Decide whether `candidate_bytes` is a no-op or a new versioned write.

    `existing_sha256` is the sha256 already on record for `doc_id` (from its
    original sidecar `.meta.json`), or `None` if `doc_id` has never been
    stored. Returns a plan dict; it never performs the write itself:

    - No-op (`existing_sha256` matches the candidate's hash): `{"action":
      "noop", "key": <original key>, "sha256": <hash>}`.
    - Write (first time, or a different hash): `{"action": "write", "key":
      <key>, "meta_key": <sidecar key>, "sha256": <hash>, "meta": {...}}`,
      where `key` is the original bronze key on a first write, or a new
      versioned key when `existing_sha256` is set but differs.
    """
    sha256 = hashlib.sha256(candidate_bytes).hexdigest()
    key = bronze_key(chamber, year, doc_id, ext)

    if existing_sha256 == sha256:
        return {"action": "noop", "key": key, "sha256": sha256}

    if existing_sha256 is not None:
        key = bronze_versioned_key(chamber, year, doc_id, sha256, ext)

    return {
        "action": "write",
        "key": key,
        "meta_key": bronze_meta_key(key),
        "sha256": sha256,
        "meta": {
            "source_url": source_url,
            "fetched_at": fetched_at,
            "sha256": sha256,
            "chamber": chamber,
            "doc_id": doc_id,
            "year": year,
            "ext": ext,
            "index_row": index_row,
        },
    }
