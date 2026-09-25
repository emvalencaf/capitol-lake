# senate-akamai-probe

Standalone, run-by-hand Terraform for #29: answers one open question —
does a headless-Playwright request from an actual AWS Lambda egress IP clear
the Senate eFD `/ptr/` Akamai bot/fingerprint check, the way #23's
local-network probe did? Not part of the main stack under `infra/` (see that
module's `main.tf` comment for why), not scheduled, not chained into
anything. Stand it up, invoke it once, record the result, tear it down.

## Prerequisites

- AWS credentials with permission to create an ECR repository, an IAM role,
  and a Lambda function (the same account `infra/`'s main stack targets is
  fine — this creates its own, separately-tagged resources).
- Docker, to build `docker/senate_akamai_probe.Dockerfile`.
- A real `/ptr/` filing UUID to probe, from a captured eFD search response
  (same capture `senate_collect_handler` consumes — see
  `docs/local-dev.md`'s Senate section for how that capture is taken).

## Steps

```bash
# From the repo root.
cd infra/probes/senate-akamai-probe
terraform init
terraform apply   # creates the ECR repo, IAM role, and Lambda (image not yet pushed)

# Build and push the probe image (docker/senate_akamai_probe.Dockerfile is
# UNVERIFIED — see its header comment; confirm the build succeeds before
# relying on it).
cd ../../..
REPO_URL=$(terraform -chdir=infra/probes/senate-akamai-probe output -raw ecr_repository_url)
docker build -f docker/senate_akamai_probe.Dockerfile -t "$REPO_URL:latest" .
aws ecr get-login-password | docker login --username AWS --password-stdin "${REPO_URL%%/*}"
docker push "$REPO_URL:latest"

# Point the Lambda at the pushed image (image_uri only resolves once the
# tag exists in ECR).
cd infra/probes/senate-akamai-probe
terraform apply -var="image_uri=${REPO_URL}:latest"

# Invoke once, against a real /ptr/ filing id.
FUNCTION_NAME=$(terraform output -raw function_name)
aws lambda invoke --function-name "$FUNCTION_NAME" \
  --payload '{"filing_id": "<a real /ptr/ uuid>"}' \
  --cli-binary-format raw-in-base64-out \
  out.json
cat out.json
```

`out.json` is `capitol_lake.probes.senate_akamai_probe.ProbeResult` as JSON:
`filing_id`, `status_code`, `outcome` (`"cleared"`, `"blocked_akamai"`,
`"blocked_other"`, or `"ambiguous"`), and `html_excerpt` (first 2000 chars,
for a human to eyeball if `outcome` is `"ambiguous"` or unexpected).

Record the result in
`docs/research/senate-akamai-lambda-probe.md`, which #28's resolution
depends on.

## Tear down

```bash
terraform destroy
```

No reason to keep this running once the question is answered — it's not a
pipeline stage and has no ongoing purpose.
