from spreadex.corpus import CorpusStore
from spreadex.exec.oracle import Judgement, Verdict
from tests.test_oracle import obs


def test_content_addressing_deduplicates(tmp_path):
    with CorpusStore(tmp_path / ".spreadex") as s:
        a = s.add_input(b"let x = 1", "fandango", valid=True)
        b = s.add_input(b"let x = 1", "grammarinator", valid=True)
        assert a == b, "identical bytes must share one blob"
        assert s.count_inputs() == 1
        assert s.generators_of(a) == ["fandango", "grammarinator"]
        blobs = [p for p in (tmp_path / ".spreadex" / "blobs").rglob("*") if p.is_file()]
        assert len(blobs) == 1


def test_blob_roundtrip(tmp_path):
    with CorpusStore(tmp_path / ".spreadex") as s:
        h = s.add_input(b"payload", "g")
        assert s.get_blob(h) == b"payload"
        assert s.blob_path(h).exists()


def test_failures_accumulate_across_runs(tmp_path):
    with CorpusStore(tmp_path / ".spreadex") as s:
        h = s.add_input(b"boom", "g", valid=True)
        j = Judgement(Verdict.CRASH, signature="sig-1", detail="exit 1")

        s.start_run("r1", "cfg")
        s.record_execution("r1", h, 0, [obs(rc=1)], j)
        s.commit()
        assert s.new_signatures("r1") == ["sig-1"]

        s.start_run("r2", "cfg")
        s.record_execution("r2", h, 0, [obs(rc=1)], j)
        s.commit()
        # Seen before, so it is not new -- this is the CI regression signal.
        assert s.new_signatures("r2") == []


def test_run_summary_counts_distinct_inputs_not_rows(tmp_path):
    with CorpusStore(tmp_path / ".spreadex") as s:
        s.start_run("r1", "cfg")
        h = s.add_input(b"x", "g", valid=True)
        j = Judgement(Verdict.DIVERGENCE, signature="d1")
        # one input, two targets -> one divergence, not two
        s.record_execution("r1", h, 0, [obs("a", rc=0), obs("b", rc=0)], j)
        s.commit()
        assert s.run_summary("r1") == {"divergence": 1}
        assert s.signatures_in_run("r1")[0]["n"] == 1
