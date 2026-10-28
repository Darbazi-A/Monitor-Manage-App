// Stage Cloud: one place to see and run every hall's Stage Display Controller.
//   /            the dashboard (public/), signed in with a name and password
//   /api/...     the dashboard's requests (a session cookie)
//   /hall/...    the halls' programs: pairing with a code, then a WebSocket with their token
import { Directory } from "./directory.js";
import { Hall } from "./hall.js";
import { ROLES, cleanName, cookie, fail, json, rank, sameText } from "./util.js";

export { Directory, Hall };

const SESSION_COOKIE = "sdc_session";
const SAFE_COMMANDS = new Set(["check_update", "install_update", "message", "status"]);

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    try {
      if (url.pathname.startsWith("/hall/")) return await hallRoutes(request, env, url);
      if (url.pathname.startsWith("/api/")) return await apiRoutes(request, env, url);
      return env.ASSETS.fetch(request);
    } catch (error) {
      console.error(error);
      return fail(500, "server error");
    }
  },
};

const directory = env => env.DIRECTORY.get(env.DIRECTORY.idFromName("main"));
const hallObject = (env, id) => env.HALL.get(env.HALL.idFromName(id));
const clientIp = request => request.headers.get("CF-Connecting-IP") || "local";

async function body(request) {
  try { return await request.json(); } catch (e) { return {}; }
}

// -- the halls' programs --------------------------------------------------------------------- //
async function hallRoutes(request, env, url) {
  const dir = directory(env);
  if (url.pathname === "/hall/pair" && request.method === "POST") {
    const data = await body(request);
    const result = await dir.pair(data.code, data.computer, clientIp(request));
    return json(result, result.ok ? 200 : 403);
  }
  if (url.pathname === "/hall/connect") {
    const token = (request.headers.get("Authorization") || "").replace(/^Bearer\s+/i, "");
    const hall = await dir.hallByToken(token);
    if (!hall) return fail(401, "this hall is not paired (or was paired again elsewhere)");
    if (request.headers.get("Upgrade") !== "websocket") return json({ ok: true, id: hall.id, name: hall.name });
    return hallObject(env, hall.id).fetch(forwarded(request, { "X-SDC-Kind": "hall", "X-SDC-Hall": hall.id }));
  }
  return fail(404, "not found");
}

