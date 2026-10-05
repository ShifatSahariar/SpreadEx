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
  // `icon` is a NAME looked up in ICONS at render time: ICONS is declared
  // further down, and reading it from here would hit the temporal dead zone.
  { id: "sut",        n: 1, tone: "green",  icon: "terminal",    t: "System under test", d: "The command to run." },
  { id: "grammar",    n: 2, tone: "blue",   icon: "doc",         t: "Inputs",            d: "Where they come from." },
  { id: "generators", n: 3, tone: "purple", icon: "sliders",     t: "Generators",        d: "Who writes the inputs." },
  { id: "strategy",   n: 4, tone: "orange", icon: "shield",      t: "Testing strategy",  d: "What counts as a failure." },
  { id: "run",        n: 5, tone: "blue",   icon: "playOutline", t: "Budget & run",      d: "Review, then launch." },
];

const S = {
  tab: "setup", step: "sut", project: null, config: {}, rejects: undefined,
  rtab: "overview", detail: null,
  kind: null, sample: undefined, probe: null,
  generators: [], grammars: [], runs: [], current: null, polling: null,
};

function initialView(project, runs) {
  if (!project.configured) return "landing";
  return runs.length ? "results" : "setup";
}

// ---------------------------------------------------------------- icons
// Inline SVG rather than glyphs: a font glyph like "▥" renders differently on
// every platform and cannot take a theme colour. These inherit currentColor,
// scale with the box, and carry no text content for a screen reader to read
// out -- the label beside them is the label.
const I = (p, o = {}) =>
  `<svg class="ico" viewBox="0 0 24 24" fill="${o.fill || "none"}" stroke="currentColor"
     stroke-width="${o.w || 1.8}" stroke-linecap="round" stroke-linejoin="round"
     aria-hidden="true" focusable="false">${p}</svg>`;

//: The brand mark, animated. Carried over from the research webapp's topbar so
//: the tool keeps the identity it has always had: the red centre pops, the
//: green squares fan to the corners, the orange circles follow, and the spokes
//: fade in behind them. Decorative, so it is hidden from assistive tech -- the
//: heading beside it already says what this is.
const BRAND_MARK = `
  <svg class="hero-mark" viewBox="0 0 60 60" xmlns="http://www.w3.org/2000/svg"
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

const ICONS = {
  terminal:    I(`<rect x="3" y="4.5" width="18" height="15" rx="3"/><path d="M7.5 9.5l3 2.5-3 2.5M12.5 15h4"/>`),
  doc:         I(`<path d="M6 3.5h7.5L19 9v11.5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-16a1 1 0 0 1 1-1z"/><path d="M13.5 3.5V9H19"/><path d="M8.5 13h7M8.5 16.5h5"/>`),
  shield:      I(`<path d="M12 3.2 5 6v6c0 4.2 2.9 7.4 7 8.8 4.1-1.4 7-4.6 7-8.8V6z"/>`),
  playOutline: I(`<path d="M7 4.8 19 12 7 19.2z"/>`),
  info:       I(`<circle cx="12" cy="12" r="9.5"/><path d="M12 11.2v5.3"/><path d="M12 7.7v.01" stroke-width="2.4"/>`),
  home:       I(`<path d="M3 10.5 12 3l9 7.5"/><path d="M5.5 9.5V20h13V9.5"/><path d="M9.5 20v-5.5h5V20"/>`),
  folder:     I(`<path d="M3 7a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.6.8l.9 1.2H19a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>`),
  sliders:    I(`<path d="M4 7h10M18 7h2M4 12h4M12 12h8M4 17h8M16 17h4"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="14" cy="17" r="2"/>`),
  play:       I(`<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M10.5 9.2v5.6L15 12z"/>`),
  download:   I(`<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M12 8.5v5m0 0 2-2m-2 2-2-2M8.5 16h7"/>`),
  gear:       I(`<circle cx="12" cy="12" r="3.2"/><path d="M19.4 14.5a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.2a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.2a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.2a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.2a1.6 1.6 0 0 0-1.5 1z"/>`),
  playSolid:  I(`<path d="M7 4.8 19 12 7 19.2z" fill="currentColor" stroke-linejoin="round"/>`, {w: 1.6}),
  book:       I(`<path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H10a2.5 2.5 0 0 1 2 1 2.5 2.5 0 0 1 2-1h4.5A1.5 1.5 0 0 1 20 5.5v12a1.5 1.5 0 0 1-1.5 1.5H14a2.5 2.5 0 0 0-2 1 2.5 2.5 0 0 0-2-1H5.5A1.5 1.5 0 0 1 4 17.5z"/><path d="M12 5v15"/>`),
  arrow:      I(`<path d="M4 12h15m0 0-5.5-5.5M19 12l-5.5 5.5"/>`),
  check:      I(`<path d="M5 12.5l4.5 4.5L19 7.5"/>`),
  alert:      I(`<path d="M12 4 2.8 19.5h18.4z"/><path d="M12 10v4.5"/><path d="M12 17.2v.01" stroke-width="2.4"/>`),
  copy:       I(`<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M15.5 8.5V6a1.5 1.5 0 0 0-1.5-1.5H6A1.5 1.5 0 0 0 4.5 6v8A1.5 1.5 0 0 0 6 15.5h2.5"/>`),
  chart:      I(`<path d="M4.5 20h15"/><rect x="6" y="11" width="3.4" height="6" rx="1"/><rect x="11.3" y="6.5" width="3.4" height="10.5" rx="1"/><rect x="16.6" y="13.5" width="3.4" height="3.5" rx="1"/>`),
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
  S.tab = tab;
  paintNavIcons();
  el("tab-home").setAttribute("aria-selected", tab === "landing");
  el("tab-setup").setAttribute("aria-selected", tab === "setup");
  el("tab-generators").setAttribute("aria-selected", false);
  el("tab-executions").setAttribute("aria-selected", false);
  el("tab-results").setAttribute("aria-selected", tab === "results");
  el("steps").style.display = tab === "setup" ? "" : "none";
  if (tab === "landing") renderLanding();
  else tab === "setup" ? renderStep() : renderResults();
}
function gotoStep(id) { S.step = id; renderSteps(); renderStep(); }

