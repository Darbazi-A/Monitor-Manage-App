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
    const text = JSON.stringify(message);
    for (const ws of this.viewers()) { try { ws.send(text); } catch (e) { /* gone */ } }
  }

  // -- connections (the Worker has checked who it is) ------------------------------------ //
  async fetch(request) {
    if (request.headers.get("Upgrade") !== "websocket") return new Response("expected a WebSocket", { status: 426 });
    const kind = request.headers.get("X-SDC-Kind");
    const hallId = request.headers.get("X-SDC-Hall");
    const { 0: client, 1: server } = new WebSocketPair();
    if (kind === "hall") {
      for (const old of this.ctx.getWebSockets("hall")) { try { old.close(4000, "another connection took over"); } catch (e) { /* */ } }
      this.ctx.acceptWebSocket(server, ["hall"]);
      server.serializeAttachment({ kind: "hall" });
      await this.ctx.storage.put("id", hallId);
      await this.ctx.storage.put("lastSeen", Date.now());
      await this.directory().hallSeen(hallId, true);
      this.broadcast({ t: "online", online: true });
    } else {
      const id = crypto.randomUUID().slice(0, 8);
      const user = request.headers.get("X-SDC-User"), role = request.headers.get("X-SDC-Role");
      this.ctx.acceptWebSocket(server, ["viewer", "v:" + id]);
      server.serializeAttachment({ kind: "viewer", id, user, role });
      server.send(JSON.stringify({ t: "hello", ...(await this.snapshot()), you: { user, role } }));
    }
    return new Response(null, { status: 101, webSocket: client });
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
    if (who.kind === "hall") await this.fromHall(message);
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
    const method = message.method === "POST" ? "POST" : "GET";
    if (rank(who.role) < rank("operator") && method !== "GET") return reply(403, { ok: false, message: "viewing only" });
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

// what goes in the journal for a request from the remote desk
function describe(message) {
  const path = String(message.path || "");
  if (path === "/api/upload" && message.params?.op === "begin") return "file sent: " + String(message.params.name || "").slice(0, 120);
  if (path !== "/api/action") return "";
  let body = message.body;
  try { if (typeof body === "string") body = JSON.parse(body); } catch (e) { body = {}; }
  const action = String(body?.action || "?");
  if (/^(web_key|web_scroll|screen_seek|screen_volume|break_seek)$/.test(action)) return "";   // too many to note
  const detail = body?.role ? ` (${body.role})` : "";
  return "remote: " + action + detail;
}
