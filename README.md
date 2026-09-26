<a id="readme-top"></a>

<br />
<div align="center">
  <h3 align="center">Capitol Lake</h3>

  <p align="center">
    Data engineering pipeline.
    <br />
    <a href="CONTRIBUTING.md"><strong>Explore the docs »</strong></a>
    <br />
    <br />
    <a href="https://github.com/emvalencaf/capitol-lake/issues/new">Report Bug</a>
    &middot;
    <a href="https://github.com/emvalencaf/capitol-lake/issues/new">Request Feature</a>
  </p>
</div>

<details>
  <summary>Table of Contents</summary>
  <ol>
    <li>
      <a href="#about-the-project">About The Project</a>
      <ul>
        <li><a href="#built-with">Built With</a></li>
      </ul>
    </li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#installation">Installation</a></li>
      </ul>
    </li>
    <li><a href="#usage">Usage</a></li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#contact">Contact</a></li>
    <li><a href="#acknowledgments">Acknowledgments</a></li>
  </ol>
</details>

## About The Project

Data engineering pipeline. See [`docs/architecture.md`](docs/architecture.md)
for the architecture overview and diagrams.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

### Built With

* [Python](https://www.python.org) managed with [uv](https://docs.astral.sh/uv/)
* [ruff](https://docs.astral.sh/ruff/)

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Getting Started

### Prerequisites

* [`uv`](https://docs.astral.sh/uv/)
* [Docker](https://docs.docker.com/get-docker/) and `docker-compose`, for the
  local MinIO/Lambda scaffold
* [Tesseract OCR](https://tesseract-ocr.github.io/) (`tesseract-ocr` on
  Debian/Ubuntu), for the scanned House PDF extractor's tests

### Installation

1. Clone the repository
   ```bash
   git clone https://github.com/emvalencaf/capitol-lake.git
   cd capitol-lake
   ```
2. Enable the git hooks
   ```bash
   scripts/setup.sh
   ```
3. Install Python dependencies
   ```bash
   uv sync
   ```

For a production deploy, see [`infra/README.md`](infra/README.md); for the
associated AWS cost estimate, see [`docs/cost.md`](docs/cost.md).

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Usage

Run the test suite:

```bash
uv run pytest
```

Pipeline stages follow a pure-function-plus-handler convention and run
locally against a MinIO stand-in for S3, with each stage's Lambda handler
runnable through the Lambda Runtime Interface Emulator exactly as it will
run in AWS. See [`docs/local-dev.md`](docs/local-dev.md) for the full
conventions and how to bring up the local stack, and
[`docs/metrics.md`](docs/metrics.md) for extraction-accuracy metrics.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Roadmap

- [ ] First milestone

See the [open issues](https://github.com/emvalencaf/capitol-lake/issues) for proposed features and known issues.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Contributing

Contributions follow the branch strategy and commit convention in
[CONTRIBUTING.md](CONTRIBUTING.md): cut a branch from `development`, commit as
`tag(subject/subsubject): summary`, and open a pull request into `development`.
Coding and documentation rules are in [CODE_STANDARDS.md](CODE_STANDARDS.md).

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## License

No license has been chosen yet.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Contact

Edson Mota Valença Filho - [@emvalencaf](https://github.com/emvalencaf)

Project Link: [https://github.com/emvalencaf/capitol-lake](https://github.com/emvalencaf/capitol-lake)

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Acknowledgments

* [Best-README-Template](https://github.com/othneildrew/Best-README-Template)

<p align="right">(<a href="#readme-top">back to top</a>)</p>
