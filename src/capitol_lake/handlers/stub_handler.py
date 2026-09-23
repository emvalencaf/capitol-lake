"""Thin Lambda adapter for the stub stage.

Wires a Lambda event to the pure function in `capitol_lake.stages.stub` and
returns its result unchanged. Handlers stay thin by convention: they only
translate the event shape into the pure function's arguments and are not
unit-tested (see docs/local-dev.md); the pure function underneath is.
"""

from capitol_lake.stages.stub import process


def handler(event: dict, context: object) -> dict:
    return process(event["bronze_key"])
