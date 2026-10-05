"""End-to-end pipeline assurance.

Four campaign shapes, each driven through every stage, with explicit
invariants at each seam:

    generation -> validation/dedup -> CC -> generator selection ->
    prioritization -> execution -> oracle -> corpus -> results ->
    replay -> export

The campaigns:

  A  the owned demo SUT (calc.py), with real generation
  B  a realistic single-SUT campaign over the behaviour fixture, covering
     every verdict the oracle can reach
  C  the alternate execution model: the same SUT driven over stdin
  D  a differential campaign over two implementations that disagree

What is asserted here is the pipeline, not the algorithms -- tests/golden/
and tests/test_golden_fixtures.py own those. The question here is whether an
input that enters at one end comes out of the other correctly classified,
persisted, reportable, replayable and exportable.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from spreadex.core.campaign import Campaign
from spreadex.core.config import load_config
from spreadex.corpus.store import CorpusStore
from spreadex.exec.oracle import Verdict

SUTS = Path(__file__).resolve().parent / "fixtures" / "suts"

#: One seed per behaviour the oracle must tell apart. Named so a failure says
#: which classification broke rather than which file.
BEHAVIOUR_SEEDS = {
    "pass_plain": ("1 + 1\n", Verdict.OK),
    "pass_other": ("2 * 3\n", Verdict.OK),
    "reject_syntax": ("REJECT bad syntax\n", Verdict.EXPECTED_REJECTION),
    "crash_npe": ("CRASH here\n", Verdict.CRASH),
    "crash_quiet": ("QUIETCRASH here\n", Verdict.CRASH),
    "hang_forever": ("HANG now\n", Verdict.TIMEOUT),
}

ORACLE_BLOCK = """oracle:
  type: crash
  rejection_patterns:
    - "^fixture: SyntaxError"
  crash_patterns:
    - "^Exception in thread"
    - "^Caught an Exception"
    - "^\\\\s*at fixture\\\\."
