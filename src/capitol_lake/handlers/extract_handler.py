"""Thin Lambda adapter for the extract stage.

Wires a Lambda event's `bronze_key` to `extract_house_filing`, fetching the
bronze PDF and writing the two returned silver Parquet part files with a
real S3 client (`boto3`). Handlers stay thin by convention: they only
translate the event shape and real clients into the pure function's
arguments and are not unit-tested (see docs/local-dev.md); the pure function
underneath is.
"""

import os

import boto3

from capitol_lake.stages.extract import extract_house_filing

BRONZE_BUCKET = os.environ.get("BRONZE_BUCKET", "bronze")
SILVER_BUCKET = os.environ.get("SILVER_BUCKET", "silver")


def handler(event: dict, context: object) -> dict:
    s3_client = boto3.client("s3", endpoint_url=os.environ.get("AWS_ENDPOINT_URL_S3"))

    bronze_key = event["bronze_key"]
    pdf_bytes = s3_client.get_object(Bucket=BRONZE_BUCKET, Key=bronze_key)["Body"].read()

    result = extract_house_filing(pdf_bytes, bronze_key=bronze_key)

    for table in ("filings", "transactions"):
        part = result[table]
        s3_client.put_object(Bucket=SILVER_BUCKET, Key=part["key"], Body=part["bytes"])

    return {
        "kind": result["kind"],
        "filings_key": result["filings"]["key"],
        "transactions_key": result["transactions"]["key"],
    }
