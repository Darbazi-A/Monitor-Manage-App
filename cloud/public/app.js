"use strict";
// Stage Cloud's dashboard, phone first: bottom tabs on a phone, a sidebar on a computer.
// Halls at a glance, one hall live (with pictures of its screens), its remote desk (the hall's own
// phone page, its requests carried over a WebSocket), the journal, people and my account.

const $ = id => document.getElementById(id);
const app = $("app");
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
let me = null;
let live = null;                 // the open hall's WebSocket
let timers = [];                 // the page's own intervals, stopped when it changes
const ui = { filter: "all", search: "" };
const ROLES = ["viewer", "operator", "admin"];
const can = role => ROLES.indexOf(me?.role) >= ROLES.indexOf(role);
const every = (ms, fn) => timers.push(setInterval(() => { if (!document.hidden) fn(); }, ms));

// -- icons (24 px, stroked) ----------------------------------------------------------------------------- //
const ICONS = {
  halls: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
  journal: '<path d="M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01"/>',
  people: '<path d="M16 20v-1.5a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4V20"/><circle cx="9.5" cy="7.5" r="3.5"/><path d="M21 20v-1.5a4 4 0 0 0-3-3.87M16 4.13a3.5 3.5 0 0 1 0 6.75"/>',
  account: '<circle cx="12" cy="8" r="4"/><path d="M4 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1"/>',
  back: '<path d="m15 18-6-6 6-6"/>', plus: '<path d="M12 5v14M5 12h14"/>', search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  remote: '<rect x="6" y="2" width="12" height="20" rx="3"/><path d="M12 18h.01M9 6h6"/>',
  message: '<path d="M21 12a8 8 0 0 1-11.8 7L4 20l1.1-4.6A8 8 0 1 1 21 12z"/>',
  update: '<path d="M21 12a9 9 0 0 1-15.5 6.2M3 12a9 9 0 0 1 15.5-6.2"/><path d="M18 2v4h-4M6 22v-4h4"/>',
  download: '<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>', more: '<circle cx="5" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/>',
  play: '<path d="M7 4v16l13-8z"/>', alert: '<path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>',
  cpu: '<rect x="5" y="5" width="14" height="14" rx="2"/><path d="M9 1v4M15 1v4M9 19v4M15 19v4M1 9h4M1 15h4M19 9h4M19 15h4"/>',
  disk: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>', volume: '<path d="M11 5 6 9H2v6h4l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M19 5a10 10 0 0 1 0 14"/>',
  phone: '<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>', laptop: '<rect x="4" y="5" width="16" height="11" rx="1.5"/><path d="M2 20h20"/>',
  layers: '<path d="m12 2 10 5-10 5L2 7z"/><path d="m2 17 10 5 10-5M2 12l10 5 10-5"/>', lock: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>', key: '<circle cx="7.5" cy="15.5" r="4.5"/><path d="m10.7 12.3 9.8-9.8M17 6l3 3M14.5 8.5l2 2"/>',
  trash: '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/>', out: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>', eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  wifioff: '<path d="M2 2l20 20M8.5 16.4a5 5 0 0 1 7 0M5 12.9a10 10 0 0 1 5.2-2.8M19 12.9a10 10 0 0 0-2.3-1.6M2 8.8a15 15 0 0 1 4.2-2.6M22 8.8A15 15 0 0 0 10.7 5M12 20h.01"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
};
const icon = (name, size = "") => `<svg class="i ${size}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ""}</svg>`;

// -- talking to the cloud ------------------------------------------------------------------------------- //
async function call(path, body) {
  const options = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(path, options);
  let data = {};
  try { data = await r.json(); } catch (e) { /* none */ }
  if (r.status === 401 && path !== "/api/login" && path !== "/api/password") { me = null; route(); throw new Error("signed out"); }
  return { status: r.status, ok: r.ok && data.ok !== false, data };
}

function toast(text, bad) {
  const el = $("toast");
  el.textContent = t(text);
  el.classList.toggle("bad", !!bad);
  el.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.remove("show"), 3200);
}

function ago(ms) {
  if (!ms) return t("never");
  const s = Math.max(0, (Date.now() - ms) / 1000);
  if (s < 60) return t("just now");
  if (s < 3600) return tf("{0} min ago", Math.floor(s / 60));
  if (s < 86400) return tf("{0} h ago", Math.floor(s / 3600));
  return tf("{0} d ago", Math.floor(s / 86400));
}
const hhmm = ms => new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
function dayName(ms) {
  const d = new Date(ms), today = new Date();
  const days = Math.round((new Date(today.toDateString()) - new Date(d.toDateString())) / 86400000);
  if (days === 0) return t("Today");
  if (days === 1) return t("Yesterday");
  return d.toLocaleDateString(lang === "ka" ? "ka-GE" : undefined, { day: "numeric", month: "long", year: today.getFullYear() === d.getFullYear() ? undefined : "numeric" });
}
const initials = name => String(name || "?").trim().split(/\s+/).map(w => w[0]).join("").slice(0, 2).toUpperCase();
const isOnline = h => h.online && Date.now() - (h.lastSeen || 0) < 180000;

