// Small helpers: answers, tokens, password hashing - WebCrypto only.

export const ROLES = ["viewer", "operator", "admin"];
export const rank = role => ROLES.indexOf(role);

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
