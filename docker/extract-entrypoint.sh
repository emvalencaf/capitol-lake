#!/bin/sh
# Resolves ADR-0001's deferred item (#43): the Lambda Python base image's
# `dnf` has no `tesseract` package (confirmed against AL2023's own repos,
# not just this image), so this stage instead uses AWS's documented
# "alternative base image" pattern (a plain Debian image, `apt-get install
# tesseract-ocr`, and the `awslambdaric` runtime interface client installed
# via pip) rather than the container-image-vs-zip+layers tradeoff ADR-0001
# actually settled. A non-AWS base image bundles no Runtime Interface
# Emulator, so `aws-lambda-rie` is installed separately in the Dockerfile
# and only used here when not already running inside Lambda (real Lambda
# always sets `AWS_LAMBDA_RUNTIME_API` itself).
if [ -z "${AWS_LAMBDA_RUNTIME_API:-}" ]; then
  exec /usr/local/bin/aws-lambda-rie /usr/local/bin/python3 -m awslambdaric "$@"
else
  exec /usr/local/bin/python3 -m awslambdaric "$@"
fi
