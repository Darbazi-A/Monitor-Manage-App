// One Durable Object per hall: the hall's program keeps a WebSocket open to it, and so does
// every browser watching that hall. It keeps the latest status, passes the browsers' requests
// (the phone page's API) to the hall and the answers back, and runs commands. WebSockets
// hibernate: an idle hall costs nothing.
import { DurableObject } from "cloudflare:workers";
import { rank } from "./util.js";

const LOG_KEEP = 200;
const SUMMARY_EVERY_MS = 25000;       // the directory's copy: on a change, at most this often
const COMMAND_MS = 15000;
const MAX_MESSAGE = 900 * 1024;
const ALIVE_MS = 75000;               // a hall that said something (a status, a ping) this recently is there
const DUPLICATE_NOTE_MS = 10 * 60000; // a second computer with this hall's pairing: told at most this often

export class Hall extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.pending = new Map();           // command id -> resolve (an RPC call waiting for the hall)
    this.counter = 0;
    ctx.setWebSocketAutoResponse(new WebSocketRequestResponsePair('{"t":"ping"}', '{"t":"pong"}'));
  }

  directory() { return this.env.DIRECTORY.get(this.env.DIRECTORY.idFromName("main")); }
  hallSocket() { return this.ctx.getWebSockets("hall").find(ws => ws.readyState === WebSocket.OPEN) || null; }
  viewers() { return this.ctx.getWebSockets("viewer"); }

  broadcast(message) {
    const text = JSON.stringify(message), now = Date.now();
    for (const ws of this.viewers()) {
      const who = ws.deserializeAttachment() || {};
      if (who.expires && who.expires < now) { this.drop(ws, "signed out"); continue; }    // the session ran out
      try { ws.send(text); } catch (e) { /* gone */ }
    }
  }

  drop(ws, why) { try { ws.close(4401, why); } catch (e) { /* already */ } }

  // the directory: this hall was paired again - the computer connected now is no longer it
  dropHall() {
    for (const ws of this.ctx.getWebSockets("hall")) { try { ws.close(4000, "this hall was paired again"); } catch (e) { /* */ } }
  }

  // the directory: someone's rights changed (removed, a new role or password, signed out)
  dropViewers(match) {
    for (const ws of this.viewers()) {
      const who = ws.deserializeAttachment() || {};
      if ((match.user && who.user === match.user) || (match.session && who.session === match.session)) this.drop(ws, "signed out");
    }
  }

  // -- connections (the Worker has checked who it is) ------------------------------------ //
  async fetch(request) {
    if (request.headers.get("Upgrade") !== "websocket") return new Response("expected a WebSocket", { status: 426 });
    const kind = request.headers.get("X-SDC-Kind");
    const hallId = request.headers.get("X-SDC-Hall");
    if (kind === "hall") {
      const ip = request.headers.get("X-SDC-IP") || "";
      // two computers with one pairing pushed each other off, over and over: the one that is
      // connected and alive stays, one from somewhere else is refused (and the hall's page says so)
      const there = this.hallSocket();
      if (there && this.alive(there) && !samePlace((there.deserializeAttachment() || {}).ip || "", ip)) {
        await this.noteDuplicate(ip);
        return new Response("this hall is connected from another computer", { status: 409 });
      }
    }
    const { 0: client, 1: server } = new WebSocketPair();
    if (kind === "hall") {
      for (const old of this.ctx.getWebSockets("hall")) { try { old.close(4000, "another connection took over"); } catch (e) { /* */ } }
      this.ctx.acceptWebSocket(server, ["hall"]);
      server.serializeAttachment({ kind: "hall", ip: request.headers.get("X-SDC-IP") || "", heard: Date.now() });
      await this.ctx.storage.put("id", hallId);
      await this.ctx.storage.put("lastSeen", Date.now());
      await this.directory().hallSeen(hallId, true);
      this.broadcast({ t: "online", online: true });
    } else {
      const id = crypto.randomUUID().slice(0, 8);
      const user = request.headers.get("X-SDC-User"), role = request.headers.get("X-SDC-Role");
      const session = request.headers.get("X-SDC-Session") || "", expires = Number(request.headers.get("X-SDC-Expires")) || 0;
      this.ctx.acceptWebSocket(server, ["viewer", "v:" + id]);
      server.serializeAttachment({ kind: "viewer", id, user, role, session, expires });
      server.send(JSON.stringify({ t: "hello", ...(await this.snapshot()), you: { user, role } }));
    }
    return new Response(null, { status: 101, webSocket: client });
  }

  // the hall's socket said something lately: its own message, or a ping the runtime answered
  alive(ws) {
    let heard = (ws.deserializeAttachment() || {}).heard || 0;
    try { heard = Math.max(heard, this.ctx.getWebSocketAutoResponseTimestamp(ws)?.getTime() || 0); } catch (e) { /* not known */ }
    return Date.now() - heard < ALIVE_MS;
  }

  async noteDuplicate(ip) {
    const last = (await this.ctx.storage.get("duplicateNoted")) || 0;
    if (Date.now() - last < DUPLICATE_NOTE_MS) return;
    await this.ctx.storage.put("duplicateNoted", Date.now());
    await this.fromHall({ t: "event", level: "warn",
      text: `Another computer (${ip || "?"}) tries to connect as this hall and was refused. If it should not be this hall: Settings → Cloud → Forget on that computer.` });
    await this.directory().note("(cloud)", await this.ctx.storage.get("id"), `a second computer tried to connect as this hall, from ${ip || "?"}`);
  }

  async snapshot() {
    const [status, lastSeen, log] = await Promise.all([
      this.ctx.storage.get("status"), this.ctx.storage.get("lastSeen"), this.ctx.storage.get("log")]);
    return { status: status || null, lastSeen: lastSeen || 0, online: !!this.hallSocket(), log: log || [] };
  }

  // -- messages ------------------------------------------------------------------------- //
  async webSocketMessage(ws, raw) {
    if (typeof raw !== "string" || raw.length > MAX_MESSAGE) return;
    let message;
    try { message = JSON.parse(raw); } catch (e) { return; }
    const who = ws.deserializeAttachment() || {};
    if (who.kind === "hall") {
      if (Date.now() - (who.heard || 0) > 5000) ws.serializeAttachment({ ...who, heard: Date.now() });
      await this.fromHall(message);
    }
    else if (who.kind === "viewer") await this.fromViewer(ws, who, message);
  }

  async fromHall(message) {
    const now = Date.now();
    if (message.t === "status" && message.status && typeof message.status === "object") {
      await this.ctx.storage.put({ status: message.status, lastSeen: now });
      this.broadcast({ t: "status", status: message.status, at: now });
      const summary = JSON.stringify(message.status.summary || {});
      const last = (await this.ctx.storage.get("summarySent")) || { at: 0, text: "" };
      // the list of halls is told on a change, and anyway every SUMMARY_EVERY_MS (it shows "last seen")
      if (summary !== last.text || now - last.at > SUMMARY_EVERY_MS) {
        await this.directory().hallSeen(await this.ctx.storage.get("id"), true, message.status.summary || {});
        await this.ctx.storage.put("summarySent", { at: now, text: summary });
      }
    } else if (message.t === "reply" && typeof message.id === "string") {
      const [viewer, inner] = message.id.split("|");
      if (inner !== undefined) {
        const target = this.ctx.getWebSockets(viewer)[0];
        if (target) target.send(JSON.stringify({ ...message, t: "reply", id: Number(inner) }));
      } else {
        const resolve = this.pending.get(message.id);
        if (resolve) { this.pending.delete(message.id); resolve(message); }
      }
    } else if (message.t === "event") {
      const log = (await this.ctx.storage.get("log")) || [];
      const entry = { at: now, level: String(message.level || "info").slice(0, 10), text: String(message.text || "").slice(0, 300) };
      log.unshift(entry);
      await this.ctx.storage.put("log", log.slice(0, LOG_KEEP));
      this.broadcast({ t: "event", ...entry });
    }
  }

  async fromViewer(ws, who, message) {
    if (message.t !== "rpc") return;
    const reply = (status, body) => ws.send(JSON.stringify({ t: "reply", id: message.id, status, type: "application/json",
                                                               body: JSON.stringify(body) }));
    // who it is now, not when the socket opened: a removed person, a lower role, a session ended
    const now = await this.directory().sessionByHash(who.session);
    if (!now || now.name !== who.user) { reply(401, { ok: false, message: "signed out" }); return this.drop(ws, "signed out"); }
    if (now.role !== who.role) ws.serializeAttachment({ ...who, role: now.role });
    const method = message.method === "POST" ? "POST" : "GET";
    if (rank(now.role) < rank("operator") && method !== "GET") return reply(403, { ok: false, message: "viewing only" });
    const refused = method === "POST" ? refusedAction(message) : "";
    if (refused) return reply(403, { ok: false, message: refused });
    const hall = this.hallSocket();
    if (!hall) return reply(503, { ok: false, message: "the hall is not connected" });
    hall.send(JSON.stringify({ t: "rpc", id: `v:${who.id}|${message.id}`, user: who.user, method,
                               path: String(message.path || ""), params: message.params || {}, body: message.body ?? null }));
    if (method === "POST") {
      const what = describe(message);
      if (what) await this.directory().note(who.user, await this.ctx.storage.get("id"), what);
    }
  }

  async webSocketClose(ws, code) {
    try { ws.close(code === 1005 ? 1000 : code, "closed"); } catch (e) { /* already */ }
    const who = ws.deserializeAttachment() || {};
    // the closing socket is still listed while this runs
    const others = this.ctx.getWebSockets("hall").filter(other => other !== ws && other.readyState === WebSocket.OPEN);
    if (who.kind === "hall" && !others.length) {
      await this.directory().hallSeen(await this.ctx.storage.get("id"), false);
      this.broadcast({ t: "online", online: false });
    }
  }

  async webSocketError(ws) { await this.webSocketClose(ws, 1011); }

  // -- commands from the Worker (RPC) ---------------------------------------------------- //
  async command(cmd, args, user) {
    const hall = this.hallSocket();
    if (!hall) return { ok: false, message: "the hall is not connected" };
    const id = "c" + (++this.counter) + "-" + Date.now();
    const answer = new Promise(resolve => {
      this.pending.set(id, resolve);
      setTimeout(() => { if (this.pending.delete(id)) resolve({ ok: false, message: "the hall did not answer" }); }, COMMAND_MS);
    });
    hall.send(JSON.stringify({ t: "cmd", id, cmd, args: args || {}, user }));
    const result = await answer;
    return { ok: !!result.ok, message: String(result.message || "") };
  }

  async forget() {
    for (const ws of this.ctx.getWebSockets()) { try { ws.close(4001, "the hall was removed"); } catch (e) { /* */ } }
    await this.ctx.storage.deleteAll();
  }
}

