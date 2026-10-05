"""Semantic guidance: extraction, the `semantics:` block, provenance, native consumption."""
import base64
import io
import json
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

from spreadex.api import setup
from spreadex.core.config import ConfigError, load_config
from spreadex.spec import SpecError, docs_support, extract_text, safe_spec_name

ROOT = Path(__file__).resolve().parents[1]
CALC = ROOT / "src/spreadex/demo/project/calc.bnf"


def _project(tmp_path, extra=""):
    (tmp_path / "spreadex.yaml").write_text(
        f"sut:\n  command: [{json.dumps(sys.executable)}, -c, 'pass']\n"
        f"oracle:\n  type: crash\n{extra}")
    return load_config(tmp_path / "spreadex.yaml")


def _spec(tmp_path, name, text="A break must be inside a loop.\n"):
    (tmp_path / "spec").mkdir(exist_ok=True)
    (tmp_path / "spec" / name).write_text(text)
    return f"spec/{name}"


# ------------------------------------------------------------ extraction

def test_text_and_markdown_are_read_as_written():
    assert extract_text("a.md", b"# Rules\nx must be declared.").text.startswith("# Rules")
    assert extract_text("a.txt", "café".encode()).text == "café"


def test_binary_oversized_and_unsupported_files_are_refused_with_a_reason():
    with pytest.raises(SpecError, match="binary"):
        extract_text("a.txt", b"abc\x00def")
    with pytest.raises(SpecError, match="MB"):
        extract_text("a.txt", b"x" * 5_000_001)
    with pytest.raises(SpecError, match="not supported"):
        extract_text("a.rtf", b"x")


def test_invalid_utf8_is_replaced_and_flagged():
    r = extract_text("a.txt", b"ok \xff\xfe ok")
    assert "�" in r.text and any("UTF-8" in w for w in r.warnings)


def _docx(paragraphs, table=None):
    docx = pytest.importorskip("docx")
    d = docx.Document()
    for p in paragraphs:
        d.add_paragraph(p)
    if table:
        t = d.add_table(rows=len(table), cols=len(table[0]))
        for i, row in enumerate(table):
            for j, cell in enumerate(row):
                t.cell(i, j).text = cell
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_docx_paragraphs_and_tables_are_extracted():
    r = extract_text("rules.docx", _docx(["A return must be inside a function."], [["rule", "scope"], ["break", "loop"]]))
    assert "A return must be inside a function." in r.text and "break | loop" in r.text


def test_an_empty_docx_warns_instead_of_pretending():
    r = extract_text("e.docx", _docx([]))
    assert r.text == "" and any("No text" in w for w in r.warnings)


def test_a_docx_zip_bomb_is_refused_before_it_is_read():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", b"\0" * 60_000_000)
    with pytest.raises(SpecError, match="unreasonable size"):
        extract_text("bomb.docx", buf.getvalue())


def test_a_non_zip_docx_is_a_clean_error():
    with pytest.raises(SpecError, match="not a valid .docx"):
        extract_text("x.docx", b"not a zip")


def _pdf(text=None, password=None):
    pypdf = pytest.importorskip("pypdf")
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    if text:
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page = w.pages[0]
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = w._add_object(stream)
    if password:
        w.encrypt(password)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def test_pdf_text_is_extracted_with_the_lossiness_warning():
    r = extract_text("rules.pdf", _pdf("Declare every variable before use."))
    assert "Declare every variable before use." in r.text
    assert r.pages == 1 and any("lose columns" in w for w in r.warnings)


def test_a_scanned_or_blank_pdf_says_no_text_was_found():
    r = extract_text("scan.pdf", _pdf())
    assert any("No text was found" in w for w in r.warnings)


def test_an_encrypted_pdf_is_refused_with_advice():
    with pytest.raises(SpecError, match="password"):
        extract_text("p.pdf", _pdf("secret text", password="pw"))


def test_a_damaged_pdf_is_a_clean_error_not_a_traceback():
    with pytest.raises(SpecError, match="Could not read that PDF"):
        extract_text("bad.pdf", b"%PDF-1.4 this is not a pdf")


def test_a_missing_optional_package_gives_the_install_hint(monkeypatch):
    monkeypatch.setitem(sys.modules, "pypdf", None)
    with pytest.raises(SpecError, match=r"spreadex\[docs\]"):
        extract_text("a.pdf", b"%PDF-1.4")


