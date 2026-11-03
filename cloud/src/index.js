// Stage Cloud: one place to see and run every hall's Stage Display Controller.
//   /            the dashboard (public/), signed in with a name and password
//   /api/...     the dashboard's requests (a session cookie)
//   /hall/...    the halls' programs: pairing with a code, then a WebSocket with their token
import { Directory } from "./directory.js";
import { Hall } from "./hall.js";
import { HALL_ROLES, PAGE_CSP, ROLE_RIGHTS, SECURITY_HEADERS, cleanName, cleanRights, cookie, fail, frameCsp, json, sameText, sha256 } from "./util.js";

export { Directory, Hall };

const SESSION_COOKIE = "sdc_session";
// the hall's commands from the dashboard, each with the right it needs (any other is refused)
const COMMAND_RIGHTS = { status: "control", message: "message", check_update: "updates", install_update: "updates",
                         lock_desk: "desk", unlock_desk: "desk" };

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    try {
      if (url.pathname.startsWith("/hall/")) return await hallRoutes(request, env, url);
      if (url.pathname.startsWith("/api/")) return await apiRoutes(request, env, url);
      return withHeaders(await env.ASSETS.fetch(request), url);
    } catch (error) {
      console.error(error);
      return fail(500, "server error");
    }
  },
};

