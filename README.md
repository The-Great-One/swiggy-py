<div align="center">

<img src="https://via.placeholder.com/120x120.png?text=Swiggy" alt="swiggy-py logo" width="120" height="120" />

# swiggy-py

**Unofficial Python client for read-only Swiggy Dineout discovery.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![GitHub issues](https://img.shields.io/github/issues/The-Great-One/swiggy-py)](https://github.com/The-Great-One/swiggy-py/issues)
[![GitHub pull requests](https://img.shields.io/github/issues-pr/The-Great-One/swiggy-py)](https://github.com/The-Great-One/swiggy-py/pulls)
[![GitHub stars](https://img.shields.io/github/stars/The-Great-One/swiggy-py?style=social)](https://github.com/The-Great-One/swiggy-py/stargazers)

[Report Bug](https://github.com/The-Great-One/swiggy-py/issues/new?template=bug_report.md) · [Request Feature](https://github.com/The-Great-One/swiggy-py/issues/new?template=feature_request.md)

</div>

---

## Table of Contents

- [About](#about)
- [Features](#features)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
- [Usage](#usage)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)
- [Contact](#contact)
- [Acknowledgments](#acknowledgments)

---

## About

`swiggy-py` is a design-stage unofficial Python client for read-only Swiggy
Dineout discovery. It is intentionally separate from
[`zomato-py`](https://github.com/The-Great-One/zomato-py); a later
provider-neutral aggregator will merge both sources for broader coverage.

The first release will discover nearby Dineout venues and enrich them with
restaurant details, offers, attributes, reviews, and evidence-backed ranking
signals.

## Features

- ✅ Read-only discovery (no booking, payment, reservation, cart, or account mutation)
- ✅ Guest-first operation (optional auth may enrich but is not required)
- ✅ Source/evidence provenance on every normalized field
- 🚧 Nearby venue discovery
- 🚧 Restaurant detail enrichment
- 🚧 Evidence-backed ranking

## Getting Started

### Prerequisites

- Python 3.10+

### Installation

```bash
git clone https://github.com/The-Great-One/swiggy-py.git
cd swiggy-py
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

## Usage

Architecture approved; implementation has not started. See the canonical design:

- [`docs/superpowers/specs/2026-09-06-swiggy-dineout-client-design.md`](docs/superpowers/specs/2026-09-06-swiggy-dineout-client-design.md)
- [`API_ENDPOINTS.md`](API_ENDPOINTS.md) — endpoint evidence ledger
- [`docs/findings.md`](docs/findings.md) — interesting discoveries, limitations, and discarded paths

## Roadmap

- [ ] v0.1 – Nearby venue discovery
- [ ] v0.2 – Detail enrichment
- [ ] v1.0 – Provider-neutral aggregator merge

See the open issues for the full list of proposed features and known bugs.

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) and
follow our [Code of Conduct](CODE_OF_CONDUCT.md).

## License

Distributed under the MIT License. See [LICENSE](LICENSE) for more information.

## Contact

Sahil Goel – [@The-Great-One](https://github.com/The-Great-One) –
sahilgoel187@gmail.com

Project link: [https://github.com/The-Great-One/swiggy-py](https://github.com/The-Great-One/swiggy-py)

## Acknowledgments

- [Img Shields](https://shields.io)
