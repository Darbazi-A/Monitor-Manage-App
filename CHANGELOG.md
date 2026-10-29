# Changelog

Every version of Stage Display Controller. The installer for each is on the
[Releases](../../releases) page.

## 1.4.0 — 2026-10-29 · The desk lock

- **Lock the desk, not the show.** A lock screen on the control monitor only - the time, the
  hall, what is on the stage, a PIN pad (the admin PIN) - while the stage screens, the sound, the
  phone remote, Stage Cloud and the clicker keep working.
- On the locked desk Win, Alt+Tab, Alt+F4, Alt+Esc, Ctrl+Esc and Ctrl+Shift+Esc do nothing, the mouse
  stays on the lock screen, and the program cannot be closed; Ctrl+Alt+Del still works.
- Locked from the status bar's **Lock**, the tray, *Settings → Admin & simple desk*, the phone
  remote (the lock in its header) or Stage Cloud (**Lock** on a hall's page); unlocked with the
  PIN, or from the phone or Stage Cloud. It can lock by itself after 5-60 minutes with nobody at
  the desk, and a program started again while locked locks again at once.
- While locked, a file that will not play is told to the phone and Stage Cloud instead of a
  dialog nobody can answer.

## 1.3.3 — 2026-10-29 · Signing in on web pages

- **Canva, Kahoot and other pages: signing in with Google (or Microsoft, Apple, Facebook) works.**
  The sign-in opens in a small window of its own on the desk, and closes by itself once done;
  the page that asked for it gets the answer. Before, the sign-in replaced the page and left it
  white. The login is remembered, as before.
- The desk's live picture of a web page on the stage follows closely while it is worked on (a
  click, a key, the clicker) and is taken about once a second otherwise - much less work for the
  computer.
- The clicker is as it was: while a page is on the stage, Page Down / Page Up turn it from any
  program, and the rest of the keyboard stays free.

## 1.3.2 — 2026-10-29 · A new look for the remote

- **The phone remote looks new** — on a phone, and in Stage Cloud's remote desk: real icons in
  coloured chips instead of emoji, the screens' pictures with ON AIR badges, a big NEXT, a clean
  bar for BLACKOUT, Undo and Stop sound, new sliders, sheets and PIN pad, Stage Cloud's colours.
  On a wider screen, more tiles in a row. Everything works as before.
- Pairing with Stage Cloud tries again for about half a minute when the network refuses, and
  says so plainly; an address copied whole from the browser is cut down to the site's name.

## 1.3.1 — 2026-10-28 · Stage Cloud, at once

- A change in the hall — a screen opened or closed, another file, the next step — reaches Stage
  Cloud within seconds, not at the next half-minute.
- The remote desk opens in the website's language.
- The website itself is new: made for a phone first (tabs at the bottom, sheets from below, an
  app on the home screen), a sidebar on a computer, live pictures of each hall's screens,
  ready-made messages, a journal by day in Georgian, light and dark.

## 1.3.0 — 2026-10-28 · Stage Cloud

- **Every hall on one website.** [Stage Cloud](cloud/README.md) shows which halls are on, their
  version, their screens and what is on them, the running order and problems — from anywhere.
- From there: look for an update, install it, show the operator a message — and the **remote
  desk**: the hall's own phone remote over the internet (screens, files from the browser,
  running order, slides, text, sound, scenes, web pages, laptops).
- People sign in as viewers, operators or administrators; everything done goes in a journal.
- In the hall: *Settings → Cloud* — the address and a code, **Pair**. The connection comes back
  by itself. *Allow running this hall from the dashboard* can be switched off; whatever the
  website does is shown at the desk, with who did it.
- The website runs on Cloudflare's free plan (`cloud\`).

## 1.2.0 — 2026-10-28 · Updates by themselves

- **The program updates itself.** It looks for a new version on GitHub a little
  after it starts, then every six hours; a newer one is downloaded in the
  background and checked against GitHub's SHA-256. A chip in the status bar says
  an update is ready.
- **Nothing changes during a show**: the update goes in when the program is
  closed — or at once with *Settings → Updates → Install now*, which closes the
  program, installs it and opens it again (about a minute). The presets, running
  orders, the hall and the settings stay.
- *Settings → Updates*: this version, what was found, **Check now**, *What's new*,
  and both switches (looking by itself, installing on closing).
- A computer without internet tries again later; run from source, the program only
  says a new version is out.
- From this version on, every hall updates itself: 1.0.0 and 1.1.0 need this one
  installed by hand, once.

## 1.1.0 — 2026-10-27 · Any hall

- **Any hall, not only this one.** *Settings → Hall → Set up the hall…*: up to
  eight stage screens, each with its own name and kind (a screen, or the one LED
  strip with the running text). **Find the screens** proposes a hall from the
  monitors connected now; **Show numbers on the monitors** tells them apart.
  Saving restarts the program with the new hall.
- Everything follows the hall: the Live page's cards, the header's pictures, the
  wiring, the number keys, the running order, the scenes, the library and
  *Build a show from a folder*, the rehearsal window, the compact bar, the simple
  desk, the timer, text and the phone.
- **A hall in a file**: *Save to a file…* / *Open a file…* carry the hall, its
  scenes and running orders to another computer (`.stagehall`).
- A new installation opens the hall wizard by itself the first time.
- Without a hall file the hall is the original one (Main Stage, Side Screens,
  the ceiling strip): nothing changes for a hall already in use.
- Fixed: a video that would not play lost its name in the message about it.

## 1.0.0 — 2026-10-27 · The first installer

The program as one Windows installer — no Python or anything else needed on the
PC — with everything built since September 2026:

- **The stage**: one dashboard for the Main Stage, the Side Screens and the
  ceiling LED strip; videos and pictures with crossfades or dips to black;
  playlists; presets (scenes) as pictures; a scrolling marquee; text slides for
  names on screen; dark room; BLACKOUT; undo; PREVIEW → TAKE; a ready check.
- **Running order**: one NEXT button for a whole event, steps that set every
  screen, the sound, text and slides; steps that go on by themselves.
- **Presentations**: PDF and PowerPoint (with its animations), a clicker that
  always works, a guest phone clicker, a speaker's time limit, a video in the
  middle of a talk with pause and seek.
- **Sound**: eight cues on F1–F8, a DJ desk with two decks and a mixer.
- **Laptops**: any laptop's screen and sound on the Main Stage over Wi-Fi, with
  a silent preview first, two laptops side by side.
- **Canva, Kahoot and the web** on the Main Stage, prepared silently on the desk.
- **School timer**: countdown, until a time, stopwatch or clock, in six looks
  and five sizes.
- **The phone** as a whole stage desk for teachers: screens, files sent from
  the phone, the running order, presentations, text, sound, scenes, Canva and
  Kahoot, laptops, rehearsals.
- **Desk**: navigation rail, an admin PIN and a simple desk for guests,
  English or Georgian, touch screens, Windows 11 look, the icon by the clock.
- **Reliability**: screens that come back by themselves, recovery after a crash,
  automatic backups of the presets and running orders.
- **Installer**: installs for the current user without administrator rights;
  the built program checks itself before an installer is made.
