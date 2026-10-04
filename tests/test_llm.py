"""Optional language-model assistance.

The rule the design audit set: a model PROPOSES, SpreadEx VERIFIES. These tests
stub the model entirely, because what matters is not what it says but that
nothing it says reaches a campaign without passing the ordinary validator.
"""

from unittest.mock import patch

import pytest

from spreadex.llm import LLMError, assist as assist_mod
from spreadex.llm.client import PROVIDERS, available, extract_code_block

GOOD = '```\n<start> ::= <s>\n<s> ::= "print " <v>\n<v> ::= "x" | "y"\n```'
UNDEFINED = '```\n<start> ::= <nope>\n```'
NONPRODUCTIVE = '```\n<start> ::= <a>\n<a> ::= <a> "x"\n```'


def stub(*replies):
    it = iter(replies)
    return lambda **kw: next(it)


# ------------------------------------------------------------- the gate

def test_a_valid_proposal_is_accepted():
    with patch.object(assist_mod, "complete", stub(GOOD)):
        p = assist_mod.infer_grammar(["print x"])
    assert p.ok and p.rules == 3 and p.start == "start"
    assert len(p.attempts) == 1


@pytest.mark.parametrize("bad", [UNDEFINED, NONPRODUCTIVE])
def test_an_invalid_proposal_is_rejected_then_retried(bad):
    """The validator's own words are handed back, and a later good answer wins."""
    with patch.object(assist_mod, "complete", stub(bad, GOOD)):
        p = assist_mod.infer_grammar(["x"])
    assert p.ok
    assert len(p.attempts) == 2
    assert p.attempts[0].ok is False and p.attempts[0].errors


def test_a_never_valid_proposal_is_reported_as_such():
    """The worst case must be 'no usable grammar', never a plausible wrong one."""
    with patch.object(assist_mod, "complete", stub(*[UNDEFINED] * 5)):
        p = assist_mod.infer_grammar(["x"])
    assert p.ok is False
    assert p.errors
    assert len(p.attempts) == assist_mod.MAX_ATTEMPTS


def test_the_retry_loop_is_bounded():
    calls = {"n": 0}

    def counting(**kw):
        calls["n"] += 1
        return UNDEFINED

    with patch.object(assist_mod, "complete", counting):
        assist_mod.infer_grammar(["x"])
    assert calls["n"] == assist_mod.MAX_ATTEMPTS


def test_proposals_report_per_generator_support():
    with patch.object(assist_mod, "complete", stub(GOOD)):
        p = assist_mod.infer_grammar(["x"], generators=["fuzzingbook", "isla"])
    assert {s["generator"] for s in p.support} == {"fuzzingbook", "isla"}
    assert all(s["usable"] for s in p.support)


def test_repair_short_circuits_on_an_already_valid_grammar():
    """No model call at all when there is nothing to fix."""
    def explode(**kw):
        raise AssertionError("the model should not have been called")

    with patch.object(assist_mod, "complete", explode):
        p = assist_mod.repair_grammar('<start> ::= "x"')
    assert p.ok and p.rules == 1


def test_inference_needs_something_to_work_from():
    with pytest.raises(LLMError, match="example inputs"):
        assist_mod.infer_grammar([], "")


# ----------------------------------------------------------- constraints

CONSTRAINT_GRAMMAR = '<start> ::= <stmt>\n<stmt> ::= "let " <var>\n<var> ::= "a" | "b"'


def test_constraints_referencing_unknown_symbols_are_rejected():
    with patch.object(assist_mod, "complete", stub("```\nwhere all(x for x in *<<ghost>>)\n```")):
        p = assist_mod.constraints_for("fandango", "something", CONSTRAINT_GRAMMAR)
    assert p.ok is False
    assert any("ghost" in e for e in p.errors)


def test_constraints_using_real_symbols_pass_the_symbol_check():
    with patch.object(assist_mod, "complete", stub("```\nwhere all(len(v) < 2 for v in *<<var>>)\n```")):
        p = assist_mod.constraints_for("fandango", "short names", CONSTRAINT_GRAMMAR)
    assert p.ok
    # Honest about what was NOT checked.
    assert any("not verified" in w for w in p.warnings)


@pytest.mark.parametrize("generator", ["fuzzingbook", "grammarinator"])
def test_generators_without_constraint_support_are_refused(generator):
    with pytest.raises(LLMError, match="does not take constraints"):
        assist_mod.constraints_for(generator, "x", CONSTRAINT_GRAMMAR)


# --------------------------------------------------------------- client

def test_providers_are_offered_with_their_key_requirements():
    by_id = {p["id"]: p for p in available()}
    assert by_id["ollama"]["local"] is True and by_id["ollama"]["needs_key"] is False
    assert by_id["openai"]["env_var"] == "OPENAI_API_KEY"


def test_a_missing_key_is_a_clear_error_not_a_crash(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from spreadex.llm.client import complete

    with pytest.raises(LLMError, match="needs an API key"):
        complete("openai", "s", "u")


def test_unknown_provider_lists_the_known_ones():
    from spreadex.llm.client import complete

    with pytest.raises(LLMError, match="Known:"):
        complete("telepathy", "s", "u")


@pytest.mark.parametrize("text,expected", [
    ("```\nhello\n```", "hello"),
    ("```bnf\nhello\n```", "hello"),
    ("no fence here", "no fence here"),
])
def test_code_block_extraction(text, expected):
    assert extract_code_block(text) == expected


def test_no_vendor_sdk_is_imported():
    """The client is urllib-only, so assistance costs no install."""
    import sys

    import spreadex.llm.client  # noqa: F401

    assert "openai" not in sys.modules and "anthropic" not in sys.modules
