// The cloud on this computer (npx wrangler dev): first administrator, signing in, lock-outs,
// a hall paired with a code and connected, its status, commands, the remote desk's requests,
// what each role may do, and what strangers may not.   node test/server_test.mjs
import { readFileSync } from "node:fs";
import { createHmac } from "node:crypto";

const BASE = process.env.CLOUD || "http://127.0.0.1:8787";
const SETUP_KEY = /SETUP_KEY=(\S+)/.exec(readFileSync(new URL("../.dev.vars", import.meta.url), "utf8"))[1];
const failures = [];
const check = (name, ok, extra = "") => {
  console.log((ok ? "PASS  " : "FAIL  ") + name, ok ? "" : JSON.stringify(extra).slice(0, 300));
  if (!ok) failures.push(name);
};
const sleep = ms => new Promise(r => setTimeout(r, ms));

// -- a phone with an authenticator app: the code for a secret, a time step not used yet --------- //
function unbase32(text) {
  const A = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"; let bits = 0, value = 0; const out = [];
  for (const c of text) { value = (value << 5) | A.indexOf(c); bits += 5; if (bits >= 8) { out.push((value >>> (bits - 8)) & 255); bits -= 8; } }
  return Buffer.from(out);
}
function totp(secret, step) {
  const counter = Buffer.alloc(8); counter.writeBigUInt64BE(BigInt(step));
  const mac = createHmac("sha1", unbase32(secret)).update(counter).digest();
  const at = mac[19] & 15;
  return String((mac.readUInt32BE(at) & 0x7fffffff) % 1000000).padStart(6, "0");
}
const phone = { secrets: {}, used: {} };
async function codeFor(name) {
  // a code works once: the next step not used yet (the cloud takes one step ahead, for a clock a little off)
  let step = Math.max(Math.floor(Date.now() / 30000), (phone.used[name] || 0) + 1);
  while (step > Math.floor(Date.now() / 30000) + 1) { await sleep(1000); }
  phone.used[name] = step;
  return totp(phone.secrets[name], step);
}

class Browser {
  constructor() { this.cookie = ""; }
  async call(path, body, extra = {}) {
    const headers = { Origin: BASE, ...(this.cookie ? { Cookie: this.cookie } : {}), ...(extra.headers || {}) };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const r = await fetch(BASE + path, { method: body === undefined ? "GET" : "POST", headers,
                                         body: body === undefined ? undefined : JSON.stringify(body) });
    const set = r.headers.get("set-cookie");
    if (set) this.cookie = set.split(";")[0].endsWith("=") ? "" : set.split(";")[0];
    let data = null;
    try { data = await r.json(); } catch (e) { /* not JSON */ }
    return { status: r.status, data, set };
  }
  // signing in all the way: the password, the code, a given password changed, the app set up
  async signIn(name, password, newPassword) {
    let x = await this.call("/api/login", { name, password });
    if (x.data?.need === "code") x = await this.call("/api/login/code", { ticket: x.data.ticket, code: await codeFor(name.toLowerCase()) });
    if (!x.data?.ok) return x;
    let me = (await this.call("/api/me")).data;
    if (me.need === "password") {
      await this.call("/api/password", { old: password, password: newPassword });
      me = (await this.call("/api/me")).data;
    }
    if (me.need === "setup2fa") me = await this.setUp2fa(name);
    return { status: 200, data: { ok: true, ...me } };
  }
  async setUp2fa(name) {
    const start = await this.call("/api/2fa/start", {});
    phone.secrets[name.toLowerCase()] = start.data.secret;
    const on = await this.call("/api/2fa/enable", { code: await codeFor(name.toLowerCase()) });
    this.recovery = on.data.codes;
    return (await this.call("/api/me")).data;
  }
  socket(path) {
    return open(BASE.replace("http", "ws") + path, { Origin: BASE, Cookie: this.cookie });
  }
}

function open(url, headers) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(url, { headers });
    ws.inbox = [];
    ws.onmessage = e => ws.inbox.push(JSON.parse(e.data));
    ws.onopen = () => resolve(ws);
    ws.onclose = e => { ws.closedWith = e.code; };
    ws.onerror = e => reject(new Error("socket refused"));
  });
}
async function waitFor(ws, test, ms = 5000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const found = ws.inbox.find(test);
    if (found) { ws.inbox.splice(ws.inbox.indexOf(found), 1); return found; }
    await sleep(20);
  }
  return null;
}

