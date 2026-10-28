# Changelog

Every version of Stage Display Controller. The installer for each is on the
[Releases](../../releases) page.

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