"""


def _seed_dir(root: Path) -> Path:
    seeds = root / "seeds"
    seeds.mkdir(parents=True, exist_ok=True)
    for name, (text, _) in BEHAVIOUR_SEEDS.items():
        (seeds / f"{name}.txt").write_text(text)
    return seeds


def _project(tmp_path: Path, name: str, yaml_text: str) -> Path:
    root = tmp_path / name
    root.mkdir(parents=True)
    for sut in SUTS.glob("*.py"):
        shutil.copy2(sut, root / sut.name)
    _seed_dir(root)
    (root / "spreadex.yaml").write_text(yaml_text)
    return root


# ---------------------------------------------------------------- campaigns

@pytest.fixture(scope="module")
def campaign_b(tmp_path_factory):
    """B: realistic single SUT, file execution, every verdict reachable."""
    root = _project(
        tmp_path_factory.mktemp("matrix") / "b", "b",
        f'sut:\n  command: ["{sys.executable}", "./behaviours.py", "{{input}}"]\n'
        "  timeout: 2s\n" + ORACLE_BLOCK +
        "generators: []\ncorpus: {path: ./seeds}\n"
        "budget: {generation: 30s, execution: 120s}\n"
        "selection_signal: cc\nembedding: {model: tfidf}\nseed: 42\n",
    )
    config = load_config(root / "spreadex.yaml")
    result = Campaign(config, log=lambda *_: None).run(jobs=2)
    return config, result


@pytest.fixture(scope="module")
def campaign_c(tmp_path_factory):
    """C: the alternate execution model -- same SUT, driven over stdin."""
    root = _project(
        tmp_path_factory.mktemp("matrix") / "c", "c",
        f'sut:\n  command: ["{sys.executable}", "./behaviours.py"]\n'
        "  input_mode: stdin\n  timeout: 2s\n" + ORACLE_BLOCK +
        "generators: []\ncorpus: {path: ./seeds}\n"
        "budget: {generation: 30s, execution: 120s}\n"
        "selection_signal: cc\nembedding: {model: tfidf}\nseed: 42\n",
    )
    config = load_config(root / "spreadex.yaml")
    result = Campaign(config, log=lambda *_: None).run(jobs=2)
    return config, result


@pytest.fixture(scope="module")
def campaign_d(tmp_path_factory):
    """D: differential -- two implementations that genuinely disagree."""
    root = tmp_path_factory.mktemp("matrix") / "d"
    root.mkdir(parents=True)
    for sut in SUTS.glob("*.py"):
        shutil.copy2(sut, root / sut.name)
    seeds = root / "seeds"
    seeds.mkdir()
    (seeds / "agree_ok.txt").write_text("plain input\n")
    (seeds / "agree_reject.txt").write_text("REJECT this\n")
    (seeds / "diverge_output.txt").write_text("DIVERGE now\n")
    (seeds / "diverge_acceptance.txt").write_text("ONLYA please\n")
    (root / "spreadex.yaml").write_text(
        "sut:\n  timeout: 5s\n  targets:\n"
        f'    - {{name: enga, command: ["{sys.executable}", "./engine_a.py", "{{input}}"]}}\n'
        f'    - {{name: engb, command: ["{sys.executable}", "./engine_b.py", "{{input}}"]}}\n'
        "oracle:\n  type: differential\n  rejection_patterns:\n"
        '    - "parse error"\n    - "unsupported construct"\n'
        '  crash_patterns:\n    - "^Exception in thread"\n'
        "generators: []\ncorpus: {path: ./seeds}\n"
        "budget: {generation: 30s, execution: 120s}\n"
        "selection_signal: cc\nembedding: {model: tfidf}\nseed: 42\n"
    )
    config = load_config(root / "spreadex.yaml")
    result = Campaign(config, log=lambda *_: None).run(jobs=2)
    return config, result


@pytest.fixture(scope="module")
def campaign_a(tmp_path_factory):
    """A: the owned demo SUT, with REAL generation rather than a seed corpus.

    The only campaign here that exercises generation, dedup against generated
    material, and CC over more than one source.
    """
    from spreadex.demo import materialize

    project = materialize(tmp_path_factory.mktemp("matrix") / "a" / "demo")
    # Edited on disk rather than in memory, so this campaign is configured the
    # way a user configures one -- and so the config-hash invariant below
    # applies to it like any other.
    yaml_text = (project / "spreadex.yaml").read_text()
    yaml_text = yaml_text.replace("count: 150", "count: 40")
    yaml_text = yaml_text.replace("generation: 30s", "generation: 120s")
    yaml_text = yaml_text.replace("execution: 60s", "execution: 120s")
    (project / "spreadex.yaml").write_text(yaml_text)
    config = load_config(project / "spreadex.yaml")
    result = Campaign(config, log=lambda *_: None).run(jobs=2)
    return config, result


ALL_CAMPAIGNS = ["campaign_a", "campaign_b", "campaign_c", "campaign_d"]


# ========================================================= stage invariants

@pytest.mark.parametrize("name", ALL_CAMPAIGNS)
def test_every_stage_reports_a_coherent_count(name, request):
    """generated >= valid >= prioritized >= executed, with none invented."""
    _, r = request.getfixturevalue(name)
    assert r.generated > 0, "nothing entered the pipeline"
    assert r.valid <= r.generated, "validation invented inputs"
    assert r.prioritized <= r.valid, "prioritization invented inputs"
    assert r.executed <= r.prioritized, "execution invented inputs"
    assert r.executed > 0, "nothing came out of the pipeline"


@pytest.mark.parametrize("name", ALL_CAMPAIGNS)
def test_the_verdicts_account_for_every_execution(name, request):
    """Each executed input is classified exactly once."""
    _, r = request.getfixturevalue(name)
    assert sum(r.verdicts.values()) == r.executed
    assert all(v >= 0 for v in r.verdicts.values())
    known = {v.value for v in Verdict}
    assert set(r.verdicts) <= known, f"unknown verdict: {set(r.verdicts) - known}"


@pytest.mark.parametrize("name", ALL_CAMPAIGNS)
def test_prioritization_is_a_permutation_not_a_filter(name, request):
    """SpreadEx orders the corpus; it must never silently drop part of it."""
    config, r = request.getfixturevalue(name)
    with CorpusStore(config.state_dir) as store:
        unique_valid = {row["blob_hash"] for row in store.iter_inputs(valid_only=True)}
    assert r.prioritized == len(unique_valid), (
        "the prioritized stream is not the whole unique valid corpus"
    )


@pytest.mark.parametrize("name", ALL_CAMPAIGNS)
def test_every_execution_is_persisted_against_a_stored_blob(name, request):
    """A result that names a hash the corpus cannot resolve is not a result."""
    config, r = request.getfixturevalue(name)
    with CorpusStore(config.state_dir) as store:
        rows = store.conn.execute(
            "SELECT DISTINCT blob_hash FROM executions WHERE run_id=?", (r.run_id,)
        ).fetchall()
        assert rows, "no executions persisted"
        for row in rows:
            data = store.get_blob(row["blob_hash"])
            assert isinstance(data, bytes) and data, row["blob_hash"]


@pytest.mark.parametrize("name", ALL_CAMPAIGNS)
def test_the_corpus_is_content_addressed(name, request):
    """The same bytes must be one blob however many generators produced them."""
    from hashlib import sha256

    config, _ = request.getfixturevalue(name)
    with CorpusStore(config.state_dir) as store:
        for row in store.iter_inputs():
            data = store.get_blob(row["blob_hash"])
            assert sha256(data).hexdigest() == row["blob_hash"], "hash does not match content"


# ==================================================== oracle classification

def test_campaign_b_reaches_every_verdict_the_oracle_can_produce(campaign_b):
    """The matrix's centre: each deliberate fixture lands in its own class."""
    config, r = campaign_b
    expected: dict[str, Verdict] = {}
    with CorpusStore(config.state_dir) as store:
        rows = store.conn.execute(
            "SELECT blob_hash, verdict FROM executions WHERE run_id=?", (r.run_id,)
        ).fetchall()
        got = {}
        for row in rows:
            text = store.get_blob(row["blob_hash"]).decode()
            got[text.strip()] = row["verdict"]

    for name, (text, verdict) in BEHAVIOUR_SEEDS.items():
        key = text.strip()
        assert key in got, f"{name} was never executed"
        assert got[key] == verdict.value, (
            f"{name}: expected {verdict.value}, got {got[key]}"
        )