// -- sheets (from below on a phone, a dialog on a computer) ------------------------------------------------ //
function sheet(html, wire) {
  const scrim = document.createElement("div");
  scrim.className = "scrim";
  scrim.innerHTML = `<div class="sheet" role="dialog" aria-modal="true"><div class="grab"></div>${html}</div>`;
  document.body.appendChild(scrim);
  const close = () => { scrim.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = e => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", onKey);
  scrim.addEventListener("click", e => { if (e.target === scrim) close(); });
  scrim.querySelectorAll("[data-close]").forEach(b => b.addEventListener("click", close));
  wire?.(scrim, close);
  setTimeout(() => scrim.querySelector("input:not([readonly]), textarea")?.focus(), 60);
  return close;
}
function ask(title, text, yes, danger) {
  return new Promise(resolve => sheet(`<h2>${esc(title)}</h2><p class="sub">${esc(text)}</p>
      <div class="buttons"><button class="btn" data-close>${esc(t("Cancel"))}</button>
      <button class="btn ${danger ? "danger" : "primary"}" id="yes">${esc(yes)}</button></div>`,
    (box, close) => {
      box.querySelector("#yes").onclick = () => { close(); resolve(true); };
      box.querySelectorAll("[data-close]").forEach(b => b.addEventListener("click", () => resolve(false)));
    }));
}

// -- theme ------------------------------------------------------------------------------------------- //
function applyTheme() {
  let theme = "auto";
  try { theme = localStorage.getItem("stageCloudTheme") || "auto"; } catch (e) { /* */ }
  if (theme === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", theme);
  return theme;
}
applyTheme();

// -- the shell ---------------------------------------------------------------------------------------- //
function navItems() {
  const items = [["halls", "#/", "Halls", "halls"]];
  if (can("operator")) items.push(["journal", "#/journal", "Journal", "journal"]);
  if (can("admin")) items.push(["people", "#/people", "People", "people"]);
  items.push(["account", "#/account", "Account", "account"]);
  return items;
}
function shell(active, title, body, options = {}) {
  const items = navItems();
  app.innerHTML = `<div class="shell">
    <aside class="side"><div class="brand"><div class="logo">${icon("halls", "s")}</div>Stage Cloud</div>
      ${items.map(([key, href, name, ico]) => `<a class="nav ${key === active ? "on" : ""}" href="${href}">${icon(ico)}${esc(t(name))}</a>`).join("")}
      <div class="foot"><div class="me"><div class="avatar">${esc(initials(me.name))}</div><div class="grow"><b>${esc(me.name)}</b>
        <small>${esc(t(me.role))}</small></div><button class="btn ghost icon" id="out" title="${esc(t("Sign out"))}">${icon("out")}</button></div></div></aside>
    <div class="main"><div class="topbar">${options.back ? `<a class="btn ghost icon" href="${options.back}" aria-label="${esc(t("Back"))}">${icon("back")}</a>` : ""}
        <h1>${esc(title)}</h1>${options.actions || ""}</div>
      <div class="content">${body}</div></div>
    <nav class="tabs">${items.map(([key, href, name, ico]) => `<a href="${href}" class="${key === active ? "on" : ""}"><span class="pill-ico">${icon(ico)}</span>${esc(t(name))}</a>`).join("")}</nav>
  </div>`;
  $("out")?.addEventListener("click", signOut);
}
async function signOut() {
  await call("/api/logout", {});
  me = null;
  location.hash = "#/";
  route();
}

async function route() {
  timers.forEach(clearInterval);
  timers = [];
  window.onmessage = null;
  if (live && !location.hash.startsWith("#/hall/" + live.hallId)) { live.close(); live = null; }
  if (!me) {
    try { const r = await fetch("/api/me"); if (r.ok) me = await r.json(); } catch (e) { /* offline */ }
  }
  if (!me) return signIn();
  const parts = location.hash.replace(/^#\/?/, "").split("/");
  if (parts[0] === "hall" && parts[1]) return parts[2] === "desk" ? remoteDesk(parts[1]) : hallPage(parts[1]);
  if (parts[0] === "journal" && can("operator")) return journalPage();
  if (parts[0] === "people" && can("admin")) return peoplePage();
  if (parts[0] === "account") return accountPage();
  return hallsPage();
}
window.addEventListener("hashchange", route);

// -- signing in, and the very first administrator ----------------------------------------------------- //
function langSeg() {
  return `<div class="seg">${["ka", "en"].map(l => `<button type="button" class="${lang === l ? "on" : ""}" data-lang="${l}">${l === "ka" ? "ქართ" : "EN"}</button>`).join("")}</div>`;
}
function wireLang(root = document) {
  root.querySelectorAll("[data-lang]").forEach(b => b.onclick = () => { setLang(b.dataset.lang); route(); });
}

async function signIn() {
  let setup = false;
  try { setup = (await (await fetch("/api/setup")).json()).needed; } catch (e) { /* */ }
  app.innerHTML = `<div class="auth-page"><div class="auth card">
    <div class="row" style="justify-content:space-between"><div class="brand"><div class="logo">${icon("halls", "s")}</div>Stage Cloud</div>${langSeg()}</div>
    <h1>${esc(t(setup ? "First administrator" : "Welcome"))}</h1>
    <p class="sub">${esc(t(setup ? "A new Stage Cloud: make its first administrator with the setup key." : "Every hall's Stage Display Controller, in one place."))}</p>
    <form id="f">${setup ? `<label class="field"><span>${esc(t("Setup key"))}</span><input id="key" autocomplete="off" autocapitalize="off" spellcheck="false" required></label>` : ""}
      <label class="field"><span>${esc(t("Name"))}</span><input id="name" autocomplete="username" autocapitalize="off" required></label>
      <label class="field"><span>${esc(t(setup ? "Password (8 or more characters)" : "Password"))}</span>
        <input id="pw" type="password" autocomplete="${setup ? "new-password" : "current-password"}" required ${setup ? 'minlength="8"' : ""}></label>
      <div class="error" id="err"></div>
      <button class="btn primary block" id="go">${esc(t(setup ? "Make it" : "Sign in"))}</button></form></div></div>`;
  wireLang();
  (setup ? $("key") : $("name")).focus();
  $("f").onsubmit = async e => {
    e.preventDefault();
    $("go").disabled = true;
    const name = $("name").value.trim(), password = $("pw").value;
    try {
      if (setup) {
        const r = await call("/api/setup", { key: $("key").value.trim(), name, password });
        if (!r.ok) { $("err").textContent = t(r.data.message || "That did not work."); return; }
      }
      const r = await call("/api/login", { name, password });
      if (!r.ok) { $("err").textContent = t(r.data.message || "That did not work."); return; }
      me = { name: r.data.name, role: r.data.role };
      route();
    } finally { if ($("go")) $("go").disabled = false; }
  };
}

// -- every hall ------------------------------------------------------------------------------------- //
function needsAttention(h) {
  const sum = h.summary || {};
  return h.paired && (!isOnline(h) || (sum.problems || []).length > 0 || sum.update?.state === "ready");
}
function statusBadge(h) {
  if (!h.paired) return `<span class="badge warn">${esc(t("not paired yet"))}</span>`;
  return isOnline(h) ? `<span class="badge ok"><span class="dot"></span>${esc(t("online"))}</span>`
    : `<span class="badge"><span class="dot"></span>${esc(tf("offline · {0}", ago(h.lastSeen)))}</span>`;
}
function screensMini(screens, on) {
  return `<div class="screens-mini">${(screens || []).map(s => `<div class="smini">
    <span class="mon ${s.kind === "strip" ? "strip" : ""} ${on && s.open ? "on" : ""}"></span><span class="nm ell">${esc(s.name)}</span>
    <span class="ell grow">${!on ? "" : s.open ? esc(s.what || t("black / nothing")) : `<span class="muted">${esc(t("closed"))}</span>`}</span></div>`).join("")}</div>`;
}
function nowLine(sum) {
  if (sum?.slides) return `<div class="now">${icon("layers", "s")}<div class="grow"><b>${esc(sum.slides.name)}</b>
    <div class="sub">${esc(tf("slide {0} of {1}", sum.slides.index, sum.slides.count))}${sum.slides.live ? " · " + esc(t("live")) : ""}</div></div></div>`;
  if (sum?.show?.name && sum.show.step > 0) return `<div class="now">${icon("play", "s")}<div class="grow"><b>${esc(sum.show.title || sum.show.name)}</b>
    <div class="sub">${esc(sum.show.name)} · ${esc(tf("step {0}/{1}", sum.show.step, sum.show.steps))}</div></div></div>`;
  return "";
}
function problemsLine(sum) {
  const problems = sum?.problems || [];
  if (!problems.length) return "";
  return `<div class="alert">${icon("alert", "s")}<div class="grow">${esc(problems[0])}${problems.length > 1 ? ` <span style="opacity:.75">${esc(tf("+{0} more", problems.length - 1))}</span>` : ""}</div></div>`;
}
function updateBadge(sum) {
  const u = sum?.update || {};
  if (u.state === "ready") return `<span class="badge brand">${icon("download", "s")}${esc(tf("update {0} ready", u.version))}</span>`;
  if (u.state === "downloading") return `<span class="badge">${esc(tf("downloading {0}", u.version))}</span>`;
  return "";
}

function hallCard(h) {
  const sum = h.summary || {}, on = isOnline(h);
  const desk = on && can("operator") && sum.control !== false;
  return `<article class="card hall ${on ? "" : "offline"}" data-id="${esc(h.id)}">
    <div class="hall-head"><div class="hall-ico">${icon(on ? "halls" : "wifioff")}</div>
      <div class="grow"><h3 class="ell">${esc(h.name)}</h3><div class="row" style="margin-top:4px;gap:6px">${statusBadge(h)}</div></div></div>
    ${h.paired ? screensMini(sum.screens, on) : `<p class="sub" style="margin:0">${esc(t("Waiting for the hall's computer: Settings → Cloud, address and code."))}</p>`}
    ${on ? nowLine(sum) : ""}${problemsLine(sum)}
    <div class="hall-foot">${sum.version ? `<span class="badge">v${esc(sum.version)}</span>` : ""}${updateBadge(sum)}
      ${sum.locked ? `<span class="badge warn">${icon("lock", "s")}${esc(t("desk locked"))}</span>` : ""}
      ${sum.control === false ? `<span class="badge" title="${esc(t("remote desk off"))}">${icon("eye", "s")}</span>` : ""}
      <span class="grow"></span>${desk ? `<button class="btn primary small" data-desk="${esc(h.id)}">${icon("remote", "s")}${esc(t("Control"))}</button>` : ""}</div>
  </article>`;
}

async function hallsPage() {
  shell("halls", t("Halls"), `<div id="stats"></div><div class="toolbar" id="tools"></div><div id="list"><div class="halls">
      <div class="skeleton"></div><div class="skeleton"></div></div></div>
    ${can("admin") ? `<button class="btn primary fab mobile-only" id="addm">${icon("plus")}${esc(t("Add a hall"))}</button>` : ""}`,
    { actions: can("admin") ? `<button class="btn primary desk-only" id="add">${icon("plus")}${esc(t("Add a hall"))}</button>` : "" });
  $("add")?.addEventListener("click", addHall);
  $("addm")?.addEventListener("click", addHall);
  let halls = [];
  const draw = () => {
    if (!$("list")) return;
    const online = halls.filter(isOnline).length, attention = halls.filter(needsAttention).length;
    $("stats").innerHTML = halls.length ? `<div class="stats">
      <button class="stat ${ui.filter === "all" ? "on" : ""}" data-filter="all"><b>${halls.length}</b><span>${esc(t("all halls"))}</span></button>
      <button class="stat ok ${ui.filter === "online" ? "on" : ""}" data-filter="online"><b>${online}</b><span>${esc(t("online"))}</span></button>
      <button class="stat ${attention ? "warn" : ""} ${ui.filter === "attention" ? "on" : ""}" data-filter="attention"><b>${attention}</b><span>${esc(t("need attention"))}</span></button></div>` : "";
    $("stats").querySelectorAll("[data-filter]").forEach(b => b.onclick = () => { ui.filter = ui.filter === b.dataset.filter ? "all" : b.dataset.filter; draw(); });
    if (halls.length > 4 && !$("q")) {
      $("tools").innerHTML = `<label class="search">${icon("search", "s")}<input id="q" type="search" placeholder="${esc(t("Find a hall…"))}" value="${esc(ui.search)}"></label>`;
      $("q").oninput = () => { ui.search = $("q").value; draw(); };
    }
    const q = ui.search.trim().toLowerCase();
    const shown = halls.filter(h => (ui.filter === "all" || (ui.filter === "online" ? isOnline(h) : needsAttention(h)))
      && (!q || h.name.toLowerCase().includes(q) || (h.summary?.computer || "").toLowerCase().includes(q)));
    if (!halls.length) {
      $("list").innerHTML = `<div class="card empty"><div class="hall-ico">${icon("halls", "l")}</div><h3>${esc(t("No halls yet"))}</h3>
        <p>${esc(t(can("admin") ? "Add a hall here, then type its code in the hall's program: Settings → Cloud." : "An administrator adds the halls."))}</p>
        ${can("admin") ? `<button class="btn primary" id="add2">${icon("plus")}${esc(t("Add a hall"))}</button>` : ""}</div>`;
      $("add2")?.addEventListener("click", addHall);
      return;
    }
    $("list").innerHTML = shown.length ? `<div class="halls">${shown.map(hallCard).join("")}</div>`
      : `<div class="card empty"><p>${esc(t("No hall matches."))}</p></div>`;
    $("list").querySelectorAll(".hall").forEach(c => c.onclick = e => {
      const deskButton = e.target.closest("[data-desk]");
      location.hash = deskButton ? `#/hall/${c.dataset.id}/desk` : `#/hall/${c.dataset.id}`;
    });
  };
  const load = async () => { try { halls = (await call("/api/halls")).data || []; draw(); } catch (e) { /* signed out */ } };
  await load();
  every(15000, load);
}

function showCode(name, code) {
  sheet(`<h2>${esc(tf("Pair “{0}”", name))}</h2>
    <ol class="steps"><li>${esc(t("On the hall's computer open Stage Display Controller → Settings → Cloud."))}</li>
      <li>${esc(t("Type the address and the code below, then Pair."))}</li></ol>
    <label class="field" style="margin-top:14px"><span>${esc(t("Address"))}</span><div class="copy"><input readonly value="${esc(location.host)}" id="addr">
      <button class="btn icon" id="cpa" title="${esc(t("Copy"))}">${icon("copy")}</button></div></label>
    <div class="field"><span>${esc(t("Code"))}</span><div class="code">${esc(code)}</div></div>
    <p class="muted" style="margin:0;font-size:13px">${esc(t("The code works once, for 30 minutes."))}</p>
    <div class="buttons"><button class="btn primary" data-close>${esc(t("Done"))}</button></div>`, box => {
    box.querySelector("#cpa").onclick = () => navigator.clipboard?.writeText(location.host).then(() => toast("Copied."));
  });
}

function addHall() {
  sheet(`<h2>${esc(t("Add a hall"))}</h2><p class="sub">${esc(t("Give it a name everyone knows - you get a code for its computer."))}</p>
    <form id="f"><label class="field"><span>${esc(t("The hall's name"))}</span><input id="n" maxlength="60" required placeholder="${esc(t("e.g. Assembly hall"))}"></label>
    <div class="error" id="err"></div><div class="buttons"><button type="button" class="btn" data-close>${esc(t("Cancel"))}</button>
    <button class="btn primary">${esc(t("Add"))}</button></div></form>`, (box, close) => {
    box.querySelector("#f").onsubmit = async e => {
      e.preventDefault();
      const name = box.querySelector("#n").value.trim();
      const r = await call("/api/halls", { name });
      if (!r.ok) { box.querySelector("#err").textContent = t(r.data.message || "That did not work."); return; }
      close();
      showCode(name, r.data.code);
      route();
    };
  });
}

// -- one hall, live --------------------------------------------------------------------------------- //
class Live {
  constructor(hallId, onMessage) {
    this.hallId = hallId; this.onMessage = onMessage; this.seq = 0; this.pending = new Map(); this.closed = false; this.tries = 0;
    this.open();
  }
  open() {
    this.ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/halls/${this.hallId}/live`);
    this.ws.onopen = () => { this.tries = 0; this.onMessage({ t: "socket", on: true }); };
    this.ws.onmessage = e => {
      let m; try { m = JSON.parse(e.data); } catch (x) { return; }
      if (m.t === "reply" && this.pending.has(m.id)) { this.pending.get(m.id)(m); this.pending.delete(m.id); return; }
      this.onMessage(m);
    };
    this.ws.onclose = () => {
      for (const [, resolve] of this.pending) resolve({ status: 503, type: "application/json", body: '{"ok":false,"message":"disconnected"}' });
      this.pending.clear();
      if (this.closed) return;
      this.onMessage({ t: "socket", on: false });
      setTimeout(() => !this.closed && this.open(), Math.min(15000, 1000 * 2 ** this.tries++));
    };
  }
  ready() { return this.ws.readyState === 1; }
  rpc(method, path, params, body) {
    return new Promise(resolve => {
      if (!this.ready()) return resolve({ status: 503, type: "application/json", body: '{"ok":false,"message":"disconnected"}' });
      const id = ++this.seq;
      this.pending.set(id, resolve);
      this.ws.send(JSON.stringify({ t: "rpc", id, method, path, params, body }));
      setTimeout(() => { if (this.pending.delete(id)) resolve({ status: 504, type: "application/json", body: '{"ok":false,"message":"no answer"}' }); }, 30000);
    });
  }
  close() { this.closed = true; try { this.ws.close(); } catch (e) { /* */ } }
}

const MESSAGES = ["The event starts in 10 minutes.", "Please check the microphones.", "Please open the stage screens.",
  "Please call me.", "The next speaker is ready."];

async function hallPage(id) {
  const r = await call("/api/halls/" + id);
  if (!r.ok) { location.hash = "#/"; return; }
  let hall = r.data, log = hall.log || [], journal = null, pictures = {}, picturesOff = false;
  shell("halls", hall.name, `<div id="hall"></div>`, {
    back: "#/", actions: can("admin") ? `<button class="btn ghost icon" id="more" aria-label="${esc(t("More"))}">${icon("more")}</button>` : "" });
  $("more")?.addEventListener("click", () => adminMenu(hall, () => { $("hall") && draw(); }));

  const draw = () => {
    const out = $("hall");
    if (!out) return;
    const st = hall.status || {}, sum = st.summary || {}, d = st.detail || {}, pc = d.pc || {};
    const on = !!hall.online, desk = on && can("operator") && sum.control !== false;
    const ready = sum.update?.state === "ready";
    const kv = (ico, label, value) => `<div>${icon(ico)}<div class="grow"><small>${esc(t(label))}</small><b title="${esc(value)}">${esc(value)}</b></div></div>`;
    out.innerHTML = `<section class="hero"><div class="hero-top"><div class="hall-ico">${icon(on ? "halls" : "wifioff", "l")}</div>
        <div class="grow"><div class="row" style="gap:6px">${statusBadge({ ...hall, online: on, lastSeen: hall.lastSeen })}
          ${sum.version ? `<span class="badge">v${esc(sum.version)}</span>` : ""}${updateBadge(sum)}</div>
          <div class="sub" style="margin-top:6px">${esc(sum.computer || hall.computer || "")}${sum.control === false ? " · " + esc(t("remote desk off")) : ""}</div></div></div>
      ${can("operator") ? `<div class="actions">
        <button class="action primary" id="desk" ${desk ? "" : "disabled"}>${icon("remote")}${esc(t("Control"))}</button>
        <button class="action" id="msg" ${on ? "" : "disabled"}>${icon("message")}${esc(t("Message"))}</button>
        <button class="action" id="upd" ${on ? "" : "disabled"}>${icon(ready ? "download" : "update")}${esc(t(ready ? "Install" : "Update"))}
          ${ready ? `<span class="tag">${esc(sum.update.version)}</span>` : ""}</button>
        <button class="action" id="lk" ${on ? "" : "disabled"}>${icon("lock")}${esc(t(sum.locked ? "Unlock" : "Lock"))}</button></div>` : ""}</section>
      <div class="cols"><div>
        <div class="section-title"><h2>${esc(t("On the stage now"))}</h2>${on && !picturesOff ? `<span class="badge ok"><span class="dot"></span>${esc(t("live"))}</span>` : ""}</div>
        ${(sum.screens || []).length ? `<div class="stage">${sum.screens.map(s => `<div class="card tile ${s.kind === "strip" ? "strip" : ""}">
          <div class="pic" data-role="${esc(s.role)}">${on && s.open && pictures[s.role] ? `<img alt="" src="${pictures[s.role]}">`
            : esc(!on ? t("offline") : !s.open ? t("closed") : picturesOff ? t("pictures need the remote desk") : t("…"))}</div>
          <div class="meta"><span class="mon-dot badge ${on && s.open ? "ok" : ""}" style="height:22px;padding:0 8px"><span class="dot"></span></span>
            <div class="grow"><b class="ell" style="display:block">${esc(s.name)}</b><span class="sub ell" style="display:block">${s.open ? esc(s.what || t("black / nothing")) : esc(t("closed"))}</span></div></div>
        </div>`).join("")}</div>` : `<div class="card pad muted">${esc(t("No status yet."))}</div>`}
        ${nowLine(sum) ? `<div style="margin-top:12px">${nowLine(sum)}</div>` : ""}
        <div class="section-title"><h2>${esc(t("Problems and events"))}</h2></div>
        ${(sum.problems || []).map(p => `<div class="alert" style="margin-bottom:8px">${icon("alert", "s")}<div class="grow">${esc(p)}</div></div>`).join("")}
        <div class="card feed">${log.length ? log.slice(0, 12).map(e => `<div><time>${esc(hhmm(e.at))}</time><div class="grow">${esc(e.text)}</div></div>`).join("")
          : `<div class="muted">${esc(t("Nothing so far."))}</div>`}</div>
      </div><div>
        <div class="section-title"><h2>${esc(t("Computer"))}</h2></div>
        <div class="kv">${kv("clock", "Last status", ago(hall.lastSeen))}${kv("cpu", "On for", pc.uptime_h != null ? tf("{0} h", pc.uptime_h) : "—")}
          ${kv("disk", "Free disk", pc.disk_free_gb != null ? pc.disk_free_gb + " GB" : "—")}${kv("volume", "Sound", d.sound ? `${d.sound.device} · ${d.sound.master}%` : "—")}
          ${kv("phone", "Phone remote", d.phone ? (d.phone.on ? tf("on · {0} phone(s)", d.phone.phones) : t("off")) : "—")}
          ${kv("laptop", "Laptops", d.share ? (d.share.on ? tf("on · {0}", d.share.laptops) : t("off")) : "—")}
          ${kv("layers", "Scene", d.preset || "—")}${kv("globe", "Windows", pc.os || "—")}</div>
        ${can("operator") ? `<div class="section-title"><h2>${esc(t("Journal"))}</h2></div><div class="card feed">${journal === null ? `<div class="muted">…</div>`
          : journal.length ? journal.slice(0, 10).map(j => `<div><time>${esc(hhmm(j.at))}</time><div class="grow"><span class="who">${esc(j.user)}</span> · ${esc(jt(j.what))}</div></div>`).join("")
          : `<div class="muted">${esc(t("Nothing so far."))}</div>`}</div>` : ""}
      </div></div>`;
    $("desk")?.addEventListener("click", () => location.hash = `#/hall/${id}/desk`);
    $("msg")?.addEventListener("click", () => messageSheet(id));
    $("upd")?.addEventListener("click", () => updateAction(id, sum));
    $("lk")?.addEventListener("click", async () => {
      if (sum.locked) { if (await ask(t("Unlock the desk?"), t("The hall's computer opens again without the PIN."), t("Unlock"))) window.hallCommand("unlock_desk"); }
      else if (await ask(t("Lock the desk?"), t("The hall's computer needs the admin PIN; the stage, the phone remote and the clicker keep working."), t("Lock"))) window.hallCommand("lock_desk");
    });
  };

  const command = async (cmd, args) => {
    const x = await call(`/api/halls/${id}/command`, { cmd, args });
    toast(x.data.message || (x.ok ? "Done." : "That did not work."), !x.ok);
    return x.ok;
  };
  window.hallCommand = command;

  // pictures of the screens, every few seconds, while the page is open and the hall allows it
  const refreshPictures = async () => {
    const sum = hall.status?.summary || {};
    if (!live?.ready() || !hall.online || sum.control === false) return;
    for (const s of (sum.screens || []).filter(x => x.open)) {
      const answer = await live.rpc("GET", "/api/screen", { role: s.role }, null);
      if (answer.status === 403) { picturesOff = true; draw(); return; }
      if (answer.status === 200 && answer.b64) {
        pictures[s.role] = `data:${answer.type};base64,${answer.b64}`;
        const box = document.querySelector(`.pic[data-role="${CSS.escape(s.role)}"]`);
        if (box) box.innerHTML = `<img alt="" src="${pictures[s.role]}">`;
      }
    }
  };
  draw();
  if (can("operator")) call(`/api/halls/${id}/journal`).then(x => { journal = x.data || []; draw(); }).catch(() => {});
  live?.close();
  live = new Live(id, m => {
    if (m.t === "hello") { hall = { ...hall, status: m.status, online: m.online, lastSeen: m.lastSeen }; log = m.log || []; draw(); refreshPictures(); }
    else if (m.t === "status") { hall.status = m.status; hall.lastSeen = m.at; hall.online = true; draw(); }
    else if (m.t === "online") { hall.online = m.online; draw(); }
    else if (m.t === "event") { log.unshift(m); draw(); }
  });
  every(4000, refreshPictures);
  every(30000, draw);
}

function messageSheet(id) {
  sheet(`<h2>${esc(t("Message for the operator"))}</h2><p class="sub">${esc(t("It opens on the hall's desk and by its clock, with your name."))}</p>
    <div class="chips">${MESSAGES.map(m => `<button class="chip" type="button">${esc(t(m))}</button>`).join("")}</div>
    <form id="f"><textarea id="text" maxlength="500" placeholder="${esc(t("Write a message…"))}" required></textarea>
    <div class="buttons"><button type="button" class="btn" data-close>${esc(t("Cancel"))}</button>
    <button class="btn primary">${icon("message", "s")}${esc(t("Send"))}</button></div></form>`, (box, close) => {
    box.querySelectorAll(".chip").forEach(c => c.onclick = () => { box.querySelector("#text").value = c.textContent; box.querySelector("#text").focus(); });
    box.querySelector("#f").onsubmit = async e => {
      e.preventDefault();
      const text = box.querySelector("#text").value.trim();
      if (text && await window.hallCommand("message", { text })) close();
    };
  });
}

async function updateAction(id, sum) {
  if (sum.update?.state === "ready") {
    if (await ask(tf("Install version {0}?", sum.update.version),
      t("The program closes, installs and opens again - about a minute with the stage screens dark."), t("Install now")))
      window.hallCommand("install_update", { now: true });
  } else {
    window.hallCommand("check_update");
  }
}

function adminMenu(hall, done) {
  sheet(`<h2>${esc(hall.name)}</h2><div class="menu" style="margin-top:8px">
    <button id="rn">${icon("edit")}${esc(t("Rename"))}</button>
    <button id="pa">${icon("key")}${esc(t("Pair again (new code)"))}</button>
    <button id="rm" class="danger">${icon("trash")}${esc(t("Remove the hall"))}</button></div>`, (box, close) => {
    box.querySelector("#rn").onclick = () => { close(); sheet(`<h2>${esc(t("Rename"))}</h2><form id="f">
      <label class="field"><span>${esc(t("The hall's name"))}</span><input id="n" maxlength="60" value="${esc(hall.name)}" required></label>
      <div class="buttons"><button type="button" class="btn" data-close>${esc(t("Cancel"))}</button><button class="btn primary">${esc(t("Save"))}</button></div></form>`,
      (b2, c2) => { b2.querySelector("#f").onsubmit = async e => { e.preventDefault(); const name = b2.querySelector("#n").value.trim();
        const x = await call(`/api/halls/${hall.id}/rename`, { name }); if (x.ok) { c2(); hall.name = name; toast("Saved."); route(); } else toast(x.data.message, true); }; }); };
    box.querySelector("#pa").onclick = async () => {
      close();
      if (!await ask(t("Pair again"), t("A new code: the computer that pairs with it becomes this hall, and the one paired now loses its access."), t("Make a code"))) return;
      const x = await call(`/api/halls/${hall.id}/pair`, {});
      if (x.ok) showCode(hall.name, x.data.code); else toast(x.data.message, true);
    };
    box.querySelector("#rm").onclick = async () => {
      close();
      if (!await ask(t("Remove the hall"), tf("Remove “{0}” from Stage Cloud? Its computer is disconnected for good (it can be paired again as a new hall).", hall.name), t("Remove"), true)) return;
      const x = await call(`/api/halls/${hall.id}/remove`, {});
      if (x.ok) { toast("Removed."); location.hash = "#/"; } else toast(x.data.message, true);
    };
  });
}

// -- the remote desk: the hall's phone page, its requests over the WebSocket ---------------------------- //
// Inside the frame (an opaque origin: the hall's page cannot reach this dashboard), fetch and the
// upload's XMLHttpRequest are handed to the dashboard, and localStorage is kept in memory.
const SHIM = `<style>html{scrollbar-width:none}::-webkit-scrollbar{display:none}</style><script>(function(){
  var pending={},seq=0;
  addEventListener("message",function(e){var m=e.data;if(e.source===parent&&m&&m.sdcReply&&pending[m.id]){pending[m.id](m);delete pending[m.id];}});
  function ask(method,url,body){return new Promise(function(res){var id=++seq;pending[id]=res;parent.postMessage({sdcRpc:true,id:id,method:method,url:url,body:body},"*");});}
  var mem={stagePin:"0000"};
  var store={getItem:function(k){return k in mem?mem[k]:null},setItem:function(k,v){mem[k]=String(v)},removeItem:function(k){delete mem[k]},
    clear:function(){mem={}},key:function(i){return Object.keys(mem)[i]||null},get length(){return Object.keys(mem).length}};
  try{Object.defineProperty(window,"localStorage",{value:store,configurable:true});}catch(e){}
  try{Object.defineProperty(window,"sessionStorage",{value:store,configurable:true});}catch(e){}
  function answer(m){var type=m.type||"application/json";var data;
    if(m.b64!=null){var bin=atob(m.b64),bytes=new Uint8Array(bin.length);for(var i=0;i<bin.length;i++)bytes[i]=bin.charCodeAt(i);data=new Blob([bytes],{type:type});}
    else data=m.body==null?"":m.body;
    return new Response(data,{status:m.status||200,headers:{"Content-Type":type}});}
  var realFetch=window.fetch.bind(window);
  window.fetch=function(input,init){var url=typeof input==="string"?input:input.url;init=init||{};
    if(url.charAt(0)!=="/")return realFetch(input,init);
    return ask(init.method||"GET",url,init.body==null?null:String(init.body)).then(answer);};
  function b64(buf){var s="",b=new Uint8Array(buf);for(var i=0;i<b.length;i+=32768)s+=String.fromCharCode.apply(null,b.subarray(i,i+32768));return btoa(s);}
  var RealXHR=window.XMLHttpRequest;
  function Upload(){this.upload={};this.status=0;this.responseText="";this._h={};}
  Upload.prototype.open=function(m,u){this._url=u;};
  Upload.prototype.setRequestHeader=function(k,v){this._h[k.toLowerCase()]=v;};
  Upload.prototype.send=function(file){var x=this,name=decodeURIComponent(x._h["x-name"]||file.name||"file"),size=file.size,PIECE=512*1024;
    function fail(msg){x.status=500;x.responseText=JSON.stringify({ok:false,message:msg});if(x.onload)x.onload();}
    ask("POST","/api/upload?op=begin&name="+encodeURIComponent(name)+"&length="+size,null).then(function(m){
      var j={};try{j=JSON.parse(m.body||"{}")}catch(e){}
      if(!j.ok)return fail(j.message||"refused");var ticket=j.ticket,at=0;
      function next(){if(at>=size){return ask("POST","/api/upload?op=finish&ticket="+encodeURIComponent(ticket),null).then(function(m){
          x.status=m.status;x.responseText=m.body||"";if(x.onload)x.onload();});}
        return file.slice(at,at+PIECE).arrayBuffer().then(function(buf){
          return ask("POST","/api/upload?op=write&ticket="+encodeURIComponent(ticket),{b64:b64(buf)}).then(function(m){
            if(m.status!==200){var k={};try{k=JSON.parse(m.body||"{}")}catch(e){}return fail(k.message||"failed");}
            at+=buf.byteLength;if(x.upload.onprogress)x.upload.onprogress({loaded:at,total:size});return next();});});}
      return next();}).catch(function(){if(x.onerror)x.onerror();});};
  window.XMLHttpRequest=function(){var real=new RealXHR(),up=new Upload(),chosen=null;
    return new Proxy({},{get:function(_,k){if(k==="open")return function(m,u){chosen=String(u).indexOf("/api/upload")===0?up:real;return chosen.open.apply(chosen,arguments);};
      var o=chosen||real;var v=o[k];return typeof v==="function"?v.bind(o):v;},
      set:function(_,k,v){(chosen||real)[k]=v;if(!chosen){up[k]=v;}return true;}});};
})();<\/script>`;

async function remoteDesk(id) {
  const r = await call("/api/halls/" + id);
  if (!r.ok) { location.hash = "#/"; return; }
  const hall = r.data;
  app.innerHTML = `<div class="desk"><div class="topbar"><a class="btn ghost icon" href="#/hall/${esc(id)}" aria-label="${esc(t("Back"))}">${icon("back")}</a>
      <h1>${esc(hall.name)}</h1><span class="badge" id="conn"><span class="dot"></span><span id="connText">${esc(t("connecting…"))}</span></span></div>
    <div class="desk-body" id="stage"><div class="wait"><div class="spinner"></div>${esc(t("Connecting to the hall…"))}</div></div></div>`;
  let frame = null, loaded = false;
  const setConn = on => {
    $("conn")?.classList.toggle("ok", on);
    if ($("connText")) $("connText").textContent = t(on ? "connected" : "reconnecting…");
  };
  const say = text => { $("stage").innerHTML = `<div class="wait">${icon("wifioff", "l")}<div>${esc(t(text))}</div>
    <a class="btn" href="#/hall/${esc(id)}">${esc(t("Back"))}</a></div>`; };
  const load = async () => {
    const page = await live.rpc("GET", "/", { lang }, null);          // the remote desk in the website's language
    if (page.status !== 200) {
      let message = "The hall did not answer.";
      try { message = JSON.parse(page.body).message || message; } catch (e) { /* */ }
      return say(message);
    }
    loaded = true;
    frame = document.createElement("iframe");
    frame.setAttribute("sandbox", "allow-scripts allow-forms allow-modals");
    frame.setAttribute("title", t("Remote desk"));
    frame.srcdoc = page.body.replace(/<head>/i, "<head>" + SHIM);
    $("stage").innerHTML = "";
    $("stage").appendChild(frame);
  };
  live?.close();
  live = new Live(id, m => {
    if (m.t === "socket") setConn(m.on);
    if (m.t === "hello") { setConn(true); if (!m.online) say("The hall is not connected."); else if (!loaded) load(); }
    if (m.t === "online" && m.online && !loaded) load();
  });
  window.onmessage = async e => {
    const m = e.data;
    if (!frame || e.source !== frame.contentWindow || !m || !m.sdcRpc) return;
    const url = new URL(m.url, "http://hall");
    const params = Object.fromEntries(url.searchParams.entries());
    const answer = await live.rpc(m.method === "POST" ? "POST" : "GET", url.pathname, params, m.body);
    frame.contentWindow?.postMessage({ sdcReply: true, id: m.id, status: answer.status, type: answer.type, body: answer.body ?? null, b64: answer.b64 ?? null }, "*");
  };
}

// -- the journal ------------------------------------------------------------------------------------- //
async function journalPage() {
  shell("journal", t("Journal"), `<p class="sub" style="margin:0 0 4px">${esc(t("Who did what, and when."))}</p>
    <div class="toolbar" style="margin-top:12px"><select id="hf" style="max-width:320px"><option value="">${esc(t("All halls"))}</option></select></div><div id="j"></div>`);
  const [rows, halls] = await Promise.all([call("/api/journal").then(x => x.data || []), call("/api/halls").then(x => x.data || [])]);
  $("hf").innerHTML += halls.map(h => `<option value="${esc(h.id)}">${esc(h.name)}</option>`).join("");
  const draw = () => {
    const only = $("hf").value;
    const shown = rows.filter(j => !only || j.hall === only);
    if (!shown.length) { $("j").innerHTML = `<div class="card empty"><p>${esc(t("Nothing so far."))}</p></div>`; return; }
    let html = "", day = "";
    for (const j of shown) {
      const name = dayName(j.at);
      if (name !== day) { html += `${day ? "</div>" : ""}<div class="day">${esc(name)}</div><div class="card feed">`; day = name; }
      html += `<div><time>${esc(hhmm(j.at))}</time><div class="grow"><span class="who">${esc(j.user || "—")}</span>${j.hallName ? ` · <span class="muted">${esc(j.hallName)}</span>` : ""}
        <div class="sub">${esc(jt(j.what))}</div></div></div>`;
    }
    $("j").innerHTML = html + "</div>";
  };
  $("hf").onchange = draw;
  draw();
}

// -- people ----------------------------------------------------------------------------------------- //
async function peoplePage() {
  shell("people", t("People"), `<div class="roles">
      <div class="role-card">${icon("eye")}<div><b>${esc(t("viewer"))}</b><div class="sub">${esc(t("Sees every hall and what is on its screens."))}</div></div></div>
      <div class="role-card">${icon("remote")}<div><b>${esc(t("operator"))}</b><div class="sub">${esc(t("Also sends messages and updates, and runs halls from the remote desk."))}</div></div></div>
      <div class="role-card">${icon("shield")}<div><b>${esc(t("admin"))}</b><div class="sub">${esc(t("Also adds halls and people."))}</div></div></div></div>
    <div class="card people" id="u"></div>
    <button class="btn primary fab mobile-only" id="addm">${icon("plus")}${esc(t("Add a person"))}</button>`,
    { actions: `<button class="btn primary desk-only" id="add">${icon("plus")}${esc(t("Add a person"))}</button>` });
  const draw = async () => {
    const users = (await call("/api/users")).data || [];
    $("u").innerHTML = users.map(u => `<div><div class="avatar">${esc(initials(u.name))}</div>
      <div class="grow"><b class="ell" style="display:block">${esc(u.name)}${u.name === me.name ? ` <span class="badge brand" style="height:20px">${esc(t("you"))}</span>` : ""}</b>
        <select data-role="${esc(u.name)}" aria-label="${esc(t("Role"))}">${ROLES.map(r => `<option value="${r}" ${r === u.role ? "selected" : ""}>${esc(t(r))}</option>`).join("")}</select></div>
      <button class="btn ghost icon" data-menu="${esc(u.name)}" aria-label="${esc(t("More"))}">${icon("more")}</button></div>`).join("");
    document.querySelectorAll("[data-role]").forEach(s => s.onchange = async () => {
      const x = await call("/api/users", { op: "role", name: s.dataset.role, role: s.value }); toast(x.ok ? "Saved." : x.data.message, !x.ok); draw(); });
    document.querySelectorAll("[data-menu]").forEach(b => b.onclick = () => {
      const name = b.dataset.menu;
      sheet(`<h2>${esc(name)}</h2><div class="menu" style="margin-top:8px"><button id="pw">${icon("key")}${esc(t("New password"))}</button>
        <button id="rm" class="danger">${icon("trash")}${esc(t("Remove"))}</button></div>`, (box, close) => {
        box.querySelector("#pw").onclick = () => { close(); personForm(name, draw); };
        box.querySelector("#rm").onclick = async () => {
          close();
          if (!await ask(tf("Remove {0}?", name), t("They can no longer sign in."), t("Remove"), true)) return;
          const x = await call("/api/users", { op: "remove", name }); toast(x.ok ? "Removed." : x.data.message, !x.ok); draw();
        };
      });
    });
  };
  $("add").onclick = () => personForm(null, draw);
  $("addm").onclick = () => personForm(null, draw);
  draw();
}

function personForm(name, done) {
  const suggestion = Array.from(crypto.getRandomValues(new Uint8Array(10)), b => "abcdefghjkmnpqrstuvwxyz23456789"[b % 31]).join("");
  sheet(`<h2>${esc(name ? tf("New password for {0}", name) : t("Add a person"))}</h2>
    <p class="sub">${esc(t("Give them the password yourself; they can change it under Account."))}</p><form id="f">
    ${name ? "" : `<label class="field"><span>${esc(t("Name"))}</span><input id="n" maxlength="40" required autocapitalize="off"></label>
      <label class="field"><span>${esc(t("Role"))}</span><select id="r">${ROLES.map(r => `<option value="${r}" ${r === "operator" ? "selected" : ""}>${esc(t(r))}</option>`).join("")}</select></label>`}
    <label class="field"><span>${esc(t("Password (8 or more characters)"))}</span><div class="copy"><input id="p" type="text" minlength="8" required autocomplete="off" value="${suggestion}">
      <button type="button" class="btn icon" id="cp" title="${esc(t("Copy"))}">${icon("copy")}</button></div></label>
    <div class="error" id="err"></div><div class="buttons"><button type="button" class="btn" data-close>${esc(t("Cancel"))}</button>
    <button class="btn primary">${esc(t("Save"))}</button></div></form>`, (box, close) => {
    box.querySelector("#cp").onclick = () => navigator.clipboard?.writeText(box.querySelector("#p").value).then(() => toast("Copied."));
    box.querySelector("#f").onsubmit = async e => {
      e.preventDefault();
      const body = name ? { op: "password", name, password: box.querySelector("#p").value }
        : { op: "add", name: box.querySelector("#n").value.trim(), role: box.querySelector("#r").value, password: box.querySelector("#p").value };
      const x = await call("/api/users", body);
      if (!x.ok) { box.querySelector("#err").textContent = t(x.data.message || "That did not work."); return; }
      close(); toast("Saved."); done();
    };
  });
}

// -- my account --------------------------------------------------------------------------------------- //
function accountPage() {
  const theme = applyTheme();
  shell("account", t("Account"), `<div class="card pad"><div class="me"><div class="avatar" style="width:48px;height:48px;font-size:17px">${esc(initials(me.name))}</div>
      <div class="grow"><b style="font-size:17px">${esc(me.name)}</b><small>${esc(t(me.role))}</small></div></div></div>
    <div class="section-title"><h2>${esc(t("Look"))}</h2></div>
    <div class="card pad" style="display:grid;gap:14px">
      <div class="row"><span class="grow">${esc(t("Language"))}</span>${langSeg()}</div>
      <div class="row"><span class="grow">${esc(t("Theme"))}</span><div class="seg">${[["auto", "Auto"], ["light", "Light"], ["dark", "Dark"]]
        .map(([k, n]) => `<button type="button" class="${theme === k ? "on" : ""}" data-theme="${k}">${esc(t(n))}</button>`).join("")}</div></div></div>
    <div class="section-title"><h2>${esc(t("Change my password"))}</h2></div>
    <div class="card pad"><form id="f">
      <label class="field"><span>${esc(t("Password now"))}</span><input id="o" type="password" autocomplete="current-password" required></label>
      <label class="field"><span>${esc(t("New password (8 or more characters)"))}</span><input id="p" type="password" minlength="8" autocomplete="new-password" required></label>
      <div class="error" id="err"></div><button class="btn primary">${esc(t("Save"))}</button>
      <p class="muted" style="font-size:13px;margin:12px 0 0">${esc(t("Changing it signs you out everywhere."))}</p></form></div>
    <button class="btn block danger mobile-only" style="margin-top:22px" id="out2">${icon("out")}${esc(t("Sign out"))}</button>`);
  wireLang();
  document.querySelectorAll("[data-theme]").forEach(b => b.onclick = () => {
    try { localStorage.setItem("stageCloudTheme", b.dataset.theme); } catch (e) { /* */ }
    accountPage();
  });
  $("out2").onclick = signOut;
  $("f").onsubmit = async e => {
    e.preventDefault();
    const x = await call("/api/password", { old: $("o").value, password: $("p").value });
    if (!x.ok) { $("err").textContent = t(x.data.message || "That did not work."); return; }
    toast("Saved."); me = null; route();
  };
}

route();
