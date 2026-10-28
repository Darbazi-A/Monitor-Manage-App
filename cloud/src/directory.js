// The directory: one Durable Object (SQLite) with the people, their sessions, the halls,
// pairing codes, the journal and the lock-outs. The Worker calls its methods over RPC.
import { DurableObject } from "cloudflare:workers";
import {
  ROLES, checkPassword, cleanName, hashPassword, normaliseCode, pairingCode, randomToken, sha256,
} from "./util.js";

const SESSION_MS = 14 * 24 * 3600 * 1000;
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
      CREATE TABLE IF NOT EXISTS failures (key TEXT PRIMARY KEY, count INTEGER, until INTEGER);`);
  }

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
    this.sql.exec("INSERT INTO users (name, role, salt, hash, created) VALUES (?, ?, ?, ?, ?)", name, role, salt, hash, Date.now());
    this.note(by, "", `user added: ${name} (${role})${ip ? " from " + ip : ""}`);
    return { ok: true };
  }

  users() { return this.rows("SELECT name, role, created FROM users ORDER BY name COLLATE NOCASE"); }

  setRole(name, role, by) {
    if (!ROLES.includes(role) || !this.one("SELECT name FROM users WHERE name = ?", name)) return { ok: false, message: "no such user" };
    if (role !== "admin" && this.lastAdmin(name)) return { ok: false, message: "the last administrator stays one" };
    this.sql.exec("UPDATE users SET role = ? WHERE name = ?", role, name);
    this.note(by, "", `role of ${name}: ${role}`);
    return { ok: true };
  }

  removeUser(name, by) {
    if (!this.one("SELECT name FROM users WHERE name = ?", name)) return { ok: false, message: "no such user" };
    if (this.lastAdmin(name)) return { ok: false, message: "the last administrator stays" };
    this.sql.exec("DELETE FROM users WHERE name = ?", name);
    this.sql.exec("DELETE FROM sessions WHERE name = ?", name);
    this.note(by, "", `user removed: ${name}`);
    return { ok: true };
  }

  lastAdmin(name) {
    const admins = this.rows("SELECT name FROM users WHERE role = 'admin'");
    return admins.length === 1 && admins[0].name === name;
  }

  async setPassword(name, password, by, old = null) {
    const user = this.one("SELECT * FROM users WHERE name = ?", name);
    if (!user) return { ok: false, message: "no such user" };
    if (old !== null && !(await checkPassword(old, user.salt, user.hash))) return { ok: false, message: "wrong password" };
    if (String(password || "").length < 8) return { ok: false, message: "password: at least 8 characters" };
    const { salt, hash } = await hashPassword(password);
    this.sql.exec("UPDATE users SET salt = ?, hash = ? WHERE name = ?", salt, hash, name);
    this.sql.exec("DELETE FROM sessions WHERE name = ?", name);    // signed out everywhere
    this.note(by, "", by === name ? "own password changed" : `password of ${name} reset`);
    return { ok: true };
  }

  // -- sessions --------------------------------------------------------------------------- //
  async login(name, password, ip) {
    const keys = ["u:" + String(name).toLowerCase(), "ip:" + ip];
    if (this.locked(keys)) return { ok: false, locked: true, message: "too many tries - wait a quarter of an hour" };
    const user = this.one("SELECT * FROM users WHERE name = ? COLLATE NOCASE", cleanName(name, 40));
    if (!user || !(await checkPassword(password, user.salt, user.hash))) {
      this.failed(keys);
      return { ok: false, message: "wrong name or password" };
    }
    this.cleared(keys);
    const token = randomToken();
    this.sql.exec("DELETE FROM sessions WHERE expires < ?", Date.now());
    this.sql.exec("INSERT INTO sessions (hash, name, expires) VALUES (?, ?, ?)", await sha256(token), user.name, Date.now() + SESSION_MS);
    this.note(user.name, "", "signed in from " + ip);
    return { ok: true, token, name: user.name, role: user.role };
  }

  async session(token) {
    if (!token) return null;
    const row = this.one(`SELECT u.name, u.role, s.expires FROM sessions s JOIN users u ON u.name = s.name
                          WHERE s.hash = ?`, await sha256(token));
    if (!row || row.expires < Date.now()) return null;
    return { name: row.name, role: row.role };
  }

  async logout(token) { this.sql.exec("DELETE FROM sessions WHERE hash = ?", await sha256(token)); }

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