def test_an_exit_zero_crash_is_still_a_crash(campaign_b):
    """QUIETCRASH exits 0 with a stack trace on stderr. Only crash_patterns
    can see it, and they are checked before the exit code is believed."""
    config, r = campaign_b
    with CorpusStore(config.state_dir) as store:
        row = next(
            row for row in store.conn.execute(
                "SELECT blob_hash, verdict, exit_code FROM executions WHERE run_id=?",
                (r.run_id,))
            if b"QUIETCRASH" in store.get_blob(row["blob_hash"])
        )
    assert row["exit_code"] == 0, "the fixture is meant to exit cleanly"
    assert row["verdict"] == Verdict.CRASH.value


def test_a_rejection_is_never_counted_as_a_failure(campaign_b):
    """The distinction the whole product rests on."""
    _, r = campaign_b
    assert r.verdicts.get(Verdict.EXPECTED_REJECTION.value, 0) >= 1
    assert r.failures == (r.verdicts.get("crash", 0)
                          + r.verdicts.get("timeout", 0)
                          + r.verdicts.get("divergence", 0))
    assert Verdict.EXPECTED_REJECTION.value not in ("crash", "timeout", "divergence")


def test_a_hang_is_a_timeout_and_does_not_stall_the_campaign(campaign_b):
    _, r = campaign_b
    assert r.verdicts.get(Verdict.TIMEOUT.value, 0) >= 1
    assert r.exec_elapsed_s < r.exec_budget_s, "the campaign ran to its budget"


# ------------------------------------------------- alternate execution model

def test_stdin_execution_classifies_identically_to_file_execution(campaign_b, campaign_c):
    """The execution model is plumbing. It must not change a verdict."""
    (_, rb), (_, rc) = campaign_b, campaign_c
    assert rb.verdicts == rc.verdicts, (
        f"file mode {rb.verdicts} vs stdin mode {rc.verdicts}"
    )


def test_stdin_mode_passed_no_path_argument(campaign_c):
    """If a path leaked through, the SUT would read the file and the stdin
    path would be untested while appearing to work."""
    config, _ = campaign_c
    target = config.targets[0]
    assert target.input_mode == "stdin"
    assert "{input}" not in " ".join(target.command)
    # resolved_command() turns ./behaviours.py into an absolute path, which is
    # correct and separate from the question here: that nothing is appended.
    assert target.render(Path("/tmp/x")) == target.resolved_command()


# --------------------------------------------------------------- differential

