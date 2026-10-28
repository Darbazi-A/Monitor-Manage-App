// Small helpers: answers, tokens, password hashing - WebCrypto only.

export const ROLES = ["viewer", "operator", "admin"];
export const rank = role => ROLES.indexOf(role);

export function json(value, status = 200, headers = {}) {
  return new Response(JSON.stringify(value), {
    status, headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", ...headers },
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
