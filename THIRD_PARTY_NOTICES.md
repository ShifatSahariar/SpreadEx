# Third-party notices

SpreadEx is released under the MIT License (see `LICENSE`). It drives several input generators,
each installed on demand into its own environment and never bundled with SpreadEx. Their licences
are their own:

| Generator | Licence | How SpreadEx uses it |
|---|---|---|
| FuzzingBook | MIT | installed from PyPI, pinned |
| Fandango | EUPL-1.2 | installed from PyPI, pinned |
| ISLa | GPL-3.0 | installed from PyPI, pinned; run as a separate process, never imported |
| Grammarinator | BSD-3-Clause | installed from PyPI, pinned |
| Fuzz4All | CC BY 4.0 | cloned from GitHub at a pinned commit and patched (below) |

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
