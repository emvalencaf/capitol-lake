"""Lambda entry point for the throwaway Senate-Akamai probe (#29).

See `capitol_lake.probes.senate_akamai_probe` for what this answers and why
it isn't a pipeline stage. Invoke by hand once (`infra/probes/senate-akamai-
probe/`), e.g.:

    aws lambda invoke --function-name capitol-lake-senate-akamai-probe \\
      --payload '{"filing_id": "<a real /ptr/ uuid>"}' --cli-binary-format \\
      raw-in-base64-out out.json

A real `/ptr/` uuid comes from a captured eFD search response (same capture
`senate_collect_handler` consumes, see docs/local-dev.md's Senate section) —
this probe never drives the search UI itself, only fetches one already-known
filing id.
"""

from __future__ import annotations

from dataclasses import asdict

from capitol_lake.probes.senate_akamai_probe import run_probe
from capitol_lake.stages.senate_collect import SENATE_FILING_URL_TEMPLATE


def handler(event: dict, context: object) -> dict:
    result = run_probe(event["filing_id"], url_template=SENATE_FILING_URL_TEMPLATE)
    return asdict(result)
