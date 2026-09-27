# Automated Senate collector Lambda (#68), packaged like the throwaway
# `docker/senate_akamai_probe.Dockerfile` (#29) rather than the plain
# `docker/lambda.Dockerfile` base every stdlib-only stage uses — Playwright's
# Chromium download needs real shared libraries (nss, atk, cups, gtk3, ...)
# the AWS Lambda Python base image's minimal userland doesn't carry, so this
# follows the same alternative-base-image pattern as
# `docker/extract.Dockerfile` (ADR-0011): `awslambdaric` (Runtime Interface
# Client) via pip, `aws-lambda-rie` (Runtime Interface Emulator) downloaded
# separately for local testing, both wired up by `extract-entrypoint.sh`.
#
# Unlike the probe, this image is a real pipeline stage (see
# docs/local-dev.md) meant to stay up, not be built/run once and torn down.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

# boto3 isn't bundled here the way it is in the AWS Lambda base image, so it
# needs its own pip install alongside Playwright (pinned to the version
# confirmed working against the live Akamai check, see
# `docker/senate_akamai_probe.Dockerfile`).
RUN pip install --no-cache-dir awslambdaric boto3 playwright==1.63.0

# Same fix as `docker/senate_akamai_probe.Dockerfile`: Playwright's default
# browser path ($HOME/.cache/ms-playwright) resolves differently at install
# time (root, building) than at launch time (Lambda's non-root sandboxed
# runtime user, e.g. sbx_user1051), so the browser this RUN installs would
# otherwise be invisible at runtime unless pinned to a path both users
# resolve identically.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

# Installs Chromium plus the OS-level shared libraries it needs
# (`--with-deps`), same as `docker/senate_akamai_probe.Dockerfile`.
RUN playwright install --with-deps chromium \
    && chmod -R o+rX /opt/ms-playwright

ARG LAMBDA_TASK_ROOT=/var/task
ARG RIE_VERSION=v1.37
RUN mkdir -p ${LAMBDA_TASK_ROOT} \
    && curl -Lo /usr/local/bin/aws-lambda-rie \
        "https://github.com/aws/aws-lambda-runtime-interface-emulator/releases/download/${RIE_VERSION}/aws-lambda-rie" \
    && chmod +x /usr/local/bin/aws-lambda-rie

WORKDIR ${LAMBDA_TASK_ROOT}
COPY src/shared ${LAMBDA_TASK_ROOT}/shared
COPY src/senate_collect_automated ${LAMBDA_TASK_ROOT}/senate_collect_automated
COPY docker/extract-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["senate_collect_automated.handler.handler"]
