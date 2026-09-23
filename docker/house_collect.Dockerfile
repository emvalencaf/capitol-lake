# House collector Lambda, packaged the same way as every stage (see
# docs/local-dev.md). No dependencies beyond the stdlib and the boto3
# already bundled in the Lambda Python base image, so no pip install layer
# is needed.
FROM public.ecr.aws/lambda/python:3.12

COPY src/capitol_lake ${LAMBDA_TASK_ROOT}/capitol_lake

CMD ["capitol_lake.handlers.house_collect_handler.handler"]
