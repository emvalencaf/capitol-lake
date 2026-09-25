# Throwaway probe image (#29) — NOT one of the pipeline stages in
# docs/local-dev.md's stage/handler convention. Answers a single open
# question (does a Lambda-origin headless-Playwright request clear the
# Senate eFD Akamai check?) and is meant to be built, run once, and torn
# down; see infra/probes/senate-akamai-probe/README.md.
#
# Playwright's Chromium download needs real shared libraries (nss, atk,
# cups, gtk3, ...) that the AWS Lambda Python base image's minimal
# Amazon Linux userland doesn't carry, so this follows the same
# alternative-base-image pattern as docker/extract.Dockerfile (ADR-0011)
# instead of `docker/lambda.Dockerfile`'s AWS base: `awslambdaric` (Runtime
# Interface Client) via pip, `aws-lambda-rie` (Runtime Interface Emulator)
# downloaded separately for local testing, both wired up by
# extract-entrypoint.sh.
#
# UNVERIFIED: this Dockerfile has not been built or run against a real
# Lambda container runtime — Playwright's Chromium is heavy (~300MB+) and
# whichever system libraries `playwright install --with-deps` pulls in on
# Debian may still need adjustment once someone actually builds this image.
# Confirm `docker build` and a local RIE invocation succeed before relying
# on it for the live probe.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir awslambdaric playwright

# Installs Chromium plus the OS-level shared libraries it needs
# (`--with-deps`), same as a human would run locally per #23's method.
RUN playwright install --with-deps chromium

ARG LAMBDA_TASK_ROOT=/var/task
ARG RIE_VERSION=1.20
RUN mkdir -p ${LAMBDA_TASK_ROOT} \
    && curl -Lo /usr/local/bin/aws-lambda-rie \
        "https://github.com/aws/aws-lambda-runtime-interface-emulator/releases/download/${RIE_VERSION}/aws-lambda-rie" \
    && chmod +x /usr/local/bin/aws-lambda-rie

WORKDIR ${LAMBDA_TASK_ROOT}
COPY src/capitol_lake ${LAMBDA_TASK_ROOT}/capitol_lake
COPY docker/extract-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["capitol_lake.handlers.senate_akamai_probe_handler.handler"]