const admin = new Browser();
// -- the first administrator -------------------------------------------------------------------- //
let r = await admin.call("/api/setup");
const fresh = r.data?.needed;
check("a new cloud asks for its first administrator", fresh === true, r.data);
r = await admin.call("/api/setup", { key: "wrong", name: "boss", password: "long enough pw" });
check("... only with the setup key", r.status === 403);
r = await admin.call("/api/setup", { key: SETUP_KEY, name: "boss", password: "short" });
check("... and a password of 8 or more", r.status === 400);
r = await admin.call("/api/setup", { key: SETUP_KEY, name: "Boss", password: "boss-password-1" });
check("first administrator made", r.data?.ok, r.data);
r = await admin.call("/api/setup", { key: SETUP_KEY, name: "Other", password: "another-password" });
check("... once only", !r.data?.ok);

// -- signing in ------------------------------------------------------------------------------- //
r = await admin.call("/api/halls");
check("nothing without signing in", r.status === 401);
r = await admin.call("/api/login", { name: "boss", password: "boss-password-1" });
check("signed in (name in any case)", r.data?.ok && r.data.role === "admin" && /HttpOnly/.test(r.set) && /SameSite=Strict/.test(r.set), r);
r = await admin.call("/api/me");
check("who am I", r.data?.name === "Boss" && r.data.role === "admin", r.data);

// -- two-step sign-in ------------------------------------------------------------------------- //
check("an administrator must set up the authenticator first", r.data?.need === "setup2fa" && r.data.totpRequired === true, r.data);
r = await admin.call("/api/halls");
check("... nothing else before it", r.status === 403 && r.data?.need === "setup2fa", r);
r = await admin.call("/api/2fa/start", {});
check("the app's secret and its QR address", /^[A-Z2-7]{32}$/.test(r.data?.secret || "") && r.data.uri.startsWith("otpauth://totp/Stage%20Cloud%3ABoss?secret="), r.data);
phone.secrets.boss = r.data.secret;
r = await admin.call("/api/2fa/enable", { code: "000000" });
check("a wrong code does not turn it on", !r.data?.ok);
r = await admin.call("/api/2fa/enable", { code: await codeFor("boss") });
const bossRecovery = r.data?.codes || [];
check("the right code turns it on, with ten recovery codes", r.data?.ok && bossRecovery.length === 10 && /^[a-z2-9]{5}-[a-z2-9]{5}$/.test(bossRecovery[0]), r.data);
r = await admin.call("/api/me");
check("... and nothing waits any more", r.data?.need === "" && r.data.totp === true, r.data);

const elsewhere = new Browser();
r = await elsewhere.call("/api/login", { name: "boss", password: "boss-password-1" });
check("the password alone is not enough now: a code is asked for", r.data?.need === "code" && r.data.ticket && !r.set, r);
const ticket = r.data.ticket;
r = await elsewhere.call("/api/login/code", { ticket, code: "123456" });
check("a wrong code: refused", r.status === 401 && !r.set);
r = await elsewhere.call("/api/login/code", { ticket, code: await codeFor("boss") });
check("the right code: signed in", r.data?.ok && /HttpOnly/.test(r.set || ""), r);
const reused = phone.used.boss;
r = await new Browser().call("/api/login", { name: "boss", password: "boss-password-1" });
r = await new Browser().call("/api/login/code", { ticket: r.data.ticket, code: totp(phone.secrets.boss, reused) });
check("a code works once", r.status === 401);
const third = new Browser();
r = await third.call("/api/login", { name: "boss", password: "boss-password-1" });
r = await third.call("/api/login/code", { ticket: r.data.ticket, code: bossRecovery[0].toUpperCase().replace("-", " ") });
check("a recovery code signs in (any case, any spacing)", r.data?.ok && r.data.recoveryLeft === 9, r.data);
r = await new Browser().call("/api/login", { name: "boss", password: "boss-password-1" });
r = await new Browser().call("/api/login/code", { ticket: r.data.ticket, code: bossRecovery[0] });
check("... once", r.status === 401);
r = await admin.call("/api/sessions");
check("my sessions: where, and which is this one", r.data?.length === 3 && r.data.filter(x => x.current).length === 1, r.data);
r = await admin.call("/api/sessions", { all: true });
check("signing out everywhere else", r.data?.ok && r.data.ended === 2 && (await elsewhere.call("/api/me")).status === 401
      && (await admin.call("/api/me")).status === 200, r.data);