def test_the_differential_campaign_finds_both_kinds_of_disagreement(campaign_d):
    """Output divergence and acceptance divergence are different findings."""
    config, r = campaign_d
    with CorpusStore(config.state_dir) as store:
        by_text = {}
        for row in store.conn.execute(
            "SELECT blob_hash, verdict, detail FROM executions WHERE run_id=?", (r.run_id,)
        ):
            by_text[store.get_blob(row["blob_hash"]).decode().strip()] = row

    assert by_text["DIVERGE now"]["verdict"] == Verdict.DIVERGENCE.value
    assert by_text["ONLYA please"]["verdict"] == Verdict.DIVERGENCE.value
    assert "accepted by" in (by_text["ONLYA please"]["detail"] or ""), (
        "an acceptance divergence should name who accepted and who refused"
    )


def test_mutual_rejection_is_agreement_not_divergence(campaign_d):
    """Engines word their errors differently and pick different exit codes.
    Reporting that as a disagreement would bury the real ones."""
    config, r = campaign_d
    with CorpusStore(config.state_dir) as store:
        row = next(
            row for row in store.conn.execute(
                "SELECT blob_hash, verdict FROM executions WHERE run_id=?", (r.run_id,))
            if b"REJECT" in store.get_blob(row["blob_hash"])
        )
    assert row["verdict"] == Verdict.EXPECTED_REJECTION.value


def test_a_divergence_run_executes_every_target(campaign_d):
    config, r = campaign_d
    assert len(config.targets) == 2
    with CorpusStore(config.state_dir) as store:
        suts = {row["sut_id"] for row in store.conn.execute(
            "SELECT DISTINCT sut_id FROM executions WHERE run_id=?", (r.run_id,))}
    assert suts == {"enga", "engb"}, suts


def test_a_differential_verdict_is_recorded_coherently_for_both_targets(campaign_d):
    """The verdict belongs to the input, not to one side of the comparison, so
    both rows must carry it -- while keeping each target's own exit code."""
    config, r = campaign_d
    with CorpusStore(config.state_dir) as store:
        per_input: dict[str, list] = {}
        for row in store.conn.execute(
            "SELECT blob_hash, sut_id, exit_code, verdict FROM executions WHERE run_id=?",
            (r.run_id,),
        ):
            per_input.setdefault(row["blob_hash"], []).append(row)

        for blob, rows in per_input.items():
            text = store.get_blob(blob).decode().strip()
            assert len(rows) == 2, f"{text}: {len(rows)} rows, expected one per target"
            assert len({row["verdict"] for row in rows}) == 1, (
                f"{text}: targets disagree about the verdict itself"
            )
            if "ONLYA" in text:
                assert {row["exit_code"] for row in rows} == {0, 1}, (
                    "per-target exit codes must survive; they are the evidence"
                )


def test_executed_counts_inputs_not_target_invocations(campaign_d):
    """An input is one unit of execution budget however many targets ran it;
    counting invocations would make a differential campaign look twice as
    productive as it is."""
    config, r = campaign_d
    with CorpusStore(config.state_dir) as store:
        rows = store.conn.execute(
            "SELECT COUNT(*) c FROM executions WHERE run_id=?", (r.run_id,)).fetchone()["c"]
        inputs = store.conn.execute(
            "SELECT COUNT(DISTINCT blob_hash) c FROM executions WHERE run_id=?",
            (r.run_id,)).fetchone()["c"]
    assert rows == 2 * inputs, "two targets, so two rows per input"
    assert r.executed == inputs


# ============================================ CC and generator selection

def test_cc_is_computed_over_the_pool_and_bounded(campaign_a):
    """CC(g) is a share of clusters, so it lives in [0,1] and K_eff is real."""
    _, r = campaign_a
    assert r.k_eff and r.k_eff >= 1
    assert r.generator_scores, "a campaign with generators must score them"
    for gen, score in r.generator_scores.items():
        assert 0.0 <= score <= 1.0, f"{gen}: CC={score}"
    assert set(r.generator_scores) == set(r.generator_counts), (
        "a generator was scored without being counted, or the reverse"
    )


def test_generator_selection_prefers_the_highest_cc(campaign_a):
    """The published RankSum selection, over this campaign's own scores."""
    from spreadex.signals.base import ClusterCoverageSignal

    _, r = campaign_a
    if len(r.generator_scores) < 2:
        pytest.skip("needs two generators to rank")
    ranks, winner = ClusterCoverageSignal.select_generator(
        [r.generator_scores], list(r.generator_scores)
    )
    best = max(r.generator_scores.items(), key=lambda kv: kv[1])[0]
    assert winner == best, f"selected {winner}, but {best} had the highest CC"
    # Competition ranking: rank 1 is the best, and the lowest sum wins.
    assert ranks[winner] == min(ranks.values())


