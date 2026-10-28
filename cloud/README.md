# Stage Cloud

One website for every hall that runs Stage Display Controller: which halls are on, their
version, their screens and what is on them, the running order and problems — and, from
anywhere, the commands (look for an update, install it, a message for the operator) and the
**remote desk**: the hall's own phone remote, over the internet.

It runs on Cloudflare's free plan: a Worker (the site and its API) and Durable Objects (one
*directory* with the people, halls and journal; one object per hall, which keeps the hall's
WebSocket and passes the remote desk's requests to it). Nothing to maintain, no server.

## How it fits together

```
 hall PC (Stage Display Controller)            Stage Cloud (Cloudflare)              a browser, anywhere
 Settings → Cloud: address + code   ──pair──▶  /hall/pair     → a token for the hall
 WebSocket with the token           ◀───────▶  Hall object     ◀── /api/halls/<id>/live ──  the dashboard
   every 30 s: status                          (status, log)        (signed in: name + password)
   answers: commands, the phone page's API     Directory (people, sessions, halls, journal)
```

- **People** sign in with a name and password. *Viewers* see the halls; *operators* also send
  commands and use the remote desk; *administrators* also add halls and people. Five wrong
  passwords lock a name for a quarter of an hour (twenty lock an address).
- **Halls** pair once with a code from the dashboard (*Add a hall* or *Pair again*: one use, 30
  minutes). A new pairing ends the old computer's access.
- **The remote desk** is the hall's phone page in a sandboxed frame: its requests go over the
  WebSocket to the hall, which answers them as it answers a phone. A hall can switch it off:
  *Settings → Cloud → Allow running this hall from the dashboard*. Whatever is done shows at the
  hall's desk, with who did it, and goes in the **journal**.

## Putting it online

Once, on this computer (in this folder, `cloud\`):

1. A free Cloudflare account: <https://dash.cloudflare.com/sign-up>.
2. `npm install` (wrangler, Cloudflare's tool).
3. `npx wrangler login` — a browser window asks to allow wrangler; allow it.
4. The setup key (a long random word, only for making the first administrator):
   `npx wrangler secret put SETUP_KEY`
5. `npx wrangler deploy` — it prints the address, `https://stage-cloud.<your-name>.workers.dev`.
6. Open it, make the first administrator with the setup key, then *Add a hall* and type its code
   in each hall's program (*Settings → Cloud*).

A new version of the site: `npx wrangler deploy` again (the halls stay connected or come back by
themselves). Cloudflare can also deploy by itself on every push to GitHub: *Workers & Pages →
stage-cloud → Settings → Builds → Connect*, root directory `cloud`.

## On this computer

```
npx wrangler dev                              # http://127.0.0.1:8787, SETUP_KEY from .dev.vars
node test/with_server.mjs test/server_test.mjs   # the cloud's own test, on a fresh local cloud
node test/words_test.cjs                      # every word of the dashboard has its Georgian
```

`.dev.vars` (not in git) holds `SETUP_KEY=…` for `wrangler dev`.

| File | What |
| --- | --- |
| `src/index.js` | The Worker: routes, signing in, who may do what, commands |
| `src/directory.js` | The directory (SQLite): people, sessions, halls, pairing codes, lock-outs, the journal |
| `src/hall.js` | One hall: its WebSocket, its status and log, passing the remote desk's requests |
| `src/util.js` | Answers, tokens, PBKDF2 passwords |
| `public/` | The dashboard: `app.js` (halls, a hall, the remote desk, journal, people), `i18n.js` (Georgian), `style.css` |
