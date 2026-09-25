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

`scripts/deploy-senate-akamai-probe.sh` (repo root) automates all of the
below — build, push, apply, invoke, and destroy:

```bash
scripts/deploy-senate-akamai-probe.sh up                  # build, push, apply
scripts/deploy-senate-akamai-probe.sh invoke <filing-id>   # invoke once, print the result
scripts/deploy-senate-akamai-probe.sh down                 # terraform destroy
```

Equivalent manual steps, if you'd rather run each command yourself:

```bash
# From the repo root.
cd infra/probes/senate-akamai-probe
terraform init

# Create the ECR repo (and IAM role) only — target-only, since the Lambda
# resource can't be created yet: it points at an image that doesn't exist
# in ECR until the next step pushes one. image_uri has no default, so a
# placeholder value satisfies Terraform's variable validation without
# being used by the targeted resource.
terraform apply -target=aws_ecr_repository.probe -var="image_uri=pending"

# Build and push the probe image (docker/senate_akamai_probe.Dockerfile is
# UNVERIFIED — see its header comment; confirm the build succeeds before
# relying on it).
cd ../../..
REPO_URL=$(terraform -chdir=infra/probes/senate-akamai-probe output -raw ecr_repository_url)
docker build -f docker/senate_akamai_probe.Dockerfile -t "$REPO_URL:latest" .
aws ecr get-login-password | docker login --username AWS --password-stdin "${REPO_URL%%/*}"
docker push "$REPO_URL:latest"

# Now the image exists in ECR: apply the full stack, including the Lambda.
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

`out.json` (or the script's `invoke` output) is
`capitol_lake.probes.senate_akamai_probe.ProbeResult` as JSON: `filing_id`,
`status_code`, `outcome` (`"cleared"`, `"blocked_akamai"`, `"blocked_other"`,
or `"ambiguous"`), and `html_excerpt` (first 2000 chars, for a human to
eyeball if `outcome` is `"ambiguous"` or unexpected).

Record the result in
`docs/research/senate-akamai-lambda-probe.md`, which #28's resolution
depends on.

## Tear down

```bash
scripts/deploy-senate-akamai-probe.sh down
# or, equivalently:
terraform destroy
```

No reason to keep this running once the question is answered — it's not a
pipeline stage and has no ongoing purpose.