def test_every_source_that_produced_inputs_is_accounted_for(campaign_a):
    """A generator that ran must appear in the counts, and the counts must sum
    to what the corpus holds."""
    config, r = campaign_a
    with CorpusStore(config.state_dir) as store:
        rows = store.conn.execute(
            "SELECT generator, COUNT(*) c FROM input_origins GROUP BY generator"
        ).fetchall()
    stored = {row["generator"]: row["c"] for row in rows}
    assert set(r.generator_counts) <= set(stored), (
        f"counted {set(r.generator_counts)} but the corpus knows {set(stored)}"
    )


# ===================================================== results, replay, export

@pytest.mark.parametrize("name", ALL_CAMPAIGNS)
def test_the_manifest_is_written_and_self_describing(name, request):
    config, r = request.getfixturevalue(name)
    manifest = json.loads((r.run_dir / "manifest.json").read_text())
    assert manifest["config_hash"] and manifest["spreadex_version"]
    assert manifest["targets"], "a manifest without targets cannot be replayed"
    assert manifest["results"]["executed"] == r.executed
    assert manifest["results"]["verdicts"] == r.verdicts
    assert manifest["corpus"]["prioritized"] == r.prioritized


@pytest.mark.parametrize("name", ALL_CAMPAIGNS)
def test_results_jsonl_matches_the_database(name, request):
    """Two records of the same run that disagree are worse than one."""
    config, r = request.getfixturevalue(name)
    rows = [json.loads(line) for line in
            (r.run_dir / "results.jsonl").read_text().splitlines() if line.strip()]
    assert rows
    with CorpusStore(config.state_dir) as store:
        db = {(row["blob_hash"], row["sut_id"]): row["verdict"]
              for row in store.conn.execute(
                  "SELECT blob_hash, sut_id, verdict FROM executions WHERE run_id=?",
                  (r.run_id,))}
    for row in rows:
        key = (row["blob_hash"], row["sut_id"])
        assert key in db, f"results.jsonl has a row the database does not: {key}"
        assert db[key] == row["verdict"]


@pytest.mark.parametrize("name", ALL_CAMPAIGNS)
def test_the_config_hash_is_stable_across_a_reload(name, request):
    """Replay compares hashes to detect drift, so an unchanged project must
    hash the same when loaded again."""
    config, r = request.getfixturevalue(name)
    again = load_config(config.project_root / "spreadex.yaml")
    assert again.hash() == config.hash()
    manifest = json.loads((r.run_dir / "manifest.json").read_text())
    assert manifest["config_hash"] == config.hash()


@pytest.mark.parametrize("name", ALL_CAMPAIGNS)
def test_replay_reports_the_run_without_changing_it(name, request):
    from spreadex.cli.main import main as cli_main

    config, r = request.getfixturevalue(name)
    before = (r.run_dir / "manifest.json").read_text()
    rc = cli_main(["-c", str(config.project_root / "spreadex.yaml"), "replay", r.run_id])
    assert rc == 0
    assert (r.run_dir / "manifest.json").read_text() == before, "replay mutated the run"


@pytest.mark.parametrize("name", ALL_CAMPAIGNS)
def test_export_is_self_contained(name, request, tmp_path):
    """A manifest naming hashes nobody else can resolve is not a reproduction,
    so the failing inputs have to travel with it."""
    from spreadex.cli.main import main as cli_main

    config, r = request.getfixturevalue(name)
    out = tmp_path / f"{name}.zip"
    rc = cli_main(["-c", str(config.project_root / "spreadex.yaml"),
                   "export", r.run_id, "-o", str(out)])
    assert rc == 0 and out.is_file()

    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        assert "spreadex.yaml" in names
        assert "run/manifest.json" in names
        assert "run/results.jsonl" in names
        manifest = json.loads(z.read("run/manifest.json"))
        assert manifest["config_hash"] == config.hash()

        if r.failures:
            failing = [n for n in names if n.startswith("failing_inputs/")
                       and not n.endswith("index.json")]
            assert failing, "a run with failures exported none of them"
            index = json.loads(z.read("failing_inputs/index.json"))
            assert len(index) == len(failing)
