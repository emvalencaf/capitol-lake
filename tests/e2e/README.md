# End-to-end tests

Intentionally empty today. Every test under `tests/units/` is a pure-function
or fixture test — none of them touch live network, real S3, or a real Lambda
runtime.

A test belongs here instead once it actually exercises one of those: a real
Lambda RIE invocation (`docker/extract-entrypoint.sh`'s RIE path, see
`docs/local-dev.md`), or a run against `docker-compose.yml`'s local stack
(MinIO + `elasticmq`, driven the way `scripts/invoke-collectors.sh` drives it
by hand) asserting on the actual objects/messages produced, not just the pure
decision logic those stages wrap.
