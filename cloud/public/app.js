"use strict";
// Stage Cloud's dashboard: every hall at a glance, one hall live, its remote desk (the hall's own
// phone page, its requests carried over a WebSocket), the journal and the people.

const $ = id => document.getElementById(id);
const app = $("app");
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
let me = null;
let live = null;               // the open hall's WebSocket
let listTimer = 0;

// -- talking to the cloud ----------------------------------------------------------------------- //
async function call(path, body) {
  const options = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(path, options);
  let data = {};
  try { data = await r.json(); } catch (e) { /* none */ }
  if (r.status === 401 && path !== "/api/login") { me = null; route(); throw new Error("signed out"); }
  return { status: r.status, ok: r.ok && data.ok !== false, data };
}

function toast(text, bad) {
  const el = $("toast");
  el.textContent = t(text);
  el.classList.toggle("bad", !!bad);
  el.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.remove("show"), 3800);
}

function ago(ms) {
  if (!ms) return t("never");
  const s = Math.max(0, (Date.now() - ms) / 1000);
  if (s < 60) return t("just now");
  if (s < 3600) return tf("{0} min ago", Math.floor(s / 60));
  if (s < 86400) return tf("{0} h ago", Math.floor(s / 3600));
  return new Date(ms).toLocaleDateString();
}
const clock = ms => new Date(ms).toLocaleString([], { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
const isOnline = h => h.online && Date.now() - (h.lastSeen || 0) < 180000;
const can = role => ["viewer", "operator", "admin"].indexOf(me?.role) >= ["viewer", "operator", "admin"].indexOf(role);

function modal(html, wire) {
  const back = document.createElement("div");
  back.className = "modal-back";
  back.innerHTML = `<div class="modal">${html}</div>`;
  document.body.appendChild(back);
  const close = () => back.remove();
  back.addEventListener("click", e => { if (e.target === back) close(); });
  back.querySelectorAll("[data-close]").forEach(b => b.onclick = close);
  wire?.(back, close);
  back.querySelector("input, textarea")?.focus();
  return close;
}

function confirmBox(text, yes, danger) {
  return new Promise(resolve => modal(`<p>${esc(text)}</p><div class="actions">
      <button data-close>${esc(t("Cancel"))}</button><button class="${danger ? "danger" : "primary"}" id="yes">${esc(yes)}</button></div>`,
    (box, close) => { box.querySelector("#yes").onclick = () => { close(); resolve(true); };
                      box.querySelectorAll("[data-close]").forEach(b => b.addEventListener("click", () => resolve(false))); }));
}

// -- the frame: header and routing --------------------------------------------------------------- //
function header(active) {
  const links = [["#/", "Halls", "halls"]];
  if (can("operator")) links.push(["#/journal", "Journal", "journal"]);
  if (can("admin")) links.push(["#/people", "People", "people"]);
  links.push(["#/account", "Account", "account"]);
  return `<header><div class="brand"><div class="logo">▣</div>Stage Cloud</div>
    <nav>${links.map(([href, name, key]) => `<a href="${href}" class="${key === active ? "on" : ""}">${esc(t(name))}</a>`).join("")}</nav>
    <div class="who">${langSwitch()}<span>${esc(me.name)} · ${esc(t(me.role))}</span>
      <button class="small" id="out">${esc(t("Sign out"))}</button></div></header>`;
}
function langSwitch() {
  return `<div class="lang">${["ka", "en"].map(l => `<button class="${lang === l ? "on" : ""}" data-lang="${l}">${l === "ka" ? "ქარ" : "EN"}</button>`).join("")}</div>`;
}
function wireHeader() {
  $("out")?.addEventListener("click", async () => { await call("/api/logout", {}); me = null; location.hash = "#/"; route(); });
  wireLang();
}
function wireLang() {
  document.querySelectorAll("[data-lang]").forEach(b => b.onclick = () => { setLang(b.dataset.lang); route(); });
}

async function route() {
  clearInterval(listTimer);
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

// -- signing in, and the very first administrator ------------------------------------------------ //
async function signIn() {
  let setup = false;
  try { setup = (await (await fetch("/api/setup")).json()).needed; } catch (e) { /* */ }
  app.innerHTML = `<div class="center"><div class="auth card">
    <div class="spread" style="margin-bottom:8px"><div class="brand"><div class="logo">▣</div>Stage Cloud</div>${langSwitch()}</div>
    <h1>${esc(t(setup ? "First administrator" : "Sign in"))}</h1>
    <p class="lead">${esc(t(setup ? "A new Stage Cloud: make its first administrator with the setup key." : "Every hall's Stage Display Controller, in one place."))}</p>
    <form id="f">${setup ? `<label>${esc(t("Setup key"))}</label><input id="key" autocomplete="off" required>` : ""}
      <label>${esc(t("Name"))}</label><input id="name" autocomplete="username" required>
      <label>${esc(t("Password"))}</label><input id="pw" type="password" autocomplete="${setup ? "new-password" : "current-password"}" required ${setup ? 'minlength="8"' : ""}>
      <div class="error" id="err"></div>
      <button class="primary" style="width:100%;margin-top:8px">${esc(t(setup ? "Make it" : "Sign in"))}</button></form></div></div>`;
  wireLang();
  $("name").focus();
  $("f").onsubmit = async e => {
    e.preventDefault();
    const name = $("name").value, password = $("pw").value;
    if (setup) {
      const r = await call("/api/setup", { key: $("key").value, name, password });
      if (!r.ok) { $("err").textContent = t(r.data.message || "That did not work."); return; }
    }
    const r = await call("/api/login", { name, password });
    if (!r.ok) { $("err").textContent = t(r.data.message || "That did not work."); return; }
    me = { name: r.data.name, role: r.data.role };
    route();
  };
}

// -- every hall -------------------------------------------------------------------------------- //
function screenLines(screens) {
  return (screens || []).map(s => `<div class="screen"><span class="dot ${s.open ? "on" : ""}"></span>
    <span class="name">${esc(s.name)}</span><span class="what">${s.open ? esc(s.what || t("black / nothing")) : esc(t("closed"))}</span></div>`).join("");
}
function updateChip(sum) {
  const u = sum?.update || {};
  if (u.state === "ready") return `<span class="chip accent">${esc(tf("update {0} ready", u.version))}</span>`;
  if (u.state === "downloading") return `<span class="chip">${esc(tf("downloading {0}", u.version))}</span>`;
  return "";
}
function showLine(sum) {
  const parts = [];
  if (sum?.show?.name) parts.push(`${esc(t("Running order"))}: <b>${esc(sum.show.name)}</b>` +
    (sum.show.step > 0 ? ` · ${esc(tf("step {0}/{1}", sum.show.step, sum.show.steps))}${sum.show.title ? " — " + esc(sum.show.title) : ""}` : ""));
  if (sum?.slides) parts.push(`${esc(t("Slides"))}: <b>${esc(sum.slides.name)}</b> ${sum.slides.index}/${sum.slides.count}${sum.slides.live ? " · " + esc(t("live")) : ""}`);
  return parts.map(p => `<div class="line">${p}</div>`).join("");
}

async function hallsPage() {
  app.innerHTML = header("halls") + `<main><div class="spread"><div><h1>${esc(t("Halls"))}</h1>
      <p class="lead" style="margin:0">${esc(t("Every hall with Stage Display Controller, as it is now."))}</p></div>
      ${can("admin") ? `<button class="primary" id="add">＋ ${esc(t("Add a hall"))}</button>` : ""}</div>
    <div class="grid" id="halls"><div class="hint">${esc(t("Loading…"))}</div></div></main>`;
  wireHeader();
  $("add")?.addEventListener("click", addHall);
  const draw = async () => {
    let halls;
    try { halls = (await call("/api/halls")).data; } catch (e) { return; }
    if (!$("halls")) return;
    if (!halls.length) {
      $("halls").outerHTML = `<div class="card empty" id="halls">${esc(t(can("admin") ? "No halls yet. Add one, then type its code in the hall's program: Settings → Cloud." : "No halls yet."))}</div>`;
      return;
    }
    $("halls").className = "grid";
    $("halls").innerHTML = halls.map(h => {
      const sum = h.summary || {}, on = isOnline(h);
      const status = !h.paired ? `<span class="chip warn">${esc(t("not paired yet"))}</span>`
        : `<span class="row" style="gap:7px"><span class="dot ${on ? "on" : ""}"></span><span class="hint">${esc(on ? t("online") : tf("offline · {0}", ago(h.lastSeen)))}</span></span>`;
      return `<div class="card hall-card ${on ? "" : "off"}" data-id="${esc(h.id)}">
        <div class="spread" style="margin:0"><h3>${esc(h.name)}</h3>${status}</div>
        <div class="row">${sum.version ? `<span class="chip">v${esc(sum.version)}</span>` : ""}${updateChip(sum)}
          ${sum.computer ? `<span class="chip">${esc(sum.computer)}</span>` : ""}${sum.control === false ? `<span class="chip warn">${esc(t("remote desk off"))}</span>` : ""}</div>
        <div class="screens">${screenLines(sum.screens)}</div>${showLine(sum)}
        ${(sum.problems || []).length ? `<div class="problems">${sum.problems.map(p => `<span class="chip bad">${esc(p)}</span>`).join("")}</div>` : ""}
        <div class="actions">${on && can("operator") && sum.control !== false
          ? `<button class="primary small" data-desk="${esc(h.id)}">${esc(t("Remote desk"))}</button>` : ""}
          <button class="small">${esc(t("Open"))}</button></div></div>`;
    }).join("");
    document.querySelectorAll(".hall-card").forEach(c => c.onclick = e => {
      location.hash = e.target.dataset.desk ? `#/hall/${c.dataset.id}/desk` : `#/hall/${c.dataset.id}`;
    });
  };
  await draw();
  listTimer = setInterval(() => { if (!document.hidden) draw(); }, 15000);
}

function showCode(name, code) {
  modal(`<h2>${esc(tf("Pair “{0}”", name))}</h2>
    <p class="hint">${esc(t("On the hall's computer: Stage Display Controller → Settings → Cloud. Type this address and this code, then Pair. The code works once, for 30 minutes."))}</p>
    <label>${esc(t("Address"))}</label><input readonly value="${esc(location.host)}">
    <div class="code">${esc(code)}</div><div class="actions"><button class="primary" data-close>${esc(t("Done"))}</button></div>`);
}

function addHall() {
  modal(`<h2>${esc(t("Add a hall"))}</h2><form id="f"><label>${esc(t("The hall's name"))}</label><input id="n" maxlength="60" required>
    <div class="error" id="err"></div><div class="actions"><button type="button" data-close>${esc(t("Cancel"))}</button>
    <button class="primary">${esc(t("Add"))}</button></div></form>`, (box, close) => {
    box.querySelector("#f").onsubmit = async e => {
      e.preventDefault();
      const name = box.querySelector("#n").value;
      const r = await call("/api/halls", { name });
      if (!r.ok) { box.querySelector("#err").textContent = t(r.data.message || "That did not work."); return; }
      close();
      showCode(name, r.data.code);
      route();
    };
  });
}

// -- one hall, live --------------------------------------------------------------------------- //
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
  rpc(method, path, params, body) {
    return new Promise(resolve => {
      if (this.ws.readyState !== 1) return resolve({ status: 503, type: "application/json", body: '{"ok":false,"message":"disconnected"}' });
      const id = ++this.seq;
      this.pending.set(id, resolve);
      this.ws.send(JSON.stringify({ t: "rpc", id, method, path, params, body }));
      setTimeout(() => { if (this.pending.delete(id)) resolve({ status: 504, type: "application/json", body: '{"ok":false,"message":"no answer"}' }); }, 30000);
    });
  }
  close() { this.closed = true; try { this.ws.close(); } catch (e) { /* */ } }
}

async function hallPage(id) {
  const r = await call("/api/halls/" + id);
  if (!r.ok) { location.hash = "#/"; return; }
  let hall = r.data, log = hall.log || [];
  app.innerHTML = header("halls") + `<main id="hall"></main>`;
  wireHeader();
  const draw = () => {
    const st = hall.status || {}, sum = st.summary || {}, d = st.detail || {}, on = hall.online;
    const pc = d.pc || {};
    const out = $("hall");
    if (!out) return;
    const typed = $("msg")?.value || "", typing = document.activeElement?.id === "msg";   // a redraw keeps a half-written message
    out.innerHTML = `<div class="spread"><div><a href="#/" class="hint">← ${esc(t("Halls"))}</a><h1>${esc(hall.name)}</h1>
        <div class="row"><span class="dot ${on ? "on" : ""}"></span><span class="hint">${esc(on ? t("online") : tf("offline · {0}", ago(hall.lastSeen)))}</span>
        ${sum.version ? `<span class="chip">v${esc(sum.version)}</span>` : ""}${updateChip(sum)}</div></div>
        ${on && can("operator") && sum.control !== false ? `<button class="primary" id="desk">${esc(t("Remote desk"))}</button>` : ""}</div>
      <div class="cols"><div class="stack">
        <div class="card"><h2>${esc(t("Screens"))}</h2>${(sum.screens || []).length ? `<table><tr><th>${esc(t("Screen"))}</th><th>${esc(t("State"))}</th><th>${esc(t("On it"))}</th></tr>
          ${sum.screens.map(s => `<tr><td>${esc(s.name)}${s.kind === "strip" ? ` <span class="chip">${esc(t("LED strip"))}</span>` : ""}</td>
            <td><span class="row" style="gap:6px"><span class="dot ${s.open ? "on" : ""}"></span>${esc(s.open ? t("open") : t("closed"))}</span></td>
            <td>${esc(s.what || "—")}</td></tr>`).join("")}</table>` : `<p class="hint">${esc(t("No status yet."))}</p>`}
          ${showLine(sum)}</div>
        <div class="card"><h2>${esc(t("Problems and events"))}</h2>
          ${(sum.problems || []).length ? `<div class="problems" style="margin-bottom:12px">${sum.problems.map(p => `<span class="chip bad">${esc(p)}</span>`).join("")}</div>` : ""}
          <div class="log">${log.length ? log.map(e => `<div><time>${esc(clock(e.at))}</time>${esc(e.text)}</div>`).join("") : `<span class="hint">${esc(t("Nothing so far."))}</span>`}</div></div>
        ${can("operator") ? `<div class="card"><h2>${esc(t("Journal"))}</h2><div class="log" id="journal"><span class="hint">…</span></div></div>` : ""}
      </div><div class="stack">
        ${can("operator") ? `<div class="card"><h2>${esc(t("Commands"))}</h2><div class="stack" style="gap:10px">
          <textarea id="msg" rows="2" maxlength="500" placeholder="${esc(t("A message for the operator…"))}"></textarea>
          <button id="send" ${on ? "" : "disabled"}>${esc(t("Show the message on the desk"))}</button>
          <button id="check" ${on ? "" : "disabled"}>${esc(t("Look for an update"))}</button>
          <button id="install" ${on && sum.update?.state === "ready" ? "" : "disabled"}>${esc(t("Install the update now"))}</button>
          <span class="hint">${esc(t("Installing closes the program for about a minute: the stage screens go dark meanwhile."))}</span></div></div>` : ""}
        <div class="card"><h2>${esc(t("Computer"))}</h2><dl class="kv">
          <dt>${esc(t("Name"))}</dt><dd>${esc(sum.computer || hall.computer || "—")}</dd>
          <dt>${esc(t("Windows"))}</dt><dd>${esc(pc.os || "—")}</dd>
          <dt>${esc(t("On for"))}</dt><dd>${pc.uptime_h != null ? esc(tf("{0} h", pc.uptime_h)) : "—"}</dd>
          <dt>${esc(t("Program on for"))}</dt><dd>${pc.program_h != null ? esc(tf("{0} h", pc.program_h)) : "—"}</dd>
          <dt>${esc(t("Free disk"))}</dt><dd>${pc.disk_free_gb != null ? esc(pc.disk_free_gb + " GB") : "—"}</dd>
          <dt>${esc(t("Sound"))}</dt><dd>${esc(d.sound ? `${d.sound.device} · ${d.sound.master}%` : "—")}</dd>
          <dt>${esc(t("Phone remote"))}</dt><dd>${esc(d.phone ? (d.phone.on ? tf("on · {0} phone(s)", d.phone.phones) : t("off")) : "—")}</dd>
          <dt>${esc(t("Laptops"))}</dt><dd>${esc(d.share ? (d.share.on ? tf("on · {0}", d.share.laptops) : t("off")) : "—")}</dd>
          <dt>${esc(t("Scene"))}</dt><dd>${esc(d.preset || "—")}</dd>
          <dt>${esc(t("Remote desk"))}</dt><dd>${esc(sum.control === false ? t("switched off in the hall") : t("allowed"))}</dd>
          <dt>${esc(t("Last status"))}</dt><dd>${esc(ago(hall.lastSeen))}</dd></dl></div>
        ${can("admin") ? `<div class="card"><h2>${esc(t("Administration"))}</h2><div class="stack" style="gap:10px">
          <button id="rename">${esc(t("Rename…"))}</button><button id="pair">${esc(t("Pair again (new code)…"))}</button>
          <button id="remove" class="danger">${esc(t("Remove the hall…"))}</button></div></div>` : ""}
      </div></div>`;
    if ($("msg")) { $("msg").value = typed; if (typing) $("msg").focus(); }
    $("desk")?.addEventListener("click", () => location.hash = `#/hall/${id}/desk`);
    const command = async (cmd, args) => {
      const x = await call(`/api/halls/${id}/command`, { cmd, args });
      toast(x.data.message || (x.ok ? "Done." : "That did not work."), !x.ok);
      return x.ok;
    };
    $("send")?.addEventListener("click", async () => { const text = $("msg").value.trim(); if (text && await command("message", { text })) $("msg").value = ""; });
    $("check")?.addEventListener("click", () => command("check_update"));
    $("install")?.addEventListener("click", async () => {
      if (await confirmBox(t("Install the update now? The program closes, installs and opens again - about a minute with the stage screens dark."), t("Install now")))
        command("install_update", { now: true });
    });
    $("rename")?.addEventListener("click", () => modal(`<h2>${esc(t("Rename"))}</h2><form id="f"><input id="n" maxlength="60" value="${esc(hall.name)}" required>
      <div class="actions"><button type="button" data-close>${esc(t("Cancel"))}</button><button class="primary">${esc(t("Save"))}</button></div></form>`, (box, close) => {
      box.querySelector("#f").onsubmit = async e => { e.preventDefault(); const name = box.querySelector("#n").value;
        const x = await call(`/api/halls/${id}/rename`, { name }); if (x.ok) { hall.name = name; close(); draw(); } else toast(x.data.message, true); };
    }));
    $("pair")?.addEventListener("click", async () => {
      if (!await confirmBox(t("A new code: the computer that pairs with it becomes this hall, and the one paired now loses its access."), t("Make a code"))) return;
      const x = await call(`/api/halls/${id}/pair`, {});
      if (x.ok) showCode(hall.name, x.data.code); else toast(x.data.message, true);
    });
    $("remove")?.addEventListener("click", async () => {
      if (!await confirmBox(tf("Remove “{0}” from Stage Cloud? Its computer is disconnected for good (it can be paired again as a new hall).", hall.name), t("Remove"), true)) return;
      const x = await call(`/api/halls/${id}/remove`, {});
      if (x.ok) location.hash = "#/"; else toast(x.data.message, true);
    });
    if ($("journal")) call(`/api/halls/${id}/journal`).then(x => {
      if ($("journal")) $("journal").innerHTML = (x.data || []).map(j => `<div><time>${esc(clock(j.at))}</time><b>${esc(j.user)}</b> · ${esc(j.what)}</div>`).join("")
        || `<span class="hint">${esc(t("Nothing so far."))}</span>`;
    }).catch(() => {});
  };
  draw();
  live?.close();
  live = new Live(id, m => {
    if (m.t === "hello") { hall = { ...hall, status: m.status, online: m.online, lastSeen: m.lastSeen }; log = m.log || []; draw(); }
    else if (m.t === "status") { hall.status = m.status; hall.lastSeen = m.at; hall.online = true; draw(); }
    else if (m.t === "online") { hall.online = m.online; draw(); }
    else if (m.t === "event") { log.unshift(m); draw(); }
  });
}

// -- the remote desk: the hall's phone page, its requests over the WebSocket ------------------------- //
// Inside the frame (an opaque origin: the hall's page cannot reach this dashboard), fetch and the
// upload's XMLHttpRequest are handed to the dashboard, and localStorage is kept in memory.
const SHIM = `<script>(function(){
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
  app.innerHTML = `<div class="control"><div class="bar"><a href="#/hall/${esc(id)}">← ${esc(t("Back"))}</a>
      <b>${esc(hall.name)} · ${esc(t("Remote desk"))}</b><span class="row" style="gap:6px"><span class="dot" id="conn"></span><span class="hint" id="connText"></span></span></div>
    <div class="stage" id="stage"><div class="wait">${esc(t("Connecting to the hall…"))}</div></div></div>`;
  let frame = null, loaded = false;
  const setConn = on => { $("conn")?.classList.toggle("on", on); if ($("connText")) $("connText").textContent = t(on ? "connected" : "reconnecting…"); };
  const load = async () => {
    const page = await live.rpc("GET", "/", {}, null);
    if (page.status !== 200) {
      let message = "The hall did not answer.";
      try { message = JSON.parse(page.body).message || message; } catch (e) { /* */ }
      $("stage").innerHTML = `<div class="wait">${esc(t(message))}</div>`;
      return;
    }
    loaded = true;
    const html = page.body.replace(/<head>/i, "<head>" + SHIM);
    frame = document.createElement("iframe");
    frame.setAttribute("sandbox", "allow-scripts allow-forms allow-modals");
    frame.srcdoc = html;
    $("stage").innerHTML = "";
    $("stage").appendChild(frame);
  };
  live?.close();
  live = new Live(id, m => {
    if (m.t === "socket") setConn(m.on);
    if (m.t === "hello") { setConn(true); if (!m.online) $("stage").innerHTML = `<div class="wait">${esc(t("The hall is not connected."))}</div>`; else if (!loaded) load(); }
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

// -- the journal, people, my account --------------------------------------------------------------- //
async function journalPage() {
  app.innerHTML = header("journal") + `<main><h1>${esc(t("Journal"))}</h1><p class="lead">${esc(t("Who did what, and when."))}</p>
    <div class="card"><table id="j"><tr><td class="hint">…</td></tr></table></div></main>`;
  wireHeader();
  const rows = (await call("/api/journal")).data || [];
  $("j").innerHTML = `<tr><th>${esc(t("When"))}</th><th>${esc(t("Who"))}</th><th>${esc(t("Hall"))}</th><th>${esc(t("What"))}</th></tr>` +
    rows.map(j => `<tr><td style="white-space:nowrap">${esc(clock(j.at))}</td><td>${esc(j.user)}</td><td>${esc(j.hallName)}</td><td>${esc(j.what)}</td></tr>`).join("");
}

async function peoplePage() {
  app.innerHTML = header("people") + `<main><div class="spread"><div><h1>${esc(t("People"))}</h1>
    <p class="lead" style="margin:0">${esc(t("Viewers see the halls. Operators also send commands and use the remote desk. Administrators also add halls and people."))}</p></div>
    <button class="primary" id="add">＋ ${esc(t("Add a person"))}</button></div><div class="card"><table id="u"></table></div></main>`;
  wireHeader();
  const roles = ["viewer", "operator", "admin"];
  const draw = async () => {
    const users = (await call("/api/users")).data || [];
    $("u").innerHTML = `<tr><th>${esc(t("Name"))}</th><th>${esc(t("Role"))}</th><th></th></tr>` + users.map(u => `<tr><td>${esc(u.name)}${u.name === me.name ? ` <span class="chip">${esc(t("you"))}</span>` : ""}</td>
      <td><select data-role="${esc(u.name)}" style="width:auto">${roles.map(r => `<option value="${r}" ${r === u.role ? "selected" : ""}>${esc(t(r))}</option>`).join("")}</select></td>
      <td style="text-align:right"><button class="small" data-pw="${esc(u.name)}">${esc(t("New password…"))}</button>
        <button class="small danger" data-rm="${esc(u.name)}">${esc(t("Remove"))}</button></td></tr>`).join("");
    document.querySelectorAll("[data-role]").forEach(s => s.onchange = async () => {
      const x = await call("/api/users", { op: "role", name: s.dataset.role, role: s.value }); toast(x.ok ? "Saved." : x.data.message, !x.ok); draw(); });
    document.querySelectorAll("[data-rm]").forEach(b => b.onclick = async () => {
      if (!await confirmBox(tf("Remove {0}?", b.dataset.rm), t("Remove"), true)) return;
      const x = await call("/api/users", { op: "remove", name: b.dataset.rm }); toast(x.ok ? "Removed." : x.data.message, !x.ok); draw(); });
    document.querySelectorAll("[data-pw]").forEach(b => b.onclick = () => personForm(b.dataset.pw, draw));
  };
  $("add").onclick = () => personForm(null, draw);
  draw();
}

function personForm(name, done) {
  modal(`<h2>${esc(name ? tf("New password for {0}", name) : t("Add a person"))}</h2><form id="f">
    ${name ? "" : `<label>${esc(t("Name"))}</label><input id="n" maxlength="40" required>
      <label>${esc(t("Role"))}</label><select id="r">${["viewer", "operator", "admin"].map(r => `<option value="${r}" ${r === "operator" ? "selected" : ""}>${esc(t(r))}</option>`).join("")}</select>`}
    <label>${esc(t("Password (8 or more characters)"))}</label><input id="p" type="text" minlength="8" required autocomplete="off">
    <div class="error" id="err"></div><div class="actions"><button type="button" data-close>${esc(t("Cancel"))}</button>
    <button class="primary">${esc(t("Save"))}</button></div></form>`, (box, close) => {
    box.querySelector("#f").onsubmit = async e => {
      e.preventDefault();
      const body = name ? { op: "password", name, password: box.querySelector("#p").value }
        : { op: "add", name: box.querySelector("#n").value, role: box.querySelector("#r").value, password: box.querySelector("#p").value };
      const x = await call("/api/users", body);
      if (!x.ok) { box.querySelector("#err").textContent = t(x.data.message || "That did not work."); return; }
      close(); toast("Saved."); done();
    };
  });
}

function accountPage() {
  app.innerHTML = header("account") + `<main><h1>${esc(t("Account"))}</h1><p class="lead">${esc(me.name)} · ${esc(t(me.role))}</p>
    <div class="card" style="max-width:440px"><h2>${esc(t("Change my password"))}</h2><form id="f">
      <label>${esc(t("Password now"))}</label><input id="o" type="password" autocomplete="current-password" required>
      <label>${esc(t("New password (8 or more characters)"))}</label><input id="p" type="password" minlength="8" autocomplete="new-password" required>
      <div class="error" id="err"></div><button class="primary">${esc(t("Save"))}</button></form>
      <p class="hint">${esc(t("Changing it signs you out everywhere."))}</p></div></main>`;
  wireHeader();
  $("f").onsubmit = async e => {
    e.preventDefault();
    const x = await call("/api/password", { old: $("o").value, password: $("p").value });
    if (!x.ok) { $("err").textContent = t(x.data.message || "That did not work."); return; }
    toast("Saved."); me = null; route();
  };
}

route();