function copyDemoCommand(button) {
  const command = "spreadex demo";
  const copied = () => {
    button.textContent = "Copied";
    setTimeout(() => { button.textContent = "Copy command"; }, 1400);
  };
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(command).then(copied).catch(() => {});
  }
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
              onclick="toggleTip(event, this)">${ICONS.info}</button>
      <span class="sc-tip" role="tooltip" id="tip-${c.n}">${c.tip}</span>
      <h3 class="sc-title">${c.title}</h3>
      <p>${c.body}</p>
    </div>`;

  el("view").innerHTML = `
    <section class="landing dashboard-home" aria-labelledby="landing-title">
      <div class="landing-hero">
        <div class="landing-intro">
          <p class="eyebrow">LOCAL TESTING WORKBENCH</p>
          <div class="hero-title-row">
            ${BRAND_MARK}
            <h1 id="landing-title">SpreadEx <span>Workbench</span></h1>
          </div>
          <p class="landing-lede">Test compilers, interpreters, parsers, and other
            program-processing systems from one local workbench.</p>
          <div class="hero-actions">
            <button class="hero-action primary landing-primary" onclick="go('setup')"
                    ${readOnly ? "disabled" : ""}>
              <span class="ha-icon">${ICONS.playSolid}</span>
              <span class="ha-text"><strong>Set up my system</strong></span>
              <span class="ha-end">${ICONS.arrow}</span>
            </button>
            <button class="hero-action quick-demo" onclick="showDemoHint()">
              <span class="ha-icon qd-icon">${ICONS.book}</span>
              <span class="ha-text"><strong>Quick demo</strong>
                <small>See a real run in ~20 seconds</small></span>
              <span class="ha-end"></span>
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

function showDemoHint() {
  // The demo is a terminal command, not a thing the browser can start: it
  // writes a project to the working directory and runs a real campaign.
  const holder = el("demo-hint");
  if (!holder) return;
  holder.innerHTML = holder.innerHTML
    ? ""
    : `<div class="note">A real campaign against a hundred-line system under test with one
         documented bug. In a terminal:<pre>spreadex demo</pre>Then reload this page.</div>`;
}


