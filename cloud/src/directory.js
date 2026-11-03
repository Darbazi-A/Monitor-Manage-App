// The directory: one Durable Object (SQLite) with the people, their sessions, the halls,
// pairing codes, the journal and the lock-outs. The Worker calls its methods over RPC.
import { DurableObject } from "cloudflare:workers";
import {
  ROLES, checkPassword, cleanName, hashPassword, newTotpSecret, normaliseCode, normaliseRecovery, pairingCode,
  randomToken, rank, recoveryCodes, sha256, totpStep,
} from "./util.js";

const SESSION_MS = 14 * 24 * 3600 * 1000;
const STEP_MS = 5 * 60 * 1000;          // a password that was right waits this long for its code
const STEP_TRIES = 5;
const SEEN_EVERY_MS = 5 * 60 * 1000;    // a session's "last seen" is written at most this often
const PAIR_MS = 30 * 60 * 1000;
const LOCK_AFTER = { u: 5, ip: 20, pair: 10 }, LOCK_MS = 15 * 60 * 1000;
const JOURNAL_KEEP = 2000;

export class Directory extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.sql = ctx.storage.sql;
    this.sql.exec(`
      CREATE TABLE IF NOT EXISTS users (name TEXT PRIMARY KEY, role TEXT NOT NULL, salt TEXT, hash TEXT, created INTEGER);
      CREATE TABLE IF NOT EXISTS sessions (hash TEXT PRIMARY KEY, name TEXT NOT NULL, expires INTEGER);
      CREATE TABLE IF NOT EXISTS halls (id TEXT PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT, pair_hash TEXT,
        pair_expires INTEGER, created INTEGER, online INTEGER DEFAULT 0, last_seen INTEGER DEFAULT 0,
        summary TEXT DEFAULT '{}', computer TEXT DEFAULT '');
      CREATE TABLE IF NOT EXISTS journal (id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER, user TEXT, hall TEXT, what TEXT);
      CREATE TABLE IF NOT EXISTS failures (key TEXT PRIMARY KEY, count INTEGER, until INTEGER);
      CREATE TABLE IF NOT EXISTS pending (hash TEXT PRIMARY KEY, name TEXT NOT NULL, expires INTEGER, tries INTEGER DEFAULT 0);`);
    // two-step sign-in and the sessions list came later: the tables of an older cloud get the columns
    const add = (table, column, type) => {
      if (!this.rows(`PRAGMA table_info(${table})`).some(c => c.name === column)) this.sql.exec(`ALTER TABLE ${table} ADD COLUMN ${column} ${type}`);
    };
    add("users", "totp", "TEXT DEFAULT ''");          // the authenticator's secret, once it is on
    add("users", "totp_new", "TEXT DEFAULT ''");      // while it is being set up
    add("users", "totp_step", "INTEGER DEFAULT 0");   // the last code used (a code works once)
    add("users", "recovery", "TEXT DEFAULT '[]'");    // hashes of the unused recovery codes
    add("users", "must_change", "INTEGER DEFAULT 0"); // a password an administrator gave: changed at the first sign-in
    add("sessions", "created", "INTEGER DEFAULT 0");
    add("sessions", "seen", "INTEGER DEFAULT 0");
    add("sessions", "ip", "TEXT DEFAULT ''");
    add("sessions", "agent", "TEXT DEFAULT ''");
  }

  // who must use the authenticator: whoever may change something in a hall
  static needsTotp(role) { return rank(role) >= rank("operator"); }

  rows(query, ...args) { return this.sql.exec(query, ...args).toArray(); }
  one(query, ...args) { return this.rows(query, ...args)[0] || null; }

  // -- lock-outs, a quarter of an hour: a name after five wrong tries; an address (a whole
  //    school behind one) after twenty; pairing codes from an address after ten ---------- //
  locked(keys) {
    const now = Date.now();
    return keys.some(key => (this.one("SELECT until FROM failures WHERE key = ?", key)?.until || 0) > now);
  }
  failed(keys) {
    for (const key of keys) {
      const limit = LOCK_AFTER[key.split(":")[0]] || 5;
      const count = (this.one("SELECT count FROM failures WHERE key = ?", key)?.count || 0) + 1;
      this.sql.exec("INSERT OR REPLACE INTO failures (key, count, until) VALUES (?, ?, ?)",
        key, count >= limit ? 0 : count, count >= limit ? Date.now() + LOCK_MS : 0);
    }
  }
  cleared(keys) { for (const key of keys) this.sql.exec("DELETE FROM failures WHERE key = ?", key); }

  // -- the first administrator ----------------------------------------------------------- //
  setupNeeded() { return !this.one("SELECT name FROM users LIMIT 1"); }

  async setup(name, password, ip) {
    if (!this.setupNeeded()) return { ok: false, message: "already set up" };
    return this.addUser(name, "admin", password, "(setup)", ip);
  }

  // -- people ------------------------------------------------------------------------------ //
  async addUser(name, role, password, by, ip = "") {
    name = cleanName(name, 40);
    if (!name || !ROLES.includes(role)) return { ok: false, message: "name and role" };
    if (String(password || "").length < 8) return { ok: false, message: "password: at least 8 characters" };
    if (this.one("SELECT name FROM users WHERE name = ? COLLATE NOCASE", name)) return { ok: false, message: "that name is taken" };
    const { salt, hash } = await hashPassword(password);
    this.sql.exec("INSERT INTO users (name, role, salt, hash, created, must_change) VALUES (?, ?, ?, ?, ?, ?)",
      name, role, salt, hash, Date.now(), by === "(setup)" ? 0 : 1);
    this.note(by, "", `user added: ${name} (${role})${ip ? " from " + ip : ""}`);
    return { ok: true };
  }

  users() {
    return this.rows("SELECT name, role, created, totp != '' AS totp, must_change FROM users ORDER BY name COLLATE NOCASE")
      .map(u => ({ ...u, totp: !!u.totp, mustChange: !!u.must_change, must_change: undefined }));
  }

  async setRole(name, role, by) {
    if (!ROLES.includes(role) || !this.one("SELECT name FROM users WHERE name = ?", name)) return { ok: false, message: "no such user" };
    if (role !== "admin" && this.lastAdmin(name)) return { ok: false, message: "the last administrator stays one" };
    this.sql.exec("UPDATE users SET role = ? WHERE name = ?", role, name);
    this.note(by, "", `role of ${name}: ${role}`);
    await this.dropViewers({ user: name });
    return { ok: true };
  }

  async removeUser(name, by) {
    if (!this.one("SELECT name FROM users WHERE name = ?", name)) return { ok: false, message: "no such user" };
    if (this.lastAdmin(name)) return { ok: false, message: "the last administrator stays" };
    this.sql.exec("DELETE FROM users WHERE name = ?", name);
    this.sql.exec("DELETE FROM sessions WHERE name = ?", name);
    this.note(by, "", `user removed: ${name}`);
    await this.dropViewers({ user: name });
    return { ok: true };
  }

  lastAdmin(name) {
    const admins = this.rows("SELECT name FROM users WHERE role = 'admin'");
    return admins.length === 1 && admins[0].name === name;
  }

  // one's own (with the old one; this session stays, every other one ends), or an
  // administrator's (a temporary one, changed at the next sign-in; every session ends)
  async setPassword(name, password, by, old = null, keepToken = "") {
    const user = this.one("SELECT * FROM users WHERE name = ?", name);
    if (!user) return { ok: false, message: "no such user" };
    if (old !== null && !(await checkPassword(old, user.salt, user.hash))) return { ok: false, message: "wrong password" };
    if (String(password || "").length < 8) return { ok: false, message: "password: at least 8 characters" };
    if (old !== null && password === old) return { ok: false, message: "a new password, not the same one" };
    const { salt, hash } = await hashPassword(password);
    this.sql.exec("UPDATE users SET salt = ?, hash = ?, must_change = ? WHERE name = ?", salt, hash, by === name ? 0 : 1, name);
    const keep = keepToken ? await sha256(keepToken) : "";
    this.sql.exec("DELETE FROM sessions WHERE name = ? AND hash != ?", name, keep);
    this.note(by, "", by === name ? "own password changed" : `password of ${name} reset`);
    await this.dropViewers({ user: name, except: keep });
    return { ok: true };
  }

  // -- the authenticator ----------------------------------------------------------------------- //
  totpStart(name) {
    const secret = newTotpSecret();
    this.sql.exec("UPDATE users SET totp_new = ? WHERE name = ?", secret, name);
    return { ok: true, secret, uri: `otpauth://totp/${encodeURIComponent("Stage Cloud:" + name)}?secret=${secret}&issuer=${encodeURIComponent("Stage Cloud")}&digits=6&period=30` };
  }

  // the code from the new entry in the app proves it was added: on, ten recovery codes, and
  // every other session of this person ends (they signed in without it)
  async totpEnable(name, code, keepToken) {
    const user = this.one("SELECT * FROM users WHERE name = ?", name);
    if (!user?.totp_new) return { ok: false, message: "start again" };
    const step = await totpStep(user.totp_new, code);
    if (!step) return { ok: false, message: "wrong code - check the phone's clock, or scan again" };
    const codes = recoveryCodes();
    const hashes = await Promise.all(codes.map(c => sha256(normaliseRecovery(c))));
    this.sql.exec("UPDATE users SET totp = totp_new, totp_new = '', totp_step = ?, recovery = ? WHERE name = ?",
      step, JSON.stringify(hashes), name);
    const keep = await sha256(keepToken);
    this.sql.exec("DELETE FROM sessions WHERE name = ? AND hash != ?", name, keep);
    await this.dropViewers({ user: name, except: keep });
    this.note(name, "", "two-step sign-in turned on");
    return { ok: true, codes };
  }

  async totpRecovery(name, password) {
    const user = this.one("SELECT * FROM users WHERE name = ?", name);
    if (!user?.totp) return { ok: false, message: "two-step sign-in is off" };
    if (!(await checkPassword(String(password || ""), user.salt, user.hash))) return { ok: false, message: "wrong password" };
    const codes = recoveryCodes();
    this.sql.exec("UPDATE users SET recovery = ? WHERE name = ?", JSON.stringify(await Promise.all(codes.map(c => sha256(normaliseRecovery(c))))), name);
    this.note(name, "", "new recovery codes");
    return { ok: true, codes };
  }

  async totpDisable(name, password) {
    const user = this.one("SELECT * FROM users WHERE name = ?", name);
    if (!user) return { ok: false, message: "no such user" };
    if (Directory.needsTotp(user.role)) return { ok: false, message: "your role needs two-step sign-in" };
    if (!(await checkPassword(String(password || ""), user.salt, user.hash))) return { ok: false, message: "wrong password" };
    this.sql.exec("UPDATE users SET totp = '', totp_new = '', recovery = '[]' WHERE name = ?", name);
    this.note(name, "", "two-step sign-in turned off");
    return { ok: true };
  }

  // an administrator, for a lost phone: off, and set up again at the next sign-in; signed out everywhere
  async totpReset(name, by) {
    if (!this.one("SELECT name FROM users WHERE name = ?", name)) return { ok: false, message: "no such user" };
    this.sql.exec("UPDATE users SET totp = '', totp_new = '', recovery = '[]' WHERE name = ?", name);
    this.sql.exec("DELETE FROM sessions WHERE name = ?", name);
    await this.dropViewers({ user: name });
    this.note(by, "", `two-step sign-in of ${name} reset`);
    return { ok: true };
  }

  // -- sessions --------------------------------------------------------------------------- //
  // the password; then, with the authenticator on, a ticket for the code (no session yet)
  async login(name, password, ip, agent = "") {
    const keys = ["u:" + String(name).toLowerCase(), "ip:" + ip];
    if (this.locked(keys)) return { ok: false, locked: true, message: "too many tries - wait a quarter of an hour" };
    const user = this.one("SELECT * FROM users WHERE name = ? COLLATE NOCASE", cleanName(name, 40));
    if (!user || !(await checkPassword(password, user.salt, user.hash))) {
      this.failed(keys);
      return { ok: false, message: "wrong name or password" };
    }
    if (user.totp) {
      const ticket = randomToken();
      this.sql.exec("DELETE FROM pending WHERE expires < ?", Date.now());
      this.sql.exec("INSERT INTO pending (hash, name, expires) VALUES (?, ?, ?)", await sha256(ticket), user.name, Date.now() + STEP_MS);
      return { ok: true, need: "code", ticket };
    }
    this.cleared(keys);
    return this.newSession(user, ip, agent, "signed in from " + ip);
  }

  // the code from the app (or a recovery code) for a ticket from login()
  async loginCode(ticket, code, ip, agent = "") {
    const hash = await sha256(String(ticket || ""));
    const row = this.one("SELECT * FROM pending WHERE hash = ?", hash);
    if (!row || row.expires < Date.now()) return { ok: false, again: true, message: "sign in again" };
    const keys = ["u:" + row.name.toLowerCase(), "ip:" + ip];
    if (this.locked(keys)) return { ok: false, locked: true, message: "too many tries - wait a quarter of an hour" };
    const user = this.one("SELECT * FROM users WHERE name = ?", row.name);
    if (!user?.totp) return { ok: false, again: true, message: "sign in again" };
    let how = "", recoveryLeft;
    const step = await totpStep(user.totp, code, user.totp_step);
    if (step) {
      this.sql.exec("UPDATE users SET totp_step = ? WHERE name = ?", step, user.name);
    } else {
      const left = JSON.parse(user.recovery || "[]");
      const typed = normaliseRecovery(code);
      const used = typed.length === 10 ? left.indexOf(await sha256(typed)) : -1;
      if (used < 0) {
        this.failed(keys);
        const tries = row.tries + 1;
        if (tries >= STEP_TRIES) this.sql.exec("DELETE FROM pending WHERE hash = ?", hash);
        else this.sql.exec("UPDATE pending SET tries = ? WHERE hash = ?", tries, hash);
        return { ok: false, again: tries >= STEP_TRIES, message: tries >= STEP_TRIES ? "sign in again" : "wrong code" };
      }
      left.splice(used, 1);
      this.sql.exec("UPDATE users SET recovery = ? WHERE name = ?", JSON.stringify(left), user.name);
      how = ` (recovery code; ${left.length} left)`;
      recoveryLeft = left.length;
    }
    this.sql.exec("DELETE FROM pending WHERE hash = ?", hash);
    this.cleared(keys);
    return { ...(await this.newSession(user, ip, agent, "signed in from " + ip + how)), recoveryLeft };
  }

  async newSession(user, ip, agent, what) {
    const token = randomToken(), now = Date.now();
    this.sql.exec("DELETE FROM sessions WHERE expires < ?", now);
    this.sql.exec("INSERT INTO sessions (hash, name, expires, created, seen, ip, agent) VALUES (?, ?, ?, ?, ?, ?, ?)",
      await sha256(token), user.name, now + SESSION_MS, now, now, String(ip).slice(0, 60), String(agent).slice(0, 200));
    this.note(user.name, "", what);
    return { ok: true, token, name: user.name, role: user.role };
  }

  async session(token) {
    if (!token) return null;
    return this.sessionByHash(await sha256(token));
  }

  // who a session is now (its role as it is now), or null once it has ended; and what it must
  // do before anything else: change a given password, set up the authenticator its role needs
  sessionByHash(hash) {
    if (!hash) return null;
    const row = this.one(`SELECT u.name, u.role, u.totp, u.must_change, s.expires, s.seen FROM sessions s
                          JOIN users u ON u.name = s.name WHERE s.hash = ?`, hash);
    if (!row || row.expires < Date.now()) return null;
    if (Date.now() - (row.seen || 0) > SEEN_EVERY_MS) this.sql.exec("UPDATE sessions SET seen = ? WHERE hash = ?", Date.now(), hash);
    const need = row.must_change ? "password" : (!row.totp && Directory.needsTotp(row.role)) ? "setup2fa" : "";
    return { name: row.name, role: row.role, expires: row.expires, totp: !!row.totp, need };
  }

  // my sessions: where and when, which is this one; ending one, or all the others
  async sessions(name, token) {
    const mine = await sha256(token);
    return this.rows("SELECT hash, created, seen, ip, agent FROM sessions WHERE name = ? AND expires > ? ORDER BY seen DESC", name, Date.now())
      .map(r => ({ id: r.hash.slice(0, 12), created: r.created, seen: r.seen, ip: r.ip, agent: r.agent, current: r.hash === mine }));
  }

  async endSessions(name, token, id) {
    const mine = await sha256(token);
    const rows = this.rows("SELECT hash FROM sessions WHERE name = ?", name)
      .filter(r => r.hash !== mine && (id === "*" || r.hash.slice(0, 12) === id));
    for (const r of rows) {
      this.sql.exec("DELETE FROM sessions WHERE hash = ?", r.hash);
      await this.dropViewers({ session: r.hash });
    }
    if (rows.length) this.note(name, "", id === "*" ? "signed out everywhere else" : "ended a session");
    return { ok: true, ended: rows.length };
  }

  async logout(token) {
    const hash = await sha256(token);
    this.sql.exec("DELETE FROM sessions WHERE hash = ?", hash);
    await this.dropViewers({ session: hash });
  }

  // the halls' open remote desks and live pages of someone whose rights changed: closed now,
  // not when they next reload (a removed person must not keep a desk open for days)
  async dropViewers(match) {
    for (const { id } of this.rows("SELECT id FROM halls")) {
      try { await this.env.HALL.get(this.env.HALL.idFromName(id)).dropViewers(match); } catch (e) { /* that hall's object is busy: it checks again on the next request */ }
    }
  }

  // -- halls ------------------------------------------------------------------------------- //
  async addHall(name, by) {
    name = cleanName(name);
    if (!name) return { ok: false, message: "a name" };
    const id = crypto.randomUUID();
    this.sql.exec("INSERT INTO halls (id, name, created) VALUES (?, ?, ?)", id, name, Date.now());
    this.note(by, id, `hall added: ${name}`);
    return { ok: true, id, ...(await this.newCode(id, by)) };
  }

  async newCode(id, by) {
    if (!this.one("SELECT id FROM halls WHERE id = ?", id)) return { ok: false, message: "no such hall" };
    const code = pairingCode();
    this.sql.exec("UPDATE halls SET pair_hash = ?, pair_expires = ? WHERE id = ?",
      await sha256(normaliseCode(code)), Date.now() + PAIR_MS, id);
    this.note(by, id, "pairing code made");
    return { ok: true, code, expires: Date.now() + PAIR_MS };
  }

  async pair(code, computer, ip) {
    const keys = ["pair:" + ip];
    if (this.locked(keys)) return { ok: false, message: "too many tries - wait a quarter of an hour" };
    const hall = this.one("SELECT * FROM halls WHERE pair_hash = ?", await sha256(normaliseCode(code)));
    if (!hall || hall.pair_expires < Date.now()) {
      this.failed(keys);
      return { ok: false, message: "this code is wrong or has expired" };
    }
    this.cleared(keys);
    const token = randomToken();
    // one computer per hall: a new pairing ends the old one's access
    this.sql.exec("UPDATE halls SET token_hash = ?, pair_hash = NULL, pair_expires = 0, computer = ? WHERE id = ?",
      await sha256(token), cleanName(computer, 80), hall.id);
    this.note(cleanName(computer, 80) || "(hall)", hall.id, "hall computer paired from " + ip);
    // the computer paired before loses its connection now (its token no longer works either)
    try { await this.env.HALL.get(this.env.HALL.idFromName(hall.id)).dropHall(); } catch (e) { /* it finds out on its next connection */ }
    return { ok: true, id: hall.id, name: hall.name, token };
  }

  async hallByToken(token) {
    if (!token) return null;
    return this.one("SELECT id, name FROM halls WHERE token_hash = ?", await sha256(token));
  }

  hall(id) {
    const row = this.one("SELECT id, name, created, online, last_seen, summary, computer, token_hash IS NOT NULL AS paired FROM halls WHERE id = ?", id);
    return row ? this.shape(row) : null;
  }

  halls() {
    return this.rows("SELECT id, name, created, online, last_seen, summary, computer, token_hash IS NOT NULL AS paired FROM halls ORDER BY name COLLATE NOCASE")
      .map(row => this.shape(row));
  }

  shape(row) {
    let summary = {};
    try { summary = JSON.parse(row.summary || "{}"); } catch (e) { /* a broken one is none */ }
    return { id: row.id, name: row.name, created: row.created, online: !!row.online, lastSeen: row.last_seen,
             summary, computer: row.computer, paired: !!row.paired };
  }

  renameHall(id, name, by) {
    name = cleanName(name);
    if (!name || !this.one("SELECT id FROM halls WHERE id = ?", id)) return { ok: false, message: "no such hall" };
    this.sql.exec("UPDATE halls SET name = ? WHERE id = ?", name, id);
    this.note(by, id, `renamed: ${name}`);
    return { ok: true };
  }

  removeHall(id, by) {
    const hall = this.one("SELECT name FROM halls WHERE id = ?", id);
    if (!hall) return { ok: false, message: "no such hall" };
    this.sql.exec("DELETE FROM halls WHERE id = ?", id);
    this.note(by, id, `hall removed: ${hall.name}`);
    return { ok: true };
  }

  hallSeen(id, online, summary) {
    if (summary === undefined) this.sql.exec("UPDATE halls SET online = ?, last_seen = ? WHERE id = ?", online ? 1 : 0, Date.now(), id);
    else this.sql.exec("UPDATE halls SET online = ?, last_seen = ?, summary = ? WHERE id = ?",
      online ? 1 : 0, Date.now(), JSON.stringify(summary || {}), id);
  }

  // -- the journal -------------------------------------------------------------------------- //
  note(user, hall, what) {
    this.sql.exec("INSERT INTO journal (at, user, hall, what) VALUES (?, ?, ?, ?)", Date.now(), user || "", hall || "", String(what).slice(0, 300));
    this.sql.exec("DELETE FROM journal WHERE id <= (SELECT MAX(id) FROM journal) - ?", JOURNAL_KEEP);
  }

  journal(hall = "", limit = 200) {
    const rows = hall
      ? this.rows("SELECT at, user, hall, what FROM journal WHERE hall = ? ORDER BY id DESC LIMIT ?", hall, limit)
      : this.rows("SELECT at, user, hall, what FROM journal ORDER BY id DESC LIMIT ?", limit);
    const names = Object.fromEntries(this.rows("SELECT id, name FROM halls").map(h => [h.id, h.name]));
    return rows.map(r => ({ ...r, hallName: names[r.hall] || "" }));
  }
}