// a request for a Durable Object: who it is comes from here, never from the client
function forwarded(request, identity) {
  const headers = new Headers();
  for (const name of ["Upgrade", "Connection", "Sec-WebSocket-Key", "Sec-WebSocket-Version", "Sec-WebSocket-Extensions"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  for (const [name, value] of Object.entries(identity)) headers.set(name, value);
  return new Request(request.url, { method: "GET", headers });
}

// -- the dashboard ------------------------------------------------------------------------------ //
async function apiRoutes(request, env, url) {
  const dir = directory(env);
  const path = url.pathname;
  const method = request.method;
  const secure = url.protocol === "https:";

  // a browser's change must come from this site's own pages (and WebSockets too)
  const origin = request.headers.get("Origin");
  if ((method !== "GET" || request.headers.get("Upgrade")) && origin && origin !== url.origin) return fail(403, "wrong origin");
  if (method !== "GET" && !origin && !request.headers.get("X-SDC-Client")) return fail(403, "wrong origin");

  if (path === "/api/setup" && method === "GET") return json({ needed: await dir.setupNeeded() });
  if (path === "/api/setup" && method === "POST") {
    const data = await body(request);
    if (!env.SETUP_KEY || !sameText(data.key || "", env.SETUP_KEY)) return fail(403, "wrong setup key");
    const result = await dir.setup(data.name, data.password, clientIp(request));
    return json(result, result.ok ? 200 : 400);
  }
  if (path === "/api/login" && method === "POST") {
    const data = await body(request);
    const result = await dir.login(String(data.name || ""), String(data.password || ""), clientIp(request));
    if (!result.ok) return json(result, result.locked ? 429 : 401);
    return json({ ok: true, name: result.name, role: result.role }, 200, {
      "Set-Cookie": `${SESSION_COOKIE}=${result.token}; HttpOnly; ${secure ? "Secure; " : ""}SameSite=Strict; Path=/; Max-Age=${14 * 24 * 3600}`,
    });
  }

  const me = await dir.session(cookie(request, SESSION_COOKIE));
  if (!me) return fail(401, "sign in");
  const need = role => rank(me.role) >= rank(role);

  if (path === "/api/logout" && method === "POST") {
    await dir.logout(cookie(request, SESSION_COOKIE));
    return json({ ok: true }, 200, { "Set-Cookie": `${SESSION_COOKIE}=; HttpOnly; ${secure ? "Secure; " : ""}SameSite=Strict; Path=/; Max-Age=0` });
  }
  if (path === "/api/me") return json(me);
  if (path === "/api/password" && method === "POST") {
    const data = await body(request);
    return reply(await dir.setPassword(me.name, data.password, me.name, String(data.old || "")));
  }

  // halls
  if (path === "/api/halls" && method === "GET") return json(await dir.halls());
  if (path === "/api/halls" && method === "POST") {
    if (!need("admin")) return fail(403, "administrators only");
    return reply(await dir.addHall((await body(request)).name, me.name));
  }
  const hallMatch = path.match(/^\/api\/halls\/([0-9a-f-]{36})(?:\/(\w+))?$/);
  if (hallMatch) {
    const [, id, verb = ""] = hallMatch;
    const hall = await dir.hall(id);
    if (!hall) return fail(404, "no such hall");
    if (!verb && method === "GET") return json({ ...hall, ...(await hallObject(env, id).snapshot()) });
    if (verb === "live") {
      if (request.headers.get("Upgrade") !== "websocket") return fail(426, "a WebSocket");
      return hallObject(env, id).fetch(forwarded(request, { "X-SDC-Kind": "viewer", "X-SDC-User": me.name, "X-SDC-Role": me.role }));
    }
    if (verb === "journal" && method === "GET") return json(await dir.journal(id, 100));
    if (method !== "POST") return fail(405, "POST");
    const data = await body(request);
    if (verb === "command") {
      if (!need("operator")) return fail(403, "operators and administrators only");
      const cmd = String(data.cmd || "");
      if (!SAFE_COMMANDS.has(cmd)) return fail(400, "unknown command");
      const args = cmd === "message" ? { text: cleanName(data.args?.text, 500) } : (data.args || {});
      if (cmd === "message" && !args.text) return fail(400, "an empty message");
      const result = await hallObject(env, id).command(cmd, args, me.name);
      await dir.note(me.name, id, `${cmd}${cmd === "message" ? ": " + args.text.slice(0, 80) : ""} → ${result.ok ? "ok" : result.message}`);
      return reply(result);
    }
    if (!need("admin")) return fail(403, "administrators only");
    if (verb === "pair") return reply(await dir.newCode(id, me.name));
    if (verb === "rename") return reply(await dir.renameHall(id, data.name, me.name));
    if (verb === "remove") {
      const result = await dir.removeHall(id, me.name);
      if (result.ok) await hallObject(env, id).forget();
      return reply(result);
    }
    return fail(404, "not found");
  }

  // people and the journal
  if (path === "/api/journal" && method === "GET") {
    if (!need("operator")) return fail(403, "operators and administrators only");
    return json(await dir.journal("", 300));
  }
  if (path === "/api/users") {
    if (!need("admin")) return fail(403, "administrators only");
    if (method === "GET") return json(await dir.users());
    const data = await body(request);
    if (data.op === "add") return reply(await dir.addUser(data.name, ROLES.includes(data.role) ? data.role : "", data.password, me.name));
    if (data.op === "role") return reply(await dir.setRole(String(data.name), String(data.role), me.name));
    if (data.op === "remove") return reply(await dir.removeUser(String(data.name), me.name));
    if (data.op === "password") return reply(await dir.setPassword(String(data.name), data.password, me.name));
    return fail(400, "unknown");
  }
  return fail(404, "not found");
}

const reply = result => json(result, result.ok ? 200 : 400);