// the same place: one address, or one network (a school's addresses change within a /24, or a /64)
export function samePlace(a, b) {
  if (!a || !b) return true;
  if (a === b) return true;
  if (a.includes(".") && b.includes(".")) return a.split(".").slice(0, 3).join(".") === b.split(".").slice(0, 3).join(".");
  if (a.includes(":") && b.includes(":")) return a.split(":").slice(0, 4).join(":") === b.split(":").slice(0, 4).join(":");
  return false;
}

// the remote desk's body, as an object
function actionBody(message) {
  let body = message.body;
  try { if (typeof body === "string") body = JSON.parse(body); } catch (e) { body = {}; }
  return body && typeof body === "object" ? body : {};
}

// a web page from the cloud is a web address and nothing else: never a file on the hall's
// computer (C:\..., file:, \\server\share), nor the browser's own pages
export function webAddressRefused(text) {
  const url = String(text ?? "").trim();
  if (!url) return "";
  if (/^https?:\/\/[^\s\/\\]/i.test(url)) return "";
  if (/^[a-z0-9-]+(\.[a-z0-9-]+)+(:\d{1,5})?([\/?#][^\s]*)?$/i.test(url)) return "";   // canva.com/design/...
  return "Only web addresses (https://...) can be opened from Stage Cloud.";
}

function refusedAction(message) {
  if (String(message.path || "") !== "/api/action") return "";
  const body = actionBody(message);
  if (body.action === "web_open" && !("index" in body)) return webAddressRefused(body.url);
  return "";
}

// what goes in the journal for a request from the remote desk
function describe(message) {
  const path = String(message.path || "");
  if (path === "/api/upload" && message.params?.op === "begin") return "file sent: " + String(message.params.name || "").slice(0, 120);
  if (path !== "/api/action") return "";
  const body = actionBody(message);
  const action = String(body?.action || "?");
  if (/^(web_key|web_scroll|screen_seek|screen_volume|break_seek)$/.test(action)) return "";   // too many to note
  const detail = body?.role ? ` (${body.role})` : "";
  return "remote: " + action + detail;
}