def test_long_text_is_cut_and_says_so():
    r = extract_text("a.txt", b"a" * 250_000)
    assert len(r.text) == 200_000 and any("cut" in w for w in r.warnings)


def test_docs_support_reports_what_is_importable():
    assert set(docs_support()) == {"pdf", "docx"}


# --------------------------------------------------------------- config

def test_a_valid_semantics_block_loads(tmp_path):
    g = _spec(tmp_path, "s.md")
    n = _spec(tmp_path, "c.fan", "where True")
    cfg = _project(tmp_path, f"semantics:\n  guidance: [{g}]\n  native:\n    fandango: {n}\n")
    assert cfg.semantics.guidance == [g] and cfg.semantics.native == {"fandango": n}


def test_absent_semantics_is_simply_empty(tmp_path):
    assert not _project(tmp_path).semantics


@pytest.mark.parametrize("block,needle", [
    ("semantics: [x]\n", "mapping"),
    ("semantics:\n  nope: 1\n", "unknown key"),
    ("semantics:\n  guidance: [spec/missing.md]\n", "not found"),
    ("semantics:\n  guidance: [../outside.md]\n", "outside the project"),
    ("semantics:\n  native:\n    grammarinator: spec/x.txt\n", "only fandango, isla"),
])
def test_bad_semantics_are_refused_with_a_fix(tmp_path, block, needle):
    (tmp_path.parent / "outside.md").write_text("x")
    with pytest.raises(ConfigError, match=needle):
        _project(tmp_path, block)


def test_guidance_must_be_text_and_structured_must_be_yaml_or_json(tmp_path):
    bad = _spec(tmp_path, "s.pdf", "x")
    with pytest.raises(ConfigError, match=r"\.txt or \.md"):
        _project(tmp_path, f"semantics:\n  guidance: [{bad}]\n")
    s = _spec(tmp_path, "s.txt", "x")
    with pytest.raises(ConfigError, match="yaml"):
        _project(tmp_path, f"semantics:\n  structured: {s}\n")


def test_editing_the_guidance_changes_the_config_hash_but_touching_it_does_not(tmp_path):
    import os
    g = _spec(tmp_path, "s.md", "version one")
    base = _project(tmp_path, f"semantics:\n  guidance: [{g}]\n").hash()
    os.utime(tmp_path / g, (1, 1))                              # new mtime, same bytes
    assert _project(tmp_path, f"semantics:\n  guidance: [{g}]\n").hash() == base
    (tmp_path / g).write_text("version two")
    assert _project(tmp_path, f"semantics:\n  guidance: [{g}]\n").hash() != base


def test_a_project_without_semantics_keeps_its_old_hash(tmp_path):
    a = _project(tmp_path).hash()
    b = _project(tmp_path, "semantics: {}\n").hash()
    assert a == b


def test_a_run_records_the_content_hash_of_its_guidance(tmp_path):
    from spreadex.core.campaign import Campaign
    from spreadex.core.manifest import Manifest

    g = _spec(tmp_path, "s.md", "rule")
    (tmp_path / "seeds").mkdir()
    (tmp_path / "seeds" / "a").write_text("one")
    cfg = _project(tmp_path, f"generators: []\ncorpus:\n  path: seeds\nsemantics:\n  guidance: [{g}]\n"
                             "budget: {generation: 5s, execution: 10s}\n")
    r = Campaign(cfg, log=lambda *_: None).run()
    m = Manifest.read(r.run_dir / "manifest.json")
    assert list(m.semantics["guidance"]) == [g] and len(m.semantics["guidance"][g]) == 16


def test_an_old_manifest_without_the_field_still_reads_and_hashes_the_same():
    from spreadex.core.manifest import Manifest
    m = Manifest(run_id="r", spreadex_version="x")
    h = m.hash()
    m.semantics = {}
    assert m.hash() == h


# ------------------------------------------------------ native consumption

def _derive(tmp_path, native_lines, gens):
    from spreadex.core.sources import derive_grammars
    shutil.copy(CALC, tmp_path / "calc.bnf")
    cfg = _project(tmp_path, f"grammar:\n  source: calc.bnf\n{native_lines}")
    return cfg, derive_grammars(cfg, gens, log=lambda *_: None)


