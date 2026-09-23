"""S3 key-layout conventions shared by every pipeline stage.

Bronze and silver keys are built here so that every stage agrees on the same
layout without importing each other's internals. Local (MinIO) and AWS (S3)
keys are identical strings; only the endpoint differs.
"""


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