r = await admin.call("/api/2fa/disable", { password: "boss-password-1" });
check("an administrator cannot turn it off", !r.data?.ok);
r = await admin.call("/api/halls", { name: "x" }, { headers: { Origin: "https://evil.example" } });
check("another site cannot act for me", r.status === 403);

// lock-out: five wrong passwords
const stranger = new Browser();
await admin.call("/api/users", { op: "add", name: "Nino", password: "nino-password" });
for (let i = 0; i < 5; i++) await stranger.call("/api/login", { name: "nino", password: "guess" + i });
r = await stranger.call("/api/login", { name: "nino", password: "nino-password" });
check("five wrong tries: locked, even with the right password", r.status === 429, r);

// -- people --------------------------------------------------------------------------------- //
r = await admin.call("/api/users", { op: "add", name: "Gio", password: "gio-password" });
check("a person added", r.data?.ok, r.data);
r = await admin.call("/api/users", { op: "add", name: "gio", password: "gio-password" });
check("names are unique", !r.data?.ok);
r = await admin.call("/api/users", { op: "remove", name: "Boss" });
check("the last administrator stays", !r.data?.ok);
r = await admin.call("/api/users", { op: "add", name: "Ana", password: "ana-password" });
const operator = new Browser();
r = await operator.call("/api/login", { name: "ana", password: "ana-password" });
const meFirst = (await operator.call("/api/me")).data, hallsFirst = (await operator.call("/api/halls")).status;
check("a password an administrator gave: changed first", meFirst?.need === "password" && hallsFirst === 403, [r.status, r.data, meFirst, hallsFirst]);
r = await operator.call("/api/password", { old: "ana-password", password: "ana-password" });
check("... to a new one", !r.data?.ok);
r = await operator.signIn("ana", "ana-password", "ana-own-password");
check("a member with no rights yet signs in: no authenticator needed", r.data?.role === "member" && r.data.need === "" && !r.data.totp, r.data);
const viewer = new Browser();
r = await viewer.signIn("gio", "gio-password", "gio-own-password");
check("... and sees no hall", r.data?.ok && Object.keys(r.data.halls).length === 0 && (await viewer.call("/api/halls")).data?.length === 0, r.data);

// -- a hall ---------------------------------------------------------------------------------- //
r = await operator.call("/api/halls", { name: "x" });
check("only main administrators add halls", r.status === 403);
r = await admin.call("/api/halls", { name: "Assembly Hall" });
const hallId = r.data?.id, code = r.data?.code;
check("a hall added, with a pairing code", r.data?.ok && /^[A-Z0-9]{4}-[A-Z0-9]{4}$/.test(code), r.data);
r = await viewer.call("/api/halls/" + hallId);
check("a hall one was not given: not there", r.status === 404 && (await viewer.call("/api/halls")).data?.length === 0, r);
let notGiven = false;
try { await viewer.socket(`/api/halls/${hallId}/live`); } catch (e) { notGiven = true; }
check("... nor its live page", notGiven);

// -- rights in the hall ------------------------------------------------------------------------- //
r = await operator.call("/api/users", { op: "grant", name: "Ana", hall: hallId, role: "operator" });
check("only those who manage a hall give rights in it", r.status === 403, r);
r = await admin.call("/api/users", { op: "grant", name: "Ana", hall: hallId, role: "operator" });
check("Ana: operator in the hall", r.data?.ok, r.data);
r = await admin.call("/api/users", { op: "grant", name: "Gio", hall: hallId, role: "viewer" });
r = await admin.call("/api/users", { op: "grant", name: "Boss", hall: hallId, role: "viewer" });
check("a main administrator needs no rights", !r.data?.ok);
r = await admin.call("/api/users", { op: "grant", name: "Gio", hall: hallId, role: "owner" });
check("an unknown role is refused", !r.data?.ok);
r = await operator.call("/api/halls");
check("rights that change things: the authenticator first", r.status === 403 && r.data?.need === "setup2fa", r);
const anaMe = await operator.setUp2fa("ana");
check("... then the hall is there, with what Ana may do", anaMe?.need === "" && anaMe.halls?.[hallId]?.rights.includes("control")
      && !anaMe.halls[hallId].rights.includes("updates"), anaMe);
