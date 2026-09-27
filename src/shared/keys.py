"""S3 key-layout conventions shared by every pipeline stage.

Bronze and silver keys are built here so that every stage agrees on the same
layout without importing each other's internals. Local (MinIO) and AWS (S3)
keys are identical strings; only the endpoint differs.
"""

import re
from typing import NamedTuple

# Reverses bronze_key()'s `bronze/<chamber>/year=<year>/<doc_id>.<ext>` layout.
_BRONZE_KEY_RE = re.compile(r"^bronze/(?P<chamber>[^/]+)/year=(?P<year>\d+)/(?P<doc_id>[^./]+)\.")


class BronzeKeyParts(NamedTuple):
    """The `chamber`/`year`/`doc_id` a bronze key was built from."""

    chamber: str
    year: int
    doc_id: str


class UnrecognizedBronzeKeyError(ValueError):
    """A bronze key doesn't match the `bronze/<chamber>/year=<year>/<doc_id>.<ext>` layout."""


def parse_bronze_key(key: str) -> BronzeKeyParts:
    """Reverse `bronze_key()`: pull `chamber`/`year`/`doc_id` back out of a key.

    Shared by every stage that only receives a bronze key (an S3-key
    reference off an SQS/S3 event, per #43) and needs its components back,
    rather than each stage duplicating the same regex.
    """
    match = _BRONZE_KEY_RE.match(key)
    if match is None:
        raise UnrecognizedBronzeKeyError(f"not a bronze key: {key!r}")
    return BronzeKeyParts(match.group("chamber"), int(match.group("year")), match.group("doc_id"))


def bronze_key(chamber: str, year: int, doc_id: str, ext: str) -> str:
    """Bronze layout: bronze/<chamber>/year=<year>/<doc_id>.<ext>."""
    return f"bronze/{chamber}/year={year}/{doc_id}.{ext}"


def bronze_versioned_key(chamber: str, year: int, doc_id: str, sha256: str, ext: str) -> str:
    """Versioned bronze key for a doc_id whose hash changed.

    bronze/<chamber>/year=<year>/<doc_id>.<sha256[:8]>.<ext>. Never reused
    for the original key: a hash-gated write only takes this path when a
    prior hash is already on record and differs from the candidate's.
    """
    return f"bronze/{chamber}/year={year}/{doc_id}.{sha256[:8]}.{ext}"


def bronze_meta_key(key: str) -> str:
    """Sidecar metadata key for a bronze key: <key>.meta.json."""
    return f"{key}.meta.json"


def silver_key(table: str, chamber: str, year: int, doc_id: str) -> str:
    """Silver layout: silver/<table>/chamber=<chamber>/year=<year>/part-<doc_id>.parquet."""
    return f"silver/{table}/chamber={chamber}/year={year}/part-{doc_id}.parquet"
