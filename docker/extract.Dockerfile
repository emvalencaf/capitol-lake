# Extraction Lambda: the one stage in this repo that needs Tesseract (a
# system binary), which isn't available via `dnf` on the AWS Lambda Python
# base image's default repos (confirmed against both this image and plain
# `amazonlinux:2023` directly). Per AWS's documented "alternative base
# image" pattern, this uses a plain Debian image instead, where Tesseract
# installs the way ADR-0001 always intended: a plain package-manager call
# (`apt-get install tesseract-ocr`, the same package this repo's own CI
# already installs, see .github/workflows/ci.yml). An alternative base image
# bundles neither the Lambda Runtime Interface Client nor the Runtime
# Interface Emulator, so both are installed explicitly here (see
# extract-entrypoint.sh); every other stage's image still uses the AWS base
# image (lambda.Dockerfile, house_collect.Dockerfile, senate_collect.Dockerfile)
# since none of them need this.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# The Runtime Interface Emulator (RIE), for local/RIE-based testing only;
# real Lambda never runs this binary. Bundled automatically by AWS base
# images, but an alternative base image has to install it itself.
ADD https://github.com/aws/aws-lambda-runtime-interface-emulator/releases/latest/download/aws-lambda-rie /usr/local/bin/aws-lambda-rie
RUN chmod +x /usr/local/bin/aws-lambda-rie

WORKDIR /var/task
ENV LAMBDA_TASK_ROOT=/var/task

COPY docker/extract-requirements.txt .
RUN pip install --no-cache-dir -r extract-requirements.txt

COPY src/capitol_lake ./capitol_lake

COPY docker/extract-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["capitol_lake.handlers.extract_handler.handler"]
