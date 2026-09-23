# Reference container image for a pipeline-stage Lambda. AWS's Python base
# images bundle the Lambda Runtime Interface Emulator and use it
# automatically when run outside Lambda, so no separate RIE install is
# needed for local testing (see docs/local-dev.md).
#
# Future stages with real dependencies (pypdf, pytesseract, ...) add a
# `pip install` layer here; the stub has none.
FROM public.ecr.aws/lambda/python:3.12

COPY src/capitol_lake ${LAMBDA_TASK_ROOT}/capitol_lake

CMD ["capitol_lake.handlers.stub_handler.handler"]
