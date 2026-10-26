"""
The phone's page: the whole stage desk on a phone, for a teacher running an
assembly or a rehearsal - a home screen of big tiles, one page per job.

Served by remote.py at "/". Every word goes through t(); in Georgian the page
carries its dictionary (phone_ka.KA) and nothing else changes.
"""
from __future__ import annotations

import json


def render(lang: str) -> bytes:
    page = PAGE
    if lang == "ka":
        from phone_ka import KA
        page = page.replace('<html lang="en">', '<html lang="ka">')
        page = page.replace("/*LANG*/null", json.dumps(KA, ensure_ascii=False))
    return page.encode("utf-8")


PAGE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover">
<meta name="theme-color" content="#0c1018">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<link rel="manifest" href="/manifest.json">
<title>Stage remote</title>
<style>
:root { --bg:#0c1018; --card:#141a26; --raised:#1a2130; --well:#0f141e; --edge:#222b3c; --edge-hi:#2c3750;
  --text:#e9edf5; --dim:#9aa6bb; --muted:#6c7891; --gold:#e3b23c; --ok:#57c98a; --warn:#d9853f; --red:#e0605c; --blue:#7c9cf0; }
* { box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
html,body { margin:0; overflow-x:hidden; background:var(--bg); color:var(--text); font:15px/1.35 "Segoe UI",system-ui,-apple-system,Roboto,"Noto Sans Georgian",sans-serif; }
body { padding:env(safe-area-inset-top) 0 calc(84px + env(safe-area-inset-bottom)); min-height:100vh; }
button, input, select, textarea { font:inherit; color:inherit; }
button { border:1px solid var(--edge); background:linear-gradient(#212a3a,#182030); border-radius:14px;
  padding:13px 10px; touch-action:manipulation; cursor:pointer; }
button:active { transform:scale(.98); background:var(--well); }
button:disabled { opacity:.4; }
button.gold { color:#12161f; background:linear-gradient(#f2c556,var(--gold)); border-color:#c9992f; font-weight:800; }
button.danger { color:var(--red); background:transparent; border-color:rgba(224,96,92,.55); font-weight:700; }
button.ghost { background:transparent; }
button.on { border-color:var(--gold); color:var(--gold); background:rgba(227,178,60,.08); }
input[type=text], input[type=search], textarea, select { width:100%; background:var(--well); border:1px solid var(--edge);
  border-radius:12px; padding:12px; outline:none; }
input[type=text]:focus, textarea:focus { border-color:var(--gold); }
textarea { min-height:84px; resize:vertical; }
input[type=range] { width:100%; accent-color:var(--gold); height:30px; }
header { position:sticky; top:0; z-index:5; display:flex; align-items:center; gap:10px; padding:12px 14px 10px;
  background:rgba(12,16,24,.96); backdrop-filter:blur(8px); border-bottom:1px solid var(--edge); }
header .back { padding:6px 12px; border-radius:10px; font-size:18px; display:none; }
header.sub .back { display:block; }
header h1 { font-size:17px; margin:0; flex:1; min-width:0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
header .dot { width:10px; height:10px; border-radius:50%; background:var(--muted); flex:none; }
header .dot.on { background:var(--ok); box-shadow:0 0 10px var(--ok); }
header .clock { color:var(--dim); font-variant-numeric:tabular-nums; }
#rehearsal { display:none; margin:10px 14px 0; padding:10px 14px; border-radius:14px; border:1px solid var(--blue);
  color:var(--blue); background:rgba(124,156,240,.08); font-weight:700; align-items:center; gap:10px; }
#rehearsal.show { display:flex; }
#rehearsal span { flex:1; }
#rehearsal button { padding:8px 12px; color:var(--blue); border-color:var(--blue); background:transparent; }
main { padding:10px 14px 16px; }
.card { background:linear-gradient(var(--raised),var(--card) 55%); border:1px solid var(--edge); border-top-color:#313d55;
  border-radius:18px; padding:14px 16px; margin-bottom:12px; }
.cap { color:var(--muted); font-size:11px; font-weight:700; letter-spacing:1.2px; text-transform:uppercase; margin-bottom:6px; }
.hint { color:var(--dim); font-size:13px; }
.muted { color:var(--muted); }
.row { display:flex; gap:10px; }
.row > * { flex:1; min-width:0; }
.stack > * + * { margin-top:10px; }
.big { min-height:64px; font-size:19px; font-weight:800; letter-spacing:.5px; }
.huge { display:block; width:100%; min-height:20vh; font-size:30px; font-weight:800; letter-spacing:2px; border-radius:22px; }
.ell { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.empty { color:var(--muted); text-align:center; padding:16px 6px; }
.banner { padding:12px 14px; border-radius:14px; border:1px solid rgba(217,133,63,.5); background:rgba(217,133,63,.08);
  color:var(--warn); margin-bottom:12px; display:flex; gap:10px; align-items:center; }
.banner span { flex:1; }
.banner button { padding:9px 12px; }
/* home */
.mv { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:8px; margin-bottom:12px; }
.mv .t { position:relative; background:#05070b; border:1.5px solid var(--edge); border-radius:12px; overflow:hidden; aspect-ratio:16/9; }
.mv .t.top { grid-column:1 / span 2; aspect-ratio:14/1; }
.mv .t.live { border-color:var(--red); }
.mv .t.rehearsal { border-color:var(--blue); }
.mv .t.closed { border-style:dashed; }
.mv img { width:100%; height:100%; object-fit:contain; display:block; }
.mv .t.top img { object-fit:fill; }
.mv .lab, .mv .tag { position:absolute; top:5px; font-size:9px; font-weight:800; letter-spacing:.8px; text-shadow:0 1px 3px #000; }
.mv .lab { left:8px; color:#fff; }
.mv .tag { right:8px; color:var(--muted); }
.mv .t.live .tag { color:#ff8c88; }
.mv .t.rehearsal .tag { color:var(--blue); }
.mv .t.top .lab, .mv .t.top .tag { top:50%; transform:translateY(-50%); }
.now h2 { font-size:22px; margin:2px 0 4px; line-height:1.15; }
.tiles { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:10px; }
.tile { min-width:0; text-align:left; padding:14px 14px 12px; min-height:104px; border-radius:18px; display:flex; flex-direction:column; gap:4px; }
.tile .ico { font-size:26px; line-height:1; }
.tile b { font-size:15px; }
.tile small { color:var(--muted); font-size:12px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.tile.live small { color:var(--red); }
.tile.busy small { color:var(--gold); }
/* screen page */
.shot { background:#05070b; border:1.5px solid var(--edge); border-radius:14px; overflow:hidden; aspect-ratio:16/9; margin-bottom:10px; }
.shot.top { aspect-ratio:8/1; }
.shot.live { border-color:var(--red); }
.shot.rehearsal { border-color:var(--blue); }
.shot img { width:100%; height:100%; object-fit:contain; display:block; }
.time { display:flex; justify-content:space-between; color:var(--dim); font-variant-numeric:tabular-nums; font-size:13px; }
.toggles { display:flex; gap:8px; flex-wrap:wrap; }
.toggles button { flex:1; padding:11px 8px; font-size:14px; }
/* lists */
.list { list-style:none; margin:0; padding:0; }
.list li { display:flex; align-items:center; gap:10px; padding:10px 8px; border-radius:12px; border:1px solid transparent; }
.list li + li { margin-top:4px; }
.list li .n { width:30px; height:30px; flex:none; border-radius:50%; background:#232c3d; color:var(--dim);
  display:grid; place-items:center; font-size:13px; font-weight:700; }
.list li .t { flex:1; min-width:0; }
.list li .t b { display:block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.list li .t small { display:block; color:var(--muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.list li.now { background:#1d2533; border-color:rgba(227,178,60,.45); }
.list li.now .n { background:var(--gold); color:#12161f; }
.list li.sel { border-color:var(--gold); }
.list li .acts { display:none; gap:6px; }
.list li.sel .acts { display:flex; }
.list li .acts button { padding:8px 11px; border-radius:10px; }
.chips { display:flex; gap:8px; overflow-x:auto; padding-bottom:4px; margin-bottom:10px; scrollbar-width:none; }
.chips button { flex:none; padding:9px 14px; border-radius:999px; font-size:14px; }
.file { display:flex; align-items:center; gap:12px; padding:8px; border-radius:12px; }
.file + .file { margin-top:4px; }
.file:active { background:var(--well); }
.file .th { position:relative; width:72px; height:42px; flex:none; border-radius:8px; background:#05070b; display:grid; place-items:center;
  font-size:20px; overflow:hidden; border:1px solid var(--edge); }
.file .th img { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; }
.file .th img:not([src]) { display:none; }
.file .t { flex:1; min-width:0; }
.file .t b { display:block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; font-weight:600; }
.file .t small { color:var(--muted); }
.crumb { display:flex; align-items:center; gap:8px; margin-bottom:8px; color:var(--dim); font-size:13px; }
.crumb button { padding:7px 12px; border-radius:10px; }
.upload { position:relative; overflow:hidden; display:block; text-align:center; }
.upload input { position:absolute; inset:0; opacity:0; width:100%; height:100%; }
.bar { height:6px; border-radius:3px; background:var(--well); overflow:hidden; margin-top:6px; }
.bar i { display:block; height:100%; background:var(--gold); width:0; transition:width .2s; }
/* slides */
.slide { background:#05070b; border:1px solid var(--edge); border-radius:12px; aspect-ratio:16/9; overflow:hidden; display:grid; place-items:center; color:var(--muted); }
.slide img { width:100%; height:100%; object-fit:contain; }
.thumbs { display:grid; grid-template-columns:repeat(3,1fr); gap:6px; }
.thumbs button { padding:0; border-radius:8px; overflow:hidden; aspect-ratio:16/9; position:relative; background:#05070b; }
.thumbs button.cur { border:2px solid var(--gold); }
.thumbs img { width:100%; height:100%; object-fit:contain; }
.thumbs span { position:absolute; left:4px; bottom:2px; font-size:10px; font-weight:800; text-shadow:0 1px 2px #000; }
.status { font-weight:800; letter-spacing:1px; font-size:12px; }
.status.live { color:var(--red); } .status.black { color:var(--warn); } .status.off { color:var(--muted); }
/* sound */
.pads { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:8px; }
.pad { min-width:0; position:relative; text-align:left; min-height:74px; padding:10px 12px; }
.pad small { display:block; color:var(--muted); font-size:11px; font-weight:800; }
.pad span { display:block; font-size:13px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; padding-right:28px; }
.pad.playing { border-color:var(--ok); background:rgba(87,201,138,.14); }
.pad.playing small { color:var(--ok); }
.pad.paused { border-color:var(--gold); }
.pad .more { position:absolute; right:6px; top:6px; padding:4px 9px; border-radius:9px; font-size:15px; background:transparent; border-color:transparent; color:var(--dim); }
/* web */
.webshot { position:relative; background:#05070b; border:1.5px solid var(--edge); border-radius:12px; overflow:hidden; aspect-ratio:16/9; }
.webshot.stage { border-color:var(--red); }
.webshot img { width:100%; height:100%; object-fit:contain; display:block; }
.webshot .tap { position:absolute; width:26px; height:26px; margin:-13px 0 0 -13px; border-radius:50%; border:2px solid var(--gold); pointer-events:none; animation:tap .5s ease-out forwards; }
@keyframes tap { to { transform:scale(1.8); opacity:0; } }
.code { font-size:34px; font-weight:800; letter-spacing:8px; color:var(--gold); }
/* bottom bar */
.quick { position:fixed; left:0; right:0; bottom:0; z-index:6; display:flex; gap:8px; padding:8px 12px calc(8px + env(safe-area-inset-bottom));
  background:rgba(12,16,24,.96); border-top:1px solid var(--edge); backdrop-filter:blur(8px); }
.quick button { flex:1; padding:12px 6px; font-size:13px; font-weight:800; letter-spacing:.5px; }
.quick .blackout { flex:1.4; color:var(--red); border-color:rgba(224,96,92,.55); background:transparent; position:relative; overflow:hidden; }
.hold { position:relative; overflow:hidden; }
.hold::after { content:""; position:absolute; left:0; bottom:0; height:4px; width:0; background:currentColor; opacity:.8; }
.hold.holding::after { width:100%; transition:width var(--hold,700ms) linear; }
/* sheet, login, toast */
#shade { position:fixed; inset:0; background:rgba(0,0,0,.55); z-index:20; display:none; }
#shade.show { display:block; }
#sheet { position:fixed; left:0; right:0; bottom:0; z-index:21; background:var(--card); border-top:1px solid var(--edge-hi);
  border-radius:20px 20px 0 0; padding:16px 16px calc(16px + env(safe-area-inset-bottom)); max-height:86vh; overflow:auto;
  transform:translateY(105%); transition:transform .22s ease; }
#sheet.show { transform:none; }
#sheet h3 { margin:0 0 4px; font-size:17px; }
#sheet .sub { color:var(--dim); font-size:13px; margin-bottom:10px; }
#sheet .opts > button { display:block; width:100%; text-align:left; margin-top:8px; }
#sheet label { display:block; color:var(--dim); font-size:13px; margin:10px 0 4px; }
#login { position:fixed; inset:0; background:var(--bg); display:none; flex-direction:column; align-items:center; justify-content:center; gap:18px; z-index:30; }
#login.show { display:flex; }
#pin { font-size:40px; letter-spacing:18px; min-height:52px; font-weight:800; }
.pinpad { display:grid; grid-template-columns:repeat(3,84px); gap:12px; }
.pinpad button { height:72px; font-size:26px; font-weight:700; border-radius:50%; }
#msg { color:var(--red); min-height:20px; }
#toast { position:fixed; left:50%; bottom:96px; transform:translateX(-50%); z-index:40; background:var(--raised); border:1px solid var(--edge-hi);
  padding:10px 16px; border-radius:12px; opacity:0; transition:opacity .25s; pointer-events:none; max-width:90vw; text-align:center; }
#toast.show { opacity:1; }
#toast.bad { border-color:var(--red); }
</style></head>
<body>
<header id="head"><button class="back ghost" id="back">‹</button><h1 id="title">Stage remote</h1><div class="dot" id="dot"></div><div class="clock" id="clock"></div></header>
<div id="rehearsal"><span id="rehtext"></span><button id="rehend"></button></div>
<main id="view"></main>
<div class="quick"><button class="blackout hold" id="qblack"></button><button id="qundo"></button><button id="qsilence"></button></div>
<div id="shade"></div><div id="sheet"></div>
<div id="login"><div class="cap" id="logincap"></div><div id="pin"></div><div class="pinpad" id="pinpad"></div><div id="msg"></div></div>
<div id="toast"></div>

<script>
"use strict";
const L = /*LANG*/null;
const t = s => (L && L[s]) || s;
const tf = (s, ...a) => t(s).replace(/\{(\d)\}/g, (m, i) => a[+i] ?? "");
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const mmss = ms => { let s = Math.max(0, Math.floor(ms / 1000)); const h = Math.floor(s / 3600); s %= 3600;
  const m = Math.floor(s / 60), r = String(s % 60).padStart(2, "0"); return h ? `${h}:${String(m).padStart(2, "0")}:${r}` : `${m}:${r}`; };
const buzz = () => { if (navigator.vibrate) navigator.vibrate(15); };

let pin = localStorage.getItem("stagePin") || "";
if (/^#pin=\d{4}$/.test(location.hash)) { pin = location.hash.slice(5); localStorage.setItem("stagePin", pin); }   // the dashboard's QR code
if (location.hash) history.replaceState(null, "", location.pathname);
let state = null, failures = 0, typed = "", lastAct = 0, seenNotice = -1;
let stack = [{ v: "home" }];
const ui = { edit: false, sel: -1, files: { place: "up", dir: "" }, filesData: null, uploads: [] };

/* -- talking to the desk ------------------------------------------------------------- */
async function api(path, body) {
  const options = { headers: { "X-Pin": pin } };
  if (body) { options.method = "POST"; options.headers["Content-Type"] = "application/json"; options.body = JSON.stringify(body); }
  const r = await fetch(path, options);
  if (r.status === 401) { pin = ""; localStorage.removeItem("stagePin"); askPin(t("Wrong PIN")); throw new Error("pin"); }
  if (r.status === 429) { askPin(t("Too many tries - wait a minute")); throw new Error("locked"); }
  return r;
}
async function act(action, extra) {
  buzz(); lastAct = Date.now();
  try { const r = await api("/api/action", Object.assign({ action }, extra || {})); const j = await r.json();
        if (j.message) toast(j.message, !j.ok); return j; }
  catch (e) { return { ok: false }; }
  finally { setTimeout(refresh, 150); }
}
async function refresh() {
  if (!pin) { askPin(); return; }
  try { const r = await api("/api/state"); state = await r.json(); $("dot").classList.add("on"); failures = 0; draw(); }
  catch (e) { if (e.message !== "pin" && e.message !== "locked" && ++failures > 2) $("dot").classList.remove("on"); }
}
const pics = {};
async function pic(key, url, img) {
  if (pics[url] && pics[url].key === key) { if (img && img.src !== pics[url].src) img.src = pics[url].src; return; }
  if (pics[url] && pics[url].busy) return;
  pics[url] = Object.assign(pics[url] || {}, { busy: true });
  try { const r = await fetch(url, { headers: { "X-Pin": pin } }); if (!r.ok) { pics[url].busy = false; return; }
        const src = URL.createObjectURL(await r.blob()); if (pics[url].src) URL.revokeObjectURL(pics[url].src);
        pics[url] = { key, src, busy: false }; if (img && img.isConnected) img.src = src; }
  catch (e) { pics[url].busy = false; }
}

/* -- little helpers ---------------------------------------------------------------------- */
function toast(text, bad) { const el = $("toast"); el.textContent = text; el.classList.toggle("bad", !!bad); el.classList.add("show");
  clearTimeout(el._h); el._h = setTimeout(() => el.classList.remove("show"), 2600); }
function put(el, html) { if (typeof el === "string") el = $(el); if (el && el._html !== html) { el._html = html; el.innerHTML = html; } }
function role(r) { return (state && state.roles.find(x => x.role === r) || { label: r }).label; }
function screen(r) { return state && state.screens.find(s => s.role === r); }
function go(v, extra) { stack.push(Object.assign({ v }, extra || {})); ui.sel = -1; build(); window.scrollTo(0, 0); }
function back() { if (stack.length > 1) { stack.pop(); ui.sel = -1; build(); window.scrollTo(0, 0); } }
function cur() { return stack[stack.length - 1]; }
function hold(el, ms, fn, when) {
  // a button that must be held (BLACKOUT, ending a talk) - a brush of the thumb does nothing
  let timer = null; el.style.setProperty("--hold", ms + "ms");
  const start = e => { if (when && !when()) return; e.preventDefault(); el.classList.add("holding");
    timer = setTimeout(() => { el.classList.remove("holding"); timer = null; fn(); }, ms); };
  const stop = () => { if (timer) { clearTimeout(timer); timer = null; toast(t("Hold the button down")); } el.classList.remove("holding"); };
  el.addEventListener("pointerdown", start); el.addEventListener("pointerup", stop); el.addEventListener("pointerleave", stop); el.addEventListener("pointercancel", stop);
}

/* -- the sheet: choices, questions, confirmations ----------------------------------------- */
let sheetDone = null;
function closeSheet(value) { $("sheet").classList.remove("show"); $("shade").classList.remove("show"); const d = sheetDone; sheetDone = null; if (d) d(value); }
function openSheet(html) { $("sheet").innerHTML = html; $("sheet").classList.add("show"); $("shade").classList.add("show"); }
$("shade").onclick = () => closeSheet(null);
function choose(title, options, sub) {
  return new Promise(done => { sheetDone = done;
    openSheet(`<h3>${esc(title)}</h3>${sub ? `<div class="sub">${esc(sub)}</div>` : ""}<div class="opts">` +
      options.map((o, i) => `<button data-i="${i}" class="${o.cls || ""}" ${o.disabled ? "disabled" : ""}>${esc(o.label)}</button>`).join("") +
      `<button data-i="-1" class="ghost">${esc(t("Cancel"))}</button></div>`);
    $("sheet").querySelectorAll("[data-i]").forEach(b => b.onclick = () => { const i = +b.dataset.i; closeSheet(i < 0 ? null : options[i].value ?? i); });
  });
}
function confirmBox(title, sub, ok, danger) {
  return choose(title, [{ label: ok || t("Yes"), value: true, cls: danger ? "danger" : "gold" }], sub).then(v => v === true);
}
function ask(title, fields, ok) {
  return new Promise(done => { sheetDone = done;
    openSheet(`<h3>${esc(title)}</h3>` + fields.map((f, i) => `<label>${esc(f.label)}</label>` + (f.multi
        ? `<textarea id="f${i}" placeholder="${esc(f.hint || "")}">${esc(f.value || "")}</textarea>`
        : `<input type="text" id="f${i}" value="${esc(f.value || "")}" placeholder="${esc(f.hint || "")}" inputmode="${f.numeric ? "numeric" : "text"}">`)).join("") +
      `<div class="row" style="margin-top:14px"><button class="ghost" id="fno">${esc(t("Cancel"))}</button><button class="gold" id="fok">${esc(ok || t("OK"))}</button></div>`);
    const first = $("f0"); if (first) setTimeout(() => first.focus(), 250);
    $("fno").onclick = () => closeSheet(null);
    $("fok").onclick = () => closeSheet(fields.map((f, i) => $("f" + i).value));
  });
}

/* -- PIN ----------------------------------------------------------------------------- */
function askPin(message) { $("login").classList.add("show"); $("msg").textContent = message || ""; typed = ""; drawPin(); }
function drawPin() { $("pin").textContent = "····".split("").map((c, i) => i < typed.length ? "●" : "·").join(""); }
(function () { $("logincap").textContent = t("Enter the PIN shown on the dashboard");
  for (const k of ["1","2","3","4","5","6","7","8","9","","0","⌫"]) { const b = document.createElement("button"); b.textContent = k; if (!k) b.style.visibility = "hidden";
    b.onclick = () => { buzz(); if (k === "⌫") typed = typed.slice(0, -1); else if (typed.length < 4) typed += k; drawPin();
      if (typed.length === 4) { pin = typed; localStorage.setItem("stagePin", pin); $("login").classList.remove("show"); refresh(); } };
    $("pinpad").appendChild(b); } })();

/* -- the frame: header, rehearsal strip, quick bar ------------------------------------------ */
$("back").onclick = back;
$("qblack").textContent = t("BLACKOUT");
hold($("qblack"), 700, () => act("blackout"));
$("qundo").textContent = "↶ " + t("Undo");
$("qundo").onclick = () => act("undo");
$("qsilence").textContent = t("Stop sound");
$("qsilence").onclick = () => act("silence");
$("rehend").textContent = t("End");
$("rehend").onclick = () => act("rehearsal", { on: false });
setInterval(() => { $("clock").textContent = new Date().toTimeString().slice(0, 5); }, 1000);

const TITLES = { home: "Stage remote", screen: "", files: "Files", show: "Running order", slides: "Presentation",
  sound: "Sound", text: "Text on screen", web: "Canva and Kahoot", laptop: "Laptop", scenes: "Scenes", rehearsal: "Rehearsal",
  timer: "Timer" };
function frame() {
  const c = cur(); $("head").classList.toggle("sub", stack.length > 1);
  let title = c.v === "screen" ? role(c.role) : t(TITLES[c.v] || "");
  if (c.v === "home" && state && state.show.name) title = state.show.name;
  if (c.v === "files" && c.purpose) title = c.purpose.title || title;
  $("title").textContent = title;
  if (!state) return;
  $("rehearsal").classList.toggle("show", state.rehearsal.on);
  $("rehtext").textContent = t("REHEARSAL - the hall sees nothing of it");
  $("qundo").disabled = !state.undo;
  if (state.notice && state.notice.id !== seenNotice) {
    if (seenNotice >= 0 && state.notice.text) toast(state.notice.text, true);    // something asked for went wrong
    seenNotice = state.notice.id;
  }
}

/* -- views ---------------------------------------------------------------------------- */
const V = {};
function build() { const c = cur(); $("view").innerHTML = ""; $("view")._html = null; $("view").onclick = null; (V[c.v] || V.home).build(c); frame(); if (state) (V[c.v] || V.home).draw(c); }
function draw() { const c = cur(); frame(); (V[c.v] || V.home).draw(c); }

function mvHtml() { return `<div class="mv" id="mv">` + state.screens.map(sc =>
  `<div class="t ${sc.role === "top" ? "top" : ""}" id="mv-${sc.role}" data-go="${sc.role}"><img alt=""><span class="lab">${esc(sc.label)}</span><span class="tag"></span></div>`).join("") + `</div>`; }
function tag(stateName) { return ({ live: t("ON AIR"), black: t("BLACK"), closed: t("CLOSED"), rehearsal: t("REHEARSAL") })[stateName] || stateName; }
function drawMv() {
  const mv = $("mv"); if (!mv) return;
  for (const sc of state.screens) {
    const el = $("mv-" + sc.role); if (!el) continue;
    el.className = `t ${sc.role === "top" ? "top" : ""} ${sc.state}`;
    el.querySelector(".tag").textContent = tag(sc.state);
    const img = el.querySelector("img");
    if (sc.state === "closed") { img.removeAttribute("src"); continue; }
    pic(sc.version + (sc.moving ? ":" + Math.floor(Date.now() / 1500) : ""), `/api/screen?role=${sc.role}`, img);
  }
}

/* HOME */
V.home = {
  build() { $("view").innerHTML = `<div id="h-banner"></div><div id="h-mv"></div><div id="h-now"></div><div class="tiles" id="h-tiles"></div>`;
    $("view").onclick = e => { const g = e.target.closest("[data-go]"); if (g && g.closest("#mv")) go("screen", { role: g.dataset.go }); }; },
  draw() {
    const s = state;
    put("h-banner", s.outputs.open < 3 && s.outputs.can_open && !s.rehearsal.on
      ? `<div class="banner"><span>${esc(tf("{0} of 3 stage screens open", s.outputs.open))}</span><button id="openscr">${esc(t("Open them"))}</button></div>` : "");
    const ob = $("openscr"); if (ob) ob.onclick = () => act("screens_open");
    if (!$("mv")) put("h-mv", mvHtml());
    drawMv();
    const show = s.show, steps = show.steps, now = show.index >= 0 ? steps[show.index] : null, next = steps[show.index + 1];
    put("h-now", steps.length ? `<div class="card now"><div class="cap">${esc(now ? tf("Now · step {0} of {1}", show.index + 1, steps.length) : t("Ready"))}</div>
      <h2>${esc(now ? now.title : t("Press NEXT to start"))}</h2><div class="hint ell">${esc(next ? t("Next") + ": " + next.title : (now ? t("— end of the running order —") : ""))}</div>
      <div class="row" style="margin-top:10px"><button id="hback" ${show.index > 0 ? "" : "disabled"}>◀</button><button class="gold big" id="hnext" style="flex:3" ${next ? "" : "disabled"}>${esc(t("NEXT"))} ▶</button></div></div>` : "");
    const hn = $("hnext"); if (hn) { hn.onclick = () => act("next"); $("hback").onclick = () => act("back"); }
    const sl = s.slides, sh = s.share, web = s.web;
    const playing = s.cues.filter(c => c.playing).map(c => "F" + (c.index + 1));
    const tiles = [
      ["show", "📋", "Running order", steps.length ? tf("{0} steps", steps.length) : t("empty - build it here"), now ? "busy" : ""],
      ["slides", "🖼", "Presentation", sl.live ? tf("slide {0} of {1} · on screen", sl.index + 1, sl.count) : (sl.open ? sl.name : t("none open")), sl.live ? "live" : ""],
      ["files", "📁", "Files", t("send from this phone, or choose"), ""],
      ["sound", "🎵", "Sound", playing.length ? tf("playing: {0}", playing.join(", ")) : tf("volume {0}%", s.master), playing.length ? "busy" : ""],
      ["text", "🔤", "Text on screen", s.screens.some(x => x.text) ? t("text is showing") : t("names, titles, running text"), s.screens.some(x => x.text) ? "busy" : ""],
      ["web", "🌐", "Canva and Kahoot", web.where === "stage" ? t("on the Main Stage") : (web.where ? t("ready on the desk") : t("presentations and games")), web.where === "stage" ? "live" : ""],
      ["laptop", "💻", "Laptop", sh.waiting.length ? tf("{0} waiting", sh.waiting.length) : (sh.stage.length ? t("on the Main Stage") : (sh.running ? t("ready for laptops") : t("off"))), sh.waiting.length ? "busy" : (sh.stage.length ? "live" : "")],
      ["scenes", "⭐", "Scenes", s.preset ? tf("now: {0}", s.preset) : tf("{0} saved", s.presets.length), ""],
      ["rehearsal", "🎭", "Rehearsal", s.rehearsal.on ? t("ON - the hall sees nothing") : t("try everything out first"), s.rehearsal.on ? "busy" : ""],
      ["timer", "⏱", "Timer", s.timer.on ? s.timer.frame.text + " · " + role(s.timer.on) : (s.timer.running ? s.timer.frame.text : t("countdown on a screen")),
        s.timer.on ? "live" : (s.timer.running ? "busy" : "")],
    ];
    put("h-tiles", tiles.map(([v, ico, label, sub, cls]) =>
      `<button class="tile ${cls}" data-v="${v}"><span class="ico">${ico}</span><b>${esc(t(label))}</b><small>${esc(sub)}</small></button>`).join(""));
    $("h-tiles").onclick = e => { const b = e.target.closest("[data-v]"); if (b) go(b.dataset.v); };
  },
};

/* SCREEN */
V.screen = {
  build(c) { $("view").innerHTML = `<div class="shot ${c.role === "top" ? "top" : ""}" id="s-shot"><img id="s-img" alt=""></div>
    <div class="card"><div class="cap" id="s-state"></div><div class="ell" id="s-file" style="font-size:17px;font-weight:700"></div><div class="hint" id="s-text"></div></div>
    <div class="row" style="margin-bottom:12px"><button class="gold big" id="s-pick">📁 ${esc(t("Show a file"))}</button><button class="big" id="s-black">${esc(t("Black"))}</button></div>
    <div class="card" id="s-video"><div class="cap">${esc(t("Video"))}</div>
      <div class="row" style="margin-bottom:6px"><button id="s-restart">⏮</button><button id="s-play" style="flex:2"></button></div>
      <input type="range" id="s-seek" min="0" max="1000" value="0"><div class="time"><span id="s-pos">0:00</span><span id="s-dur">0:00</span></div>
      <div class="toggles" style="margin-top:10px"><button id="s-loop"></button><button id="s-mute"></button></div>
      <div class="cap" style="margin-top:12px">${esc(t("Volume"))}</div><input type="range" id="s-vol" min="0" max="100"></div>`;
    const r = c.role;
    $("s-pick").onclick = () => go("files", { purpose: { kind: "screen", role: r, title: tf("A file for {0}", role(r)) } });
    $("s-black").onclick = () => act("screen_black", { role: r });
    $("s-restart").onclick = () => act("screen_seek", { role: r, ms: 0 });
    $("s-play").onclick = () => { const sc = screen(r); act("screen_play", { role: r, on: !(sc && sc.playing) }); };
    $("s-loop").onclick = () => { const sc = screen(r); act("screen_loop", { role: r, on: !(sc && sc.loop) }); };
    $("s-mute").onclick = () => { const sc = screen(r); act("screen_mute", { role: r, on: !(sc && sc.muted) }); };
    const seek = $("s-seek"); seek.oninput = () => { seek._busy = true; const sc = screen(r); if (sc) $("s-pos").textContent = mmss(seek.value / 1000 * sc.duration); };
    seek.onchange = () => { const sc = screen(r); seek._busy = false; if (sc) act("screen_seek", { role: r, ms: Math.round(seek.value / 1000 * sc.duration) }); };
    const vol = $("s-vol"); vol.oninput = () => { vol._busy = true; }; vol.onchange = () => { vol._busy = false; act("screen_volume", { role: r, value: +vol.value }); };
  },
  draw(c) {
    const sc = screen(c.role); if (!sc) return;
    $("s-shot").className = `shot ${c.role === "top" ? "top" : ""} ${sc.state}`;
    if (sc.state !== "closed") pic(sc.version + (sc.moving ? ":" + Math.floor(Date.now() / 1000) : ""), `/api/screen?role=${c.role}`, $("s-img"));
    $("s-state").textContent = tag(sc.state);
    $("s-file").textContent = sc.open ? (sc.file || t("nothing - black")) : t("This screen is closed");
    $("s-text").textContent = sc.text ? t("Text on it") + ": " + sc.text.filter(Boolean).join(" — ") : "";
    $("s-black").disabled = !sc.open;
    $("s-video").style.display = sc.video && sc.open ? "" : "none";
    $("s-play").textContent = sc.playing ? "❚❚ " + t("Pause") : "▶ " + t("Play");
    $("s-loop").textContent = "🔁 " + (sc.loop ? t("Repeat: on") : t("Repeat: off")); $("s-loop").classList.toggle("on", sc.loop);
    $("s-mute").textContent = sc.muted ? "🔇 " + t("Sound: off") : "🔊 " + t("Sound: on"); $("s-mute").classList.toggle("on", !sc.muted);
    if (!$("s-seek")._busy) { $("s-seek").value = sc.duration ? Math.round(sc.position / sc.duration * 1000) : 0; $("s-pos").textContent = mmss(sc.position); }
    $("s-dur").textContent = mmss(sc.duration);
    if (!$("s-vol")._busy) $("s-vol").value = sc.volume;
  },
};

/* FILES */
const KIND_ICON = { video: "🎬", image: "🖼", audio: "🎵", deck: "📑" };
const KIND_NAME = { video: "video", image: "picture", audio: "sound", deck: "presentation" };
function size(n) { return n > 1e9 ? (n / 1e9).toFixed(1) + " GB" : n > 1e6 ? Math.round(n / 1e6) + " MB" : Math.max(1, Math.round(n / 1e3)) + " KB"; }
async function loadFiles() {
  try { const r = await api(`/api/files?place=${encodeURIComponent(ui.files.place)}&dir=${encodeURIComponent(ui.files.dir)}`);
        ui.filesData = await r.json(); ui.files.dir = ui.filesData.dir; ui.files.place = ui.filesData.place; drawFiles(); } catch (e) {}
}
function drawFiles() {
  const d = ui.filesData; if (!d || !$("f-list")) return;
  put("f-places", d.places.map(p => `<button data-place="${esc(p.key)}" class="${p.key === d.place ? "on" : ""}">${esc(p.name)}</button>`).join(""));
  put("f-crumb", d.dir ? `<button id="f-up">‹ ${esc(t("Up"))}</button><span class="ell">${esc(d.dir)}</span>` : "");
  const up = $("f-up"); if (up) up.onclick = () => { ui.files.dir = d.dir.split("/").slice(0, -1).join("/"); loadFiles(); };
  const purpose = cur().purpose;
  const wanted = purpose ? { screen: ["video", "image"], deck: ["deck", "image"], break: ["video"], cue: ["audio", "video"] }[purpose.kind] : null;
  const files = d.files.filter(f => !wanted || wanted.includes(f.kind));
  put("f-list", (d.folders.map(f => `<div class="file" data-dir="${esc(f.dir)}"><div class="th">📂</div><div class="t"><b>${esc(f.name)}</b></div></div>`).join("") +
    files.map(f => `<div class="file" data-id="${esc(f.id)}"><div class="th">${f.kind === "image" || f.kind === "video" ? `<img data-thumb="${esc(f.id)}" alt="">` : ""}<span>${KIND_ICON[f.kind]}</span></div>
      <div class="t"><b>${esc(f.name)}</b><small>${esc(t(KIND_NAME[f.kind]))} · ${size(f.size)}</small></div></div>`).join("")) ||
    `<div class="empty">${esc(d.place === "up" ? t("Nothing sent yet - press the button above to send a file from this phone.") : t("No usable files here."))}</div>`);
  document.querySelectorAll("[data-thumb]").forEach(img => {
    img.onload = () => { const s = img.nextElementSibling; if (s) s.style.display = "none"; };     // the picture replaces the icon
    pic("t", `/api/thumb?id=${encodeURIComponent(img.dataset.thumb)}`, img); });
}
async function fileChosen(f) {
  const p = cur().purpose;
  if (p) {
    if (p.kind === "screen") { const j = await act("screen_file", { role: p.role, id: f.id }); if (j.ok) back(); return; }
    if (p.kind === "deck") { const j = await act("deck_open", { id: f.id }); if (j.ok) { stack.pop(); build(); } return; }
    if (p.kind === "break") { const j = await act("break_add", { id: f.id }); if (j.ok) back(); return; }
    if (p.kind === "cue") { const j = await act("cue_assign", { index: p.index, id: f.id }); if (j.ok) back(); return; }
  }
  const opts = [];
  if (f.kind === "video" || f.kind === "image") for (const r of state.roles) opts.push({ label: tf("Show on {0}", r.label), value: ["screen_file", { role: r.role, id: f.id }] });
  if (f.kind === "video" && state.slides.live) opts.push({ label: t("Play it in the talk (the slides wait)"), value: ["break_play", { id: f.id }] });
  if (f.kind === "video") opts.push({ label: t("Add to the talk's videos"), value: ["break_add", { id: f.id }] });
  if (f.kind === "deck" || f.kind === "image") opts.push({ label: t("Open as the presentation"), value: ["deck_open", { id: f.id }] });
  if (f.kind === "audio" || f.kind === "video") opts.push({ label: t("Put it on a sound pad…"), value: ["pad", null] });
  const pick = await choose(f.name, opts);
  if (!pick) return;
  if (pick[0] === "pad") {
    const index = await choose(t("Which sound pad?"), state.cues.map(c => ({ label: `F${c.index + 1}   ${c.label || t("empty")}`, value: c.index })));
    if (index !== null) act("cue_assign", { index, id: f.id }); return;
  }
  const j = await act(pick[0], pick[1]);
  if (j.ok && pick[0] === "deck_open") go("slides");
}
function uploadFiles(list) {
  for (const file of list) {
    const job = { name: file.name, done: 0, total: file.size, state: "sending" }; ui.uploads.unshift(job); drawUploads();
    const x = new XMLHttpRequest(); x.open("POST", "/api/upload");
    x.setRequestHeader("X-Pin", pin); x.setRequestHeader("X-Name", encodeURIComponent(file.name));
    x.setRequestHeader("Content-Type", "application/octet-stream");
    x.upload.onprogress = e => { job.done = e.loaded; drawUploads(); };
    x.onload = () => { let j = {}; try { j = JSON.parse(x.responseText); } catch (e) {}
      job.state = j.ok ? "done" : "failed"; job.message = j.message || ""; drawUploads(); toast(j.message || t("Sent."), !j.ok);
      if (j.ok && ui.files.place === "up") loadFiles(); };
    x.onerror = () => { job.state = "failed"; job.message = t("The connection broke."); drawUploads(); };
    x.send(file);
  }
}
function drawUploads() {
  put("f-jobs", ui.uploads.slice(0, 6).map(j => `<div class="card" style="padding:10px 12px"><div class="ell"><b>${esc(j.name)}</b></div>
    <div class="hint">${j.state === "done" ? "✔ " + esc(t("on the stage computer")) : j.state === "failed" ? "✖ " + esc(j.message || t("failed")) :
      esc(tf("sending… {0}%", j.total ? Math.floor(j.done / j.total * 100) : 0))}</div>
    ${j.state === "sending" ? `<div class="bar"><i style="width:${j.total ? j.done / j.total * 100 : 0}%"></i></div>` : ""}</div>`).join(""));
}
V.files = {
  build(c) {
    $("view").innerHTML = `<label class="upload"><button class="gold big" style="width:100%">⬆ ${esc(t("Send a file from this phone"))}</button>
      <input type="file" id="f-input" multiple accept="image/*,video/*,audio/*,.pdf,.ppt,.pptx,.pps,.ppsx,.pptm,.odp"></label>
      <div class="hint" style="margin:6px 2px 12px">${esc(t("Videos, pictures, music and presentations - they go to “Sent from phones” on the stage computer."))}</div>
      <div id="f-jobs"></div><div class="chips" id="f-places"></div><div class="crumb" id="f-crumb"></div><div class="card" style="padding:8px"><div id="f-list"><div class="empty">…</div></div></div>`;
    $("f-input").onchange = e => { uploadFiles([...e.target.files]); e.target.value = ""; };
    $("f-places").onclick = e => { const b = e.target.closest("[data-place]"); if (b) { ui.files = { place: b.dataset.place, dir: "" }; loadFiles(); } };
    $("f-list").onclick = e => { const d = e.target.closest("[data-dir]"); if (d) { ui.files.dir = d.dataset.dir; loadFiles(); return; }
      const f = e.target.closest("[data-id]"); const file = f && ui.filesData.files.find(x => x.id === f.dataset.id); if (file) fileChosen(file); };
    drawUploads(); loadFiles();
  },
  draw() {},
};

/* RUNNING ORDER */
V.show = {
  build() {
    $("view").innerHTML = `<div class="row" style="margin-bottom:12px"><button id="o-name" class="ell" style="flex:3;text-align:left"></button><button id="o-edit"></button></div>
      <div id="o-now"></div><div class="card"><div class="cap" id="o-cap"></div><ul class="list" id="o-steps"></ul><div id="o-add"></div></div>`;
    $("o-name").onclick = async () => {
      const names = state.show.shows;
      const pick = await choose(t("Running orders"), names.map(n => ({ label: (n === state.show.name ? "● " : "") + n, value: n }))
        .concat([{ label: "+ " + t("New running order"), value: "\u0000new" }]));
      if (pick === "\u0000new") { const v = await ask(t("New running order"), [{ label: t("Name"), hint: t("e.g. Spring assembly") }], t("Create"));
        if (v && v[0].trim()) act("show_new", { name: v[0].trim() }); }
      else if (pick) act("show_select", { name: pick });
    };
    $("o-edit").onclick = () => { ui.edit = !ui.edit; ui.sel = -1; $("o-steps")._html = null; draw(); };
    $("o-steps").onclick = async e => {
      const b = e.target.closest("[data-a]"); const li = e.target.closest("li[data-i]");
      if (b) { const i = +b.dataset.i, sid = state.show.ids[i], st = state.show.steps[i];
        if (b.dataset.a === "go") act("goto", { index: i });
        else if (b.dataset.a === "edit") editStep(i);
        else if (b.dataset.a === "up" || b.dataset.a === "down") { const j = await act("step_move", { index: i, sid, delta: b.dataset.a === "up" ? -1 : 1 });
          if (j.ok) ui.sel = i + (b.dataset.a === "up" ? -1 : 1); }
        return; }
      if (li) { const i = +li.dataset.i; ui.sel = ui.sel === i ? -1 : i; $("o-steps")._html = null; draw(); }
    };
  },
  draw() {
    const show = state.show, steps = show.steps, now = show.index >= 0 ? steps[show.index] : null, next = steps[show.index + 1];
    $("o-name").textContent = "📋 " + show.name + "  ▾";
    $("o-edit").textContent = ui.edit ? "✔ " + t("Done") : "✏ " + t("Edit"); $("o-edit").classList.toggle("on", ui.edit);
    put("o-now", ui.edit ? `<div class="hint" style="margin-bottom:12px">${esc(t("Set the screens up the way a moment should look (Screens, Files, Text, Sound), then add it here as a step. Tap a step to rename, move or delete it."))}</div>` :
      `<div class="card now"><div class="cap">${esc(now ? tf("Now · step {0} of {1}", show.index + 1, steps.length) : (steps.length ? t("Ready") : t("No steps yet")))}</div>
      <h2>${esc(now ? now.title : (steps.length ? t("Press NEXT to start") : t("Tap Edit to build it")))}</h2>
      ${now && now.notes ? `<div class="hint" style="white-space:pre-wrap">${esc(now.notes)}</div>` : ""}
      ${show.auto != null ? `<div class="hint" style="color:var(--gold)">${esc(tf("goes on by itself in {0} s", Math.ceil(show.auto)))}</div>` : ""}
      <button class="gold huge" id="o-next" style="margin-top:10px" ${next ? "" : "disabled"}>${esc(t("NEXT"))} ▶</button>
      <div class="hint ell" style="margin-top:6px">${esc(next ? t("Next") + ": " + next.title : (now ? t("— end of the running order —") : ""))}</div>
      <div class="row" style="margin-top:10px"><button id="o-back" ${show.index > 0 ? "" : "disabled"}>◀ ${esc(t("Back"))}</button><button id="o-restart">↺ ${esc(t("Start over"))}</button></div></div>`);
    const n = $("o-next"); if (n) { n.onclick = () => { if (Date.now() - lastAct > 600) act("next"); }; $("o-back").onclick = () => act("back");
      $("o-restart").onclick = async () => { if (await confirmBox(t("Back to before step 1?"), t("Nothing on the screens changes until NEXT."))) act("restart"); }; }
    $("o-cap").textContent = ui.edit ? t("Steps · tap one to change it") : t("Steps · tap one, then GO");
    put("o-steps", steps.length ? steps.map((st, i) => `<li data-i="${i}" class="${i === show.index ? "now" : ""} ${i === ui.sel ? "sel" : ""}"><div class="n">${i + 1}</div>
      <div class="t"><b>${esc(st.title)}</b><small>${esc(st.summary)}</small></div><div class="acts">${ui.edit
        ? `<button data-a="up" data-i="${i}">⬆</button><button data-a="down" data-i="${i}">⬇</button><button data-a="edit" data-i="${i}">✏</button>`
        : `<button class="gold" data-a="go" data-i="${i}">${esc(t("GO"))}</button>`}</div></li>`).join("")
      : `<li class="empty">${esc(t("No steps in this running order."))}</li>`);
    put("o-add", ui.edit ? `<button class="gold" id="o-capture" style="width:100%;margin-top:10px">+ ${esc(t("Add a step: what is on the screens now"))}</button>` : "");
    const cap = $("o-capture"); if (cap) cap.onclick = async () => {
      const v = await ask(t("New step"), [{ label: t("Name"), hint: t("e.g. Opening, Anthem, Prize giving") }, { label: t("Notes for whoever runs it (optional)"), multi: true }], t("Add"));
      if (v) act("step_capture", { title: v[0], notes: v[1] }); };
  },
};
async function editStep(i) {
  const st = state.show.steps[i], sid = state.show.ids[i];
  const pick = await choose(st.title, [{ label: "✏ " + t("Name and notes"), value: "edit" }, { label: "⏱ " + t("Go on by itself after…"), value: "auto" },
    { label: "↻ " + t("Replace it with what is on the screens now"), value: "re" }, { label: "🗑 " + t("Delete this step"), value: "del", cls: "danger" }]);
  if (pick === "edit") { const v = await ask(t("Step"), [{ label: t("Name"), value: st.title }, { label: t("Notes"), value: st.notes, multi: true }], t("Save"));
    if (v) act("step_edit", { index: i, sid, title: v[0], notes: v[1] }); }
  else if (pick === "auto") { const v = await ask(t("Go on by itself after how many seconds? (0 = wait for NEXT)"), [{ label: t("Seconds"), value: "0", numeric: true }], t("Save"));
    if (v) act("step_edit", { index: i, sid, auto: parseInt(v[0], 10) || 0 }); }
  else if (pick === "re") { if (await confirmBox(t("Replace this step?"), t("It will put up exactly what the screens show now."))) act("step_recapture", { index: i, sid }); }
  else if (pick === "del") { if (await confirmBox(tf("Delete “{0}”?", st.title), "", t("Delete"), true)) { ui.sel = -1; act("step_delete", { index: i, sid }); } }
}

/* PRESENTATION */
V.slides = {
  build() {
    $("view").innerHTML = `<div id="p-none"></div><div id="p-deck"><div class="card"><div class="row" style="align-items:center"><div style="flex:3;min-width:0">
        <div class="status" id="p-status"></div><div class="ell" id="p-name" style="font-size:17px;font-weight:700"></div></div><div id="p-count" style="text-align:right;font-size:22px;font-weight:800"></div></div>
        <div class="chips" id="p-roles" style="margin:10px 0 0"></div></div>
      <div class="row" style="margin-bottom:10px"><div class="slide" id="p-cur" style="flex:2"></div><div class="slide" id="p-nxt"></div></div>
      <button class="gold huge" id="p-next">${esc(t("NEXT"))} ▶</button>
      <div class="row" style="margin:10px 0 12px"><button id="p-back">◀ ${esc(t("Back"))}</button><button id="p-black"></button></div>
      <div class="row" style="margin-bottom:12px"><button class="big" id="p-live"></button></div>
      <div class="card" id="p-break"></div>
      <div class="card"><div class="cap">${esc(t("Slides · tap to jump"))}</div><div class="thumbs" id="p-thumbs"></div></div>
      <div class="row"><button id="p-open">📁 ${esc(t("Open another"))}</button><button id="p-close" class="danger">${esc(t("Close it"))}</button></div></div>`;
    $("p-next").onclick = () => act("slide_next");
    $("p-back").onclick = () => act("slide_back");
    $("p-black").onclick = () => act("slide_black");
    $("p-open").onclick = () => go("files", { purpose: { kind: "deck", title: t("Open a presentation") } });
    $("p-close").onclick = async () => { if (await confirmBox(t("Close this presentation?"), t("It leaves the app; the file stays where it is."), t("Close it"), true)) act("deck_close"); };
    $("p-roles").onclick = e => { const b = e.target.closest("[data-role]"); if (b && !state.slides.live) act("deck_show", { role: b.dataset.role }); };
    $("p-thumbs").onclick = e => { const b = e.target.closest("[data-i]"); if (b) act("slide_goto", { index: +b.dataset.i }); };
    $("p-break").onclick = async e => { const b = e.target.closest("[data-b]"); if (!b) return; const a = b.dataset.b;
      if (a === "play") act("break_play", { index: +b.dataset.i });
      else if (a === "add") go("files", { purpose: { kind: "break", title: t("A video for the talk") } });
      else if (a === "toggle") act("break_toggle");
      else if (a === "rw") act("break_seek", { delta: -10000 }); else if (a === "ff") act("break_seek", { delta: 10000 });
      else if (a === "back") act("break_back"); };
    $("p-break").onchange = e => { if (e.target.id === "p-bseek") { const b = state.slides.break; e.target._busy = false;
      if (b) act("break_seek", { ms: Math.round(e.target.value / 1000 * b.duration) }); } };
    $("p-break").oninput = e => { if (e.target.id === "p-bseek") e.target._busy = true; };
  },
  draw() {
    const s = state.slides;
    $("p-deck").style.display = s.open ? "" : "none";
    put("p-none", s.open ? "" : `<div class="card"><h2 style="margin:4px 0">${esc(t("No presentation open"))}</h2>
      <div class="hint">${esc(t("Send the PDF or PowerPoint from this phone, or pick one on the stage computer."))}</div>
      <button class="gold big" id="p-first" style="width:100%;margin-top:12px">📁 ${esc(t("Open a presentation"))}</button></div>`);
    const first = $("p-first"); if (first) first.onclick = () => go("files", { purpose: { kind: "deck", title: t("Open a presentation") } });
    if (!s.open) return;
    const st = $("p-status"); st.className = "status " + (s.live ? (s.black ? "black" : "live") : "off");
    st.textContent = s.paused ? t("VIDEO PLAYING · the slides wait") : s.live ? (s.black ? t("BLACK") : tf("ON AIR · {0}", s.target)) : t("NOT ON A SCREEN");
    $("p-name").textContent = s.name; $("p-count").textContent = s.count ? `${s.index + 1}/${s.count}` : "…";
    put("p-roles", s.live ? "" : `<span class="hint" style="align-self:center">${esc(t("Show on:"))}</span>` + state.roles.map(r =>
      `<button data-role="${r.role}" class="${r.role === s.role ? "on" : ""}">${esc(r.label)}</button>`).join(""));
    const live = $("p-live");
    live.textContent = s.live ? "■ " + t("End the presentation (hold)") : "▶ " + tf("Show on {0}", role(s.role));
    live.classList.add("big", "hold"); live.classList.toggle("danger", s.live); live.classList.toggle("gold", !s.live);
    if (!live._wired) { live._wired = true;
      hold(live, 650, () => act("deck_end"), () => state.slides.live);          // ending: held
      live.addEventListener("click", () => { if (!state.slides.live) act("deck_show", { role: state.slides.role }); }); }   // starting: a tap
    $("p-next").textContent = s.paused ? t("Back to slides") : t("NEXT") + " ▶";
    $("p-black").textContent = s.black ? t("Lift black") : t("Black"); $("p-black").disabled = !s.live;
    $("p-close").disabled = s.live;
    if (s.count) { pic(s.deck + ":" + s.index, `/api/slide?deck=${s.deck}&i=${s.index}`, slideImg("p-cur"));
      if (s.index + 1 < s.count) pic(s.deck + ":" + (s.index + 1), `/api/slide?deck=${s.deck}&i=${s.index + 1}`, slideImg("p-nxt")); else put("p-nxt", esc(t("end"))); }
    const thumbs = $("p-thumbs");
    if (thumbs._deck !== s.deck + s.count) { thumbs._deck = s.deck + s.count; thumbs.innerHTML = Array.from({ length: s.count }, (_, i) =>
      `<button data-i="${i}"><img alt=""><span>${i + 1}</span></button>`).join(""); thumbs._loaded = 0; }
    thumbs.querySelectorAll("button").forEach((b, i) => { b.classList.toggle("cur", i === s.index);
      if (i < (thumbs._loaded || 0) + 6) pic(s.deck + ":" + i, `/api/slide?deck=${s.deck}&i=${i}`, b.querySelector("img")); });
    thumbs._loaded = Math.min(s.count, (thumbs._loaded || 0) + 6);
    const b = s.break;
    if (b) { const bs = $("p-bseek");
      put("p-break", `<div class="cap">${esc(t("Video in the talk"))}</div><div class="ell" style="font-weight:700;color:var(--gold)">${esc(b.name)}</div>
        <input type="range" id="p-bseek" min="0" max="1000"><div class="time"><span id="p-bpos"></span><span id="p-bdur"></span></div>
        <div class="row" style="margin-top:8px"><button data-b="rw">⏪ 10</button><button data-b="toggle" id="p-btog"></button><button data-b="ff">10 ⏩</button></div>
        <button class="gold" data-b="back" style="width:100%;margin-top:10px">${esc(s.live ? t("Back to slides") : t("Stop the video"))}</button>`);
      const seek = $("p-bseek"); if (!seek._busy) seek.value = b.duration ? Math.round(b.position / b.duration * 1000) : 0;
      $("p-bpos").textContent = mmss(b.position); $("p-bdur").textContent = mmss(b.duration);
      $("p-btog").textContent = b.playing ? "❚❚ " + t("Pause") : "▶ " + t("Play"); }
    else put("p-break", `<div class="cap">${esc(t("Videos during the talk"))}</div>` + (s.breaks.length
      ? s.breaks.map((n, i) => `<button data-b="play" data-i="${i}" style="width:100%;text-align:left;margin-top:6px" class="ell">▶ ${esc(n)}</button>`).join("")
      : `<div class="hint">${esc(t("A video to play in the middle - the slides wait and come back where they were."))}</div>`) +
      `<button data-b="add" class="ghost" style="width:100%;margin-top:8px">+ ${esc(t("Add a video"))}</button>`);
  },
};
function slideImg(id) { const box = $(id); let img = box.querySelector("img"); if (!img) { box.innerHTML = "<img alt=''>"; box._html = null; img = box.querySelector("img"); } return img; }

/* SOUND */
V.sound = {
  build() {
    $("view").innerHTML = `<div class="card"><div class="cap">${esc(t("Volume of the sound pads"))}</div><div class="row" style="align-items:center">
      <input type="range" id="d-vol" min="0" max="100" style="flex:4"><b id="d-volv" style="text-align:right"></b></div></div>
      <div class="pads" id="d-pads"></div><button class="danger big" id="d-stop" style="width:100%;margin-top:12px">■ ${esc(t("Stop all sound"))}</button>
      <div class="hint" style="margin-top:10px">${esc(t("Tap a pad to play or pause it; ⋯ to choose its sound."))}</div>`;
    const vol = $("d-vol"); vol.oninput = () => { vol._busy = true; $("d-volv").textContent = vol.value + "%"; };
    vol.onchange = () => { vol._busy = false; act("master", { value: +vol.value }); };
    $("d-stop").onclick = () => act("silence");
    $("d-pads").onclick = async e => { const m = e.target.closest("[data-more]");
      if (m) { const i = +m.dataset.more, c = state.cues[i];
        const pick = await choose(`F${i + 1}  ${c.label || t("empty")}`, [{ label: "📁 " + t("Choose its sound"), value: "pick" }]
          .concat(c.filled ? [{ label: "■ " + t("Stop"), value: "stop" }, { label: "🗑 " + t("Empty this pad"), value: "clear", cls: "danger" }] : []));
        if (pick === "pick") go("files", { purpose: { kind: "cue", index: i, title: tf("A sound for F{0}", i + 1) } });
        else if (pick === "stop") act("cue_stop", { index: i }); else if (pick === "clear") act("cue_clear", { index: i });
        return; }
      const b = e.target.closest("[data-cue]"); if (b) { const c = state.cues[+b.dataset.cue];
        if (c.filled) act("cue", { index: c.index }); else go("files", { purpose: { kind: "cue", index: c.index, title: tf("A sound for F{0}", c.index + 1) } }); } };
  },
  draw() {
    if (!$("d-vol")._busy) { $("d-vol").value = state.master; $("d-volv").textContent = state.master + "%"; }
    put("d-pads", state.cues.map(c => `<button class="pad ${c.playing ? "playing" : ""} ${c.paused ? "paused" : ""}" data-cue="${c.index}">
      <small>F${c.index + 1}${c.playing ? " ▶" : c.paused ? " ❚❚" : ""}</small><span>${esc(c.label || t("empty - tap to choose"))}</span>
      <span class="more" data-more="${c.index}">⋯</span></button>`).join(""));
  },
};

/* TEXT */
V.text = {
  build() {
    $("view").innerHTML = `<div class="card stack"><div class="cap">${esc(t("A name or a title on a screen"))}</div>
      <input type="text" id="x-title" placeholder="${esc(t("Title - e.g. Nino Beridze"))}"><input type="text" id="x-sub" placeholder="${esc(t("Second line - e.g. Grade 11 (optional)"))}">
      <div class="chips" id="x-roles" style="margin:0"></div>
      <div class="row"><button class="gold big" id="x-show">${esc(t("Show"))}</button><button class="big" id="x-hide">${esc(t("Hide"))}</button></div>
      <div class="hint" id="x-now"></div></div>
      <div class="card stack"><div class="cap">${esc(t("Running text on the Top Screen"))}</div><textarea id="x-mq" placeholder="${esc(t("Welcome to our spring assembly!"))}"></textarea>
      <div class="row"><button class="gold" id="x-mqon">▶ ${esc(t("Start"))}</button><button id="x-mqoff">■ ${esc(t("Stop"))}</button></div><div class="hint" id="x-mqnow"></div></div>`;
    ui.textRole = ui.textRole || (state ? state.text.target : "main");
    $("x-roles").onclick = e => { const b = e.target.closest("[data-role]"); if (b) { ui.textRole = b.dataset.role; $("x-roles")._html = null; draw(); } };
    $("x-show").onclick = () => act("text_show", { role: ui.textRole, title: $("x-title").value, subtitle: $("x-sub").value });
    $("x-hide").onclick = () => act("text_hide", { role: ui.textRole });
    $("x-mqon").onclick = () => act("marquee", { on: true, text: $("x-mq").value });
    $("x-mqoff").onclick = () => act("marquee", { on: false });
    if (state && !$("x-mq").value) $("x-mq").value = state.text.marquee.text || "";
  },
  draw() {
    put("x-roles", state.roles.map(r => `<button data-role="${r.role}" class="${r.role === ui.textRole ? "on" : ""}">${esc(r.label)}</button>`).join(""));
    const shown = state.screens.filter(s => s.text).map(s => `${s.label}: ${s.text.filter(Boolean).join(" — ")}`);
    $("x-now").textContent = shown.length ? t("Showing now") + " · " + shown.join(" · ") : t("No text on the screens.");
    $("x-mqnow").textContent = state.text.marquee.running ? t("Running now.") : t("Not running.");
  },
};

/* CANVA / KAHOOT */
V.web = {
  build() {
    $("view").innerHTML = `<div id="w-none" class="card"><div class="cap">${esc(t("Saved links"))}</div><div id="w-links"></div>
        <div class="row" style="margin-top:10px"><input type="text" id="w-url" placeholder="${esc(t("or paste a Canva / Kahoot link"))}" style="flex:3"><button id="w-go">${esc(t("Open"))}</button></div>
        <div class="hint" style="margin-top:8px">${esc(t("It opens on the stage computer first, silent - log in and get it ready, then put it on the Main Stage."))}</div></div>
      <div id="w-page"><div class="status" id="w-status" style="margin-bottom:6px"></div><div class="webshot" id="w-shot"><img id="w-img" alt=""></div>
        <div class="hint" style="margin:6px 2px 10px">${esc(t("Tap the picture to click there."))}</div>
        <div class="row" style="margin-bottom:10px"><button class="big" data-k="back">◀</button><button class="big" data-k="next">▶</button><button data-k="enter">⏎</button><button data-s="-0.6">⇡</button><button data-s="0.6">⇣</button></div>
        <div class="row" style="margin-bottom:12px"><input type="text" id="w-type" placeholder="${esc(t("Type into the page…"))}" style="flex:3"><button id="w-send">${esc(t("Send"))}</button></div>
        <div class="row" style="margin-bottom:10px"><button class="big" id="w-stage"></button></div>
        <div class="row"><button id="w-links2">🔗 ${esc(t("Another link"))}</button><button class="danger" id="w-close">${esc(t("Close"))}</button></div></div>`;
    $("w-links").onclick = e => { const b = e.target.closest("[data-i]"); if (b) act("web_open", { index: +b.dataset.i }); };
    $("w-go").onclick = () => { const u = $("w-url").value.trim(); if (u) act("web_open", { url: u }); };
    $("w-img").onclick = e => { const r = e.target.getBoundingClientRect(); const fx = (e.clientX - r.left) / r.width, fy = (e.clientY - r.top) / r.height;
      const dot = document.createElement("span"); dot.className = "tap"; dot.style.left = (fx * 100) + "%"; dot.style.top = (fy * 100) + "%"; $("w-shot").appendChild(dot);
      setTimeout(() => dot.remove(), 600); act("web_click", { x: fx, y: fy }); };
    $("w-page").onclick = e => { const k = e.target.closest("[data-k]"); if (k) act("web_key", { key: k.dataset.k });
      const s = e.target.closest("[data-s]"); if (s) act("web_scroll", { amount: +s.dataset.s }); };
    $("w-send").onclick = () => { const v = $("w-type").value; if (v) { act("web_type", { text: v }); $("w-type").value = ""; } };
    $("w-stage").onclick = () => act(state.web.where === "stage" ? "web_off" : "web_stage");
    $("w-close").onclick = async () => { if (await confirmBox(t("Close the page?"), t("Logins are kept for next time."), t("Close"), true)) act("web_close"); };
    $("w-links2").onclick = () => act("web_close");
  },
  draw() {
    const w = state.web, open = !!w.where;
    $("w-none").style.display = open ? "none" : ""; $("w-page").style.display = open ? "" : "none";
    put("w-links", w.links.map((l, i) => `<button data-i="${i}" style="width:100%;text-align:left;margin-top:6px">🌐 ${esc(l.name)}</button>`).join("") || `<div class="hint">${esc(t("No saved links."))}</div>`);
    if (!open) return;
    const st = $("w-status"); st.className = "status " + (w.where === "stage" ? "live" : "off");
    st.textContent = (w.where === "stage" ? t("ON THE MAIN STAGE") : t("ON THE DESK ONLY - silent")) + " · " + (w.loading ? t("loading…") : w.title);
    $("w-shot").className = "webshot " + (w.where === "stage" ? "stage" : "");
    pic("w" + Math.floor(Date.now() / 900), "/api/web", $("w-img"));
    $("w-stage").textContent = w.where === "stage" ? "■ " + t("Take it off the stage") : "▶ " + t("Show on the Main Stage");
    $("w-stage").className = "big " + (w.where === "stage" ? "danger" : "gold");
  },
};

/* LAPTOP */
V.laptop = {
  build() {
    $("view").innerHTML = `<div class="card"><div class="row" style="align-items:center"><div style="flex:3"><div class="cap">${esc(t("Laptop screen share"))}</div><div id="l-state"></div></div><button id="l-toggle"></button></div>
      <div id="l-how" class="hint" style="margin-top:10px"></div></div><div id="l-wait"></div><div id="l-on"></div>`;
    $("l-toggle").onclick = () => act("share_on", { on: !state.share.running });
    $("view").onclick = e => { const b = e.target.closest("[data-l]"); if (!b) return; const id = b.dataset.id, a = b.dataset.l;
      if (a === "take") act("share_take", { id, mode: b.dataset.mode || "alone" }); else if (a === "decline") act("share_decline", { id });
      else if (a === "end") act("share_end", { id }); else if (a === "mute") act("share_silence", { id, on: b.dataset.on === "1" }); };
  },
  draw() {
    const s = state.share;
    put("l-state", s.running ? `<b style="color:var(--ok)">${esc(t("On"))}</b>` : `<b class="muted">${esc(t("Off"))}</b>`);
    $("l-toggle").textContent = s.running ? t("Switch off") : t("Switch on"); $("l-toggle").className = s.running ? "" : "gold";
    put("l-how", s.running ? `${esc(t("On the laptop, open this in Chrome or Edge:"))}<div style="font-size:18px;font-weight:700;color:var(--text);margin:6px 0;word-break:break-all">${esc(s.address)}</div>
      ${esc(t("and type the code:"))}<div class="code">${esc(s.code)}</div>` : esc(t("Switch it on, and a laptop on the same Wi-Fi can show its screen - and sound - on the Main Stage.")));
    put("l-wait", s.waiting.length ? `<div class="card"><div class="cap">${esc(t("Waiting to be shown"))}</div>` + s.waiting.map(r =>
      `<div style="margin-top:8px"><b>💻 ${esc(r.name)}</b><div class="row" style="margin-top:6px"><button class="gold" data-l="take" data-id="${esc(r.id)}">${esc(t("Show on the Main Stage"))}</button>
       <button class="danger" data-l="decline" data-id="${esc(r.id)}">${esc(t("Decline"))}</button></div></div>`).join("") + `</div>` : "");
    put("l-on", s.links.length ? `<div class="card"><div class="cap">${esc(t("Connected"))}</div>` + s.links.map(l =>
      `<div style="margin-top:8px"><b>${l.where === "stage" ? "🔴" : "💻"} ${esc(l.name)}</b> <span class="muted">${esc(l.where === "stage" ? t("on the Main Stage") : t("preview"))}</span>
       <div class="row" style="margin-top:6px">${l.where === "stage" ? "" : `<button class="gold" data-l="take" data-id="${esc(l.id)}">${esc(t("Show"))}</button>${s.stage.length ? `<button data-l="take" data-mode="side" data-id="${esc(l.id)}">${esc(t("Beside"))}</button>` : ""}`}
       <button data-l="mute" data-id="${esc(l.id)}" data-on="${l.silenced ? "0" : "1"}">${esc(l.silenced ? t("Sound on") : t("Mute"))}</button><button class="danger" data-l="end" data-id="${esc(l.id)}">${esc(t("End"))}</button></div></div>`).join("") + `</div>` : "");
  },
};

/* SCENES */
V.scenes = {
  build() {
    $("view").innerHTML = `<div class="hint" style="margin:0 2px 12px">${esc(t("A scene puts a whole look on every screen at once - backgrounds, sound pads, text."))}</div>
      <div class="card"><ul class="list" id="c-list"></ul></div><button class="gold big" id="c-save" style="width:100%">+ ${esc(t("Save the screens as a new scene"))}</button><div id="c-upd"></div>`;
    $("c-list").onclick = async e => { const b = e.target.closest("[data-p]"); if (!b) return;
      if (await confirmBox(tf("Put “{0}” on the screens?", b.dataset.p), t("Undo can bring back what is there now."), t("Put it on"))) act("preset", { name: b.dataset.p }); };
    $("c-save").onclick = async () => { const v = await ask(t("New scene"), [{ label: t("Name"), hint: t("e.g. Assembly opening") }], t("Save"));
      if (v && v[0].trim()) { const name = v[0].trim(); const exists = state.presets.includes(name);
        if (exists && !(await confirmBox(tf("Replace “{0}”?", name), t("A scene with that name exists."), t("Replace"), true))) return;
        act("preset_save", { name, replace: exists }); } };
  },
  draw() {
    put("c-list", state.presets.length ? state.presets.map(p => `<li><div class="t"><b>${p === state.preset ? "● " : ""}${esc(p)}</b></div><button data-p="${esc(p)}">${esc(p === state.preset ? t("On the screens") : t("Put it on"))}</button></li>`).join("")
      : `<li class="empty">${esc(t("No scenes saved yet."))}</li>`);
    put("c-upd", state.preset ? `<button id="c-update" style="width:100%;margin-top:10px">↻ ${esc(tf("Update “{0}” with the screens now", state.preset))}</button>` : "");
    const u = $("c-update"); if (u) u.onclick = async () => { if (await confirmBox(tf("Replace “{0}”?", state.preset), t("It will hold what the screens show now."), t("Replace"), true))
      act("preset_save", { name: state.preset, replace: true }); };
  },
};

/* REHEARSAL */
V.rehearsal = {
  build() {
    $("view").innerHTML = `<div class="card"><h2 style="margin:2px 0 6px" id="r-head"></h2><div class="hint">${esc(t("While rehearsing, everything you do - files, scenes, the running order, text - goes to a rehearsal window on the stage computer instead of the hall's screens. The pictures on this phone show the rehearsal, so you can try a whole event out first. The hall keeps what it had."))}</div></div>
      <button class="big" id="r-toggle" style="width:100%;margin-bottom:12px"></button>
      <div class="card" id="r-sound"></div><div id="r-mv"></div>`;
    $("r-toggle").onclick = () => act("rehearsal", { on: !state.rehearsal.on });
    $("r-sound").onclick = e => { const b = e.target.closest("[data-dev]"); if (b) act("rehearsal_sound", { device: b.dataset.dev }); };
  },
  draw() {
    const r = state.rehearsal;
    $("r-head").textContent = r.on ? t("Rehearsing now") : t("Not rehearsing");
    $("r-toggle").textContent = r.on ? "■ " + t("End the rehearsal") : "🎭 " + t("Start a rehearsal");
    $("r-toggle").className = "big " + (r.on ? "danger" : "gold");
    put("r-sound", r.on ? `<div class="cap">${esc(t("Rehearsal sound"))}</div>` + [{ k: "", n: t("Silent") }].concat(r.devices.map(d => ({ k: d, n: d })))
      .map(d => `<button data-dev="${esc(d.k)}" class="${d.k === r.sound ? "on" : ""}" style="width:100%;text-align:left;margin-top:6px">${d.k === r.sound ? "● " : ""}${esc(d.n)}</button>`).join("")
      : `<div class="hint">${esc(t("Sound while rehearsing can stay silent or go to headphones - you choose once it starts."))}</div>`);
    if (r.on && !$("mv")) put("r-mv", mvHtml());
    if (!r.on) put("r-mv", "");
    drawMv();
  },
};

/* TIMER */
const T_MODES = [["countdown", "Countdown"], ["until", "Until a time"], ["stopwatch", "Stopwatch"], ["clock", "Clock"]];
const T_STYLES = [["school", "School"], ["black", "Black"], ["light", "Light"], ["bold", "Bold"], ["ring", "Ring"], ["glass", "Over the picture"]];
const T_SIZES = [["full", "Full screen"], ["large", "Large"], ["medium", "Medium"], ["small", "Small"], ["strip", "Band"]];
const T_PLACES = [["tl", "↖"], ["tr", "↗"], ["c", "●"], ["bl", "↙"], ["br", "↘"]];
const T_SELECTS = [["warn", "Warning colour", [[0, "no warning"], [60, "last minute"], [120, "last 2 minutes"], [300, "last 5 minutes"]]],
  ["overtime", "When the time is up", [["count", "counts on, red (+)"], ["stop", "stops at 0:00"], ["flash", "0:00, flashing"]]],
  ["sound", "Sound at the end", [["beeps", "three beeps"], ["off", "silent"]]]];
function chips(id, options, current, attr) {
  put(id, options.map(([v, label]) => `<button data-${attr}="${v}" class="${String(v) === String(current) ? "on" : ""}">${esc(t(label))}</button>`).join("")); }
V.timer = {
  build() {
    $("view").innerHTML = `<div class="card" style="text-align:center"><div class="status" id="t-state"></div>
        <div id="t-big" style="font-size:68px;font-weight:200;line-height:1.1;font-variant-numeric:tabular-nums;margin:4px 0"></div>
        <div class="bar" style="height:4px;margin:0 0 12px"><i id="t-line"></i></div>
        <div class="row"><button class="gold big" id="t-run" style="flex:2"></button><button class="big" id="t-reset">↺</button></div>
        <div class="row" style="margin-top:8px"><button id="t-minus">− 1 ${esc(t("min"))}</button><button id="t-plus">+ 1 ${esc(t("min"))}</button></div></div>
      <div class="card stack"><div class="cap">${esc(t("On the screen"))}</div><div class="chips" id="t-roles" style="margin:0"></div>
        <button class="big" id="t-show" style="width:100%"></button></div>
      <div class="card stack"><div class="cap">${esc(t("What it counts"))}</div>
        <input type="text" id="t-title" placeholder="${esc(t("Name on the screen (optional)"))}">
        <div class="chips" id="t-modes" style="margin:0;flex-wrap:wrap"></div>
        <div id="t-dur"><div class="chips" id="t-presets" style="flex-wrap:wrap"></div>
          <div class="row"><input type="text" id="t-min" inputmode="numeric" placeholder="${esc(t("minutes"))}"><input type="text" id="t-sec" inputmode="numeric" placeholder="${esc(t("seconds"))}"><button id="t-setdur">${esc(t("Set"))}</button></div></div>
        <div id="t-until" class="row"><input type="time" id="t-time" style="flex:2;background:var(--well);border:1px solid var(--edge);border-radius:12px;padding:12px"><button id="t-setuntil">${esc(t("Set"))}</button></div></div>
      <div class="card stack"><div class="cap">${esc(t("How it looks"))}</div>
        <div class="chips" id="t-styles" style="margin:0"></div><div class="chips" id="t-sizes" style="margin:0"></div>
        <div class="chips" id="t-places" style="margin:0"></div><div class="toggles" id="t-toggles"></div><div id="t-selects"></div></div>`;
    $("t-run").onclick = () => act("timer_toggle");
    $("t-reset").onclick = () => act("timer_reset");
    $("t-minus").onclick = () => act("timer_add", { ms: -60000 });
    $("t-plus").onclick = () => act("timer_add", { ms: 60000 });
    $("t-show").onclick = () => state.timer.on ? act("timer_hide") : act("timer_show", { role: ui.timerRole || "main" });
    $("t-roles").onclick = e => { const b = e.target.closest("[data-role]"); if (!b) return; ui.timerRole = b.dataset.role;
      if (state.timer.on) act("timer_show", { role: b.dataset.role }); else { $("t-roles")._html = null; draw(); } };
    $("t-title").onchange = () => act("timer_set", { title: $("t-title").value });
    $("t-modes").onclick = e => { const b = e.target.closest("[data-mode]"); if (b) act("timer_set", { mode: b.dataset.mode }); };
    $("t-presets").onclick = e => { const b = e.target.closest("[data-min]"); if (b) act("timer_set", { ms: +b.dataset.min * 60000 }); };
    $("t-setdur").onclick = () => { const ms = ((parseInt($("t-min").value, 10) || 0) * 60 + (parseInt($("t-sec").value, 10) || 0)) * 1000;
      if (ms > 0) act("timer_set", { ms }); };
    $("t-setuntil").onclick = () => { if ($("t-time").value) act("timer_set", { until: $("t-time").value.slice(0, 5) }); };
    $("view").onclick = e => {
      const s = e.target.closest("[data-style]"); if (s) { act("timer_look", { style: s.dataset.style }); return; }
      const z = e.target.closest("[data-size]"); if (z) { act("timer_look", { size: z.dataset.size }); return; }
      const p = e.target.closest("[data-place]"); if (p) { act("timer_look", { position: p.dataset.place }); return; }
      const k = e.target.closest("[data-flag]"); if (k) act("timer_look", { [k.dataset.flag]: !state.timer.look[k.dataset.flag] }); };
    $("t-selects").onchange = e => { const sel = e.target.closest("select"); if (!sel) return;
      act("timer_look", { [sel.dataset.key]: sel.dataset.key === "warn" ? +sel.value : sel.value }); };
    put("t-selects", T_SELECTS.map(([key, label, options]) => `<label class="hint" style="display:block;margin:10px 0 4px">${esc(t(label))}</label>
      <select data-key="${key}">${options.map(([v, l]) => `<option value="${v}">${esc(t(l))}</option>`).join("")}</select>`).join(""));
    put("t-presets", [1, 2, 3, 5, 10, 15, 20, 30, 45, 60].map(m => `<button data-min="${m}">${m} ${esc(t("min"))}</button>`).join(""));
  },
  draw() {
    const tm = state.timer, f = tm.frame, look = tm.look;
    ui.timerRole = tm.on || ui.timerRole || "main";
    const colour = { warn: "var(--gold)", over: "var(--red)" }[f.state] || "var(--text)";
    $("t-big").textContent = f.text; $("t-big").style.color = colour;
    $("t-line").style.width = f.fraction == null ? "0" : (f.fraction * 100).toFixed(1) + "%";
    $("t-state").textContent = tm.on ? tf("ON {0}", role(tm.on)) : t("NOT ON A SCREEN");
    $("t-state").className = "status " + (tm.on ? "live" : "off");
    const pausable = tm.mode === "countdown" || tm.mode === "stopwatch";
    $("t-run").textContent = tm.running ? "❚❚ " + t("Pause") : (pausable ? "▶ " + t("Start") : t("Runs by itself"));
    $("t-run").disabled = !pausable;
    $("t-minus").disabled = $("t-plus").disabled = tm.mode !== "countdown";
    $("t-reset").disabled = tm.mode === "clock";
    chips("t-roles", state.roles.map(r => [r.role, r.label]), ui.timerRole, "role");
    $("t-show").textContent = tm.on ? "■ " + tf("Take it off {0}", role(tm.on)) : "▶ " + t("Show on the screen");
    $("t-show").className = "big " + (tm.on ? "danger" : "gold");
    if (document.activeElement !== $("t-title")) $("t-title").value = tm.title;
    chips("t-modes", T_MODES, tm.mode, "mode");
    $("t-dur").style.display = tm.mode === "countdown" ? "" : "none";
    $("t-until").style.display = tm.mode === "until" ? "" : "none";
    if (document.activeElement !== $("t-time")) $("t-time").value = tm.until;
    document.querySelectorAll("#t-presets [data-min]").forEach(b => b.classList.toggle("on", +b.dataset.min * 60000 === tm.duration));
    chips("t-styles", T_STYLES, look.style, "style");
    chips("t-sizes", T_SIZES, look.size, "size");
    chips("t-places", T_PLACES, look.position, "place");
    put("t-toggles", [["title", "Name"], ["clock", "Clock"], ["logo", "Logo"], ["bar", "Line"]].map(([k, l]) =>
      `<button data-flag="${k}" class="${look[k] ? "on" : ""}">${look[k] ? "✔ " : ""}${esc(t(l))}</button>`).join(""));
    document.querySelectorAll("#t-selects select").forEach(sel => { if (document.activeElement !== sel) sel.value = String(look[sel.dataset.key]); });
  },
};

/* -- go ----------------------------------------------------------------------------------- */
build();
setInterval(() => { if (!document.hidden && !$("sheet").classList.contains("show")) refresh(); }, 1000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
window.addEventListener("popstate", () => { back(); history.pushState(null, "", location.pathname); });
history.pushState(null, "", location.pathname);
refresh();
</script></body></html>
"""
