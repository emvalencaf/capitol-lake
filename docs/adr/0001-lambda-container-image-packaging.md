# Lambda packaged as a container image, not zip + layers

The extraction Lambda needs Tesseract (a system binary) plus several Python
libraries (pytesseract, Pillow, requests, beautifulsoup4, lxml, pypdf). A
zip + layers split (Tesseract in one layer, scraping/parsing deps in
another) comfortably fits Lambda's size limits (~20-23 MB compressed against
a 250 MB unzipped cap), so size was not the blocker. We chose a **container
image (ECR)** instead, for both local development and production, because
every real-world reference we found for Tesseract-on-Lambda — community
projects and AWS-adjacent examples alike — packages it this way rather than
as a hand-built zip layer, since a container image lets Tesseract be
installed with a plain `yum`/`apt` call instead of manually
compiling/stripping a binary that must exactly match the Lambda runtime's
OS and CPU architecture. It also keeps local and deployed environments
symmetric: the same image runs locally via the Lambda Runtime Interface
Emulator and ships to production unchanged.

## Considered options

- **Zip + 2 layers** (Tesseract layer, scraping-deps layer): rejected
  despite fitting size limits, because it requires manually building a
  portable Tesseract binary for the exact Lambda runtime OS/architecture —
  a maintenance burden with no real-world precedent for this use case.
- **Container image (ECR)**: chosen — matches every reference
  implementation found (e.g. `iwstkhr/aws-lambda-tesseract-ocr-example`,
  AWS's own OCR-on-Lambda-container-image blog pattern), and keeps
  local/production packaging identical.