function renderSteps() {
  const host = el("steps");
  // The row is rebuilt on every step change, which would snap a scrolled row
  // back to the start; carry its position across.
  const before = host.querySelector(".steps-row")?.scrollLeft || 0;

  host.innerHTML = `<ol class="steps-row">${STEPS.map((s, i) => `
    <li class="step-item tone-${s.tone}">
      <button type="button" class="step" onclick="gotoStep('${s.id}')"
              ${s.id === S.step ? 'aria-current="step"' : ""}>
        <span class="n">${s.n}</span>
        <span class="step-card">
          <span class="step-ico">${ICONS[s.icon]}</span>
          <span class="step-text"><span class="t">${esc(s.t)}</span><span class="d">${esc(s.d)}</span></span>
        </span>
      </button>${i < STEPS.length - 1 ? '<span class="step-link" aria-hidden="true"></span>' : ""}
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
  if ((c.generation?.mode || "time") === "time" && !c.generation?.count) {
    lines.push("", "generation:", "  mode: time",
               `  per_generator: ${c.generation.per_generator || "30s"}`);
  } else if (c.generation?.count) {
    lines.push("", "generation:", `  count: ${c.generation.count}`);
  }
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
    el("view").innerHTML = `<div class="card"><div class="note bad">${esc(e.message || e)}</div></div>`;
  });
}

// ------------------------------------------------- step 1: system under test

// Presets only prefill the command and the example shown on the right; the
// user's text is never overwritten once they have typed something of their own.
const SUT_KINDS = [
  { id: "cli",    t: "Executable",     d: "A compiled program or binary", icon: "terminal",
    cmd: "./your-parser {input}" },
  { id: "jar",    t: "Java / JVM",     d: "JAR, class or JVM-based program", icon: "book",
    cmd: "java -jar your-tool.jar {input}" },
  { id: "script", t: "Script / Runtime", d: "Python, Node.js, Ruby and more", icon: "doc",
    cmd: "python3 your_parser.py {input}" },
  { id: "other",  t: "Custom command", d: "Any command that runs your program", icon: "gear",
    cmd: "" },
];

const SUT_EXAMPLES = [
  { id: "jar",    t: "Java (Rhino)", code: "java -jar rhino-all.jar {input}" },
  { id: "python", t: "Python",       code: "python3 your_parser.py {input}" },
  { id: "node",   t: "Node.js",      code: "node parse.js {input}" },
  { id: "other",  t: "Custom",       code: "./run-my-tool.sh {input}" },
];

const SUT_TIPS = [
  "Use the exact command you would type in a terminal.",
  "Keep {input} where the test file path should go.",
  "Use absolute paths if the command lives outside this project.",
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
  S.probeShowDetails = false;
  stepSut();
}

function toggleProbeDetails() { stashSut(); S.probeShowDetails = !S.probeShowDetails; stepSut(); }

