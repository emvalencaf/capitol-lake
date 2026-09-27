"""Reference pipeline stage: the pure-function half of the stage contract.

A real stage (collect, extract, ticker/LLM-fallback, silver-write) follows
this same shape: a function that takes an S3 key or raw bytes and returns a
plain, structured dict. It never touches S3, SQS, or any other AWS service
directly, which is what lets it be tested and run without mocking AWS.
"""


def process(bronze_key: str) -> dict:
    """Echo back the given bronze key wrapped in a structured result.

    Stand-in for a real stage's business logic; future stages replace the
    body while keeping the same "one argument in, one dict out" shape.
    """
    return {"bronze_key": bronze_key, "ok": True}
