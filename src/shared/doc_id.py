"""House doc-id routing: shared between `house_collect` and `extract_data`.

`house_collect` uses `route_doc_id` to classify each index entry while
collecting; `extract_data` uses the same function to route a bronze key's
doc id to the right extractor (digital vs. scanned). Kept out of both
Lambdas' own packages since it's the one piece of House-specific logic two
different Lambda images both need.
"""

from __future__ import annotations

DIGITAL_PREFIX = "20"
SCANNED_PREFIXES = ("82", "91")


class UnknownDocIdPrefixError(ValueError):
    """A doc id doesn't match any known House filing-kind prefix."""


def route_doc_id(doc_id: str) -> str:
    """Classify a House doc id as `"digital"` or `"scanned"` by its prefix.

    Digital filings (`20…`) are text-layer PDFs, extractable directly.
    Scanned filings (`82…`, `91…`) are paper-form scans requiring OCR
    downstream. Anything else is a prefix the collector doesn't recognize.
    """
    if doc_id.startswith(DIGITAL_PREFIX):
        return "digital"
    if doc_id.startswith(SCANNED_PREFIXES):
        return "scanned"
    raise UnknownDocIdPrefixError(f"unrecognized House doc id prefix: {doc_id!r}")
