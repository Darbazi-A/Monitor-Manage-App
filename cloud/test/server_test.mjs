// The cloud on this computer (npx wrangler dev): first administrator, signing in, lock-outs,
// a hall paired with a code and connected, its status, commands, the remote desk's requests,
// what each role may do, and what strangers may not.   node test/server_test.mjs
import { readFileSync } from "node:fs";

const BASE = process.env.CLOUD || "http://127.0.0.1:8787";
const SETUP_KEY = /SETUP_KEY=(\S+)/.exec(readFileSync(new URL("../.dev.vars", import.meta.url), "utf8"))[1];
const failures = [];
const check = (name, ok, extra = "") => {
  console.log((ok ? "PASS  " : "FAIL  ") + name, ok ? "" : JSON.stringify(extra).slice(0, 300));
  if (!ok) failures.push(name);
};
const sleep = ms => new Promise(r => setTimeout(r, ms));

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
r = await admin.call("/api/halls", { name: "x" }, { headers: { Origin: "https://evil.example" } });
check("another site cannot act for me", r.status === 403);

// lock-out: five wrong passwords
const stranger = new Browser();
await admin.call("/api/users", { op: "add", name: "Nino", role: "operator", password: "nino-password" });
for (let i = 0; i < 5; i++) await stranger.call("/api/login", { name: "nino", password: "guess" + i });
r = await stranger.call("/api/login", { name: "nino", password: "nino-password" });
check("five wrong tries: locked, even with the right password", r.status === 429, r);

// -- people --------------------------------------------------------------------------------- //
r = await admin.call("/api/users", { op: "add", name: "Gio", role: "viewer", password: "gio-password" });
check("a viewer added", r.data?.ok, r.data);
r = await admin.call("/api/users", { op: "add", name: "gio", role: "viewer", password: "gio-password" });
check("names are unique", !r.data?.ok);
r = await admin.call("/api/users", { op: "remove", name: "Boss" });
check("the last administrator stays", !r.data?.ok);
r = await admin.call("/api/users", { op: "add", name: "Ana", role: "operator", password: "ana-password" });
const operator = new Browser();
r = await operator.call("/api/login", { name: "ana", password: "ana-password" });
check("an operator signs in", r.data?.role === "operator");
const viewer = new Browser();
await viewer.call("/api/login", { name: "gio", password: "gio-password" });

// -- a hall ---------------------------------------------------------------------------------- //
r = await operator.call("/api/halls", { name: "x" });
check("only administrators add halls", r.status === 403);
r = await admin.call("/api/halls", { name: "Assembly Hall" });
const hallId = r.data?.id, code = r.data?.code;
check("a hall added, with a pairing code", r.data?.ok && /^[A-Z0-9]{4}-[A-Z0-9]{4}$/.test(code), r.data);
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
check("a hall that does not answer: said so (in 15 s)", !r.data?.ok && /did not answer/.test(r.data?.message), r.data);

// -- the remote desk over a WebSocket --------------------------------------------------------- //
const desk = await operator.socket(`/api/halls/${hallId}/live`);
const hello = await waitFor(desk, m => m.t === "hello");
check("the remote desk gets the hall's status at once", hello?.status?.summary?.version === "1.3.0" && hello.online
      && hello.log?.[0]?.text === "a video would not play" && hello.you?.role === "operator", hello);
desk.send(JSON.stringify({ t: "rpc", id: 7, method: "POST", path: "/api/action", body: JSON.stringify({ action: "text_show", role: "main" }) }));
const asked = await waitFor(hall, m => m.t === "rpc");
check("its request reaches the hall, with who asked", asked?.path === "/api/action" && asked.user === "Ana" && asked.method === "POST", asked);
hall.send(JSON.stringify({ t: "reply", id: asked.id, status: 200, type: "application/json", body: '{"ok":true,"message":"done"}' }));
const back = await waitFor(desk, m => m.t === "reply" && m.id === 7);
check("... and the answer comes back to that desk only", back?.status === 200 && JSON.parse(back.body).message === "done", back);
hall.send(JSON.stringify({ t: "status", status: { ...status, summary: { ...status.summary, version: "1.3.1" } } }));
const pushed = await waitFor(desk, m => m.t === "status");
check("status changes are pushed to the desk", pushed?.status?.summary?.version === "1.3.1");

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

// -- pairing again, going offline, removing ------------------------------------------------------ //
r = await admin.call(`/api/halls/${hallId}/pair`, {});
const second = await pair(r.data.code);
check("pairing again gives a new token", second.data?.ok && second.data.token !== token);
const closed = await waitFor(desk, m => m.t === "online", 300);
const again = await open(BASE.replace("http", "ws") + "/hall/connect", { Authorization: "Bearer " + second.data.token });
await sleep(300);
check("the new connection takes over", again.readyState === 1 && hall.readyState >= 2, [hall.readyState, closed]);
let oldRefused = false;
try { await open(BASE.replace("http", "ws") + "/hall/connect", { Authorization: "Bearer " + token }); } catch (e) { oldRefused = true; }
check("the old token no longer works", oldRefused);
again.close();
const off = await waitFor(desk, m => m.t === "online" && m.online === false, 3000);
r = await admin.call("/api/halls");
check("closing: offline, in the desk and the list", off && r.data?.[0]?.online === false, r.data?.[0]);

r = await admin.call("/api/password", { old: "wrong", password: "new-boss-password" });
check("own password: the old one is needed", !r.data?.ok);
r = await operator.call(`/api/halls/${hallId}/remove`, {});
check("only administrators remove halls", r.status === 403);
r = await admin.call(`/api/halls/${hallId}/remove`, {});
r = await admin.call("/api/halls");
check("a hall removed", r.data?.length === 0, r.data);
r = await admin.call("/api/logout", {});
r = await admin.call("/api/me");
check("signed out", r.status === 401);

desk.close(); watching.close();
console.log("\nFAILURES:", failures.length ? failures : "none");
process.exit(failures.length ? 1 : 0);
