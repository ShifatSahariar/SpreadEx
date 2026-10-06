"""A crash's signature must not depend on where the project lives.

Only the head of stderr used to be kept, and a Python traceback ends with the frames and the
exception that identify the failure, so a longer project path pushed them past the cut and the
same crash was bucketed differently in a different folder.
"""
from spreadex.exec.observation import preview
from spreadex.exec.signature import failure_signature, top_frames


def _traceback(root: str, depth: int) -> str:
    frames = "".join(f'  File "{root}/calc.py", line {10 + i}, in {"expr" if i % 2 else "term"}\n    x = y\n'
                     for i in range(depth))
    return ("Traceback (most recent call last):\n" + frames +
            f'  File "{root}/calc.py", line 103, in remainder\n    value % right\n'
            "ZeroDivisionError: float modulo\n")


def test_the_same_crash_gets_the_same_signature_in_a_short_and_a_long_folder():
    short = _traceback("/p", 40)
    long = _traceback("/private/tmp/" + "very-long-folder-name/" * 8 + "project", 40)
    assert len(long) > 4000, "deep enough to be cut"
    assert failure_signature(preview(short)) == failure_signature(preview(long))


def test_python_signatures_use_the_innermost_frames():
    frames = top_frames(_traceback("/p", 12), 3)
    assert frames[-1] == "calc.py:remainder"


def test_the_preview_keeps_the_exception_line_at_the_end():
    p = preview(_traceback("/x/" * 50, 60))
    assert p.rstrip().endswith("ZeroDivisionError: float modulo") and "chars omitted" in p


def test_signatures_use_the_real_stderr_tail_not_the_display_preview(tmp_path):
    """The preview is for people; a signature computed from it depended on path length."""
    import sys
    from spreadex.exec.runner import Target, run_one
    script = tmp_path / ("deep/" * 20) / "boom.py"
    script.parent.mkdir(parents=True)
    # Mutual recursion: Python prints every frame (it only compresses identical repeats).
    script.write_text("def f(n):\n    return 1 % 0 if n == 0 else g(n - 1)\n"
                      "def g(n):\n    return f(n - 1)\nf(60)\n")
    inp = tmp_path / "in.txt"
    inp.write_text("x")
    obs = run_one(Target(name="t", command=[sys.executable, str(script), "{input}"]), inp, input_hash="h")
    assert len(obs.stderr_preview) < len(obs.stderr_tail)
    assert obs.stderr_tail.rstrip().endswith("ZeroDivisionError: integer modulo by zero")