r = await viewer.call("/api/halls");
check("a viewer sees the hall given, and needs no authenticator", r.data?.length === 1 && r.data[0].access.role === "viewer", r.data);
const pair = async (c, ip) => {
  const x = await fetch(BASE + "/hall/pair", { method: "POST", headers: { "Content-Type": "application/json", "X-SDC-Client": "hall" },
                                               body: JSON.stringify({ code: c, computer: "STAGE-PC" }) });
  return { status: x.status, data: await x.json() };
};
r = await pair("ZZZZ-ZZZZ");
check("a wrong code pairs nothing", r.status === 403);
r = await pair(code.toLowerCase().replace("-", " "));
const token = r.data?.token;
check("the hall pairs with its code (any case, any spacing)", r.data?.ok && r.data.id === hallId && token, r.data);
r = await pair(code);
check("a code works once", r.status === 403);

let refused = false;
try { await open(BASE.replace("http", "ws") + "/hall/connect", { Authorization: "Bearer nonsense" }); } catch (e) { refused = true; }
check("a wrong token cannot connect", refused);
const hall = await open(BASE.replace("http", "ws") + "/hall/connect", { Authorization: "Bearer " + token });
check("the hall connects", hall.readyState === 1);
await sleep(300);
r = await admin.call("/api/halls");
check("the list says it is online", r.data?.[0]?.online === true && r.data[0].computer === "STAGE-PC", r.data);

const status = { summary: { version: "1.3.0", screens: [{ role: "main", name: "Main Stage", open: true, what: "intro.mp4" }] },
                 detail: { disk: 123 } };
hall.send(JSON.stringify({ t: "status", status }));
await sleep(400);
r = await admin.call("/api/halls/" + hallId);
check("its status is kept", r.data?.status?.summary?.version === "1.3.0" && r.data.online, r.data);
r = await admin.call("/api/halls");
check("... and its summary is in the list", r.data?.[0]?.summary?.screens?.[0]?.what === "intro.mp4", r.data?.[0]);
hall.send(JSON.stringify({ t: "event", level: "warn", text: "a video would not play" }));

// -- a second computer with the same pairing ----------------------------------------------------- //
let twinRefused = false;
try { await open(BASE.replace("http", "ws") + "/hall/connect", { Authorization: "Bearer " + token, "CF-Connecting-IP": "203.0.113.9" }); }
catch (e) { twinRefused = true; }
await sleep(300);
check("a second computer from elsewhere does not push the live hall off", twinRefused && hall.readyState === 1, [twinRefused, hall.readyState]);
r = await admin.call("/api/halls/" + hallId);
check("... and the hall's page says so", (r.data?.log || []).some(e => /Another computer \(203\.0\.113\.9\)/.test(e.text)), r.data?.log);

// -- commands -------------------------------------------------------------------------------- //
const answering = (async () => {
  const cmd = await waitFor(hall, m => m.t === "cmd", 5000);
  hall.send(JSON.stringify({ t: "reply", id: cmd.id, ok: true, message: "shown: " + cmd.args.text + " by " + cmd.user }));
})();
r = await operator.call(`/api/halls/${hallId}/command`, { cmd: "message", args: { text: "Event at 14:00" } });
await answering;
check("an operator's message reaches the hall and it answers", r.data?.ok && r.data.message === "shown: Event at 14:00 by Ana", r.data);
r = await viewer.call(`/api/halls/${hallId}/command`, { cmd: "message", args: { text: "hi" } });
check("a viewer cannot send commands", r.status === 403);
r = await operator.call(`/api/halls/${hallId}/command`, { cmd: "format_disk" });
check("unknown commands are refused", r.status === 400);
r = await operator.call(`/api/halls/${hallId}/command`, { cmd: "check_update" });
check("an operator does not update the hall's program", r.status === 403, r);
r = await operator.call(`/api/halls/${hallId}/pair`, {});
check("... nor pair it again", r.status === 403, r);
r = await admin.call(`/api/halls/${hallId}/command`, { cmd: "check_update" });
check("a hall that does not answer: said so (in 15 s)", !r.data?.ok && /did not answer/.test(r.data?.message), r.data);