def test_a_fandango_native_file_is_appended_as_written(tmp_path):
    n = _spec(tmp_path, "c.fan", "where int(<digits>) != 0")
    cfg, out = _derive(tmp_path, f"semantics:\n  native:\n    fandango: {n}\n", ["fandango"])
    text = out["fandango"].read_text()
    assert "where int(<digits>) != 0" in text and "used as written" in text


def test_an_isla_native_file_sits_beside_the_derived_grammar(tmp_path):
    n = _spec(tmp_path, "c.isla", "forall <digits> d: str.len(d) > 0")
    cfg, out = _derive(tmp_path, f"semantics:\n  native:\n    isla: {n}\n", ["isla"])
    assert "forall <digits> d: str.len(d) > 0" in out["isla"].with_suffix(".isla").read_text()
    from spreadex.generators.adapters import _sibling_constraint
    assert _sibling_constraint(out["isla"]) is not None


def test_changing_a_native_file_never_reuses_the_cached_dialect(tmp_path):
    n = _spec(tmp_path, "c.fan", "where True")
    cfg1, out1 = _derive(tmp_path, f"semantics:\n  native:\n    fandango: {n}\n", ["fandango"])
    (tmp_path / n).write_text("where False")
    cfg2, out2 = _derive(tmp_path, f"semantics:\n  native:\n    fandango: {n}\n", ["fandango"])
    assert out1["fandango"] != out2["fandango"] and "where False" in out2["fandango"].read_text()


def test_guidance_alone_changes_no_generator_input(tmp_path):
    g = _spec(tmp_path, "s.md", "natural language only")
    cfg, out = _derive(tmp_path, f"semantics:\n  guidance: [{g}]\n", ["fandango"])
    assert "natural language" not in out["fandango"].read_text()


# --------------------------------------------------------------- the API

def test_save_guidance_lands_under_spec_and_sanitises_the_name(tmp_path):
    cfg = _project(tmp_path)
    r = setup.save_spec(cfg, {"kind": "guidance", "name": "../../evil name.md", "text": "rule"})
    assert r["ok"] and r["written"].startswith("spec/") and ".." not in r["written"]
    assert (tmp_path / r["written"]).read_text() == "rule"
    assert not (tmp_path.parent / "evil name.md").exists()


def test_save_refuses_empty_oversized_and_unknown_kinds(tmp_path):
    cfg = _project(tmp_path)
    assert not setup.save_spec(cfg, {"kind": "guidance", "text": "  "})["ok"]
    assert not setup.save_spec(cfg, {"kind": "guidance", "text": "x" * 1_000_001})["ok"]
    assert not setup.save_spec(cfg, {"kind": "native:grammarinator", "text": "x"})["ok"]
    assert not setup.save_spec(cfg, {"kind": "structured", "text": "a: [unclosed"})["ok"]


def test_save_stores_the_original_document_beside_the_text(tmp_path):
    cfg = _project(tmp_path)
    blob = base64.b64encode(b"%PDF-original").decode()
    r = setup.save_spec(cfg, {"kind": "guidance", "name": "rules.md", "text": "rule",
                              "original": {"name": "rules.pdf", "data": blob}})
    assert r["ok"] and (tmp_path / "spec" / "rules.pdf").read_bytes() == b"%PDF-original"


def test_extract_document_reads_but_never_writes(tmp_path):
    cfg = _project(tmp_path)
    r = setup.extract_document(cfg, {"name": "a.md", "data": base64.b64encode(b"hello rule").decode()})
    assert r["ok"] and r["text"] == "hello rule" and not (tmp_path / "spec").exists()
    assert not setup.extract_document(cfg, {"name": "a.md", "data": "!!!not base64"})["ok"]


def test_read_spec_reports_installed_formats_and_the_saved_text(tmp_path):
    g = _spec(tmp_path, "s.md", "saved rule")
    cfg = _project(tmp_path, f"semantics:\n  guidance: [{g}]\n")
    r = setup.read_spec(cfg)
    assert r["texts"][g] == "saved rule" and set(r["docs"]) == {"pdf", "docx"}


def test_safe_spec_name():
    assert safe_spec_name("../../x y.md", "d.md") == "x_y.md"
    assert safe_spec_name("...", "d.md") == "d.md"
    assert safe_spec_name("", "d.md") == "d.md"
