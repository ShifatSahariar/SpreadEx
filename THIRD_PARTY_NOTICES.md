# Third-party notices

SpreadEx is released under the MIT License (see `LICENSE`). It drives several input generators,
each installed on demand into its own environment and never bundled with SpreadEx. Their licences
are their own:

| Generator | Version | Licence | How SpreadEx uses it |
|---|---|---|---|
| FuzzingBook | 1.2.2 | MIT | installed from PyPI, pinned, unmodified |
| Fandango | 1.3.0 | EUPL-1.2 | installed from PyPI, pinned, unmodified |
| ISLa | 1.14.4 | GPL-3.0 | installed from PyPI, pinned, unmodified; run as a separate process, never imported |
| Grammarinator | 26.1 | BSD-3-Clause | installed from PyPI, pinned, unmodified |
| Fuzz4All | commit `0bf42fe` | CC BY 4.0 | cloned from GitHub at a pinned commit and patched (below) |

Other components downloaded on demand, also unmodified and never bundled:

| Component | Licence | How SpreadEx uses it |
|---|---|---|
| UniXcoder (`microsoft/unixcoder-base`) | Apache-2.0 | embedding model for the diversity map, downloaded once from Hugging Face (`[neural]` extra) |
| Rhino 1.9.1 (`rhino-all-1.9.1.jar`) | MPL-2.0 | the Rhino example's system under test, downloaded from Maven Central and SHA-256 verified |

## Fuzz4All

Fuzz4All: Universal Fuzzing with Large Language Models. Chunqiu Steven Xia, Matteo Paltenghi,
Jia Le Tian, Michael Pradel, Lingming Zhang. ICSE 2024. <https://github.com/fuzz4all/fuzz4all>,
licensed under the Creative Commons Attribution 4.0 International licence (CC BY 4.0), as stated
in the repository's `LICENSE` at the pinned commit `0bf42fe037c8761bdde61e1c37a0946e8103fba1`.

SpreadEx does not redistribute Fuzz4All. `spreadex generators install fuzz4all` clones the
repository at that commit and applies `src/spreadex/generators/patches/fuzz4all/0001-spreadex.patch`,
which SpreadEx ships. **The patch modifies the original work.** It contains:

- changes adapted from the ClusGram study's patch of the same artifact: a chat-completions model
  backend (`Fuzz4All/model.py`), autoprompting restored from upstream commit `6d11693`
  (`Fuzz4All/target/target.py`), usage accounting and bounded retries in
  `Fuzz4All/util/api_request.py`;
- SpreadEx's own addition: one target class (`Fuzz4All/target/spreadex/`) that executes candidate
  programs with SpreadEx's runner and oracle, and its registration in `Fuzz4All/make_target.py`.

The patch's SHA-256 is recorded in `src/spreadex/generators/catalog/fuzz4all.yaml` and in every
installation's receipt.