// -- the remote desk over a WebSocket --------------------------------------------------------- //
const desk = await operator.socket(`/api/halls/${hallId}/live`);
const hello = await waitFor(desk, m => m.t === "hello");
check("the remote desk gets the hall's status at once", hello?.status?.summary?.version === "1.3.0" && hello.online
      && hello.log?.some(e => e.text === "a video would not play") && hello.you?.role === "operator" && hello.you.rights.includes("web"), hello);
desk.send(JSON.stringify({ t: "rpc", id: 7, method: "POST", path: "/api/action", body: JSON.stringify({ action: "text_show", role: "main" }) }));
const asked = await waitFor(hall, m => m.t === "rpc");
check("its request reaches the hall, with who asked", asked?.path === "/api/action" && asked.user === "Ana" && asked.method === "POST", asked);
hall.send(JSON.stringify({ t: "reply", id: asked.id, status: 200, type: "application/json", body: '{"ok":true,"message":"done"}' }));
const back = await waitFor(desk, m => m.t === "reply" && m.id === 7);
check("... and the answer comes back to that desk only", back?.status === 200 && JSON.parse(back.body).message === "done", back);
hall.send(JSON.stringify({ t: "status", status: { ...status, summary: { ...status.summary, version: "1.3.1" } } }));
const pushed = await waitFor(desk, m => m.t === "status");
check("status changes are pushed to the desk", pushed?.status?.summary?.version === "1.3.1");

for (const [what, body, path] of [["locking the desk", { action: "desk_lock" }], ["an action the cloud does not know", { action: "format_disk" }],
                                  ["another request", {}, "/api/pin"]]) {
  desk.send(JSON.stringify({ t: "rpc", id: 30, method: "POST", path: path || "/api/action", body: JSON.stringify(body) }));
  const answer = await waitFor(desk, m => m.t === "reply" && m.id === 30);
  check(`an operator's desk: refused, ${what}`, answer?.status === 403 && !(await waitFor(hall, m => m.t === "rpc", 300)), answer);
}

const watching = await viewer.socket(`/api/halls/${hallId}/live`);
await waitFor(watching, m => m.t === "hello");
watching.send(JSON.stringify({ t: "rpc", id: 1, method: "POST", path: "/api/action", body: '{"action":"screen_black"}' }));
const no = await waitFor(watching, m => m.t === "reply" && m.id === 1);
check("a viewer's remote desk only looks", no?.status === 403 && !(await waitFor(hall, m => m.t === "rpc", 500)), no);
watching.send(JSON.stringify({ t: "rpc", id: 2, method: "GET", path: "/api/state" }));
check("... but may read", (await waitFor(hall, m => m.t === "rpc" && m.method === "GET"))?.path === "/api/state");

let crossSite = false;
try { await open(BASE.replace("http", "ws") + `/api/halls/${hallId}/live`, { Origin: "https://evil.example", Cookie: operator.cookie }); }
catch (e) { crossSite = true; }
check("another site cannot open the remote desk", crossSite);

r = await operator.call("/api/journal");
const texts = (r.data || []).map(j => j.what);
check("the journal has who did what", texts.some(t => t.startsWith("message: Event at 14:00")) && texts.includes("remote: text_show (main)")
      && texts.some(t => t.startsWith("hall computer paired")), texts.slice(0, 10));
r = await viewer.call("/api/journal");
check("viewers do not read the journal", r.status === 403);

r = await viewer.call(`/api/halls/${hallId}/journal`);
check("... nor a hall's journal", r.status === 403);

// -- a hall administrator --------------------------------------------------------------------- //
r = await admin.call("/api/users", { op: "add", name: "Dato", password: "dato-password", hall: hallId, hallRole: "halladmin" });
check("a hall administrator added, straight into the hall", r.data?.ok, r.data);
const hallAdmin = new Browser();
r = await hallAdmin.signIn("dato", "dato-password", "dato-own-password");
check("... signs in with the authenticator", r.data?.ok && r.data.totp && r.data.halls?.[hallId]?.rights.includes("manage"), r.data);
r = await admin.call("/api/halls", { name: "Gym" });
const gymId = r.data?.id;
r = await hallAdmin.call("/api/users");
check("a hall administrator sees the people, with rights in their hall only",
      r.status === 200 && r.data.some(u => u.name === "Ana" && u.grants.length === 1) && r.data.every(u => u.totp === undefined), r.data);
