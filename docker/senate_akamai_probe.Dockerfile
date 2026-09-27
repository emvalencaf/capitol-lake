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
# Verified against a real Lambda container runtime (see
# docs/research/senate-akamai-lambda-probe.md's Attempts log): the fixes
# below (PLAYWRIGHT_BROWSERS_PATH, Lambda-required Chromium launch flags in
# senate_akamai_probe.py) came from real deploy failures against this exact
# image, ending in a confirmed "cleared" probe result.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Pinned to the version actually verified working (see the Attempts log
# above) — unlike docker/extract.Dockerfile's requirements.txt, this is a
# single inline pin rather than a separate file, since this image has only
# two runtime dependencies.
RUN pip install --no-cache-dir awslambdaric playwright==1.63.0

# Playwright's default browser path is $HOME/.cache/ms-playwright, resolved
# at both install time (root, building) and launch time (Lambda runs
# container images as a sandboxed, non-root user with its own $HOME, e.g.
# sbx_user1051) — those two paths don't match, so the browser this RUN
# installs is invisible at runtime ("Executable doesn't exist at
# /home/sbx_user.../chromium-.../chrome") unless the path is pinned to
# somewhere both users resolve identically. Setting this env var (not just
# ARG) makes it part of the image config, so it's still in effect at
# runtime, not just during this build step.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

# Installs Chromium plus the OS-level shared libraries it needs
# (`--with-deps`), same as a human would run locally per #23's method.
RUN playwright install --with-deps chromium \
    && chmod -R o+rX /opt/ms-playwright

ARG LAMBDA_TASK_ROOT=/var/task
ARG RIE_VERSION=1.20
RUN mkdir -p ${LAMBDA_TASK_ROOT} \
    && curl -Lo /usr/local/bin/aws-lambda-rie \
        "https://github.com/aws/aws-lambda-runtime-interface-emulator/releases/download/${RIE_VERSION}/aws-lambda-rie" \
    && chmod +x /usr/local/bin/aws-lambda-rie

WORKDIR ${LAMBDA_TASK_ROOT}
COPY src/shared ${LAMBDA_TASK_ROOT}/shared
COPY src/senate_akamai_probe ${LAMBDA_TASK_ROOT}/senate_akamai_probe
COPY docker/extract-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["senate_akamai_probe.handler.handler"]
