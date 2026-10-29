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
:root { --bg:#0b0e14; --card:#131823; --raised:#1a2130; --well:#0e131c; --edge:#232c3d; --edge-hi:#2f3a50;
  --text:#e9edf5; --dim:#a9b3c6; --muted:#6d788d; --brand:#5b8cff; --brand2:#8b6cff; --brand-soft:rgba(91,140,255,.14);
  --gold:#f5b443; --ok:#34d399; --warn:#f5b443; --red:#f87171; --blue:#7aa2ff; --radius:18px; }
* { box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
html,body { margin:0; overflow-x:hidden; background:var(--bg); color:var(--text);
  font:15px/1.4 "Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,Roboto,"Noto Sans Georgian","Sylfaen",sans-serif; -webkit-font-smoothing:antialiased; }
body { padding:env(safe-area-inset-top) 0 calc(92px + env(safe-area-inset-bottom)); min-height:100vh;
  background:radial-gradient(900px 420px at 50% -120px, rgba(91,140,255,.12), transparent 70%), var(--bg); background-attachment:fixed; }
button, input, select, textarea { font:inherit; color:inherit; }
svg.i { width:20px; height:20px; flex:none; stroke:currentColor; fill:none; stroke-width:2; stroke-linecap:round; stroke-linejoin:round; vertical-align:-4px; }
svg.i.s { width:16px; height:16px; vertical-align:-3px; }
svg.i.l { width:24px; height:24px; }
button { display:inline-flex; align-items:center; justify-content:center; gap:8px; min-height:46px; border:1px solid var(--edge);
  background:var(--raised); border-radius:14px; padding:11px 12px; touch-action:manipulation; cursor:pointer; font-weight:600;
  transition:background .15s, border-color .15s, transform .08s; }
button:active { transform:scale(.97); background:var(--well); }
button:disabled { opacity:.38; pointer-events:none; }
button.gold { color:#fff; background:linear-gradient(135deg,var(--brand),var(--brand2)); border-color:transparent; font-weight:700;
  box-shadow:0 6px 18px rgba(91,140,255,.28); }
button.gold:active { filter:brightness(.92); }
button.gold:disabled { background:var(--raised); border-color:var(--edge); color:var(--muted); box-shadow:none; opacity:.6; }
button.danger { color:var(--red); background:rgba(248,113,113,.08); border-color:rgba(248,113,113,.4); font-weight:700; }
button.ghost { background:transparent; border-color:transparent; }
button.on { border-color:var(--brand); color:#cfdcff; background:var(--brand-soft); }
input[type=text], input[type=search], input[type=time], textarea, select { width:100%; min-height:46px; background:var(--well);
  border:1px solid var(--edge-hi); border-radius:13px; padding:11px 13px; outline:none; transition:border-color .15s, box-shadow .15s; }
input[type=text]:focus, input[type=time]:focus, textarea:focus, select:focus { border-color:var(--brand); box-shadow:0 0 0 4px var(--brand-soft); }
textarea { min-height:88px; resize:vertical; }
input[type=range] { -webkit-appearance:none; appearance:none; width:100%; height:32px; background:transparent; }
input[type=range]::-webkit-slider-runnable-track { height:6px; border-radius:99px; background:var(--edge-hi); }
input[type=range]::-webkit-slider-thumb { -webkit-appearance:none; width:24px; height:24px; margin-top:-9px; border-radius:50%;
  background:#fff; border:4px solid var(--brand); box-shadow:0 2px 8px rgba(0,0,0,.5); }
input[type=range]::-moz-range-track { height:6px; border-radius:99px; background:var(--edge-hi); }
input[type=range]::-moz-range-thumb { width:16px; height:16px; border-radius:50%; background:#fff; border:4px solid var(--brand); }
/* the frame */
header { position:sticky; top:0; z-index:5; display:flex; align-items:center; gap:10px; min-height:60px; padding:10px 14px;
  background:rgba(11,14,20,.82); backdrop-filter:blur(16px); -webkit-backdrop-filter:blur(16px); border-bottom:1px solid rgba(255,255,255,.06); }
header .back { width:42px; min-height:42px; padding:0; border-radius:12px; display:none; background:var(--raised); border-color:var(--edge); }
header.sub .back { display:inline-flex; }
header .mark { width:34px; height:34px; border-radius:10px; flex:none; display:grid; place-items:center; color:#fff;
  background:linear-gradient(135deg,var(--brand),var(--brand2)); box-shadow:0 6px 16px rgba(91,140,255,.35); }
header.sub .mark { display:none; }
header h1 { font-size:18px; font-weight:700; margin:0; flex:1; min-width:0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; letter-spacing:-.01em; }
.conn { display:flex; align-items:center; gap:8px; padding:6px 11px; border-radius:99px; background:var(--raised); border:1px solid var(--edge); }
header .dot { width:8px; height:8px; border-radius:50%; background:var(--muted); flex:none; }
header .dot.on { background:var(--ok); box-shadow:0 0 0 3px rgba(52,211,153,.2); }
header .clock { color:var(--dim); font-variant-numeric:tabular-nums; font-size:14px; font-weight:600; }
#rehearsal { display:none; margin:12px 14px 0; padding:10px 12px 10px 14px; border-radius:16px; border:1px solid rgba(122,162,255,.5);
  color:var(--blue); background:rgba(122,162,255,.1); font-weight:700; align-items:center; gap:10px; }
#rehearsal.show { display:flex; }
#rehearsal span { flex:1; font-size:14px; }
#rehearsal button { min-height:38px; padding:6px 14px; color:var(--blue); border-color:rgba(122,162,255,.5); background:transparent; }
main { padding:14px 14px 18px; max-width:860px; margin:0 auto; }
.card { background:var(--card); border:1px solid var(--edge); border-radius:var(--radius); padding:16px; margin-bottom:12px;
  box-shadow:0 1px 0 rgba(255,255,255,.03) inset, 0 8px 24px rgba(0,0,0,.18); }
.cap { color:var(--muted); font-size:12px; font-weight:700; letter-spacing:.06em; text-transform:uppercase; margin-bottom:8px; }
:lang(ka) .cap { text-transform:none; letter-spacing:.01em; font-size:13px; }
.hint { color:var(--dim); font-size:13.5px; }
.muted { color:var(--muted); }
.row { display:flex; gap:10px; }
.row > * { flex:1; min-width:0; }
.stack > * + * { margin-top:10px; }
.big { min-height:58px; font-size:17px; font-weight:700; }
.huge { display:flex; width:100%; min-height:18vh; font-size:28px; font-weight:800; letter-spacing:.06em; border-radius:22px; }
.ell { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.empty { color:var(--muted); text-align:center; padding:18px 6px; }
.banner { padding:10px 10px 10px 14px; border-radius:16px; border:1px solid rgba(245,180,67,.4); background:rgba(245,180,67,.09);
  color:var(--warn); margin-bottom:12px; display:flex; gap:10px; align-items:center; font-weight:600; }
.banner span { flex:1; }
.banner button { min-height:38px; padding:6px 14px; }
/* home: the screens */
.mv { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:10px; margin-bottom:14px; }
.mv .t { position:relative; background:#04060a; border:1px solid var(--edge); border-radius:16px; overflow:hidden; aspect-ratio:16/9; cursor:pointer;
  box-shadow:0 8px 22px rgba(0,0,0,.35); }
.mv .t.top { grid-column:1 / -1; aspect-ratio:14/1; border-radius:12px; }
.mv .t.live { border-color:rgba(248,113,113,.7); box-shadow:0 0 0 1px rgba(248,113,113,.35), 0 8px 22px rgba(0,0,0,.35); }
.mv .t.rehearsal { border-color:rgba(122,162,255,.7); }
.mv .t.closed { border-style:dashed; box-shadow:none; }
.mv img { width:100%; height:100%; object-fit:contain; display:block; }
.mv .t.top img { object-fit:fill; }
.mv .t::after { content:""; position:absolute; inset:auto 0 0 0; height:44%; background:linear-gradient(transparent, rgba(0,0,0,.7)); pointer-events:none; }
.mv .t.top::after { display:none; }
.mv .lab { position:absolute; left:10px; bottom:7px; z-index:1; font-size:12px; font-weight:700; color:#fff; text-shadow:0 1px 3px #000;
  max-width:62%; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.mv .tag { position:absolute; right:7px; top:7px; z-index:1; font-size:10px; font-weight:800; letter-spacing:.06em; padding:3px 8px;
  border-radius:99px; background:rgba(0,0,0,.55); color:var(--dim); backdrop-filter:blur(6px); }
.mv .t.live .tag { background:#e5484d; color:#fff; }
.mv .t.rehearsal .tag { background:var(--blue); color:#0b1020; }
.mv .t.top .lab, .mv .t.top .tag { top:50%; bottom:auto; transform:translateY(-50%); }
.mv .t.top .tag { padding:2px 7px; }
/* home: now, and the tiles */
.now { background:linear-gradient(160deg, rgba(91,140,255,.16), rgba(139,108,255,.08) 60%, var(--card)); border-color:rgba(91,140,255,.35); }
.now h2 { font-size:22px; margin:2px 0 4px; line-height:1.2; letter-spacing:-.01em; }
.tiles { display:grid; grid-template-columns:repeat(auto-fill, minmax(150px, 1fr)); gap:10px; }
.tile { position:relative; min-width:0; text-align:left; align-items:flex-start; justify-content:flex-start; flex-direction:column; gap:3px;
  padding:14px; min-height:112px; border-radius:18px; background:var(--card); }
.tile .ico { width:42px; height:42px; border-radius:13px; display:grid; place-items:center; margin-bottom:8px; color:var(--c, var(--brand));
  background:color-mix(in srgb, var(--c, var(--brand)) 16%, transparent); }
.tile b { font-size:15px; font-weight:700; }
.tile small { max-width:100%; color:var(--muted); font-size:12.5px; font-weight:500; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.tile.live, .tile.busy { border-color:color-mix(in srgb, var(--state) 45%, var(--edge)); }
.tile.live { --state:var(--red); } .tile.busy { --state:var(--gold); }
.tile.live::after, .tile.busy::after { content:""; position:absolute; top:14px; right:14px; width:9px; height:9px; border-radius:50%;
  background:var(--state); box-shadow:0 0 0 4px color-mix(in srgb, var(--state) 22%, transparent); }
.tile.live small, .tile.busy small { color:var(--state); }
/* a screen */
.shot { position:relative; background:#04060a; border:1px solid var(--edge); border-radius:18px; overflow:hidden; aspect-ratio:16/9; margin-bottom:12px;
  box-shadow:0 10px 28px rgba(0,0,0,.4); }
.shot.top { aspect-ratio:8/1; border-radius:12px; }
.shot.live { border-color:rgba(248,113,113,.7); }
.shot.rehearsal { border-color:rgba(122,162,255,.7); }
.shot img { width:100%; height:100%; object-fit:contain; display:block; }
.time { display:flex; justify-content:space-between; color:var(--dim); font-variant-numeric:tabular-nums; font-size:13px; }
.toggles { display:flex; gap:8px; flex-wrap:wrap; }
.toggles button { flex:1; min-height:44px; padding:9px 8px; font-size:14px; }
/* lists */
.list { list-style:none; margin:0; padding:0; }
.list li { display:flex; align-items:center; gap:12px; padding:10px; border-radius:14px; border:1px solid transparent; }
.list li + li { margin-top:4px; }
.list li .n { width:32px; height:32px; flex:none; border-radius:10px; background:var(--raised); color:var(--dim);
  display:grid; place-items:center; font-size:13px; font-weight:700; }
.list li .t { flex:1; min-width:0; }
.list li .t b { display:block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.list li .t small { display:block; color:var(--muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.list li.now { background:var(--brand-soft); border-color:rgba(91,140,255,.45); }
.list li.now .n { background:linear-gradient(135deg,var(--brand),var(--brand2)); color:#fff; }
.list li.sel { border-color:var(--brand); }
.list li .acts { display:none; gap:6px; }
.list li.sel .acts { display:flex; }
.list li .acts button { min-height:40px; padding:6px 12px; border-radius:11px; }
.list li > button { min-height:40px; padding:6px 14px; }
.chips { display:flex; gap:8px; overflow-x:auto; padding-bottom:4px; margin-bottom:10px; scrollbar-width:none; }
.chips::-webkit-scrollbar { display:none; }
.chips button { flex:none; min-height:40px; padding:7px 15px; border-radius:999px; font-size:14px; }
.file { display:flex; align-items:center; gap:12px; padding:8px; border-radius:14px; cursor:pointer; }
.file + .file { margin-top:2px; }
.file:active { background:var(--raised); }
.file .th { position:relative; width:76px; height:44px; flex:none; border-radius:10px; background:var(--well); display:grid; place-items:center;
  color:var(--dim); overflow:hidden; border:1px solid var(--edge); }
.file .th img { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; }
.file .th img:not([src]) { display:none; }
.file .t { flex:1; min-width:0; }
.file .t b { display:block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; font-weight:600; }
.file .t small { color:var(--muted); }
.crumb { display:flex; align-items:center; gap:8px; margin-bottom:8px; color:var(--dim); font-size:13px; }
.crumb button { min-height:38px; padding:6px 12px; border-radius:11px; }
.upload { position:relative; overflow:hidden; display:block; text-align:center; }
.upload button { width:100%; }
.upload input { position:absolute; inset:0; opacity:0; width:100%; height:100%; }
.bar { height:6px; border-radius:99px; background:var(--well); overflow:hidden; margin-top:6px; }
.bar i { display:block; height:100%; background:linear-gradient(90deg,var(--brand),var(--brand2)); width:0; transition:width .2s; }
/* slides */
.slide { background:#04060a; border:1px solid var(--edge); border-radius:14px; aspect-ratio:16/9; overflow:hidden; display:grid; place-items:center; color:var(--muted); }
.slide img { width:100%; height:100%; object-fit:contain; }
.thumbs { display:grid; grid-template-columns:repeat(auto-fill, minmax(96px, 1fr)); gap:8px; }
.thumbs button { min-height:0; padding:0; border-radius:10px; overflow:hidden; aspect-ratio:16/9; position:relative; background:#04060a; }
.thumbs button.cur { border:2px solid var(--brand); box-shadow:0 0 0 3px var(--brand-soft); }
.thumbs img { width:100%; height:100%; object-fit:contain; }
.thumbs span { position:absolute; left:6px; bottom:3px; font-size:11px; font-weight:800; text-shadow:0 1px 2px #000; }
.status { display:inline-flex; align-items:center; gap:7px; font-weight:800; letter-spacing:.06em; font-size:12px; }
.status::before { content:""; width:8px; height:8px; border-radius:50%; background:currentColor; }
.status.live { color:var(--red); } .status.black { color:var(--warn); } .status.off { color:var(--muted); }
/* sound */
.pads { display:grid; grid-template-columns:repeat(auto-fill, minmax(150px, 1fr)); gap:10px; }
.pad { min-width:0; position:relative; text-align:left; align-items:flex-start; justify-content:center; flex-direction:column; gap:4px;
  min-height:78px; padding:12px 14px; border-radius:16px; background:var(--card); }
.pad small { display:block; color:var(--muted); font-size:12px; font-weight:800; letter-spacing:.04em; }
.pad span { display:block; max-width:100%; font-size:14px; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; padding-right:28px; }
.pad.playing { border-color:rgba(52,211,153,.6); background:rgba(52,211,153,.1); }
.pad.playing small { color:var(--ok); }
.pad.paused { border-color:rgba(245,180,67,.6); }
.pad .more { position:absolute; right:6px; top:8px; padding:2px 9px; border-radius:9px; font-size:16px; color:var(--dim); }
/* web */
.webshot { position:relative; background:#04060a; border:1px solid var(--edge); border-radius:16px; overflow:hidden; aspect-ratio:16/9; }
.webshot.stage { border-color:rgba(248,113,113,.7); }
.webshot img { width:100%; height:100%; object-fit:contain; display:block; }
.webshot .tap { position:absolute; width:26px; height:26px; margin:-13px 0 0 -13px; border-radius:50%; border:2px solid var(--brand); pointer-events:none; animation:tap .5s ease-out forwards; }
@keyframes tap { to { transform:scale(1.8); opacity:0; } }
.code { font-size:36px; font-weight:800; letter-spacing:8px; color:#cfdcff; font-variant-numeric:tabular-nums; }
/* the quick bar */
.quick { position:fixed; left:0; right:0; bottom:0; z-index:6; display:flex; gap:8px; padding:10px 12px calc(10px + env(safe-area-inset-bottom));
  background:rgba(11,14,20,.86); border-top:1px solid rgba(255,255,255,.06); backdrop-filter:blur(16px); -webkit-backdrop-filter:blur(16px); }
.quick > * { max-width:280px; }
.quick { justify-content:center; }
.quick button { flex:1; min-height:54px; padding:6px 4px; font-size:12px; font-weight:800; letter-spacing:.02em; border-radius:15px; flex-direction:column; gap:3px; line-height:1.15; }
.quick button span { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:100%; }
@media (min-width:600px) { .quick button { flex-direction:row; gap:8px; font-size:13px; } }
.quick .blackout { flex:1.35; color:#fff; border-color:transparent; background:linear-gradient(135deg,#e5484d,#c4314b);
  box-shadow:0 6px 18px rgba(229,72,77,.3); }
.hold { position:relative; overflow:hidden; }
.hold::after { content:""; position:absolute; left:0; bottom:0; height:4px; width:0; background:currentColor; opacity:.85; }
.hold.holding::after { width:100%; transition:width var(--hold,700ms) linear; }
/* the sheet, signing in, the toast */
#shade { position:fixed; inset:0; background:rgba(4,6,10,.6); z-index:20; display:none; backdrop-filter:blur(2px); }
#shade.show { display:block; }
#sheet { position:fixed; left:0; right:0; bottom:0; z-index:21; max-width:620px; margin:0 auto; background:var(--card); border:1px solid var(--edge-hi);
  border-bottom:0; border-radius:24px 24px 0 0; padding:10px 16px calc(18px + env(safe-area-inset-bottom)); max-height:86vh; overflow:auto;
  transform:translateY(105%); transition:transform .24s cubic-bezier(.2,.8,.2,1); box-shadow:0 -12px 40px rgba(0,0,0,.45); }
#sheet::before { content:""; display:block; width:40px; height:5px; border-radius:99px; background:var(--edge-hi); margin:0 auto 14px; }
#sheet.show { transform:none; }
#sheet h3 { margin:0 0 4px; font-size:18px; }
#sheet .sub { color:var(--dim); font-size:13.5px; margin-bottom:10px; }
#sheet .opts > button { display:flex; width:100%; justify-content:flex-start; text-align:left; margin-top:8px; min-height:52px; padding:10px 16px; }
#sheet .opts > button.ghost { justify-content:center; color:var(--dim); }
#sheet label { display:block; color:var(--dim); font-size:13px; font-weight:600; margin:12px 0 6px; }
#login { position:fixed; inset:0; background:radial-gradient(700px 400px at 50% 0, rgba(91,140,255,.18), transparent 70%), var(--bg);
  display:none; flex-direction:column; align-items:center; justify-content:center; gap:18px; z-index:30; padding:20px; }
#login.show { display:flex; }
#pinmark { width:60px; height:60px; border-radius:18px; display:grid; place-items:center; color:#fff; background:linear-gradient(135deg,var(--brand),var(--brand2));
  box-shadow:0 10px 26px rgba(91,140,255,.4); }
#pinmark svg { width:30px; height:30px; }
#login .cap { font-size:15px; text-transform:none; letter-spacing:0; color:var(--dim); font-weight:600; }
#pin { font-size:34px; letter-spacing:16px; min-height:46px; font-weight:800; padding-left:16px; }
.pinpad { display:grid; grid-template-columns:repeat(3,78px); gap:14px; }
.pinpad button { width:78px; height:78px; min-height:0; font-size:26px; font-weight:600; border-radius:50%; background:var(--card); }
#msg { color:var(--red); min-height:20px; font-weight:600; }
#toast { position:fixed; left:50%; bottom:calc(96px + env(safe-area-inset-bottom)); transform:translate(-50%, 10px); z-index:40; background:#e9edf5; color:#0b0e14;
  padding:11px 18px; border-radius:14px; opacity:0; transition:opacity .2s, transform .2s; pointer-events:none; max-width:90vw; text-align:center;
  font-weight:600; font-size:14px; box-shadow:0 10px 30px rgba(0,0,0,.45); }
#toast.show { opacity:1; transform:translate(-50%, 0); }
#toast.bad { background:var(--red); color:#fff; }
@media (min-width:700px) { .mv { gap:12px; } .huge { min-height:120px; } }
@media (prefers-reduced-motion: reduce) { * { transition:none !important; animation:none !important; } }
</style></head>
<body>
<header id="head"><button class="back ghost" id="back" aria-label="Back"></button><div class="mark" id="mark"></div><h1 id="title">Stage remote</h1><div class="conn"><div class="dot" id="dot"></div><div class="clock" id="clock"></div></div></header>
<div id="rehearsal"><span id="rehtext"></span><button id="rehend"></button></div>
<main id="view"></main>
<div class="quick"><button class="blackout hold" id="qblack"></button><button id="qundo"></button><button id="qsilence"></button></div>
<div id="shade"></div><div id="sheet"></div>
<div id="login"><div id="pinmark"></div><div class="cap" id="logincap"></div><div id="pin"></div><div class="pinpad" id="pinpad"></div><div id="msg"></div></div>
<div id="toast"></div>

<script>
"use strict";
const L = /*LANG*/null;
const t = s => (L && L[s]) || s;

/* -- icons (24 px, stroked) ------------------------------------------------------------------- */
const IC = {
  back: '<path d="m15 18-6-6 6-6"/>', mark: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
  power: '<path d="M12 2v10"/><path d="M18.4 6.6a9 9 0 1 1-12.8 0"/>', undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
  mute: '<path d="M11 5 6 9H2v6h4l5 4z"/><path d="m22 9-6 6M16 9l6 6"/>', sound: '<path d="M11 5 6 9H2v6h4l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M19 5a10 10 0 0 1 0 14"/>',
  list: '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>', slides: '<rect x="2" y="4" width="20" height="13" rx="2"/><path d="M12 17v4M8 21h8"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>', music: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
  text: '<path d="M4 7V5h16v2M9 19h6M12 5v14"/>', globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
  laptop: '<rect x="4" y="5" width="16" height="11" rx="1.5"/><path d="M2 20h20"/>', star: '<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z"/>',
  mask: '<path d="M4 5h16v6a8 8 0 0 1-16 0z"/><path d="M9 10h.01M15 10h.01M9.5 14a3.5 3.5 0 0 0 5 0"/>', timer: '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2 2M9 2h6"/>',
  play: '<path d="M7 4v16l13-8z"/>', pause: '<path d="M8 4v16M16 4v16"/>', stop: '<rect x="5" y="5" width="14" height="14" rx="2"/>',
  restart: '<path d="M5 4v16"/><path d="M19 4 9 12l10 8z"/>', repeat: '<path d="m17 2 4 4-4 4"/><path d="M3 11V9a3 3 0 0 1 3-3h15M7 22l-4-4 4-4"/><path d="M21 13v2a3 3 0 0 1-3 3H3"/>',
  square: '<rect x="3" y="3" width="18" height="18" rx="3"/>', upload: '<path d="M12 21V9M7 14l5-5 5 5M5 3h14"/>',
  video: '<rect x="2" y="5" width="15" height="14" rx="2"/><path d="m17 10 5-3v10l-5-3"/>', image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-5-5L5 21"/>',
  deck: '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8M12 17v4M7 9h10M7 12h6"/>', edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  check: '<path d="M20 6 9 17l-5-5"/>', up: '<path d="m18 15-6-6-6 6"/>', down: '<path d="m6 9 6 6 6-6"/>', link: '<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/>',
  left: '<path d="m15 18-6-6 6-6"/>', right: '<path d="m9 18 6-6-6-6"/>', enter: '<path d="M9 10 4 15l5 5"/><path d="M20 4v7a4 4 0 0 1-4 4H4"/>',
  scrollup: '<path d="M12 19V5M5 12l7-7 7 7"/>', scrolldown: '<path d="M12 5v14M19 12l-7 7-7-7"/>', reset: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
  rw: '<path d="M11 19 2 12l9-7zM22 19l-9-7 9-7z"/>', ff: '<path d="m13 19 9-7-9-7zM2 19l9-7-9-7z"/>', live: '<circle cx="12" cy="12" r="3"/><path d="M16.2 7.8a6 6 0 0 1 0 8.4M7.8 16.2a6 6 0 0 1 0-8.4M19 5a10 10 0 0 1 0 14M5 19A10 10 0 0 1 5 5"/>',
  next: '<path d="M5 4v16l11-8z"/><path d="M19 5v14"/>',
};
const ico = (n, s) => `<svg class="i ${s || ""}" viewBox="0 0 24 24" aria-hidden="true">${IC[n] || ""}</svg>`;
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
function isStrip(r) { const s = screen(r); return !!s && s.kind === "strip"; }
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
$("back").innerHTML = ico("back");
$("mark").innerHTML = ico("mark", "s");
$("qblack").innerHTML = ico("power", "s") + `<span>${esc(t("BLACKOUT"))}</span>`;
hold($("qblack"), 700, () => act("blackout"));
$("qundo").innerHTML = ico("undo", "s") + `<span>${esc(t("Undo"))}</span>`;
$("qundo").onclick = () => act("undo");
$("qsilence").innerHTML = ico("mute", "s") + `<span>${esc(t("Stop sound"))}</span>`;
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
  `<div class="t ${sc.kind === "strip" ? "top" : ""}" id="mv-${sc.role}" data-go="${sc.role}"><img alt=""><span class="lab">${esc(sc.label)}</span><span class="tag"></span></div>`).join("") + `</div>`; }
function tag(stateName) { return ({ live: t("ON AIR"), black: t("BLACK"), closed: t("CLOSED"), rehearsal: t("REHEARSAL") })[stateName] || stateName; }
function drawMv() {
  const mv = $("mv"); if (!mv) return;
  for (const sc of state.screens) {
    const el = $("mv-" + sc.role); if (!el) continue;
    el.className = `t ${sc.kind === "strip" ? "top" : ""} ${sc.state}`;
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
      <div class="row" style="margin-top:10px"><button id="hback" ${show.index > 0 ? "" : "disabled"}>${ico("left")}</button><button class="gold big" id="hnext" style="flex:3" ${next ? "" : "disabled"}>${esc(t("NEXT"))} ${ico("next")}</button></div></div>` : "");
    const hn = $("hnext"); if (hn) { hn.onclick = () => act("next"); $("hback").onclick = () => act("back"); }
    const sl = s.slides, sh = s.share, web = s.web;
    const playing = s.cues.filter(c => c.playing).map(c => "F" + (c.index + 1));
    const tiles = [
      ["show", "list:#7aa2ff", "Running order", steps.length ? tf("{0} steps", steps.length) : t("empty - build it here"), now ? "busy" : ""],
      ["slides", "slides:#a78bfa", "Presentation", sl.live ? tf("slide {0} of {1} · on screen", sl.index + 1, sl.count) : (sl.open ? sl.name : t("none open")), sl.live ? "live" : ""],
      ["files", "folder:#f5b443", "Files", t("send from this phone, or choose"), ""],
      ["sound", "music:#34d399", "Sound", playing.length ? tf("playing: {0}", playing.join(", ")) : tf("volume {0}%", s.master), playing.length ? "busy" : ""],
      ["text", "text:#60a5fa", "Text on screen", s.screens.some(x => x.text) ? t("text is showing") : t("names, titles, running text"), s.screens.some(x => x.text) ? "busy" : ""],
      ["web", "globe:#22d3ee", "Canva and Kahoot", web.where === "stage" ? t("on the Main Stage") : (web.where ? t("ready on the desk") : t("presentations and games")), web.where === "stage" ? "live" : ""],
      ["laptop", "laptop:#94a3b8", "Laptop", sh.waiting.length ? tf("{0} waiting", sh.waiting.length) : (sh.stage.length ? t("on the Main Stage") : (sh.running ? t("ready for laptops") : t("off"))), sh.waiting.length ? "busy" : (sh.stage.length ? "live" : "")],
      ["scenes", "star:#fbbf24", "Scenes", s.preset ? tf("now: {0}", s.preset) : tf("{0} saved", s.presets.length), ""],
      ["rehearsal", "mask:#f472b6", "Rehearsal", s.rehearsal.on ? t("ON - the hall sees nothing") : t("try everything out first"), s.rehearsal.on ? "busy" : ""],
      ["timer", "timer:#fb923c", "Timer", s.timer.on ? s.timer.frame.text + " · " + role(s.timer.on) : (s.timer.running ? s.timer.frame.text : t("countdown on a screen")),
        s.timer.on ? "live" : (s.timer.running ? "busy" : "")],
    ];
    put("h-tiles", tiles.map(([v, ic, label, sub, cls]) =>
      `<button class="tile ${cls}" data-v="${v}" style="--c:${ic.split(":")[1]}"><span class="ico">${ico(ic.split(":")[0], "l")}</span><b>${esc(t(label))}</b><small>${esc(sub)}</small></button>`).join(""));
    $("h-tiles").onclick = e => { const b = e.target.closest("[data-v]"); if (b) go(b.dataset.v); };
  },
};

/* SCREEN */
V.screen = {
  build(c) { $("view").innerHTML = `<div class="shot ${isStrip(c.role) ? "top" : ""}" id="s-shot"><img id="s-img" alt=""></div>
    <div class="card"><div class="cap" id="s-state"></div><div class="ell" id="s-file" style="font-size:17px;font-weight:700"></div><div class="hint" id="s-text"></div></div>
    <div class="row" style="margin-bottom:12px"><button class="gold big" id="s-pick">${ico("folder")} ${esc(t("Show a file"))}</button><button class="big" id="s-black">${ico("square")} ${esc(t("Black"))}</button></div>
    <div class="card" id="s-video"><div class="cap">${esc(t("Video"))}</div>
      <div class="row" style="margin-bottom:6px"><button id="s-restart" aria-label="Restart">${ico("restart")}</button><button id="s-play" style="flex:2"></button></div>
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
    $("s-shot").className = `shot ${isStrip(c.role) ? "top" : ""} ${sc.state}`;
    if (sc.state !== "closed") pic(sc.version + (sc.moving ? ":" + Math.floor(Date.now() / 1000) : ""), `/api/screen?role=${c.role}`, $("s-img"));
    $("s-state").textContent = tag(sc.state);
    $("s-file").textContent = sc.open ? (sc.file || t("nothing - black")) : t("This screen is closed");
    $("s-text").textContent = sc.text ? t("Text on it") + ": " + sc.text.filter(Boolean).join(" — ") : "";
    $("s-black").disabled = !sc.open;
    $("s-video").style.display = sc.video && sc.open ? "" : "none";
    $("s-play").innerHTML = sc.playing ? ico("pause") + " " + esc(t("Pause")) : ico("play") + " " + esc(t("Play"));
    $("s-loop").innerHTML = ico("repeat", "s") + " " + esc(sc.loop ? t("Repeat: on") : t("Repeat: off")); $("s-loop").classList.toggle("on", sc.loop);
    $("s-mute").innerHTML = sc.muted ? ico("mute", "s") + " " + esc(t("Sound: off")) : ico("sound", "s") + " " + esc(t("Sound: on")); $("s-mute").classList.toggle("on", !sc.muted);
    if (!$("s-seek")._busy) { $("s-seek").value = sc.duration ? Math.round(sc.position / sc.duration * 1000) : 0; $("s-pos").textContent = mmss(sc.position); }
    $("s-dur").textContent = mmss(sc.duration);
    if (!$("s-vol")._busy) $("s-vol").value = sc.volume;
  },
};

/* FILES */
const KIND_ICON = { video: ico("video"), image: ico("image"), audio: ico("music"), deck: ico("deck") };
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
  put("f-list", (d.folders.map(f => `<div class="file" data-dir="${esc(f.dir)}"><div class="th" style="color:var(--gold)">${ico("folder")}</div><div class="t"><b>${esc(f.name)}</b></div></div>`).join("") +
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
    $("view").innerHTML = `<label class="upload"><button class="gold big" style="width:100%">${ico("upload")} ${esc(t("Send a file from this phone"))}</button>
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
    $("o-name").innerHTML = ico("list") + `<span class="ell" style="flex:1;text-align:left">${esc(show.name)}</span>` + ico("down", "s");
    $("o-edit").innerHTML = ui.edit ? ico("check", "s") + " " + esc(t("Done")) : ico("edit", "s") + " " + esc(t("Edit")); $("o-edit").classList.toggle("on", ui.edit);
    put("o-now", ui.edit ? `<div class="hint" style="margin-bottom:12px">${esc(t("Set the screens up the way a moment should look (Screens, Files, Text, Sound), then add it here as a step. Tap a step to rename, move or delete it."))}</div>` :
      `<div class="card now"><div class="cap">${esc(now ? tf("Now · step {0} of {1}", show.index + 1, steps.length) : (steps.length ? t("Ready") : t("No steps yet")))}</div>
      <h2>${esc(now ? now.title : (steps.length ? t("Press NEXT to start") : t("Tap Edit to build it")))}</h2>
      ${now && now.notes ? `<div class="hint" style="white-space:pre-wrap">${esc(now.notes)}</div>` : ""}
      ${show.auto != null ? `<div class="hint" style="color:var(--gold)">${esc(tf("goes on by itself in {0} s", Math.ceil(show.auto)))}</div>` : ""}
      <button class="gold huge" id="o-next" style="margin-top:10px" ${next ? "" : "disabled"}>${esc(t("NEXT"))} ${ico("next", "l")}</button>
      <div class="hint ell" style="margin-top:6px">${esc(next ? t("Next") + ": " + next.title : (now ? t("— end of the running order —") : ""))}</div>
      <div class="row" style="margin-top:10px"><button id="o-back" ${show.index > 0 ? "" : "disabled"}>${ico("left", "s")} ${esc(t("Back"))}</button><button id="o-restart">${ico("reset", "s")} ${esc(t("Start over"))}</button></div></div>`);
    const n = $("o-next"); if (n) { n.onclick = () => { if (Date.now() - lastAct > 600) act("next"); }; $("o-back").onclick = () => act("back");
      $("o-restart").onclick = async () => { if (await confirmBox(t("Back to before step 1?"), t("Nothing on the screens changes until NEXT."))) act("restart"); }; }
    $("o-cap").textContent = ui.edit ? t("Steps · tap one to change it") : t("Steps · tap one, then GO");
    put("o-steps", steps.length ? steps.map((st, i) => `<li data-i="${i}" class="${i === show.index ? "now" : ""} ${i === ui.sel ? "sel" : ""}"><div class="n">${i + 1}</div>
      <div class="t"><b>${esc(st.title)}</b><small>${esc(st.summary)}</small></div><div class="acts">${ui.edit
        ? `<button data-a="up" data-i="${i}">${ico("up", "s")}</button><button data-a="down" data-i="${i}">${ico("down", "s")}</button><button data-a="edit" data-i="${i}">${ico("edit", "s")}</button>`
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
      <button class="gold huge" id="p-next">${esc(t("NEXT"))}</button>
      <div class="row" style="margin:10px 0 12px"><button id="p-back">${ico("left", "s")} ${esc(t("Back"))}</button><button id="p-black"></button></div>
      <div class="row" style="margin-bottom:12px"><button class="big" id="p-live"></button></div>
      <div class="card" id="p-break"></div>
      <div class="card"><div class="cap">${esc(t("Slides · tap to jump"))}</div><div class="thumbs" id="p-thumbs"></div></div>
      <div class="row"><button id="p-open">${ico("folder", "s")} ${esc(t("Open another"))}</button><button id="p-close" class="danger">${esc(t("Close it"))}</button></div></div>`;
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
      <button class="gold big" id="p-first" style="width:100%;margin-top:12px">${ico("folder")} ${esc(t("Open a presentation"))}</button></div>`);
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
    $("p-next").innerHTML = s.paused ? esc(t("Back to slides")) : esc(t("NEXT")) + " " + ico("next", "l");
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
        <div class="row" style="margin-top:8px"><button data-b="rw">${ico("rw", "s")} 10</button><button data-b="toggle" id="p-btog"></button><button data-b="ff">10 ${ico("ff", "s")}</button></div>
        <button class="gold" data-b="back" style="width:100%;margin-top:10px">${esc(s.live ? t("Back to slides") : t("Stop the video"))}</button>`);
      const seek = $("p-bseek"); if (!seek._busy) seek.value = b.duration ? Math.round(b.position / b.duration * 1000) : 0;
      $("p-bpos").textContent = mmss(b.position); $("p-bdur").textContent = mmss(b.duration);
      $("p-btog").innerHTML = b.playing ? ico("pause", "s") + " " + esc(t("Pause")) : ico("play", "s") + " " + esc(t("Play")); }
    else put("p-break", `<div class="cap">${esc(t("Videos during the talk"))}</div>` + (s.breaks.length
      ? s.breaks.map((n, i) => `<button data-b="play" data-i="${i}" style="width:100%;text-align:left;margin-top:6px" class="ell">${ico("play", "s")} ${esc(n)}</button>`).join("")
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
      <div class="pads" id="d-pads"></div><button class="danger big" id="d-stop" style="width:100%;margin-top:12px">${ico("stop")} ${esc(t("Stop all sound"))}</button>
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
      <div class="row"><button class="gold" id="x-mqon">${ico("play", "s")} ${esc(t("Start"))}</button><button id="x-mqoff">${ico("stop", "s")} ${esc(t("Stop"))}</button></div><div class="hint" id="x-mqnow"></div></div>`;
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
        <div class="row" style="margin-bottom:10px"><button class="big" data-k="back">${ico("left")}</button><button class="big" data-k="next">${ico("right")}</button><button data-k="enter">${ico("enter")}</button><button data-s="-0.6">${ico("scrollup")}</button><button data-s="0.6">${ico("scrolldown")}</button></div>
        <div class="row" style="margin-bottom:12px"><input type="text" id="w-type" placeholder="${esc(t("Type into the page…"))}" style="flex:3"><button id="w-send">${esc(t("Send"))}</button></div>
        <div class="row" style="margin-bottom:10px"><button class="big" id="w-stage"></button></div>
        <div class="row"><button id="w-links2">${ico("link", "s")} ${esc(t("Another link"))}</button><button class="danger" id="w-close">${esc(t("Close"))}</button></div></div>`;
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
    put("w-links", w.links.map((l, i) => `<button data-i="${i}" style="width:100%;justify-content:flex-start;margin-top:6px">${ico("globe", "s")} ${esc(l.name)}</button>`).join("") || `<div class="hint">${esc(t("No saved links."))}</div>`);
    if (!open) return;
    const st = $("w-status"); st.className = "status " + (w.where === "stage" ? "live" : "off");
    st.textContent = (w.where === "stage" ? t("ON THE MAIN STAGE") : t("ON THE DESK ONLY - silent")) + " · " + (w.loading ? t("loading…") : w.title);
    $("w-shot").className = "webshot " + (w.where === "stage" ? "stage" : "");
    pic("w" + Math.floor(Date.now() / 900), "/api/web", $("w-img"));
    $("w-stage").innerHTML = w.where === "stage" ? ico("stop") + " " + esc(t("Take it off the stage")) : ico("live") + " " + esc(t("Show on the Main Stage"));
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
      `<div style="margin-top:8px"><b>${ico("laptop", "s")} ${esc(r.name)}</b><div class="row" style="margin-top:6px"><button class="gold" data-l="take" data-id="${esc(r.id)}">${esc(t("Show on the Main Stage"))}</button>
       <button class="danger" data-l="decline" data-id="${esc(r.id)}">${esc(t("Decline"))}</button></div></div>`).join("") + `</div>` : "");
    put("l-on", s.links.length ? `<div class="card"><div class="cap">${esc(t("Connected"))}</div>` + s.links.map(l =>
      `<div style="margin-top:8px"><b>${ico(l.where === "stage" ? "live" : "laptop", "s")} ${esc(l.name)}</b> <span class="muted">${esc(l.where === "stage" ? t("on the Main Stage") : t("preview"))}</span>
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
    $("r-toggle").innerHTML = r.on ? ico("stop") + " " + esc(t("End the rehearsal")) : ico("mask") + " " + esc(t("Start a rehearsal"));
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
        <div class="row"><button class="gold big" id="t-run" style="flex:2"></button><button class="big" id="t-reset" aria-label="Reset">${ico("reset")}</button></div>
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
    $("t-run").innerHTML = tm.running ? ico("pause") + " " + esc(t("Pause")) : (pausable ? ico("play") + " " + esc(t("Start")) : esc(t("Runs by itself")));
    $("t-run").disabled = !pausable;
    $("t-minus").disabled = $("t-plus").disabled = tm.mode !== "countdown";
    $("t-reset").disabled = tm.mode === "clock";
    chips("t-roles", state.roles.map(r => [r.role, r.label]), ui.timerRole, "role");
    $("t-show").innerHTML = tm.on ? ico("stop") + " " + esc(tf("Take it off {0}", role(tm.on))) : ico("live") + " " + esc(t("Show on the screen"));
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
