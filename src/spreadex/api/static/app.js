// SpreadEx UI: a setup wizard over the campaign engine, plus result views.
//
// The wizard's job is to produce a spreadex.yaml the user has reviewed, and
// then launch exactly that. It never synthesises a command behind their back.

// The token is handed over once in the URL, then kept for this tab only, so it
// stops sitting in the address bar, in history, and in anything we later link.
const incoming = new URL(location.href);
// The token comes from the link once. It is kept for this tab AND for this address: the token is the
// same on every launch of a project, and each project keeps its own port, so a new tab or a bookmark
// of the plain address keeps working.
const tokenStore = { get: k => { try { return sessionStorage.getItem(k) || localStorage.getItem(k) || ""; } catch (e) { return ""; } },
                     set: (k, v) => { try { sessionStorage.setItem(k, v); localStorage.setItem(k, v); } catch (e) { /* private mode */ } } };
// Opened from the link `spreadex ui` printed (it carries the token): start on Home. A reload of a
// tab keeps its place instead.
const FRESH_OPEN = !!incoming.searchParams.get("token");
// `?tour=1`: the guided demo was just opened; read before the address is cleaned.
const TOUR_START = incoming.searchParams.get("tour") === "1";
if (TOUR_START && !incoming.searchParams.get("token")) {
  incoming.searchParams.delete("tour");
  history.replaceState({}, "", incoming.pathname + incoming.search);
}
if (incoming.searchParams.get("token")) {
  tokenStore.set("spreadex-token", incoming.searchParams.get("token"));
  incoming.searchParams.delete("token");
  incoming.searchParams.delete("tour");
  history.replaceState({}, "", incoming.pathname);
}
const TOKEN = tokenStore.get("spreadex-token");

async function api(path, body) {
  const opts = { headers: { "X-SpreadEx-Token": TOKEN } };
  if (body !== undefined) {
    opts.method = "POST";
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(path, opts);
  const payload = await r.json().catch(() => ({}));
  if (!r.ok) {
    const err = new Error(payload.error || r.statusText);
    err.unauthorized = r.status === 401;
    throw err;
  }
  return payload;
}
// One place decides how a failed request looks. A 401 is not a bug in the step the
// user clicked: the tab's token is missing, or belongs to a server that has since
// been restarted (an unconfigured project gets a fresh token on every launch).
function failureCard(e) {
  if (e && (e.unauthorized || !TOKEN)) {
    return `<div class="card" role="alert"><h3>This tab can no longer reach SpreadEx</h3>
      <p class="why">${TOKEN
        ? "Its access token no longer matches this server &mdash; usually because this address now belongs to a different project."
        : "It was opened without an access token."}
        Run this in the project folder. It reopens the right Workbench, with a working link:</p>
      <pre>spreadex ui</pre></div>`;
  }
  return `<div class="card"><div class="note bad">${esc((e && e.message) || e)}</div></div>`;
}
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const num = n => (n ?? 0).toLocaleString();
const el = id => document.getElementById(id);

// Light by default. A choice is remembered for this machine, not just this address: every project's
// Workbench has its own port, so browser storage alone would forget it in the next project.
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  try { localStorage.setItem("spreadex-theme", theme); } catch (e) { /* blocked storage */ }
}
function toggleTheme() {
  const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
  applyTheme(next);
  // A read-only Workbench refuses every POST; the choice then lasts for this address only.
  api("/api/prefs", { theme: next }).catch(() => {});
}

const STEPS = [
  // `icon` is a NAME looked up in ICONS at render time: ICONS is declared
  // further down, and reading it from here would hit the temporal dead zone.
  { id: "sut",        n: 1, tone: "green",  icon: "terminal",    t: "System under test", d: "How to run your program." },
  { id: "grammar",    n: 2, tone: "blue",   icon: "doc",         t: "Inputs",            d: "What does it accept?" },
  { id: "generators", n: 3, tone: "purple", icon: "sliders",     t: "Generators",        d: "Choose who writes inputs." },
  { id: "strategy",   n: 4, tone: "orange", icon: "shield",      t: "Testing strategy",  d: "What counts as a failure?" },
  { id: "run",        n: 5, tone: "red",    icon: "playOutline", t: "Review & run",      d: "Review and launch." },
];

const S = {
  tab: "setup", step: "sut", project: null, config: {}, rejects: undefined,
  rtab: "overview", rview: "list", live: null, detail: null,
  kind: null, sample: undefined, probe: null,
  generators: [], grammars: [], runs: [], current: null, polling: null,
  // Steps the user has confirmed with Continue (or that a saved project already had), and the SUT
  // command the last successful Test connection ran. Together they decide which steps are reachable.
  confirmed: new Set(), verifiedSut: null,
};

// Where a page load lands, in this order (an active run is handled before this is asked):
// the view this tab was on, if it still makes sense -> the latest campaign -> Review & run for a
// configured project with no campaigns -> the first setup step for a new one.
function initialView(project, runs, saved, reachable) {
  if (saved && savedViewValid(saved, runs, reachable)) return saved;
  if (runs.length) return { tab: "results", rview: "run", current: runs[0].run_id };
  if (project.configured) return { tab: "setup", step: "run" };
  return { tab: "setup", step: "sut" };
}
function savedViewValid(v, runs, reachable) {
  if (v.tab === "landing") return true;
  if (v.tab === "results") return v.rview === "list" ? runs.length > 0
    : v.rview === "run" && runs.some(r => r.run_id === v.current);
  if (v.tab === "setup") return STEPS.some(x => x.id === v.step) && reachable(v.step);
  return false;
}
const VIEW_KEY = "spreadex-view";
function saveView() {
  const v = { tab: S.tab, step: S.step, rview: S.rview === "live" ? "list" : S.rview, current: S.current };
  try { sessionStorage.setItem(VIEW_KEY, JSON.stringify(v)); } catch (e) { /* blocked storage */ }
}
function loadView() {
  try { return JSON.parse(sessionStorage.getItem(VIEW_KEY) || "null"); } catch (e) { return null; }
}

// ---------------------------------------------------------------- icons
// Inline SVG rather than glyphs: a font glyph like "▥" renders differently on
// every platform and cannot take a theme colour. These inherit currentColor,
// scale with the box, and carry no text content for a screen reader to read
// out -- the label beside them is the label.
const I = (p, o = {}) =>
  `<svg class="ico" viewBox="0 0 24 24" fill="${o.fill || "none"}" stroke="currentColor"
     stroke-width="${o.w || 2}" stroke-linecap="round" stroke-linejoin="round"
     aria-hidden="true" focusable="false">${p}</svg>`;

//: The brand mark, animated. Carried over from the research webapp's topbar so
//: the tool keeps the identity it has always had: the red centre pops, the
//: green squares fan to the corners, the orange circles follow, and the spokes
//: fade in behind them. Decorative, so it is hidden from assistive tech -- the
//: heading beside it already says what this is.
const BRAND_MARK = `
  <svg class="hero-mark" viewBox="11 11 38 38" xmlns="http://www.w3.org/2000/svg"
       aria-hidden="true" focusable="false">
    <line class="logo-line-green"  x1="30" y1="30" x2="16.5" y2="16.5"/>
    <line class="logo-line-green"  x1="30" y1="30" x2="43.5" y2="16.5"/>
    <line class="logo-line-green"  x1="30" y1="30" x2="16.5" y2="43.5"/>
    <line class="logo-line-green"  x1="30" y1="30" x2="43.5" y2="43.5"/>
    <line class="logo-line-orange" x1="30" y1="30" x2="30" y2="17"/>
    <line class="logo-line-orange" x1="30" y1="30" x2="30" y2="43"/>
    <line class="logo-line-orange" x1="30" y1="30" x2="17" y2="30"/>
    <line class="logo-line-orange" x1="30" y1="30" x2="43" y2="30"/>
    <rect class="logo-green" x="12" y="12" width="9" height="9" rx="1.5"/>
    <rect class="logo-green" x="39" y="12" width="9" height="9" rx="1.5"/>
    <rect class="logo-green" x="12" y="39" width="9" height="9" rx="1.5"/>
    <rect class="logo-green" x="39" y="39" width="9" height="9" rx="1.5"/>
    <circle class="logo-orange" cx="30" cy="17" r="5"/>
    <circle class="logo-orange" cx="30" cy="43" r="5"/>
    <circle class="logo-orange" cx="17" cy="30" r="5"/>
    <circle class="logo-orange" cx="43" cy="30" r="5"/>
    <circle class="logo-red" cx="30" cy="30" r="8"   fill="#e53935"/>
    <circle class="logo-red" cx="30" cy="30" r="4.5" fill="#c62828"/>
  </svg>`;

//: The campaign workflow, drawn as one SVG (supplied as spreadex_workflow.svg).
//: Inlined rather than loaded as an <img> so it follows the page font and
//: the light/dark theme; the artwork itself is unchanged apart from a
//: cropped viewBox and prefixed ids. It has no fixed size, so it scales
//: with its container.
const WORKFLOW_SVG = `
<svg class="workflow" xmlns="http://www.w3.org/2000/svg" viewBox="30 55 1345 485" role="img" aria-label="How a SpreadEx campaign runs: a grammar is used to generate inputs, which are checked and analysed; they are then prioritized, executed, observed and classified, and the results are saved and reported.">
<defs>
  <linearGradient id="wf-bg" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#F3EEFF"/><stop offset=".42" stop-color="#F2FBFF"/>
    <stop offset=".72" stop-color="#F2FFF8"/><stop offset="1" stop-color="#EEF9FF"/>
  </linearGradient>
  <filter id="wf-blur"><feGaussianBlur stdDeviation="28"/></filter>
  <filter id="wf-shadow" x="-20%" y="-20%" width="140%" height="140%">
    <feDropShadow dx="0" dy="5" stdDeviation="8" flood-color="#64748B" flood-opacity=".10"/>
  </filter>
  <linearGradient id="wf-g-top" gradientUnits="userSpaceOnUse" x1="275" y1="0" x2="465" y2="0"><stop offset="0" stop-color="#8B5CF6"/><stop offset="1" stop-color="#1687E8"/></linearGradient>
  <linearGradient id="wf-g-ret" gradientUnits="userSpaceOnUse" x1="1180" y1="0" x2="360" y2="0"><stop offset="0" stop-color="#12D7EE"/><stop offset=".55" stop-color="#10DCC0"/><stop offset="1" stop-color="#19D49A"/></linearGradient>
  <linearGradient id="wf-g-pe" gradientUnits="userSpaceOnUse" x1="485" y1="0" x2="535" y2="0"><stop offset="0" stop-color="#F5A524"/><stop offset="1" stop-color="#C99A2E"/></linearGradient>
  <linearGradient id="wf-g-eo" gradientUnits="userSpaceOnUse" x1="695" y1="0" x2="745" y2="0"><stop offset="0" stop-color="#16B65D"/><stop offset="1" stop-color="#2DD4BF"/></linearGradient>
  <linearGradient id="wf-g-oc" gradientUnits="userSpaceOnUse" x1="905" y1="0" x2="955" y2="0"><stop offset="0" stop-color="#3B82F6"/><stop offset="1" stop-color="#7C5CF0"/></linearGradient>
  <linearGradient id="wf-g-cr" gradientUnits="userSpaceOnUse" x1="1115" y1="0" x2="1160" y2="0"><stop offset="0" stop-color="#A78BFA"/><stop offset="1" stop-color="#7C4DE8"/></linearGradient>
  <linearGradient id="wf-g-down" gradientUnits="userSpaceOnUse" x1="0" y1="290" x2="0" y2="388"><stop offset="0" stop-color="#8B5CF6"/><stop offset=".5" stop-color="#EC4899"/><stop offset="1" stop-color="#F43F5E"/></linearGradient>
</defs>

<!-- soft backdrop -->
<path class="wf-backdrop" d="M40 165 C160 15 360 22 490 110 C620 198 725 50 880 74 C1040 99 1050 10 1245 35 C1375 52 1415 182 1365 305 C1310 442 1155 493 1010 455 C840 410 760 562 565 532 C400 507 305 447 160 470 C30 491 -40 377 40 165Z" fill="url(#wf-bg)" opacity=".88"/>
<ellipse cx="505" cy="155" rx="190" ry="90" fill="#CDB7FF" opacity=".16" filter="url(#wf-blur)"/>
<ellipse cx="830" cy="330" rx="250" ry="105" fill="#A8F0E1" opacity=".15" filter="url(#wf-blur)"/>

<!-- connectors -->
<path d="M275 235 H315 Q345 235 345 205 Q345 165 390 165 H456" fill="none" stroke-width="7" stroke-linecap="round" stroke="url(#wf-g-top)"/>
<path d="M627 165 H676" fill="none" stroke-width="7" stroke-linecap="round" stroke="#1687E8"/>
<path d="M847 165 H906" fill="none" stroke-width="7" stroke-linecap="round" stroke="#69747A"/>
<path d="M1075 165 H1130 Q1180 165 1180 215 V240 Q1180 290 1125 290 H360" fill="none" stroke-width="7" stroke-linecap="round" stroke="url(#wf-g-ret)"/>
<path d="M360 290 Q305 290 305 340 V350 Q305 388 318 388" fill="none" stroke-width="7" stroke-linecap="round" stroke="url(#wf-g-down)"/>
<path d="M487 410 H526" fill="none" stroke-width="7" stroke-linecap="round" stroke="url(#wf-g-pe)"/>
<path d="M697 410 H736" fill="none" stroke-width="7" stroke-linecap="round" stroke="url(#wf-g-eo)"/>
<path d="M907 410 H946" fill="none" stroke-width="7" stroke-linecap="round" stroke="url(#wf-g-oc)"/>
<path d="M1117 410 H1151" fill="none" stroke-width="7" stroke-linecap="round" stroke="url(#wf-g-cr)"/>

<!-- arrowheads -->
<path d="M448 152 L462 165 L448 178" fill="none" stroke="#1687E8" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M668 152 L682 165 L668 178" fill="none" stroke="#1687E8" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M898 152 L912 165 L898 178" fill="none" stroke="#69747A" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M308 375 L322 388 L308 401" fill="none" stroke="#F43F5E" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M518 397 L532 410 L518 423" fill="none" stroke="#C99A2E" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M728 397 L742 410 L728 423" fill="none" stroke="#2DD4BF" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M938 397 L952 410 L938 423" fill="none" stroke="#7C5CF0" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M1143 397 L1157 410 L1143 423" fill="none" stroke="#7C4DE8" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>

<!-- nodes -->
<g class="wf-labels" text-anchor="middle" fill="#111827">
  <!-- grammar -->
  <rect class="wf-node" x="65" y="120" width="210" height="235" rx="24" fill="#fff" fill-opacity=".72" stroke="#C9DEFA" stroke-width="2" filter="url(#wf-shadow)"/>
  <g transform="translate(135 150)" stroke="#4898F2" stroke-width="5" fill="none" stroke-linejoin="round">
    <path d="M10 0h48l25 25v72H10z"/><path d="M58 0v25h25"/><path d="M28 48h38M28 65h38M28 82h28"/>
  </g>
  <text x="170" y="294" font-size="26" font-weight="700">Grammar</text>
  <text x="170" y="325" class="wf-sub" font-size="18" fill="#64748B">(built-in or custom)</text>

  <!-- generate -->
  <rect class="wf-node" x="465" y="80" width="160" height="170" rx="22" fill="#FBF8FF" stroke="#E1D6FA" stroke-width="2" filter="url(#wf-shadow)"/>
  <g transform="translate(525 115)" fill="#7D4DE8"><path d="M20 0l6 15 15 6-15 6-6 15-6-15-14-6 14-6z"/><path d="M50 5l4 9 9 4-9 4-4 9-4-9-9-4 9-4z"/><circle cx="51" cy="46" r="5"/></g>
  <text x="545" y="216" font-size="23" font-weight="700">Generate</text>

  <!-- check -->
  <rect class="wf-node" x="685" y="80" width="160" height="170" rx="22" fill="#F7FBFF" stroke="#CBE1FB" stroke-width="2" filter="url(#wf-shadow)"/>
  <g transform="translate(735 112)" fill="none" stroke="#1677EA" stroke-width="5"><path d="M30 0l30 10v25c0 22-14 38-30 47C14 73 0 57 0 35V10z"/><path d="M16 38l10 10 20-24"/></g>
  <text x="765" y="216" font-size="23" font-weight="700">Check</text>

  <!-- analyze -->
  <rect class="wf-node" x="915" y="80" width="160" height="170" rx="22" fill="#FFF9F2" stroke="#F7D7B7" stroke-width="2" filter="url(#wf-shadow)"/>
  <g transform="translate(960 120)" fill="#FF8A1F"><rect x="0" y="32" width="10" height="35" rx="3"/><rect x="18" y="18" width="10" height="49" rx="3"/><rect x="36" y="0" width="10" height="67" rx="3"/><rect x="54" y="26" width="10" height="41" rx="3"/></g>
  <text x="995" y="216" font-size="23" font-weight="700">Analyze</text>

  <!-- prioritize -->
  <rect class="wf-node" x="325" y="345" width="160" height="170" rx="22" fill="#FFF7F8" stroke="#F8CDD4" stroke-width="2" filter="url(#wf-shadow)"/>
  <g transform="translate(370 380)" fill="#FF3E55"><circle cx="6" cy="8" r="5"/><circle cx="6" cy="28" r="5"/><circle cx="6" cy="48" r="5"/><rect x="20" y="3" width="42" height="10" rx="3"/><rect x="20" y="23" width="42" height="10" rx="3"/><rect x="20" y="43" width="42" height="10" rx="3"/></g>
  <text x="405" y="480" font-size="23" font-weight="700">Prioritize</text>

  <!-- execute -->
  <rect class="wf-node" x="535" y="345" width="160" height="170" rx="22" fill="#F5FFF9" stroke="#CBEFDC" stroke-width="2" filter="url(#wf-shadow)"/>
  <path d="M595 380 L595 438 L645 409 Z" fill="none" stroke="#16B65D" stroke-width="5" stroke-linejoin="round"/>
  <text x="615" y="480" font-size="23" font-weight="700">Execute</text>

  <!-- observe -->
  <rect class="wf-node" x="745" y="345" width="160" height="170" rx="22" fill="#F7FBFF" stroke="#CBE1FB" stroke-width="2" filter="url(#wf-shadow)"/>
  <g transform="translate(790 380)" fill="none" stroke="#086CE5" stroke-width="5"><circle cx="26" cy="26" r="22"/><path d="M42 42l25 25"/></g>
  <text x="825" y="480" font-size="23" font-weight="700">Observe</text>

  <!-- classify -->
  <rect class="wf-node" x="955" y="345" width="160" height="170" rx="22" fill="#FBF8FF" stroke="#E3D4FA" stroke-width="2" filter="url(#wf-shadow)"/>
  <path d="M1013 384h36l29 29-45 45-29-29z" fill="#8347E8"/><circle cx="1028" cy="399" r="5" fill="#fff"/>
  <text x="1035" y="480" font-size="23" font-weight="700">Classify</text>

  <!-- report -->
  <rect class="wf-node" x="1160" y="300" width="180" height="215" rx="24" fill="#fff" fill-opacity=".72" stroke="#C9DEFA" stroke-width="2" filter="url(#wf-shadow)"/>
  <g transform="translate(1212 335)" stroke="#4898F2" stroke-width="5" fill="none" stroke-linejoin="round">
    <path d="M8 0h45l24 24v78H8z"/><path d="M53 0v24h24"/><path d="M25 80V62M40 80V48M55 80V57"/>
  </g>
  <text x="1250" y="480" font-size="23" font-weight="700">Save &amp; Report</text>
</g>

<!-- dots -->
<g class="wf-dots" stroke="#fff" stroke-width="3"><circle cx="575" cy="290" r="9" fill="#34D399"/><circle cx="760" cy="290" r="9" fill="#2DD4BF"/><circle cx="945" cy="290" r="9" fill="#22D3EE"/><circle cx="1115" cy="290" r="9" fill="#22D3EE"/><circle cx="1180" cy="240" r="9" fill="#22D3EE"/></g>
</svg>`;

// Lucide (ISC) icon bodies, vendored so the Workbench never fetches from a CDN.
// Outline, 2px stroke, round caps and joins; keep to this one set. Semantic use:
// CircleCheck success, TriangleAlert warning, CircleX error, Info information.
const ICONS = {
  terminal: I(`<path d="m7 11 2-2-2-2" /> <path d="M11 13h4" /> <rect width="18" height="18" x="3" y="3" rx="2" ry="2" />`),
  doc: I(`<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z" /> <path d="M14 2v5a1 1 0 0 0 1 1h5" /> <path d="M10 9H8" /> <path d="M16 13H8" /> <path d="M16 17H8" />`),
  shield: I(`<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z" />`),
  playOutline: I(`<path d="M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z" />`),
  home: I(`<path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8" /> <path d="M3 10a2 2 0 0 1 .709-1.528l7-6a2 2 0 0 1 2.582 0l7 6A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />`),
  folder: I(`<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" />`),
  sliders: I(`<path d="M10 5H3" /> <path d="M12 19H3" /> <path d="M14 3v4" /> <path d="M16 17v4" /> <path d="M21 12h-9" /> <path d="M21 19h-5" /> <path d="M21 5h-7" /> <path d="M8 10v4" /> <path d="M8 12H3" />`),
  gear: I(`<path d="M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34 0 0 1 2.33 4.033 2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 1.915 2.34 2.34 0 0 1-4.659 0 2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319-1.915" /> <circle cx="12" cy="12" r="3" />`),
  book: I(`<path d="M12 5v16" /> <path d="M20.001 19A2 2 0 0022 17V5a2 2 0 00-1.999-2L16 3.002A5 5 0 0012 5a5 5 0 00-4-2H4a2 2 0 00-2 2v12a2 2 0 001.999 2H8a5 5 0 014 2 5 5 0 014-2z" />`),
  arrow: I(`<path d="M5 12h14" /> <path d="m12 5 7 7-7 7" />`),
  chart: I(`<path d="M3 3v16a2 2 0 0 0 2 2h16" /> <path d="M18 17V9" /> <path d="M13 17V5" /> <path d="M8 17v-3" />`),
  check: I(`<path d="M20 6 9 17l-5-5" />`),
  alert: I(`<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3" /> <path d="M12 9v4" /> <path d="M12 17h.01" />`),
  // Lucide monitor-play and file-plus: the Quick demo card and its Start fresh action.
  demoScreen: I(`<path d="M10 7.75a.75.75 0 0 1 1.142-.638l3.664 2.249a.75.75 0 0 1 0 1.278l-3.664 2.25a.75.75 0 0 1-1.142-.64z" /> <path d="M12 17v4" /> <path d="M8 21h8" /> <rect x="2" y="3" width="20" height="14" rx="2" />`),
  filePlus: I(`<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z" /> <path d="M14 2v5a1 1 0 0 0 1 1h5" /> <path d="M9 15h6" /> <path d="M12 18v-6" />`),
  copy: I(`<rect width="14" height="14" x="8" y="8" rx="2" ry="2" /> <path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" />`),
  success: I(`<circle cx="12" cy="12" r="10" /> <path d="m16 9-5.5 5.5L8 12" />`),
  error: I(`<circle cx="12" cy="12" r="10" /> <path d="m15 9-6 6" /> <path d="m9 9 6 6" />`),
  help: I(`<circle cx="12" cy="12" r="10" /> <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" /> <path d="M12 17h.01" />`),
  bulb: I(`<path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5" /> <path d="M9 18h6" /> <path d="M10 22h4" />`),
  example: I(`<path d="M4 12.15V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.706.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2h-3.35" /> <path d="M14 2v5a1 1 0 0 0 1 1h5" /> <path d="m5 16-3 3 3 3" /> <path d="m9 22 3-3-3-3" />`),
  upload: I(`<path d="M12 3v12" /> <path d="m17 8-5-5-5 5" /> <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />`),
  import: I(`<circle cx="18" cy="5" r="3" /> <circle cx="6" cy="12" r="3" /> <circle cx="18" cy="19" r="3" /> <line x1="8.59" x2="15.42" y1="13.51" y2="17.49" /> <line x1="15.41" x2="8.59" y1="6.51" y2="10.49" />`),
  back: I(`<path d="m12 19-7-7 7-7" /> <path d="M19 12H5" />`),
  database: I(`<ellipse cx="12" cy="5" rx="9" ry="3" /> <path d="M3 5V19A9 3 0 0 0 21 19V5" /> <path d="M3 12A9 3 0 0 0 21 12" />`),
  braces: I(`<path d="M8 3H7a2 2 0 0 0-2 2v5a2 2 0 0 1-2 2 2 2 0 0 1 2 2v5c0 1.1.9 2 2 2h1" /> <path d="M16 21h1a2 2 0 0 0 2-2v-5c0-1.1.9-2 2-2a2 2 0 0 1-2-2V5a2 2 0 0 0-2-2h-1" />`),
  dots: I(`<circle cx="12" cy="12" r="1" /> <circle cx="19" cy="12" r="1" /> <circle cx="5" cy="12" r="1" />`),
  calc: I(`<rect width="16" height="20" x="4" y="2" rx="2" /> <line x1="8" x2="16" y1="6" y2="6" /> <line x1="16" x2="16" y1="14" y2="18" /> <path d="M16 10h.01" /> <path d="M12 10h.01" /> <path d="M8 10h.01" /> <path d="M12 14h.01" /> <path d="M8 14h.01" /> <path d="M12 18h.01" /> <path d="M8 18h.01" />`),
  chevron: I(`<path d="m6 9 6 6 6-6" />`),
  scale: I(`<path d="M12 3v18" /> <path d="m19 8 3 8a5 5 0 0 1-6 0zV7" /> <path d="M3 7h1a17 17 0 0 0 8-2 17 17 0 0 0 8 2h1" /> <path d="m5 8 3 8a5 5 0 0 1-6 0zV7" /> <path d="M7 21h10" />`),
  grid: I(`<rect width="7" height="7" x="3" y="3" rx="1" /> <rect width="7" height="7" x="14" y="3" rx="1" /> <rect width="7" height="7" x="14" y="14" rx="1" /> <rect width="7" height="7" x="3" y="14" rx="1" />`),
};

// Reserve from the SpreadEx icon system: approved glyphs not on screen yet. They live here,
// outside ICONS, so the guard against dead icons still protects the set in use.
const ICON_RESERVE = {
  info: I(`<circle cx="12" cy="12" r="10" /> <path d="M12 16v-4" /> <path d="M12 8h.01" />`),
  external: I(`<path d="M15 3h6v6" /> <path d="M10 14 21 3" /> <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />`),
  rerun: I(`<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" /> <path d="M21 3v5h-5" /> <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" /> <path d="M8 16H3v5" />`),
  stop: I(`<rect width="18" height="18" x="3" y="3" rx="2" />`),
  folderOpen: I(`<path d="m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2" />`),
  file: I(`<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z" /> <path d="M14 2v5a1 1 0 0 0 1 1h5" />`),
  code: I(`<path d="m18 16 4-4-4-4" /> <path d="m6 8-4 4 4 4" /> <path d="m14.5 4-5 16" />`),
  trash: I(`<path d="M10 11v6" /> <path d="M14 11v6" /> <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" /> <path d="M3 6h18" /> <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />`),
  edit: I(`<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z" /> <path d="m15 5 4 4" />`),
  search: I(`<path d="m21 21-4.34-4.34" /> <circle cx="11" cy="11" r="8" />`),
  download: I(`<path d="M12 15V3" /> <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /> <path d="m7 10 5 5 5-5" />`),
  clock: I(`<circle cx="12" cy="12" r="10" /> <path d="M12 6v6l4 2" />`),
  cpu: I(`<path d="M12 20v2" /> <path d="M12 2v2" /> <path d="M17 20v2" /> <path d="M17 2v2" /> <path d="M2 12h2" /> <path d="M2 17h2" /> <path d="M2 7h2" /> <path d="M20 12h2" /> <path d="M20 17h2" /> <path d="M20 7h2" /> <path d="M7 20v2" /> <path d="M7 2v2" /> <rect x="4" y="4" width="16" height="16" rx="2" /> <rect x="8" y="8" width="8" height="8" rx="1" />`),
  stdin: I(`<path d="m10 17 5-5-5-5" /> <path d="M15 12H3" /> <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" />`),
  bug: I(`<path d="M12 20v-9" /> <path d="M14 7a4 4 0 0 1 4 4v3a6 6 0 0 1-12 0v-3a4 4 0 0 1 4-4z" /> <path d="M14.12 3.88 16 2" /> <path d="M21 21a4 4 0 0 0-3.81-4" /> <path d="M21 5a4 4 0 0 1-3.55 3.97" /> <path d="M22 13h-4" /> <path d="M3 21a4 4 0 0 1 3.81-4" /> <path d="M3 5a4 4 0 0 0 3.55 3.97" /> <path d="M6 13H2" /> <path d="m8 2 1.88 1.88" /> <path d="M9 7.13V6a3 3 0 1 1 6 0v1.13" />`),
  coverage: I(`<path d="M3 3v16a2 2 0 0 0 2 2h16" /> <path d="m19 9-5 5-4-4-3 3" />`),
  stats: I(`<path d="M21 12c.552 0 1.005-.449.95-.998a10 10 0 0 0-8.953-8.951c-.55-.055-.998.398-.998.95v8a1 1 0 0 0 1 1z" /> <path d="M21.21 15.89A10 10 0 1 1 8 2.83" />`),
  table: I(`<path d="M12 3v18" /> <rect width="18" height="18" x="3" y="3" rx="2" /> <path d="M3 9h18" /> <path d="M3 15h18" />`),
  plus: I(`<path d="M5 12h14" /> <path d="M12 5v14" />`),
  minus: I(`<path d="M5 12h14" />`),
  expand: I(`<path d="m6 9 6 6 6-6" />`),
  collapse: I(`<path d="m18 15-6-6-6 6" />`),
};
Object.assign(ICONS, ICON_RESERVE);

// Brand marks (Simple Icons, CC0) for runtimes that Lucide deliberately has no glyphs for.
// Coloured, not currentColor: a brand mark is the one place colour carries identity.
const BRANDS = {
  java: `<svg class="ico brand" viewBox="0 0 24 24" fill="#ED8B00" aria-hidden="true" focusable="false"><path d="M11.915 0 11.7.215C9.515 2.4 7.47 6.39 6.046 10.483c-1.064 1.024-3.633 2.81-3.711 3.551-.093.87 1.746 2.611 1.55 3.235-.198.625-1.304 1.408-1.014 1.939.1.188.823.011 1.277-.491a13.389 13.389 0 0 0-.017 2.14c.076.906.27 1.668.643 2.232.372.563.956.911 1.667.911.397 0 .727-.114 1.024-.264.298-.149.571-.33.91-.5.68-.34 1.634-.666 3.53-.604 1.903.062 2.872.39 3.559.704.687.314 1.15.664 1.925.664.767 0 1.395-.336 1.807-.9.412-.563.631-1.33.72-2.24.06-.623.055-1.32 0-2.066.454.45 1.117.604 1.213.424.29-.53-.816-1.314-1.013-1.937-.198-.624 1.642-2.366 1.549-3.236-.08-.748-2.707-2.568-3.748-3.586C16.428 6.374 14.308 2.394 12.13.215zm.175 6.038a2.95 2.95 0 0 1 2.943 2.942 2.95 2.95 0 0 1-2.943 2.943A2.95 2.95 0 0 1 9.148 8.98a2.95 2.95 0 0 1 2.942-2.942zM8.685 7.983a3.515 3.515 0 0 0-.145.997c0 1.951 1.6 3.55 3.55 3.55 1.95 0 3.55-1.598 3.55-3.55 0-.329-.046-.648-.132-.951.334.095.64.208.915.336a42.699 42.699 0 0 1 2.042 5.829c.678 2.545 1.01 4.92.846 6.607-.082.844-.29 1.51-.606 1.94-.315.431-.713.651-1.315.651-.593 0-.932-.27-1.673-.61-.741-.338-1.825-.694-3.792-.758-1.974-.064-3.073.293-3.821.669-.375.188-.659.373-.911.5s-.466.2-.752.2c-.53 0-.876-.209-1.16-.64-.285-.43-.474-1.101-.545-1.948-.141-1.693.176-4.069.823-6.614a43.155 43.155 0 0 1 1.934-5.783c.348-.167.749-.31 1.192-.425zm-3.382 4.362a.216.216 0 0 1 .13.031c-.166.56-.323 1.116-.463 1.665a33.849 33.849 0 0 0-.547 2.555 3.9 3.9 0 0 0-.2-.39c-.58-1.012-.914-1.642-1.16-2.08.315-.24 1.679-1.755 2.24-1.781zm13.394.01c.562.027 1.926 1.543 2.24 1.783-.246.438-.58 1.068-1.16 2.08a4.428 4.428 0 0 0-.163.309 32.354 32.354 0 0 0-.562-2.49 40.579 40.579 0 0 0-.482-1.652.216.216 0 0 1 .127-.03z"/></svg>`,
  python: `<svg class="ico brand" viewBox="0 0 24 24" fill="#3776AB" aria-hidden="true" focusable="false"><path d="M14.25.18l.9.2.73.26.59.3.45.32.34.34.25.34.16.33.1.3.04.26.02.2-.01.13V8.5l-.05.63-.13.55-.21.46-.26.38-.3.31-.33.25-.35.19-.35.14-.33.1-.3.07-.26.04-.21.02H8.77l-.69.05-.59.14-.5.22-.41.27-.33.32-.27.35-.2.36-.15.37-.1.35-.07.32-.04.27-.02.21v3.06H3.17l-.21-.03-.28-.07-.32-.12-.35-.18-.36-.26-.36-.36-.35-.46-.32-.59-.28-.73-.21-.88-.14-1.05-.05-1.23.06-1.22.16-1.04.24-.87.32-.71.36-.57.4-.44.42-.33.42-.24.4-.16.36-.1.32-.05.24-.01h.16l.06.01h8.16v-.83H6.18l-.01-2.75-.02-.37.05-.34.11-.31.17-.28.25-.26.31-.23.38-.2.44-.18.51-.15.58-.12.64-.1.71-.06.77-.04.84-.02 1.27.05zm-6.3 1.98l-.23.33-.08.41.08.41.23.34.33.22.41.09.41-.09.33-.22.23-.34.08-.41-.08-.41-.23-.33-.33-.22-.41-.09-.41.09zm13.09 3.95l.28.06.32.12.35.18.36.27.36.35.35.47.32.59.28.73.21.88.14 1.04.05 1.23-.06 1.23-.16 1.04-.24.86-.32.71-.36.57-.4.45-.42.33-.42.24-.4.16-.36.09-.32.05-.24.02-.16-.01h-8.22v.82h5.84l.01 2.76.02.36-.05.34-.11.31-.17.29-.25.25-.31.24-.38.2-.44.17-.51.15-.58.13-.64.09-.71.07-.77.04-.84.01-1.27-.04-1.07-.14-.9-.2-.73-.25-.59-.3-.45-.33-.34-.34-.25-.34-.16-.33-.1-.3-.04-.25-.02-.2.01-.13v-5.34l.05-.64.13-.54.21-.46.26-.38.3-.32.33-.24.35-.2.35-.14.33-.1.3-.06.26-.04.21-.02.13-.01h5.84l.69-.05.59-.14.5-.21.41-.28.33-.32.27-.35.2-.36.15-.36.1-.35.07-.32.04-.28.02-.21V6.07h2.09l.14.01zm-6.47 14.25l-.23.33-.08.41.08.41.23.33.33.23.41.08.41-.08.33-.23.23-.33.08-.41-.08-.41-.23-.33-.33-.23-.41-.08-.41.08z"/></svg>`,
  node: `<svg class="ico brand" viewBox="0 0 24 24" fill="#339933" aria-hidden="true" focusable="false"><path d="M11.998,24c-0.321,0-0.641-0.084-0.922-0.247l-2.936-1.737c-0.438-0.245-0.224-0.332-0.08-0.383 c0.585-0.203,0.703-0.25,1.328-0.604c0.065-0.037,0.151-0.023,0.218,0.017l2.256,1.339c0.082,0.045,0.197,0.045,0.272,0l8.795-5.076 c0.082-0.047,0.134-0.141,0.134-0.238V6.921c0-0.099-0.053-0.192-0.137-0.242l-8.791-5.072c-0.081-0.047-0.189-0.047-0.271,0 L3.075,6.68C2.99,6.729,2.936,6.825,2.936,6.921v10.15c0,0.097,0.054,0.189,0.139,0.235l2.409,1.392 c1.307,0.654,2.108-0.116,2.108-0.89V7.787c0-0.142,0.114-0.253,0.256-0.253h1.115c0.139,0,0.255,0.112,0.255,0.253v10.021 c0,1.745-0.95,2.745-2.604,2.745c-0.508,0-0.909,0-2.026-0.551L2.28,18.675c-0.57-0.329-0.922-0.945-0.922-1.604V6.921 c0-0.659,0.353-1.275,0.922-1.603l8.795-5.082c0.557-0.315,1.296-0.315,1.848,0l8.794,5.082c0.57,0.329,0.924,0.944,0.924,1.603 v10.15c0,0.659-0.354,1.273-0.924,1.604l-8.794,5.078C12.643,23.916,12.324,24,11.998,24z M19.099,13.993 c0-1.9-1.284-2.406-3.987-2.763c-2.731-0.361-3.009-0.548-3.009-1.187c0-0.528,0.235-1.233,2.258-1.233 c1.807,0,2.473,0.389,2.747,1.607c0.024,0.115,0.129,0.199,0.247,0.199h1.141c0.071,0,0.138-0.031,0.186-0.081 c0.048-0.054,0.074-0.123,0.067-0.196c-0.177-2.098-1.571-3.076-4.388-3.076c-2.508,0-4.004,1.058-4.004,2.833 c0,1.925,1.488,2.457,3.895,2.695c2.88,0.282,3.103,0.703,3.103,1.269c0,0.983-0.789,1.402-2.642,1.402 c-2.327,0-2.839-0.584-3.011-1.742c-0.02-0.124-0.126-0.215-0.253-0.215h-1.137c-0.141,0-0.254,0.112-0.254,0.253 c0,1.482,0.806,3.248,4.655,3.248C17.501,17.007,19.099,15.91,19.099,13.993z"/></svg>`,
};

// ------------------------------------------------------------- navigation

function paintNavIcons() {
  document.querySelectorAll("[data-icon]").forEach(node => {
    if (node.dataset.painted) return;
    const svg = ICONS[node.dataset.icon];
    if (!svg) return;
    node.insertAdjacentHTML("afterbegin", svg);
    node.dataset.painted = "1";
  });
}

function go(tab) {
  // Leaving the wizard retires any step still loading, so it cannot draw over the new page.
  if (tab !== "setup") RENDER++;
  S.tab = tab;
  paintNavIcons();
  el("tab-home").setAttribute("aria-selected", tab === "landing");
  el("tab-setup").setAttribute("aria-selected", tab === "setup");
  el("tab-results").setAttribute("aria-selected", tab === "results");
  el("steps").style.display = tab === "setup" ? "" : "none";
  // The Campaigns menu opens the list, except while one is running: then it is that one.
  if (tab === "results" && S.rview !== "live" && S.rview !== "run") S.rview = S.live?.active ? "live" : "list";
  if (tab === "setup" && !stepReachable(S.step)) { S.step = firstOpenStep(); renderSteps(); }
  saveView();
  if (tab === "landing") { renderLanding(); paintDemoCard(); }
  else tab === "setup" ? renderStep() : renderResults();
}
// A step is reachable when every step before it is complete; an unreachable one sends you to the
// first step that still needs doing. Moving back, or among completed steps, is always allowed.
function gotoStep(id) {
  S.step = stepReachable(id) ? id : firstOpenStep();
  saveView(); renderSteps(); renderStep();
}

function renderLanding() {
  const readOnly = Boolean(S.project?.read_only);

  // Two layers of copy on purpose. The face of each card says WHAT in a short
  // line; the (i) says HOW, in a sentence or two. Every claim here is something
  // the tool does today -- an earlier version promised "coverage, mutation
  // score" (that is the research repository, not this tool) and "a built-in
  // system" (there is no picker; there is the bundled demo).
  const STEPS = [
    { n: 1, tone: "green",  icon: ICONS.folder,  title: "Choose a subject",
      body: "Add your own system, or try the bundled demo.",
      tip: "Give SpreadEx the command that runs your system on one input file. " +
           "No system handy? Run <code>spreadex demo</code> for a bundled one." },
    { n: 2, tone: "blue",   icon: ICONS.sliders, title: "Configure generators",
      body: "Pick generators and set parameters.",
      tip: "Choose which generators write inputs from your grammar, compare them on equal " +
           "time or equal count, and say what counts as a failure." },
    { n: 3, tone: "orange", icon: ICONS.gear,    title: "Run campaign",
      body: "Generate, execute and collect results.",
      tip: "SpreadEx generates inputs, runs the most different ones first, executes as " +
           "many as the budget allows, and records every outcome." },
    { n: 4, tone: "purple", icon: ICONS.chart,   title: "Explore results",
      body: "Analyze and export reports.",
      tip: "See what failed and why, how the generators compared, and whether the ordering " +
           "beat random. Export a campaign as a zip to reproduce it." },
  ];
  const card = c => `<div class="start-card ${c.tone}-card">
      <div class="sc-top">
        <span class="sc-num">${c.n}</span>
        <span class="start-icon">${c.icon}</span>
      </div>
      <button type="button" class="sc-info" aria-label="More about: ${c.title}"
              aria-describedby="tip-${c.n}" aria-expanded="false"
              onclick="toggleTip(event, this)">${ICONS.help}</button>
      <span class="sc-tip" role="tooltip" id="tip-${c.n}">${c.tip}</span>
      <h3 class="sc-title">${c.title}</h3>
      <p>${c.body}</p>
    </div>`;

  el("view").innerHTML = `
    <section class="landing dashboard-home" aria-labelledby="landing-title">
      <div class="landing-hero">
        <div class="landing-intro">
          <div class="hero-title-row">
            ${BRAND_MARK}
            <h1 id="landing-title"><span class="t1">SpreadEx</span> <span class="t2">Workbench</span></h1>
          </div>
          <p class="landing-lede">Generate, prioritize, and run tests for compilers, interpreters, parsers,
            and other program-processing systems — all locally.</p>
          <div class="hero-actions">
            <button class="hero-action primary landing-primary" onclick="go('setup')"
                    ${readOnly ? "disabled" : ""}>
              <span class="ha-icon">${ICONS.playOutline}</span>
              <span class="ha-text"><strong>Set up my system</strong>
                <small>Guides you step by step</small></span>
              <span class="ha-end">${ICONS.arrow}</span>
            </button>
            <button class="hero-action quick-demo" onclick="startDemo(false)" ${readOnly ? "disabled" : ""}>
              <span class="ha-icon qd-icon">${ICONS.demoScreen}</span>
              <span class="ha-text"><strong>Quick demo <span class="qd-badge">~20s</span></strong>
                <small>Run a real campaign and see the results</small>
                <small class="qd-meta">No setup · Runs locally</small></span>
              <span class="ha-end">${ICONS.arrow}</span>
            </button>
          </div>
          ${readOnly ? `<p class="landing-readonly">This Workbench is read-only. Open it without
            <code>--read-only</code> to configure a project or run campaigns.</p>` : ""}
          <div id="demo-hint"></div>
        </div>

        <figure class="workflow-figure" tabindex="0" role="group" aria-label="Campaign workflow diagram">${WORKFLOW_SVG}</figure>
      </div>

      <div class="landing-divider"></div>

      <section class="get-started" aria-labelledby="get-started-title">
        <div class="section-heading">
          <div>
            <h2 id="get-started-title">Get started</h2>
            <p>Set up a subject, choose generators, and run your first testing campaign.</p>
          </div>
          <button class="link-arrow" onclick="go('setup')">View documentation ${ICONS.arrow}</button>
        </div>
        <div class="start-cards">
          ${STEPS.map(card).join(`<span class="card-arrow">${ICONS.arrow}</span>`)}
        </div>
      </section>
    </section>`;
}

// ----------------------------------------------------------- card tooltips
// Hover and keyboard focus show a tooltip through CSS alone. A tap does not
// focus a button in Safari, so touch (and a deliberate click) toggles a class
// instead; Escape or any outside click closes it.
//
// Escape must also hide a tooltip that hover or focus is holding open, even
// though the pointer has not moved (WCAG 1.4.13: content shown on hover must be
// dismissible without moving the pointer). That is what `tip-dismissed` is: it
// overrides hover and focus until the pointer or focus arrives afresh.
function closeTips() {
  document.querySelectorAll(".start-card.tip-open").forEach(card => {
    card.classList.remove("tip-open");
    card.querySelector(".sc-info")?.setAttribute("aria-expanded", "false");
  });
}
function dismissTips() {
  document.querySelectorAll(".start-card").forEach(card => {
    const tip = card.querySelector(".sc-tip");
    if (tip && getComputedStyle(tip).visibility === "visible") card.classList.add("tip-dismissed");
  });
  closeTips();
}
function toggleTip(event, button) {
  event.stopPropagation();                  // or the document handler closes it at once
  const card = button.closest(".start-card");
  const opening = !card.classList.contains("tip-open");
  closeTips();
  if (opening) {
    card.classList.remove("tip-dismissed");
    card.classList.add("tip-open");
    button.setAttribute("aria-expanded", "true");
  }
}
document.addEventListener("click", closeTips);
document.addEventListener("keydown", e => { if (e.key === "Escape") dismissTips(); });
// "Afresh" = the pointer coming in from outside the button, or focus landing on it.
document.addEventListener("pointerover", e => {
  const button = e.target.closest?.(".sc-info");
  if (button && !button.contains(e.relatedTarget)) {
    button.closest(".start-card").classList.remove("tip-dismissed");
  }
});
document.addEventListener("focusin", e => {
  e.target.closest?.(".sc-info")?.closest(".start-card").classList.remove("tip-dismissed");
});

// ---- opening the demo (Home)

async function startDemo(reset) {
  if (S.project?.demo && !reset) { go("setup"); return tourStart(); }
  const msg = el("demo-hint");
  if (msg) msg.innerHTML = `<div class="note" role="status">Preparing the demo&hellip;</div>`;
  try {
    const r = await api("/api/demo/open", { reset: !!reset });
    if (r.ok === false) throw new Error(r.error);
    try { sessionStorage.removeItem(TOUR_KEY); } catch (e) { /* blocked storage */ }
    location.href = r.url;
  } catch (e) { if (msg) msg.innerHTML = `<div class="note bad" role="alert">${esc(e.message || e)}</div>`; }
}
function demoFresh() {
  if (!confirm("Start the demo over? Its campaigns are deleted and its files restored. Your own project is not touched.")) return;
  startDemo(true);
}
async function paintDemoCard() {
  const holder = el("demo-hint"); if (!holder) return;
  let st = null;
  try { st = await api("/api/demo"); } catch (e) { /* the button still works */ }
  S.demo = st;
  const again = st && (st.exists && (st.has_runs || st.is_demo));
  holder.innerHTML = `${again ? `<div class="demo-again">
      <button type="button" class="demo-btn continue" onclick="startDemo(false)">${ICONS.playOutline}<span>Continue demo</span></button>
      <button type="button" class="demo-btn" onclick="demoFresh()">${ICONS.filePlus}<span>Start fresh</span></button></div>` : ""}`;
}


// A step shows its check only when it comes before the one you are on AND the thing it asks for
// exists -- so jumping ahead with an empty step 1 does not paint it as done.
function stepDone(id) {
  const c = cfg();
  if (id === "sut") return targets().some(t => (t.command || []).length) && S.verifiedSut === sutKey(c.sut);
  if (id === "grammar") return !!(c.grammar?.source || c.corpus?.path) && S.confirmed.has(id);
  if (id === "generators") return !!((c.generators || []).length || c.corpus?.path) && S.confirmed.has(id);
  if (id === "strategy") return !!c.oracle && S.confirmed.has(id);
  return false;
}
function stepReachable(id) {
  const i = STEPS.findIndex(x => x.id === id);
  return i >= 0 && STEPS.slice(0, i).every(x => stepDone(x.id));
}
function firstOpenStep() { return (STEPS.find(x => !stepDone(x.id)) || STEPS[STEPS.length - 1]).id; }
// What Test connection checked. Changing any of it means the command has to be tested again.
function sutKey(sut) {
  const s = sut || {}, t = (s.targets || [])[0] || s;
  return JSON.stringify([t.command || [], t.cwd || "", t.env || {}, s.input_mode || "file"]);
}

function renderSteps() {
  const host = el("steps");
  // The row is rebuilt on every step change, which would snap a scrolled row
  // back to the start; carry its position across.
  const before = host.querySelector(".steps-row")?.scrollLeft || 0;
  const cur = STEPS.findIndex(s => s.id === S.step);
  const done = STEPS.map((s, i) => i < cur && stepDone(s.id));

  host.innerHTML = `<ol class="steps-row">${STEPS.map((s, i) => `
    <li class="step-item tone-${s.tone} ${done[i] ? "done" : ""}">
      <button type="button" class="step" onclick="gotoStep('${s.id}')"
              ${s.id === S.step ? 'aria-current="step"' : ""}
              ${stepReachable(s.id) ? "" : `disabled title="Finish the steps before this one first"`}>
        <span class="n">${s.n}</span>
        <span class="step-ico">${ICONS[s.icon]}</span>
        <span class="step-text"><span class="t">${esc(s.t)}${done[i]
          ? `<span class="step-ok">${ICONS.check}<span class="visually-hidden">completed</span></span>` : ""}</span>
          <span class="d">${esc(s.d)}</span></span>
      </button>${i < STEPS.length - 1 ? `<span class="step-link ${done[i] ? "on" : ""}" aria-hidden="true"></span>` : ""}
    </li>`).join("")}</ol>`;

  const row = host.querySelector(".steps-row");
  row.scrollLeft = before;
  centreCurrentStep();
}

// When the row is too narrow to show all five it scrolls; keep the current step
// in view rather than leaving it off to one side. Also run when the window
// changes width -- a rotated phone, a resized window -- because the step has not
// changed but where it sits has.
function centreCurrentStep() {
  const row = document.querySelector("#steps .steps-row");
  const current = row?.querySelector('[aria-current="step"]');
  if (!current || row.scrollWidth <= row.clientWidth) return;
  // Smooth scrolling is driven by animation frames, which a hidden tab does not
  // run: the scroll would silently never happen. Nobody can see an animation in
  // a hidden tab anyway, so there it just lands.
  const smooth = !document.hidden && matchMedia("(prefers-reduced-motion: no-preference)").matches;
  row.scrollTo({ left: current.offsetLeft - (row.clientWidth - current.offsetWidth) / 2,
                 behavior: smooth ? "smooth" : "auto" });
}
let resizeTimer;
addEventListener("resize", () => {
  clearTimeout(resizeTimer);                // a drag fires dozens; act once it settles
  resizeTimer = setTimeout(centreCurrentStep, 120);
});

// ---- command line helpers (pure: the tests run this region under Node) -----
//
// A command is stored as an argv list and shown as one editable string, so it
// has to survive the round trip. The wizard used to split on whitespace, which
// made a path with a space -- the usual case on macOS -- impossible to enter.

// POSIX-flavoured, deliberately small: single quotes are literal, double quotes
// allow \" and \\ , and a backslash outside quotes only escapes whitespace, a
// quote or another backslash (so a Windows-style path is not mangled).
function splitCommand(text) {
  const argv = [];
  let cur = "", started = false, quote = null;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quote) {
      if (ch === quote) quote = null;
      else if (quote === '"' && ch === "\\" && '"\\$`'.includes(text[i + 1] ?? "")) cur += text[++i];
      else cur += ch;
    } else if (ch === '"' || ch === "'") { quote = ch; started = true; }
    else if (/\s/.test(ch)) { if (started || cur) { argv.push(cur); cur = ""; started = false; } }
    else if (ch === "\\" && /[\s"'\\]/.test(text[i + 1] ?? "")) { cur += text[++i]; started = true; }
    else { cur += ch; started = true; }
  }
  if (quote) return { argv, error: `a ${quote === '"' ? "double" : "single"} quote is never closed` };
  if (started || cur) argv.push(cur);
  return { argv, error: null };
}

function joinCommand(argv) {
  return (argv || []).map(a => {
    a = String(a);
    return a !== "" && !/[\s"'\\]/.test(a) ? a : '"' + a.replace(/(["\\])/g, "\\$1") + '"';
  }).join(" ");
}

// NAME=value per line; blank lines and # comments are ignored.
function parseEnv(text) {
  const env = {};
  const lines = String(text || "").split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    const key = eq > 0 ? line.slice(0, eq).trim() : "";
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) {
      return { env: null, error: `line ${i + 1}: expected NAME=value (NAME may use letters, digits and _)` };
    }
    env[key] = line.slice(eq + 1).trim();
  }
  return { env, error: null };
}

function envToText(env) {
  return Object.entries(env || {}).map(([k, v]) => `${k}=${v}`).join("\n");
}

const INTERPRETERS = new Set(["python", "python3", "node", "nodejs", "ruby", "perl", "php",
                              "bash", "sh", "deno", "bun", "lua", "rscript"]);
function inferKind(argv) {
  const exe = (argv || [])[0];
  if (!exe) return "cli";
  if (exe === "java") return "jar";
  if (INTERPRETERS.has(exe.split("/").pop())) return "script";
  return /^(\.{1,2}\/|\/)/.test(exe) ? "cli" : "other";
}

// What a generator can do with the semantic input the user supplied in step 2. Pure and
// deterministic -- no model, no guess -- so the same inputs always give the same sentence.
// `g` is a catalog row ({id, name, constraints}); `sem` is the saved semantics block.
// What each selected generator will do with the user's constraints, said plainly on its card.
// Nothing is converted behind the user's back: a generator reads its own constraint format, or
// runs from the grammar alone.
const NATIVE_FORMAT = { fandango: ["Fandango", ".fan"], isla: ["ISLa", ".isla"] };
function semanticLine(g, sem, experimental) {
  const native = (sem && sem.native) || {};
  const hasGuidance = !!(sem && sem.guidance && sem.guidance.length);
  const hasStructured = !!(sem && sem.structured);
  const others = Object.keys(native).filter(id => id !== g.id);
  const label = id => (NATIVE_FORMAT[id] || [id[0].toUpperCase() + id.slice(1)])[0];
  if (!hasGuidance && !hasStructured && !Object.keys(native).length) return null;
  if (native[g.id]) return { tone: "ok", text: `\u2713 ${g.name} constraints provided (${native[g.id]}), used as written.${hasGuidance ? " Your written guidance is not used by it." : ""}` };
  // A generator without constraint support is not an error, whatever was supplied for others.
  if (!g.constraints) return { tone: "muted", text: `${g.name} has no constraint support, so it runs from the grammar alone.` };
  const parts = [];
  if (others.length) parts.push(`You supplied ${others.map(label).join(" and ")}-specific constraints; ${g.name} cannot use them.`);
  const [name, ext] = NATIVE_FORMAT[g.id] || [g.name, "constraints file"];
  if (hasGuidance) parts.push(`Your rule is in plain language, which is not consumed directly by ${name}. Recommended: provide a ${name} constraints file (${ext}) on the Inputs step.` +
    (experimental ? " Or draft one from your rule with the experimental assistant (Add constraints), then review it."
                  : " Drafting one from your rule needs spreadex ui --experimental."));
  if (hasStructured) parts.push("Structured constraints are stored but not interpreted yet.");
  return { tone: others.length ? "warn" : "muted", text: parts.join(" ") };
}

// ---- testing strategy (pure: the tests run this under Node too) ---------------

function parseExitCodes(text) {
  return String(text || "").split(/[,\s]+/).filter(Boolean).map(x => Number(x))
    .filter(n => Number.isInteger(n));
}
// Blank entries go; the rest are kept EXACTLY as typed. A pattern like "^js: " has a trailing space
// that matters, so trimming it would quietly change what it matches.
const cleanPatterns = list => (list || []).map(p => String(p)).filter(p => p.trim() !== "");

// The oracle block that a set of switches means. Other keys the user wrote by hand (banners,
// compare_stdout) pass through untouched; a switch that is off removes its own keys so nothing stale
// is saved.
function strategyOracle(base, st, multi) {
  const o = { ...(base || {}) };
  o.type = st.diff && multi ? "differential" : "crash";
  const rej = cleanPatterns(st.rejPats), sig = cleanPatterns(st.sigPats), codes = parseExitCodes(st.codes);
  if (st.rej && rej.length) o.rejection_patterns = rej; else delete o.rejection_patterns;
  if (st.rej && codes.length) o.expected_exit_codes = codes; else delete o.expected_exit_codes;
  if (st.sig && sig.length) o.crash_patterns = sig; else delete o.crash_patterns;
  return o;
}

// Starting points, not answers: patterns are what many systems print, never what YOUR system prints.
const STRATEGY_PRESETS = {
  parser:      { t: "Compiler / Parser", d: "Crashes, timeouts, rejections, patterns",
                 st: { rej: true, rejPats: ["SyntaxError", "ParseError"], codes: "", sig: false, sigPats: [], diff: false } },
  interpreter: { t: "Interpreter", d: "Crashes, timeouts, patterns",
                 st: { rej: false, rejPats: [], codes: "", sig: true, sigPats: ["Segmentation fault", "Assertion failed", "panic:"], diff: false } },
  custom:      { t: "Custom", d: "Start from scratch",
                 st: { rej: false, rejPats: [], codes: "", sig: false, sigPats: [], diff: false } },
};

// "5", "5s", "2m", "1.5h" -> seconds, or null. Mirrors the server's duration parser.
function durationSeconds(text) {
  const m = /^(\d+(?:\.\d+)?)\s*([smh]?)$/i.exec(String(text || "").trim());
  if (!m) return null;
  return Number(m[1]) * ({ "": 1, s: 1, m: 60, h: 3600 }[m[2].toLowerCase()]);
}
const RECOMMENDED_TIMEOUT = "5s";

// Look at how the system answered a deliberately invalid input and propose what to record. Pure and
// deterministic -- no model. The pattern is the start of the diagnostic up to the first quote or
// digit (the parts that change from input to input), regex-escaped and anchored, and the user can
// edit it before it is saved. Returns null when there is nothing that looks like a refusal.
function suggestRejection(probe) {
  if (!probe || !probe.ok || probe.timed_out || probe.signal) return null;
  if (probe.exit_code === 0 || probe.exit_code === null || probe.exit_code === undefined) return null;
  const first = t => String(t || "").split(/\r?\n/).map(l => l.trim()).find(Boolean) || "";
  const line = first(probe.stderr) || first(probe.stdout);
  let pattern = "";
  if (line) {
    // A short word before the first colon is usually the system's own rejection prefix.
    const colon = line.indexOf(":");
    let prefix;
    if (colon >= 3 && colon <= 30) prefix = line.slice(0, colon);
    else {
      const cut = line.search(/["'\d]/);
      prefix = cut >= 0 ? line.slice(0, cut) : line;
      if (cut < 0 && prefix.includes(":")) prefix = prefix.slice(0, prefix.indexOf(":"));
      if (prefix.trim().length < 3) prefix = line.slice(0, 40);
    }
    pattern = "^" + prefix.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }
  return { exitCode: probe.exit_code, line, pattern };
}
// ---- end testing strategy ------------------------------------------------------

// ---- review & run (pure) -----------------------------------------------------
//
// What the budget controls mean to the engine. In equal-time mode only `per_generator` is used (the
// total `generation` figure is recorded, not enforced), so the total is DERIVED here as
// per-generator x generators instead of being a second field that could disagree. In equal-count
// mode each generator is given `generation / generators` seconds as a ceiling; 120 s each keeps
// that ceiling from cutting a normal run short. Execution stops at whichever limit applies:
// a time limit, a number of executions, or (no limit) every prioritised input, bounded by 24 h.
const GEN_CEILING_S = 120, MAX_EXEC_S = 86400;

function runFromConfig(c) {
  const g = c.generation || {}, b = c.budget || {};
  const per = durationSeconds(g.per_generator ?? "30s");
  const execS = durationSeconds(b.execution ?? "1m");
  const r = { genMode: g.mode === "time" || g.count == null ? "time" : "count",
              perGen: per && per > 0 ? per : 30, count: Number.isInteger(g.count) && g.count > 0 ? g.count : 200,
              execMode: "time", execMinutes: execS && execS > 0 ? execS / 60 : 1, execCount: 500,
              signal: c.selection_signal === "random" ? "random" : "cc", model: (c.embedding || {}).model || "tfidf", jobs: 4,
              // Generators to keep by Cluster Coverage; 0 means all of them. Selection is opt-in: a project
              // without it keeps every generator, as it always has (the guided demo sets keep: 1).
              keep: c.selection && Number.isInteger(c.selection.keep) ? c.selection.keep : 0 };
  if (b.max_inputs) { r.execMode = "count"; r.execCount = b.max_inputs; }
  else if (execS && execS >= MAX_EXEC_S) r.execMode = "corpus";
  return r;
}

function runProblems(r) {
  const out = [];
  if (r.genMode === "time" && !(r.perGen > 0)) out.push("Seconds per generator must be more than zero.");
  if (r.genMode === "count" && !(Number.isInteger(r.count) && r.count >= 1)) out.push("Inputs per generator must be a whole number, 1 or more.");
  if (r.execMode === "time" && !(r.execMinutes > 0)) out.push("The time limit must be more than zero.");
  if (r.execMode === "count" && !(Number.isInteger(r.execCount) && r.execCount >= 1)) out.push("Number of tests must be a whole number, 1 or more.");
  return out;
}

// The config keys these choices mean. `nGens` is how many generators are selected; `timeoutS` is the
// per-input timeout (the worst case for a count-limited run).
function budgetFromRun(r, nGens, timeoutS) {
  const n = Math.max(1, nGens || 0);
  const generation = r.genMode === "time" ? { mode: "time", per_generator: `${r.perGen}s` } : { count: r.count };
  const genTotal = r.genMode === "time" ? Math.ceil(r.perGen * n) : GEN_CEILING_S * n;
  const budget = { generation: `${genTotal}s` };
  if (r.execMode === "time") budget.execution = `${Math.round(r.execMinutes * 60)}s`;
  else if (r.execMode === "count") {
    budget.max_inputs = r.execCount;
    budget.execution = `${Math.min(MAX_EXEC_S, Math.max(60, Math.ceil(r.execCount * (timeoutS || 5))))}s`;
  } else budget.execution = `${MAX_EXEC_S}s`;
  return { generation, budget };
}

// Honest about what is known: a time limit is exact, a count or "everything" is an upper bound or
// open-ended, and the estimate says which.
function runEstimate(r, nGens, timeoutS) {
  const n = nGens || 0;
  const genS = n === 0 ? 0 : (r.genMode === "time" ? r.perGen * n : GEN_CEILING_S * n);
  const genExact = n === 0 || r.genMode === "time";
  let execS = null, execExact = false;
  if (r.execMode === "time") { execS = r.execMinutes * 60; execExact = true; }
  else if (r.execMode === "count") execS = r.execCount * (timeoutS || 5);
  return { genS, genExact, execS, execExact, totalS: execS === null ? null : genS + execS, exact: genExact && execExact };
}
function fmtSeconds(s) {
  if (s < 90) return `${Math.round(s)} s`;
  const m = s / 60;
  if (m < 90) return `${(Math.round(m * 10) / 10).toString().replace(/\.0$/, "")} minutes`;
  return `${(Math.round(m / 6) / 10).toString().replace(/\.0$/, "")} hours`;
}
// ---- end review & run -----------------------------------------------------------

// ---- results formatting (pure) ----
function fmtMs(ms) { if (ms == null) return "—"; return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1).replace(/\.?0+$/, "")} s`; }
function fmtDur(s) {
  if (s == null) return "\u2014";
  s = Math.round(s);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60), r = s % 60;
  return r ? `${m}m ${r}s` : `${m}m`;
}
function fmtPct(n, d, digits = 1) { return d ? `${(100 * n / d).toFixed(digits)}%` : "—"; }
function pageNumbers(cur, last) {
  const set = new Set([1, last, cur - 1, cur, cur + 1].filter(n => n >= 1 && n <= last));
  const out = []; let prev = 0;
  [...set].sort((a, b) => a - b).forEach(n => { if (n - prev > 1) out.push("…"); out.push(n); prev = n; });
  return out;
}
// ---- end results formatting ----

// ---- live stage (pure) ----
const STAGES = [["install", "Install"], ["generate", "Generate"], ["rank", "Prioritize"], ["select", "Select"], ["execute", "Execute"], ["finish", "Finish"]];
// "Select" is a stage only for campaigns that keep the top generators by Cluster Coverage.
const SELECTED_LINE = /^\s*selected by cluster coverage:/;
function stagesFor(lines) { return lines.some(l => SELECTED_LINE.test(l)) ? STAGES : STAGES.filter(s => s[0] !== "select"); }
function liveStage(lines, done) {
  if (done) return "finish";
  // Monotonic: a campaign only moves forward, so a later line that merely LOOKS like an earlier
  // stage (an install note starts with "- ") must never pull the display back.
  const order = STAGES.map(x => x[0]);
  let at = 0;
  const reach = id => { at = Math.max(at, order.indexOf(id)); };
  for (const l of lines) {
    if (/^Installing /.test(l) || /^- /.test(l)) reach("install");
    if (/^Running:/.test(l) || /^Generating/.test(l)) reach("generate");
    if (/^Ranking with signal/.test(l)) reach("rank");
    if (SELECTED_LINE.test(l)) reach("select");
    if (/^Executing against/.test(l)) reach("execute");
  }
  return order[at];
}
// ---- end live stage ----

const DURATION = /^\d+(\.\d+)?\s*[smh]?$/i;
// ---- end command line helpers ----------------------------------------------

// ------------------------------------------------------ config helpers

function cfg() { return S.config || {}; }
function sut() { return cfg().sut || {}; }
function targets() {
  const s = sut();
  if (s.targets) return s.targets;
  if (s.command) return [{ name: s.name || "sut", command: s.command, cwd: s.cwd, env: s.env }];
  return [];
}

function buildYaml() {
  // Emitted by hand rather than with a YAML library so the file stays in the
  // shape a person would have written, comments and all.
  const c = cfg(), t = targets();
  const q = v => JSON.stringify(v);
  const lines = ["# Written by the SpreadEx setup wizard. Safe to edit by hand.", "sut:"];
  const extras = x => {
    const out = [];
    if (x.cwd) out.push(`cwd: ${q(x.cwd)}`);
    if (x.env && Object.keys(x.env).length) {
      out.push(`env: {${Object.entries(x.env).map(([k, v]) => `${k}: ${q(String(v))}`).join(", ")}}`);
    }
    return out;
  };
  if (t.length > 1) {
    lines.push("  targets:");
    t.forEach(x => lines.push(`    - {${[`name: ${x.name}`, `command: [${x.command.map(q).join(", ")}]`, ...extras(x)].join(", ")}}`));
  } else if (t.length === 1) {
    lines.push(`  command: [${t[0].command.map(q).join(", ")}]`);
    extras(t[0]).forEach(l => lines.push(`  ${l}`));
  }
  if (c.sut?.input_mode === "stdin") lines.push("  input_mode: stdin");
  if (c.sut?.memory_mb) lines.push(`  memory_mb: ${c.sut.memory_mb}`);
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
  if (c.input_extension) lines.push("", `input_extension: ${q(c.input_extension)}`);
  if (c.generator_options && Object.keys(c.generator_options).length) {
    lines.push("", "generator_options:");
    Object.entries(c.generator_options).forEach(([gid, o]) => lines.push(`  ${gid}: {${Object.entries(o).map(([k, v]) => `${k}: ${v}`).join(", ")}}`));
  }
  if (c.semantics) {
    lines.push("", "semantics:");
    if (c.semantics.guidance?.length) lines.push(`  guidance: [${c.semantics.guidance.map(q).join(", ")}]`);
    if (c.semantics.structured) lines.push(`  structured: ${q(c.semantics.structured)}`);
    if (c.semantics.native && Object.keys(c.semantics.native).length) {
      lines.push("  native:");
      Object.entries(c.semantics.native).forEach(([gid, p]) => lines.push(`    ${gid}: ${q(p)}`));
    }
  }
  if ((c.generation?.mode || "time") === "time" && !c.generation?.count) {
    lines.push("", "generation:", "  mode: time",
               `  per_generator: ${c.generation.per_generator || "30s"}`);
  } else if (c.generation?.count) {
    lines.push("", "generation:", `  count: ${c.generation.count}`);
  }
  lines.push("", "budget:",
    `  generation: ${c.budget?.generation || "1m"}`,
    `  execution: ${c.budget?.execution || "1m"}`);
  if (c.budget?.max_inputs) lines.push(`  max_inputs: ${c.budget.max_inputs}`);
  if (c.selection?.keep) lines.push("", "selection:", `  by: ${c.selection.by || "cc"}`, `  keep: ${c.selection.keep}`);
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

// Every input is RUN; these checks decide which results deserve attention. The engine already
// separates ok / expected_rejection / crash / timeout / divergence, so this step only chooses which
// of those to report, in the user's words. Crashes and timeouts are the floor and cannot be turned
// off; the other three are switches that write (or remove) their own keys in `oracle:`.

const STRAT_CHECKS = [
  { id: "crash", t: "Crashes & timeouts", tone: "red",    icon: "bug",     floor: true,
    tip: "A signal, a crash-shaped exit, or no answer before the timeout. Always on: this is the floor." },
  { id: "rej",   t: "Expected rejections", tone: "green", icon: "success",
    tip: "Many systems exit non-zero on input they legitimately refuse. Say how yours does, or every invalid input is reported as a crash." },
  { id: "sig",   t: "Failure signatures", tone: "blue",   icon: "doc",
    tip: "Messages that always mean a real failure. They are checked first, so a broad rejection rule cannot hide a bug. Failures are also grouped by signature automatically in the results." },
  { id: "diff",  t: "Differential testing", tone: "purple", icon: "scale",
    tip: "Run the same input on two or more implementations; a different exit class, exception or output is a divergence. No expected output needed." },
];

function stratState() {
  if (S.strat) return S.strat;
  const o = cfg().oracle || {};
  S.strat = {
    rej: !!((o.rejection_patterns || []).length || (o.expected_exit_codes || []).length),
    rejPats: [...(o.rejection_patterns || [])], codes: (o.expected_exit_codes || []).join(", "),
    sig: !!(o.crash_patterns || []).length, sigPats: [...(o.crash_patterns || [])],
    diff: o.type === "differential",
    open: {}, menu: false, undo: null, note: "",
    probeText: "@@ not valid @@", probe: null, probing: false, suggestion: null, suggestionDone: false,
    tip: (() => { try { return sessionStorage.getItem("spreadex-tip4") !== "1"; } catch (e) { return true; } })(),
  };
  return S.strat;
}

// Two halves, and the order matters. readStrat() copies what is ON SCREEN into the state; call it
// once, BEFORE changing anything. syncStrat() writes the state to the config without looking at the
// screen. Reading the screen after a change would copy the old inputs back over the new state.
function readStrat() {
  const st = stratState();
  document.querySelectorAll(".pat-rejPats").forEach((i, k) => { st.rejPats[k] = i.value; });
  document.querySelectorAll(".pat-sigPats").forEach((i, k) => { st.sigPats[k] = i.value; });
  return st;
}
function syncStrat() {
  const st = stratState();
  S.config.oracle = strategyOracle(cfg().oracle, st, targets().length > 1);
  return st;
}
function stashStrat() { readStrat(); return syncStrat(); }   // for leaving the page, where nothing changes

function stratSet(id, on) {
  const st = readStrat();
  if (id === "diff" && on && targets().length < 2) return;
  st[id] = on;
  // Switching a check on opens its settings, and one with no patterns yet gets an empty row to type in.
  if (on) { st.open[id] = true; if (id === "rej" && !st.rejPats.length) st.rejPats = [""]; if (id === "sig" && !st.sigPats.length) st.sigPats = [""]; }
  st.note = ""; syncStrat(); stepStrategy();
}
function stratToggleRow(id) { const st = readStrat(); st.open[id] = !st.open[id]; syncStrat(); stepStrategy(); }
function stratAddPattern(key) { const st = readStrat(); st[key].push(""); st.open[key === "rejPats" ? "rej" : "sig"] = true; syncStrat(); stepStrategy();
  const rows = document.querySelectorAll(`.pat-${key}`); rows[rows.length - 1]?.focus(); }
function stratDropPattern(key, i) { const st = readStrat(); st[key].splice(i, 1); syncStrat(); stepStrategy(); }
function stratClear() { const st = readStrat(); st.undo = JSON.stringify(st); Object.assign(st, { rej: false, sig: false, diff: false }); st.note = "Cleared. Crashes and timeouts are always checked."; syncStrat(); stepStrategy(); }

function stratPreset(id) {
  const st = readStrat(), p = STRATEGY_PRESETS[id];
  if (!p) return;
  st.undo = JSON.stringify({ rej: st.rej, rejPats: st.rejPats, codes: st.codes, sig: st.sig, sigPats: st.sigPats, diff: st.diff });
  Object.assign(st, JSON.parse(JSON.stringify(p.st)), { menu: false });
  if (st.diff && targets().length < 2) st.diff = false;
  st.open = { rej: st.rej, sig: st.sig };
  st.note = id === "custom" ? "Starting from scratch." :
    `Applied “${p.t}”. The patterns are starting points: replace them with real messages from your system.`;
  syncStrat(); stepStrategy();
}
function stratUndo() { const st = stratState(); if (!st.undo) return; Object.assign(st, JSON.parse(st.undo), { undo: null, note: "Undone." }); syncStrat(); stepStrategy(); }
function stratMenu(open) { const st = readStrat(); st.menu = open === undefined ? !st.menu : open; syncStrat(); stepStrategy(); }
function stratDismissTip() { stratState().tip = false; try { sessionStorage.setItem("spreadex-tip4", "1"); } catch (e) { /* fine */ } stepStrategy(); }


// The timeout lives in System under test; this edits the same value from where it matters most.
// Both the saved config and step 1's draft are updated, or going back and pressing Continue there
// would put the old value back.
function stratSetTimeout(value) {
  const v = String(value).trim();
  const secs = durationSeconds(v);
  if (secs === null || secs <= 0) return false;
  S.config.sut = { ...sut(), timeout: v };
  if (S.draft) S.draft.timeout = v;
  return true;
}
function stratTimeoutInput(input) {
  // The box holds seconds (the design's "seconds" unit); the config stores "20s".
  const raw = String(input.value).trim();
  const ok = raw !== "" && stratSetTimeout(raw + "s");
  input.setAttribute("aria-invalid", String(!ok));
  const f = input.closest(".tfield");
  const w = f?.querySelector(".pat-warn");
  if (w) w.textContent = ok ? "" : "Enter a number of seconds greater than zero.";
  const badge = f?.querySelector(".t-state");
  if (badge && ok) badge.innerHTML = timeoutState(raw + "s");
}
function timeoutState(v) {
  return durationSeconds(v) === durationSeconds(RECOMMENDED_TIMEOUT)
    ? `<span class="tag ok">Recommended</span>`
    : `<span class="tag">Changed</span> <button type="button" class="linkish" onclick="stratResetTimeout()">Reset to recommended</button>`;
}
function stratResetTimeout() { readStrat(); stratSetTimeout(RECOMMENDED_TIMEOUT); stepStrategy(); }

// How does YOUR system refuse input? Run it once on something invalid and show what came back,
// instead of asking the user to know an exit code and a regex.
async function stratObserve() {
  const st = readStrat(), t = targets()[0];
  if (!t || !(t.command || []).length) { st.probe = { ok: false, error: "Set the command in System under test first." }; return stepStrategy(); }
  const text = el("probe-text") ? el("probe-text").value : st.probeText;
  st.probeText = text; st.probing = true; st.suggestion = null; st.suggestionDone = false; stepStrategy();
  const s0 = sut();
  const body = { command: t.command, sample: text || "@@ not valid @@", input_mode: s0.input_mode || "file", timeout: s0.timeout || "5s" };
  if (t.cwd) body.cwd = t.cwd;
  if (t.env && Object.keys(t.env).length) body.env = t.env;
  try { st.probe = await api("/api/probe", body); } catch (e) { st.probe = { ok: false, error: String(e.message || e) }; }
  st.probing = false; st.suggestion = suggestRejection(st.probe); stepStrategy();
}
function stratAcceptSuggestion() {
  const st = readStrat(), sg = st.suggestion;
  if (!sg) return;
  const codes = parseExitCodes(st.codes);
  if (!codes.includes(sg.exitCode)) codes.push(sg.exitCode);
  st.codes = codes.join(", ");
  if (sg.pattern && !cleanPatterns(st.rejPats).includes(sg.pattern)) {
    st.rejPats = cleanPatterns(st.rejPats); st.rejPats.push(sg.pattern);
  }
  st.rej = true; st.open.rej = true; st.suggestionDone = true;
  st.note = "Added as an expected rejection. Check the pattern below and edit it if it is too broad."; 
  syncStrat(); stepStrategy();
}
function stratDeclineSuggestion() { const st = readStrat(); st.suggestion = null; st.suggestionDone = true; syncStrat(); stepStrategy(); }

// The order SpreadEx applies, shown so nobody wonders. It is not configurable: reordering it would
// change what a verdict means and make two campaigns incomparable.
const CLASSIFY_ORDER = [
  ["No answer in time", "reported as a timeout"],
  ["Killed by a signal", "reported as a crash, whatever the exit code says"],
  ["Output matches a failure message", "reported as a crash (checked before any rejection rule)"],
  ["Exit code is an expected exit code", "fine, nothing to report"],
  ["Output matches an expected rejection message", "a normal refusal of the input"],
  ["Anything else that exits non-zero", "reported as a crash"],
];

// JavaScript's regex dialect is close to Python's but not the same, so this is a hint: the server
// compiles every pattern with Python's engine when the config is saved, and has the last word.
function patternHint(p) {
  if (!p.trim()) return "";
  try { new RegExp(p, "i"); return ""; } catch (e) { return "This may not be a valid pattern. Escape special characters like ( with a backslash."; }
}

function patRows(key, placeholder) {
  const list = stratState()[key];
  const rows = list.length ? list : [""];
  return rows.map((v, i) => `<div class="pat-row">
      <input type="text" class="sut-cmd pat-${key}" value="${esc(v)}" placeholder="${esc(placeholder)}" spellcheck="false"
        aria-label="Message pattern ${i + 1}" oninput="this.nextElementSibling.nextElementSibling.textContent = patternHint(this.value)">
      <button type="button" class="gx" onclick="stratDropPattern('${key}', ${i})" aria-label="Remove this pattern">&times;</button>
      <span class="pat-warn warn" role="status">${esc(patternHint(v))}</span>
    </div>`).join("");
}

function stratActive() {
  const st = stratState();
  return STRAT_CHECKS.filter(c => c.floor || st[c.id]);
}

function stratChips(c) {
  const st = stratState(), o = cfg().oracle || {};
  // A chip is also a shortcut: the pencil says "edit this", and it opens the row's settings.
  const chip = (icon, text) => `<button type="button" class="schip edit" onclick="stratOpen('${c.id}')" aria-label="Edit: ${esc(text)}">${ICONS[icon]}<span>${esc(text)}</span>${ICONS.edit}</button>`;
  if (c.id === "crash") {
    const judged = st.rej || (o.expected_exit_codes || []).length;
    return chip("clock", `Timeout: ${sut().timeout || "5s"}`) +
           chip("alert", judged ? "Non-zero exit: judged" : "Non-zero exit: counts as crash");
  }
  if (c.id === "rej") {
    if (!st.rej) return "";
    const n = parseExitCodes(st.codes).length, m = cleanPatterns(st.rejPats).length;
    return (n ? chip("file", `${n} exit code${n > 1 ? "s" : ""}`) : "") + (m ? chip("doc", `${m} pattern${m > 1 ? "s" : ""}`) : "")
      || chip("file", "Nothing set up yet");
  }
  if (c.id === "sig") {
    if (!st.sig) return "";
    const m = cleanPatterns(st.sigPats).length;
    return chip("doc", m ? `${m} pattern${m > 1 ? "s" : ""}` : "Nothing set up yet");
  }
  if (targets().length > 1) return `<span class="schip">${ICONS.grid}<span>${targets().length} implementations</span></span>`;
  return `<button type="button" class="schip add" onclick="stratGoAddReference()">${ICONS.plus}<span>Add reference</span></button>`;
}
function stratOpen(id) { const st = readStrat(); st.open[id] = true; syncStrat(); stepStrategy(); }

function stratGoAddReference() { stashStrat(); const d = sutDraft(); if (!d.extra.length) d.extra.push({ name: "sut2", command: "" }); gotoStep("sut"); }


function observerBlock() {
  const st = stratState(), p = st.probe, sg = st.suggestion;
  const out = !p ? "" : !p.ok ? `<div class="res bad" role="alert"><span class="res-ico" aria-hidden="true">${ICONS.error}</span><div class="res-main"><div class="res-s">${esc(p.error)}</div></div></div>`
    : `<div class="obs-seen"><div><span class="muted">Exit code</span> <span class="mono">${p.timed_out ? "no answer" : esc(String(p.exit_code))}</span></div>
        ${(p.stderr || "").trim() ? `<div><span class="muted">stderr</span> <span class="mono">${esc((p.stderr || "").trim().split(/\r?\n/)[0])}</span></div>` : ""}
        ${(p.stdout || "").trim() ? `<div><span class="muted">stdout</span> <span class="mono">${esc((p.stdout || "").trim().split(/\r?\n/)[0])}</span></div>` : ""}</div>`;
  const ask = sg && !st.suggestionDone ? `<div class="obs-ask"><strong>Does this represent a normal input rejection?</strong>
      <div class="muted">${sg.pattern ? `It would add exit code <span class="mono">${esc(String(sg.exitCode))}</span> and the pattern <span class="mono">${esc(sg.pattern)}</span>.` : `It would add exit code <span class="mono">${esc(String(sg.exitCode))}</span>.`}</div>
      <div class="actions"><button type="button" class="primary small" onclick="stratAcceptSuggestion()">Yes, add as expected rejection</button>
        <button type="button" class="ghost small" onclick="stratDeclineSuggestion()">No</button></div></div>`
    : (p && p.ok && !sg && !st.probing ? `<p class="muted">That did not look like a refusal (it exited 0, hung, or was killed), so nothing is suggested.</p>` : "");
  return `<div class="observe"><label for="probe-text">See how your system refuses invalid input ${hint("hint-obs", "SpreadEx runs your command once on the text below and shows what came back, so you can say whether that is a normal refusal. Nothing is added unless you say yes.")}</label>
    <div class="tline"><input id="probe-text" type="text" class="sut-cmd" value="${esc(st.probeText)}" spellcheck="false">
      <button type="button" class="ghost small" onclick="stratObserve()" ${st.probing ? "disabled" : ""}>${st.probing ? "Running…" : "Run once"}</button></div>
    ${out}${ask}</div>`;
}

// Exit codes are tokens, not a comma-separated string: each one reads as a thing you can remove.
function codeTokens() {
  const codes = parseExitCodes(stratState().codes);
  return `<div class="ctokens">${codes.map(c => `<span class="cchip"><span class="mono">${c}</span>
      <button type="button" onclick="stratDropCode(${c})" aria-label="Remove exit code ${c}">&times;</button></span>`).join("")}
    <span class="cadd"><input id="code-add" type="text" inputmode="numeric" class="sut-cmd" placeholder="Add code" size="7" aria-label="Add an exit code"
        onkeydown="if (event.key === 'Enter') { event.preventDefault(); stratAddCode(); }">
      <button type="button" class="linkish" onclick="stratAddCode()">${ICONS.plus} Add</button></span></div>`;
}
function stratAddCode() {
  const st = readStrat(), box = el("code-add"), n = box ? Number(box.value.trim()) : NaN;
  if (!Number.isInteger(n)) { if (box) { box.setAttribute("aria-invalid", "true"); box.focus(); } return; }
  const codes = parseExitCodes(st.codes);
  if (!codes.includes(n)) codes.push(n);
  st.codes = codes.join(", "); st.rej = true; syncStrat(); stepStrategy(); el("code-add")?.focus();
}
function stratDropCode(n) {
  const st = readStrat(); st.codes = parseExitCodes(st.codes).filter(c => c !== n).join(", ");
  syncStrat(); stepStrategy();
}
function stratNonZero(v) { stratSet("rej", v === "judged"); }

function stratDetail(c) {
  const st = stratState();
  const col = (inner, cls = "") => `<div class="scol ${cls}">${inner}</div>`;
  if (c.id === "crash") {
    const tv = sut().timeout || RECOMMENDED_TIMEOUT;
    const secs = durationSeconds(tv);
    return `<div class="sgrid">${col(`<div class="tfield"><label for="timeout-4">Execution timeout ${hint("hint-timeout", "SpreadEx recommends 5 seconds. A compiler may need 30; a tiny parser may be fine with 1.")}</label>
        <div class="unitbox"><input id="timeout-4" type="number" min="0.1" step="any" class="sut-cmd" value="${esc(String(secs === null ? "" : Math.round(secs * 100) / 100))}" oninput="stratTimeoutInput(this)" aria-describedby="t-help"><span class="unit">seconds</span></div>
        <div class="t-state">${timeoutState(tv)}</div>
        <p id="t-help" class="muted">An input with no response in this time is reported as a timeout.</p>
        <span class="pat-warn warn" role="status"></span></div>`)}
      ${col(`<label for="nz">Non-zero exit code ${hint("hint-nz", "Most compilers and parsers exit non-zero for input they refuse. Choose whether that is a crash or is judged by your Expected rejections.")}</label>
        <select id="nz" onchange="stratNonZero(this.value)"><option value="crash" ${st.rej ? "" : "selected"}>Treat as crash (default)</option>
          <option value="judged" ${st.rej ? "selected" : ""}>Judge by expected rejections</option></select>
        <p class="muted">A non-zero exit is considered a crash unless you configure Expected rejections.</p>`)}</div>`;
  }
  if (c.id === "rej") return `${observerBlock()}<div class="sgrid">${col(`<label>Exit codes that are not failures ${hint("hint-codes", "A run that ends with one of these is treated as normal.")}</label>
        ${codeTokens()}<p class="muted">Exit codes used when the system intentionally rejects an input.</p>`)}
      ${col(`<label>Rejection message patterns ${hint("hint-rejpats", "Matching diagnostics are treated as a normal input rejection rather than a crash. Regular expressions, ignoring case.")}</label>
        ${patRows("rejPats", "SyntaxError")}
        <button type="button" class="ghost small" onclick="stratAddPattern('rejPats')">${ICONS.plus} Add pattern</button>`)}</div>`;
  if (c.id === "sig") return `<div class="sgrid">${col(`<label>Crash / error message patterns ${hint("hint-sigpats", "Output matching one of these is always reported as a failure, even if the exit code looks fine.")}</label>
        ${patRows("sigPats", "Segmentation fault")}
        <button type="button" class="ghost small" onclick="stratAddPattern('sigPats')">${ICONS.plus} Add pattern</button>`)}
      ${col(`<div class="sinfo">${ICONS.info}<div><strong>Matched before rejections</strong>
        <p class="muted">These patterns are checked before the rejection patterns, so a genuine crash is not hidden by a broad rejection rule.</p></div></div>`)}</div>`;
  return targets().length > 1
    ? `<p class="muted">${targets().length} implementations run every input. A different exit class, exception or output is a divergence; all of them refusing the same input is not.</p>`
    : `<p class="muted">Needs a second implementation to compare against. Add one in System under test; no expected output is required.</p>
       <button type="button" class="ghost small" onclick="stratGoAddReference()">${ICONS.plus} Add a second implementation</button>`;
}

function stepStrategy() {
  const st = stratState(), multi = targets().length > 1;
  const active = stratActive();
  el("view").innerHTML = `
  <div class="sut strat">
   <div class="sut-main">
    <header class="sut-head">
      <span class="sut-badge orange" aria-hidden="true">4</span>
      <div class="strat-title"><h3>What do you want to detect? ${hint("hint-strat", "SpreadEx runs every input, then these checks decide which results deserve your attention. Most generated input is invalid on purpose, so a refusal is not automatically a bug.")}</h3>
        <p class="why">Choose how results are judged.</p></div>
      <div class="preset-pick"><button type="button" class="ghost" aria-haspopup="menu" aria-expanded="${st.menu}" onclick="stratMenu()">Use a preset ${ICONS.chevron}</button>
        ${st.menu ? `<div class="preset-menu" role="menu">${Object.entries(STRATEGY_PRESETS).map(([id, p]) =>
          `<button type="button" role="menuitem" onclick="stratPreset('${id}')"><strong>${esc(p.t)}</strong><span class="muted">${esc(p.d)}</span></button>`).join("")}</div>` : ""}</div>
    </header>

    ${st.note ? `<div class="inp-guide" role="status">${ICONS.info}<div>${esc(st.note)}${st.undo ? ` <button type="button" class="linkish" onclick="stratUndo()">Undo</button>` : ""}</div></div>` : ""}

    <div class="schecks" role="group" aria-label="Checks">
      ${STRAT_CHECKS.map(c => {
        const on = c.floor || st[c.id], dis = c.floor || (c.id === "diff" && !multi);
        return `<label class="scheck tc-${c.tone} ${on ? "on" : ""} ${dis && !c.floor ? "dis" : ""}">
          <span class="stile ${c.tone}" aria-hidden="true">${ICONS[c.icon]}</span>
          <span class="scheck-t">${c.t}</span>
          <input type="checkbox" ${on ? "checked" : ""} ${dis ? "disabled" : ""} onchange="stratSet('${c.id}', this.checked)" aria-label="${esc(c.t)}${c.floor ? " (always on)" : ""}">
          <span class="box" aria-hidden="true">${ICONS.check}</span>
          ${hint("hint-" + c.id, c.tip)}</label>`; }).join("")}
    </div>

    <section class="sut-sec" aria-labelledby="cfg-h">
      <h4 id="cfg-h">Configuration</h4>
      <p class="muted inp-sub">Set up the selected checks. Use the defaults or customise as needed.</p>
      <div class="srows">${STRAT_CHECKS.map(c => {
        const on = c.floor || st[c.id], open = !!st.open[c.id];
        const dis = c.id === "diff" && !multi;
        return `<div class="srow tc-${c.tone} ${on ? "on" : "off"}" data-tour="strat-${c.id}">
          <div class="srow-h">
            <button type="button" class="switch" role="switch" aria-checked="${on}" ${c.floor || dis ? "disabled" : ""}
              aria-label="${esc(c.t)}${c.floor ? " (always on)" : ""}" onclick="stratSet('${c.id}', ${!on})"><span></span></button>
            <span class="stile ${c.tone}" aria-hidden="true">${ICONS[c.icon]}</span>
            <strong class="srow-t">${c.t} ${hint("hint-row-" + c.id, c.tip)}</strong>
            <span class="spill">${on ? "Enabled" : "Disabled"}</span>
            <span class="schips">${stratChips(c)}</span>
            <button type="button" class="chev ${open ? "open" : ""}" aria-expanded="${open}" aria-label="${open ? "Hide" : "Show"} settings for ${esc(c.t)}"
              onclick="stratToggleRow('${c.id}')">${ICONS.chevron}</button>
          </div>
          ${open ? `<div class="srow-b">${stratDetail(c)}</div>` : ""}
        </div>`; }).join("")}
      </div>
    </section>

    <details class="sut-adv">
      <summary><span><strong>How SpreadEx classifies a result</strong></span><span class="muted">The order is fixed by SpreadEx so results stay comparable</span></summary>
      <div class="sut-adv-body"><ol class="classify">${CLASSIFY_ORDER.map(([a, b]) => `<li><strong>${esc(a)}</strong> <span class="muted">&rarr; ${esc(b)}</span></li>`).join("")}</ol>
        <p class="muted">With two or more implementations, each is judged this way first; then a difference between them is a divergence.
          Everything on this page is saved to <span class="mono">spreadex.yaml</span>, which you can also edit by hand.</p></div>
    </details>

    <div id="err"></div>
    <div class="actions inp-actions">
      <button type="button" class="ghost" onclick="stashStrat(); gotoStep('generators')">${ICONS.back} Back to Generators</button>
      <button type="button" class="primary" data-tour="strat-continue" onclick="commitStrategy()">Continue to Review &amp; run ${ICONS.arrow}</button>
    </div>
   </div>

   <aside class="sut-side" aria-label="Help">
    ${st.tip ? `<div class="side-card tipcard"><div class="gsel-h"><h4><span class="h-ico amber">${ICONS.bulb}</span> Quick tip</h4>
        <button type="button" class="gx" onclick="stratDismissTip()" aria-label="Dismiss tip">&times;</button></div>
      <p>Non-zero exit codes are not always crashes. Configure expected rejections to avoid false positives.</p></div>` : ""}
    <div class="side-card">
      <h4><span class="h-ico purple">${ICONS.doc}</span> Presets</h4>
      ${Object.entries(STRATEGY_PRESETS).map(([id, p]) => `<button type="button" class="preset" onclick="stratPreset('${id}')">
        <span><strong>${esc(p.t)}</strong><span class="muted">${esc(p.d)}</span></span>${ICONS.arrow}</button>`).join("")}
    </div>
    <div class="side-card">
      <div class="gsel-h"><h4>Selected checks <span class="muted">(${active.length})</span></h4>
        <button type="button" class="linkish" onclick="stratClear()">Clear all</button></div>
      ${active.map(c => `<div class="gsel-row"><span class="stile sm ${c.tone}" aria-hidden="true">${ICONS[c.icon]}</span><strong>${c.t}</strong>
        ${c.floor ? `<span class="muted">always on</span>` : `<button type="button" class="gx" onclick="stratSet('${c.id}', false)" aria-label="Turn off ${esc(c.t)}">&times;</button>`}</div>`).join("")}
    </div>
   </aside>
  </div>`;
}

function commitStrategy() {
  const st = stashStrat();
  const tsecs = el("timeout-4") ? durationSeconds(el("timeout-4").value + "s") : 1;
  if (tsecs === null || tsecs <= 0) {
    st.open.crash = true; stepStrategy();
    el("err").innerHTML = `<div class="note bad" role="alert">The timeout must be a number of seconds greater than zero.</div>`;
    return;
  }
  if (st.rej && !cleanPatterns(st.rejPats).length && !parseExitCodes(st.codes).length) {
    st.open.rej = true; stepStrategy();
    el("err").innerHTML = `<div class="note bad" role="alert">Expected rejections is on but nothing is set up. Add a message your system prints
      when it refuses input, or turn the check off.</div>`;
    return;
  }
  if (st.sig && !cleanPatterns(st.sigPats).length) {
    st.open.sig = true; stepStrategy();
    el("err").innerHTML = `<div class="note bad" role="alert">Failure signatures is on but has no patterns. Add one, or turn the check off.</div>`;
    return;
  }
  S.confirmed.add("strategy");
  gotoStep("run");
  tourEvent("step.strategy");
}

// ------------------------------------------------------------ step views

// Two of the steps fetch before they paint. Without a token, a slow step 3
// can finish after you have already moved to step 5 and overwrite it -- the
// state is right, the screen is a step behind, and nothing looks broken.
let RENDER = 0;

function renderStep() {
  const mine = ++RENDER;
  const step = S.step;
  const fn = { sut: stepSut, grammar: stepGrammar, generators: stepGenerators,
               strategy: stepStrategy, run: stepRun }[step];
  Promise.resolve(fn(() => mine === RENDER)).catch(e => {
    if (mine !== RENDER) return;   // we were superseded; its error is moot
    el("view").innerHTML = failureCard(e);
  });
}

// ------------------------------------------------- step 1: system under test

// Presets only prefill the command and the example shown on the right; the
// user's text is never overwritten once they have typed something of their own.
const SUT_KINDS = [
  { id: "cli",    t: "Executable",     d: "A command-line program that accepts an input file.", img: "cli", icon: "terminal", tone: "green",
    cmd: "./your-parser {input}" },
  { id: "jar",    t: "Java / JVM",     d: "Run a JAR or Java class with your JDK.", img: "jar", icon: "java", tone: "orange",
    cmd: "java -jar your-tool.jar {input}" },
  { id: "script", t: "Script / Runtime", d: "Python, Node.js, Ruby, or another interpreter.", img: "script", icon: "python", tone: "blue",
    cmd: "python3 your_parser.py {input}" },
  { id: "other",  t: "Custom command", d: "Define the complete execution command.", img: "other", icon: "grid", tone: "slate",
    cmd: "" },
];

const SUT_EXAMPLES = [
  { id: "jar",    t: "Java (Rhino)", code: "java -jar rhino-all.jar {input}" },
  { id: "python", t: "Python",       code: "python3 your_parser.py {input}" },
  { id: "node",   t: "Node.js",      code: "node parse.js {input}" },
  { id: "other",  t: "Custom",       code: "./run-my-tool.sh {input}" },
];


// The terminal-and-document picture above the help column. Decorative; colours that must
// follow the theme come from tokens, the terminal itself stays dark in both.
const SUT_ART = `<svg viewBox="0 0 320 170" role="presentation" focusable="false">
  <path d="M30 96c-10-38 24-70 64-62 34-30 96-24 112 10 40-6 76 24 66 60-8 30-40 46-76 40-40 30-110 26-136-8-20-2-28-16-30-40z" fill="#16A34A" opacity=".12"/>
  <ellipse cx="226" cy="64" rx="70" ry="46" fill="#1687F8" opacity=".12"/>
  <rect x="78" y="40" width="150" height="92" rx="10" fill="#0F1F2E"/>
  <circle cx="92" cy="54" r="3" fill="#F59E0B"/><circle cx="102" cy="54" r="3" fill="#16A34A"/><circle cx="112" cy="54" r="3" fill="#1687F8"/>
  <path d="M96 82l14 10-14 10" fill="none" stroke="#22C55E" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M120 104h22" stroke="#22C55E" stroke-width="6" stroke-linecap="round"/>
  <rect x="190" y="84" width="62" height="70" rx="10" fill="var(--color-surface)" stroke="#1687F8" stroke-width="4"/>
  <path d="M204 108h34M204 122h34M204 136h22" stroke="#1687F8" stroke-width="5" stroke-linecap="round"/>
</svg>`;

const SUT_TIPS = [
  "Use {input} where the test file path should go.",
  "You can configure advanced options if needed.",
  "Failure detection and oracles are configured later in Testing strategy.",
];

function sutDraft() {
  if (S.draft) return S.draft;
  const t = targets();
  const s = sut();
  const first = t[0] || {};
  S.draft = {
    kind: S.kind || (first.command ? inferKind(first.command) : "cli"),
    command: first.command ? joinCommand(first.command) : "",
    extra: t.slice(1).map(x => ({ name: x.name, command: joinCommand(x.command || []) })),
    cwd: first.cwd || s.cwd || "",
    env: envToText(first.env || s.env),
    input_mode: first.input_mode || s.input_mode || "file",
    memory_mb: first.memory_mb || s.memory_mb || "",
    timeout: String(s.timeout || "5s"),
    advancedOpen: !!(first.cwd || s.cwd || first.env || s.env || s.memory_mb ||
                     (first.input_mode || s.input_mode) === "stdin"),
    exampleTab: "jar",
  };
  return S.draft;
}

// Read what is on screen back into the draft before any re-render, so toggling
// a card or a tab never eats what was typed.
function stashSut() {
  const d = sutDraft();
  const v = id => (el(id) ? el(id).value : undefined);
  if (v("sut-cmd") !== undefined) d.command = v("sut-cmd");
  if (v("sut-cwd") !== undefined) d.cwd = v("sut-cwd");
  if (v("sut-env") !== undefined) d.env = v("sut-env");
  if (v("sut-mem") !== undefined) d.memory_mb = v("sut-mem");
  if (v("sut-timeout") !== undefined) d.timeout = v("sut-timeout");
  if (el("sut-stdin")) d.input_mode = el("sut-stdin").checked ? "stdin" : "file";
  const adv = document.getElementById("sut-adv");
  if (adv) d.advancedOpen = adv.open;
  document.querySelectorAll(".sut-extra").forEach((row, i) => {
    if (!d.extra[i]) return;
    d.extra[i].name = row.querySelector(".x-name").value;
    d.extra[i].command = row.querySelector(".x-cmd").value;
  });
  return d;
}

function pickSutKind(id) {
  const d = stashSut();
  const was = SUT_KINDS.find(k => k.id === d.kind);
  const k = SUT_KINDS.find(x => x.id === id);
  d.kind = id;
  S.kind = id;
  // Swap the placeholder command only if the box is empty or still holds the
  // previous card's untouched template.
  if (k && k.cmd && (!d.command.trim() || (was && was.cmd === d.command))) d.command = k.cmd;
  if (id === "jar") d.exampleTab = "jar";
  else if (id === "script") d.exampleTab = "python";
  else if (id === "other") d.exampleTab = "other";
  S.probe = null;
  stepSut();
}

function sutExampleTab(id) { stashSut().exampleTab = id; stepSut(); }

function copyExample(button) {
  const d = sutDraft();
  const ex = SUT_EXAMPLES.find(x => x.id === d.exampleTab) || SUT_EXAMPLES[0];
  const done = () => { button.classList.add("copied"); button.setAttribute("aria-label", "Copied");
    setTimeout(() => { button.classList.remove("copied"); button.setAttribute("aria-label", "Copy command"); }, 1400); };
  if (navigator.clipboard?.writeText) navigator.clipboard.writeText(ex.code).then(done).catch(() => {});
}

function addSutExtra() {
  const d = stashSut();
  d.extra.push({ name: `sut${d.extra.length + 2}`, command: "" });
  stepSut();
}
function dropSutExtra(i) { const d = stashSut(); d.extra.splice(i, 1); stepSut(); }

// Everything the form says, checked once, in the order a person fixes things.
// `problem` is for Continue and Test (a blocker); the draft is never altered.
function readSut() {
  const d = stashSut();
  const main = splitCommand(d.command);
  if (main.error) return { problem: `Command: ${main.error}.`, focus: "sut-cmd" };
  if (!main.argv.length) return { problem: "Enter the command that runs your program.", focus: "sut-cmd" };
  const env = parseEnv(d.env);
  if (env.error) return { problem: `Environment variables: ${env.error}.`, focus: "sut-env", open: true };
  if (!DURATION.test(String(d.timeout).trim())) {
    return { problem: `Timeout: "${d.timeout}" is not a duration; use 5, 5s, 2m or 1h.`, focus: "sut-timeout", open: true };
  }
  let memory_mb;
  if (String(d.memory_mb).trim() !== "") {
    memory_mb = Number(d.memory_mb);
    if (!Number.isInteger(memory_mb) || memory_mb <= 0) {
      return { problem: "Memory limit: enter a whole number of megabytes.", focus: "sut-mem", open: true };
    }
  }
  const extra = [];
  for (const [i, x] of d.extra.entries()) {
    if (!x.command.trim()) continue;
    const p = splitCommand(x.command);
    if (p.error || !p.argv.length) return { problem: `Second implementation: ${p.error || "enter a command"}.`, focus: null };
    extra.push({ name: (x.name || `sut${i + 2}`).trim(), command: p.argv });
  }
  return { argv: main.argv, env: env.env, cwd: d.cwd.trim(), memory_mb,
           input_mode: d.input_mode, timeout: String(d.timeout).trim(), extra };
}

function showSutProblem(r) {
  el("err").innerHTML = `<div class="note bad" role="alert">${esc(r.problem)}</div>`;
  if (r.open && el("sut-adv")) el("sut-adv").open = true;
  if (r.focus && el(r.focus)) el(r.focus).focus();
}

async function verifyCommand() {
  const r = readSut();
  el("err").innerHTML = "";
  if (r.problem) { showSutProblem(r); return; }
  const btn = el("sut-test");
  btn.disabled = true;
  S.probe = { pending: true };
  el("probe").innerHTML = sutResult();
  const body = { command: r.argv, input_mode: r.input_mode, timeout: r.timeout,
                 sample: S.sample || "1 + 1\n" };
  if (r.cwd) body.cwd = r.cwd;
  if (Object.keys(r.env).length) body.env = r.env;
  if (r.memory_mb) body.memory_mb = r.memory_mb;
  try { S.probe = await api("/api/probe", body); }
  catch (e) { S.probe = { ok: false, error: String(e.message || e) }; }
  S.probe.key = sutKey({ command: r.argv, cwd: r.cwd, env: r.env, input_mode: r.input_mode });
  tourEvent(S.probe.ok && !S.probe.timed_out ? "probe.ok" : "probe.fail");
  S.probeShowDetails = false;
  stepSut();
}

function toggleProbeDetails() { stashSut(); S.probeShowDetails = !S.probeShowDetails; stepSut(); }

function sutResult() {
  const r = S.probe;
  if (!r) return "";
  const check = `<span class="res-ico" aria-hidden="true">${ICONS.success}</span>`;
  if (r.pending) return `<div class="res note" role="status">Running it once&hellip;</div>`;
  if (!r.ok) {
    return `<div class="res bad" role="alert"><span class="res-ico" aria-hidden="true">${ICONS.error}</span>
      <div class="res-main"><div class="res-t">It did not run</div>
      <div class="res-s">${esc(r.error)}</div></div></div>`;
  }
  const dead = r.timed_out;
  const facts = [["Command", `<span class="mono">${esc((r.command || []).join(" "))}</span>`],
                 ["Runtime", esc(r.runtime || "Not detected")],
                 ["Test time", dead ? `no answer in ${Math.round(r.duration_ms / 1000)}s`
                                    : `${Math.round(r.duration_ms)} ms`]];
  const block = (title, text) => text && text.trim()
    ? `<div class="res-pre"><label>${title}</label><pre>${esc(text)}</pre></div>` : "";
  return `<div class="res ${dead ? "warn" : "good"}" role="status">${dead ? `<span class="res-ico" aria-hidden="true">${ICONS.alert}</span>` : check}
    <div class="res-main">
      <div class="res-t">${dead ? "No answer in time" : "System ready!"}</div>
      <div class="res-s">${dead
        ? "If that is normal for your system, raise the timeout under Advanced options. Otherwise the command may be waiting on stdin &mdash; turn on &ldquo;Pass input via stdin&rdquo;."
        : `SpreadEx successfully executed a test input.${r.exit_code ? ` It exited with code <span class="mono">${r.exit_code}</span>, which is often correct for a parser &mdash; you will say what counts as a failure on step 4.` : ""}`}</div>
      <dl class="res-facts">${facts.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("")}</dl>
      ${S.probeShowDetails ? `${block("Standard output", r.stdout)}${block("Standard error", r.stderr)}
        ${!(r.stdout || "").trim() && !(r.stderr || "").trim() ? `<div class="res-s">It printed nothing.</div>` : ""}` : ""}
    </div>
    <button class="ghost small res-btn" onclick="toggleProbeDetails()" aria-expanded="${!!S.probeShowDetails}">${S.probeShowDetails ? "Hide details" : "View details"}</button></div>`;
}

function stepSut() {
  const d = sutDraft();
  if (S.sample === undefined) S.sample = "1 + 1\n";
  const ex = SUT_EXAMPLES.find(x => x.id === d.exampleTab) || SUT_EXAMPLES[0];
  el("view").innerHTML = `
  <div class="sut">
   <div class="sut-main">
    <header class="sut-head">
      <span class="sut-badge" aria-hidden="true">1</span>
      <div><h3>Connect your system under test</h3>
        <p class="why">Tell SpreadEx how to run one test input against your program. We'll verify the command before configuring input generation.</p></div>
    </header>

    <section class="sut-sec" aria-labelledby="sut-q">
      <h4 id="sut-q">How do you run your program?</h4>
      <div class="sut-kinds" role="radiogroup" aria-labelledby="sut-q">
        ${SUT_KINDS.map(k => `<button type="button" role="radio" class="sut-kind ${d.kind === k.id ? "on" : ""}"
          aria-checked="${d.kind === k.id}" onclick="pickSutKind('${k.id}')">
          <span class="tile big ${k.tone}" aria-hidden="true"><img src="/static/assets/sut-${k.img}.png" alt="" width="34" height="34" draggable="false"></span>
          <span class="sk-t">${k.t}</span><span class="sk-d">${k.d}</span>
          <span class="sk-ok" aria-hidden="true">${ICONS.check}</span></button>`).join("")}
      </div>
    </section>

    <section class="sut-sec">
      <div class="sut-lab"><label for="sut-cmd">Execution command</label>
        ${hint("hint-cmd", "SpreadEx runs this command once for every generated input. Quote any argument that contains a space.")}
        <span class="sut-pill"><code>{input}</code> will be replaced with each generated test file</span></div>
      <input id="sut-cmd" data-tour="sut-command" class="sut-cmd" type="text" spellcheck="false" autocomplete="off"
        value="${esc(d.command)}" placeholder="${esc((SUT_KINDS.find(k => k.id === d.kind) || {}).cmd || "your-command {input}")}">
      ${d.extra.map((x, i) => `<div class="sut-extra">
        <input class="x-name" type="text" value="${esc(x.name)}" aria-label="Name of implementation ${i + 2}">
        <input class="x-cmd sut-cmd" type="text" spellcheck="false" value="${esc(x.command)}" aria-label="Command for implementation ${i + 2}" placeholder="another-implementation {input}">
        <button type="button" class="ghost small" onclick="dropSutExtra(${i})" aria-label="Remove">&times;</button></div>`).join("")}
      <div class="sut-compare"><button type="button" class="linkish" onclick="addSutExtra()">Compare another implementation</button>
        <span class="muted">Two or more lets SpreadEx test them against each other &mdash; no expected output needed.</span></div>
    </section>

    <div class="sut-test-row">
      <button type="button" id="sut-test" data-tour="sut-test" class="primary" onclick="verifyCommand()">${ICONS.playOutline} Test connection</button>
      <span class="muted">Runs a quick check with a sample input to verify the setup.</span>
    </div>

    <details id="sut-adv" class="sut-adv" ${d.advancedOpen ? "open" : ""}>
      <summary><span><strong>Advanced options</strong> (optional)</span>
        <span class="muted">Working directory, environment variables, input via stdin, timeouts, resource limits&hellip;</span></summary>
      <div class="sut-adv-body">
        <label for="sut-cwd">Working directory</label>
        <input id="sut-cwd" type="text" value="${esc(d.cwd)}" placeholder="Leave empty for a clean scratch directory (relative paths are from this project)">
        <label for="sut-env">Environment variables <span class="muted">one NAME=value per line</span></label>
        <textarea id="sut-env" rows="3" spellcheck="false" placeholder="JAVA_OPTS=-Xmx512m">${esc(d.env)}</textarea>
        <label class="sut-check"><input id="sut-stdin" type="checkbox" ${d.input_mode === "stdin" ? "checked" : ""}>
          Pass input via stdin <span class="muted">instead of as a file path</span></label>
        <div class="row">
          <div><label for="sut-timeout">Timeout per input</label><input id="sut-timeout" type="text" value="${esc(d.timeout)}"></div>
          <div><label for="sut-mem">Memory limit (MB)</label><input id="sut-mem" type="text" inputmode="numeric" value="${esc(d.memory_mb)}" placeholder="2048">
            <span class="muted sut-note">Not enforced everywhere &mdash; macOS often ignores it.</span></div>
        </div>
      </div>
    </details>

    <div id="probe" aria-live="polite">${sutResult()}</div>
    <div id="err"></div>
    <div class="actions sut-actions">
      <button type="button" class="primary" data-tour="sut-continue" onclick="commitSut()">Continue to Inputs ${ICONS.arrow}</button>
    </div>
   </div>

   <aside class="sut-side" aria-label="Help">
    <div class="side-card side-hero" aria-hidden="true">${SUT_ART}</div>
    <div class="side-card">
      <h4><span class="h-ico blue">${ICONS.book}</span> What happens here?</h4>
      <p>Provide the command to run your program with one test input. SpreadEx will run a small test to verify the setup before you configure inputs.</p>
    </div>
    <div class="side-card">
      <h4><span class="h-ico purple">${ICONS.example}</span> Examples</h4>
      <div class="ex-tabs" role="tablist">${SUT_EXAMPLES.map(x => `<button type="button" role="tab"
        aria-selected="${x.id === ex.id}" class="${x.id === ex.id ? "on" : ""}" onclick="sutExampleTab('${x.id}')">${x.t}</button>`).join("")}</div>
      <div class="ex-code"><code>${esc(ex.code)}</code>
        <button type="button" class="ex-copy" onclick="copyExample(this)" aria-label="Copy command">${ICONS.copy}</button></div>
    </div>
    <div class="side-card">
      <h4><span class="h-ico amber">${ICONS.bulb}</span> Tips</h4>
      <ul class="tips-list">${SUT_TIPS.map(t => `<li><span aria-hidden="true">${ICONS.check}</span>${esc(t)}</li>`).join("")}</ul>
    </div>
   </aside>
  </div>`;
}

function commitSut() {
  const r = readSut();
  el("err").innerHTML = "";
  if (r.problem) { showSutProblem(r); return; }
  const key = sutKey({ command: r.argv, cwd: r.cwd, env: r.env, input_mode: r.input_mode });
  if (key !== S.verifiedSut && !(S.probe?.ok && S.probe.key === key)) {
    showSutProblem({ problem: S.probe?.key === key && !S.probe.ok
      ? "The last Test connection failed. Fix the command, then test it again."
      : "Test the connection first: the command has not been run since it was entered or changed.",
      focus: "sut-test" });
    return;
  }
  S.verifiedSut = key;
  const d = sutDraft();
  const opts = {};
  if (r.cwd) opts.cwd = r.cwd;
  if (Object.keys(r.env).length) opts.env = r.env;
  const shared = { timeout: r.timeout };
  if (r.memory_mb) shared.memory_mb = r.memory_mb;
  if (r.input_mode === "stdin") shared.input_mode = "stdin";
  if (r.extra.length) {
    // cwd and env belong to a target, so every implementation gets them; the
    // rest are defaults the engine applies to all.
    S.config.sut = { ...shared, targets: [{ name: "sut1", command: r.argv, ...opts },
                                          ...r.extra.map(x => ({ ...x, ...opts }))] };
  } else {
    S.config.sut = { ...shared, command: r.argv, ...opts };
  }
  // A second implementation is the only thing that makes differential testing
  // possible, so dropping back to one target has to retire it.
  const o = { ...(cfg().oracle || {}) };
  if (!r.extra.length && o.type === "differential") o.type = "crash";
  S.config.oracle = o;
  S.kind = d.kind;
  gotoStep("grammar");
  tourEvent("step.sut");
}

// ------------------------------------------------------- step 2: inputs

// What each way of describing the inputs means in this tool today. Registry is
// deliberately absent: "SpreadEx grammar" offers the few grammars that ship in
// the wheel and that the test suite exercises, not a catalogue of languages.
const INP_MODES = [
  { id: "builtin", t: "SpreadEx grammar", d: "Start from a tested grammar that ships with SpreadEx.", icon: "book",   tone: "green" },
  { id: "provide", t: "Provide grammar",  d: "Use a grammar file that is already in this project.", icon: "folder", tone: "blue" },
  { id: "import",  t: "Import grammar",   d: "Bring one from elsewhere: ANTLR, BNF, EBNF and more.",  icon: "import", tone: "purple" },
  { id: "none",    t: "No grammar",       d: "Use inputs you already have in a folder.",               icon: "doc",    tone: "orange" },
];

// Language logos: Simple Icons paths (CC0) in their brand colour; Lucide glyphs or a letter
// badge where no brand mark exists. The last four entries are the non-language choices.
const INP_LANGS = [{"id":"js","t":"JavaScript","sub":"ECMAScript","ext":".js","d":"M0 0h24v24H0V0zm22.034 18.276c-.175-1.095-.888-2.015-3.003-2.873-.736-.345-1.554-.585-1.797-1.14-.091-.33-.105-.51-.046-.705.15-.646.915-.84 1.515-.66.39.12.75.42.976.9 1.034-.676 1.034-.676 1.755-1.125-.27-.42-.404-.601-.586-.78-.63-.705-1.469-1.065-2.834-1.034l-.705.089c-.676.165-1.32.525-1.71 1.005-1.14 1.291-.811 3.541.569 4.471 1.365 1.02 3.361 1.244 3.616 2.205.24 1.17-.87 1.545-1.966 1.41-.811-.18-1.26-.586-1.755-1.336l-1.83 1.051c.21.48.45.689.81 1.109 1.74 1.756 6.09 1.666 6.871-1.004.029-.09.24-.705.074-1.65l.046.067zm-8.983-7.245h-2.248c0 1.938-.009 3.864-.009 5.805 0 1.232.063 2.363-.138 2.711-.33.689-1.18.601-1.566.48-.396-.196-.597-.466-.83-.855-.063-.105-.11-.196-.127-.196l-1.825 1.125c.305.63.75 1.172 1.324 1.517.855.51 2.004.675 3.207.405.783-.226 1.458-.691 1.811-1.411.51-.93.402-2.07.397-3.346.012-2.054 0-4.109 0-6.179l.004-.056z","hex":"F7DF1E"},{"id":"py","t":"Python","sub":"Python 3.x","ext":".py","d":"M14.25.18l.9.2.73.26.59.3.45.32.34.34.25.34.16.33.1.3.04.26.02.2-.01.13V8.5l-.05.63-.13.55-.21.46-.26.38-.3.31-.33.25-.35.19-.35.14-.33.1-.3.07-.26.04-.21.02H8.77l-.69.05-.59.14-.5.22-.41.27-.33.32-.27.35-.2.36-.15.37-.1.35-.07.32-.04.27-.02.21v3.06H3.17l-.21-.03-.28-.07-.32-.12-.35-.18-.36-.26-.36-.36-.35-.46-.32-.59-.28-.73-.21-.88-.14-1.05-.05-1.23.06-1.22.16-1.04.24-.87.32-.71.36-.57.4-.44.42-.33.42-.24.4-.16.36-.1.32-.05.24-.01h.16l.06.01h8.16v-.83H6.18l-.01-2.75-.02-.37.05-.34.11-.31.17-.28.25-.26.31-.23.38-.2.44-.18.51-.15.58-.12.64-.1.71-.06.77-.04.84-.02 1.27.05zm-6.3 1.98l-.23.33-.08.41.08.41.23.34.33.22.41.09.41-.09.33-.22.23-.34.08-.41-.08-.41-.23-.33-.33-.22-.41-.09-.41.09zm13.09 3.95l.28.06.32.12.35.18.36.27.36.35.35.47.32.59.28.73.21.88.14 1.04.05 1.23-.06 1.23-.16 1.04-.24.86-.32.71-.36.57-.4.45-.42.33-.42.24-.4.16-.36.09-.32.05-.24.02-.16-.01h-8.22v.82h5.84l.01 2.76.02.36-.05.34-.11.31-.17.29-.25.25-.31.24-.38.2-.44.17-.51.15-.58.13-.64.09-.71.07-.77.04-.84.01-1.27-.04-1.07-.14-.9-.2-.73-.25-.59-.3-.45-.33-.34-.34-.25-.34-.16-.33-.1-.3-.04-.25-.02-.2.01-.13v-5.34l.05-.64.13-.54.21-.46.26-.38.3-.32.33-.24.35-.2.35-.14.33-.1.3-.06.26-.04.21-.02.13-.01h5.84l.69-.05.59-.14.5-.21.41-.28.33-.32.27-.35.2-.36.15-.36.1-.35.07-.32.04-.28.02-.21V6.07h2.09l.14.01zm-6.47 14.25l-.23.33-.08.41.08.41.23.33.33.23.41.08.41-.08.33-.23.23-.33.08-.41-.08-.41-.23-.33-.33-.23-.41-.08-.41.08z","hex":"3776AB"},{"id":"java","t":"Java","sub":"Java (JDK)","ext":".java","d":"M11.915 0 11.7.215C9.515 2.4 7.47 6.39 6.046 10.483c-1.064 1.024-3.633 2.81-3.711 3.551-.093.87 1.746 2.611 1.55 3.235-.198.625-1.304 1.408-1.014 1.939.1.188.823.011 1.277-.491a13.389 13.389 0 0 0-.017 2.14c.076.906.27 1.668.643 2.232.372.563.956.911 1.667.911.397 0 .727-.114 1.024-.264.298-.149.571-.33.91-.5.68-.34 1.634-.666 3.53-.604 1.903.062 2.872.39 3.559.704.687.314 1.15.664 1.925.664.767 0 1.395-.336 1.807-.9.412-.563.631-1.33.72-2.24.06-.623.055-1.32 0-2.066.454.45 1.117.604 1.213.424.29-.53-.816-1.314-1.013-1.937-.198-.624 1.642-2.366 1.549-3.236-.08-.748-2.707-2.568-3.748-3.586C16.428 6.374 14.308 2.394 12.13.215zm.175 6.038a2.95 2.95 0 0 1 2.943 2.942 2.95 2.95 0 0 1-2.943 2.943A2.95 2.95 0 0 1 9.148 8.98a2.95 2.95 0 0 1 2.942-2.942zM8.685 7.983a3.515 3.515 0 0 0-.145.997c0 1.951 1.6 3.55 3.55 3.55 1.95 0 3.55-1.598 3.55-3.55 0-.329-.046-.648-.132-.951.334.095.64.208.915.336a42.699 42.699 0 0 1 2.042 5.829c.678 2.545 1.01 4.92.846 6.607-.082.844-.29 1.51-.606 1.94-.315.431-.713.651-1.315.651-.593 0-.932-.27-1.673-.61-.741-.338-1.825-.694-3.792-.758-1.974-.064-3.073.293-3.821.669-.375.188-.659.373-.911.5s-.466.2-.752.2c-.53 0-.876-.209-1.16-.64-.285-.43-.474-1.101-.545-1.948-.141-1.693.176-4.069.823-6.614a43.155 43.155 0 0 1 1.934-5.783c.348-.167.749-.31 1.192-.425zm-3.382 4.362a.216.216 0 0 1 .13.031c-.166.56-.323 1.116-.463 1.665a33.849 33.849 0 0 0-.547 2.555 3.9 3.9 0 0 0-.2-.39c-.58-1.012-.914-1.642-1.16-2.08.315-.24 1.679-1.755 2.24-1.781zm13.394.01c.562.027 1.926 1.543 2.24 1.783-.246.438-.58 1.068-1.16 2.08a4.428 4.428 0 0 0-.163.309 32.354 32.354 0 0 0-.562-2.49 40.579 40.579 0 0 0-.482-1.652.216.216 0 0 1 .127-.03z","hex":"000000"},{"id":"sql","t":"SQL","sub":"SQL (e.g., PostgreSQL)","ext":".sql","lucide":"database","hex":"7C3AED"},{"id":"lua","t":"Lua","sub":"Lua 5.1 / 5.4","ext":".lua","d":"M.38 10.377l-.272-.037c-.048.344-.082.695-.101 1.041l.275.016c.018-.34.051-.682.098-1.02zM4.136 3.289l-.184-.205c-.258.232-.509.48-.746.734l.202.188c.231-.248.476-.49.728-.717zM5.769 2.059l-.146-.235c-.296.186-.586.385-.863.594l.166.219c.27-.203.554-.399.843-.578zM1.824 18.369c.185.297.384.586.593.863l.22-.164c-.205-.271-.399-.555-.58-.844l-.233.145zM1.127 16.402l-.255.104c.129.318.274.635.431.943l.005.01.245-.125-.005-.01c-.153-.301-.295-.611-.421-.922zM.298 9.309l.269.063c.076-.332.168-.664.272-.986l-.261-.087c-.108.332-.202.672-.28 1.01zM.274 12.42l-.275.01c.012.348.04.699.083 1.043l.273-.033c-.042-.336-.069-.68-.081-1.02zM.256 14.506c.073.34.162.682.264 1.014l.263-.08c-.1-.326-.187-.658-.258-.99l-.269.056zM11.573.275L11.563 0c-.348.012-.699.039-1.044.082l.034.273c.338-.041.68-.068 1.02-.08zM23.221 8.566c.1.326.186.66.256.992l.27-.059c-.072-.34-.16-.682-.262-1.014l-.264.081zM17.621 1.389c-.309-.164-.627-.314-.947-.449l-.107.252c.314.133.625.281.926.439l.128-.242zM15.693.572c-.332-.105-.67-.199-1.01-.277l-.063.268c.332.076.664.168.988.273l.085-.264zM6.674 1.545c.298-.15.606-.291.916-.418L7.486.873c-.317.127-.632.272-.937.428l-.015.008.125.244.015-.008zM23.727 11.588l.275-.01a11.797 11.797 0 0 0-.082-1.045l-.273.033c.041.338.068.682.08 1.022zM13.654.105c-.346-.047-.696-.08-1.043-.098l-.014.273c.339.018.683.051 1.019.098l.038-.273zM9.544.527l-.058-.27c-.34.072-.681.16-1.014.264l.081.262c.325-.099.659-.185.991-.256zM1.921 5.469l.231.15c.185-.285.384-.566.592-.834l-.217-.17c-.213.276-.417.563-.606.854zM.943 7.318l.253.107c.132-.313.28-.625.439-.924l-.243-.128c-.163.307-.314.625-.449.945zM18.223 21.943l.145.234c.295-.186.586-.385.863-.594l-.164-.219c-.272.204-.557.4-.844.579zM21.248 19.219l.217.17c.215-.273.418-.561.607-.854l-.23-.148c-.186.285-.385.564-.594.832zM19.855 20.715l.184.203c.258-.23.51-.479.746-.732l-.201-.188c-.23.248-.477.488-.729.717zM22.359 17.504l.244.129c.162-.307.314-.625.449-.945l-.254-.107a11.27 11.27 0 0 1-.439.923zM23.617 13.629l.273.039c.049-.346.082-.695.102-1.043l-.275-.014c-.018.338-.051.682-.1 1.018zM23.156 15.621l.264.086c.107-.332.201-.67.279-1.01l-.268-.063c-.077.333-.169.665-.275.987zM22.453 6.672c.154.303.297.617.424.932l.256-.104c-.131-.322-.277-.643-.436-.953l-.244.125zM8.296 23.418c.331.107.67.201 1.009.279l.062-.268c-.331-.076-.663-.168-.986-.273l-.085.262zM10.335 23.889c.345.049.696.082 1.043.102l.014-.275c-.339-.018-.682-.051-1.019-.098l-.038.271zM17.326 22.449c-.303.154-.613.297-.926.424l.104.256c.318-.131.639-.275.947-.434l.004-.002-.123-.246-.006.002zM4.613 21.467c.274.213.562.418.854.605l.149-.23c-.285-.184-.565-.385-.833-.592l-.17.217zM12.417 23.725l.009.275c.348-.014.699-.041 1.045-.084l-.035-.271c-.336.041-.68.068-1.019.08zM6.37 22.604c.307.162.625.314.946.449l.107-.254c-.313-.133-.624-.279-.924-.439l-.129.244zM3.083 20.041c.233.258.48.51.734.746l.188-.201c-.249-.23-.49-.477-.717-.729l-.205.184zM14.445 23.475l.059.27c.34-.074.68-.162 1.014-.266l-.082-.262c-.325.099-.659.185-.991.258zM21.18.129A2.689 2.689 0 1 0 21.18 5.507 2.689 2.689 0 1 0 21.18.129zM15.324 15.447c0 .471.314.66.852.66.67 0 1.297-.396 1.297-1.016v-.645c-.23.107-.379.141-1.107.24-.735.109-1.042.306-1.042.761zM12 2.818c-5.07 0-9.18 4.109-9.18 9.18 0 5.068 4.11 9.18 9.18 9.18 5.07 0 9.18-4.111 9.18-9.18 0-5.07-4.11-9.18-9.18-9.18zm-2.487 13.77H5.771v-6.023h.769v5.346h2.974v.677zm4.13 0h-.619v-.67c-.405.57-.811.793-1.446.793-.843 0-1.38-.463-1.38-1.182v-3.271h.686v3c0 .52.347.85.893.85.719 0 1.181-.578 1.181-1.461v-2.389h.686v4.33zm-.53-8.393c0-1.484 1.205-2.689 2.689-2.689s2.688 1.205 2.688 2.689-1.203 2.688-2.688 2.688-2.689-1.203-2.689-2.688zm5.567 7.856v.52c-.223.059-.33.074-.471.074-.34 0-.637-.238-.711-.57-.381.406-.918.637-1.471.637-.877 0-1.422-.463-1.422-1.248 0-.527.256-.916.76-1.123.266-.107.414-.141 1.389-.264.545-.066.719-.191.719-.48v-.182c0-.412-.348-.645-.967-.645-.645 0-.957.24-1.016.77h-.693c.041-1 .686-1.404 1.734-1.404 1.066 0 1.627.412 1.627 1.182v2.412c0 .215.133.338.373.338.041-.002.074-.002.149-.017z","hex":"000080"},{"id":"c","t":"C","sub":"C (GCC/Clang)","ext":".c","d":"M16.5921 9.1962s-.354-3.298-3.627-3.39c-3.2741-.09-4.9552 2.474-4.9552 6.14 0 3.6651 1.858 6.5972 5.0451 6.5972 3.184 0 3.5381-3.665 3.5381-3.665l6.1041.365s.36 3.31-2.196 5.836c-2.552 2.5241-5.6901 2.9371-7.8762 2.9201-2.19-.017-5.2261.034-8.1602-2.97-2.938-3.0101-3.436-5.9302-3.436-8.8002 0-2.8701.556-6.6702 4.047-9.5502C7.444.72 9.849 0 12.254 0c10.0422 0 10.7172 9.2602 10.7172 9.2602z","hex":"A8B9CC"},{"id":"cpp","t":"C++","sub":"C++ (GCC/Clang)","ext":".cpp","d":"M22.394 6c-.167-.29-.398-.543-.652-.69L12.926.22c-.509-.294-1.34-.294-1.848 0L2.26 5.31c-.508.293-.923 1.013-.923 1.6v10.18c0 .294.104.62.271.91.167.29.398.543.652.69l8.816 5.09c.508.293 1.34.293 1.848 0l8.816-5.09c.254-.147.485-.4.652-.69.167-.29.27-.616.27-.91V6.91c.003-.294-.1-.62-.268-.91zM12 19.11c-3.92 0-7.109-3.19-7.109-7.11 0-3.92 3.19-7.11 7.11-7.11a7.133 7.133 0 016.156 3.553l-3.076 1.78a3.567 3.567 0 00-3.08-1.78A3.56 3.56 0 008.444 12 3.56 3.56 0 0012 15.555a3.57 3.57 0 003.08-1.778l3.078 1.78A7.135 7.135 0 0112 19.11zm7.11-6.715h-.79v.79h-.79v-.79h-.79v-.79h.79v-.79h.79v.79h.79zm2.962 0h-.79v.79h-.79v-.79h-.79v-.79h.79v-.79h.79v.79h.79z","hex":"00599C"},{"id":"rust","t":"Rust","sub":"Rust (Cargo)","ext":".rs","d":"M23.8346 11.7033l-1.0073-.6236a13.7268 13.7268 0 00-.0283-.2936l.8656-.8069a.3483.3483 0 00-.1154-.578l-1.1066-.414a8.4958 8.4958 0 00-.087-.2856l.6904-.9587a.3462.3462 0 00-.2257-.5446l-1.1663-.1894a9.3574 9.3574 0 00-.1407-.2622l.49-1.0761a.3437.3437 0 00-.0274-.3361.3486.3486 0 00-.3006-.154l-1.1845.0416a6.7444 6.7444 0 00-.1873-.2268l.2723-1.153a.3472.3472 0 00-.417-.4172l-1.1532.2724a14.0183 14.0183 0 00-.2278-.1873l.0415-1.1845a.3442.3442 0 00-.49-.328l-1.076.491c-.0872-.0476-.1742-.0952-.2623-.1407l-.1903-1.1673A.3483.3483 0 0016.256.955l-.9597.6905a8.4867 8.4867 0 00-.2855-.086l-.414-1.1066a.3483.3483 0 00-.5781-.1154l-.8069.8666a9.2936 9.2936 0 00-.2936-.0284L12.2946.1683a.3462.3462 0 00-.5892 0l-.6236 1.0073a13.7383 13.7383 0 00-.2936.0284L9.9803.3374a.3462.3462 0 00-.578.1154l-.4141 1.1065c-.0962.0274-.1903.0567-.2855.086L7.744.955a.3483.3483 0 00-.5447.2258L7.009 2.348a9.3574 9.3574 0 00-.2622.1407l-1.0762-.491a.3462.3462 0 00-.49.328l.0416 1.1845a7.9826 7.9826 0 00-.2278.1873L3.8413 3.425a.3472.3472 0 00-.4171.4171l.2713 1.1531c-.0628.075-.1255.1509-.1863.2268l-1.1845-.0415a.3462.3462 0 00-.328.49l.491 1.0761a9.167 9.167 0 00-.1407.2622l-1.1662.1894a.3483.3483 0 00-.2258.5446l.6904.9587a13.303 13.303 0 00-.087.2855l-1.1065.414a.3483.3483 0 00-.1155.5781l.8656.807a9.2936 9.2936 0 00-.0283.2935l-1.0073.6236a.3442.3442 0 000 .5892l1.0073.6236c.008.0982.0182.1964.0283.2936l-.8656.8079a.3462.3462 0 00.1155.578l1.1065.4141c.0273.0962.0567.1914.087.2855l-.6904.9587a.3452.3452 0 00.2268.5447l1.1662.1893c.0456.088.0922.1751.1408.2622l-.491 1.0762a.3462.3462 0 00.328.49l1.1834-.0415c.0618.0769.1235.1528.1873.2277l-.2713 1.1541a.3462.3462 0 00.4171.4161l1.153-.2713c.075.0638.151.1255.2279.1863l-.0415 1.1845a.3442.3442 0 00.49.327l1.0761-.49c.087.0486.1741.0951.2622.1407l.1903 1.1662a.3483.3483 0 00.5447.2268l.9587-.6904a9.299 9.299 0 00.2855.087l.414 1.1066a.3452.3452 0 00.5781.1154l.8079-.8656c.0972.0111.1954.0203.2936.0294l.6236 1.0073a.3472.3472 0 00.5892 0l.6236-1.0073c.0982-.0091.1964-.0183.2936-.0294l.8069.8656a.3483.3483 0 00.578-.1154l.4141-1.1066a8.4626 8.4626 0 00.2855-.087l.9587.6904a.3452.3452 0 00.5447-.2268l.1903-1.1662c.088-.0456.1751-.0931.2622-.1407l1.0762.49a.3472.3472 0 00.49-.327l-.0415-1.1845a6.7267 6.7267 0 00.2267-.1863l1.1531.2713a.3472.3472 0 00.4171-.416l-.2713-1.1542c.0628-.0749.1255-.1508.1863-.2278l1.1845.0415a.3442.3442 0 00.328-.49l-.49-1.076c.0475-.0872.0951-.1742.1407-.2623l1.1662-.1893a.3483.3483 0 00.2258-.5447l-.6904-.9587.087-.2855 1.1066-.414a.3462.3462 0 00.1154-.5781l-.8656-.8079c.0101-.0972.0202-.1954.0283-.2936l1.0073-.6236a.3442.3442 0 000-.5892zm-6.7413 8.3551a.7138.7138 0 01.2986-1.396.714.714 0 11-.2997 1.396zm-.3422-2.3142a.649.649 0 00-.7715.5l-.3573 1.6685c-1.1035.501-2.3285.7795-3.6193.7795a8.7368 8.7368 0 01-3.6951-.814l-.3574-1.6684a.648.648 0 00-.7714-.499l-1.473.3158a8.7216 8.7216 0 01-.7613-.898h7.1676c.081 0 .1356-.0141.1356-.088v-2.536c0-.074-.0536-.0881-.1356-.0881h-2.0966v-1.6077h2.2677c.2065 0 1.1065.0587 1.394 1.2088.0901.3533.2875 1.5044.4232 1.8729.1346.413.6833 1.2381 1.2685 1.2381h3.5716a.7492.7492 0 00.1296-.0131 8.7874 8.7874 0 01-.8119.9526zM6.8369 20.024a.714.714 0 11-.2997-1.396.714.714 0 01.2997 1.396zM4.1177 8.9972a.7137.7137 0 11-1.304.5791.7137.7137 0 011.304-.579zm-.8352 1.9813l1.5347-.6824a.65.65 0 00.33-.8585l-.3158-.7147h1.2432v5.6025H3.5669a8.7753 8.7753 0 01-.2834-3.348zm6.7343-.5437V8.7836h2.9601c.153 0 1.0792.1772 1.0792.8697 0 .575-.7107.7815-1.2948.7815zm10.7574 1.4862c0 .2187-.008.4363-.0243.651h-.9c-.09 0-.1265.0586-.1265.1477v.413c0 .973-.5487 1.1846-1.0296 1.2382-.4576.0517-.9648-.1913-1.0275-.4717-.2704-1.5186-.7198-1.8436-1.4305-2.4034.8817-.5599 1.799-1.386 1.799-2.4915 0-1.1936-.819-1.9458-1.3769-2.3153-.7825-.5163-1.6491-.6195-1.883-.6195H5.4682a8.7651 8.7651 0 014.907-2.7699l1.0974 1.151a.648.648 0 00.9182.0213l1.227-1.1743a8.7753 8.7753 0 016.0044 4.2762l-.8403 1.8982a.652.652 0 00.33.8585l1.6178.7188c.0283.2875.0425.577.0425.8717zm-9.3006-9.5993a.7128.7128 0 11.984 1.0316.7137.7137 0 01-.984-1.0316zm8.3389 6.71a.7107.7107 0 01.9395-.3625.7137.7137 0 11-.9405.3635z","hex":"000000"},{"id":"go","t":"Go","sub":"Go (Golang)","ext":".go","d":"M1.811 10.231c-.047 0-.058-.023-.035-.059l.246-.315c.023-.035.081-.058.128-.058h4.172c.046 0 .058.035.035.07l-.199.303c-.023.036-.082.07-.117.07zM.047 11.306c-.047 0-.059-.023-.035-.058l.245-.316c.023-.035.082-.058.129-.058h5.328c.047 0 .07.035.058.07l-.093.28c-.012.047-.058.07-.105.07zm2.828 1.075c-.047 0-.059-.035-.035-.07l.163-.292c.023-.035.07-.07.117-.07h2.337c.047 0 .07.035.07.082l-.023.28c0 .047-.047.082-.082.082zm12.129-2.36c-.736.187-1.239.327-1.963.514-.176.046-.187.058-.34-.117-.174-.199-.303-.327-.548-.444-.737-.362-1.45-.257-2.115.175-.795.514-1.204 1.274-1.192 2.22.011.935.654 1.706 1.577 1.835.795.105 1.46-.175 1.987-.77.105-.13.198-.27.315-.434H10.47c-.245 0-.304-.152-.222-.35.152-.362.432-.97.596-1.274a.315.315 0 01.292-.187h4.253c-.023.316-.023.631-.07.947a4.983 4.983 0 01-.958 2.29c-.841 1.11-1.94 1.8-3.33 1.986-1.145.152-2.209-.07-3.143-.77-.865-.655-1.356-1.52-1.484-2.595-.152-1.274.222-2.419.993-3.424.83-1.086 1.928-1.776 3.272-2.02 1.098-.2 2.15-.07 3.096.571.62.41 1.063.97 1.356 1.648.07.105.023.164-.117.2m3.868 6.461c-1.064-.024-2.034-.328-2.852-1.029a3.665 3.665 0 01-1.262-2.255c-.21-1.32.152-2.489.947-3.529.853-1.122 1.881-1.706 3.272-1.95 1.192-.21 2.314-.095 3.33.595.923.63 1.496 1.484 1.648 2.605.198 1.578-.257 2.863-1.344 3.962-.771.783-1.718 1.273-2.805 1.495-.315.06-.63.07-.934.106zm2.78-4.72c-.011-.153-.011-.27-.034-.387-.21-1.157-1.274-1.81-2.384-1.554-1.087.245-1.788.935-2.045 2.033-.21.912.234 1.835 1.075 2.21.643.28 1.285.244 1.905-.07.923-.48 1.425-1.228 1.484-2.233z","hex":"00ADD8"},{"id":"ruby","t":"Ruby","sub":"Ruby","ext":".rb","d":"M20.156.083c3.033.525 3.893 2.598 3.829 4.77L24 4.822 22.635 22.71 4.89 23.926h.016C3.433 23.864.15 23.729 0 19.139l1.645-3 2.819 6.586.503 1.172 2.805-9.144-.03.007.016-.03 9.255 2.956-1.396-5.431-.99-3.9 8.82-.569-.615-.51L16.5 2.114 20.159.073l-.003.01zM0 19.089zM5.13 5.073c3.561-3.533 8.157-5.621 9.922-3.84 1.762 1.777-.105 6.105-3.673 9.636-3.563 3.532-8.103 5.734-9.864 3.957-1.766-1.777.045-6.217 3.612-9.75l.003-.003z","hex":"CC342D"},{"id":"php","t":"PHP","sub":"PHP","ext":".php","d":"M7.01 10.207h-.944l-.515 2.648h.838c.556 0 .97-.105 1.242-.314.272-.21.455-.559.55-1.049.092-.47.05-.802-.124-.995-.175-.193-.523-.29-1.047-.29zM12 5.688C5.373 5.688 0 8.514 0 12s5.373 6.313 12 6.313S24 15.486 24 12c0-3.486-5.373-6.312-12-6.312zm-3.26 7.451c-.261.25-.575.438-.917.551-.336.108-.765.164-1.285.164H5.357l-.327 1.681H3.652l1.23-6.326h2.65c.797 0 1.378.209 1.744.628.366.418.476 1.002.33 1.752a2.836 2.836 0 0 1-.305.847c-.143.255-.33.49-.561.703zm4.024.715l.543-2.799c.063-.318.039-.536-.068-.651-.107-.116-.336-.174-.687-.174H11.46l-.704 3.625H9.388l1.23-6.327h1.367l-.327 1.682h1.218c.767 0 1.295.134 1.586.401s.378.7.263 1.299l-.572 2.944h-1.389zm7.597-2.265a2.782 2.782 0 0 1-.305.847c-.143.255-.33.49-.561.703a2.44 2.44 0 0 1-.917.551c-.336.108-.765.164-1.286.164h-1.18l-.327 1.682h-1.378l1.23-6.326h2.649c.797 0 1.378.209 1.744.628.366.417.477 1.001.331 1.751zM17.766 10.207h-.943l-.516 2.648h.838c.557 0 .971-.105 1.242-.314.272-.21.455-.559.551-1.049.092-.47.049-.802-.125-.995s-.524-.29-1.047-.29z","hex":"777BB4"},{"id":"r","t":"R","sub":"R","ext":".r","d":"M12 2.746c-6.627 0-12 3.599-12 8.037 0 3.897 4.144 7.144 9.64 7.88V16.26c-2.924-.915-4.925-2.755-4.925-4.877 0-3.035 4.084-5.494 9.12-5.494 5.038 0 8.757 1.683 8.757 5.494 0 1.976-.999 3.379-2.662 4.272.09.066.174.128.258.216.169.149.25.363.372.544 2.128-1.45 3.44-3.437 3.44-5.631 0-4.44-5.373-8.038-12-8.038zm-2.111 4.99v13.516l4.093-.002-.002-5.291h1.1c.225 0 .321.066.549.25.272.22.715.982.715.982l2.164 4.063 4.627-.002-2.864-4.826s-.086-.193-.265-.383a2.22 2.22 0 00-.582-.416c-.422-.214-1.149-.434-1.149-.434s3.578-.264 3.578-3.826c0-3.562-3.744-3.63-3.744-3.63zm4.127 2.93l2.478.002s1.149-.062 1.149 1.127c0 1.165-1.149 1.17-1.149 1.17h-2.478zm1.754 6.119c-.494.049-1.012.079-1.54.088v1.807a16.622 16.622 0 002.37-.473l-.471-.891s-.108-.183-.248-.394c-.039-.054-.08-.098-.111-.137z","hex":"276DC3"},{"id":"kotlin","t":"Kotlin","sub":"Kotlin (JVM)","ext":".kt","d":"M24 24H0V0h24L12 12Z","hex":"7F52FF"},{"id":"swift","t":"Swift","sub":"Swift","ext":".swift","d":"M7.508 0c-.287 0-.573 0-.86.002-.241.002-.483.003-.724.01-.132.003-.263.009-.395.015A9.154 9.154 0 0 0 4.348.15 5.492 5.492 0 0 0 2.85.645 5.04 5.04 0 0 0 .645 2.848c-.245.48-.4.972-.495 1.5-.093.52-.122 1.05-.136 1.576a35.2 35.2 0 0 0-.012.724C0 6.935 0 7.221 0 7.508v8.984c0 .287 0 .575.002.862.002.24.005.481.012.722.014.526.043 1.057.136 1.576.095.528.25 1.02.495 1.5a5.03 5.03 0 0 0 2.205 2.203c.48.244.97.4 1.498.495.52.093 1.05.124 1.576.138.241.007.483.009.724.01.287.002.573.002.86.002h8.984c.287 0 .573 0 .86-.002.241-.001.483-.003.724-.01a10.523 10.523 0 0 0 1.578-.138 5.322 5.322 0 0 0 1.498-.495 5.035 5.035 0 0 0 2.203-2.203c.245-.48.4-.972.495-1.5.093-.52.124-1.05.138-1.576.007-.241.009-.481.01-.722.002-.287.002-.575.002-.862V7.508c0-.287 0-.573-.002-.86a33.662 33.662 0 0 0-.01-.724 10.5 10.5 0 0 0-.138-1.576 5.328 5.328 0 0 0-.495-1.5A5.039 5.039 0 0 0 21.152.645 5.32 5.32 0 0 0 19.654.15a10.493 10.493 0 0 0-1.578-.138 34.98 34.98 0 0 0-.722-.01C17.067 0 16.779 0 16.492 0H7.508zm6.035 3.41c4.114 2.47 6.545 7.162 5.549 11.131-.024.093-.05.181-.076.272l.002.001c2.062 2.538 1.5 5.258 1.236 4.745-1.072-2.086-3.066-1.568-4.088-1.043a6.803 6.803 0 0 1-.281.158l-.02.012-.002.002c-2.115 1.123-4.957 1.205-7.812-.022a12.568 12.568 0 0 1-5.64-4.838c.649.48 1.35.902 2.097 1.252 3.019 1.414 6.051 1.311 8.197-.002C9.651 12.73 7.101 9.67 5.146 7.191a10.628 10.628 0 0 1-1.005-1.384c2.34 2.142 6.038 4.83 7.365 5.576C8.69 8.408 6.208 4.743 6.324 4.86c4.436 4.47 8.528 6.996 8.528 6.996.154.085.27.154.36.213.085-.215.16-.437.224-.668.708-2.588-.09-5.548-1.893-7.992z","hex":"F05138"},{"id":"ts","t":"TypeScript","sub":"TypeScript","ext":".ts","d":"M1.125 0C.502 0 0 .502 0 1.125v21.75C0 23.498.502 24 1.125 24h21.75c.623 0 1.125-.502 1.125-1.125V1.125C24 .502 23.498 0 22.875 0zm17.363 9.75c.612 0 1.154.037 1.627.111a6.38 6.38 0 0 1 1.306.34v2.458a3.95 3.95 0 0 0-.643-.361 5.093 5.093 0 0 0-.717-.26 5.453 5.453 0 0 0-1.426-.2c-.3 0-.573.028-.819.086a2.1 2.1 0 0 0-.623.242c-.17.104-.3.229-.393.374a.888.888 0 0 0-.14.49c0 .196.053.373.156.529.104.156.252.304.443.444s.423.276.696.41c.273.135.582.274.926.416.47.197.892.407 1.266.628.374.222.695.473.963.753.268.279.472.598.614.957.142.359.214.776.214 1.253 0 .657-.125 1.21-.373 1.656a3.033 3.033 0 0 1-1.012 1.085 4.38 4.38 0 0 1-1.487.596c-.566.12-1.163.18-1.79.18a9.916 9.916 0 0 1-1.84-.164 5.544 5.544 0 0 1-1.512-.493v-2.63a5.033 5.033 0 0 0 3.237 1.2c.333 0 .624-.03.872-.09.249-.06.456-.144.623-.25.166-.108.29-.234.373-.38a1.023 1.023 0 0 0-.074-1.089 2.12 2.12 0 0 0-.537-.5 5.597 5.597 0 0 0-.807-.444 27.72 27.72 0 0 0-1.007-.436c-.918-.383-1.602-.852-2.053-1.405-.45-.553-.676-1.222-.676-2.005 0-.614.123-1.141.369-1.582.246-.441.58-.804 1.004-1.089a4.494 4.494 0 0 1 1.47-.629 7.536 7.536 0 0 1 1.77-.201zm-15.113.188h9.563v2.166H9.506v9.646H6.789v-9.646H3.375z","hex":"3178C6"},{"id":"scala","t":"Scala","sub":"Scala (JVM)","ext":".scala","d":"M4.589 24c4.537 0 13.81-1.516 14.821-3v-5.729c-.957 1.408-10.284 2.912-14.821 2.912V24zM4.589 16.365c4.537 0 13.81-1.516 14.821-3V7.636c-.957 1.408-10.284 2.912-14.821 2.912v5.817zM4.589 8.729c4.537 0 13.81-1.516 14.821-3V0C18.453 1.408 9.126 2.912 4.589 2.912v5.817z","hex":"DC322F"},{"id":"cs","t":"C#","sub":"C# (.NET)","ext":".cs","badge":"C#","hex":"512BD4"},{"id":"hs","t":"Haskell","sub":"Haskell (GHC)","ext":".hs","d":"M0 3.535L5.647 12 0 20.465h4.235L9.883 12 4.235 3.535zm5.647 0L11.294 12l-5.647 8.465h4.235l3.53-5.29 3.53 5.29h4.234L9.883 3.535zm8.941 4.938l1.883 2.822H24V8.473zm2.824 4.232l1.882 2.822H24v-2.822z","hex":"5D4F85"},{"id":"dart","t":"Dart","sub":"Dart","ext":".dart","d":"M4.105 4.105S9.158 1.58 11.684.316a3.079 3.079 0 0 1 1.481-.315c.766.047 1.677.788 1.677.788L24 9.948v9.789h-4.263V24H9.789l-9-9C.303 14.5 0 13.795 0 13.105c0-.319.18-.818.316-1.105l3.789-7.895zm.679.679v11.787c.002.543.021 1.024.498 1.508L10.204 23h8.533v-4.263L4.784 4.784zm12.055-.678c-.899-.896-1.809-1.78-2.74-2.643-.302-.267-.567-.468-1.07-.462-.37.014-.87.195-.87.195L6.341 4.105l10.498.001z","hex":"0175C2"},{"id":"ex","t":"Elixir","sub":"Elixir (BEAM)","ext":".ex","d":"M19.793 16.575c0 3.752-2.927 7.426-7.743 7.426-5.249 0-7.843-3.71-7.843-8.29 0-5.21 3.892-12.952 8-15.647a.397.397 0 0 1 .61.371 9.716 9.716 0 0 0 1.694 6.518c.522.795 1.092 1.478 1.763 2.352.94 1.227 1.637 1.906 2.644 3.842l.015.028a7.107 7.107 0 0 1 .86 3.4z","hex":"4B275F"},{"id":"basic","t":"BASIC","sub":"BASIC","ext":".bas","badge":"B","hex":"1687F8"},{"id":"txt","t":"Plain text","sub":"Unstructured text files","ext":".txt","lucide":"doc","hex":"64748B"},{"id":"json","t":"JSON","sub":"JSON data","ext":".json","lucide":"braces","hex":"64748B"},{"id":"other","t":"Other","sub":"Custom or domain-specific language","ext":"","lucide":"code","hex":"64748B"},{"id":"","t":"Not specified","sub":"Select later","ext":"","lucide":"dots","hex":"64748B"}];

// Small, hand-written illustrations of each notation. They are examples of the
// format, not tested grammars; the test suite parses every one of them.
const INP_EXAMPLES = [
  { id: "bnf", t: "BNF", file: "expr.bnf", code:
`<start> ::= <expr>
<expr>  ::= <term> | <term> " + " <expr>
<term>  ::= <digit> | "(" <expr> ")"
<digit> ::= "0" | "1" | "2"` },
  { id: "ebnf", t: "EBNF", file: "list.ebnf", code:
`<start> ::= <item> ("," <item>)*
<item>  ::= <word> | <word> " " <word>
<word>  ::= "a" | "b" | "c"` },
  { id: "antlr", t: "ANTLR", file: "Expr.g4", code:
`grammar Expr;
start : expr ;
expr  : term ('+' term)* ;
term  : DIGIT | '(' expr ')' ;
DIGIT : [0-9] ;` },
  { id: "fan", t: "Fandango", file: "expr.fan", code:
`<start> ::= <expr>
<expr> ::= <term> | <term> " + " <expr>
<term> ::= <digit>
<digit> ::= "0" | "1"` },
];


// Decorative only; colours come from the theme tokens so dark mode needs no second copy.
const inpArt = id => `<svg viewBox="0 0 320 170" role="presentation" focusable="false">
  <path d="M30 96c-10-38 24-70 64-62 34-30 96-24 112 10 40-6 76 24 66 60-8 30-40 46-76 40-40 30-110 26-136-8-20-2-28-16-30-40z" fill="#1687F8" opacity=".12"/>
  <ellipse cx="226" cy="64" rx="70" ry="46" fill="#9333EA" opacity=".10"/>
  <rect x="96" y="30" width="128" height="104" rx="12" fill="var(--color-surface)" stroke="var(--color-border)" stroke-width="2"/>
  <path d="M114 56h56M114 72h82M114 88h64" stroke="#1687F8" stroke-width="6" stroke-linecap="round" opacity=".8"/>
  <rect x="180" y="96" width="62" height="52" rx="10" fill="#9333EA"/>
  <text x="211" y="130" text-anchor="middle" font-family="ui-sans-serif, system-ui, sans-serif" font-size="${(LANG_ABBR[id] || "").length > 2 ? 17 : 22}" font-weight="700" fill="#fff">${esc(LANG_ABBR[id] ?? "")}</text>
</svg>`;


// Where a person can get a grammar for each language, and what the upstream project calls its
// versions. Looked up in antlr/grammars-v4 on 2026-10-05; SpreadEx bundles none of these (the
// repository has no single licence -- each grammar carries its own), so every block below is
// shown inactive and the guidance points at Import / Provide instead.
const GV4 = "https://github.com/antlr/grammars-v4/tree/master/";
const LANG_PACKS = {
  js:   { dir: "javascript", blocks: [["ECMAScript 5.1", "javascript/ecmascript"], ["Modern JavaScript", "javascript/javascript"], ["JSX", "javascript/jsx"]] },
  ts:   { dir: "javascript/typescript", blocks: [["TypeScript", "javascript/typescript"]] },
  py:   { dir: "python", blocks: [["Python 3.14", "python/python3_14"], ["Python 3 (3.6-based)", "python/python3"], ["Python 2.7", "python/python2_7_18"]] },
  java: { dir: "java", blocks: [["Java (latest)", "java/java"], ["Java 20", "java/java20"], ["Java 9", "java/java9"], ["Java 8", "java/java8"]] },
  sql:  { dir: "sql", blocks: [["SQLite", "sql/sqlite"], ["PostgreSQL", "sql/postgresql"], ["MySQL", "sql/mysql"], ["T-SQL", "sql/tsql"], ["PL/SQL", "sql/plsql"]] },
  lua:  { dir: "lua", blocks: [["Lua", "lua"]] },
  c:    { dir: "c", blocks: [["C", "c"]] },
  cpp:  { dir: "cpp", blocks: [["C++", "cpp"]] },
  rust: { dir: "rust", blocks: [["Rust (1.60 reference)", "rust"]] },
  go:   { dir: "golang", blocks: [["Go", "golang"]] },
  php:  { dir: "php", blocks: [["PHP", "php"]] },
  r:    { dir: "r", blocks: [["R", "r"]] },
  kotlin: { dir: "kotlin", blocks: [["Kotlin", "kotlin"]] },
  swift:  { dir: "swift", blocks: [["Swift", "swift"]] },
  scala:  { dir: "scala", blocks: [["Scala", "scala"]] },
  cs:   { dir: "csharp", blocks: [["C#", "csharp"]] },
  hs:   { dir: "haskell", blocks: [["Haskell", "haskell"]] },
  dart: { dir: "dart2", blocks: [["Dart 2", "dart2"]] },
  ex:   { dir: "elixir", blocks: [["Elixir", "elixir"]] },
  basic:{ dir: "basic", blocks: [["jvmBASIC", "basic"]] },
  json: { dir: "json", blocks: [["JSON", "json"]] },
  ruby: { dir: "", blocks: [] },   // no Ruby grammar in grammars-v4
};

// The picture above the help column names the chosen language on its badge.
const LANG_ABBR = { js: "JS", py: "PY", java: "JV", sql: "SQL", lua: "LUA", c: "C", cpp: "C++", rust: "RS",
  go: "GO", ruby: "RB", php: "PHP", r: "R", kotlin: "KT", swift: "SW", ts: "TS", scala: "SC", cs: "C#",
  hs: "HS", dart: "DT", ex: "EX", basic: "BAS", txt: "TXT", json: "{}", other: "</>", "": "…" };

// A (?) that explains itself on hover AND keyboard focus, and can be dismissed with Escape
// (WCAG 1.4.13). The text is also the button's accessible name, so a screen reader gets it
// without having to find the tooltip.
function hint(id, text) {
  return `<span class="hint"><button type="button" class="hint-btn" aria-label="${esc(text)}" aria-describedby="${id}">${ICONS.help}</button>
    <span class="hint-box" role="tooltip" id="${id}">${esc(text)}</span></span>`;
}
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && document.activeElement?.closest?.(".hint")) document.activeElement.blur();
});

const INP_FORMATS = ["BNF", "EBNF", "ANTLR (.g4)", "Fandango", "ISLa", "FuzzingBook (.py)"];

const INP_TIPS = [
  "Start from a bundled grammar if one fits; edit a copy in your project.",
  "Upload BNF, EBNF, Fandango or ANTLR; SpreadEx converts it for each generator.",
  "No grammar? Point at a folder of inputs. Generators are skipped, the rest works.",
  "Set the file extension if your system picks its parser from it.",
];

const langById = id => INP_LANGS.find(l => l.id === id) || INP_LANGS[INP_LANGS.length - 1];

// One logo for a language: a brand mark where one exists, a Lucide glyph or a letter
// badge otherwise, on a tile tinted from its own colour (lightened in dark mode by CSS).
// Java and Python use the artwork supplied for the run-style cards: Simple Icons has no Java
// cup (its OpenJDK mark is the Duke mascot) and only a one-colour Python.
const LANG_IMG = { java: "/static/assets/sut-jar.png", py: "/static/assets/sut-script.png" };

function langLogo(l, big) {
  const inner = LANG_IMG[l.id] ? `<img src="${LANG_IMG[l.id]}" alt="" draggable="false">` : l.d ? `<svg class="ico brand" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="${l.d}"/></svg>`
    : l.lucide ? ICONS[l.lucide] : `<span class="lang-badge">${esc(l.badge)}</span>`;
  return `<span class="lang-tile ${big ? "big" : ""}" style="--b:#${l.hex}" aria-hidden="true">${inner}</span>`;
}

function langOption(l, d) {
  return `<button type="button" role="option" class="lang-opt ${l.id === d.lang ? "on" : ""}" aria-selected="${l.id === d.lang}"
    onclick="chooseInpLang('${l.id}')">${langLogo(l, true)}<span class="lang-name">${esc(l.t)}</span><span class="lang-sub">${esc(l.sub)}</span></button>`;
}

function toggleLangMenu(force) {
  const menu = el("lang-menu"), btn = el("lang-btn");
  if (!menu) return;
  const open = force === undefined ? menu.hidden : force;
  menu.hidden = !open;
  btn.setAttribute("aria-expanded", String(open));
  if (open) { menu.scrollTop = 0; (menu.querySelector(".lang-opt.on") || menu.querySelector(".lang-opt")).focus({ preventScroll: true }); }
}
document.addEventListener("click", e => { if (!e.target.closest?.(".lang-pick")) toggleLangMenu(false); });
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && el("lang-menu") && !el("lang-menu").hidden) { toggleLangMenu(false); el("lang-btn").focus(); }
});

function chooseInpLang(id) {
  const d = stashInp();
  d.lang = id;
  // Filling the extension is a convenience: once the user has typed their own, it stays theirs.
  const l = langById(id);
  if (!d.extTouched) d.ext = l.ext;
  paintInputs();
  el("lang-btn")?.focus();
}

// ------------------------------------------------ step 2: semantic guidance

function semInit() {
  const saved = (cfg().semantics) || {};
  const path = (saved.guidance || [])[0] || "";
  return { text: path ? ((S.spec?.texts || {})[path] || "") : "", path, editing: false, busy: "", msg: "",
           warnings: [], source: "", original: null, advancedOpen: !!(saved.structured || Object.keys(saved.native || {}).length) };
}

function semSaved() { return cfg().semantics || {}; }
function setSemantics(next) {
  const clean = {};
  if (next.guidance && next.guidance.length) clean.guidance = next.guidance;
  if (next.structured) clean.structured = next.structured;
  if (next.native && Object.keys(next.native).length) clean.native = next.native;
  S.config.semantics = Object.keys(clean).length ? clean : undefined;
}

function b64(buffer) {
  let bin = ""; const bytes = new Uint8Array(buffer);
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

function stashSem() {
  const d = inpState().sem;
  if (el("sem-text")) d.text = el("sem-text").value;
  return d;
}

function semWrite() { const d = stashSem(); d.editing = !d.editing; d.msg = ""; paintInputs(); if (d.editing) el("sem-text")?.focus(); }

async function semUpload(input) {
  const file = input.files && input.files[0];
  if (!file) return;
  const d = stashSem();
  d.busy = `Reading ${file.name}…`; d.msg = ""; d.warnings = []; paintInputs();
  let res;
  try {
    const data = b64(await file.arrayBuffer());
    res = await api("/api/spec/extract", { name: file.name, data });
    if (res.ok) d.original = /\.(pdf|docx)$/i.test(file.name) ? { name: file.name, data } : null;
  } catch (e) { res = { ok: false, error: e.message }; }
  d.busy = "";
  if (!res.ok) { d.msg = res.error; paintInputs(); return; }
  d.text = res.text; d.warnings = res.warnings || []; d.source = `${file.name} · ${num(res.chars)} characters${res.pages ? ` · ${res.pages} pages` : ""}`;
  d.editing = true; d.name = file.name.replace(/\.[^.]+$/, "") + ".md";
  paintInputs();
}

async function semSave() {
  const d = stashSem();
  d.busy = "Saving…"; d.msg = ""; paintInputs();
  let res;
  try { res = await api("/api/spec/save", { kind: "guidance", name: d.name || "semantics.md", text: d.text, original: d.original }); }
  catch (e) { res = { ok: false, error: e.message }; }
  d.busy = "";
  if (!res.ok) { d.msg = res.error; paintInputs(); return; }
  d.path = res.written; d.editing = false; d.original = null; d.warnings = []; d.source = "";
  setSemantics({ ...semSaved(), guidance: [res.written] });
  paintInputs();
}

function semRemove() {
  const d = stashSem();
  d.path = ""; d.text = ""; d.editing = false;
  setSemantics({ ...semSaved(), guidance: [] });
  paintInputs();
}

async function semFileSlot(input, kind) {
  const file = input.files && input.files[0];
  if (!file) return;
  const d = stashSem();
  if (file.size > 1_000_000) { d.msg = "That file is over 1 MB; keep rules short and focused."; paintInputs(); return; }
  let res;
  try { res = await api("/api/spec/save", { kind, name: file.name, text: await file.text() }); }
  catch (e) { res = { ok: false, error: e.message }; }
  if (!res.ok) { d.msg = res.error; paintInputs(); return; }
  d.msg = "";
  const cur = semSaved();
  if (kind === "structured") setSemantics({ ...cur, structured: res.written });
  else setSemantics({ ...cur, native: { ...(cur.native || {}), [kind.split(":")[1]]: res.written } });
  paintInputs();
}

function semDropSlot(kind) {
  stashSem();
  const cur = semSaved();
  if (kind === "structured") setSemantics({ ...cur, structured: "" });
  else { const n = { ...(cur.native || {}) }; delete n[kind.split(":")[1]]; setSemantics({ ...cur, native: n }); }
  paintInputs();
}
function toggleSemAdvanced(open) { inpState().sem.advancedOpen = open; }

function semanticSection() {
  const d = inpState().sem, saved = semSaved();
  const docs = S.spec?.docs || { pdf: true, docx: true };
  const missing = [!docs.pdf && "PDF", !docs.docx && "DOCX"].filter(Boolean);
  const capable = (S.generators || []).filter(g => g.constraints && ["fandango", "isla"].includes(g.id));
  const nativeRows = Object.entries(saved.native || {}).map(([gid, path]) => `<div class="sem-file">
    <span class="mono">${esc(path)}</span><span class="muted">${esc(gid)}, used as written</span>
    <button type="button" class="linkish" onclick="semDropSlot('native:${esc(gid)}')">Remove</button></div>`).join("");
  return `<section class="sut-sec sem" aria-labelledby="sem-h">
    <h4 id="sem-h"><span class="num" aria-hidden="true">4</span> Semantic guidance <span class="muted">(optional)</span>
      ${hint("hint-sem", "Rules a grammar cannot say, such as a variable being declared before use. Written once here; step 3 shows what each generator can do with it.")}</h4>
    <p class="muted inp-sub">Describe rules that go beyond syntax. Plain language is fine.</p>
    <div class="sem-card" data-tour="inputs-constraint">
      <div class="sem-head"><span class="tile green" aria-hidden="true">${ICONS.doc}</span>
        <div><strong>Natural language</strong> <span class="tag ok">Recommended</span>
          <div class="muted">Write the rules, or upload documentation that states them.</div></div></div>
      ${d.path && !d.editing ? `<div class="sem-file"><span class="res-ico-sm" aria-hidden="true">${ICONS.success}</span>
        <span class="mono">${esc(d.path)}</span><span class="muted">${num(d.text.length)} characters</span>
        <button type="button" class="linkish" onclick="semWrite()">Edit</button>
        <button type="button" class="linkish" onclick="semRemove()">Remove</button></div>` : ""}
      ${d.editing ? `<label for="sem-text">Guidance${d.source ? ` <span class="muted">from ${esc(d.source)}</span>` : ""}</label>
        <textarea id="sem-text" rows="8" spellcheck="true" placeholder="A break statement can only appear inside a loop or switch.&#10;A variable must be declared before it is used.">${esc(d.text)}</textarea>
        ${(d.warnings || []).map(w => `<div class="inp-guide">${ICONS.alert}<div>${esc(w)}</div></div>`).join("")}
        <div class="actions"><button type="button" class="primary" onclick="semSave()" ${d.busy ? "disabled" : ""}>Save guidance</button>
          <button type="button" class="ghost" onclick="semWrite()">Cancel</button></div>` : `
      <div class="inp-up">
        <button type="button" class="btn-like" onclick="semWrite()">${ICONS.edit} Write guidance</button>
        <label class="btn-like" for="sem-file">${ICONS.upload} Upload document</label>
        <input id="sem-file" type="file" accept=".txt,.md,.pdf,.docx" onchange="semUpload(this)">
        <span class="chips"><span class="chip">.txt</span><span class="chip">.md</span><span class="chip">.pdf</span><span class="chip">.docx</span></span>
      </div>`}
      ${missing.length && !d.editing ? `<div class="muted sem-note">Reading ${missing.join(" and ")} needs <span class="mono">pip install 'spreadex[docs]'</span>. .txt and .md work now.</div>` : ""}
      ${d.busy ? `<div class="muted sem-note" role="status"><span class="spinner"></span> ${esc(d.busy)}</div>` : ""}
      ${d.msg ? `<div class="res bad" role="alert"><span class="res-ico" aria-hidden="true">${ICONS.error}</span><div class="res-main"><div class="res-s">${esc(d.msg)}</div></div></div>` : ""}
    </div>
    <div class="sem-card sem-native">
      <div class="sem-head"><span class="tile orange" aria-hidden="true">${ICONS.shield}</span>
        <div><strong>Generator-specific specification</strong> <span class="tag ok">Recommended</span>
          <div class="muted">Generators that support constraints read their own format: Fandango a <span class="mono">.fan</span> file, ISLa an <span class="mono">.isla</span> file.
            Each file goes to its generator unchanged; SpreadEx does not convert it. Generators without constraint support use the grammar alone.</div></div></div>
      ${nativeRows}
      ${capable.length ? `<div class="inp-up">${capable.filter(g => !(saved.native || {})[g.id]).map(g => `<label class="btn-like" for="sem-nat-${g.id}">${ICONS.upload} ${esc(g.name)} constraints (${g.id === "isla" ? ".isla" : ".fan"})</label>
          <input id="sem-nat-${g.id}" type="file" class="visually-hidden" onchange="semFileSlot(this, 'native:${g.id}')">`).join(" ")}</div>`
        : `<div class="muted">No installed generator takes its own constraints.</div>`}
    </div>
    <details class="sut-adv" ${d.advancedOpen ? "open" : ""} ontoggle="toggleSemAdvanced(this.open)">
      <summary><span><strong>Advanced</strong></span><span class="muted">Structured constraints</span></summary>
      <div class="sut-adv-body">
        <label>Structured constraints <span class="tag warn">reserved</span></label>
        <p class="muted">A YAML or JSON file. Stored and recorded with each run, but not interpreted by any generator yet.</p>
        ${saved.structured ? `<div class="sem-file"><span class="mono">${esc(saved.structured)}</span>
          <button type="button" class="linkish" onclick="semDropSlot('structured')">Remove</button></div>`
          : `<label class="btn-like" for="sem-struct">${ICONS.upload} Choose a file</label><input id="sem-struct" type="file" accept=".yaml,.yml,.json" class="visually-hidden" onchange="semFileSlot(this, 'structured')">`}
      </div>
    </details>
    <div class="sem-sum" aria-label="Input specification summary">
      <div><span class="muted">Language</span> ${esc(langById(inpState().lang).t)}</div>
      <div><span class="muted">Grammar</span> ${inpState().picked ? "✓ " + esc(inpState().picked) : (inpState().mode === "none" ? "none (inputs folder)" : "not chosen")}</div>
      <div><span class="muted">Semantic guidance</span> ${saved.guidance?.length ? "✓ " + esc(saved.guidance[0]) : "none"}</div>
      <div><span class="muted">Native specs</span> ${Object.keys(saved.native || {}).length ? esc(Object.keys(saved.native).join(", ")) : "none"}</div>
    </div>
  </section>`;
}

function inpState() {
  if (S.inp) return S.inp;
  const c = cfg();
  const ext = c.input_extension || "";
  const lang = ext ? (INP_LANGS.find(l => l.ext === ext) || langById("other")) : langById("");
  S.inp = {
    lang: lang.id,
    ext,
    extTouched: !!ext,
    mode: c.grammar?.source ? "provide" : (c.corpus?.path ? "none" : "builtin"),
    picked: c.grammar?.source || "",
    corpus: c.corpus?.path || "",
    analysis: null, details: false, busy: "", msg: "",
    exampleTab: "bnf",
    constraintsOpen: false,
    sem: semInit(),
  };
  return S.inp;
}

function stashInp() {
  const d = inpState();
  if (el("sem-text")) d.sem.text = el("sem-text").value;
  if (el("inp-ext")) d.ext = el("inp-ext").value.trim();
  if (el("corpus")) d.corpus = el("corpus").value.trim();
  if (el("inp-project") && el("inp-project").value) d.picked = el("inp-project").value;
  return d;
}

function touchInpExt() { const d = inpState(); d.extTouched = true; d.ext = el("inp-ext").value.trim(); }

function pickInpMode(id) {
  const d = stashInp();
  d.mode = id; d.msg = "";
  // Switching tabs must not leave a stale analysis for a grammar the new tab
  // is not using.
  if (id === "none") d.analysis = null;
  paintInputs();
  if (id !== "none" && d.picked) analyseGrammar();
}

function inpExampleTab(id) { stashInp().exampleTab = id; paintInputs(); }
function copyInpExample(button) {
  const ex = INP_EXAMPLES.find(x => x.id === inpState().exampleTab) || INP_EXAMPLES[0];
  if (navigator.clipboard?.writeText) navigator.clipboard.writeText(ex.code).then(() => {
    button.classList.add("copied");
    setTimeout(() => button.classList.remove("copied"), 1400);
  }).catch(() => {});
}

// Saving goes through the server, which parses the text with the front end its
// file name asks for and refuses what does not pass -- so "picked" always means
// "validated".
async function saveInpGrammar(path, text) {
  const d = inpState();
  d.busy = "Checking the grammar…"; d.msg = ""; paintInputs();
  let res;
  try { res = await api("/api/grammar/save", { path, text }); }
  catch (e) { d.busy = ""; d.msg = e.message; d.analysis = null; paintInputs(); return false; }
  d.busy = "";
  if (!res.ok) { d.msg = res.error; d.analysis = null; paintInputs(); return false; }
  d.picked = res.written; d.msg = "";
  await analyseGrammar();
  return true;
}

async function useBundled(id) {
  const g = (S.bundled || []).find(x => x.id === id);
  if (!g) return;
  const d = stashInp();
  // A bundled grammar belongs to the project once chosen, so editing it never
  // touches the installed package. It does not decide the file extension: that
  // is a fact about the system under test, not about the grammar.
  await saveInpGrammar(g.path, g.text);
}

async function uploadInp(input, rename) {
  const file = input.files && input.files[0];
  if (!file) return;
  if (file.size > 2_000_000) { inpState().msg = "That file is over 2 MB; a grammar should be far smaller."; paintInputs(); return; }
  const text = await file.text();
  const name = file.name.replace(/[^A-Za-z0-9._-]/g, "_");
  await saveInpGrammar(`grammars/${name}`, text);
}

async function analyseGrammar() {
  const d = inpState();
  if (!d.picked) { d.analysis = null; paintInputs(); return; }
  d.busy = "Checking the grammar…"; paintInputs();
  try { d.analysis = await api(`/api/grammar?source=${encodeURIComponent(d.picked)}`); }
  catch (e) { d.analysis = { error: e.message }; }
  d.busy = ""; d.details = false; paintInputs();
}

function toggleInpDetails() { stashInp().details = !inpState().details; paintInputs(); }

function inpAnalysis() {
  const d = inpState(), g = d.analysis;
  if (d.busy) return `<div class="res note" role="status"><span class="spinner"></span> ${esc(d.busy)}</div>`;
  if (d.msg) return `<div class="res bad" role="alert"><span class="res-ico" aria-hidden="true">${ICONS.error}</span>
    <div class="res-main"><div class="res-t">SpreadEx could not use that grammar</div><div class="res-s"><pre class="inp-err">${esc(d.msg)}</pre></div></div></div>`;
  if (!g) return "";
  if (g.error) return `<div class="res bad" role="alert"><span class="res-ico" aria-hidden="true">${ICONS.error}</span>
    <div class="res-main"><div class="res-t">This grammar could not be read</div><div class="res-s"><pre class="inp-err">${esc(g.error)}</pre></div></div></div>`;
  const errors = (g.findings || []).filter(f => f.severity === "error");
  const warns = (g.findings || []).filter(f => f.severity === "warning");
  const tone = errors.length ? "bad" : warns.length ? "warn" : "good";
  const icon = errors.length ? ICONS.error : warns.length ? ICONS.alert : ICONS.success;
  const title = errors.length ? "Grammar has problems" : warns.length ? "Grammar is usable, with warnings" : "Grammar ready!";
  const sub = errors.length ? `${errors.length} error${errors.length > 1 ? "s" : ""} to fix before generators can use it.`
    : "The grammar has been parsed and checked.";
  const facts = [["Start symbol", `<span class="mono">&lt;${esc(g.start)}&gt;</span>`],
                 ["Productions", num(g.rules)],
                 ["Alternatives", num(g.alternatives ?? g.rules)],
                 ["Uses", esc((g.features || []).join(", ") || "plain BNF")]];
  const sev = s => s === "error" ? "bad" : s === "warning" ? "warn" : "muted";
  const detail = d.details ? `
    <table class="inp-support"><tbody>${(g.support || []).map(s => `<tr><td>${esc(s.generator)}</td><td>
      <span class="${s.status === "blocked" || s.status === "unsupported" ? "bad" : "ok"}">
      ${s.status === "blocked" || s.status === "unsupported" ? "Cannot use it" : "Can use it"}
      ${{ direct: "directly", rewrite: "after rewriting", blocked: "", unsupported: "(dialect not emitted yet)" }[s.status] || ""}</span>
      ${(s.blockers || []).map(b => `<div class="bad">${esc(b)}</div>`).join("")}
      ${(s.risks || []).map(r => `<div class="warn">! ${esc(r)}</div>`).join("")}</td></tr>`).join("")}</tbody></table>
    ${(g.findings || []).map(f => `<div class="inp-find"><span class="tag ${sev(f.severity)}">${esc(f.code)}</span>
      ${f.rule ? `<span class="mono muted"> &lt;${esc(f.rule)}&gt;</span>` : ""} ${esc(f.message)}</div>`).join("")}` : "";
  return `<div class="res ${tone}" role="status"><span class="res-ico" aria-hidden="true">${icon}</span>
    <div class="res-main"><div class="res-t">${title}</div><div class="res-s">${sub}</div>
      <dl class="res-facts">${facts.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("")}</dl>${detail}</div>
    <button type="button" class="ghost small res-btn" onclick="toggleInpDetails()" aria-expanded="${d.details}">${d.details ? "Hide details" : "View details"}</button></div>`;
}

function bundledCards(d) {
  return (S.bundled || []).map(g => `<button type="button" class="inp-g ${d.picked === g.path ? "on" : ""}"
    onclick="useBundled('${esc(g.id)}')" aria-pressed="${d.picked === g.path}">
    <span class="lang-tile big" style="--b:#16A34A" aria-hidden="true">${ICONS.calc}</span>
    <span class="inp-gt"><strong>${esc(g.name)}</strong><span class="muted">${esc(g.language)} · ${g.rules} productions</span></span>
    <span class="inp-ok" aria-hidden="true">${ICONS.check}</span></button>`).join("");
}

// What the language the user chose has upstream, shown as inactive blocks: SpreadEx does not
// ship these, and a block that looked clickable would promise something it cannot do.
function languagePack(d) {
  const l = langById(d.lang), pack = LANG_PACKS[d.lang];
  if (!d.lang || !pack) return `<p class="muted inp-sub">Choose an input language above to see the grammars that exist for it.</p>`;
  const blocks = pack.blocks.map(([name, dir]) => `<div class="inp-g off" aria-disabled="true">
    ${langLogo(l, true)}<span class="inp-gt"><strong>${esc(name)}</strong><span class="muted">Not bundled yet</span></span></div>`).join("");
  const where = pack.blocks.length
    ? `The ANTLR project's <a href="${GV4}${pack.dir}" target="_blank" rel="noopener noreferrer">grammars-v4 &rarr; <span class="mono">${esc(pack.dir)}</span></a>
       has ${pack.blocks.length > 1 ? "these" : "this"}. Check each grammar's own licence, then bring the file in with
       <button type="button" class="linkish" onclick="pickInpMode('import')">Import grammar</button>.`
    : `grammars-v4 has no ${esc(l.t)} grammar. Write one in BNF (see the examples on the right) and add it with
       <button type="button" class="linkish" onclick="pickInpMode('import')">Import grammar</button>.`;
  return `<h5 class="inp-h5">${esc(l.t)} grammars</h5>
    ${blocks ? `<div class="inp-list">${blocks}</div>` : ""}
    <div class="inp-guide">${ICONS.info}<div><strong>No ready-made ${esc(l.t)} grammar ships with SpreadEx yet.</strong>
      <div class="muted">${where}</div></div></div>`;
}

function inpPanel() {
  const d = inpState();
  const picked = d.picked ? `<div class="muted inp-picked">Using <span class="mono">${esc(d.picked)}</span></div>` : "";
  if (d.mode === "builtin") {
    return `<h4>Pick a ready-made grammar</h4>
      <p class="muted inp-sub">Ready to use, and copied into your project so you can edit it freely.</p>
      ${languagePack(d)}
      <h5 class="inp-h5">Demo grammar</h5>
      <div class="inp-list">${bundledCards(d) || `<div class="muted">No bundled grammars found.</div>`}</div>${picked}`;
  }
  if (d.mode === "provide") {
    const gs = S.grammars || [];
    return `<h4>Use a grammar from this project</h4>
      <p class="muted inp-sub">Pick a grammar file that is already in your project folder. It is read in place and never copied or changed.</p>
      ${gs.length ? `<label for="inp-project">Grammar file</label>
      <select id="inp-project" onchange="stashInp(); analyseGrammar()">
        <option value="">— choose a file —</option>
        ${gs.map(g => `<option value="${esc(g.path)}" ${g.path === d.picked ? "selected" : ""}>${esc(g.path)}</option>`).join("")}
      </select>` : `<div class="inp-guide">${ICONS.info}<div><strong>No grammar files found in this project.</strong>
        <div class="muted">SpreadEx looks for .bnf, .ebnf, .g4, .fan, .isla and FuzzingBook .py files. Have one somewhere else?
        <button type="button" class="linkish" onclick="pickInpMode('import')">Import grammar</button> copies it in.</div></div></div>`}${picked}`;
  }
  if (d.mode === "import") {
    const l = langById(d.lang), pack = LANG_PACKS[d.lang];
    const tip = d.lang && pack && pack.dir
      ? `<div class="inp-guide">${ICONS.bulb}<div><strong>Looking for a ${esc(l.t)} grammar?</strong>
          <div class="muted"><a href="${GV4}${pack.dir}" target="_blank" rel="noopener noreferrer">grammars-v4 &rarr; <span class="mono">${esc(pack.dir)}</span></a>
          publishes ${esc(pack.blocks.map(b => b[0]).join(", "))} as ANTLR <span class="mono">.g4</span> files. Download the grammar file, then choose it below.</div></div></div>` : "";
    return `<h4>Import a grammar from elsewhere</h4>
      <p class="muted inp-sub">Choose a file on your computer. SpreadEx checks it, converts it for each generator, and saves a copy in
        <span class="mono">grammars/</span>; your original stays where it is.</p>
      ${tip}
      <div class="inp-up"><label class="btn-like" for="inp-file2">${ICONS.upload} Choose a grammar file</label>
        <input id="inp-file2" type="file" accept=".g4,.py,.bnf,.ebnf,.fan,.isla,.txt" onchange="uploadInp(this)">
        <span class="chips"><span class="chip">.g4 ANTLR</span><span class="chip">.bnf</span><span class="chip">.ebnf</span>
          <span class="chip">.fan Fandango</span><span class="chip">.isla</span><span class="chip">.py FuzzingBook</span></span></div>${picked}`;
  }
  return `<h4>Use inputs you already have</h4>
    <p class="muted inp-sub">A folder of example inputs. Generators need a grammar, so they are skipped;
      prioritization and execution work the same.</p>
    <label for="corpus">Folder of inputs</label>
    <input id="corpus" type="text" value="${esc(d.corpus)}" placeholder="./seeds" spellcheck="false">`;
}

function paintInputs() {
  const d = inpState();
  const ex = INP_EXAMPLES.find(x => x.id === d.exampleTab) || INP_EXAMPLES[0];
  const lang = langById(d.lang);
  el("view").innerHTML = `
  <div class="sut">
   <div class="sut-main">
    <header class="sut-head">
      <span class="sut-badge blue" aria-hidden="true">2</span>
      <div><h3>Define the input specification</h3>
        <p class="why">Tell SpreadEx what valid test inputs for your program look like and where they come from.</p></div>
    </header>

    <section class="sut-sec">
      <h4><span class="num" aria-hidden="true">1</span> Input language <span class="muted">(optional)</span> ${hint("hint-lang", "Optional. Choosing a language fills in the file extension and shows where to find grammars for it.")}</h4>
      <p class="muted inp-sub">Choose the input language for presets and file extensions.</p>
      <div class="inp-lang">
        <div class="lang-pick"><label id="lang-lab">Language</label>
          <button type="button" id="lang-btn" class="lang-btn" aria-haspopup="listbox" aria-expanded="false"
            aria-labelledby="lang-lab lang-btn" onclick="toggleLangMenu()">${langLogo(lang)}<span class="lang-cur">${esc(lang.t)}</span>
            <span class="lang-chev" aria-hidden="true">${ICONS.chevron}</span></button>
          <div id="lang-menu" class="lang-menu" role="listbox" aria-labelledby="lang-lab" hidden>
            <div class="lang-grid">${INP_LANGS.slice(0, -4).map(l => langOption(l, d)).join("")}</div>
            <div class="lang-foot">${INP_LANGS.slice(-4).map(l => langOption(l, d)).join("")}</div>
          </div></div>
        <div><label for="inp-ext">File extension ${hint("hint-ext", "The ending given to every input file when it is run, for example .js. Many programs pick their parser from it. Leave it empty to use none.")}</label>
          <input id="inp-ext" type="text" value="${esc(d.ext)}" oninput="touchInpExt()" spellcheck="false" placeholder="${esc(lang.ext || "e.g. .js")}"></div>
      </div>
    </section>

    <section class="sut-sec" aria-labelledby="inp-q">
      <h4 id="inp-q"><span class="num" aria-hidden="true">2</span> How should SpreadEx understand your input language?</h4>
      <div class="sut-kinds" role="radiogroup" aria-labelledby="inp-q">
        ${INP_MODES.map(m => `<button type="button" role="radio" class="sut-kind ${d.mode === m.id ? "on" : ""}"
          aria-checked="${d.mode === m.id}" onclick="pickInpMode('${m.id}')">
          <span class="tile ${m.tone}" aria-hidden="true">${ICONS[m.icon]}</span>
          <span class="sk-t">${m.t}</span><span class="sk-d">${m.d}</span>
          <span class="sk-ok" aria-hidden="true">${ICONS.check}</span></button>`).join("")}
      </div>
      <div class="inp-panel" data-tour="inputs-grammar">${inpPanel()}</div>
    </section>

    ${d.mode === "none" ? "" : `<section class="sut-sec" aria-live="polite">
      <h4><span class="num" aria-hidden="true">3</span> Grammar analysis</h4>
      <p class="muted inp-sub">Checks the grammar and shows which generators can use it.</p>
      ${inpAnalysis() || `<div class="muted inp-empty">Choose or add a grammar above to see its analysis.</div>`}
    </section>`}

    ${semanticSection()}

    <div id="err"></div>
    <div class="actions inp-actions">
      <button type="button" class="ghost" onclick="gotoStep('sut')">${ICONS.back} Back to System under test</button>
      ${S.project?.experimental ? `<button type="button" class="ghost" onclick="toggleAssistant()">Help me write one</button>` : ""}
      <button type="button" class="primary" data-tour="inputs-continue" onclick="commitGrammar()">Continue to Generators ${ICONS.arrow}</button>
    </div>
   </div>

   <aside class="sut-side" aria-label="Help">
    <div class="side-card inp-hero side-hero" aria-hidden="true">${inpArt(d.lang)}</div>
    <div class="side-card">
      <h4><span class="h-ico blue">${ICONS.book}</span> What are input specifications?</h4>
      <p>An input specification tells SpreadEx what valid test inputs for your program look like. It usually consists of a grammar and, optionally, semantic constraints.</p>
    </div>
    <div class="side-card">
      <h4><span class="h-ico purple">${ICONS.example}</span> Example grammars</h4>
      <div class="ex-tabs" role="tablist">${INP_EXAMPLES.map(x => `<button type="button" role="tab"
        aria-selected="${x.id === ex.id}" class="${x.id === ex.id ? "on" : ""}" onclick="inpExampleTab('${x.id}')">${x.t}</button>`).join("")}</div>
      <div class="ex-code ex-block"><pre><code>${esc(ex.code)}</code></pre>
        <button type="button" class="ex-copy" onclick="copyInpExample(this)" aria-label="Copy example">${ICONS.copy}</button></div>
    </div>
    <div class="side-card">
      <h4><span class="h-ico green">${ICONS.grid}</span> Supported formats</h4>
      <p>SpreadEx reads and normalises grammars written as:</p>
      <div class="chips">${INP_FORMATS.map(f => `<span class="chip">${f}</span>`).join("")}</div>
    </div>
    <div class="side-card">
      <h4><span class="h-ico amber">${ICONS.bulb}</span> Tips</h4>
      <ul class="tips-list">${INP_TIPS.map(t => `<li><span aria-hidden="true">${ICONS.check}</span>${esc(t)}</li>`).join("")}</ul>
    </div>
   </aside>
  </div>
  <div id="assistant"></div>`;
}

async function stepGrammar(current = () => true) {
  el("view").innerHTML = `<div class="card"><div class="empty">Looking for grammars…</div></div>`;
  const [{ grammars }, bundled, spec, gens] = await Promise.all([api("/api/files"), api("/api/grammars/bundled"), api("/api/spec"), api("/api/generators")]);
  if (!current()) return;   // the user moved on while this was loading
  S.grammars = grammars;
  S.bundled = bundled.grammars;
  S.spec = spec;
  S.generators = gens.generators;
  const d = inpState();
  if (!d.sem.text && d.sem.path) d.sem.text = (spec.texts || {})[d.sem.path] || "";
  // The assistant (and a returning user) can change the config under us.
  if (cfg().grammar?.source && cfg().grammar.source !== d.picked) { d.picked = cfg().grammar.source; d.mode = "provide"; }
  paintInputs();
  if (d.mode !== "none" && d.picked) analyseGrammar();
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
    catch (e) { holder.innerHTML = failureCard(e); return; }
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
  const corpusPath = (el("corpus")?.value || S.inp?.corpus || cfg().corpus?.path || "").trim();
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

function commitGrammar() {
  const d = stashInp();
  const useGrammar = d.mode !== "none";
  const source = useGrammar ? d.picked : "";
  const corpus = d.mode === "none" ? d.corpus : "";
  const err = m => { el("err").innerHTML = `<div class="note bad" role="alert">${esc(m)}</div>`; };
  if (!source && !corpus) {
    err(d.mode === "none" ? "Enter the folder that holds your inputs."
                          : "Choose or add a grammar first, or pick \u201cNo grammar\u201d to use inputs you already have.");
    return;
  }
  if (useGrammar && d.analysis?.error) { err("That grammar could not be read; fix it or choose another."); return; }
  if (useGrammar && (d.analysis?.findings || []).some(f => f.severity === "error")) {
    err("The grammar has errors. Open View details, fix them, then continue."); return;
  }
  if (d.ext && !/^\.[A-Za-z0-9_+-]{1,12}$/.test(d.ext)) {
    err("File extension: use a dot and letters or digits, like .js or .sql."); el("inp-ext")?.focus(); return;
  }
  // Different inputs can need different generators: a change sends the later steps back for review.
  if ((cfg().grammar?.source || "") !== source || (cfg().corpus?.path || "") !== corpus) {
    S.confirmed.delete("generators"); S.confirmed.delete("strategy");
  }
  S.confirmed.add("grammar");
  S.config.grammar = source ? { source } : undefined;
  S.config.corpus = corpus ? { path: corpus } : undefined;
  S.config.input_extension = d.ext || undefined;
  gotoStep("generators");
  tourEvent("step.grammar");
}

// ------------------------------------------------ step 3: generators

// Logos come from the research tool's assets (small copies). Grammarinator has none there, so it
// takes the purple node glyph from the design. Families drive the filter bar.
const GEN_LOGO = { fandango: "gen-fandango.png", isla: "gen-isla.png", fuzzingbook: "gen-fuzzingbook.png",
  clusgram: "gen-clusgram.png", nautilus: "gen-nautilus.png", dharma: "gen-dharma.png",
  fuzz4all: "gen-llm.png" };   // Fuzz4All has no mark of its own here; the generic LLM icon stands in
const FAMILY_LABEL = { "probabilistic": "Probabilistic", "constraint-based": "Constraint-based",
  "coverage-guided": "Coverage-guided", "llm-based": "LLM-based" };

// The catalog's version string is whatever `--version` printed ("Fandango 1.2.0",
// "grammarinator-process 26.1"). Show only the number; hide it if there is none.
function cleanVersion(v) { const m = /\d+(?:\.\d+)+/.exec(v || ""); return m ? m[0] : ""; }

function genLogo(id, big) {
  const inner = GEN_LOGO[id] ? `<img src="/static/assets/${GEN_LOGO[id]}" alt="" draggable="false">`
    : id === "grammarinator" ? ICONS.import : ICONS.code;
  return `<span class="gen-logo ${big ? "big" : ""} ${GEN_LOGO[id] ? "" : "glyph"}" aria-hidden="true">${inner}</span>`;
}

// "A-TEST 2018", or "Online book" where there is no paper. Grey and small on purpose: it is context,
// not a status. The full citation is the tooltip.
function refLabel(r) {
  if (!r) return "";
  if (r.venue && r.year) return `${r.venue} ${r.year}`;
  return r.kind || "";
}
function refTitle(r) {
  if (!r) return "";
  const base = [r.authors, r.title ? `\u201c${r.title}\u201d` : "", r.venue && r.year ? `${r.venue} ${r.year}` : (r.kind || "")]
    .filter(Boolean).join(", ");
  return r.note ? `${base}. ${r.note}.` : base;
}
function refLine(r) {
  const t = refLabel(r);
    // A bare dash has no citation behind it, so it gets no tooltip.
  const tip = (r.authors || r.title) ? ` title="${esc(refTitle(r))}"` : "";
  return t ? `<span class="gref"${tip}>${ICONS.book}<span>${esc(t)}</span></span>` : "";
}

function genState() {
  if (!S.gen) S.gen = { filter: "all", modal: null, draftConstraints: true, analysis: null };
  return S.gen;
}

// Is this generator able to run the grammar from step 2? Uses the same expressibility report the
// Inputs page shows; with no grammar nothing can run, which is said plainly.
function genFit(g) {
  const d = genState(), a = d.analysis;
  if (!cfg().grammar?.source) return { ok: false, why: "Needs a grammar. Your inputs come from a folder." };
  if (!a || a.error) return { ok: false, why: a?.error ? "The grammar could not be read." : "Checking the grammar…" };
  if (!g.emittable) return { ok: false, why: "SpreadEx cannot write this generator's grammar dialect yet." };
  const s = (a.support || []).find(x => x.generator === g.id);
  if (!s) return { ok: true, how: "direct" };
  if (s.status === "blocked" || s.status === "unsupported") {
    return { ok: false, why: (s.blockers && s.blockers[0]) || "It cannot express this grammar." };
  }
  return { ok: true, how: s.status, risks: s.risks || [] };
}

function genSplit() {
  const all = S.generators || [];
  const fits = all.map(g => ({ g, fit: genFit(g) }));
  const recommended = fits.filter(x => x.fit.ok).slice(0, 3);
  const recIds = new Set(recommended.map(x => x.g.id));
  const other = fits.filter(x => !recIds.has(x.g.id));
  return { recommended, other };
}

// A generator that is not installed is not a problem: it is installed when the run starts, after
// everything has been asked. Selecting it changes the wording from a state to a plan.
function isPending(g) { return !g.installed && (cfg().generators || []).includes(g.id); }
function installTag(g) {
  if (g.installed) return `<span class="tag ok">Installed</span>`;
  return isPending(g) ? `<span class="tag pend">Installs when you run</span>` : `<span class="tag warn">Not installed</span>`;
}

function inFilter(family) { const f = genState().filter; return f === "all" || family === f; }

function genCard({ g, fit }, recommended) {
  const chosen = (cfg().generators || []).includes(g.id);
  const line = semanticLine(g, cfg().semantics, !!S.project?.experimental);
  const opt = (cfg().generator_options || {})[g.id] || {};
  return `<div class="gcard ${chosen ? "on" : ""} ${fit.ok ? "" : "off"}" data-gen="${esc(g.id)}" ${chosen ? 'data-tour="gen-selected"' : ""}>
    <label class="gcheck"><input type="checkbox" ${chosen ? "checked" : ""} ${fit.ok || chosen ? "" : "disabled"}
      onclick="event.stopPropagation()" onchange="toggleGen('${esc(g.id)}')" aria-label="Use ${esc(g.name)}"><span class="box" aria-hidden="true">${ICONS.check}</span></label>
    <button type="button" class="gbody" onclick="openGenModal('${esc(g.id)}', this)" aria-haspopup="dialog">
      ${genLogo(g.id)}
      <span class="gtext">
        <span class="gname">${esc(g.name)} ${recommended ? `<span class="tag ok gtag">Recommended</span>` : ""}</span>
        <span class="gtags"><span class="tag gfam">${esc(FAMILY_LABEL[g.family] || "Grammar")}</span>
          ${installTag(g)}
          ${cleanVersion(g.version) ? `<span class="muted gver">v${esc(cleanVersion(g.version))}</span>` : ""}</span>
        ${refLine(g.reference)}
        ${fit.ok ? "" : `<span class="gwhy">${ICONS.alert}<span>${esc(fit.why)}</span></span>`}
        ${chosen && opt.constraints === false ? `<span class="muted gopt">Constraints off: grammar only</span>` : ""}
        ${chosen && line ? `<span class="sem-line ${line.tone}">${ICONS[line.tone === "ok" ? "success" : line.tone === "warn" ? "alert" : "info"]}<span>${esc(line.text)}</span></span>` : ""}
      </span></button></div>`;
}

function upcomingCard(u) {
  return `<div class="gcard soon" aria-disabled="true">
    <div class="gbody static">${genLogo(u.id)}<span class="gtext">
      <span class="gname">${esc(u.name)}</span>
      <span class="gtags"><span class="tag gfam">${esc(FAMILY_LABEL[u.family])}</span></span>
      ${refLine(u.reference)}</span></div></div>`;
}

function setGenFilter(id) { genState().filter = id; paintGenerators(); }
function clearGenerators() { S.config.generators = []; paintGenerators(); }
function removeGen(id) { toggleGen(id); }

function selectedGenRows() {
  return (cfg().generators || []).map(id => (S.generators || []).find(g => g.id === id)).filter(Boolean);
}

function inputSpecBar() {
  const d = inpState(), c = cfg();
  const l = langById(d.lang);
  const gram = c.grammar?.source;
  const how = d.mode === "builtin" ? "SpreadEx grammar" : d.mode === "import" ? "Imported grammar" : d.mode === "provide" ? "Project grammar" : "";
  const start = d.analysis?.start;
  return `<div class="specbar">
    <div class="specbar-l"><div class="muted specbar-t">Input specification from previous step</div>
      <div class="specbar-row">
        ${d.lang ? langLogo(l, true) : `<span class="lang-tile big" style="--b:#64748B" aria-hidden="true">${ICONS.doc}</span>`}
        <span><strong>${esc(d.lang ? l.t : "Language not specified")}</strong></span>
        ${gram ? `<span class="spec-i">${ICONS.doc}<span class="mono">${esc(gram.split("/").pop())}</span></span>
          ${how ? `<span class="spec-i">${ICONS.grid}<span>${how}</span></span>` : ""}
          ${start ? `<span class="spec-i">${ICONS.code}<span>Start: <span class="mono">${esc(start)}</span></span></span>` : ""}`
          : `<span class="spec-i">${ICONS.folder}<span>${c.corpus?.path ? `Inputs folder <span class="mono">${esc(c.corpus.path)}</span>` : "No grammar chosen"}</span></span>`}
      </div></div>
    <button type="button" class="ghost small specbar-edit" onclick="gotoStep('grammar')">${ICONS.edit} Edit</button></div>`;
}

async function stepGenerators(current = () => true) {
  el("view").innerHTML = `<div class="card"><div class="empty">Checking generators…</div></div>`;
  const src = cfg().grammar?.source;
  const [gens, analysis] = await Promise.all([
    api("/api/generators"),
    src ? api(`/api/grammar?source=${encodeURIComponent(src)}`).catch(e => ({ error: e.message })) : Promise.resolve(null),
  ]);
  if (!current()) return;
  S.generators = gens.generators;
  S.upcoming = gens.upcoming || [];
  const d = genState();
  d.analysis = analysis;
  if (analysis && !analysis.error && inpState().picked === src) inpState().analysis = analysis;
  if (!cfg().generators) S.config.generators = gens.generators.filter(g => g.selected).map(g => g.id);
  if (!S.config.generators.length && !cfg().corpus) {
    // First visit: pre-tick what is both installed and able to run this grammar.
    const fit = new Set(genSplit().recommended.map(x => x.g.id));
    S.config.generators = gens.generators.filter(g => g.installed && g.emittable && (fit.has(g.id) || !src)).map(g => g.id);
  }
  paintGenerators();
}

function paintGenerators() {
  const d = genState();
  const { recommended, other } = genSplit();
  const recShown = recommended.filter(x => inFilter(x.g.family));
  const otherShown = other.filter(x => inFilter(x.g.family));
  const soon = (S.upcoming || []).filter(u => inFilter(u.family));
  const sel = selectedGenRows();
  const sig = cfg().selection_signal || "cc";
  el("view").innerHTML = `
  <div class="sut gens">
   <div class="sut-main">
    <header class="sut-head">
      <span class="sut-badge purple" aria-hidden="true">3</span>
      <div><h3>Choose your input generators</h3>
        <p class="why">Select one or more generators. SpreadEx will handle compatible grammar formats.</p></div>
    </header>
    ${inputSpecBar()}

    <div class="gfilter" role="tablist" aria-label="Generator family">
      ${[["all", "All"], ...Object.entries(FAMILY_LABEL)].map(([id, t]) => `<button type="button" role="tab" class="${d.filter === id ? "on" : ""}"
        aria-selected="${d.filter === id}" onclick="setGenFilter('${id}')">${t}</button>`).join("")}
    </div>

    <section class="gsec rec" aria-labelledby="gh-rec" data-tour="gen-cards">
      <div class="gsec-h"><h4 id="gh-rec">Recommended generators ${hint("hint-rec", "Generators that are able to run your grammar, so they should work without changes.")}</h4>
        <span class="gcount">Up to 3 shown</span></div>
      <div class="ggrid">${recShown.map(x => genCard(x, true)).join("") ||
        `<div class="muted gempty">${recommended.length ? "None in this family." : (cfg().grammar?.source ? "No installed or installable generator can run this grammar." : "Generators need a grammar. Go back to add one, or continue with an inputs folder.")}</div>`}</div>
    </section>

    <section class="gsec" aria-labelledby="gh-oth">
      <div class="gsec-h"><h4 id="gh-oth">Other generators ${hint("hint-oth", "Generators that cannot run this grammar, or that did not make the top three. Disabled ones say why. Ones that are not installed yet are installed when you run.")}</h4>
        <span class="gcount">${otherShown.length} shown</span></div>
      <div class="ggrid">${otherShown.map(x => genCard(x, false)).join("") ||
        `<div class="muted gempty">None in this family.</div>`}</div>
    </section>

    ${soon.length ? `<section class="gsec soonsec" aria-labelledby="gh-soon">
      <div class="gsec-h"><h4 id="gh-soon">Coming soon ${hint("hint-soon", "Planned generators. They are listed so you can see what is on the way; they cannot be selected yet.")}</h4>
        <span class="gcount">${soon.length} planned</span></div>
      <div class="ggrid">${soon.map(upcomingCard).join("")}</div>
    </section>` : ""}

    <div id="joblog"></div>
    <div id="err"></div>
    <div class="actions inp-actions">
      <button type="button" class="ghost" onclick="gotoStep('grammar')">${ICONS.back} Back to Inputs</button>
      ${constraintCapable().length ? `<button type="button" class="ghost" onclick="toggleConstraints()">Add constraints</button>` : ""}
      <button type="button" class="primary" data-tour="gen-continue" onclick="commitGenerators()">Continue to Testing strategy ${ICONS.arrow}</button>
    </div>
    <div id="constraints"></div>
   </div>

   <aside class="sut-side" aria-label="Help">
    <div class="side-card">
      <h4><span class="h-ico purple">${ICONS.stats}</span> Generator selection</h4>
      <div class="gsel-opt"><span class="gsel-dot" aria-hidden="true"></span>
        <span><strong>Automatic recommendation</strong>
          <span class="muted gsel-sub">${sig === "cc" ? "Cluster Coverage" : esc(sig)} ${hint("hint-cc", "SpreadEx ranks generated inputs by how much new input space each adds (Cluster Coverage) before running them. You can change the signal in Review & run.")}</span></span></div>
      <details class="gsel-adv"><summary>${ICONS.gear} Advanced settings</summary>
        <p class="muted">The selection signal and the embedding model are set in Review &amp; run.</p>
        <button type="button" class="linkish" onclick="gotoStep('run')">Open Review &amp; run</button></details>
    </div>
    <div class="side-card">
      <div class="gsel-h"><h4>Selected generators <span class="muted">(${sel.length})</span></h4>
        ${sel.length ? `<button type="button" class="linkish" onclick="clearGenerators()">Clear all</button>` : ""}</div>
      ${sel.length ? sel.map(g => `<div class="gsel-row">${genLogo(g.id)}<strong>${esc(g.name)}</strong>
        <span class="muted">${g.installed ? (cleanVersion(g.version) ? "v" + esc(cleanVersion(g.version)) : "") : "installs on run"}</span>
        <button type="button" class="gx" onclick="removeGen('${esc(g.id)}')" aria-label="Remove ${esc(g.name)}">&times;</button></div>`).join("")
        : `<div class="muted">None yet. Tick a generator, or click one to see its options.</div>`}
    </div>
    <div class="side-card">
      <h4><span class="h-ico amber">${ICONS.bulb}</span> Tips</h4>
      <ul class="tips-list">${["Select at least one generator.", "Generators that cannot run your grammar are disabled, with the reason.",
        "Click a generator to see its options and install it.", "Compare generators after your first run."]
        .map(t => `<li><span aria-hidden="true">${ICONS.check}</span>${esc(t)}</li>`).join("")}</ul>
    </div>
   </aside>
  </div>
  <div id="gen-modal-host"></div>`;
  if (CONSTRAINTS.open) paintConstraints();
  if (d.modal) paintGenModal();
}

// A popup per generator: what it is, whether it can run this grammar, and the choices that are real
// for it today. Only Fandango and ISLa have one (use my constraints file, or the grammar alone).
function openGenModal(id, opener) {
  const d = genState();
  // The clicked card, not document.activeElement: Safari does not focus a button on click.
  d.modal = id; d.opener = opener || document.activeElement; d.openerGen = id;
  const opt = (cfg().generator_options || {})[id] || {};
  d.draftConstraints = opt.constraints !== false;
  paintGenModal();
}
function closeGenModal() {
  const d = genState();
  const back = (d.opener && document.contains(d.opener)) ? d.opener
    : document.querySelector(`.gcard[data-gen="${d.openerGen}"] .gbody`);
  d.modal = null; el("gen-modal-host").innerHTML = "";
  if (back) back.focus();
}
function setGenConstraints(v) { genState().draftConstraints = v; paintGenModal(); }

function confirmGenModal() {
  const d = genState(), id = d.modal, g = (S.generators || []).find(x => x.id === id);
  if (!g) return closeGenModal();
  const nativeFile = (cfg().semantics?.native || {})[id];
  const opts = { ...(cfg().generator_options || {}) };
  if (g.constraints && nativeFile) {
    if (d.draftConstraints) delete opts[id]; else opts[id] = { constraints: false };
  }
  S.config.generator_options = Object.keys(opts).length ? opts : undefined;
  const set = new Set(cfg().generators || []); set.add(id);
  S.config.generators = [...set];
  closeGenModal(); paintGenerators();
}
function removeFromModal() { const id = genState().modal; closeGenModal(); toggleGen(id, false); }

function paintGenModal() {
  const d = genState(), g = (S.generators || []).find(x => x.id === d.modal);
  if (!g) return;
  const chosen = (cfg().generators || []).includes(g.id);
  const fit = genFit(g);
  const nativeFile = (cfg().semantics?.native || {})[g.id];
  const hasGuidance = !!(cfg().semantics?.guidance || []).length;
  const supportRow = ((d.analysis && d.analysis.support) || []).find(x => x.generator === g.id);
  let options;
  if (g.constraints) {
    const withOk = !!nativeFile;
    options = `<div class="gm-opts" role="radiogroup" aria-label="${esc(g.name)} options">
      <label class="gm-opt ${d.draftConstraints ? "" : "on"}"><input type="radio" name="gm-c" ${d.draftConstraints ? "" : "checked"} onchange="setGenConstraints(false)">
        <span><strong>Grammar only</strong><span class="muted">Run ${esc(g.name)} on your grammar without constraints.</span></span></label>
      <label class="gm-opt ${d.draftConstraints && withOk ? "on" : ""} ${withOk ? "" : "dis"}"><input type="radio" name="gm-c" ${d.draftConstraints && withOk ? "checked" : ""} ${withOk ? "" : "disabled"} onchange="setGenConstraints(true)">
        <span><strong>Use my constraints</strong><span class="muted">${withOk
          ? `Your file <span class="mono">${esc(nativeFile)}</span> is used as written.`
          : `No ${esc(g.name)} constraints file yet. Add one under Advanced in step 2.${hasGuidance ? " Your written guidance is not translated for you." : ""}`}</span></span></label></div>`;
  } else {
    options = `<p class="muted gm-none">There is nothing to set for ${esc(g.name)}: it runs from your grammar. Options will appear here as they are added.</p>`;
  }
  const status = g.installed
    ? `<span class="tag ok">Installed${cleanVersion(g.version) ? " v" + esc(cleanVersion(g.version)) : ""}</span> <span class="muted">${esc(g.where || "")}</span>`
    : `${installTag(g)} <button type="button" class="ghost small" onclick="closeGenModal(); installGen('${esc(g.id)}')">${ICONS.download} Install now</button>`;
  const lazy = g.installed ? "" : `<p class="muted gm-sum">${esc(g.name)} is not installed. If you use it, SpreadEx downloads it into its own
    environment when you start the run, after the setup is finished. That keeps the first install small. Or install it now.</p>`;
  el("gen-modal-host").innerHTML = `
  <div class="gm-back" onclick="if (event.target === this) closeGenModal()">
   <div class="gm" role="dialog" aria-modal="true" aria-labelledby="gm-t" onkeydown="genModalKeys(event)">
    <header class="gm-h">${genLogo(g.id, true)}
      <div><h3 id="gm-t">Configure ${esc(g.name)}</h3>
        ${refLine(g.reference)}
        <div class="gtags"><span class="tag gfam">${esc(FAMILY_LABEL[g.family] || "Grammar")}</span> ${status}</div></div>
      <button type="button" class="gx" onclick="closeGenModal()" aria-label="Close">&times;</button></header>
    <p class="muted gm-sum">${esc(g.summary)}</p>
    ${lazy}
    <h4 class="inp-h5">Can it run your grammar?</h4>
    ${fit.ok ? `<div class="gm-fit ok">${ICONS.success}<span>${fit.how === "rewrite" ? "Yes, after rewriting the grammar into its dialect." : "Yes, directly."}
        ${(fit.risks || []).map(r => `<span class="warn gm-risk">! ${esc(r)}</span>`).join("")}</span></div>`
      : `<div class="gm-fit bad">${ICONS.error}<span>${esc(fit.why)}</span></div>`}
    <h4 class="inp-h5">Generation options</h4>
    ${options}
    <div class="gm-f">
      ${chosen ? `<button type="button" class="ghost subtle-danger" onclick="removeFromModal()">Remove ${esc(g.name)}</button>` : ""}
      <span class="gm-sp"></span>
      <button type="button" class="ghost" onclick="closeGenModal()">Cancel</button>
      <button type="button" class="primary" id="gm-ok" onclick="confirmGenModal()" ${fit.ok || chosen ? "" : "disabled"}>${chosen ? "Save options" : `Use ${esc(g.name)}`}</button>
    </div>
   </div></div>`;
  (el("gm-ok") || document.querySelector(".gm .gx"))?.focus({ preventScroll: true });
}

// Keep Tab inside the dialog and close it on Escape.
function genModalKeys(e) {
  if (e.key === "Escape") { e.stopPropagation(); closeGenModal(); return; }
  if (e.key !== "Tab") return;
  const f = [...document.querySelectorAll(".gm button:not([disabled]), .gm input:not([disabled])")];
  if (!f.length) return;
  const first = f[0], last = f[f.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
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

function toggleGen(id, force) {
  const set = new Set(cfg().generators || []);
  const want = force === undefined ? !set.has(id) : force;
  want ? set.add(id) : set.delete(id);
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
  // Generators that are not installed are installed when the run starts (see the review screen).
  S.confirmed.add("generators");
  gotoStep("strategy");
  tourEvent("step.generators");
}

// ------------------------------------------------- step 5: review & run

function runState() {
  if (!S.run) S.run = runFromConfig(cfg());
  return S.run;
}
function nGenerators() { return (cfg().generators || []).length; }
function timeoutSecs() { return durationSeconds(sut().timeout || "5s") || 5; }

// Write the choices to the config. Called after every edit, so the YAML preview, the summary and
// the saved file can never disagree with what is on screen.
function syncRun() {
  const r = runState(), b = budgetFromRun(r, nGenerators(), timeoutSecs());
  S.config.generation = b.generation;
  S.config.budget = b.budget;
  S.config.selection_signal = r.signal;
  // Only meaningful with something to choose from, and only with Cluster Coverage scores to choose by.
  if (nGenerators() > 1 && r.signal === "cc" && r.keep > 0 && r.keep < nGenerators()) S.config.selection = { by: "cc", keep: r.keep };
  else delete S.config.selection;
  S.config.embedding = { model: r.model };
  return r;
}

// Typing updates the state and the panels beside it, but never re-renders the inputs themselves
// (that would drop focus on every keystroke).
function runInput(key, value, integer) {
  const r = runState();
  const n = Number(value);
  r[key] = value === "" || Number.isNaN(n) ? NaN : (integer ? Math.trunc(n) : n);
  if (!runProblems(r).length) syncRun();
  refreshRunPanels();
}
function runSet(key, value) { runState()[key] = value; if (!runProblems(runState()).length) syncRun(); stepRun(); }
function refreshRunPanels() {
  if (el("run-ready")) el("run-ready").innerHTML = readyCard();
  if (el("run-summary")) el("run-summary").innerHTML = summaryCard();
  if (el("run-est")) el("run-est").innerHTML = estimateLines();
  if (el("preview")) el("preview").textContent = runProblems(runState()).length ? "Fix the highlighted values to see the file." : buildYaml();
  const b = el("launch"); if (b) b.disabled = !readiness().ready;
}

function readiness() {
  const c = cfg(), r = runState();
  const items = [
    { id: "sut", t: "SUT", ok: stepDone("sut"), fix: "sut", why: "Add the command that runs your program and test the connection." },
    { id: "grammar", t: "Grammar", ok: !!(c.grammar?.source || c.corpus?.path), fix: "grammar", why: "Choose a grammar, or a folder of inputs." },
    { id: "generators", t: "Generators", ok: !!((c.generators || []).length || c.corpus?.path), fix: "generators", why: "Select at least one generator." },
    { id: "strategy", t: "Strategy", ok: !!c.oracle, fix: "strategy", why: "Choose what to detect." },
    { id: "budget", t: "Budget", ok: !runProblems(r).length, fix: null, why: runProblems(r)[0] || "" },
    { id: "storage", t: "Storage", ok: S.project?.writable !== false, fix: null, why: "SpreadEx cannot write to this project folder." },
  ];
  return { items, ready: items.every(i => i.ok) };
}

function estimateLines() {
  const e = runEstimate(runState(), nGenerators(), timeoutSecs());
  const r = runState();
  const gen = nGenerators() === 0 ? "no generation (existing inputs)" : `${e.genExact ? "~" : "up to "}${fmtSeconds(e.genS)} generation`;
  const ex = r.execMode === "corpus" ? "until every input has run" : `${e.execExact ? "" : "up to "}${fmtSeconds(e.execS)} execution`;
  const total = e.totalS === null ? "Time depends on the number of inputs" : `${e.exact ? "~" : "Up to ~"}${fmtSeconds(e.totalS)}`;
  return `<div class="est-total"><span class="est-ico" aria-hidden="true">${ICONS.clock}</span><strong>${esc(total)}</strong>
      ${hint("hint-est", "Generation plus execution. A time limit is exact; a number of tests is the worst case (every input using its full timeout); running the whole corpus has no fixed length.")}</div>
    <div class="est-row">${ICONS.doc}<span>${esc(gen)}</span></div>
    <div class="est-row">${ICONS.playOutline}<span>${esc(ex)}</span></div>`;
}

function readyCard() {
  const { items, ready } = readiness();
  const bad = items.filter(i => !i.ok);
  return `<div class="ready-l ${ready ? "ok" : "warn"}">
      <span class="ready-ico" aria-hidden="true">${ready ? ICONS.success : ICONS.alert}</span>
      <div><h4>${ready ? "Ready to run" : "Not ready yet"} ${hint("hint-ready", "Each item is checked from what you set in the earlier steps. A problem names the step to fix.")}</h4>
        ${ready ? "" : `<div class="ready-why" role="status">${bad.map(i => `${esc(i.why)}${i.fix ? ` <button type="button" class="linkish" onclick="gotoStep('${i.fix}')">Fix</button>` : ""}`).join("<br>")}</div>`}</div></div>
    <ul class="ready-list">${items.map(i => `<li class="${i.ok ? "ok" : "bad"}"><span aria-hidden="true">${i.ok ? ICONS.success : ICONS.error}</span>${esc(i.t)}</li>`).join("")}</ul>
    <div class="ready-est" id="run-est">${estimateLines()}</div>`;
}

function summaryCard() {
  const c = cfg(), r = runState(), t = targets()[0];
  const row = (tone, icon, title, body, step) => `<div class="sum-row"><span class="stile ${tone}" aria-hidden="true">${ICONS[icon]}</span>
      <div class="sum-t"><strong>${esc(title)}</strong><span class="muted">${body}</span></div>
      <button type="button" class="linkish" onclick="gotoStep('${step}')">Edit</button></div>`;
  const cmd = t ? (t.command || []).slice(0, 2).join(" ") : "Not set";
  const d = inpState();
  const inputs = c.grammar?.source ? `${d.lang ? esc(langById(d.lang).t) + " · " : ""}<span class="mono">${esc(c.grammar.source.split("/").pop())}</span>`
    : c.corpus?.path ? `Folder <span class="mono">${esc(c.corpus.path)}</span>` : "Not chosen";
  const gens = (c.generators || []).map(id => ((S.generators || []).find(g => g.id === id) || { name: id }).name);
  const o = c.oracle || {};
  const checks = ["Crash", "Timeout"].concat((o.rejection_patterns || []).length || (o.expected_exit_codes || []).length ? ["Rejection"] : [],
    (o.crash_patterns || []).length ? ["Signatures"] : [], o.type === "differential" ? ["Differential"] : []);
  const budget = `${r.genMode === "time" ? `${r.perGen} s / generator` : `${r.count} inputs / generator`} &middot; ${r.execMode === "time" ? `${esc(String(r.execMinutes))} min` : r.execMode === "count" ? `${r.execCount} tests` : "whole corpus"}`;
  const pending = (S.generators || []).filter(isPending).map(g => g.name);
  return `${row("red", "terminal", "System under test", `<span class="mono">${esc(cmd)}</span>`, "sut")}
    ${row("blue", "doc", "Inputs", inputs, "grammar")}
    ${row("purple", "sliders", `Generators (${gens.length})`, gens.length ? esc(gens.join(", ")) : "None (existing inputs only)", "generators")}
    ${row("orange", "shield", "Testing strategy", esc(checks.join(", ")), "strategy")}
    ${row("green", "stats", "Test ordering", r.signal === "random" ? "Random (baseline)" : "SpreadEx prioritization", "run")}
    ${row("slate", "clock", "Budget", budget, "run")}
    ${pending.length ? `<div class="sum-pend">${ICONS.download}<span>Installed on first run: ${pending.map(esc).join(", ")}. Downloaded from PyPI into ${pending.length > 1 ? "their own environments" : "its own environment"} before the clock starts.</span></div>` : ""}`;
}

function runNumber(id, key, value, min, integer, unit, aria) {
  const bad = Number.isNaN(value) || value < min;
  return `<span class="unitbox rn ${bad ? "bad" : ""}"><input id="${id}" type="number" min="${min}" step="${integer ? 1 : "any"}" class="sut-cmd"
      value="${Number.isNaN(value) ? "" : esc(String(value))}" aria-label="${esc(aria)}" aria-invalid="${bad}" oninput="runInput('${key}', this.value, ${integer})"><span class="unit">${esc(unit)}</span></span>`;
}

function runOption({ on, title, tag, body, onclick, group }) {
  return `<div class="ropt ${on ? "on" : ""}"><label class="ropt-h"><input type="radio" name="${group}" ${on ? "checked" : ""} onchange="${onclick}">
      <span class="rdot" aria-hidden="true"></span><strong>${title}</strong>${tag ? `<span class="tag pend">${tag}</span>` : ""}</label>
      ${on && body ? `<div class="ropt-b">${body}</div>` : ""}</div>`;
}

async function stepRun(current = () => true) {
  if (!S.generators) { try { S.generators = (await api("/api/generators")).generators; } catch (e) { /* the summary just omits the row */ } }
  if (S.project?.writable === undefined) { try { S.project = await api("/api/project"); } catch (e) { /* non-fatal */ } }
  if (!current()) return;
  if (!cfg().generation) S.config.generation = { mode: "time", per_generator: "30s" };
  const r = runState();
  syncRun();
  const grp = (name, o) => runOption({ ...o, group: name });
  el("view").innerHTML = `
  <div class="sut runpage">
   <div class="sut-main">
    <header class="sut-head">
      <span class="sut-badge red" aria-hidden="true">5</span>
      <div><h3>Review &amp; run</h3>
        <p class="why">Set the budget, review your configuration, and launch the campaign.</p></div>
    </header>

    <div class="rbudgets">
      <section class="rcard purple" aria-labelledby="rg-h" data-tour="run-genbudget">
        <h4 id="rg-h"><span class="stile purple" aria-hidden="true">${ICONS.doc}</span> Generation budget
          ${hint("hint-gen", "How much each generator is given to produce inputs. Equal time answers \\u201cwho makes better use of a budget\\u201d; they will produce different numbers of inputs, and that is the measurement.")}</h4>
        <div class="ropts two">
          ${grp("gm", { on: r.genMode === "time", title: "Equal time", tag: "Recommended", onclick: "runSet('genMode','time')",
            body: `${runNumber("run-pergen", "perGen", r.perGen, 0.1, false, "s / generator", "Seconds per generator")}
                   <p class="muted">Every generator gets the same time. Cluster coverage is computed over the pooled inputs, so a much faster generator contributes more of that pool.</p>` })}
          ${grp("gm", { on: r.genMode === "count", title: "Equal count", onclick: "runSet('genMode','count')",
            body: `${runNumber("run-count", "count", r.count, 1, true, "inputs / generator", "Inputs per generator")}
                   <p class="muted">Reproducible, but not resource-fair: the same number of inputs can cost one generator seconds and another minutes.</p>` })}
        </div>
      </section>

      <section class="rcard blue" aria-labelledby="re-h" data-tour="run-execbudget">
        <h4 id="re-h"><span class="stile blue" aria-hidden="true">${ICONS.playOutline}</span> Execution budget
          ${hint("hint-exec", "When to stop running inputs against your system. Whichever you choose, each input still has its own timeout from the Testing strategy step.")}</h4>
        <div class="ropts">
          ${grp("em", { on: r.execMode === "time", title: "Time limit", onclick: "runSet('execMode','time')",
            body: runNumber("run-execmin", "execMinutes", r.execMinutes, 0.1, false, "minutes", "Execution time limit in minutes") })}
          ${grp("em", { on: r.execMode === "count", title: "Number of tests", onclick: "runSet('execMode','count')",
            body: runNumber("run-execcount", "execCount", r.execCount, 1, true, "executions", "Number of executions") })}
          ${grp("em", { on: r.execMode === "corpus", title: "Entire corpus", onclick: "runSet('execMode','corpus')",
            body: `<p class="muted">Run every input that was generated, however long it takes (stopped at 24 hours).</p>` })}
        </div>
      </section>
    </div>

    <section class="rcard green wide" aria-labelledby="ro-h" data-tour="run-ordering">
      <h4 id="ro-h"><span class="stile green" aria-hidden="true">${ICONS.table}</span> Test ordering
        ${hint("hint-order", "Which generated inputs run first. SpreadEx prioritization uses the diversity map to put the most different inputs first; random order is the baseline to compare against.")}</h4>
      <div class="ropts two">
        ${grp("so", { on: r.signal === "cc", title: "SpreadEx prioritization", tag: "Recommended", onclick: "runSet('signal','cc')",
          body: `<p class="muted">The most different inputs first, from the diversity map.</p>` })}
        ${grp("so", { on: r.signal === "random", title: "Random order", onclick: "runSet('signal','random')",
          body: `<p class="muted">The baseline. Useful to see what prioritization is worth.</p>` })}
      </div>
      ${nGenerators() > 1 && r.signal === "cc" ? `<div class="rsel-h"><strong>Generator selection</strong>
        ${hint("hint-gsel", "After generating, SpreadEx measures each generator's Cluster Coverage over all the inputs, then runs only the inputs of the generators you keep. Coverage is still reported for every generator.")}</div>
      <div class="ropts ${nGenerators() > 2 ? "three" : "two"}">
        ${grp("gs", { on: !(r.keep > 0 && r.keep < nGenerators()), title: "All generators", onclick: "runSet('keep',0)",
          body: `<p class="muted">Run every generator's inputs; Cluster Coverage is only reported.</p>` })}
        ${grp("gs", { on: r.keep === 1, title: "Best generator", onclick: "runSet('keep',1)",
          body: `<p class="muted">Keep the one with the highest Cluster Coverage and run only its inputs.</p>` })}
        ${nGenerators() > 2 ? grp("gs", { on: r.keep === 2, title: "Best 2 generators", onclick: "runSet('keep',2)",
          body: `<p class="muted">Keep the two with the highest Cluster Coverage.</p>` }) : ""}
      </div>` : ""}
      <details class="sut-adv"><summary><span><strong>Advanced</strong></span><span class="muted">Embedding model and parallel executions</span></summary>
        <div class="sut-adv-body"><div class="row">
          <div><label for="run-model">Embedding</label><select id="run-model" onchange="runSet('model', this.value)">
            <option value="tfidf" ${r.model === "tfidf" ? "selected" : ""}>TF-IDF (no GPU, no key)</option>
            <option value="unixcoder" ${r.model === "unixcoder" ? "selected" : ""}>UniXcoder (needs spreadex[neural])</option></select></div>
          <div><label for="jobs">Parallel executions</label><input id="jobs" type="number" min="1" max="32" value="${r.jobs}" oninput="runState().jobs = Math.max(1, Number(this.value) || 1)"></div>
        </div><p class="muted">More than one parallel execution is faster, but makes durations noisier and can time out an input that would have passed on its own.</p></div>
      </details>
    </section>

    <section class="rcard ready" id="run-ready" aria-live="polite">${readyCard()}</section>

    <details class="sut-adv"><summary><span><strong>The file that will be written</strong></span><span class="muted">spreadex.yaml &mdash; you can also edit it by hand</span></summary>
      <div class="sut-adv-body"><pre id="preview">${esc(runProblems(r).length ? "Fix the highlighted values to see the file." : buildYaml())}</pre></div></details>

    <div id="err"></div>
    <div id="joblog"></div>
    <div class="actions inp-actions"><button type="button" class="ghost" onclick="gotoStep('strategy')">${ICONS.back} Back to Testing strategy</button></div>
   </div>

   <aside class="sut-side" aria-label="Summary">
    <div class="side-card sumcard">
      <div class="gsel-h"><h4><span class="stile slate" aria-hidden="true">${ICONS.doc}</span> Campaign summary</h4>
        <button type="button" class="ghost small" onclick="gotoStep('sut')">${ICONS.edit} Edit all</button></div>
      <div id="run-summary">${summaryCard()}</div>
    </div>
    <div class="side-card runcard">
      <button type="button" class="primary runbtn" id="launch" data-tour="run-launch" onclick="launch()" ${readiness().ready ? "" : "disabled"}>${ICONS.playOutline} Run campaign</button>
      <p class="muted runnote">${ICONS.shield}<span>Your inputs and results stay on this machine.${(S.generators || []).some(isPending) ? " Missing generators are downloaded from PyPI first." : ""}</span></p>
    </div>
   </aside>
  </div>`;
}

async function launch() {
  if (!readiness().ready) return;
  syncRun();
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
    const started = await api("/api/run", { jobs: runState().jobs || 1, install_missing: true });
    if (started.ok === false) throw new Error(started.error);
  } catch (e) {
    el("err").innerHTML = `<div class="note bad">${esc(e.message)}</div>`;
    el("launch").disabled = false;
    return;
  }
  // Land on the campaign that is running, not on a list: that is the one being waited for.
  startLive();
  tourEvent("campaign.started");
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
//
// One workspace over one run, answering in order: did anything fail, what should I investigate, was
// the testing effective, which generator contributed, can I reproduce it. Every number is read from
// what the run recorded. What a run did not record (coverage, mutation score, cost, cluster
// assignments) is not shown, rather than estimated.

async function loadRuns() {
  const r = await api("/api/runs");
  S.runs = r.runs;
  if (!S.current || !S.runs.some(x => x.run_id === S.current)) S.current = S.runs[0]?.run_id || null;
}

const VERDICTS = {
  ok:                 { label: "Passed",             color: "#16A34A", tone: "green" },
  expected_rejection: { label: "Expected rejection", color: "#1687F8", tone: "blue" },
  crash:              { label: "Crash",              color: "#EF4444", tone: "red" },
  timeout:            { label: "Timeout",            color: "#F59E0B", tone: "amber" },
  divergence:         { label: "Divergence",         color: "#9333EA", tone: "purple" },
};
const VORDER = ["ok", "expected_rejection", "crash", "timeout", "divergence"];
const vtag = v => `<span class="vtag ${(VERDICTS[v] || {}).tone || ""}">${esc((VERDICTS[v] || { label: v }).label)}</span>`;
const GEN_COLORS = ["#1687F8", "#9333EA", "#F59E0B", "#16A34A", "#EF4444", "#64748B"];
const genColor = (name, all) => GEN_COLORS[Math.max(0, all.indexOf(name)) % GEN_COLORS.length];

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" });
}
function fmtTime(iso) { const d = new Date(iso); return isNaN(d) ? "" : d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }); }

// ------- small SVG charts (no library; they follow the theme through currentColor and tokens)

function donut(parts, total, centre, sub) {
  const R = 52, C = 2 * Math.PI * R;
  let acc = 0;
  const arcs = parts.filter(p => p.n > 0).map(p => {
    const len = (p.n / total) * C, seg = `<circle cx="70" cy="70" r="${R}" fill="none" stroke="${p.color}" stroke-width="16"
      stroke-dasharray="${Math.max(0.5, len - (parts.filter(q => q.n > 0).length > 1 ? 1.5 : 0))} ${C}" stroke-dashoffset="${-acc}" transform="rotate(-90 70 70)"><title>${esc(p.label)}: ${p.n}</title></circle>`;
    acc += len;
    return seg;
  }).join("");
  return `<svg class="donut" viewBox="0 0 140 140" role="img" aria-label="${esc(centre)} ${esc(sub)}">
    <circle cx="70" cy="70" r="${R}" fill="none" stroke="var(--color-border)" stroke-width="16"/>${arcs}
    <text x="70" y="68" text-anchor="middle" class="donut-n">${esc(centre)}</text>
    <text x="70" y="86" text-anchor="middle" class="donut-s">${esc(sub)}</text></svg>`;
}

// Vertical stacked columns over a list of bins; `keys` are the stacked series, in drawing order.
function stackedColumns(bins, keys, colors, xLabel) {
  if (!bins.length) return `<div class="empty">Nothing was executed.</div>`;
  const W = 640, H = 190, P = { l: 34, r: 8, t: 8, b: 26 };
  const max = Math.max(1, ...bins.map(b => keys.reduce((s, k) => s + (b[k] || 0), 0)));
  const bw = (W - P.l - P.r) / bins.length;
  const y = v => H - P.b - (v / max) * (H - P.t - P.b);
  const ticks = [0, 0.5, 1].map(f => Math.round(max * f));
  const bars = bins.map((b, i) => {
    let base = 0;
    return keys.map((k, j) => {
      const v = b[k] || 0; if (!v) return "";
      const rect = `<rect x="${P.l + i * bw + 1}" y="${y(base + v)}" width="${Math.max(1, bw - 2)}" height="${y(base) - y(base + v)}" fill="${colors[j]}"><title>inputs ${b.from}–${b.to}: ${k.replace("_", " ")} ${v}</title></rect>`;
      base += v; return rect;
    }).join("");
  }).join("");
  const last = bins[bins.length - 1].to;
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Outcomes in execution order">
    ${ticks.map(t => `<g><line x1="${P.l}" x2="${W - P.r}" y1="${y(t)}" y2="${y(t)}" class="grid"/><text x="${P.l - 5}" y="${y(t) + 3}" text-anchor="end" class="axis">${t}</text></g>`).join("")}
    ${bars}
    <text x="${P.l}" y="${H - 8}" class="axis">1</text><text x="${(W + P.l) / 2}" y="${H - 8}" text-anchor="middle" class="axis">${esc(xLabel || "inputs, in execution order")}</text><text x="${W - P.r}" y="${H - 8}" text-anchor="end" class="axis">${last}</text></svg>`;
}

// Horizontal bars, one per row; `max` fixes the scale so rows can be compared.
function hbars(rows, max, fmt) {
  return `<div class="hbars">${rows.map(r => `<div class="hbar"><span class="hb-l">${esc(r.label)}</span>
    <span class="hb-t"><span class="hb-f" style="width:${max ? Math.max(0, Math.min(100, 100 * r.value / max)) : 0}%;background:${r.color}"></span></span>
    <span class="hb-v">${esc(fmt ? fmt(r.value) : String(r.value))}</span></div>`).join("")}</div>`;
}

function legend(items) {
  return `<div class="legend">${items.map(i => `<span><i style="background:${i.color}"></i>${esc(i.label)}</span>`).join("")}</div>`;
}

function resCard(title, body, { tip, right, cls = "", tour = "" } = {}) {
  return `<section class="rescard ${cls}"${tour ? ` data-tour="${tour}"` : ""}><div class="rescard-h"><h4>${esc(title)}${tip ? " " + hint("hint-r-" + title.replace(/\W+/g, ""), tip) : ""}</h4>${right || ""}</div>${body}</section>`;
}

// ------- the header every tab shares

// A campaign is named by its run id, which never changes: deleting another campaign cannot
// rename this one, and it is the same id the CLI, exports and replay use.
function campaignName(id) { return `Campaign ${id}`; }
function runTitle(d) { return campaignName(d.run_id); }

function resultsHeader(d) {
  const v = d.verdicts || {}, c = d.corpus || {};
  const t = (d.targets || [])[0] || {};
  const kpi = (tone, icon, n, label) => `<div class="kpi ${tone}"><span class="stile ${tone}" aria-hidden="true">${ICONS[icon]}</span>
      <div><strong>${num(n)}</strong><span>${label}</span></div></div>`;
  const status = statusPill((S.runs.find(r => r.run_id === S.current) || {}).status || (d.complete ? "finished" : "aborted"));
  return `<header class="reshead">
    <button type="button" class="rback" onclick="showCampaigns()" aria-label="Back to campaigns" title="Back to campaigns">${ICONS.back}</button>
    <div class="rtitle">
      <div class="rtitle-1"><div class="runpick"><button type="button" class="runpick-b" aria-haspopup="listbox" aria-expanded="${!!S.runMenu}" onclick="toggleRunMenu()">
          <h2>${esc(runTitle(d))}</h2>${(S.runs || []).length > 1 ? ICONS.chevron : ""}</button>
          ${S.runMenu ? `<div class="runmenu" role="listbox">${S.runs.map((r, i) => `<button type="button" role="option" aria-selected="${r.run_id === S.current}" onclick="pickRun('${esc(r.run_id)}')">
            <strong>${esc(r.run_id)}</strong><span>${esc(fmtDate(r.started_at))} ${esc(fmtTime(r.started_at))}</span><span class="${r.failures ? "bad" : "muted"}">${r.failures ? r.failures + " failing" : "no failures"}</span></button>`).join("")}</div>` : ""}</div>
        ${status}</div>
      <div class="rtitle-2"><strong>${esc(t.name || "sut")}</strong>${t.version ? ` <span class="muted">${esc(String(t.version).split("\n")[0].slice(0, 40))}</span>` : ""}</div>
      <div class="rtitle-3"><span>${ICONS.clock} ${esc(fmtDate(d.started_at))} · ${esc(fmtTime(d.started_at))}</span><span>${ICONS.playOutline} ${esc(fmtDur(d.duration_s))}</span><span>seed ${esc(String(d.seed))}</span></div>
    </div>
    <div class="kpis" data-tour="res-kpis">
      ${kpi("blue", "doc", c.generated ?? 0, "Generated")}
      ${kpi("green", "success", c.valid ?? 0, "Valid inputs")}
      ${kpi("blue", "playOutline", d.executed, "Executed")}
      ${kpi("red", "bug", v.crash || 0, "Crashes")}
      ${kpi("amber", "clock", v.timeout || 0, "Timeouts")}
      ${kpi("purple", "scale", v.divergence || 0, "Divergences")}
    </div>
    <div class="ractions">
      <div class="runpick"><button type="button" class="ghost rmore" aria-haspopup="menu" aria-expanded="${!!S.actMenu}" aria-label="More actions" onclick="toggleActMenu()">${ICONS.dots}</button>
        ${S.actMenu ? `<div class="runmenu right" role="menu">
          <button type="button" role="menuitem" onclick="copyReplayCommand()">Copy replay command</button>
          ${canAct() ? `<button type="button" role="menuitem" onclick="rerunCampaign(S.current)">Run again with this configuration</button>
          <button type="button" role="menuitem" onclick="S.actMenu = false; go('setup'); gotoStep('run')">Edit setup, then run…</button>
          <button type="button" role="menuitem" class="danger" onclick="deleteCampaign(S.current)">Delete campaign…</button>` : ""}</div>` : ""}</div>
      <button type="button" class="ghost rexport" onclick="exportRun()">${ICONS.download} Export</button>
    </div></header>`;
}

function toggleRunMenu() { S.runMenu = !S.runMenu; S.actMenu = false; paintRun(); }
function toggleActMenu() { S.actMenu = !S.actMenu; S.runMenu = false; paintRun(); }
function copyReplayCommand() {
  S.actMenu = false; paintRun();
  if (navigator.clipboard?.writeText) navigator.clipboard.writeText(`spreadex replay ${S.current}`).catch(() => {});
}
// The export needs the token header, so it is fetched and saved rather than linked.
async function downloadExport(id) {
  const r = await fetch(`/api/runs/${encodeURIComponent(id)}/export`, { headers: { "X-SpreadEx-Token": TOKEN } });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
  const url = URL.createObjectURL(await r.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: `spreadex-${id}.zip` });
  document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
}
async function exportRun() {
  try { await downloadExport(S.current); }
  catch (e) { S.exportError = String(e.message || e); paintRun(); }
}

const RESULT_TABS = [
  { id: "overview", t: "Overview", icon: "chart" },
  { id: "generators", t: "Generators", icon: "grid" },
  { id: "budget", t: "Budget", icon: "clock" },
  { id: "findings", t: "Findings", icon: "bug" },
  { id: "corpus", t: "Corpus", icon: "database" },
];

function pickResultTab(id) { S.rtab = id; S.runMenu = S.actMenu = false; paintRun(); if (id === "corpus") loadCorpus(); if (id === "findings") ensureFinding(); tourEvent("tab." + id); }

// ------- Overview: what happened

function tabOverview(d) {
  const v = d.verdicts || {}, total = d.executed || 0;
  const parts = VORDER.map(k => ({ key: k, n: v[k] || 0, label: VERDICTS[k].label, color: VERDICTS[k].color }));
  const outcome = `<div class="outcome">${donut(parts, total || 1, num(total), "executed")}
    <div class="outrows">${parts.map(p => `<div class="outrow"><i style="background:${p.color}"></i><span class="o-l">${p.label}</span><strong>${num(p.n)}</strong>
      <span class="o-p">${fmtPct(p.n, total)}</span><span class="o-b"><span style="width:${total ? 100 * p.n / total : 0}%;background:${p.color}"></span></span></div>`).join("")}</div></div>`;

  const fs = d.findings || [];
  const top = fs.length ? `<table class="rtable"><thead><tr><th>#</th><th>Type</th><th>Signature</th><th>Generator</th><th>First seen</th></tr></thead><tbody>
      ${fs.slice(0, 5).map((f, i) => `<tr class="click" onclick="openFinding('${esc(f.signature)}')"><td>${i + 1}</td><td>${vtag(f.verdict)}</td>
        <td class="sig">${esc(f.stderr_first)}</td><td>${esc(f.generator)}</td><td>input #${f.position + 1}</td></tr>`).join("")}</tbody></table>
      ${fs.length > 5 ? `<button type="button" class="linkish" onclick="pickResultTab('findings')">${fs.length - 5} more finding${fs.length - 5 > 1 ? "s" : ""}</button>` : ""}`
    : `<div class="empty">No failures in ${num(total)} executed inputs. For a mature system under test that is the expected outcome, not a missing measurement.</div>`;

  const p = d.prioritization || {};
  const prio = p.findings ? `<div class="mini3">
      <div><strong>${num(p.first_at)}</strong><span>First finding at input</span></div>
      <div><strong>${p.by_quarter} / ${p.findings}</strong><span>Findings in the first 25%</span></div>
      <div><strong>${p.all_pct}%</strong><span>of the run when the last one appeared</span></div></div>
      <div class="rnote">${ICONS.info}<div>Inputs run in SpreadEx's priority order. Budget compares this with a random order of the same inputs.
        <button type="button" class="linkish" onclick="pickResultTab('budget')">See Budget</button></div></div>`
    : `<div class="empty">Nothing failed, so there is no discovery order to report.</div>`;

  const gens = d.by_generator || [];
  const gtable = `<div class="tscroll"><table class="rtable"><thead><tr><th>Generator</th><th>Generated</th><th>Valid</th><th>Executed</th><th>Findings</th><th>Pass rate</th></tr></thead><tbody>
    ${gens.map(g => `<tr><td><i class="dotc" style="background:${genColor(g.name, gens.map(x => x.name))}"></i>${esc(g.name)}</td><td>${num(g.generated)}</td><td>${num(g.valid)}</td><td>${num(g.executed)}</td>
      <td>${g.findings ? `<span class="count bad">${g.findings}</span>` : `<span class="muted">0</span>`}</td>
      <td class="passcell"><span>${g.pass_rate == null ? "—" : (100 * g.pass_rate).toFixed(1) + "%"}</span><span class="o-b"><span style="width:${100 * (g.pass_rate || 0)}%;background:#16A34A"></span></span></td></tr>`).join("")}
    <tr class="total"><td>Total</td><td>${num(d.corpus?.generated)}</td><td>${num(d.corpus?.valid)}</td><td>${num(d.executed)}</td><td><span class="count bad">${fs.length}</span></td>
      <td>${total ? ((100 * (v.ok || 0) / total).toFixed(1) + "%") : "—"}</td></tr></tbody></table>`;

  // Crashes that read like rejections: the most common first-run mistake, said plainly with the fix.
  const hints = d.rejection_hints || [];
  const hintNote = hints.length ? `<div class="res warn" role="note"><span class="res-ico" aria-hidden="true">${ICONS.alert}</span><div class="res-main">
      <div class="res-t">Some of these crashes look like your system rejecting input</div>
      <div class="res-s">${hints.map(h => `${num(h.inputs)} input${h.inputs > 1 ? "s" : ""}, exit ${h.exit_code}: <span class="mono">${esc(h.line.slice(0, 90))}</span>`).join("<br>")}</div>
      <div class="res-s">If that is how your system refuses invalid input, add ${hints.map(h => `<span class="mono">${esc(h.pattern)}</span>`).join(", ")} under <span class="mono">oracle.rejection_patterns</span> (Testing strategy step), and those inputs will count as expected rejections instead of findings.</div></div></div>` : "";
  return `${hintNote}<div class="resgrid">
    ${resCard("Campaign outcome", outcome, { tip: "How every executed input was judged. A refusal the system makes on purpose is an expected rejection, not a failure." })}
    ${resCard("Prioritization", prio, { tip: "When the findings were reached, against how many inputs were executed. Only what this run recorded." })}
    ${resCard("Top findings", top, { right: fs.length ? `<button type="button" class="ghost small" onclick="pickResultTab('findings')">View all ${ICONS.arrow}</button>` : "", cls: "wide-l" })}
    ${resCard("Generator contribution", gtable, { tip: "Per generator, from the inputs it produced and the verdicts they received.", cls: "wide-r" })}
    ${resCard("Execution outcome over time", stackedColumns(d.timeline || [], VORDER, VORDER.map(k => VERDICTS[k].color), "inputs, in execution order")
      + legend(VORDER.map(k => ({ label: VERDICTS[k].label, color: VERDICTS[k].color }))), { tip: "Outcomes in the order inputs were executed. With parallel executions this is position, not wall-clock time.", cls: "wide-l" })}
    ${resCard("Campaign details", detailsTable(d), { right: `<button type="button" class="ghost small" onclick="go('setup')">${ICONS.edit} Edit setup</button>`, cls: "wide-r" })}
  </div>`;
}

function detailsTable(d) {
  const t = (d.targets || [])[0] || {}, b = d.budgets || {}, o = d.oracle || {};
  const checks = ["Crash", "Timeout"].concat((o.rejection_patterns || []).length || (o.expected_exit_codes || []).length ? ["Rejection"] : [],
    (o.crash_patterns || []).length ? ["Signatures"] : [], o.type === "differential" ? ["Differential"] : []);
  const row = (k, v) => `<div class="drow"><span class="muted">${k}</span><span>${v}</span></div>`;
  const exec = b.max_inputs ? `${num(b.max_inputs)} executions` : (b.execution_s ? fmtDur(b.execution_s) : "—");
  return `<div class="dgrid">${row("SUT", esc(t.name || "sut"))}${row("Command", `<span class="mono">${esc((t.command || []).join(" "))}</span>`)}
    ${row("Generators", esc((d.by_generator || []).map(g => g.name).join(", ") || "—"))}${row("Testing strategy", esc(checks.join(", ")))}
    ${row("Test ordering", d.signal === "random" ? "Random (baseline)" : "SpreadEx prioritization")}${row("Execution budget", esc(exec))}</div>`;
}

// ------- Generators: who contributed

function groupedBars(rows, series, colors) {
  const W = 560, H = 190, P = { l: 38, r: 8, t: 10, b: 28 };
  const max = Math.max(1, ...rows.flatMap(r => series.map(s => r[s] || 0)));
  const gw = (W - P.l - P.r) / Math.max(1, rows.length), bw = Math.min(26, (gw - 14) / series.length);
  const y = v => H - P.b - (v / max) * (H - P.t - P.b);
  const ticks = [0, 0.5, 1].map(f => Math.round(max * f));
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Grouped bars per generator">
    ${ticks.map(t => `<g><line x1="${P.l}" x2="${W - P.r}" y1="${y(t)}" y2="${y(t)}" class="grid"/><text x="${P.l - 5}" y="${y(t) + 3}" text-anchor="end" class="axis">${t}</text></g>`).join("")}
    ${rows.map((r, i) => {
      const x0 = P.l + i * gw + (gw - bw * series.length) / 2;
      return series.map((s, j) => `<rect x="${x0 + j * bw}" y="${y(r[s] || 0)}" width="${bw - 2}" height="${y(0) - y(r[s] || 0)}" fill="${colors[j]}"><title>${esc(r.name)} ${s}: ${r[s] || 0}</title></rect>
        <text x="${x0 + j * bw + (bw - 2) / 2}" y="${y(r[s] || 0) - 3}" text-anchor="middle" class="axis">${r[s] || 0}</text>`).join("")
        + `<text x="${P.l + i * gw + gw / 2}" y="${H - 9}" text-anchor="middle" class="axis">${esc(r.name)}</text>`;
    }).join("")}</svg>`;
}

function tabGenerators(d) {
  const gens = d.by_generator || [], names = gens.map(g => g.name);
  // When the campaign selected generators by CC, say which, on every row.
  const sel = d.selection;
  const selTag = n => !sel ? "" : sel.selected.includes(n) ? ` <span class="vtag green">Selected by CC</span>`
    : sel.dropped.includes(n) ? ` <span class="vtag">Not selected</span>` : "";
  const sorts = { executed: g => -g.executed, findings: g => -g.findings, pass: g => -(g.pass_rate ?? -1), cc: g => -(g.cc ?? -1) };
  const key = S.gsort || "executed";
  const rows = [...gens].sort((a, b) => sorts[key](a) - sorts[key](b));
  const fv = g => ["crash", "timeout", "divergence"].map(k => g.verdicts[k] ? `<span class="count ${VERDICTS[k].tone}" title="${VERDICTS[k].label}">${g.verdicts[k]}</span>` : "").join("") || `<span class="muted">0</span>`;
  const ccMax = Math.max(1, ...gens.map(g => g.cc || 0));
  const table = `<div class="tscroll"><table class="rtable"><thead><tr><th>Generator</th><th>Generated</th><th>Valid</th><th>Executed</th><th>Failing inputs</th><th>Pass rate</th><th>Cluster coverage ${hint("hint-cc-col", "How much of the pooled input space this generator's inputs reach. It is relative to the pool in this run: add or remove a generator and every score changes.")}</th></tr></thead><tbody>
    ${rows.map(g => `<tr><td><i class="dotc" style="background:${genColor(g.name, names)}"></i>${esc(g.name)}${selTag(g.name)}</td><td>${num(g.generated)}</td><td>${num(g.valid)}</td><td>${num(g.executed)}</td><td>${fv(g)}</td>
      <td class="passcell"><span>${g.pass_rate == null ? "—" : (100 * g.pass_rate).toFixed(1) + "%"}</span><span class="o-b"><span style="width:${100 * (g.pass_rate || 0)}%;background:#16A34A"></span></span></td>
      <td class="passcell"><span>${g.cc == null ? "—" : g.cc.toFixed(3)}</span><span class="o-b"><span style="width:${g.cc == null ? 0 : 100 * g.cc / ccMax}%;background:#1687F8"></span></span></td></tr>`).join("")}</tbody></table></div>`;
  const sortSel = `<label class="sortby">Sort by <select onchange="S.gsort = this.value; paintRun()">${[["executed", "Executed inputs"], ["findings", "Findings"], ["pass", "Pass rate"], ["cc", "Cluster coverage"]]
    .map(([v, t]) => `<option value="${v}" ${key === v ? "selected" : ""}>${t}</option>`).join("")}</select></label>`;

  const executedChart = groupedBars(gens, ["generated", "valid", "executed"], ["#cbd5e1", "#1687F8", "#16A34A"]) + legend([{ label: "Generated", color: "#cbd5e1" }, { label: "Valid", color: "#1687F8" }, { label: "Executed", color: "#16A34A" }]);
  const failChart = groupedBars(gens.map(g => ({ name: g.name, crash: g.verdicts.crash, timeout: g.verdicts.timeout, divergence: g.verdicts.divergence })), ["crash", "timeout", "divergence"], ["#EF4444", "#F59E0B", "#9333EA"])
    + legend([{ label: "Crash", color: "#EF4444" }, { label: "Timeout", color: "#F59E0B" }, { label: "Divergence", color: "#9333EA" }]);
  const ccRows = gens.filter(g => g.cc != null).sort((a, b) => b.cc - a.cc).map(g => ({ label: g.name, value: g.cc, color: genColor(g.name, names) }));
  const outcomeBars = `<div class="stack100">${gens.map(g => { const t = g.executed || 1; return `<div class="s100"><span class="hb-l">${esc(g.name)}</span><span class="s100-t">${VORDER.map(k =>
    g.verdicts[k] ? `<span style="width:${100 * g.verdicts[k] / t}%;background:${VERDICTS[k].color}" title="${VERDICTS[k].label}: ${g.verdicts[k]}">${100 * g.verdicts[k] / t >= 9 ? (100 * g.verdicts[k] / t).toFixed(1) + "%" : ""}</span>` : "").join("")}</span></div>`; }).join("")}</div>`
    + legend(VORDER.map(k => ({ label: VERDICTS[k].label, color: VERDICTS[k].color })));

  const pick = (fn, cmp) => gens.filter(fn).reduce((a, g) => (a === null || cmp(g, a) ? g : a), null);
  const topF = pick(g => g.findings > 0, (g, a) => g.findings > a.findings), topP = pick(g => g.pass_rate != null, (g, a) => g.pass_rate > a.pass_rate), topC = pick(g => g.cc != null, (g, a) => g.cc > a.cc);
  const hl = (g, icon, tag, big, sub) => g ? `<div class="hl"><div class="hl-h"><i class="dotc" style="background:${genColor(g.name, names)}"></i><strong>${esc(g.name)}</strong></div>
      <span class="vtag ${tag}">${icon} ${big}</span><div class="muted">${sub}</div></div>` : "";
  const highlights = [hl(topF, ICONS.bug, "red", "Most findings", `${topF?.findings} finding${topF?.findings > 1 ? "s" : ""}`),
    hl(topP, ICONS.success, "green", "Highest pass rate", topP ? (100 * topP.pass_rate).toFixed(1) + "%" : ""),
    hl(topC, ICONS.grid, "blue", "Broadest coverage", topC ? `Cluster coverage ${topC.cc.toFixed(3)}` : "")].filter(Boolean);

  const totalValid = gens.reduce((s, g) => s + (g.valid || 0), 0), big = gens.reduce((a, g) => (!a || g.valid > a.valid ? g : a), null);
  const notes = [...(d.corpus?.signal_caveats || [])];
  if (gens.length > 1 && big && totalValid && big.valid / totalValid > 0.5) notes.push(`${big.name} contributed ${fmtPct(big.valid, totalValid, 0)} of the comparison pool, so pool-relative cluster coverage favours it partly for that reason. Interpret the scores with care.`);
  const basis = d.generation_mode === "time" ? "Equal time" : d.generation_mode === "count" ? "Equal count" : "";
  const rec = ccRows.length > 1 ? `<div class="rec"><span class="stile green" aria-hidden="true">${ICONS.stats}</span><div><strong>SpreadEx recommendation</strong>
      <p>Under this campaign's configuration${basis ? ` (${basis.toLowerCase()})` : ""}, <strong>${esc(ccRows[0].label)}</strong> reached the broadest region of the pooled input space (cluster coverage ${ccRows[0].value.toFixed(3)}). That makes it a reasonable generator to give more budget next time. It does not make it the best generator in general.</p></div></div>` : "";

  if (!gens.length) return `<div class="empty">This run recorded no generator breakdown.</div>`;
  return `<div class="resgrid one">
    ${resCard("Generator comparison", `${basis ? `<div class="muted rbasis">Comparison basis: ${basis}</div>` : ""}${sel ? `<div class="rnote" data-tour="gen-selection">${ICONS.info}<div>This campaign kept ${sel.selected.length === 1 ? "the generator" : `the <strong>${sel.selected.length}</strong> generators`} with the highest Cluster Coverage (${sel.selected.map(esc).join(", ")}). Inputs from ${sel.dropped.map(esc).join(", ")} were generated and measured, but not executed.</div></div>` : ""}${table}${notes.map(n => `<div class="rnote warnnote">${ICONS.alert}<div>${esc(n)}</div></div>`).join("")}`, { right: sortSel, tour: "gen-compare", tip: "Everything here is computed from this run's recorded inputs and verdicts." })}
    ${rec}
    <div class="resgrid three">
      ${resCard("Executed inputs per generator", executedChart)}
      ${resCard("Failing inputs by generator", failChart)}
      ${resCard("Cluster coverage", ccRows.length ? hbars(ccRows, 1, v => v.toFixed(3)) : `<div class="empty">Not computed for this run.</div>`, { tip: "Pool-relative: it compares generators against each other within this run." })}
    </div>
    <div class="resgrid two">
      ${resCard("Execution outcome per generator", outcomeBars)}
      ${resCard("Generator highlights", highlights.length ? `<div class="hls">${highlights.join("")}</div>` : `<div class="empty">Nothing stands out.</div>`)}
    </div></div>`;
}

// ------- Budget: was the budget well spent

function budgetCurveChart(d) {
  const a = d.budget_curve || [], r = d.random_curve || [], total = d.executed;
  if (!a.length || !a.some(p => p[1] > 0)) return `<div class="empty">No failures were found, so there is no discovery curve to draw.</div>`;
  const W = 620, H = 200, P = { l: 34, r: 12, t: 10, b: 28 };
  const maxY = Math.max(1, ...a.map(p => p[1]), ...r.map(p => p[1]));
  const x = i => P.l + (i / Math.max(1, total)) * (W - P.l - P.r), y = v => H - P.b - (v / maxY) * (H - P.t - P.b);
  const step = pts => pts.map((p, i) => `${i ? "L" : "M"}${x(p[0])},${y(p[1])}`).join(" ");
  const ticks = Array.from({ length: Math.min(maxY, 5) + 1 }, (_, i) => Math.round(i * maxY / Math.min(maxY, 5)));
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Findings discovered as inputs were executed">
    ${ticks.map(t => `<g><line x1="${P.l}" x2="${W - P.r}" y1="${y(t)}" y2="${y(t)}" class="grid"/><text x="${P.l - 5}" y="${y(t) + 3}" text-anchor="end" class="axis">${t}</text></g>`).join("")}
    ${r.length ? `<path d="${step(r)}" fill="none" stroke="#94a3b8" stroke-width="2" stroke-dasharray="5 4"/>` : ""}
    <path d="${step([[0, 0], ...a])}" fill="none" stroke="#16A34A" stroke-width="2.5"/>
    <text x="${P.l}" y="${H - 8}" class="axis">0</text><text x="${(W + P.l) / 2}" y="${H - 8}" text-anchor="middle" class="axis">inputs executed</text><text x="${W - P.r}" y="${H - 8}" text-anchor="end" class="axis">${num(total)}</text></svg>
    ${legend([{ label: "SpreadEx order", color: "#16A34A" }, ...(r.length ? [{ label: "Random order of the same inputs (average)", color: "#94a3b8" }] : [])])}`;
}

function tabBudget(d) {
  const b = d.budgets || {}, gens = d.by_generator || [], names = gens.map(g => g.name), p = d.prioritization || {};
  const row = (k, v) => `<div class="drow"><span class="muted">${k}</span><strong>${v}</strong></div>`;
  const timeMode = d.generation_mode === "time";
  const genReq = gens.reduce((s, g) => s + (g.gen_requested_s || 0), 0), genAct = gens.reduce((s, g) => s + (g.gen_elapsed_s || 0), 0);
  const cfgGen = `<div class="dgrid one">${row("Allocation", timeMode ? "Equal time" : "Equal count")}${timeMode ? row("Time per generator", fmtDur(gens[0]?.gen_requested_s)) : ""}
    ${row("Generators", gens.length)}${row(timeMode ? "Total generation time" : "Generation ceiling", genReq ? "up to " + fmtDur(genReq) : fmtDur(b.generation_s))}</div>`;
  const mode = b.max_inputs ? "Number of tests" : (b.execution_s >= 86400 ? "Entire corpus" : "Time limit");
  const cfgExec = `<div class="dgrid one">${row("Mode", mode)}${row("Time limit", b.execution_s >= 86400 ? "—" : fmtDur(b.execution_s))}${row("Max executions", b.max_inputs ? num(b.max_inputs) : "—")}
    ${row("Prioritization", d.signal === "random" ? "Random" : "SpreadEx")}</div>`;
  const cfg = `<div class="resgrid two tight">
      <div class="subcard"><div class="subcard-h"><span class="stile purple" aria-hidden="true">${ICONS.doc}</span><strong>Generation budget</strong></div>${cfgGen}</div>
      <div class="subcard"><div class="subcard-h"><span class="stile blue" aria-hidden="true">${ICONS.playOutline}</span><strong>Execution budget</strong></div>${cfgExec}</div></div>
      <button type="button" class="linkish" onclick="go('setup'); gotoStep('run')">Edit for the next run</button>`;

  const genPct = genReq ? Math.min(100, Math.round(100 * genAct / genReq)) : null;
  const prioritized = d.corpus?.prioritized, execPct = prioritized ? Math.min(100, Math.round(100 * d.executed / prioritized)) : null;
  const usage = `<div class="resgrid two tight">
      <div class="subcard"><div class="subcard-h"><span class="stile purple" aria-hidden="true">${ICONS.doc}</span><strong>Generation</strong></div>
        <div class="big2"><div><strong>${genAct ? fmtDur(genAct) : "—"}</strong><span>Total time</span></div><div><strong>${num(d.corpus?.generated)}</strong><span>Inputs produced</span></div></div>
        ${genPct == null ? "" : `<div class="usebar"><span class="o-b"><span style="width:${genPct}%;background:#9333EA"></span></span><b>${genPct}%</b></div><div class="muted">of the time it was given</div>`}</div>
      <div class="subcard"><div class="subcard-h"><span class="stile blue" aria-hidden="true">${ICONS.playOutline}</span><strong>Execution</strong></div>
        <div class="big2"><div><strong>${fmtDur(d.exec_cpu_s)}</strong><span>Time inside the SUT</span></div><div><strong>${num(d.executed)}</strong><span>Executed inputs</span></div></div>
        ${execPct == null ? "" : `<div class="usebar"><span class="o-b"><span style="width:${execPct}%;background:#1687F8"></span></span><b>${execPct}%</b></div><div class="muted">of the prioritized corpus (${num(prioritized)}) was reached</div>`}</div></div>`;

  const genTime = gens.some(g => g.gen_requested_s != null)
    ? groupedBars(gens.map(g => ({ name: g.name, actual: Math.round((g.gen_elapsed_s || 0) * 10) / 10, configured: g.gen_requested_s || 0 })), ["actual", "configured"], ["#9333EA", "#cbd5e1"])
      + legend([{ label: "Actual time (s)", color: "#9333EA" }, { label: "Configured time (s)", color: "#cbd5e1" }])
    : `<div class="empty">This run did not record per-generator generation time.</div>`;

  const table = `<div class="tscroll"><table class="rtable"><thead><tr><th>Generator</th><th>Generated</th><th>Valid</th><th>Executed</th><th>Generation time</th><th>Avg time / input</th></tr></thead><tbody>
    ${gens.map(g => `<tr><td><i class="dotc" style="background:${genColor(g.name, names)}"></i>${esc(g.name)}</td><td>${num(g.generated)}</td><td>${num(g.valid)}</td><td>${num(g.executed)}</td>
      <td>${g.gen_elapsed_s == null ? "—" : g.gen_elapsed_s.toFixed(1) + " s"}</td><td>${g.avg_ms == null ? "—" : fmtMs(g.avg_ms)}</td></tr>`).join("")}
    <tr class="total"><td>Total</td><td>${num(d.corpus?.generated)}</td><td>${num(d.corpus?.valid)}</td><td>${num(d.executed)}</td><td>${genAct ? genAct.toFixed(1) + " s" : "—"}</td><td>${d.executed ? fmtMs(1000 * d.exec_cpu_s / d.executed) : "—"}</td></tr></tbody></table>`;

  // Statements the numbers support, and nothing more.
  const take = [];
  if (genReq && genAct) take.push([genAct <= genReq * 1.02 ? "ok" : "warn", genAct <= genReq * 1.02 ? "Generation finished within its budget" : "Generation ran over its budget", `${fmtDur(genAct)} total (limit ${fmtDur(genReq)})`]);
  if (prioritized) take.push([d.executed >= prioritized ? "ok" : "info", d.executed >= prioritized ? "Every prioritized input was executed" : "The budget ended before the corpus did", `${num(d.executed)} of ${num(prioritized)} prioritized inputs ran`]);
  if (p.findings) take.push(["ok", `${p.by_quarter} of ${p.findings} finding${p.findings > 1 ? "s" : ""} appeared in the first 25% of executions`, `The last appeared at input ${num(p.all_at)} (${p.all_pct}% of the run)`]);
  const prod = gens.filter(g => g.generated).sort((a, c) => c.generated - a.generated);
  if (timeMode && prod.length > 1 && prod[0].generated >= 2 * prod[prod.length - 1].generated) take.push(["info", "Generator throughput varies", `${prod[prod.length - 1].name} produced ${num(prod[prod.length - 1].generated)} inputs in the time ${prod[0].name} produced ${num(prod[0].generated)}. That is the measurement of equal-time comparison, not a flaw.`]);
  const takeaways = take.length ? `<div class="takes">${take.map(([k, t, s]) => `<div class="take ${k}"><span aria-hidden="true">${ICONS[k === "ok" ? "success" : k === "warn" ? "alert" : "info"]}</span><div><strong>${esc(t)}</strong><span>${esc(s)}</span></div></div>`).join("")}</div>` : `<div class="empty">Nothing notable.</div>`;

  return `<div class="resgrid one">
    <div class="resgrid two">${resCard("Budget configuration", cfg, { tip: "What this run was given. It is the configuration recorded in the run, not the project's current setup." })}
      ${resCard("Actual resource usage", usage, { tip: "What the run actually spent. Time inside the SUT is the sum of each execution's duration; executions can overlap." })}</div>
    <div class="resgrid two">${resCard("Findings discovered", budgetCurveChart(d), { tour: "budget-curve", tip: "Distinct failure signatures found as inputs were executed, against the average of random orderings of the same inputs." })}
      ${resCard("Execution timeline", stackedColumns(d.timeline || [], VORDER, VORDER.map(k => VERDICTS[k].color), "inputs, in execution order") + legend(VORDER.map(k => ({ label: VERDICTS[k].label, color: VERDICTS[k].color }))))}</div>
    <div class="resgrid two">${resCard("Generation time per generator", genTime)}${resCard("Key takeaways", takeaways)}</div>
    ${resCard("Resource usage by generator", table)}
  </div>`;
}

// ------- Findings: what broke, and why SpreadEx says so

function rfState() { if (!S.rf) S.rf = { filter: "all", q: "", sort: "first", sel: null, detail: null, replay: null, busy: false, loading: false, err: "" }; return S.rf; }

function visibleFindings(d) {
  const st = rfState(), q = st.q.trim().toLowerCase();
  let fs = (d.findings || []).filter(f => st.filter === "all" || f.verdict === st.filter)
    .filter(f => !q || [f.id, f.signature, f.stderr_first, f.detail, f.generator, f.verdict].join(" ").toLowerCase().includes(q));
  if (st.sort === "count") fs = [...fs].sort((a, b) => b.count - a.count);
  else if (st.sort === "type") fs = [...fs].sort((a, b) => a.verdict.localeCompare(b.verdict) || a.position - b.position);
  return fs;
}

function openFinding(signature) { rfState().sel = signature; S.rtab = "findings"; rfState().replay = null; paintRun(); ensureFinding(true); tourEvent("finding.opened"); }
function setFindingFilter(f) { rfState().filter = f; rfState().sel = null; paintRun(); ensureFinding(); }
function findingSearch(v) { const st = rfState(); st.q = v; st.sel = null; clearTimeout(S.fq); S.fq = setTimeout(() => { paintRun(); ensureFinding(); el("f-search")?.focus(); const i = el("f-search"); if (i) i.setSelectionRange(i.value.length, i.value.length); }, 250); }
function findingSort(v) { rfState().sort = v; rfState().sel = null; paintRun(); ensureFinding(); }
function stepFinding(delta) {
  const d = S.detail, list = visibleFindings(d), st = rfState();
  const i = list.findIndex(f => f.signature === st.sel);
  const next = list[(i + delta + list.length) % list.length];
  if (next) openFinding(next.signature);
}

async function ensureFinding(force) {
  const d = S.detail, st = rfState(), list = visibleFindings(d);
  if (!list.length) { st.detail = null; return paintRun(); }
  if (!st.sel || !list.some(f => f.signature === st.sel)) st.sel = list[0].signature;
  if (!force && st.detail && st.detail.signature === st.sel) return;
  const want = st.sel; st.loading = true; st.detail = null; st.err = ""; paintRun();
  try { const f = await api(`/api/runs/${encodeURIComponent(S.current)}/finding?signature=${encodeURIComponent(want)}`); if (st.sel === want) st.detail = f; }
  catch (e) { st.err = String(e.message || e); }
  st.loading = false; paintRun();
}

function codeBlock(text) {
  const lines = String(text).split("\n"); if (lines.length && lines[lines.length - 1] === "") lines.pop();
  return `<pre class="codeb"><code>${lines.map((l, i) => `<span class="ln">${i + 1}</span>${esc(l) || " "}`).join("\n")}</code></pre>`;
}
function copyText(text, btn) {
  if (navigator.clipboard?.writeText) navigator.clipboard.writeText(text).then(() => { if (btn) { btn.classList.add("copied"); setTimeout(() => btn.classList.remove("copied"), 1200); } }).catch(() => {});
}
function saveText(name, text) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
}

async function replayFinding() {
  const st = rfState(), f = st.detail; if (!f || st.busy) return;
  st.busy = true; st.replay = null; paintRun();
  try { st.replay = await api(`/api/runs/${encodeURIComponent(S.current)}/replay`, { hash: f.hash }); }
  catch (e) { st.replay = { ok: false, error: String(e.message || e) }; }
  st.busy = false; paintRun();
  tourEvent("replay.done", st.replay);
}

function replayPanel(f) {
  const st = rfState(), r = st.replay;
  if (st.busy) return `<div class="rnote">${ICONS.info}<div>Running this input again…</div></div>`;
  if (!r) return "";
  if (!r.ok) return `<div class="res bad" role="alert"><span class="res-ico" aria-hidden="true">${ICONS.error}</span><div class="res-main"><div class="res-s">${esc(r.error)}</div></div></div>`;
  const o = r.original, n = r.replay;
  return `<div class="res ${r.reproduced ? "good" : "warn"}" role="status"><span class="res-ico" aria-hidden="true">${r.reproduced ? ICONS.success : ICONS.alert}</span>
    <div class="res-main"><div class="res-t">${r.reproduced ? "Reproduced" : "Not reproduced"}</div>
      <div class="res-s">${r.reproduced ? "The same result came back." : "The result was different this time. It may be flaky or nondeterministic, or the system may have been fixed."}</div>
      <dl class="res-facts"><div><dt>Original</dt><dd>${esc((VERDICTS[o.verdict] || {}).label || o.verdict)} · ${esc(fmtMs(o.duration_ms))}</dd></div>
        <div><dt>Replay</dt><dd>${esc((VERDICTS[n.verdict] || {}).label || n.verdict)} · ${esc(fmtMs(n.duration_ms))}</dd></div></dl>
      <div class="muted">Run against the project's current command and settings.</div></div></div>`;
}

function findingDetailView(f) {
  const d = S.detail, list = visibleFindings(d), st = rfState();
  const i = list.findIndex(x => x.signature === f.signature);
  const meta = (k, v) => `<div><span class="muted">${k}</span><strong>${v}</strong></div>`;
  const ev = f.evidence.map(e => `<div class="ev ${e.status}"><span aria-hidden="true">${ICONS[e.status === "matched" ? "success" : "minus"] || ICONS.success}</span><span class="ev-r">${esc(e.rule)}</span><span class="ev-n">${esc(e.note)}</span></div>`).join("");
  const tone = (VERDICTS[f.verdict] || {}).tone || "red";
  return `<div class="fdetail">
    <div class="fd-h"><span class="stile ${tone}" aria-hidden="true">${ICONS[f.verdict === "timeout" ? "clock" : f.verdict === "divergence" ? "scale" : "bug"]}</span>
      <div class="fd-t"><h3>Finding ${esc(f.id)} <button type="button" class="gx" aria-label="Copy finding id" onclick="copyText('${esc(f.id)}', this)">${ICONS.copy}</button> ${vtag(f.verdict)}</h3>
        <div class="fd-head">${esc(f.headline)}</div></div>
      <div class="fd-nav"><button type="button" class="ghost small" onclick="stepFinding(-1)" aria-label="Previous finding">${ICONS.back}</button><span>${i + 1} / ${list.length}</span>
        <button type="button" class="ghost small" onclick="stepFinding(1)" aria-label="Next finding">${ICONS.arrow}</button></div></div>
    <div class="fd-meta">${meta("First seen", `input #${f.first_rank + 1}`)}${meta("Generator", esc(f.generator))}${meta("Runtime", esc(fmtMs(f.duration_ms)))}${meta("Inputs with this signature", num(f.count))}</div>
    <div class="fd-grid">
      <div class="subcard" data-tour="fd-input"><div class="subcard-h"><strong>Input</strong><span class="grow"></span>
        <button type="button" class="ghost small" onclick="copyText(S.rf.detail.input, this)">${ICONS.copy} Copy</button>
        <button type="button" class="ghost small" onclick="saveText('${esc(f.id)}-input.txt', S.rf.detail.input)">${ICONS.download} Save</button></div>${codeBlock(f.input)}</div>
      <div class="subcard" data-tour="fd-class"><div class="subcard-h"><strong>Classification</strong> ${hint("hint-class", "The checks in the order SpreadEx applies them. The first one that matches decides the result.")}</div>
        <div class="evs">${ev}</div><div class="evresult ${tone}"><span class="muted">Result</span><strong>${esc((VERDICTS[f.verdict] || { label: f.verdict }).label)}</strong></div></div></div>
    <div class="fd-grid b">
      <div class="subcard" data-tour="fd-output"><div class="subcard-h"><strong>Execution output</strong><span class="grow"></span>${f.stderr ? `<button type="button" class="ghost small" onclick="copyText(S.rf.detail.stderr, this)">${ICONS.copy} Copy</button>` : ""}</div>
        <div class="tabs2"><span class="muted">stderr</span><span class="muted fine">stdout is not kept for failures</span></div>
        ${f.stderr ? `<pre class="errb">${esc(f.stderr)}</pre>` : `<div class="empty">This execution printed nothing to stderr.</div>`}</div>
      <div class="subcard"><div class="subcard-h"><strong>Details</strong></div>
        <div class="dgrid one">${[["Finding ID", `${esc(f.id)}`], ["Type", vtag(f.verdict)], ["Generator", esc(f.generators.join(", "))], ["Exit code", f.signal != null ? `signal ${f.signal}` : f.timed_out ? "no answer" : esc(String(f.exit_code))],
          ["Runtime", esc(fmtMs(f.duration_ms))], ["Input hash", `<span class="mono">${esc(f.hash.slice(0, 12))}</span>`], ["Signature", `<span class="mono">${esc(f.signature.slice(0, 12))}</span>`]]
          .map(([k, v]) => `<div class="drow"><span class="muted">${k}</span><span>${v}</span></div>`).join("")}</div></div></div>
    ${f.similar_total ? `<div class="subcard"><div class="subcard-h"><strong>Similar inputs (${f.similar_total})</strong> ${hint("hint-sim", "Other inputs in this run with the same failure signature. A signature is not a bug: distinct bugs can share one, and one bug can span several.")}</div>
      <div class="sims">${f.similar.map(s => `<div class="sim"><span class="mono">#${s.rank + 1}</span><span>${esc(s.generator)}</span><span class="mono grow">${esc(s.preview)}</span></div>`).join("")}${f.similar_total > f.similar.length ? `<div class="muted">and ${f.similar_total - f.similar.length} more</div>` : ""}</div></div>` : ""}
    <div class="subcard replay"><div class="subcard-h"><strong>Replay</strong></div>
      <p class="muted">Run this input again against your current command and see whether the same thing happens. Nothing is saved.</p>
      <button type="button" class="primary" data-tour="fd-replay" onclick="replayFinding()" ${st.busy ? "disabled" : ""}>${ICONS.playOutline} Replay this input</button>${replayPanel(f)}</div>
  </div>`;
}

function tabFindings(d) {
  const st = rfState(), all = d.findings || [], list = visibleFindings(d);
  const count = k => all.filter(f => f.verdict === k).length;
  const chip = (id, label, n, tone) => `<button type="button" class="fchip ${tone} ${st.filter === id ? "on" : ""}" aria-pressed="${st.filter === id}" onclick="setFindingFilter('${id}')">${label} <b>${n}</b></button>`;
  if (!all.length) return `<div class="resgrid one">${resCard("Findings", `<div class="empty">No failures in ${num(d.executed)} executed inputs.<br><span class="muted">For a mature system under test this is the expected outcome, not a missing measurement. Expected rejections are not failures; the Overview counts them separately.</span></div>`)}</div>`;
  const cards = list.map(f => `<button type="button" data-tour="finding-card" class="fcard ${f.signature === st.sel ? "on" : ""}" onclick="openFinding('${esc(f.signature)}')" aria-current="${f.signature === st.sel}">
      <span class="stile ${(VERDICTS[f.verdict] || {}).tone || "red"} sm" aria-hidden="true">${ICONS[f.verdict === "timeout" ? "clock" : f.verdict === "divergence" ? "scale" : "bug"]}</span>
      <span class="fc-m"><strong>${esc(f.stderr_first)}</strong>
        <span class="muted">${esc(f.detail || "")}</span><span class="fc-tags">${vtag(f.verdict)}<span class="vtag blue">${esc(f.generator)}</span></span></span>
      <span class="fc-r"><span class="muted">${esc(f.id)}</span><span class="muted">input #${f.position + 1}</span><span class="muted">${esc(fmtMs(f.duration_ms))}</span></span></button>`).join("");
  return `<div class="fwork">
    <section class="rescard flist"><div class="rescard-h"><h4>Findings <span class="muted">(${all.length})</span> ${hint("hint-findings", "Failures grouped by signature. Two findings are not necessarily two bugs, and a divergence is not automatically a bug.")}</h4></div>
      <div class="fchips">${chip("all", "All", all.length, "blue")}${chip("crash", "Crash", count("crash"), "red")}${chip("timeout", "Timeout", count("timeout"), "amber")}${chip("divergence", "Divergence", count("divergence"), "purple")}</div>
      <div class="fsearch"><input id="f-search" type="search" placeholder="Search findings…" value="${esc(st.q)}" oninput="findingSearch(this.value)" aria-label="Search findings">
        <label class="sortby">Sort <select onchange="findingSort(this.value)" aria-label="Sort findings"><option value="first" ${st.sort === "first" ? "selected" : ""}>First seen</option><option value="count" ${st.sort === "count" ? "selected" : ""}>Most inputs</option><option value="type" ${st.sort === "type" ? "selected" : ""}>Type</option></select></label></div>
      <div class="fcards">${cards || `<div class="empty">No finding matches.</div>`}</div></section>
    <section class="rescard fdet">${st.loading ? `<div class="empty">Loading…</div>` : st.err ? `<div class="note bad">${esc(st.err)}</div>` : st.detail ? findingDetailView(st.detail) : `<div class="empty">Select a finding.</div>`}</section></div>`;
}

// ------- Corpus: what exactly ran

function rcState() { if (!S.rc) S.rc = { q: "", generator: "", verdict: "", offset: 0, limit: 10, data: null, loading: false, sel: null, text: null, dist: "generator", err: "" }; return S.rc; }

async function loadCorpus() {
  const st = rcState(); st.loading = true; st.err = ""; paintRun();
  const qs = new URLSearchParams({ offset: st.offset, limit: st.limit });
  if (st.q) qs.set("q", st.q); if (st.generator) qs.set("generator", st.generator); if (st.verdict) qs.set("verdict", st.verdict);
  try { st.data = await api(`/api/runs/${encodeURIComponent(S.current)}/inputs?${qs}`); if (!st.sel || !st.data.items.some(i => i.hash === st.sel)) st.sel = st.data.items[0]?.hash || null; }
  catch (e) { st.err = String(e.message || e); }
  st.loading = false; paintRun(); loadInputText();
}
async function loadInputText() {
  const st = rcState(); if (!st.sel) { st.text = null; return; }
  const want = st.sel;
  try { const t = await api(`/api/input?hash=${encodeURIComponent(want)}`); if (st.sel === want) { st.text = t; paintRun(); } } catch (e) { /* the panel just stays empty */ }
}
function corpusFilter(key, value) { const st = rcState(); st[key] = value; st.offset = 0; st.sel = null; loadCorpus(); }
function corpusSearch(v) { const st = rcState(); st.q = v; st.offset = 0; st.sel = null; clearTimeout(S.cq); S.cq = setTimeout(async () => { await loadCorpus(); const i = el("c-search"); if (i) { i.focus(); i.setSelectionRange(i.value.length, i.value.length); } }, 300); }
function corpusReset() { Object.assign(rcState(), { q: "", generator: "", verdict: "", offset: 0, sel: null }); loadCorpus(); }
function corpusPage(offset) { const st = rcState(); st.offset = Math.max(0, offset); st.sel = null; loadCorpus(); }
function corpusSelect(h) { rcState().sel = h; rcState().text = null; paintRun(); loadInputText(); }
function corpusStep(delta) { const st = rcState(), it = st.data?.items || []; const i = it.findIndex(x => x.hash === st.sel); const n = it[i + delta]; if (n) corpusSelect(n.hash); }


function tabCorpus(d) {
  const st = rcState(), c = d.corpus || {}, v = d.verdicts || {}, gens = d.by_generator || [], names = gens.map(g => g.name);
  const tile = (tone, icon, n, label, sub) => `<div class="ctile ${tone}"><span class="stile ${tone}" aria-hidden="true">${ICONS[icon]}</span><strong>${num(n)}</strong><span>${label}</span>${sub ? `<span class="muted">${sub}</span>` : ""}</div>`;
  const overview = `<div class="ctiles">${tile("blue", "doc", c.generated ?? 0, "Generated")}${tile("green", "success", c.valid ?? 0, "Valid", fmtPct(c.valid, c.generated))}
    ${tile("blue", "playOutline", d.executed, "Executed", fmtPct(d.executed, c.valid))}${tile("red", "bug", (d.findings || []).length, "Findings")}</div>`;
  const dist = st.dist === "outcome"
    ? hbars(VORDER.map(k => ({ label: VERDICTS[k].label, value: v[k] || 0, color: VERDICTS[k].color })), Math.max(1, ...VORDER.map(k => v[k] || 0)), x => num(x))
    : `<div class="stack100">${gens.map(g => { const t = g.executed || 1; return `<div class="s100"><span class="hb-l">${esc(g.name)}</span><span class="s100-t">${VORDER.map(k => g.verdicts[k] ? `<span style="width:${100 * g.verdicts[k] / t}%;background:${VERDICTS[k].color}" title="${VERDICTS[k].label}: ${g.verdicts[k]}"></span>` : "").join("")}</span><b>${num(g.executed)}</b></div>`; }).join("")}</div>`
      + legend(VORDER.map(k => ({ label: VERDICTS[k].label, color: VERDICTS[k].color })));
  const distTabs = `<div class="seg" role="tablist">${[["generator", "By generator"], ["outcome", "By outcome"]].map(([id, t]) => `<button type="button" role="tab" class="${st.dist === id ? "on" : ""}" aria-selected="${st.dist === id}" onclick="rcState().dist = '${id}'; paintRun()">${t}</button>`).join("")}</div>`;

  const data = st.data, f = data?.facets || { generators: {}, verdicts: {} };
  const page = data ? Math.floor(data.offset / data.limit) + 1 : 1, last = data ? Math.max(1, Math.ceil(data.total / data.limit)) : 1;
  const sel = (key, label, opts) => `<label class="csel"><span class="visually-hidden">${label}</span><select onchange="corpusFilter('${key}', this.value)" aria-label="${label}"><option value="">${label}</option>${opts.map(([val, t]) => `<option value="${esc(val)}" ${st[key] === val ? "selected" : ""}>${esc(t)}</option>`).join("")}</select></label>`;
  const rows = (data?.items || []).map(i => `<tr class="click ${i.hash === st.sel ? "sel" : ""}" onclick="corpusSelect('${esc(i.hash)}')" tabindex="0" onkeydown="if (event.key === 'Enter') corpusSelect('${esc(i.hash)}')">
      <td class="mono">${i.rank + 1}</td><td class="mono prev">${esc(i.preview)}</td><td><i class="dotc" style="background:${genColor(i.generator, names)}"></i>${esc(i.generator)}</td>
      <td>${vtag(i.verdict)}${i.finding ? ` <span class="muted">${esc(i.finding)}</span>` : ""}</td><td>${num(i.size)}</td><td>${esc(fmtMs(i.duration_ms))}</td></tr>`).join("");
  const filtersOn = st.q || st.generator || st.verdict;
  const table = `<div class="cfilters"><div class="fsearch"><input id="c-search" type="search" placeholder="Search inputs…" value="${esc(st.q)}" oninput="corpusSearch(this.value)" aria-label="Search inputs"></div>
      ${sel("generator", "Generator", Object.entries(f.generators).map(([k, n]) => [k, `${k} (${n})`]))}${sel("verdict", "Outcome", VORDER.filter(k => f.verdicts[k]).map(k => [k, `${VERDICTS[k].label} (${f.verdicts[k]})`]))}
      <button type="button" class="ghost small" onclick="corpusReset()" ${filtersOn ? "" : "disabled"}>Reset</button></div>
    ${st.err ? `<div class="note bad">${esc(st.err)}</div>` : ""}
    <div class="tscroll"><table class="rtable"><thead><tr><th>#</th><th>Input (preview)</th><th>Generator</th><th>Outcome</th><th>Length</th><th>Exec. time</th></tr></thead>
      <tbody>${st.loading && !data ? `<tr><td colspan="6" class="empty">Loading…</td></tr>` : rows || `<tr><td colspan="6" class="empty">No input matches.</td></tr>`}</tbody></table></div>
    ${data ? `<div class="pager"><span class="muted">Showing ${data.total ? data.offset + 1 : 0}–${Math.min(data.offset + data.limit, data.total)} of ${num(data.total)}${data.total !== data.all ? ` (of ${num(data.all)} executed)` : " executed inputs"}</span>
      <span class="pgs"><button type="button" class="ghost small" onclick="corpusPage(${data.offset - data.limit})" ${page <= 1 ? "disabled" : ""} aria-label="Previous page">${ICONS.back}</button>
        ${pageNumbers(page, last).map(n => n === "…" ? `<span class="muted">…</span>` : `<button type="button" class="pgn ${n === page ? "on" : ""}" onclick="corpusPage(${(n - 1) * data.limit})" aria-current="${n === page}">${n}</button>`).join("")}
        <button type="button" class="ghost small" onclick="corpusPage(${data.offset + data.limit})" ${page >= last ? "disabled" : ""} aria-label="Next page">${ICONS.arrow}</button></span>
      <label class="sortby"><select onchange="rcState().limit = Number(this.value); corpusPage(0)" aria-label="Rows per page">${[10, 25, 50].map(n => `<option ${st.limit === n ? "selected" : ""}>${n}</option>`).join("")}</select> / page</label></div>` : ""}`;

  const it = (data?.items || []).find(x => x.hash === st.sel), idx = (data?.items || []).findIndex(x => x.hash === st.sel);
  const details = it ? `<div class="subcard" data-tour="corpus-input"><div class="subcard-h"><strong>Input details</strong><span class="grow"></span><span class="muted">${idx + 1} / ${data.items.length}</span>
      <button type="button" class="ghost small" onclick="corpusStep(-1)" aria-label="Previous input" ${idx <= 0 ? "disabled" : ""}>${ICONS.back}</button><button type="button" class="ghost small" onclick="corpusStep(1)" aria-label="Next input" ${idx >= data.items.length - 1 ? "disabled" : ""}>${ICONS.arrow}</button></div>
      <div class="subcard-h"><button type="button" class="ghost small" onclick="copyText(S.rc.text?.text || '', this)">${ICONS.copy} Copy</button><button type="button" class="ghost small" onclick="saveText('input-${esc(it.hash.slice(0, 8))}.txt', S.rc.text?.text || '')">${ICONS.download} Download</button></div>
      ${st.text ? codeBlock(st.text.text) + (st.text.truncated ? `<div class="muted">truncated</div>` : "") : `<div class="empty">Loading…</div>`}
      <div class="dgrid one">${[["Input", `<span class="mono">#${it.rank + 1}</span>`], ["Hash", `<span class="mono">${esc(it.hash.slice(0, 12))}</span>`], ["Generator", esc(it.generator)], ["Outcome", vtag(it.verdict)],
        ["Length", `${num(it.size)} bytes`], ["Exec. time", esc(fmtMs(it.duration_ms))]].map(([k, v2]) => `<div class="drow"><span class="muted">${k}</span><span>${v2}</span></div>`).join("")}</div>
      ${it.finding ? `<button type="button" class="linkish" onclick="openFinding('${esc((d.findings.find(x => x.id === it.finding) || {}).signature || "")}')">Open finding ${esc(it.finding)}</button>` : ""}</div>`
    : `<div class="subcard"><div class="empty">Select an input to see it.</div></div>`;

  return `<div class="resgrid one">
    <div class="resgrid two corp">${resCard("Corpus overview", overview + `<div class="rnote">${ICONS.info}<div>Generated inputs that were never reached are counted here but not listed: a run records the inputs it executed.</div></div>`, { tip: "Generated is everything the generators produced; valid is what survived de-duplication and validation; executed is what the budget reached." })}
      ${resCard("Corpus distribution", dist, { right: distTabs, tip: "Executed inputs, split by who produced them and what happened to them." })}</div>
    <div class="resgrid corpwork">${resCard("Test inputs", table, { tip: "Every executed input of this run, in the order SpreadEx ran them." })}${details}</div></div>`;
}


// ------- Campaigns: the list Results opens on, and the live view of the one that is running

function showCampaigns() { S.rview = "list"; S.runMenu = S.actMenu = false; saveView(); renderResults(); }
function openCampaign(id) {
  // The running one opens live; a finished one opens its results.
  if (S.live?.active && S.live.runId === id) { S.rview = "live"; return go("results"); }
  S.current = id; S.rview = "run"; S.rtab = "overview"; S.runMenu = false; saveView(); renderResults();
}

const RUN_STATUS = {
  finished:  ["ok",   "success", "Completed"],
  cancelled: ["warn", "stop",    "Cancelled"],
  aborted:   ["warn", "alert",   "Interrupted"],
  failed:    ["bad",  "error",   "Failed"],
};
function statusPill(status) {
  if (status === "running") return `<span class="rstatus live"><span class="pulse" aria-hidden="true"></span> Running</span>`;
  const [tone, icon, label] = RUN_STATUS[status] || RUN_STATUS.aborted;
  return `<span class="rstatus ${tone}">${ICONS[icon]} ${label}</span>`;
}
function fmtBytes(n) {
  if (!n) return "0 KB";
  return n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`;
}

// ---- campaign actions. Each one changes something on disk, so a read-only Workbench offers none.

function canAct() { return !S.project?.read_only; }

async function cancelCampaign(id, ev) {
  ev?.stopPropagation();
  try {
    const r = await api(`/api/runs/${encodeURIComponent(id)}/cancel`, {});
    if (r.ok === false) throw new Error(r.error);
    if (S.live) S.live.cancelling = true;
  } catch (e) { S.listError = String(e.message || e); }
  S.tab === "results" && S.rview === "live" ? paintLive() : renderResults();
}

async function rerunCampaign(id, ev) {
  ev?.stopPropagation();
  S.actMenu = false;
  try {
    const r = await api(`/api/runs/${encodeURIComponent(id)}/rerun`, {});
    if (r.ok === false) throw new Error(r.error);
  } catch (e) {
    S.listError = S.actionError = String(e.message || e);
    return S.rview === "run" ? paintRun() : renderResults();
  }
  startLive();
}

async function deleteCampaign(id, ev) {
  ev?.stopPropagation();
  S.actMenu = false;
  const r = (S.runs || []).find(x => x.run_id === id);
  const label = campaignName(id);
  if (!confirm(`Permanently delete ${label}?\n\nIts results, logs and the inputs no other campaign used (about ${fmtBytes(r?.size_bytes)}) are removed. Inputs shared with other campaigns are kept. This cannot be undone.`)) return;
  try {
    const out = await api(`/api/runs/${encodeURIComponent(id)}/delete`, {});
    if (out.ok === false) throw new Error(out.error);
    S.listError = "";
  } catch (e) { S.listError = String(e.message || e); }
  await loadRuns();
  S.rview = "list"; saveView(); renderResults();
}

function campaignsList() {
  const runs = S.runs || [];
  const live = runs.find(r => r.status === "running");
  const act = (r) => !canAct() ? "" : r.status === "running"
    ? `<button type="button" class="ghost small" onclick="cancelCampaign('${esc(r.run_id)}', event)">${ICONS.stop} Cancel</button>`
    : `<button type="button" class="ghost small" onclick="rerunCampaign('${esc(r.run_id)}', event)" ${live ? "disabled" : ""} title="Run again with the configuration this campaign used">${ICONS.rerun} Re-run</button>
       <button type="button" class="ghost small" onclick="exportCampaign('${esc(r.run_id)}', event)">${ICONS.download} Export</button>
       <button type="button" class="ghost small" onclick="deleteCampaign('${esc(r.run_id)}', event)" title="Delete (frees about ${esc(fmtBytes(r.size_bytes))})" aria-label="Delete ${esc(campaignName(r.run_id))}">${ICONS.trash}</button>`;
  const rows = runs.map(r => `<tr class="click" tabindex="0" onclick="openCampaign('${esc(r.run_id)}')" onkeydown="if (event.key === 'Enter' && event.target === this) openCampaign('${esc(r.run_id)}')">
      <td><strong class="mono">${esc(r.run_id)}</strong>${r.origin === "cli" ? ` <span class="muted">CLI</span>` : ""}</td><td>${statusPill(r.status)}</td>
      <td>${esc(fmtDate(r.started_at))} <span class="muted">${esc(fmtTime(r.started_at))}</span></td>
      <td>${esc(r.target || "—")}</td>
      <td>${(r.generators || []).map(g => `<span class="vtag blue">${esc(g)}</span>`).join(" ") || `<span class="muted">—</span>`}</td>
      <td>${num(r.executed)}</td>
      <td>${r.findings ? `<span class="count bad">${r.findings}</span>` : `<span class="muted">none</span>`}</td>
      <td>${esc(fmtDur(r.duration_s))}</td><td>${esc(fmtBytes(r.size_bytes))}</td>
      <td class="rowacts">${act(r)}</td></tr>`).join("");
  return `<div class="resws">
    <div class="listhead"><div><h2>Campaigns</h2><p class="muted">${runs.length} run${runs.length === 1 ? "" : "s"} in this project, from the Workbench and the command line. Open one to see what happened.</p></div>
      ${canAct() ? `<button type="button" class="primary" onclick="go('setup'); gotoStep('run')" ${live ? "disabled title=\"A campaign is already running\"" : ""}>${ICONS.playOutline} Run a campaign</button>` : ""}</div>
    ${S.listError ? `<div class="note bad" role="alert">${esc(S.listError)}</div>` : ""}
    ${live ? `<button type="button" class="livebanner" onclick="watchActive()"><span class="pulse" aria-hidden="true"></span><span><strong>${esc(campaignName(live.run_id))} is running</strong><span class="muted"> — watch it live</span></span>${ICONS.arrow}</button>` : ""}
    <section class="rescard"><div class="tscroll"><table class="rtable clist"><thead><tr><th>Campaign</th><th>Status</th><th>Started</th><th>SUT</th><th>Generators</th><th>Executed</th><th>Findings</th><th>Duration</th><th>Size</th><th><span class="visually-hidden">Actions</span></th></tr></thead>
      <tbody>${rows}</tbody></table></div></section></div>`;
}

async function exportCampaign(id, ev) {
  ev?.stopPropagation();
  try { await downloadExport(id); S.listError = ""; }
  catch (e) { S.listError = `Export failed: ${e.message || e}`; renderResults(); }
}

// ---- live: one background job at a time, so what is running is never ambiguous


// `external` is the project lock's record of a run this server did not start; `since` is when a
// run it did start began, for a page reloaded mid-run.
function startLive(external, since) {
  S.booted = true;
  clearInterval(S.livePoll);
  const at = external?.started_at || since;
  S.live = { active: true, runId: external?.run_id || null, external: !!external, lines: [], total: 0, error: "", done: false,
             progress: null, startedAt: at ? Date.parse(at) : Date.now() };
  S.rview = "live";
  go("results");
  S.livePoll = setInterval(pollLive, 900);
  pollLive();
}
// The banner on the list: back to the live view of whatever is running, whoever started it.
async function watchActive() {
  if (S.live?.active) { S.rview = "live"; return go("results"); }
  try { const act = await api("/api/active"); if (act.active) return startLive(act); } catch (e) { /* fall through */ }
  await loadRuns(); renderResults();
}

async function pollLive() {
  const L = S.live; if (!L || !L.active || L.busy) return;
  L.busy = true;
  try {
    // A run this server started has a job with a log; one started elsewhere (the CLI, another
    // Workbench) is followed through the project lock and the database alone.
    const a = L.external ? { idle: true } : await api(`/api/activity?since=${L.total}`);
    const job = !a.idle && a.kind === "run";
    if (job) { L.lines.push(...(a.lines || [])); L.total = a.total_lines ?? L.total + (a.lines || []).length; const st = liveStage(L.lines, false); if (st !== L.tourStage) { L.tourStage = st; tourEvent("stage." + st); } }
    const act = await api("/api/active");
    if (act.active && act.run_id) L.runId = act.run_id;
    if (L.runId) {
      const runs = (await api("/api/runs")).runs; S.runs = runs;
      const mine = runs.find(r => r.run_id === L.runId);
      if (mine) { L.progress = await api(`/api/runs/${encodeURIComponent(mine.run_id)}/progress`); }
      // A run started elsewhere has no log here: once inputs are executing, that is its stage.
      if (L.external && L.progress?.executed) tourEvent("stage.execute");
    }
    const finished = job ? a.done : !act.active;
    if (finished) {
      L.done = true; L.active = false; clearInterval(S.livePoll);
      if (job && a.ok === false) { L.error = a.error || "The campaign failed."; tourEvent("campaign.failed"); }
      else { await loadRuns(); L.busy = false; tourEvent("campaign.done"); await tourSettled(); return L.runId ? openCampaign(L.runId) : showCampaigns(); }
    }
  } catch (e) { /* a missed poll is fine; the next one catches up */ }
  L.busy = false;
  if (S.tab === "results" && S.rview === "live") paintLive();
}

function paintLive() { const h = el("view"); if (h && el("live-root")) el("live-root").innerHTML = liveBody(); else if (h) h.innerHTML = `<div class="resws" id="live-root">${liveBody()}</div>`; }

function liveBody() {
  const L = S.live || { lines: [], progress: null }, p = L.progress, v = (p && p.verdicts) || {};
  const stages = stagesFor(L.lines);
  const stage = liveStage(L.lines, L.done && !L.error), idx = stages.findIndex(s => s[0] === stage);
  const kpi = (tone, icon, n, label) => `<div class="kpi ${tone}"><span class="stile ${tone}" aria-hidden="true">${ICONS[icon]}</span><div><strong>${num(n)}</strong><span>${label}</span></div></div>`;
  const total = p && p.exec_budget_s && p.exec_budget_s < 3600 ? (p.gen_budget_s || 0) + p.exec_budget_s : null;
  const bar = p && p.elapsed_s != null && total ? Math.min(100, Math.round(100 * p.elapsed_s / total)) : null;
  const last = p?.latest;
  return `<header class="reshead live" data-tour="live-view"><button type="button" class="rback" onclick="showCampaigns()" aria-label="Back to campaigns">${ICONS.back}</button>
      <div class="rtitle"><div class="rtitle-1"><h2>${L.runId ? esc(campaignName(L.runId)) : "Starting campaign"}</h2>
        ${L.error ? `<span class="rstatus bad">${ICONS.error} Failed</span>` : L.cancelling ? `<span class="rstatus warn">${ICONS.stop} Cancelling&hellip;</span>` : `<span class="rstatus live"><span class="pulse" aria-hidden="true"></span> Running</span>`}</div>
        <div class="rtitle-3"><span>${ICONS.clock} ${esc(fmtDur((Date.now() - (L.startedAt || Date.now())) / 1000))} since it started${L.external ? " (from the command line or another Workbench)" : ""}</span></div></div>
      ${canAct() && L.runId && !L.done ? `<div class="ractions"><button type="button" class="ghost" onclick="cancelCampaign('${esc(L.runId)}')" ${L.cancelling ? "disabled" : ""}
          title="Stop after the input that is running now; what has run so far is kept">${ICONS.stop} Cancel campaign</button></div>` : ""}
      <div class="kpis">${kpi("blue", "playOutline", p?.executed || 0, "Executed")}${kpi("green", "success", v.ok || 0, "Passed")}${kpi("blue", "doc", v.expected_rejection || 0, "Rejected")}
        ${kpi("red", "bug", v.crash || 0, "Crashes")}${kpi("amber", "clock", v.timeout || 0, "Timeouts")}</div></header>
    ${L.external ? "" : `<div class="stagebar" data-tour="live-stages" role="list" aria-label="Campaign stages">${stages.map(([id, t], i) => `<div class="stg ${i < idx ? "done" : i === idx ? "now" : ""}" role="listitem" ${i === idx ? 'aria-current="step"' : ""}><span>${i < idx ? ICONS.check : i + 1}</span>${t}</div>`).join("")}</div>`}
    ${L.error ? `<div class="res bad" role="alert"><span class="res-ico" aria-hidden="true">${ICONS.error}</span><div class="res-main"><div class="res-t">The campaign stopped</div><div class="res-s">${esc(L.error)}</div></div>
        <button type="button" class="ghost small res-btn" onclick="go('setup'); gotoStep('run')">Back to Review &amp; run</button></div>`
      : `<section class="rescard"><div class="rescard-h"><h4>Progress</h4></div>
        ${bar != null ? `<div class="usebar"><span class="o-b"><span style="width:${bar}%;background:#1687F8"></span></span><b>${bar}%</b></div><div class="muted">${esc(fmtDur(p.elapsed_s))} elapsed of up to ${esc(fmtDur(total))} (generation plus execution budget)</div>`
          : `<div class="indet" aria-hidden="true"><span></span></div><div class="muted">${stage === "install" ? "Installing what is missing, then generating." : "Running; this budget is a number of tests or the whole corpus, so there is no fixed time to count down."}</div>`}</section>`}
    <div class="resgrid two"><section class="rescard"><div class="rescard-h"><h4>Latest finding</h4></div>
        ${last ? `<div class="fcard on"><span class="stile ${(VERDICTS[last.verdict] || {}).tone || "red"} sm" aria-hidden="true">${ICONS.bug}</span><span class="fc-m"><strong>${esc(last.headline)}</strong>
            <span class="fc-tags">${vtag(last.verdict)}<span class="muted">${esc(last.id)} · input #${last.first_rank + 1}</span></span></span></div>
          <div class="muted livecount">${p.findings.length} finding${p.findings.length === 1 ? "" : "s"} so far</div>`
        : `<div class="empty">Nothing has failed yet.</div>`}</section>
      <section class="rescard"><div class="rescard-h"><h4>Log</h4></div>${L.external
        ? `<div class="empty">This campaign was started outside this Workbench, so its log is in the terminal that started it. The figures above come from the project's results as they are written.</div>`
        : `<pre class="livelog" aria-live="off">${esc(L.lines.slice(-14).join("\n")) || "Waiting for the first message…"}</pre>`}</section></div>`;
}

// ------- the page

// Campaigns is the project's run history whether or not it has any runs yet. Teaching what a
// result looks like belongs to Home; here an empty history is just that, and the way to fill it.
function campaignsEmpty() {
  return `<div class="resws">
    <div class="listhead"><div><h2>Campaigns</h2><p class="muted">Manage previous and active testing campaigns.</p></div></div>
    <section class="rescard cempty">
      <h3>No campaigns yet</h3>
      <p class="muted">Runs you launch from SpreadEx or the command line appear here. You can open, re-run,
        export, or permanently delete them from this page.</p>
      ${canAct() ? `<button type="button" class="primary" onclick="go('setup')">${ICONS.playOutline} Set up a campaign</button>` : ""}
    </section></div>`;
}

async function renderResults() {
  const v = el("view");
  if (S.rview === "live" && S.live) { v.innerHTML = `<div class="resws" id="live-root">${liveBody()}</div>`; return; }
  if (S.rview !== "run") {
    // Always the persisted history of this project, read fresh: a campaign may have been run or
    // deleted from the command line since this page loaded.
    try { await loadRuns(); } catch (e) { v.innerHTML = failureCard(e); return; }
    if (S.tab !== "results" || S.rview === "run") return;   // the user moved on meanwhile
    v.innerHTML = S.runs.length ? campaignsList() : campaignsEmpty();
    return;
  }
  if (!S.runs.length) { S.rview = "list"; v.innerHTML = campaignsEmpty(); return; }
  v.innerHTML = `<div id="detail"><div class="empty">Loading…</div></div>`;
  // The overview is fetched once per run; the tabs read from what came back. (run_detail shuffles
  // the corpus hundreds of times for the random baseline, so it is not cheap.)
  try { S.detail = await api(`/api/runs/${encodeURIComponent(S.current)}`); }
  catch (e) { el("detail").innerHTML = failureCard(e); return; }
  S.rf = null; S.rc = null; S.runMenu = S.actMenu = false; S.exportError = ""; S.actionError = "";
  paintRun();
  if (S.rtab === "corpus") loadCorpus();
  if (S.rtab === "findings") ensureFinding();
}

function pickRun(id) { openCampaign(id); }

function paintRun() {
  const d = S.detail;
  if (!d || !el("detail")) return;
  const body = ({ overview: tabOverview, generators: tabGenerators, budget: tabBudget, findings: tabFindings, corpus: tabCorpus }[S.rtab] || tabOverview)(d);
  const tab = S.rtab in { overview: 1, generators: 1, budget: 1, findings: 1, corpus: 1 } ? S.rtab : "overview";
  const n = (d.findings || []).length;
  el("detail").innerHTML = `<div class="resws">${resultsHeader(d)}
    ${S.exportError ? `<div class="note bad" role="alert">Export failed: ${esc(S.exportError)}</div>` : ""}
    ${S.actionError ? `<div class="note bad" role="alert">${esc(S.actionError)}</div>` : ""}
    <div class="rtabs2" role="tablist">${RESULT_TABS.map(t => `<button type="button" role="tab" data-tour="tab-${t.id}" class="${tab === t.id ? "on" : ""}" aria-selected="${tab === t.id}" onclick="pickResultTab('${t.id}')">
      ${ICONS[t.icon]}<span>${t.t}</span>${t.id === "findings" && n ? `<span class="rbadge">${n}</span>` : ""}</button>`).join("")}</div>
    <div class="restab-body">${body}</div></div>`;
}

// ---- tour (pure: the tests run this region under Node) -----------------------
//
// The guided demo. One concept, one highlighted target, one sentence, one action at a time. The
// guide only OBSERVES the Workbench: every target is a real element (data-tour="..."), every
// number comes from the real campaign, and it never clicks anything for the user. A beat moves on
// when the user does the real thing (`event`), acknowledges an explanation (`ack`), or the real
// campaign reaches the next stage (`event: "stage.*"`).
//
// `text(c)` gets a context of real data: { sut, cfg, probe, samples, live, detail, finding, replay }.

const TOUR_SUT = "MiniCalc";

function tourPct(n, d) { return d ? Math.round(100 * n / d) : 0; }
// A rule short enough for the coach card: its first alternative and its most telling one
// (parentheses, else an operator), each verbatim, then "| …" for what was left out.
function tourShortRule(rule) {
  const [head, body] = rule.split("::=");
  if (body === undefined) return rule;
  const alts = body.split("|").map(x => x.trim());
  const pick = alts.slice(1).find(x => x.includes('"("')) || alts.slice(1).find(x => /"\s*[-+*\/%]\s*"/.test(x));
  const kept = pick ? [alts[0], pick] : alts.slice(0, 2);
  return `${head.trim()} ::= ${kept.join(" | ")}${alts.length > kept.length ? " | …" : ""}`;
}
// Two inputs that show the grammar at work: nesting and an operator first, then the rest.
function tourExamples(samples) {
  const s = samples || [], rich = x => /\(/.test(x) && /[-+*\/%]/.test(x.replace(/^-/, ""));
  return [...s.filter(rich), ...s.filter(x => !rich(x))].slice(0, 2);
}

// Copy conventions, the same on every card:
//   **concept**  the idea being taught            -> orange
//   [[name]]     the system or product named      -> deep blue
//   {{value}}    a real number or a short heading -> bold, neutral
//   `code`       a technical value
// A blank line starts a smaller secondary line. One concept per card.
const TOUR = [
  // -- Setup 1 of 5: system under test
  { id: "sut.command", chapter: "Setup · 1 of 5", route: { tab: "setup", step: "sut" }, target: "sut-command", advance: { ack: "Next" },
    text: () => `Every campaign needs a **system to test**. We've connected [[${TOUR_SUT}]] for you.\n\nThis command runs each test input.` },
  { id: "sut.test", chapter: "Setup · 1 of 5", route: { tab: "setup", step: "sut" }, target: "sut-test", advance: { event: "probe.ok" },
    success: () => `✓ [[${TOUR_SUT}]] is connected.`,
    text: c => c.probe && c.probe.ok === false
      ? `That did not work. The **real error** is shown below the button.\n\nFix it, or test the connection again.`
      : `Let's check that SpreadEx can run [[${TOUR_SUT}]].` },
  { id: "sut.continue", chapter: "Setup · 1 of 5", route: { tab: "setup", step: "sut" }, target: "sut-continue", advance: { event: "step.sut" },
    text: () => `SpreadEx can now execute test inputs. Continue to **Inputs**.` },
  // -- 2 of 5: inputs
  { id: "inputs.grammar", chapter: "Setup · 2 of 5", route: { tab: "setup", step: "grammar" }, target: "inputs-grammar", advance: { ack: "Next" },
    // Grammar first, what it produces second: two real rules from calc.bnf, two real seed inputs.
    grammar: c => ({ rules: (c.grammarRules || []).slice(0, 2).map(tourShortRule), examples: tourExamples(c.samples) }),
    text: () => `SpreadEx needs to know **what inputs** [[${TOUR_SUT}]] **accepts**. We've included a small **BNF grammar** for you.` },
  { id: "inputs.constraint", chapter: "Setup · 2 of 5", route: { tab: "setup", step: "grammar" }, target: "inputs-constraint", advance: { ack: "Next" },
    rule: c => c.rule || "",
    check: { text: "Prepared for the generators that support constraints",
             tip: "In this demo the rule is already provided in Fandango's own format (spec/constraints.fan), and SpreadEx passes that file to Fandango unchanged. FuzzingBook and Grammarinator do not support constraints, so they use the grammar alone. In your own project, provide that file for each such generator, or draft it from your rule with the experimental assistant." },
    text: () => `{{Add a constraint.}} Tell SpreadEx an extra **rule** for generated inputs, one the grammar cannot express.` },
  { id: "inputs.continue", chapter: "Setup · 2 of 5", route: { tab: "setup", step: "grammar" }, target: "inputs-continue", advance: { event: "step.grammar" },
    text: () => `This **grammar** guides test generation. Nothing to upload or edit.` },
  // -- 3 of 5: generators
  { id: "gen.card", chapter: "Setup · 3 of 5", route: { tab: "setup", step: "generators" }, target: "gen-selected", advance: { ack: "Next" },
    text: c => `{{${(c.generators || []).length}}} **generators** are selected. Each writes {{${c.count || "the same number of"}}} candidate inputs from the same grammar.` },
  { id: "gen.cc", chapter: "Setup · 3 of 5", route: { tab: "setup", step: "generators" }, target: "gen-cards", advance: { ack: "Next" },
    text: c => `After generating, SpreadEx compares them by **Cluster Coverage**: it groups similar inputs into clusters and counts how many clusters each generator reached.` +
      (c.keep ? `\n\nThis campaign keeps ${c.keep === 1 ? "the {{single best}} generator and runs only its inputs" : `the best {{${c.keep}}} and runs only their inputs`}.` : "") },
  { id: "gen.continue", chapter: "Setup · 3 of 5", route: { tab: "setup", step: "generators" }, target: "gen-continue", advance: { event: "step.generators" },
    text: () => `SpreadEx will test inputs produced from this grammar. Continue to **Testing strategy**.` },
  // -- 4 of 5: strategy
  { id: "strat.rej", chapter: "Setup · 4 of 5", route: { tab: "setup", step: "strategy" }, target: "strat-rej", advance: { ack: "Next" },
    text: () => `**Expected rejections** are inputs the system is allowed to reject. SpreadEx separates them from findings.` },
  { id: "strat.crash", chapter: "Setup · 4 of 5", route: { tab: "setup", step: "strategy" }, target: "strat-crash", advance: { ack: "Next" },
    text: c => `A **crash** is different. SpreadEx reports it as something worth investigating.` +
      (c.timeout ? `\n\nNo response within \`${c.timeout}\` is classified as a **timeout**.` : "") },
  { id: "strat.continue", chapter: "Setup · 4 of 5", route: { tab: "setup", step: "strategy" }, target: "strat-continue", advance: { event: "step.strategy" },
    text: () => `These settings are ready for the demo. You only need to understand what they mean.` },
  // -- 5 of 5: review & run
  { id: "run.genbudget", chapter: "Setup · 5 of 5", route: { tab: "setup", step: "run" }, target: "run-genbudget", advance: { ack: "Next" },
    text: c => c.count
      ? `The **generation budget** is what each generator gets. Here it is an equal count: {{${c.count}}} inputs each, so the run is reproducible.\n\nEqual time is the resource-fair alternative: every generator gets the same seconds.`
      : `The **generation budget** is what each generator gets: the same seconds each, so the comparison is resource-fair.` },
  { id: "run.execbudget", chapter: "Setup · 5 of 5", route: { tab: "setup", step: "run" }, target: "run-execbudget", advance: { ack: "Next" },
    text: c => `The **execution budget** says when to stop running inputs against [[${TOUR_SUT}]]` + (c.execution ? `: here, up to {{${c.execution}}}.` : ".") +
      `\n\nEach input still has its own timeout from the testing strategy.` },
  { id: "run.ordering", chapter: "Setup · 5 of 5", route: { tab: "setup", step: "run" }, target: "run-ordering", advance: { ack: "Next" },
    text: c => `**Test ordering**: SpreadEx prioritization runs the most different inputs first; random order is the baseline to compare against.` +
      (c.keep ? `\n\n**Generator selection**: ${c.keep === 1 ? "only the {{best generator}}" : `only the top {{${c.keep}}} generators`} by Cluster Coverage will run.` : "") },
  { id: "run.launch", chapter: "Setup · 5 of 5", route: { tab: "setup", step: "run" }, target: "run-launch", advance: { event: "campaign.started" },
    story: c => [TOUR_SUT, "Calculator grammar", (c.generators || []).join(", ") || "Seed inputs", "Candidate inputs",
                 ...(c.keep ? [c.keep === 1 ? "Cluster Coverage: keep the best generator" : `Cluster Coverage: keep the top ${c.keep}`] : []), "SpreadEx prioritization", "Execute + classify"],
    text: () => `Everything is ready. Run your first **real SpreadEx campaign**.` },
  // -- running: watch
  { id: "live.install", chapter: "Running", route: { live: true }, target: "live-stages|live-view", advance: { event: "stage.generate" },
    text: () => `Preparing the **generator**. This setup time does not use your campaign budget.` },
  { id: "live.generate", chapter: "Running", route: { live: true }, target: "live-stages|live-view", advance: { event: "stage.rank" },
    text: c => `${(c.generators || []).length > 1 ? `{{${c.generators.length}}} generators are creating` : "Creating"} **candidate inputs** from the [[${TOUR_SUT}]] grammar.` },
  { id: "live.rank", chapter: "Running", route: { live: true }, target: "live-stages|live-view", advance: { event: "stage.select" },
    text: () => `SpreadEx turns every candidate into a vector, groups similar ones into **clusters**, and measures each generator's **Cluster Coverage**.` },
  { id: "live.select", chapter: "Running", route: { live: true }, target: "live-stages|live-view", advance: { event: "stage.execute" },
    text: c => { const m = /selected by cluster coverage: (.*) \(kept (\d+) of (\d+); dropped (.*); (\d+) inputs to execute\)/.exec(c.selectLine || "");
      return m ? `**Generator selection**: kept {{${m[1]}}}; dropped {{${m[4]}}}.\n\nOnly the kept generators' {{${m[5]}}} inputs will run.`
        : `**Generator selection**: no choice was needed here, so every generator's inputs will run.`; } },
  { id: "live.execute", chapter: "Running", route: { live: true }, target: "live-stages|live-view", advance: { event: "campaign.done" },
    text: () => `Running the inputs against [[${TOUR_SUT}]] in **SpreadEx priority order**, and classifying each result.` },
  { id: "live.failed", chapter: "Running", route: { live: true }, target: "live-stages|live-view", advance: { ack: "Next" }, final: true,
    text: () => `The campaign stopped. The **real error** is shown below.` },
  // -- understand your results
  { id: "res.overview", chapter: "Understand your results", route: { tab: "results", rtab: "overview" }, target: "res-kpis", advance: { ack: "Next" },
    text: c => { const d = c.detail || {}, v = d.verdicts || {}, n = (d.findings || []).length, f = `finding${n === 1 ? "" : "s"}`;
      return `{{Start here for the big picture.}} SpreadEx executed {{${d.executed ?? 0} inputs}} and discovered **${n} ${f}**.\n\n` +
        `{{${v.ok || 0}}} normal · {{${v.expected_rejection || 0}}} expected rejections · {{${n}}} ${f}` +
        // A zero is part of the story when the selected generator followed the demo's constraint.
        (!v.expected_rejection && d.selection && c.rule
          ? `\n\n{{0 expected rejections}}: in this run the selected generator followed the constraint, so inputs matching [[${TOUR_SUT}]]'s known rejection case were filtered out before execution.` : ""); } },
  { id: "res.findtab", chapter: "Understand your results", route: { tab: "results", rtab: "overview" }, target: "tab-findings", advance: { event: "tab.findings" },
    text: c => (c.detail?.findings || []).length ? `Now let's investigate the **finding**.` : `Nothing failed this time. **Findings** is where you would look.` },
  { id: "res.finding", chapter: "Understand your results", route: { tab: "results", rtab: "findings" }, target: "finding-card", advance: { event: "finding.opened" },
    text: () => `A **finding** is behavior worth investigating.\n\nSimilar failures are grouped together.` },
  { id: "fd.input", chapter: "Understand your results", route: { tab: "results", rtab: "findings" }, target: "fd-input", advance: { ack: "Next" },
    text: () => `This is the exact **input that triggered the problem**.` },
  { id: "fd.class", chapter: "Understand your results", route: { tab: "results", rtab: "findings" }, target: "fd-class", advance: { ack: "Next" },
    text: c => `SpreadEx classified this as a **${c.finding?.verdict || "failure"}**, not a normal rejection.\n\nThe first matching check determines the classification.` },
  { id: "fd.output", chapter: "Understand your results", route: { tab: "results", rtab: "findings" }, target: "fd-output", advance: { ack: "Next" },
    text: () => `This is the **execution evidence** from [[${TOUR_SUT}]].` },
  { id: "fd.replay", chapter: "Understand your results", route: { tab: "results", rtab: "findings" }, target: "fd-replay", advance: { event: "replay.done" },
    passed: "Replay was not run, so nothing was checked. You can replay any finding later.",
    success: r => r && r.reproduced ? "✓ {{Reproduced.}} The same input triggered the behavior again."
      : r && r.ok === false ? `Replay failed: ${r.error}` : "{{Not reproduced}} this time. The page explains what that can mean.",
    text: () => `Let's see if the same input **reproduces the finding**.` },
  { id: "res.gentab", chapter: "Understand your results", route: { tab: "results", rtab: "findings" }, target: "tab-generators", advance: { event: "tab.generators" },
    text: () => `Next: **where the inputs came from**.` },
  { id: "gen.compare", chapter: "Understand your results", route: { tab: "results", rtab: "generators" }, target: "gen-compare", advance: { ack: "Next" },
    text: c => { const g = (c.detail?.by_generator || []).filter(x => x.executed);
      return `Each row shows **where the test inputs came from** and what happened to them.` +
        (c.detail?.selection ? ` The **Selected by CC** tags show which generators this campaign kept.` : "") + `\n\n` +
        `**Cluster coverage** shows how broadly a generator explored the input space: higher means it reached **more different regions**.` +
        (g.length > 1 ? " Compare generators to see which explored more broadly." : ""); } },
  { id: "res.budtab", chapter: "Understand your results", route: { tab: "results", rtab: "generators" }, target: "tab-budget", advance: { event: "tab.budget" },
    text: () => `Next: **how early** the finding appeared.` },
  { id: "bud.curve", chapter: "Understand your results", route: { tab: "results", rtab: "budget" }, target: "budget-curve", advance: { ack: "Next" },
    text: c => { const d = c.detail || {}, f = (d.findings || []).map(x => x.position).filter(x => x != null);
      const first = f.length ? Math.min(...f) + 1 : null;
      return (first ? `The first finding appeared at {{input ${first} of ${d.executed}}}: only {{${tourPct(first, d.executed)}%}} of the inputs that ran.\n\n` : "") +
        `SpreadEx prioritizes which tests run first, helping important behaviors appear **earlier within a limited budget**.`; } },
  { id: "res.cortab", chapter: "Understand your results", route: { tab: "results", rtab: "budget" }, target: "tab-corpus", advance: { event: "tab.corpus" },
    text: () => `Last: **the inputs themselves**.` },
  { id: "cor.input", chapter: "Understand your results", route: { tab: "results", rtab: "corpus" }, target: "corpus-input", advance: { ack: "Next" },
    text: () => `The **Corpus** contains the actual inputs from this campaign.\n\nFor each input, you can see **where it came from** and **what happened when it ran**.` },
  { id: "done", chapter: "Done", target: null, advance: { ack: "Next" }, final: true,
    text: () => `{{You've completed your first SpreadEx campaign.}}` },
];
// What the finish card lists.
const TOUR_LEARNT = ["Connected a system", "Generated test inputs", "Compared generators by Cluster Coverage", "Ran a prioritized campaign",
                     "Investigated a finding", "Replayed the behavior", "Learned how to read the results"];
const TOUR_IDS = TOUR.map(b => b.id);

// The beat after `id` once `event` happened; the same beat when the event means nothing here.
// "ack" is the coach card's Next button. Campaign events can arrive in any running beat, and a stage can be
// skipped (nothing to install), so they jump forward rather than step.
function tourNext(id, event) {
  const i = TOUR_IDS.indexOf(id);
  if (i < 0) return id;
  const beat = TOUR[i];
  if (beat.chapter === "Running") {
    if (event === "campaign.failed") return "live.failed";
    if (event === "campaign.done") return id === "live.failed" ? id : "res.overview";
    const m = /^stage\.(\w+)$/.exec(event || "");
    if (m && TOUR_IDS.includes("live." + m[1]) && TOUR_IDS.indexOf("live." + m[1]) > i) return "live." + m[1];
  }
  if (beat.final) return id;
  const a = beat.advance;
  if ((a.ack && event === "ack") || (a.event && a.event === event)) return TOUR_IDS[i + 1];
  // Doing the real thing early (Continue before Next) moves on to where it leads.
  const ahead = TOUR.findIndex((b, k) => k > i && b.advance.event === event && b.chapter === beat.chapter);
  if (ahead >= 0 && !/^stage\./.test(event)) return TOUR_IDS[ahead + 1];
  return id;
}
// One beat back, for re-reading. Never into the Running chapter (it has passed) or before the start.
function tourPrev(id) {
  let i = TOUR_IDS.indexOf(id);
  if (i <= 0 || TOUR[i].chapter === "Running" || id === "done") return id;
  for (i -= 1; i >= 0; i--) if (TOUR[i].chapter !== "Running") return TOUR_IDS[i];
  return id;
}
// "n of N" within the beat's chapter. Setup's chapters already say which step of five they are.
function tourProgress(id) {
  const beat = TOUR[TOUR_IDS.indexOf(id)];
  if (!beat || beat.final || beat.chapter.startsWith("Setup")) return null;
  const same = TOUR.filter(b => b.chapter === beat.chapter && !b.final);
  return { n: same.indexOf(beat) + 1, of: same.length };
}
// Results steps that wait for a real action can be passed without doing it. Setup ones cannot:
// the steps after them need what they do (a tested command, a confirmed step).
function tourCanPass(id) {
  const beat = TOUR[TOUR_IDS.indexOf(id)];
  return !!beat && !!beat.advance.event && beat.chapter === "Understand your results";
}
// Watching a campaign: a jump over several stages is shown one stage at a time.
function tourStep(id, event) {
  const next = tourNext(id, event), i = TOUR_IDS.indexOf(id), j = TOUR_IDS.indexOf(next);
  if (TOUR[i]?.chapter !== "Running" || next === "live.failed" || j <= i) return { id: next, again: false };
  // the next stage still to show, if the jump passes over one (never the failure beat)
  const k = TOUR.findIndex((b, x) => x > i && x < j && b.chapter === "Running" && !b.final);
  return k >= 0 ? { id: TOUR_IDS[k], again: true } : { id: next, again: false };
}
// ---- end tour

// The guide's state lives in this tab (a reload resumes it); it starts only in the demo Workbench.
const TOUR_KEY = "spreadex-tour";
function tourLoad() { try { return JSON.parse(sessionStorage.getItem(TOUR_KEY) || "null"); } catch (e) { return null; } }
function tourSave() { try { S.tour ? sessionStorage.setItem(TOUR_KEY, JSON.stringify(S.tour)) : sessionStorage.removeItem(TOUR_KEY); } catch (e) { /* blocked storage */ } }

function tourStart() {
  // The real gating then asks for the user's own Test connection and Continue clicks.
  S.verifiedSut = null; S.confirmed.clear(); S.probe = null;
  S.tour = { id: TOUR[0].id, flash: "", paused: false, enteredAt: Date.now() };
  tourSave(); paintDemoStrip();
  S.step = TOUR[0].route.step; go("setup"); renderSteps(); tourRoute(false);
}
// After a reload mid-tour, the setup steps the user already did through the guide count as done,
// and the ones still ahead are not -- so the gating matches where the guide is.
function tourRestoreGates() {
  const at = TOUR_IDS.indexOf(S.tour.id), past = id => at > TOUR_IDS.indexOf(id);
  S.verifiedSut = past("sut.test") ? sutKey(cfg().sut) : null;
  S.confirmed.clear();
  [["inputs.continue", "grammar"], ["gen.continue", "generators"], ["strat.continue", "strategy"]]
    .forEach(([beat, step]) => { if (past(beat)) S.confirmed.add(step); });
}
function tourStop() { S.tour = null; tourSave(); paintDemoStrip(); tourPaint(); }
function tourPause() { if (S.tour) { S.tour.paused = true; tourSave(); paintDemoStrip(); tourPaint(); } }
function tourResume() { if (S.tour) { S.tour.paused = false; tourSave(); paintDemoStrip(); tourRoute(true); } else tourStart(); }

// A tour can come back to a "Running" step with nothing running -- the page was opened or reloaded
// after the campaign ended. Waiting for a progress bar that will never come is a dead end: move on
// to what actually happened instead. Returns true when it moved.
function tourReconcile() {
  const b = S.tour && TOUR[TOUR_IDS.indexOf(S.tour.id)];
  // Only once the page has settled: during start-up the live view may not have reconnected yet.
  if (!S.booted || !b || b.chapter !== "Running" || b.final || S.live?.active || tourDraining) return false;
  const last = (S.runs || [])[0];
  tourQueue.length = 0;
  if (last && (last.status === "finished" || last.status === "cancelled")) {
    S.current = last.run_id; S.rview = "run"; S.rtab = "overview";
    tourSet("res.overview", ""); setTimeout(() => tourRoute(true), 80);
  } else {
    tourSet("run.launch", last ? "The last campaign did not finish. Run it again." : "");
    setTimeout(() => tourRoute(true), 80);
  }
  return true;
}

function tourBeat() { return S.tour && !S.tour.paused ? TOUR[TOUR_IDS.indexOf(S.tour.id)] : null; }

// Called from the real handlers. `info` carries what the success line needs (the replay result).
const TOUR_DWELL_MS = 1500;   // each campaign stage stays on screen at least this long
const tourQueue = [];
let tourDraining = null;

function tourEvent(name, info) {
  if (!S.tour) return;
  if (TOUR[TOUR_IDS.indexOf(S.tour.id)]?.chapter === "Running" || tourQueue.length) {
    tourQueue.push(name);
    if (!tourDraining) tourDraining = tourDrain();
    return;
  }
  tourApply(name, info);
}
// The real campaign can finish in a few seconds. Its stages are still shown one after another,
// each for a moment -- what is shown is what happened, just not faster than it can be read.
async function tourDrain() {
  while (tourQueue.length && S.tour) {
    // Each stage stays readable for a moment -- unless nobody can see it: a hidden tab throttles
    // timers to a crawl, and holding the queue there would also hold back the results page.
    const wait = TOUR_DWELL_MS - (Date.now() - (S.tour.enteredAt || 0));
    if (wait > 0 && !document.hidden) await tourWait(wait);
    const name = tourQueue[0], { id, again } = tourStep(S.tour.id, name);
    if (!again) tourQueue.shift();
    if (id === S.tour.id) continue;
    tourSet(id, "");
  }
  tourDraining = null;
}
// A pause that ends early if the tab is hidden: timers in a hidden tab can be held back for up to
// a minute, and nobody is watching the stages then anyway.
function tourWait(ms) {
  return new Promise(resolve => {
    const done = () => { clearTimeout(timer); document.removeEventListener("visibilitychange", onVis); resolve(); };
    const onVis = () => { if (document.hidden) done(); };
    const timer = setTimeout(done, ms);
    document.addEventListener("visibilitychange", onVis);
  });
}
// Resolves once the queued stages have been shown -- but the results never wait on the guide for
// long: past the time the remaining stages need, it moves straight on to the results chapter.
function tourSettled() {
  if (!tourDraining) return Promise.resolve();
  const limit = TOUR_DWELL_MS * (tourQueue.length + 2);
  return Promise.race([tourDraining, new Promise(r => setTimeout(r, limit))]).then(() => {
    const b = S.tour && TOUR[TOUR_IDS.indexOf(S.tour.id)];
    if (b && b.chapter === "Running" && !b.final) { tourQueue.length = 0; tourSet("res.overview", ""); }
  });
}

function tourApply(name, info) {
  const before = S.tour.id, beat = TOUR[TOUR_IDS.indexOf(before)];
  const next = tourNext(before, name);
  if (next === before) { if (name === "probe.fail") tourPaint(); return; }
  tourSet(next, beat?.success && beat.advance.event === name ? beat.success(info) : "");
}
function tourSet(id, flash) {
  S.tour.flash = flash; S.tour.id = id; S.tour.enteredAt = Date.now(); tourSave();
  // A step change already re-renders; give it a moment, then point at the next thing.
  setTimeout(() => tourRoute(false), 60);
}
function tourBack() { const id = tourPrev(S.tour.id); if (id !== S.tour.id) { tourSet(id, ""); setTimeout(() => tourRoute(true), 80); } }
// Pass a results step without doing its action. Nothing is pretended: the next card says so.
function tourPass() {
  const b = tourBeat(); if (!b || !tourCanPass(b.id)) return;
  tourSet(TOUR_IDS[TOUR_IDS.indexOf(b.id) + 1], b.passed || "");
  setTimeout(() => tourRoute(true), 80);
}

// Open the beat's screen if a different one is showing. Only ever navigates; never clicks.
function tourRoute(force) {
  const b = tourBeat(); if (!b) return tourPaint();
  const r = b.route;
  if (r && force) {
    if (r.live) { if (S.live?.active) { S.rview = "live"; go("results"); } else tourReconcile(); }
    else if (r.tab === "setup") { go("setup"); gotoStep(r.step); }
    else if (r.tab === "results" && S.current) {
      if (S.tab !== "results" || S.rview !== "run") { S.rtab = r.rtab || "overview"; S.rview = "run"; go("results"); }
      else if (r.rtab && S.rtab !== r.rtab) { S.rtab = r.rtab; paintRun(); if (r.rtab === "corpus") loadCorpus(); if (r.rtab === "findings") ensureFinding(); }
    }
  }
  S.tour.scrolled = null;
  tourPaint();
}

// The tour's own light markup (see the conventions above TOUR). Escaped first, so data can never
// become markup.
function tourRich(text) {
  return esc(text)
    .replace(/\*\*(.+?)\*\*/g, '<strong class="tour-key">$1</strong>')
    .replace(/\[\[(.+?)\]\]/g, '<strong class="tour-name">$1</strong>')
    .replace(/\{\{(.+?)\}\}/g, '<strong class="tour-val">$1</strong>')
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

function tourContext() {
  const c = cfg(), sut = c.sut || {};
  return { probe: S.probe, samples: S.demo?.samples || [], grammarRules: S.demo?.grammar_rules || [],
           constraint: S.demo?.constraint || "", rule: S.demo?.rule || "", keep: Number.isInteger(c.selection?.keep) ? c.selection.keep : 0, count: c.generation?.count || 0,
           execution: c.budget?.execution || "", selectLine: (S.live?.lines || []).find(l => SELECTED_LINE.test(l)) || "", timeout: sut.timeout ? String(sut.timeout) : "",
           generators: c.generators || [], detail: S.detail, finding: S.rf?.detail };
}

let tourFrame = 0;
// Animation frames do not run in a hidden tab, so a guide repainted only by them would come back
// stale; a hidden tab gets a timer instead.
function tourSchedule() {
  cancelAnimationFrame(tourFrame); clearTimeout(tourFrame);
  tourFrame = document.hidden ? setTimeout(tourPaint, 60) : requestAnimationFrame(tourPaint);
}

function tourPaint() {
  let hole = el("tour-hole"), card = el("tour-card");
  document.querySelectorAll(".tour-target").forEach(n => n.classList.remove("tour-target"));
  const b = tourBeat();
  if (!b) { hole?.remove(); card?.remove(); return; }
  if (!hole) { hole = Object.assign(document.createElement("div"), { id: "tour-hole", className: "tour-hole" }); hole.setAttribute("aria-hidden", "true"); document.body.appendChild(hole); }
  if (!card) { card = Object.assign(document.createElement("div"), { id: "tour-card", className: "tour-card" }); card.setAttribute("role", "dialog"); card.setAttribute("aria-live", "polite"); card.setAttribute("aria-label", "Guided demo"); document.body.appendChild(card); }
  // A target may name fallbacks ("a|b"): the first one on the page is used.
  const t = b.target ? b.target.split("|").map(x => document.querySelector(`[data-tour="${x}"]`)).find(Boolean) || null : null;
  const c = tourContext();
  const g = b.grammar ? b.grammar(c) : null;
  const bnf = g && g.rules.length ? `<div class="tour-bnf"><pre>${g.rules.map(esc).join("\n")}</pre>
      ${g.examples.length ? `<div class="tour-arrow" aria-hidden="true">↓</div><div class="tour-ex"><span class="muted">It can generate inputs like</span>
        ${g.examples.map(x => `<code>${esc(x)}</code>`).join(" ")}</div>` : ""}</div>` : "";
  const codeBlock = (b.code && b.code(c) ? `<div class="tour-bnf"><pre>${esc(b.code(c))}</pre></div>` : "")
    + (b.rule && b.rule(c) ? `<div class="tour-rule"><span class="spark" aria-hidden="true">\u2726</span><span>\u201c${esc(b.rule(c))}\u201d</span></div>` : "")
    + (b.check ? `<div class="tour-check"><span class="ok" aria-hidden="true">\u2713</span><span>${esc(b.check.text)}</span>${hint("hint-tour-check", b.check.tip)}</div>` : "");
  const story = b.story ? `<ol class="tour-story">${b.story(c).map(s => `<li>${esc(s)}</li>`).join("")}</ol>` : "";
  const finish = b.id === "done" ? `<ul class="tour-learnt">${TOUR_LEARNT.map(s => `<li>${ICONS.check}<span>${s}</span></li>`).join("")}</ul>` : "";
  const missing = b.target && !t;
  if (missing && b.chapter === "Running" && tourReconcile()) return;
  const prog = tourProgress(b.id), back = tourPrev(b.id) !== b.id;
  const buttons = b.id === "done"
    ? `${S.project?.return_url ? `<a class="primary tour-btn" href="${esc(S.project.return_url)}">Try SpreadEx on my project</a>` : ""}<button type="button" class="ghost small" onclick="tourStop()">Keep exploring</button>`
    : `${b.id === "live.failed" ? `<button type="button" class="ghost small" onclick="tourStop()">Exit the guide</button>`
        : missing && b.route ? `<button type="button" class="primary small" onclick="tourRoute(true)">Take me there</button>`
        : b.advance.ack ? `<button type="button" class="primary small" onclick="tourEvent('ack')">${esc(b.advance.ack)} ${ICONS.arrow}</button>` : ""}
       ${!missing && tourCanPass(b.id) ? `<button type="button" class="ghost small" onclick="tourPass()" title="Go on without doing this; nothing is run for you">Show me the next part</button>` : ""}
       ${back ? `<button type="button" class="linkish" onclick="tourBack()">Back</button>` : ""}
       ${b.id === "done" || b.id === "live.failed" ? "" : `<button type="button" class="linkish tour-skip" onclick="tourPause()">Skip tour</button>`}`;
  const html = `<div class="tour-chap">${esc(b.chapter)}${prog ? ` · ${prog.n} of ${prog.of}` : ""}</div>
    ${S.tour.flash ? `<div class="tour-flash ${S.tour.flash.startsWith("✓") ? "" : "plain"}">${tourRich(S.tour.flash)}</div>` : ""}
    ${tourRich(b.text(c)).split("\n\n").map((para, k) => `<p class="${k ? "tour-sub" : ""}">${para}</p>${k === 0 ? codeBlock : ""}`).join("")}${bnf}${story}${finish}
    ${missing && !b.route ? `<p class="muted">Waiting for the page to show it&hellip;</p>` : ""}
    <div class="tour-actions">${buttons}</div>`;
  // Repaints are frequent (scroll, re-render); rebuilding unchanged buttons would swallow clicks and focus.
  if (card.dataset.html !== html) { card.innerHTML = html; card.dataset.html = html; }
  if (!t) { hole.style.display = "none"; card.classList.add("centre"); card.style.top = card.style.left = ""; return; }
  t.classList.add("tour-target");
  if (S.tour.scrolled !== b.id) {
    S.tour.scrolled = b.id;
    t.scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: no-preference)").matches ? "smooth" : "auto" });
    setTimeout(tourSchedule, 350);   // place again once the scroll settles
  }
  let r = t.getBoundingClientRect(); const pad = 6;
  // A step that renders in stages can push the target away after the first scroll: follow it once.
  if ((r.bottom < 0 || r.top > innerHeight) && S.tour.rescrolled !== b.id) {
    S.tour.rescrolled = b.id; t.scrollIntoView({ block: "center" }); r = t.getBoundingClientRect();
  }
  Object.assign(hole.style, { display: "", top: `${r.top - pad}px`, left: `${r.left - pad}px`, width: `${r.width + 2 * pad}px`, height: `${r.height + 2 * pad}px` });
  card.classList.remove("centre");
  if (innerWidth < 640) { card.style.top = card.style.left = ""; card.classList.add("docked"); return; }
  card.classList.remove("docked");
  const ch = card.offsetHeight, cw = card.offsetWidth;
  const below = r.bottom + 14 + ch < innerHeight;
  // Always on screen, even while its target is scrolled away: the card is how you find it again.
  const top = Math.min(innerHeight - ch - 8, Math.max(8, below ? r.bottom + 14 : r.top - ch - 14));
  card.style.top = `${top}px`;
  const left = Math.min(innerWidth - cw - 12, Math.max(12, r.left));
  card.style.left = `${left}px`;
  // The pointer: from the card's edge toward the target, when the card sits right next to it.
  const tip = below ? top === r.bottom + 14 : top === r.top - ch - 14;
  card.classList.toggle("pt-up", tip && below); card.classList.toggle("pt-down", tip && !below);
  card.style.setProperty("--pt-x", `${Math.max(18, Math.min(cw - 18, r.left + Math.min(r.width, 120) / 2 - left))}px`);
}
addEventListener("scroll", tourSchedule, { passive: true });
addEventListener("resize", tourSchedule);
new MutationObserver(tourSchedule).observe(document.getElementById("view") || document.body, { childList: true, subtree: true });

// The demo Workbench says what it is, and offers the way back.
function paintDemoStrip() {
  let strip = el("demo-strip");
  if (!S.project?.demo) { strip?.remove(); return; }
  if (!strip) {
    strip = Object.assign(document.createElement("div"), { id: "demo-strip", className: "demo-strip" });
    document.querySelector("header.topbar").insertAdjacentElement("afterend", strip);
  }
  strip.innerHTML = `<span class="demo-tag">Demo Workspace</span>
    <span class="muted">A bundled example, separate from your project. Its campaigns run for real.</span>
    <span class="grow"></span>
    ${S.tour && !S.tour.paused ? `<button type="button" class="ghost small" onclick="tourPause()">Skip tour</button>` : `<button type="button" class="ghost small" onclick="tourResume()">${S.tour ? "Resume tour" : "Start the tour"}</button>`}
    <button type="button" class="ghost small" onclick="demoFresh()">Start fresh</button>
    ${S.project.return_url ? `<a class="ghost small demo-back" href="${esc(S.project.return_url)}">${ICONS.back} Back to my project</a>` : ""}`;
}

// ------------------------------------------------------------- bootstrap

(async function () {
  try {
    S.project = await api("/api/project");
    if (S.project.theme && S.project.theme !== document.documentElement.getAttribute("data-theme")) applyTheme(S.project.theme);
    // The project path used to sit in the header, competing with the menu. It
    // is one hover away in the badge instead.
    const badge = el("local-badge");
    badge.title = `Running locally for ${S.project.root}\n\n${badge.title}`;
    const conf = await api("/api/config");
    S.config = conf.parsed || {};
    S.draft = null;
    S.inp = null;
    S.gen = null;
    S.strat = null;
    S.run = null;
    await loadRuns();
    // What is already saved on disk was reviewed when it was written: its steps count as done,
    // and its command as tested, until the user changes them.
    if (S.project.configured) {
      S.verifiedSut = sutKey(S.config.sut);
      ["grammar", "generators", "strategy"].forEach(id => S.confirmed.add(id));
    }
    paintDemoStrip();
    if (S.project.demo) {
      try { S.demo = await api("/api/demo"); } catch (e) { /* samples are optional */ }
      S.tour = TOUR_START ? null : tourLoad();
      if (S.tour) { tourRestoreGates(); paintDemoStrip(); }
    }
    // A page refreshed (or opened) while a campaign is running goes straight back to watching it --
    // whether this Workbench started it or not.
    try {
      const job = await api("/api/activity");
      const act = await api("/api/active");
      // A fresh open still starts on Home (Campaigns shows the running one); a reload goes back to it.
      if (!FRESH_OPEN && !job.idle && !job.done && job.kind === "run") { renderSteps(); return startLive(null, act.started_at); }
      if (!FRESH_OPEN && act.active) { renderSteps(); return startLive(act); }
    } catch (e) { /* no job info is not an error */ }
    // Just opened from Home: begin at step 1. (Reloaded mid-tour, it carries on from where it was.)
    if (S.project.demo && TOUR_START) { renderSteps(); return tourStart(); }
    const v = FRESH_OPEN ? { tab: "landing" } : initialView(S.project, S.runs, loadView(), stepReachable);
    if (v.step) S.step = v.step;
    if (v.rview) S.rview = v.rview;
    if (v.current) S.current = v.current;
    renderSteps();
    go(v.tab);
    S.booted = true;
    if (S.tour && !tourReconcile()) tourRoute(true);
  } catch (e) {
    const noToken = !TOKEN || /token/i.test(e.message);
    el("view").innerHTML = noToken
      ? `<div class="card"><h3>This tab has no access token</h3>
          <p class="why">The token is handed over once in the URL and kept only for this tab, so a
          fresh tab has to be opened from the link SpreadEx printed.</p><pre>spreadex ui</pre></div>`
      : `<div class="card"><div class="note bad">${esc(e.message)}</div></div>`;
  }
})();