// the site's files, with the security headers (the Worker runs first for every request)
function withHeaders(response, url) {
  const path = url.pathname, out = new Response(response.body, response);
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) out.headers.set(name, value);
  const type = out.headers.get("Content-Type") || "";
  if (type.startsWith("text/html")) {
    out.headers.set("Content-Security-Policy", path === "/desk-frame.html" || path === "/desk-frame" ? frameCsp(url.origin) : PAGE_CSP);
    out.headers.set("Cache-Control", "no-cache");
  }
  if (path !== "/desk-frame.html" && path !== "/desk-frame") out.headers.set("X-Frame-Options", "DENY");
  return out;
}

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
    return hallObject(env, hall.id).fetch(forwarded(request, { "X-SDC-Kind": "hall", "X-SDC-Hall": hall.id, "X-SDC-IP": clientIp(request) }));
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
  const sessionCookie = token => `${SESSION_COOKIE}=${token}; HttpOnly; ${secure ? "Secure; " : ""}SameSite=Strict; Path=/; Max-Age=${14 * 24 * 3600}`;
  const signedIn = result => json({ ok: true, name: result.name, role: result.role, recoveryLeft: result.recoveryLeft }, 200,
                                  { "Set-Cookie": sessionCookie(result.token) });
  const agent = (request.headers.get("User-Agent") || "").slice(0, 200);
  if (path === "/api/login" && method === "POST") {
    const data = await body(request);
    const result = await dir.login(String(data.name || ""), String(data.password || ""), clientIp(request), agent);
    if (!result.ok) return json(result, result.locked ? 429 : 401);
    if (result.need === "code") return json({ ok: true, need: "code", ticket: result.ticket });
    return signedIn(result);
  }
  if (path === "/api/login/code" && method === "POST") {
    const data = await body(request);
    const result = await dir.loginCode(String(data.ticket || ""), String(data.code || ""), clientIp(request), agent);
    if (!result.ok) return json(result, result.locked ? 429 : 401);
    return signedIn(result);
  }

  const token = cookie(request, SESSION_COOKIE);
  const me = await dir.session(token);
  if (!me) return fail(401, "sign in");
  const isAdmin = me.role === "admin";

  if (path === "/api/logout" && method === "POST") {
    await dir.logout(token);
    return json({ ok: true }, 200, { "Set-Cookie": `${SESSION_COOKIE}=; HttpOnly; ${secure ? "Secure; " : ""}SameSite=Strict; Path=/; Max-Age=0` });
  }
  if (path === "/api/me") {
    return json({ name: me.name, role: me.role, totp: me.totp, need: me.need, totpRequired: me.totpRequired,
                  halls: me.need ? {} : await dir.accessMap(me.name) });
  }
  if (path === "/api/password" && method === "POST") {
    const data = await body(request);
    return reply(await dir.setPassword(me.name, data.password, me.name, String(data.old || ""), token));
  }
  if (path === "/api/2fa/start" && method === "POST") return reply(await dir.totpStart(me.name));
  if (path === "/api/2fa/enable" && method === "POST") return reply(await dir.totpEnable(me.name, String((await body(request)).code || ""), token));
  // a given password changed, the authenticator its role needs set up - before anything else
  if (me.need) return json({ ok: false, need: me.need, message: me.need === "password" ? "change your password first" : "set up two-step sign-in first" }, 403);
  if (path === "/api/2fa/recovery" && method === "POST") return reply(await dir.totpRecovery(me.name, (await body(request)).password));
  if (path === "/api/2fa/disable" && method === "POST") return reply(await dir.totpDisable(me.name, (await body(request)).password));
  if (path === "/api/sessions" && method === "GET") return json(await dir.sessions(me.name, token));
  if (path === "/api/sessions" && method === "POST") {
    const data = await body(request);
    return reply(await dir.endSessions(me.name, token, data.all ? "*" : String(data.id || "")));
  }

  // what I may do: in every hall, and in one (nothing at all in a hall I was not given)
  const mine = await dir.accessMap(me.name);
  const may = (hall, right) => !!mine[hall]?.rights.includes(right);
  const managed = Object.keys(mine).filter(id => may(id, "manage"));

  // halls: the ones I have rights in, each with what I may do there
  if (path === "/api/halls" && method === "GET") return json((await dir.halls()).filter(h => mine[h.id]).map(h => ({ ...h, access: mine[h.id] })));
  if (path === "/api/halls" && method === "POST") {
    if (!isAdmin) return fail(403, "main administrators only");
    return reply(await dir.addHall((await body(request)).name, me.name));
  }
  const hallMatch = path.match(/^\/api\/halls\/([0-9a-f-]{36})(?:\/(\w+))?$/);
  if (hallMatch) {
    const [, id, verb = ""] = hallMatch;
    const hall = await dir.hall(id);
    if (!hall || !mine[id]) return fail(404, "no such hall");
    if (!verb && method === "GET") return json({ ...hall, access: mine[id], ...(await hallObject(env, id).snapshot()) });
    if (verb === "live") {
      if (request.headers.get("Upgrade") !== "websocket") return fail(426, "a WebSocket");
      // the hall checks this session's rights again on every request, and closes the socket when they end
      return hallObject(env, id).fetch(forwarded(request, { "X-SDC-Kind": "viewer", "X-SDC-Hall": id, "X-SDC-User": me.name,
        "X-SDC-Session": await sha256(cookie(request, SESSION_COOKIE)), "X-SDC-Expires": String(me.expires) }));
    }
    if (verb === "journal" && method === "GET") {
      if (!may(id, "journal")) return fail(403, "not allowed");
      return json(await dir.journal(id, 100));
    }
    if (method !== "POST") return fail(405, "POST");
    const data = await body(request);
    if (verb === "command") {
      const cmd = String(data.cmd || "");
      if (!COMMAND_RIGHTS[cmd]) return fail(400, "unknown command");
      if (!may(id, COMMAND_RIGHTS[cmd])) return fail(403, "not allowed");
      const args = cmd === "message" ? { text: cleanName(data.args?.text, 500) } : cmd === "install_update" ? { now: !!data.args?.now } : {};
      if (cmd === "message" && !args.text) return fail(400, "an empty message");
      const result = await hallObject(env, id).command(cmd, args, me.name);
      await dir.note(me.name, id, `${cmd}${cmd === "message" ? ": " + args.text.slice(0, 80) : ""} → ${result.ok ? "ok" : result.message}`);
      return reply(result);
    }
    if (verb === "pair") return may(id, "pair") ? reply(await dir.newCode(id, me.name)) : fail(403, "not allowed");
    if (verb === "rename") return may(id, "manage") ? reply(await dir.renameHall(id, data.name, me.name)) : fail(403, "not allowed");
    if (verb === "remove") {
      if (!isAdmin) return fail(403, "main administrators only");
      const result = await dir.removeHall(id, me.name);
      if (result.ok) await hallObject(env, id).forget();
      return reply(result);
    }
    return fail(404, "not found");
  }

  // the journal: every line for a main administrator, else the lines of the halls I may read it in
  if (path === "/api/journal" && method === "GET") {
    if (isAdmin) return json(await dir.journal("", 300));
    const readable = Object.keys(mine).filter(id => may(id, "journal"));
    if (!readable.length) return fail(403, "not allowed");
    return json(await dir.journal("", 300, readable));
  }

  // people: a main administrator manages everyone; someone who manages a hall sees the people
  // and gives rights in that hall (only the rights they have), and may add a person to it
  if (path === "/api/users") {
    if (!isAdmin && !managed.length) return fail(403, "not allowed");
    if (method === "GET") return json(await dir.users(isAdmin ? null : managed));
    const data = await body(request);
    const name = String(data.name || "");
    if (data.op === "grant") return reply(await dir.grant(me.name, name, String(data.hall || ""), String(data.role || ""), data.rights ?? null));
    if (data.op === "add") {
      const hall = String(data.hall || "");
      const hallRole = String(data.hallRole || "viewer");
      if (!isAdmin && !managed.includes(hall)) return fail(403, "add them to a hall you manage");
      if (hall && !HALL_ROLES.includes(hallRole)) return fail(400, "unknown role");
      if (hall && !cleanRights(data.rights ?? ROLE_RIGHTS[hallRole]).every(right => may(hall, right))) return fail(403, "only rights you have yourself");
      const added = await dir.addUser(data.name, isAdmin && data.role === "admin" ? "admin" : "member", data.password, me.name);
      if (!added.ok || !hall) return reply(added);
      return reply(await dir.grant(me.name, added.name, hall, hallRole, data.rights ?? null));
    }
    if (!isAdmin) return fail(403, "main administrators only");
    if (data.op === "role") return reply(await dir.setRole(name, String(data.role), me.name));
    if (data.op === "remove") return reply(await dir.removeUser(name, me.name));
    if (data.op === "password") {
      if (name === me.name) return fail(400, "change your own password under Account");
      return reply(await dir.setPassword(name, data.password, me.name));
    }
    if (data.op === "reset2fa") return reply(await dir.totpReset(name, me.name));
    if (data.op === "signout") return reply(await dir.signOutUser(name, me.name));
    if (data.op === "sessions") return json({ ok: true, sessions: await dir.userSessions(name) });
    return fail(400, "unknown");
  }
  return fail(404, "not found");
}

const reply = result => json(result, result.ok ? 200 : (result.message === "not allowed" ? 403 : 400));
