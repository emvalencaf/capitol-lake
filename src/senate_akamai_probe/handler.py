"""Lambda entry point for the throwaway Senate-Akamai probe (#29).

See `senate_akamai_probe.probe` for what this answers and why
it isn't a pipeline stage. Invoke by hand once (`infra/probes/senate-akamai-
probe/`), e.g.:

    aws lambda invoke --function-name capitol-lake-senate-akamai-probe \\
      --payload '{"filing_id": "<a real /ptr/ uuid>"}' --cli-binary-format \\
      raw-in-base64-out out.json

A real `/ptr/` uuid comes from a captured eFD search response (same capture
`senate_collect.handler` consumes, see docs/local-dev.md's Senate section) —
this probe never drives the search UI itself, only fetches one already-known
filing id.
"""

from __future__ import annotations

from dataclasses import asdict

from senate_akamai_probe.probe import run_probe
from shared.senate_index import SENATE_FILING_URL_TEMPLATE


def handler(event: dict, context: object) -> dict:
    result = run_probe(event["filing_id"], url_template=SENATE_FILING_URL_TEMPLATE)
    return asdict(result)