r = await hallAdmin.call("/api/users", { op: "grant", name: "Gio", hall: hallId, role: "technician" });
check("... gives rights in their hall", r.data?.ok, r.data);
r = await hallAdmin.call("/api/users", { op: "grant", name: "Gio", hall: gymId, role: "viewer" });
check("... but not in another", r.status === 403, r);
r = await hallAdmin.call("/api/users", { op: "role", name: "Gio", role: "admin" });
check("... makes nobody a main administrator", r.status === 403);
r = await hallAdmin.call("/api/users", { op: "remove", name: "Gio" });
check("... removes nobody", r.status === 403);
r = await hallAdmin.call("/api/users", { op: "grant", name: "Dato", hall: hallId, role: "viewer" });
check("... and does not change their own rights", !r.data?.ok);
r = await hallAdmin.call("/api/users", { op: "add", name: "Lika", password: "lika-password", hall: hallId, hallRole: "operator" });
check("... adds a person to their hall", r.data?.ok, r.data);
r = await hallAdmin.call("/api/users", { op: "add", name: "Mari", password: "mari-password" });
check("... but only into their hall", r.status === 403);
const allBut = ["control", "web", "files", "message", "journal", "desk", "pair", "manage"];
r = await admin.call("/api/users", { op: "grant", name: "Dato", hall: hallId, role: "halladmin", rights: allBut });
check("a right taken away from one person", r.data?.ok && (await hallAdmin.call("/api/me")).data?.halls?.[hallId]?.rights.includes("updates") === false);
r = await hallAdmin.call("/api/users", { op: "grant", name: "Lika", hall: hallId, role: "technician" });
check("... they cannot give it to others", r.status === 400 && /only rights you have/.test(r.data?.message), r.data);
r = await hallAdmin.call("/api/users", { op: "grant", name: "Gio", hall: hallId, role: "viewer" });
check("... nor change someone who has it", !r.data?.ok, r.data);
r = await admin.call("/api/users", { op: "grant", name: "Gio", hall: hallId, role: "viewer" });
r = await hallAdmin.call("/api/journal");
check("a hall administrator's journal: their hall only", r.status === 200 && r.data.length > 0 && r.data.every(j => j.hall === hallId), r.data?.slice(0, 3));
r = await hallAdmin.call(`/api/halls/${hallId}/rename`, { name: "Assembly Hall" });
check("... and may rename it", r.data?.ok, r.data);
r = await hallAdmin.call(`/api/halls/${hallId}/remove`, {});
check("... but not remove it", r.status === 403);
r = await admin.call("/api/users", { op: "sessions", name: "Dato" });
check("a main administrator sees someone's sessions", r.data?.sessions?.length === 1, r.data);
r = await admin.call("/api/users", { op: "signout", name: "Dato" });
check("... and signs them out everywhere", r.data?.ended === 1 && (await hallAdmin.call("/api/me")).status === 401, r.data);
await admin.call(`/api/halls/${gymId}/remove`, {});

// -- the web from the cloud: web addresses only ------------------------------------------------- //
for (const [url, ok] of [["file:///C:/Users/x/secret.pdf", false], ["C:\\Users\\x\\a.pdf", false], ["\\\\server\\share", false],
                         ["chrome://settings", false], ["javascript:alert(1)", false], ["https://kahoot.it", true], ["canva.com/design/abc", true]]) {
  desk.send(JSON.stringify({ t: "rpc", id: 40, method: "POST", path: "/api/action", body: JSON.stringify({ action: "web_open", url }) }));
  if (ok) {
    const there = await waitFor(hall, m => m.t === "rpc" && m.path === "/api/action");
    check(`a web address reaches the hall: ${url}`, !!there);
    hall.send(JSON.stringify({ t: "reply", id: there.id, status: 200, type: "application/json", body: '{"ok":true}' }));
    await waitFor(desk, m => m.t === "reply" && m.id === 40);
  } else {
    const answer = await waitFor(desk, m => m.t === "reply" && m.id === 40);
    check(`not a web address, refused: ${url}`, answer?.status === 403 && !(await waitFor(hall, m => m.t === "rpc", 300)), answer);
  }
}

