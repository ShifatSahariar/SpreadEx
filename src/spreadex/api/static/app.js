// SpreadEx UI: a setup wizard over the campaign engine, plus result views.
//
// The wizard's job is to produce a spreadex.yaml the user has reviewed, and
// then launch exactly that. It never synthesises a command behind their back.

// The token is handed over once in the URL, then kept for this tab only, so it
// stops sitting in the address bar, in history, and in anything we later link.
const incoming = new URL(location.href);
if (incoming.searchParams.get("token")) {
  sessionStorage.setItem("spreadex-token", incoming.searchParams.get("token"));
  incoming.searchParams.delete("token");
  history.replaceState({}, "", incoming.pathname);
}
const TOKEN = sessionStorage.getItem("spreadex-token") || "";

async function api(path, body) {
  const opts = { headers: { "X-SpreadEx-Token": TOKEN } };
  if (body !== undefined) {
    opts.method = "POST";
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(path, opts);
  const payload = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(payload.error || r.statusText);
  return payload;
}
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const num = n => (n ?? 0).toLocaleString();
const el = id => document.getElementById(id);

function toggleTheme() {
  const root = document.documentElement;
  const explicit = root.getAttribute("data-theme");
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  // With no explicit choice yet, the first click flips away from the system.
  const next = explicit ? (explicit === "dark" ? "light" : "dark") : (systemDark ? "light" : "dark");
  root.setAttribute("data-theme", next);
  try { localStorage.setItem("spreadex-theme", next); } catch (e) { /* blocked storage */ }
}

const STEPS = [
  { id: "sut",        n: 1, t: "System under test", d: "The command to run." },
  { id: "grammar",    n: 2, t: "Inputs",            d: "Where they come from." },
  { id: "generators", n: 3, t: "Generators",        d: "Who writes the inputs." },
  { id: "strategy",   n: 4, t: "Testing strategy",  d: "What counts as a failure." },
  { id: "run",        n: 5, t: "Budget & run",      d: "Review, then launch." },
];

const S = {
  tab: "setup", step: "sut", project: null, config: {}, rejects: undefined,
  kind: null, sample: undefined, probe: null,
  generators: [], grammars: [], runs: [], current: null, polling: null,
};

// ------------------------------------------------------------- navigation

function go(tab) {
  S.tab = tab;
  el("tab-setup").setAttribute("aria-selected", tab === "setup");
  el("tab-results").setAttribute("aria-selected", tab === "results");
  el("steps").style.display = tab === "setup" ? "" : "none";
  tab === "setup" ? renderStep() : renderResults();
}
function gotoStep(id) { S.step = id; renderSteps(); renderStep(); }

function renderSteps() {
  el("steps").innerHTML = STEPS.map(s => `
    <button class="step" aria-current="${s.id === S.step}" onclick="gotoStep('${s.id}')">
      <span class="n">${s.n}</span>
      <span><span class="t">${s.t}</span><br><span class="d">${s.d}</span></span>
    </button>`).join("");
}

// ------------------------------------------------------ config helpers

function cfg() { return S.config || {}; }
function sut() { return cfg().sut || {}; }
function targets() {
  const s = sut();
  if (s.targets) return s.targets;
  if (s.command) return [{ name: s.name || "sut", command: s.command }];
  return [];
}

function buildYaml() {
  // Emitted by hand rather than with a YAML library so the file stays in the
  // shape a person would have written, comments and all.
  const c = cfg(), t = targets();
  const q = v => JSON.stringify(v);
  const lines = ["# Written by the SpreadEx setup wizard. Safe to edit by hand.", "sut:"];
  if (t.length > 1) {
    lines.push("  targets:");
    t.forEach(x => lines.push(`    - {name: ${x.name}, command: [${x.command.map(q).join(", ")}]}`));
  } else if (t.length === 1) {
    lines.push(`  command: [${t[0].command.map(q).join(", ")}]`);
  }
  lines.push(`  timeout: ${c.sut?.timeout || "5s"}`, "", "oracle:");
  lines.push(`  type: ${t.length > 1 ? "differential" : (c.oracle?.type || "crash")}`);
  if (c.oracle?.expected_exit_codes?.length) {
    lines.push(`  expected_exit_codes: [${c.oracle.expected_exit_codes.join(", ")}]`);
  }
  for (const key of ["rejection_patterns", "crash_patterns", "banners"]) {
    const v = c.oracle?.[key];
    if (v && v.length) {
      lines.push(`  ${key}:`);
      v.forEach(p => lines.push(`    - ${q(p)}`));
    }
  }
  lines.push("", `generators: [${(c.generators || []).join(", ")}]`);
  if (c.grammar?.source) lines.push("", "grammar:", `  source: ${c.grammar.source}`);
  if (c.corpus?.path) lines.push("", "corpus:", `  path: ${c.corpus.path}`);
  if (c.generation?.count) lines.push("", "generation:", `  count: ${c.generation.count}`);
  lines.push("", "budget:",
    `  generation: ${c.budget?.generation || "1m"}`,
    `  execution: ${c.budget?.execution || "1m"}`);
  lines.push("", `selection_signal: ${c.selection_signal || "cc"}`,
    "embedding:", `  model: ${c.embedding?.model || "tfidf"}`,
    "", `seed: ${c.seed ?? 42}`, "");
  return lines.join("\n");
}

async function saveConfig(write) {
  const res = await api("/api/config", { yaml: buildYaml(), write: !!write });
  return res;
}

// ------------------------------------------------- step 4: testing strategy

// Checks, not a single "oracle" dropdown. The engine already distinguishes
// ok / expected_rejection / crash / timeout / divergence; this step only
// decides which of those the user wants reported, in their words.

function patternRows(key, placeholder) {
  const list = cfg().oracle?.[key] || [];
  const rows = list.length ? list : [""];
  return rows.map((v, i) => `
    <div class="pat-row">
      <input type="text" class="pat-${key}" value="${esc(v)}" placeholder="${esc(placeholder)}">
      <button class="ghost small" onclick="dropPattern('${key}', ${i})"
        title="Remove this message" aria-label="Remove">&times;</button>
    </div>`).join("");
}

function readPatterns(key) {
  return Array.from(document.querySelectorAll(`.pat-${key}`))
    .map(i => i.value.trim()).filter(Boolean);
}

function stashStrategy() {
  // Keep what is on screen before re-rendering, so adding a row never eats what
  // the user already typed -- and keep the answer to "does this system reject
  // input?" separately, because it stays true while the list is still empty.
  const o = { ...(cfg().oracle || {}) };
  if (el("chk-reject")) {
    S.rejects = el("chk-reject").checked;
    o.rejection_patterns = S.rejects ? readPatterns("rejection_patterns") : [];
    o.crash_patterns = readPatterns("crash_patterns");
    o.type = (el("chk-diff") && el("chk-diff").checked) ? "differential" : "crash";
    const codes = (el("exit-codes").value || "").split(/[,\s]+/)
      .map(x => parseInt(x, 10)).filter(n => !Number.isNaN(n));
    if (codes.length) o.expected_exit_codes = codes; else delete o.expected_exit_codes;
  }
  S.config.oracle = o;
}

function addPattern(key) { stashStrategy();
  S.config.oracle[key] = [...(cfg().oracle[key] || []), ""]; stepStrategy(); }
function dropPattern(key, i) { stashStrategy();
  const v = [...(cfg().oracle[key] || [])]; v.splice(i, 1);
  S.config.oracle[key] = v; stepStrategy(); }
function redrawStrategy() { stashStrategy(); stepStrategy(); }

function stepStrategy() {
  const o = cfg().oracle || {}, multi = targets().length > 1;
  if (S.rejects === undefined) S.rejects = (o.rejection_patterns || []).length > 0;
  const rejects = S.rejects;
  el("view").innerHTML = `
  <div class="card">
    <h3>What counts as a failure?</h3>
    <p class="why">SpreadEx distinguishes a measurement from a judgement. Every input is
      <em>run</em>; these checks decide which results are worth your attention. Most generated
      input is invalid on purpose, and a parser rejecting it is doing its job &mdash; not a bug.</p>

    <label class="check"><input type="checkbox" checked disabled>
      <span><strong>Crashes and hangs</strong><br>
      <span class="muted">A signal, a crash-shaped exit, or no answer before the timeout.
      Always on &mdash; this is the floor.</span></span></label>

    <label class="check"><input type="checkbox" id="chk-diff" ${o.type === "differential" ? "checked" : ""}
      ${multi ? "" : "disabled"} onchange="redrawStrategy()">
      <span><strong>Disagreement between implementations</strong><br>
      <span class="muted">${multi
        ? "Both run the same input; a different exit code, exception or output is a divergence. No expected output needed."
        : "Add a second implementation on step 1 to enable this."}</span></span></label>

    <label class="check"><input type="checkbox" id="chk-reject" ${rejects ? "checked" : ""}
      onchange="redrawStrategy()">
      <span><strong>This system reports invalid input itself</strong><br>
      <span class="muted">If it exits non-zero for input it legitimately refuses, say how it
      says so &mdash; otherwise every invalid input is reported as a crash.</span></span></label>

    ${rejects ? `
    <div class="indent">
      <label>Messages that mean &ldquo;I rejected this&rdquo;</label>
      <p class="muted" style="font-size:12.5px;margin:2px 0 6px">One per line, matched against
        the output as a regular expression. Copy a real error message from your system.</p>
      ${patternRows("rejection_patterns", "SyntaxError")}
      <button class="ghost small" onclick="addPattern('rejection_patterns')">Add another message</button>
    </div>` : ""}

    <details ${(o.crash_patterns || []).length || (o.expected_exit_codes || []).length ? "open" : ""}>
      <summary>Advanced</summary>
      <div class="indent">
        <label>Messages that always mean a real failure</label>
        <p class="muted" style="font-size:12.5px;margin:2px 0 6px">Checked <em>before</em> the
          rejection messages above, so a broad rejection rule cannot hide a genuine bug.</p>
        ${patternRows("crash_patterns", "java.lang.NullPointerException")}
        <button class="ghost small" onclick="addPattern('crash_patterns')">Add another message</button>
        <div style="margin-top:10px">
          <label for="exit-codes">Exit codes that are not failures</label>
          <input id="exit-codes" type="text" placeholder="0, 1"
            value="${esc((o.expected_exit_codes || []).join(", "))}">
        </div>
      </div>
    </details>

    <div class="actions">
      <button class="ghost" onclick="stashStrategy(); gotoStep('generators')">Back</button>
      <button class="primary" onclick="commitStrategy()">Continue</button>
    </div>
    <div id="err"></div>
  </div>`;
}

function commitStrategy() { stashStrategy(); gotoStep("run"); }

// ------------------------------------------------------------ step views

function renderStep() {
  ({ sut: stepSut, grammar: stepGrammar, generators: stepGenerators,
     strategy: stepStrategy, run: stepRun }[S.step])();
}

function targetRow(x, i, total) {
  return `<div class="row" data-target="${i}" style="align-items:flex-end">
    ${total > 1 ? `<div style="flex:0 0 130px"><label>Name</label>
      <input type="text" class="t-name" value="${esc(x.name || "sut" + (i + 1))}"></div>` : ""}
    <div style="flex:4"><label>Command${total > 1 ? "" : ""}</label>
      <input type="text" class="t-cmd" value="${esc((x.command || []).join(" "))}"></div>
    ${total > 1 ? `<div style="flex:0 0 40px"><button class="ghost small" onclick="dropTarget(${i})">&times;</button></div>` : ""}
  </div>`;
}

function readTargets() {
  return [...document.querySelectorAll("[data-target]")].map((row, i) => ({
    name: (row.querySelector(".t-name")?.value || `sut${i + 1}`).trim(),
    command: (row.querySelector(".t-cmd").value || "").trim().split(/\s+/).filter(Boolean),
  })).filter(x => x.command.length);
}
function addTarget() {
  const t = readTargets();
  t.push({ name: `sut${t.length + 1}`, command: [] });
  S.config.sut = { ...sut(), targets: t, command: undefined };
  stepSut();
}
function dropTarget(i) {
  const t = readTargets(); t.splice(i, 1);
  S.config.sut = t.length > 1 ? { ...sut(), targets: t, command: undefined }
                              : { ...sut(), command: t[0]?.command, targets: undefined };
  stepSut();
}

// Categories are a starting point, not a taxonomy: each one fills in a command
// shape and a sample input that suits it. The user edits both.
const TARGET_KINDS = [
  { id: "cli",     t: "A command-line program",
    d: "Reads a file given as an argument.",
    cmd: "./your-parser {input}", sample: "1 + 1\n" },
  { id: "jar",     t: "A Java program",
    d: "A jar, run with the JDK on your PATH.",
    cmd: "java -jar your-tool.jar {input}", sample: "1 + 1\n" },
  { id: "script",  t: "A script",
    d: "Python, Node, Ruby -- anything with an interpreter.",
    cmd: "python3 parse.py {input}", sample: "1 + 1\n" },
  { id: "other",   t: "Something else",
    d: "Write the command yourself.", cmd: "", sample: "" },
];

function pickKind(id) {
  const k = TARGET_KINDS.find(x => x.id === id);
  S.kind = id;
  if (id === null) { S.config.sut = { timeout: sut().timeout }; S.probe = null; stepSut(); return; }
  if (k && k.cmd && !readTargets().length) {
    S.config.sut = { ...sut(), command: k.cmd.split(" ") };
  }
  if (k && k.sample) S.sample = k.sample;
  S.probe = null;
  stepSut();
}

async function verifyCommand() {
  const t = readTargets();
  if (!t.length) { el("err").innerHTML = `<div class="note bad">Enter a command first.</div>`; return; }
  S.config.sut = { ...sut(), ...(t.length > 1 ? { targets: t } : { command: t[0].command }) };
  S.sample = el("sample").value;
  el("probe").innerHTML = `<div class="note">Running it once&hellip;</div>`;
  try {
    S.probe = await api("/api/probe", { command: t[0].command, sample: S.sample });
  } catch (e) {
    S.probe = { ok: false, error: String(e.message || e) };
  }
  stepSut();
}

function probeReport() {
  const r = S.probe;
  if (!r) return "";
  if (!r.ok) return `<div class="note bad"><strong>It did not run.</strong><br>${esc(r.error)}</div>`;
  const dead = r.timed_out;
  // Deliberately not a verdict. A non-zero exit here is usually the system
  // doing its job -- step 4 is where that gets configured.
  const head = dead
    ? `<strong>No answer in ${Math.round(r.duration_ms / 1000)}s.</strong> If that is normal for
       your system, raise the timeout; if not, the command may be waiting for input on stdin,
       which SpreadEx does not provide.`
    : `<strong>It ran.</strong> Exit code <span class="mono">${r.exit_code}</span>,
       ${Math.round(r.duration_ms)}&thinsp;ms. A non-zero exit here is often correct &mdash;
       you will say what counts as a failure on step 4.`;
  const block = (title, text) => text && text.trim()
    ? `<div style="margin-top:8px"><label>${title}</label><pre>${esc(text)}</pre></div>` : "";
  return `<div class="note ${dead ? "warn" : "good"}">${head}
    <div style="margin-top:8px"><label>Command run</label>
      <pre>${esc((r.command || []).join(" "))}</pre></div>
    ${block("Standard output", r.stdout)}${block("Standard error", r.stderr)}</div>`;
}

function stepSut() {
  const t = targets();
  const rows = t.length ? t : [{ name: "sut", command: [] }];
  const chosen = S.kind || (t.length ? "other" : null);
  if (S.sample === undefined) S.sample = "1 + 1\n";
  el("view").innerHTML = `
  <div class="card">
    <h3>What are you testing?</h3>
    <p class="why">SpreadEx runs one command for every generated input.
      <span class="mono">{input}</span> is replaced with the path to each one; leave it out and
      the path is appended as the last argument.</p>

    ${chosen ? "" : `<div class="kinds">${TARGET_KINDS.map(k => `
      <button class="kind" onclick="pickKind('${k.id}')">
        <span class="t">${k.t}</span><span class="d">${k.d}</span>
      </button>`).join("")}</div>`}

    ${chosen ? `
    <div id="targets">${rows.map((x, i) => targetRow(x, i, rows.length)).join("")}</div>
    <div class="actions">
      <button class="ghost small" onclick="addTarget()">Compare another implementation</button>
      <span class="muted" style="font-size:12.5px">Two or more lets SpreadEx test them against
        each other &mdash; no expected output needed.</span>
    </div>
    <div class="row" style="margin-top:4px">
      <div><label for="timeout">Timeout per input</label>
        <input id="timeout" type="text" value="${esc(sut().timeout || "5s")}"></div>
      <div><label for="sample">Sample input to try it with</label>
        <input id="sample" type="text" value="${esc(S.sample.replace(/\n$/, ""))}"></div>
    </div>
    <div class="actions">
      <button class="ghost" onclick="verifyCommand()">Try it once</button>
      <span class="muted" style="font-size:12.5px">Runs your command on that sample, now, so a
        typo does not surface as 500 crashes later.</span>
    </div>
    <div id="probe">${probeReport()}</div>
    <div class="actions">
      <button class="ghost small" onclick="pickKind(null)">Start over</button>
      <button class="primary" onclick="commitSut()">Continue</button>
    </div>` : ""}
    <div id="err"></div>
  </div>`;
}

function commitSut() {
  const t = readTargets();
  if (!t.length) { el("err").innerHTML = `<div class="note bad">Enter a command to run.</div>`; return; }
  S.config.sut = t.length > 1
    ? { timeout: el("timeout").value, targets: t }
    : { timeout: el("timeout").value, command: t[0].command };
  // A second implementation is the only thing that makes differential testing
  // possible, so dropping back to one target has to retire it.
  const o = { ...(cfg().oracle || {}) };
  if (t.length < 2 && o.type === "differential") o.type = "crash";
  S.config.oracle = o;
  gotoStep("grammar");
}

async function stepGrammar() {
  el("view").innerHTML = `<div class="card"><div class="empty">Looking for grammars…</div></div>`;
  const { grammars } = await api("/api/files");
  S.grammars = grammars;
  const chosen = cfg().grammar?.source || "";
  el("view").innerHTML = `
  <div class="card">
    <h3>Where do the inputs come from?</h3>
    <p class="why">A grammar describes what a valid input looks like, and generators write new
      ones from it. One grammar is enough: SpreadEx derives each generator's dialect &mdash; a
      FuzzingBook dict, plain BNF for ISLa, BNF-with-operators for Fandango, ANTLRv4 for
      Grammarinator &mdash; so you write it once.</p>
    <p class="why">No grammar? Point SpreadEx at a directory of inputs you already have. That
      rules out the generators, but prioritization and execution work the same.</p>
    <label for="grammar">A grammar in this project</label>
    <select id="grammar" onchange="inspectGrammar()">
      <option value="">— none; I will use existing inputs instead —</option>
      ${grammars.map(g => `<option value="${esc(g.path)}" ${g.path === chosen ? "selected" : ""}>${esc(g.path)}</option>`).join("")}
    </select>
    ${grammars.length ? "" : `<div class="note">No grammar-shaped files found under this project
      (.bnf, .g4, .fan, .ebnf, or a .py holding a grammar dict).</div>`}
    <label for="corpus">Or a directory of inputs you already have</label>
    <input id="corpus" type="text" placeholder="./seeds" value="${esc(cfg().corpus?.path || "")}">
    <div id="ginfo"></div>
    <div class="actions">
      <button class="ghost" onclick="gotoStep('sut')">Back</button>
      <button class="ghost" onclick="toggleAssistant()">Help me write one</button>
      <button class="primary" onclick="commitGrammar()">Continue</button>
    </div>
  </div>
  <div id="assistant"></div>`;
  if (chosen) inspectGrammar();
}

// ------------------------------------------------------- assistant (opt-in)

let ASSIST = { open: false, providers: [], proposal: null, busy: false };

async function toggleAssistant() {
  ASSIST.open = !ASSIST.open;
  const holder = el("assistant");
  if (!holder) return;
  if (!ASSIST.open) { holder.innerHTML = ""; return; }
  if (!ASSIST.providers.length) {
    try { ASSIST.providers = (await api("/api/providers")).providers; }
    catch (e) { holder.innerHTML = `<div class="card"><div class="note bad">${esc(e.message)}</div></div>`; return; }
  }
  paintAssistant();
}

function providerPicker(id) {
  return `<select id="${id}" onchange="paintKeyField()">
    ${ASSIST.providers.map(p => `<option value="${esc(p.id)}">${esc(p.label)}${p.local ? " — on this machine" : ""}${p.key_in_env ? " — key found" : ""}</option>`).join("")}
  </select>`;
}

function paintKeyField() {
  const p = ASSIST.providers.find(x => x.id === el("provider").value);
  const box = el("keybox");
  if (!box || !p) return;
  box.innerHTML = p.local
    ? `<div class="note" style="border-left-color:var(--color-success);background:var(--color-success-lt)">
         ${esc(p.note || "Runs locally.")} Nothing leaves this machine.</div>`
    : (p.key_in_env
      ? `<div class="muted" style="font-size:12.5px;margin-top:8px">Using
           <span class="mono">${esc(p.env_var)}</span> from your environment.</div>`
      : `<label for="apikey">${esc(p.label)} API key</label>
         <input id="apikey" type="password" autocomplete="off" placeholder="sk-…">
         <div class="muted" style="font-size:12px;margin-top:4px">Held for this request only.
           Never written to disk, never logged.</div>`);
}

function paintAssistant() {
  const holder = el("assistant");
  if (!holder) return;
  const corpusPath = (el("corpus")?.value || "").trim();
  holder.innerHTML = `
  <div class="card">
    <h3>Grammar assistant</h3>
    <p class="why">A model proposes a grammar; SpreadEx then checks it with the same parser and
      diagnostics a hand-written grammar goes through. If it does not pass, the error is handed
      back and it tries again &mdash; and if it still does not pass, you are told that rather than
      given something that merely looks right.</p>
    <div class="note">This sends your examples and description to the provider you pick. Choose a
      local model if that matters.</div>
    <div class="row" style="margin-top:4px">
      <div><label for="provider">Provider</label>${providerPicker("provider")}</div>
      <div><label for="model">Model</label><input id="model-name" type="text" placeholder="(default)"></div>
    </div>
    <div id="keybox"></div>
    <label for="corpus-hint">Learn from example inputs in</label>
    <input id="corpus-hint" type="text" value="${esc(corpusPath)}" placeholder="./seeds">
    <label for="description">Describe the input language (optional)</label>
    <textarea id="description" style="min-height:80px"
      placeholder="A program is a sequence of statements. A statement is a print or an assignment…"></textarea>
    <div class="actions">
      <button class="primary" id="go-assist" onclick="runAssist('infer')">Propose a grammar</button>
      <span id="assist-status" class="muted" style="font-size:12.5px"></span>
    </div>
    <div id="proposal"></div>
  </div>`;
  paintKeyField();
}

function llmSettings() {
  return {
    provider: el("provider").value,
    model: el("model-name").value,
    api_key: el("apikey")?.value || "",
  };
}

async function runAssist(task, extra) {
  if (ASSIST.busy) return;
  ASSIST.busy = true;
  const btn = el("go-assist"); if (btn) btn.disabled = true;
  el("assist-status").innerHTML = `<span class="spinner"></span> asking the model…`;
  let res;
  try {
    res = await api("/api/assist", {
      task,
      corpus: el("corpus-hint")?.value || "",
      description: el("description")?.value || "",
      ...llmSettings(), ...(extra || {}),
    });
  } catch (e) {
    el("assist-status").textContent = "";
    el("proposal").innerHTML = `<div class="note bad">${esc(e.message)}</div>`;
    ASSIST.busy = false; if (btn) btn.disabled = false;
    return;
  }
  ASSIST.busy = false; if (btn) btn.disabled = false;
  el("assist-status").textContent = "";
  if (!res.ok) {
    el("proposal").innerHTML = `<div class="note bad">${esc(res.error)}</div>`;
    return;
  }
  ASSIST.proposal = res.proposal;
  paintProposal();
}

function paintProposal() {
  const p = ASSIST.proposal;
  const tries = p.attempts.length;
  el("proposal").innerHTML = `
    <div style="margin-top:18px;border-top:1px solid var(--color-border);padding-top:16px">
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
        ${p.ok ? `<span class="tag ok">validated</span>` : `<span class="tag bad">did not validate</span>`}
        <span class="muted" style="font-size:12.5px">
          ${tries} attempt${tries === 1 ? "" : "s"}${p.ok ? ` · ${num(p.rules)} rules · start &lt;${esc(p.start)}&gt;` : ""}</span>
      </div>
      ${p.errors.length ? `<div class="note bad">${p.errors.map(esc).join("<br>")}</div>` : ""}
      ${p.warnings.length ? `<div class="note">${p.warnings.map(esc).join("<br>")}</div>` : ""}
      ${p.support?.length ? `<table style="margin-top:12px"><tbody>${p.support.map(s => `
        <tr><td style="width:32%">${esc(s.generator)}</td>
            <td><span class="${s.usable ? "ok" : "bad"}">${s.usable ? "&#10003;" : "&#10007;"}
              ${s.directly ? "directly" : (s.usable ? "after rewriting" : "cannot express")}</span>
            ${(s.risks || []).map(r => `<div class="warn" style="font-size:12px">! ${esc(r)}</div>`).join("")}</td></tr>`).join("")}</tbody></table>` : ""}
      <textarea id="proposed" style="margin-top:12px;min-height:220px">${esc(p.text)}</textarea>
      <div class="actions">
        <button class="ghost" onclick="runAssist('repair', {grammar: el('proposed').value})">Revalidate &amp; fix</button>
        <input id="savepath" type="text" style="flex:0 0 220px" value="grammar.bnf">
        <button class="primary" onclick="acceptProposal()" ${p.ok ? "" : "disabled"}>Save &amp; use</button>
        ${p.ok ? "" : `<span class="muted" style="font-size:12.5px">Fix the errors before saving.</span>`}
      </div>
      <div id="saveerr"></div>
    </div>`;
}

async function acceptProposal() {
  const path = el("savepath").value.trim();
  try {
    const res = await api("/api/grammar/save", { path, text: el("proposed").value });
    if (!res.ok) { el("saveerr").innerHTML = `<div class="note bad">${esc(res.error)}</div>`; return; }
    S.config.grammar = { source: res.written };
    ASSIST.open = false;
    await stepGrammar();
  } catch (e) { el("saveerr").innerHTML = `<div class="note bad">${esc(e.message)}</div>`; }
}

async function inspectGrammar() {
  const source = el("grammar").value;
  const info = el("ginfo");
  if (!source) { info.innerHTML = ""; return; }
  info.innerHTML = `<div class="empty"><span class="spinner"></span> Checking the grammar…</div>`;
  let g;
  try { g = await api(`/api/grammar?source=${encodeURIComponent(source)}`); }
  catch (e) { info.innerHTML = `<div class="note bad">${esc(e.message)}</div>`; return; }
  if (g.error) { info.innerHTML = `<pre class="bad">${esc(g.error)}</pre>`; return; }

  const sev = s => s === "error" ? "bad" : s === "warning" ? "warn" : "muted";
  info.innerHTML = `
    <div style="margin-top:16px" class="stats">
      <div class="stat"><div class="k">Rules</div><div class="v">${num(g.rules)}</div></div>
      <div class="stat"><div class="k">Start</div><div class="v mono">&lt;${esc(g.start)}&gt;</div></div>
    </div>
    <div class="muted" style="font-size:12.5px;margin-top:8px">Uses: ${g.features?.length ? esc(g.features.join(", ")) : "plain BNF"}</div>
    <table style="margin-top:14px"><tbody>
      ${(g.support || []).map(s => `<tr><td style="width:30%">${esc(s.generator)}</td><td>
        <span class="${s.status === "blocked" || s.status === "unsupported" ? "bad" : "ok"}">
          ${s.status === "blocked" || s.status === "unsupported" ? "&#10007;" : "&#10003;"}
          ${{ direct: "directly", rewrite: "after rewriting", blocked: "cannot express", unsupported: "not emitted yet" }[s.status]}</span>
        ${(s.blockers || []).map(b => `<div class="bad" style="font-size:12px">${esc(b)}</div>`).join("")}
        ${(s.risks || []).map(r => `<div class="warn" style="font-size:12px">! ${esc(r)}</div>`).join("")}
      </td></tr>`).join("")}
    </tbody></table>
    ${(g.findings || []).length ? `<details open style="margin-top:12px">
      <summary>${g.findings.length} diagnostic(s)</summary>
      ${g.findings.map(f => `<div style="padding:6px 0">
        <span class="tag ${sev(f.severity)}">${esc(f.code)}</span>
        ${f.rule ? `<span class="mono muted"> &lt;${esc(f.rule)}&gt;</span>` : ""}
        <div style="margin-top:3px">${esc(f.message)}</div></div>`).join("")}
    </details>` : `<div class="note" style="border-left-color:var(--color-success);background:var(--color-success-lt)">
      No problems found in this grammar.</div>`}`;
}

function commitGrammar() {
  const source = el("grammar").value, corpus = el("corpus").value.trim();
  if (!source && !corpus) {
    el("ginfo").innerHTML = `<div class="note bad">Pick a grammar or point at a corpus directory &mdash;
      SpreadEx needs somewhere for inputs to come from.</div>`;
    return;
  }
  S.config.grammar = source ? { source } : undefined;
  S.config.corpus = corpus ? { path: corpus } : undefined;
  gotoStep("generators");
}

async function stepGenerators() {
  el("view").innerHTML = `<div class="card"><div class="empty">Checking generators…</div></div>`;
  const { generators } = await api("/api/generators");
  S.generators = generators;
  if (!cfg().generators) S.config.generators = generators.filter(g => g.selected).map(g => g.id);
  if (!S.config.generators.length && !cfg().corpus) {
    S.config.generators = generators.filter(g => g.installed && g.emittable).map(g => g.id);
  }
  paintGenerators();
}

function paintGenerators() {
  const chosen = new Set(cfg().generators || []);
  el("view").innerHTML = `
  <div class="card">
    <h3>Which generators?</h3>
    <p class="why">Each runs in its own isolated environment, so one generator's dependency pins
      cannot break another's. Picking several is the point: SpreadEx compares them.</p>
    <div class="gen-grid">
      ${S.generators.map(g => `
        <div class="gen" aria-pressed="${chosen.has(g.id)}" onclick="toggleGen('${g.id}')">
          <div class="name">${esc(g.name)}</div>
          <div class="meta">${esc(g.dialect)}${g.constraints ? " · constraints" : ""}</div>
          <div class="state">${g.installed
            ? `<span class="tag ok">installed${g.version ? " " + esc(g.version) : ""}</span>`
            : `<span class="tag warn">not installed</span>`}
            ${g.emittable ? "" : `<span class="tag bad">no dialect</span>`}</div>
          ${g.installed ? "" : `<div class="actions" style="margin-top:9px">
            <button class="ghost small" onclick="event.stopPropagation();installGen('${g.id}')">Install</button></div>`}
          ${g.notes ? `<div class="meta" style="margin-top:7px">${esc(g.notes)}</div>` : ""}
        </div>`).join("")}
    </div>
    <div id="joblog"></div>
    <div class="actions">
      <button class="ghost" onclick="gotoStep('grammar')">Back</button>
      ${constraintCapable().length ? `<button class="ghost" onclick="toggleConstraints()">Add constraints</button>` : ""}
      <button class="primary" onclick="commitGenerators()">Continue</button>
    </div>
    <div id="err"></div>
  </div>
  <div id="constraints"></div>`;
  if (CONSTRAINTS.open) paintConstraints();
}

// ------------------------------------------------ constraints (opt-in)

let CONSTRAINTS = { open: false, proposal: null, busy: false };

function constraintCapable() {
  const chosen = new Set(cfg().generators || []);
  return S.generators.filter(g => g.constraints && chosen.has(g.id));
}

async function toggleConstraints() {
  CONSTRAINTS.open = !CONSTRAINTS.open;
  if (!CONSTRAINTS.open) { el("constraints").innerHTML = ""; return; }
  if (!ASSIST.providers.length) {
    try { ASSIST.providers = (await api("/api/providers")).providers; } catch (e) { /* shown below */ }
  }
  paintConstraints();
}

function paintConstraints() {
  // The step may still be loading when this is called; there is nothing to
  // paint into yet, and it will be painted on arrival instead.
  const holder = el("constraints");
  if (!holder) return;
  const capable = constraintCapable();
  holder.innerHTML = `
  <div class="card">
    <h3>Constraints</h3>
    <p class="why">Only Fandango and ISLa accept constraints &mdash; rules a generated input must
      satisfy, like "every variable is declared before it is used". Describe them in plain language
      and a model writes them in that generator's syntax.</p>
    <div class="note">Unlike a grammar, a constraint cannot be fully machine-checked: SpreadEx
      verifies that every symbol it mentions exists, but whether it <em>means</em> what you intended
      only a short campaign will show.</div>
    <div class="row" style="margin-top:4px">
      <div><label for="c-generator">Generator</label>
        <select id="c-generator">${capable.map(g => `<option value="${esc(g.id)}">${esc(g.name)}</option>`).join("")}</select></div>
      <div><label for="c-provider">Provider</label>
        <select id="c-provider">${ASSIST.providers.map(p => `<option value="${esc(p.id)}">${esc(p.label)}</option>`).join("")}</select></div>
    </div>
    <div id="c-key"></div>
    <label for="c-text">What must be true of every generated input?</label>
    <textarea id="c-text" style="min-height:90px"
      placeholder="Every variable is declared before it is used.&#10;Loop bounds are between 1 and 10."></textarea>
    <div class="actions">
      <button class="primary" id="c-go" onclick="runConstraints()">Write the constraints</button>
      <span id="c-status" class="muted" style="font-size:12.5px"></span>
    </div>
    <div id="c-out"></div>
  </div>`;
  const p = ASSIST.providers.find(x => x.id === el("c-provider")?.value);
  if (p && !p.local && !p.key_in_env) {
    el("c-key").innerHTML = `<label for="c-apikey">${esc(p.label)} API key</label>
      <input id="c-apikey" type="password" autocomplete="off" placeholder="sk-…">
      <div class="muted" style="font-size:12px;margin-top:4px">Held for this request only.</div>`;
  }
}

async function runConstraints() {
  if (CONSTRAINTS.busy) return;
  const source = cfg().grammar?.source;
  if (!source) {
    el("c-out").innerHTML = `<div class="note bad">Pick a grammar first &mdash; constraints are
      written against its symbols.</div>`;
    return;
  }
  CONSTRAINTS.busy = true;
  el("c-go").disabled = true;
  el("c-status").innerHTML = `<span class="spinner"></span> asking the model…`;
  let res;
  try {
    const g = await api(`/api/grammar?source=${encodeURIComponent(source)}`);
    res = await api("/api/assist", {
      task: "constraints",
      generator: el("c-generator").value,
      constraints: el("c-text").value,
      grammar: g.text || "",
      grammar_source: source,
      provider: el("c-provider").value,
      api_key: el("c-apikey")?.value || "",
    });
  } catch (e) {
    el("c-status").textContent = "";
    el("c-out").innerHTML = `<div class="note bad">${esc(e.message)}</div>`;
    CONSTRAINTS.busy = false; el("c-go").disabled = false;
    return;
  }
  CONSTRAINTS.busy = false; el("c-go").disabled = false;
  el("c-status").textContent = "";
  if (!res.ok) { el("c-out").innerHTML = `<div class="note bad">${esc(res.error)}</div>`; return; }

  const p = res.proposal;
  el("c-out").innerHTML = `
    <div style="margin-top:16px;border-top:1px solid var(--color-border);padding-top:14px">
      ${p.ok ? `<span class="tag ok">symbols check out</span>` : `<span class="tag bad">rejected</span>`}
      ${p.errors.length ? `<div class="note bad">${p.errors.map(esc).join("<br>")}</div>` : ""}
      ${p.warnings.length ? `<div class="note">${p.warnings.map(esc).join("<br>")}</div>` : ""}
      <pre>${esc(p.text)}</pre>
      <div class="muted" style="font-size:12.5px;margin-top:8px">Copy these into your
        ${esc(el("c-generator").value === "fandango" ? ".fan grammar" : ".isla constraint file")}
        beside the grammar, then re-run.</div>
    </div>`;
}

function toggleGen(id) {
  const set = new Set(cfg().generators || []);
  set.has(id) ? set.delete(id) : set.add(id);
  S.config.generators = [...set];
  paintGenerators();
}

async function installGen(id) {
  try { await api("/api/generators/install", { id }); }
  catch (e) { el("err").innerHTML = `<div class="note bad">${esc(e.message)}</div>`; return; }
  watchJob(() => stepGenerators());
}

function commitGenerators() {
  if (!(cfg().generators || []).length && !cfg().corpus) {
    el("err").innerHTML = `<div class="note bad">Select at least one generator, or go back and
      point at a corpus directory.</div>`;
    return;
  }
  const missing = S.generators.filter(g => (cfg().generators || []).includes(g.id) && !g.installed);
  if (missing.length) {
    el("err").innerHTML = `<div class="note bad">Not installed: ${missing.map(m => esc(m.name)).join(", ")}.
      Install them, or deselect them.</div>`;
    return;
  }
  gotoStep("strategy");
}

async function stepRun() {
  const c = cfg();
  el("view").innerHTML = `
  <div class="card">
    <h3>Budget</h3>
    <p class="why">SpreadEx spends what you give it and no more. Generation and execution are
      budgeted separately, because they fail in different ways.</p>
    <div class="row">
      <div><label for="bgen">Generation</label><input id="bgen" type="text" value="${esc(c.budget?.generation || "1m")}"></div>
      <div><label for="bexec">Execution</label><input id="bexec" type="text" value="${esc(c.budget?.execution || "1m")}"></div>
      <div><label for="count">Inputs per generator</label><input id="count" type="number" min="1" value="${c.generation?.count || 200}"></div>
    </div>
    <div class="row">
      <div><label for="signal">Selection signal</label>
        <select id="signal">
          <option value="cc" ${c.selection_signal !== "random" ? "selected" : ""}>Cluster coverage (recommended)</option>
          <option value="random" ${c.selection_signal === "random" ? "selected" : ""}>Random (baseline)</option>
        </select></div>
      <div><label for="model">Embedding</label>
        <select id="model">
          <option value="tfidf" ${(c.embedding?.model || "tfidf") === "tfidf" ? "selected" : ""}>TF-IDF (no GPU, no key)</option>
          <option value="unixcoder" ${c.embedding?.model === "unixcoder" ? "selected" : ""}>UniXcoder (needs spreadex[neural])</option>
        </select></div>
      <div><label for="jobs">Parallel executions</label><input id="jobs" type="number" min="1" max="32" value="4"></div>
    </div>
    <div class="note">More than one parallel execution is faster, but makes durations noisier and
      can time out an input that would have passed on its own.</div>
  </div>

  <div class="card">
    <h3>Review</h3>
    <p class="why">This is what will happen. It is written to
      <span class="mono">spreadex.yaml</span>, and the campaign runs exactly this &mdash;
      nothing else.</p>
    <div id="summary">${reviewSummary()}</div>
    <details>
      <summary>The file that will be written</summary>
      <pre id="preview">${esc(buildYaml())}</pre>
    </details>
    <div class="actions">
      <button class="ghost" onclick="gotoStep('strategy')">Back</button>
      <button class="ghost" onclick="refreshPreview()">Refresh preview</button>
      <button class="primary" id="launch" onclick="launch()">Save &amp; run</button>
    </div>
    <div id="err"></div>
    <div id="joblog"></div>
  </div>`;
  ["bgen", "bexec", "count", "signal", "model"].forEach(id =>
    el(id).addEventListener("change", refreshPreview));
}

function reviewSummary() {
  // The same facts as the YAML, in the order someone would ask about them.
  const c = cfg(), t = targets();
  const gens = c.generators || [];
  const src = c.grammar?.source ? `the grammar <span class="mono">${esc(c.grammar.source)}</span>`
            : c.corpus?.path ? `the inputs already in <span class="mono">${esc(c.corpus.path)}</span>`
            : "<span class=\"bad\">nothing yet &mdash; go back to step 2</span>";
  const checks = ["crashes and hangs"];
  if (c.oracle?.type === "differential") checks.push("disagreement between implementations");
  const nrej = (c.oracle?.rejection_patterns || []).length;
  if (nrej) checks.push(nrej === 1 ? "one message that means a deliberate rejection"
                                   : `${nrej} messages that mean a deliberate rejection`);
  const row = (k, v) => `<tr><th>${k}</th><td>${v}</td></tr>`;
  return `<table class="summary">
    ${row(t.length > 1 ? "Testing" : "Testing under",
          t.map(x => `<span class="mono">${esc((x.command || []).join(" "))}</span>`).join("<br>"))}
    ${row("Inputs from", src)}
    ${row("Written by", gens.length
        ? gens.map(esc).join(", ")
        : (c.corpus?.path ? "nobody &mdash; existing inputs only"
                          : "<span class=\"bad\">no generator selected</span>"))}
    ${row("Reported as failures", checks.join("; "))}
    ${row("Budget", `${esc(c.budget?.generation || "1m")} generating,
           ${esc(c.budget?.execution || "1m")} executing &mdash; and no more`)}
    ${row("Ordered by", (c.selection_signal === "random")
        ? "random (the baseline)" : "cluster coverage, most different first")}
  </table>`;
}

function collectRunConfig() {
  S.config.budget = { generation: el("bgen").value, execution: el("bexec").value };
  S.config.generation = { count: Number(el("count").value) || 200 };
  S.config.selection_signal = el("signal").value;
  S.config.embedding = { model: el("model").value };
}
function refreshPreview() {
  collectRunConfig();
  el("preview").textContent = buildYaml();
  el("summary").innerHTML = reviewSummary();
}

async function launch() {
  collectRunConfig();
  el("launch").disabled = true;
  el("err").innerHTML = "";
  try {
    const check = await saveConfig(false);
    if (!check.ok) {
      el("err").innerHTML = `<div class="note bad">${check.errors.map(esc).join("<br>")}</div>`;
      el("launch").disabled = false;
      return;
    }
    await saveConfig(true);
    // The server adopts the file we just wrote; re-read so the header and the
    // steps reflect the project that now exists.
    try { S.project = await api("/api/project"); } catch (e) { /* non-fatal */ }
    const started = await api("/api/run", { jobs: Number(el("jobs").value) || 1 });
    if (started.ok === false) throw new Error(started.error);
    el("joblog").innerHTML = `<div class="note" style="border-left-color:var(--color-primary);
      background:var(--color-primary-lt)">Running <span class="mono">${esc(started.command)}</span></div>`;
  } catch (e) {
    el("err").innerHTML = `<div class="note bad">${esc(e.message)}</div>`;
    el("launch").disabled = false;
    return;
  }
  watchJob(async () => {
    await loadRuns();
    go("results");
  });
}

// --------------------------------------------------------------- job log

function watchJob(onDone) {
  let shown = 0;
  const holder = el("joblog");
  const pre = document.createElement("pre");
  holder.appendChild(pre);
  clearInterval(S.polling);
  S.polling = setInterval(async () => {
    let j;
    try { j = await api(`/api/activity?since=${shown}`); } catch { return; }
    if (j.idle) return;
    shown += (j.lines || []).length;
    if (j.lines?.length) { pre.textContent += j.lines.join("\n") + "\n"; pre.scrollTop = pre.scrollHeight; }
    if (j.done) {
      clearInterval(S.polling);
      if (j.ok === false) {
        holder.insertAdjacentHTML("beforeend", `<div class="note bad">${esc(j.error || "failed")}</div>`);
        const b = el("launch"); if (b) b.disabled = false;
      } else if (onDone) onDone();
    }
  }, 700);
}

// --------------------------------------------------------------- results

async function loadRuns() {
  const r = await api("/api/runs");
  S.runs = r.runs;
  if (!S.current || !S.runs.some(x => x.run_id === S.current)) S.current = S.runs[0]?.run_id || null;
}

function budgetChart(actual, random, total) {
  if (!actual || actual.length < 2) return "";
  if (!actual.some(p => p[1] > 0)) {
    return `<div class="empty">No failures in ${num(total)} executed inputs, so there is no curve
      to draw.<br><span style="font-size:12.5px">For a mature system under test this is the expected
      outcome, not a missing measurement.</span></div>`;
  }
  const W = 620, H = 180, P = { l: 34, r: 12, t: 10, b: 24 };
  const maxY = Math.max(1, ...actual.map(p => p[1]), ...(random || []).map(p => p[1]));
  const x = i => P.l + (i / Math.max(1, total - 1)) * (W - P.l - P.r);
  const y = v => H - P.b - (v / maxY) * (H - P.t - P.b);
  const line = pts => pts.map((p, i) => `${i ? "L" : "M"}${x(p[0] - 1).toFixed(1)},${y(p[1]).toFixed(1)}`).join(" ");
  const ticks = [...new Set([0, Math.round(maxY / 2), maxY])];
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" role="img"
      aria-label="distinct failure signatures against inputs executed">
    ${ticks.map(t => `<line x1="${P.l}" x2="${W - P.r}" y1="${y(t)}" y2="${y(t)}"
       stroke="var(--color-border)" stroke-dasharray="2 3"/>
      <text x="${P.l - 7}" y="${y(t) + 4}" font-size="10" fill="var(--color-muted)" text-anchor="end">${t}</text>`).join("")}
    <text x="${W - P.r}" y="${H - 6}" font-size="10" fill="var(--color-muted)" text-anchor="end">${total} executed</text>
    ${random?.length ? `<path d="${line(random)}" fill="none" stroke="var(--color-muted)" stroke-width="1.5" stroke-dasharray="4 3"/>` : ""}
    <path d="${line(actual)}" fill="none" stroke="var(--series-0)" stroke-width="2"/>
  </svg>
  <div class="legend"><span><span class="swatch" style="background:var(--series-0)"></span>this ordering</span>
  ${random?.length ? `<span><span class="swatch" style="background:var(--color-muted)"></span>random ordering (mean of 200 shuffles)</span>` : ""}</div>`;
}

async function renderResults() {
  const v = el("view");
  if (!S.runs.length) {
    v.innerHTML = `<div class="card"><div class="empty">No campaigns yet.<br>
      <button class="primary" style="margin-top:14px" onclick="go('setup')">Set one up</button></div></div>`;
    return;
  }
  v.innerHTML = `<div class="runlist">${S.runs.map(r => `
    <button aria-current="${r.run_id === S.current}" onclick="pickRun('${esc(r.run_id)}')">
      ${esc(r.run_id.replace("T", " ").replace("Z", ""))} · ${num(r.executed)} executed${r.failures ? ` · <span class="bad">${r.failures} failing</span>` : ""}
    </button>`).join("")}</div><div id="detail"><div class="empty">Loading…</div></div>`;

  let d;
  try { d = await api(`/api/runs/${encodeURIComponent(S.current)}`); }
  catch (e) { el("detail").innerHTML = `<div class="card bad">${esc(e.message)}</div>`; return; }

  const ver = d.verdicts || {};
  const failing = (ver.crash || 0) + (ver.timeout || 0) + (ver.divergence || 0);
  const costs = d.generators.map(g => g.cost_s).filter(c => c > 0);
  const spread = costs.length > 1 ? Math.max(...costs) / Math.min(...costs) : 1;

  el("detail").innerHTML = `
  <div class="card">
    <div class="stats">
      <div class="stat"><div class="k">Executed</div><div class="v">${num(d.executed)}</div></div>
      <div class="stat"><div class="k">Passed</div><div class="v">${num(ver.ok || 0)}</div></div>
      <div class="stat"><div class="k">Rejected (expected)</div><div class="v">${num(ver.expected_rejection || 0)}</div></div>
      <div class="stat"><div class="k">Failing</div><div class="v ${failing ? "bad" : ""}">${num(failing)}</div></div>
      <div class="stat"><div class="k">Signatures</div><div class="v">${num(d.signatures.length)}</div></div>
    </div>
    <div class="note">A <em>rejected</em> input is one the system under test correctly refused.
      Counting those as failures is the difference between a usable tool and a noise generator.</div>
  </div>
  ${d.generators.length ? `<div class="card">
    <h3>Generator comparison</h3>
    <p class="why">Which generators deserve the next generation budget. Cluster coverage is computed
      <em>before</em> anything is executed${d.corpus.k_eff ? `, over ${d.corpus.k_eff} clusters` : ""}.</p>
    <table><thead><tr><th>Generator</th><th class="num">CC</th><th></th><th class="num">Inputs</th><th class="num">Generation cost</th></tr></thead>
      <tbody>${d.generators.map((g, i) => `<tr><td>${esc(g.name)}</td>
        <td class="num mono">${g.cc.toFixed(2)}</td>
        <td style="width:32%"><span class="bar" style="width:${(g.cc * 100).toFixed(0)}%;background:var(--series-${i % 4})"></span></td>
        <td class="num mono">${num(g.inputs)}</td><td class="num mono">${g.cost_s.toFixed(1)}s</td></tr>`).join("")}</tbody></table>
    ${spread > 5 ? `<div class="note">Generation costs differ by more than 5&times;, so these CC values
      compare equal <strong>input counts</strong>, not equal budgets.</div>` : ""}
  </div>` : ""}
  <div class="card">
    <h3>Budget curve</h3>
    <p class="why">Distinct failure signatures against inputs executed. The dashed line is the same
      inputs in random order, so the gap is what the ordering bought &mdash; and no gap is a real
      answer too.</p>
    ${budgetChart(d.budget_curve, d.random_curve, d.executed)}
  </div>
  <div class="card">
    <h3>Failure signatures</h3>
    <p class="why">A signature is not a bug: distinct bugs can share one and one bug can span
      several. Treat the count as a triage aid.</p>
    ${d.signatures.length ? d.signatures.map(s => `<details>
      <summary><span class="mono">${esc(s.signature)}</span>
        <span class="tag ${s.verdict === "divergence" ? "warn" : "bad"}">${esc(s.verdict)}</span>
        &times;${s.count} · first at input ${s.first_rank + 1}${s.new ? ` <span class="tag warn">new</span>` : ""}</summary>
      ${s.detail ? `<div class="muted" style="font-size:12.5px;margin-top:6px">${esc(s.detail)}</div>` : ""}
      ${s.stderr ? `<pre>${esc(s.stderr)}</pre>` : ""}
      <div class="actions"><button class="ghost small" onclick="showInput('${esc(s.example)}', this)">Show an input that triggers it</button></div>
      <div class="holder"></div></details>`).join("") : `<div class="empty">No failures in this run.</div>`}
  </div>
  <div class="card">
    <h3>Reproducing this run</h3>
    <table><tbody>
      <tr><td class="muted" style="width:30%">Config hash</td><td class="mono">${esc(d.config_hash)}</td></tr>
      <tr><td class="muted">Seed / signal</td><td class="mono">${esc(d.seed)} / ${esc(d.signal)}</td></tr>
      ${(d.targets || []).map(t => `<tr><td class="muted">Target ${esc(t.name)}</td>
        <td class="mono">${esc((t.command || []).join(" "))}<br><span class="muted">${esc(t.version || "version unknown")}</span></td></tr>`).join("")}
      <tr><td class="muted">Environment</td><td class="mono">python ${esc(d.environment.python)} · ${esc(d.environment.platform)}</td></tr>
    </tbody></table>
    <pre>spreadex replay ${esc(d.run_id)}</pre>
  </div>`;
}

function pickRun(id) { S.current = id; renderResults(); }

async function showInput(hash, btn) {
  const holder = btn.closest("details").querySelector(".holder");
  if (holder.dataset.loaded) { holder.innerHTML = ""; delete holder.dataset.loaded; return; }
  try {
    const d = await api(`/api/input?hash=${encodeURIComponent(hash)}`);
    holder.innerHTML = `<pre>${esc(d.text)}${d.truncated ? "\n… truncated" : ""}</pre>
      <div class="muted" style="font-size:12px">${d.size_bytes} bytes · from ${esc(d.generators.join(", "))}</div>`;
    holder.dataset.loaded = "1";
  } catch (e) { holder.innerHTML = `<div class="note bad">${esc(e.message)}</div>`; }
}

// ------------------------------------------------------------- bootstrap

(async function () {
  try {
    S.project = await api("/api/project");
    el("project").textContent = S.project.root;
    const conf = await api("/api/config");
    S.config = conf.parsed || {};
    await loadRuns();
    renderSteps();
    // An unconfigured directory always starts at the wizard, whatever happens
    // to be in .spreadex -- there is no campaign to show until it is set up.
    go(S.project.configured && S.runs.length ? "results" : "setup");
  } catch (e) {
    const noToken = !TOKEN || /token/i.test(e.message);
    el("view").innerHTML = noToken
      ? `<div class="card"><h3>This tab has no access token</h3>
          <p class="why">The token is handed over once in the URL and kept only for this tab, so a
          fresh tab has to be opened from the link SpreadEx printed.</p><pre>spreadex ui</pre></div>`
      : `<div class="card"><div class="note bad">${esc(e.message)}</div></div>`;
  }
})();
