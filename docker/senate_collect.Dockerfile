# Senate collector Lambda, packaged the same way as every stage (see
# docs/local-dev.md). No dependencies beyond the stdlib and the boto3
# already bundled in the Lambda Python base image, so no pip install layer
# is needed. Not scheduled (#18): invoked manually with a locally exported
# search-result payload.
FROM public.ecr.aws/lambda/python:3.12

COPY src/shared ${LAMBDA_TASK_ROOT}/shared
COPY src/senate_collect ${LAMBDA_TASK_ROOT}/senate_collect

CMD ["senate_collect.handler.handler"]