// -- the site's own pages: security headers ---------------------------------------------------- //
let page = await fetch(BASE + "/");
let csp = page.headers.get("content-security-policy") || "";
check("the dashboard: its own scripts only, never framed", /script-src 'self'(;|$)/.test(csp) && /frame-ancestors 'none'/.test(csp)
      && page.headers.get("x-frame-options") === "DENY" && page.headers.get("x-content-type-options") === "nosniff", csp);
page = await fetch(BASE + "/desk-frame");
csp = page.headers.get("content-security-policy") || "";
check("the remote desk's frame: inline scripts, reaches nothing, framed by this site only",
      page.status === 200 && /script-src 'unsafe-inline'/.test(csp) && /connect-src 'none'/.test(csp) && csp.includes("frame-ancestors " + BASE)
      && !page.headers.get("x-frame-options"), [page.status, csp]);
r = await admin.call("/api/me");
check("API answers carry them too", r.status === 200);

// -- rights that change while a desk is open ---------------------------------------------------- //
r = await admin.call("/api/users", { op: "grant", name: "Ana", hall: hallId, role: "viewer" });
await sleep(300);
check("new rights close the open desk at once", desk.closedWith === 4401, desk.closedWith);
const again1 = await operator.socket(`/api/halls/${hallId}/live`);
const hello2 = await waitFor(again1, m => m.t === "hello");
check("... and the desk opened again has the new role", hello2?.you?.role === "viewer", hello2?.you);
again1.send(JSON.stringify({ t: "rpc", id: 9, method: "POST", path: "/api/action", body: '{"action":"screen_black"}' }));
check("... which only looks", (await waitFor(again1, m => m.t === "reply" && m.id === 9))?.status === 403);
r = await admin.call("/api/users", { op: "remove", name: "Gio" });
await sleep(300);
check("removing someone closes their live page", watching.closedWith === 4401, watching.closedWith);
await operator.call("/api/logout", {});
await sleep(300);
check("signing out closes the desks of that session", again1.closedWith === 4401, again1.closedWith);

// -- pairing again, going offline, removing ------------------------------------------------------ //
const watch = await admin.socket(`/api/halls/${hallId}/live`);
await waitFor(watch, m => m.t === "hello");
r = await admin.call(`/api/halls/${hallId}/pair`, {});
const second = await pair(r.data.code);
check("pairing again gives a new token", second.data?.ok && second.data.token !== token);
const closed = await waitFor(watch, m => m.t === "online", 300);
const again = await open(BASE.replace("http", "ws") + "/hall/connect", { Authorization: "Bearer " + second.data.token, "CF-Connecting-IP": "198.51.100.7" });
await sleep(300);
check("pairing again, from another computer: the new one takes over", again.readyState === 1 && hall.readyState >= 2, [hall.readyState, closed]);
let oldRefused = false;
try { await open(BASE.replace("http", "ws") + "/hall/connect", { Authorization: "Bearer " + token }); } catch (e) { oldRefused = true; }
check("the old token no longer works", oldRefused);
again.close();
const off = await waitFor(watch, m => m.t === "online" && m.online === false, 3000);
r = await admin.call("/api/halls");
check("closing: offline, in the desk and the list", off && r.data?.[0]?.online === false, r.data?.[0]);

r = await admin.call("/api/password", { old: "wrong", password: "new-boss-password" });
check("own password: the old one is needed", !r.data?.ok);
await operator.signIn("ana", "ana-own-password");
r = await operator.call(`/api/halls/${hallId}/remove`, {});
check("only main administrators remove halls", r.status === 403);
r = await admin.call(`/api/halls/${hallId}/remove`, {});
r = await admin.call("/api/halls");
check("a hall removed", r.data?.length === 0, r.data);
r = await admin.call("/api/users", { op: "reset2fa", name: "Ana" });
const anaAgain = new Browser();
r = await anaAgain.call("/api/login", { name: "ana", password: "ana-own-password" });
check("a lost phone: the administrator resets it - the password alone signs in again (a viewer by now)",
      !r.data?.need && (await anaAgain.call("/api/me")).data?.totp === false, r.data);
r = await admin.call("/api/logout", {});
r = await admin.call("/api/me");
check("signed out", r.status === 401);

watch.close();
console.log("\nFAILURES:", failures.length ? failures : "none");
process.exit(failures.length ? 1 : 0);
