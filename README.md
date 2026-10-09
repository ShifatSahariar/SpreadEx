<div align="center">

<img src="docs/assets/spreadex-logo.svg" alt="SpreadEx" width="110">

# SpreadEx

**Run several grammar-based test generators against your program, compare them,<br>and spend a fixed budget on the most diverse inputs first.**

[![CI](https://github.com/ShifatSahariar/SpreadEx/actions/workflows/ci.yml/badge.svg)](https://github.com/ShifatSahariar/SpreadEx/actions/workflows/ci.yml)
[![Acceptance](https://github.com/ShifatSahariar/SpreadEx/actions/workflows/acceptance.yml/badge.svg)](https://github.com/ShifatSahariar/SpreadEx/actions/workflows/acceptance.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![ICST 2026](https://img.shields.io/badge/paper-ICST%202026-8A2BE2)](https://github.com/ShifatSahariar/Embedding-based-Diversity-Mapping)

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-local%20store-003B57?style=for-the-badge&logo=sqlite&logoColor=white)
![Java](https://img.shields.io/badge/Java-11+%20(Rhino%20example)-ED8B00?style=for-the-badge&logo=openjdk&logoColor=white)
![Local-first](https://img.shields.io/badge/Local--first-nothing%20uploaded-2EA44F?style=for-the-badge)

![macOS](https://img.shields.io/badge/macOS-verified-success?style=flat-square&logo=apple&logoColor=white)
![Linux](https://img.shields.io/badge/Linux-partly%20verified-yellow?style=flat-square&logo=linux&logoColor=white)
![Windows](https://img.shields.io/badge/Windows-unverified-lightgrey?style=flat-square&logo=windows&logoColor=white)

</div>

---

<p align="center">
  <img src="src/spreadex/api/static/guides/img/results-generators.png" alt="The SpreadEx Workbench comparing generators by Cluster Coverage" width="860">
</p>

## ✨ What it does

| | |
|---|---|
| 🧬 **Generate** | Fandango, Grammarinator, FuzzingBook and ISLa, each in its own pinned environment, from one grammar or one per generator |
| 🗺️ **Compare** | Embeds every input, clusters them, and scores each generator by **Cluster Coverage** before anything runs |
| 🎯 **Prioritize** | Runs the most diverse inputs first within your time or test budget |
| ⚖️ **Judge** | Separates **crashes**, **timeouts** and **divergences** from inputs your program **correctly rejects** |
| 🔁 **Reproduce** | Every run records its inputs, versions and checksums; findings replay with one click |
| 🖥️ **Workbench** | A five-step local wizard, results views and built-in **Guides** |

## 🚀 Quick start

```bash
pipx install git+https://github.com/ShifatSahariar/SpreadEx.git
```

```bash
spreadex demo          # a real campaign on a small calculator with one real bug
```

Then open the Workbench in your own project:

```bash
cd my-project
spreadex               # the wizard writes spreadex.yaml for you
```

> **Try a real engine:** `spreadex example rhino` sets up the public Rhino 1.9.1 JavaScript engine (downloaded once, SHA-256 verified) with three generators. Needs Java 11+.

## 🧰 Commands

```bash
spreadex init                  # write spreadex.yaml for this project
spreadex doctor                # check the setup; every problem comes with its fix
spreadex generators install fandango grammarinator
spreadex run                   # generate → compare → prioritize → execute → judge
spreadex ui                    # open the Workbench
spreadex results               # how the last campaign went (--all lists them)
spreadex replay <run>          # inspect a past campaign, or --execute it again
spreadex record <run> <gen> -o <dir>   # save a generator's inputs to replay later
spreadex export                # zip the manifest, results and failing inputs
```

<details>
<summary>More commands and flags</summary>

```bash
spreadex example rhino [dir]   # the Rhino showcase project
spreadex runtimes install rhino
spreadex grammar check <file>  # diagnose a grammar; see what each generator supports
spreadex grammar adapt <file>  # derive every generator's dialect
spreadex runs cancel|delete    # manage campaigns
spreadex ui --list | --stop | --read-only

spreadex run --budget 10m -j 8 --selection-signal cc|random --fail-on new-failure
```

The full reference, generated from the CLI itself, is in the Workbench under **Guides → Troubleshooting & CLI**.
</details>

## 🧪 Generators

| Generator | Family | Constraints | Mode |
|---|---|:---:|---|
| ![Fandango](https://img.shields.io/badge/Fandango-1.3.0-7C3AED?style=flat-square) | Constraint-based | ✅ | fresh |
| ![Grammarinator](https://img.shields.io/badge/Grammarinator-26.1-7C3AED?style=flat-square) | Probabilistic | — | fresh |
| ![FuzzingBook](https://img.shields.io/badge/FuzzingBook-1.2.2-7C3AED?style=flat-square) | Probabilistic | — | fresh |
| ![ISLa](https://img.shields.io/badge/ISLa-1.14.4-7C3AED?style=flat-square) | Constraint-based | ✅ | fresh |
| ![Fuzz4All](https://img.shields.io/badge/Fuzz4All-LLM-6B7280?style=flat-square) | LLM-based | — | replays a recording · live generation not available yet |

Installs are deterministic (exact pins, isolated environments, never implicit). Grammars can be BNF, EBNF, ANTLR `.g4`, Fandango or FuzzingBook; SpreadEx converts between them.

## 🔒 Local-first

Your program, its inputs and every result stay in your project's `.spreadex/` folder. The network is used only when you ask: installing a generator (PyPI), opening the Rhino example (Maven Central), or the optional, experimental grammar assistant.

```
my-project/
├── spreadex.yaml
└── .spreadex/   corpus.db · blobs/ · runs/<id>/manifest.json
```

## 📄 Research

The algorithms are those of the ICST 2026 paper *Embedding-based Diversity Mapping for Test Generator Selection and Input Prioritization in Grammar-based Testing*. A CI gate checks this implementation against the published code.
Research code and replication package: **[Embedding-based-Diversity-Mapping](https://github.com/ShifatSahariar/Embedding-based-Diversity-Mapping)** · Artifact: [doi.org/10.5281/zenodo.20071065](https://doi.org/10.5281/zenodo.20071065)

> Cluster Coverage and prioritization are heuristics for spending a budget well; they do not predict faults.

## 🛠️ Development

```bash
pip install -e ".[dev]"
pytest -q -m "not network" --ignore=tests/golden
```

```bash
pip install -e ".[golden]"     # the research-equivalence gate
SPREADEX_REQUIRE_GOLDEN=1 pytest tests/golden -q
```

<details>
<summary>Status and platforms</summary>

**v0.1.0-alpha.** Verified from a clean install on **macOS arm64**. **Linux** is partly verified (the Rhino journey on arm64, the demo journeys on x86_64); the unit suite has not yet passed there. **Windows is unverified.** Not yet: coverage collection, regression mode, adaptive allocation, live Fuzz4All.
</details>

<div align="center"><sub>MIT licensed · Built for grammar-based testing research and practice</sub></div>