function sutResult() {
  const r = S.probe;
  if (!r) return "";
  const check = `<span class="res-ico" aria-hidden="true">${ICONS.check}</span>`;
  if (r.pending) return `<div class="res note" role="status">Running it once&hellip;</div>`;
  if (!r.ok) {
    return `<div class="res bad" role="alert"><span class="res-ico" aria-hidden="true">${ICONS.alert}</span>
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
        <p class="why">Tell SpreadEx how to run the program you want to test.</p></div>
    </header>

    <section class="sut-sec" aria-labelledby="sut-q">
      <h4 id="sut-q">How do you run your program?</h4>
      <div class="sut-kinds" role="radiogroup" aria-labelledby="sut-q">
        ${SUT_KINDS.map(k => `<button type="button" role="radio" class="sut-kind ${d.kind === k.id ? "on" : ""}"
          aria-checked="${d.kind === k.id}" onclick="pickSutKind('${k.id}')">
          <span class="sk-ico" aria-hidden="true">${ICONS[k.icon]}</span>
          <span class="sk-t">${k.t}</span><span class="sk-d">${k.d}</span>
          <span class="sk-ok" aria-hidden="true">${ICONS.check}</span></button>`).join("")}
      </div>
    </section>

    <section class="sut-sec">
      <div class="sut-lab"><label for="sut-cmd">Execution command</label>
        <button type="button" class="sut-help" aria-label="SpreadEx runs this command once per generated input. Quote any argument that contains a space."
          title="SpreadEx runs this once per generated input. Quote any argument that contains a space.">${ICONS.info}</button>
        <span class="sut-pill"><code>{input}</code> will be replaced with each generated test file</span></div>
      <input id="sut-cmd" class="sut-cmd" type="text" spellcheck="false" autocomplete="off"
        value="${esc(d.command)}" placeholder="${esc((SUT_KINDS.find(k => k.id === d.kind) || {}).cmd || "your-command {input}")}">
      ${d.extra.map((x, i) => `<div class="sut-extra">
        <input class="x-name" type="text" value="${esc(x.name)}" aria-label="Name of implementation ${i + 2}">
        <input class="x-cmd sut-cmd" type="text" spellcheck="false" value="${esc(x.command)}" aria-label="Command for implementation ${i + 2}" placeholder="another-implementation {input}">
        <button type="button" class="ghost small" onclick="dropSutExtra(${i})" aria-label="Remove">&times;</button></div>`).join("")}
      <div class="sut-compare"><button type="button" class="linkish" onclick="addSutExtra()">Compare another implementation</button>
        <span class="muted">Two or more lets SpreadEx test them against each other &mdash; no expected output needed.</span></div>
    </section>

    <div class="sut-test-row">
      <button type="button" id="sut-test" class="primary" onclick="verifyCommand()">${ICONS.playSolid} Test connection</button>
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
      <button type="button" class="primary" onclick="commitSut()">Continue to Inputs ${ICONS.arrow}</button>
    </div>
   </div>

   <aside class="sut-side" aria-label="Help">
    <div class="side-card">
      <h4>What happens here?</h4>
      <p>SpreadEx runs your program once for every generated input, then watches how it behaves &mdash; exit code, output and time &mdash; to find the inputs worth a closer look.</p>
    </div>
    <div class="side-card">
      <h4>Examples</h4>
      <div class="ex-tabs" role="tablist">${SUT_EXAMPLES.map(x => `<button type="button" role="tab"
        aria-selected="${x.id === ex.id}" class="${x.id === ex.id ? "on" : ""}" onclick="sutExampleTab('${x.id}')">${x.t}</button>`).join("")}</div>
      <div class="ex-code"><code>${esc(ex.code)}</code>
        <button type="button" class="ex-copy" onclick="copyExample(this)" aria-label="Copy command">${ICONS.copy}</button></div>
    </div>
    <div class="side-card">
      <h4>Tips</h4>
      <ul class="tips-list">${SUT_TIPS.map(t => `<li><span aria-hidden="true">${ICONS.check}</span>${esc(t)}</li>`).join("")}</ul>
    </div>
   </aside>
  </div>`;
}

function commitSut() {
  const r = readSut();
  el("err").innerHTML = "";
  if (r.problem) { showSutProblem(r); return; }
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
}

async function stepGrammar(current = () => true) {
  el("view").innerHTML = `<div class="card"><div class="empty">Looking for grammars…</div></div>`;
  const { grammars } = await api("/api/files");
  if (!current()) return;   // the user moved on while this was loading
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
      ${S.project?.experimental
        ? `<button class="ghost" onclick="toggleAssistant()">Help me write one</button>`
        : ""}
      <button class="primary" onclick="commitGrammar()">Continue</button>
    </div>
    ${S.project?.experimental ? "" : `<div class="note">
      No grammar yet? SpreadEx can ask a model to draft one from examples and then check its
      answer against your inputs before offering it. That is the one feature that sends anything
      off this machine, it has no evaluation behind it, and it is off by default:
      <span class="mono">spreadex ui --experimental</span>.</div>`}
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

async function stepGenerators(current = () => true) {
  el("view").innerHTML = `<div class="card"><div class="empty">Checking generators…</div></div>`;
  const { generators } = await api("/api/generators");
  if (!current()) return;
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

async function stepRun(current = () => true) {
  const c = cfg();
  if (!c.generation) c.generation = { mode: "time", per_generator: "30s" };
  el("view").innerHTML = `
  <div class="card">
    <h3>Budget</h3>
    <p class="why">SpreadEx spends what you give it and no more. Generation and execution are
      budgeted separately, because they fail in different ways.</p>
    <div class="row">
      <div><label for="bgen">Generation</label><input id="bgen" type="text" value="${esc(c.budget?.generation || "1m")}"></div>
      <div><label for="bexec">Execution</label><input id="bexec" type="text" value="${esc(c.budget?.execution || "1m")}"></div>
      <div><label for="genmode">How generators are compared</label>
        <select id="genmode" onchange="redrawBudget()">
          <option value="time" ${(c.generation?.mode || "time") === "time" ? "selected" : ""}>Equal time &mdash; recommended</option>
          <option value="count" ${(c.generation?.mode || "time") !== "time" ? "selected" : ""}>Equal number of inputs</option>
        </select></div>
      ${(c.generation?.mode || "time") === "time"
        ? `<div><label for="pergen">Seconds per generator</label>
             <input id="pergen" type="text" value="${esc(c.generation?.per_generator || "30s")}"></div>`
        : `<div><label for="count">Inputs per generator</label>
             <input id="count" type="number" min="1" value="${c.generation?.count || 200}"></div>`}
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
    <div class="note">${(c.generation?.mode || "time") === "time"
      ? `<strong>Equal time</strong> gives every generator the same number of seconds, so the
         comparison answers "who makes better use of a budget". They will produce different
         numbers of inputs &mdash; that is the measurement, not a flaw. Note that cluster
         coverage is computed over the pooled inputs, so a much faster generator contributes
         more of that pool and scores higher partly for that reason; the results say so when
         it happens.`
      : `<strong>Equal number of inputs</strong> is reproducible and is what the ICST&nbsp;2026
         experiments used, but it is not resource-fair: on this project's own JavaScript
         grammar the same 150 inputs cost Fandango 2.5&thinsp;s and ISLa 44.8&thinsp;s. Prefer
         equal time when you are deciding where budget should go.`}</div>
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
  ["bgen", "bexec", "count", "pergen", "signal", "model"].forEach(id =>
    el(id) && el(id).addEventListener("change", refreshPreview));
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
    ${row("Generators compared", (c.generation?.mode === "time")
        ? `by equal time &mdash; ${esc(c.generation.per_generator || "30s")} each`
        : `by equal input count &mdash; ${c.generation?.count || 200} each, `
          + `<span class="muted">which is reproducible but not resource-fair</span>`)}
    ${row("Ordered by", (c.selection_signal === "random")
        ? "random (the baseline)" : "cluster coverage, most different first")}
  </table>`;
}

function redrawBudget() { collectRunConfig(); stepRun(); }

function collectRunConfig() {
  S.config.budget = { generation: el("bgen").value, execution: el("bexec").value };
  // The two modes are mutually exclusive on purpose: a config carrying both a
  // count and a time budget does not say which one was honoured.
  const mode = el("genmode") ? el("genmode").value : (cfg().generation?.mode || "count");
  S.config.generation = mode === "time"
    ? { mode: "time", per_generator: (el("pergen") && el("pergen").value) || "30s" }
    : { count: Number(el("count") && el("count").value) || 200 };
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

const RESULT_TABS = [
  { id: "overview",   t: "Overview"   },
  { id: "generators", t: "Generators" },
  { id: "budget",     t: "Budget"     },
  { id: "failures",   t: "Failures"   },
  { id: "corpus",     t: "Corpus"     },
];

function pickResultTab(id) { S.rtab = id; paintRun(); }

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

  // run_detail shuffles the corpus 200 times for the random baseline, so it is
  // fetched once per run and the tabs read from what came back.
  try { S.detail = await api(`/api/runs/${encodeURIComponent(S.current)}`); }
  catch (e) { el("detail").innerHTML = `<div class="card bad">${esc(e.message)}</div>`; return; }
  paintRun();
}

function paintRun() {
  const d = S.detail;
  if (!d) return;
  const body = ({ overview: tabOverview, generators: tabGenerators, budget: tabBudget,
                  failures: tabFailures, corpus: tabCorpus }[S.rtab] || tabOverview)(d);
  el("detail").innerHTML = `
    <div class="rtabs" role="tablist">${RESULT_TABS.map(t => `
      <button role="tab" aria-selected="${(S.rtab || "overview") === t.id}"
        onclick="pickResultTab('${t.id}')">${t.t}${t.id === "failures" && d.signatures.length
          ? ` <span class="tag ${d.signatures.length ? "bad" : ""}">${d.signatures.length}</span>` : ""}</button>`).join("")}
    </div>${body}`;
}

function failingCount(d) {
  const v = d.verdicts || {};
  return (v.crash || 0) + (v.timeout || 0) + (v.divergence || 0);
}

// --------------------------------------------------------------- overview

function tabOverview(d) {
  const ver = d.verdicts || {}, failing = failingCount(d);
  return `
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
  <div class="card">
    <h3>What happened</h3>
    <p class="why">${failing
      ? `SpreadEx executed ${num(d.executed)} inputs and ${num(failing)} did something worth
         looking at, across ${d.signatures.length} distinct signature(s). The
         <strong>Failures</strong> tab has them.`
      : `SpreadEx executed ${num(d.executed)} inputs and nothing crashed, hung or diverged.
         For a mature system under test that is the expected outcome, not a missing measurement
         &mdash; the <strong>Budget</strong> tab shows how far the campaign actually got.`}</p>
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

// ------------------------------------------------------------- generators

function tabGenerators(d) {
  if (!d.generators.length) {
    return `<div class="card"><div class="empty">This campaign used existing inputs, so there is
      no generator to compare.</div></div>`;
  }
  const costs = d.generators.map(g => g.cost_s).filter(c => c > 0);
  const spread = costs.length > 1 ? Math.max(...costs) / Math.min(...costs) : 1;
  return `<div class="card">
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
    ${(d.corpus.signal_caveats || []).map(c =>
      `<div class="note warn">${esc(c)}</div>`).join("")}
    <div class="note">Cluster coverage is measured against <em>this</em> pool. Add or remove a
      generator and every score moves, so compare these numbers within a campaign, never across
      campaigns.</div>
  </div>`;
}

// ----------------------------------------------------------------- budget

function tabBudget(d) {
  return `<div class="card">
    <h3>Budget curve</h3>
    <p class="why">Distinct failure signatures against inputs executed. The dashed line is the same
      inputs in random order, so the gap is what the ordering bought &mdash; and no gap is a real
      answer too.</p>
    ${budgetChart(d.budget_curve, d.random_curve, d.executed)}
  </div>`;
}

// --------------------------------------------------------------- failures

function tabFailures(d) {
  return `<div class="card">
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
      <div class="holder"></div></details>`).join("") : `<div class="empty">Nothing crashed, hung or
      diverged in this run.<br><span class="muted">That is a result, not a gap.</span></div>`}
  </div>`;
}

// ----------------------------------------------------------------- corpus

function tabCorpus(d) {
  const c = d.corpus || {};
  const row = (k, v, why) => v === null || v === undefined ? "" :
    `<tr><th>${k}</th><td class="mono" style="width:70px">${num(v)}</td>
       <td class="muted">${why}</td></tr>`;
  return `<div class="card">
    <h3>The corpus this campaign drew on</h3>
    <p class="why">Inputs are stored once, by content, so the same input produced by two generators
      or re-seen in a later version is one blob with several execution records.</p>
    <table class="summary"><tbody>
      ${row("Generated", c.generated, "written by the generators, before any filtering")}
      ${row("Valid", c.valid, "kept after the generator's own validity check")}
      ${row("Prioritized", c.prioritized, "ordered for execution by the selection signal")}
      ${row("Executed", d.executed, "actually run before the execution budget ran out")}
      ${row("Clusters", c.k_eff, "found by the shared clustering, which is what CC is measured over")}
    </tbody></table>
    ${c.prioritized && d.executed < c.prioritized ? `<div class="note">The execution budget ran out
      after ${num(d.executed)} of ${num(c.prioritized)} inputs. The rest are still in the corpus and
      a longer budget picks up where this one stopped.</div>` : ""}
    <pre>spreadex export ${esc(d.run_id)}</pre>
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
    // The project path used to sit in the header, competing with the menu. It
    // is one hover away in the badge instead.
    const badge = el("local-badge");
    badge.title = `Running locally for ${S.project.root}\n\n${badge.title}`;
    const conf = await api("/api/config");
    S.config = conf.parsed || {};
    S.draft = null;
    await loadRuns();
    renderSteps();
    go(initialView(S.project, S.runs));
  } catch (e) {
    const noToken = !TOKEN || /token/i.test(e.message);
    el("view").innerHTML = noToken
      ? `<div class="card"><h3>This tab has no access token</h3>
          <p class="why">The token is handed over once in the URL and kept only for this tab, so a
          fresh tab has to be opened from the link SpreadEx printed.</p><pre>spreadex ui</pre></div>`
      : `<div class="card"><div class="note bad">${esc(e.message)}</div></div>`;
  }
})();
