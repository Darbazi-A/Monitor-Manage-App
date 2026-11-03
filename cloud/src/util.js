// Small helpers: answers, tokens, password hashing - WebCrypto only.

// who someone is in the whole cloud: a main administrator (every hall, the people), or a member
// who has rights in the halls they were given
export const GLOBAL_ROLES = ["member", "admin"];

// what one may do in one hall. A role is a starting set of rights; each right can be given or
// taken away person by person. Anything not listed here is refused.
export const RIGHTS = ["control", "web", "files", "message", "journal", "desk", "updates", "pair", "manage"];
export const HALL_ROLES = ["viewer", "operator", "technician", "halladmin"];
const OPERATOR = ["control", "web", "files", "message", "journal"];
const TECHNICIAN = [...OPERATOR, "desk", "updates", "pair"];
export const ROLE_RIGHTS = { viewer: [], operator: OPERATOR, technician: TECHNICIAN, halladmin: [...TECHNICIAN, "manage"] };
export const cleanRights = list => RIGHTS.filter(right => Array.isArray(list) && list.includes(right));

// every answer: no sniffing, no framing by other sites, no referrer, HTTPS from now on
export const SECURITY_HEADERS = {
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
  "Strict-Transport-Security": "max-age=31536000",
  "Cross-Origin-Opener-Policy": "same-origin",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
};

// the dashboard: its own scripts only (no inline ones), its own frame (the remote desk), nobody frames it
export const PAGE_CSP = [
  "default-src 'self'", "script-src 'self'", "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "font-src https://fonts.gstatic.com", "img-src 'self' data: blob:", "connect-src 'self'", "frame-src 'self'",
  "manifest-src 'self'", "object-src 'none'", "base-uri 'none'", "form-action 'self'", "frame-ancestors 'none'",
].join("; ");

// the remote desk's frame: the hall's phone page and its inline scripts, but it reaches nothing -
// its requests go to the dashboard by postMessage - and only this site's dashboard may frame it
// (by its address: the frame is sandboxed, an opaque origin, which 'self' would not match)
export const frameCsp = origin => [
  "default-src 'none'", "script-src 'unsafe-inline'", "style-src 'unsafe-inline'", "img-src data: blob:",
  "media-src data: blob:", "font-src data:", "connect-src 'none'", "object-src 'none'", "base-uri 'none'",
  "form-action 'none'", `frame-ancestors ${origin}`,
].join("; ");

export function json(value, status = 200, headers = {}) {
  return new Response(JSON.stringify(value), {
    status, headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", ...SECURITY_HEADERS, ...headers },
  });
}

export const fail = (status, message) => json({ ok: false, message }, status);

const encoder = new TextEncoder();

export function b64url(bytes) {
  let text = "";
  for (const byte of bytes) text += String.fromCharCode(byte);
  return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function randomToken(size = 32) {
  return b64url(crypto.getRandomValues(new Uint8Array(size)));
}

// a pairing code a person can type: no 0/O, 1/I/L
const CODE_LETTERS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";
export function pairingCode() {
  const bytes = crypto.getRandomValues(new Uint8Array(8));
  const chars = [...bytes].map(b => CODE_LETTERS[b % CODE_LETTERS.length]).join("");
  return chars.slice(0, 4) + "-" + chars.slice(4);
}
export const normaliseCode = code => String(code || "").toUpperCase().replace(/[^A-Z0-9]/g, "");

export async function sha256(text) {
  const digest = await crypto.subtle.digest("SHA-256", encoder.encode(text));
  return [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, "0")).join("");
}

const ITERATIONS = 100000;            // the most the Workers runtime allows
export async function hashPassword(password, salt = randomToken(16)) {
  const key = await crypto.subtle.importKey("raw", encoder.encode(password), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", hash: "SHA-256", salt: encoder.encode(salt), iterations: ITERATIONS }, key, 256);
  return { salt, hash: b64url(new Uint8Array(bits)) };
}

export function sameText(a, b) {
  const x = encoder.encode(String(a)), y = encoder.encode(String(b));
  if (x.length !== y.length) return false;
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

export async function checkPassword(password, salt, hash) {
  const again = await hashPassword(password, salt);
  return sameText(again.hash, hash);
}

export function cookie(request, name) {
  for (const part of (request.headers.get("Cookie") || "").split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return rest.join("=");
  }
  return "";
}

export const cleanName = (text, size = 60) => String(text || "").replace(/[\u0000-\u001f<>]/g, "").trim().slice(0, size);

// -- two-step sign-in: TOTP (RFC 6238 - Google / Microsoft Authenticator), recovery codes ----------- //
const B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
export function base32(bytes) {
  let bits = 0, value = 0, out = "";
  for (const byte of bytes) {
    value = (value << 8) | byte; bits += 8;
    while (bits >= 5) { out += B32[(value >>> (bits - 5)) & 31]; bits -= 5; }
  }
  if (bits > 0) out += B32[(value << (5 - bits)) & 31];
  return out;
}
export function unbase32(text) {
  let bits = 0, value = 0;
  const out = [];
  for (const char of String(text).toUpperCase().replace(/[^A-Z2-7]/g, "")) {
    value = (value << 5) | B32.indexOf(char); bits += 5;
    if (bits >= 8) { out.push((value >>> (bits - 8)) & 255); bits -= 8; }
  }
  return new Uint8Array(out);
}
export const newTotpSecret = () => base32(crypto.getRandomValues(new Uint8Array(20)));

async function hotp(secret, counter) {
  const key = await crypto.subtle.importKey("raw", unbase32(secret), { name: "HMAC", hash: "SHA-1" }, false, ["sign"]);
  const message = new Uint8Array(8);
  let c = counter;
  for (let i = 7; i >= 0; i--) { message[i] = c & 255; c = Math.floor(c / 256); }
  const mac = new Uint8Array(await crypto.subtle.sign("HMAC", key, message));
  const at = mac[19] & 15;
  const number = ((mac[at] & 127) << 24) | (mac[at + 1] << 16) | (mac[at + 2] << 8) | mac[at + 3];
  return String(number % 1000000).padStart(6, "0");
}

// the time step a code is right for (a step either side, for a clock a little off), or 0;
// a step at or before `after` was used already and is refused (a code works once)
export async function totpStep(secret, code, after = 0, now = Date.now()) {
  code = String(code || "").replace(/\s/g, "");
  if (!secret || !/^\d{6}$/.test(code)) return 0;
  const step = Math.floor(now / 30000);
  for (const s of [step, step - 1, step + 1]) {
    if (s > after && sameText(await hotp(secret, s), code)) return s;
  }
  return 0;
}

// ten one-time codes for a lost phone: XXXXX-XXXXX, kept only as hashes
export function recoveryCodes(count = 10) {
  const letters = "abcdefghjkmnpqrstuvwxyz23456789";
  return Array.from({ length: count }, () => {
    const chars = [...crypto.getRandomValues(new Uint8Array(10))].map(b => letters[b % letters.length]).join("");
    return chars.slice(0, 5) + "-" + chars.slice(5);
  });
}
export const normaliseRecovery = code => String(code || "").toLowerCase().replace(/[^a-z0-9]/g, "");
