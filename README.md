# Stage Display Controller

A multi-screen playback controller for a school assembly hall stage, written in
Python with PySide6 (Qt 6). One operator dashboard drives three stage outputs.

![Live tab](docs/live.png)

## The setup it drives

| Output | Screen | Notes |
| --- | --- | --- |
| **Main Stage** | large central screen | not always-on-top, so a presentation or browser can be shown over the background |
| **Side Screens** | left + right | mirrored by the video hardware, so the app renders **one** window for both |
| **Top Screen** | ceiling LED strip | background *plus* a scrolling marquee composited over it |

## Features

- **Display routing** — assign each role to a physical monitor; the widest
  monitor is auto-detected as the ceiling strip.
- **Custom output geometry** — LED processors (Nova Studio, LVP, …) often map a
  canvas that differs from the resolution Windows reports. The ceiling strip
  reports `2816×256` but is driven at `2818×132`, so every output can be given an
  exact width/height/offset instead of plain fullscreen.
- **Playlists** — prepare several backgrounds per screen before an event, then
  switch instantly by clicking an entry or using the prev/next arrows. Entries
  are numbered and can be dragged into the running order.
- **Real video posters** — a frame is pulled out of each clip, so previews and
  playlists show the footage rather than a film icon.
- **Position bar** — elapsed / total per screen, draggable to seek, so nobody is
  guessing how long a clip has left.
- **Sound cues** — eight small players on `F1`–`F8`: play, pause, resume, stop
  and a seek bar each. Every cue has its own player, so a fanfare fires over a
  bed of music instead of interrupting it. Per-cue loop, a master level, a
  sound-device picker, and fades rather than hard cuts.
- **Keyboard control** — `1` `2` `3` pick a screen, `←` `→` step through its
  playlist, `Space` plays/pauses, `F1`–`F8` fire sound cues, `B` blacks out.
- **Text slides** — names on screen over whatever is running, prepared as a
  plain running order (one line per slide) and stepped through live. Sized to
  fit, so a long name shrinks instead of being chopped off.
- **Build a show from a folder** — point it at the event's folder and it sorts
  everything onto the right screens by shape and by name, fills the three
  playlists and the sound cues, and shows you the plan before it acts.
- **Media library** — browse the folders the event material lives in, with real
  thumbnails, a name filter and pinned folders. Send one item straight to a
  screen, fill a playlist from a multi-selection, or drop a sound onto a cue.
- **Drag & drop** everywhere; drop several files at once to fill a playlist.
- **Transitions** — a crossfade that dissolves the old picture into the new one,
  or a fade through black. Off / Fast / Normal / Slow, applied to every screen,
  to playlist steps and to blackouts.
- **Refuses bad files instead of stalling** — every file is checked before it
  reaches a screen, and anything unusable is explained in plain language with a
  suggested fix. Clips that cannot be decoded are flagged red in the playlist
  *before* the show.
- **Scaling modes** — Stretch, Fit (keep aspect), Fill (crop to cover).
- **Repeat** — on by default, per screen.
- **Marquee** — text, typeface, pixel size, colour and scroll speed, drawn over
  live video via a `QGraphicsScene`.
- **Presets** — routing, geometry, playlists, scaling, volumes and marquee
  settings saved as JSON, on their own labelled row that shows which preset is
  on the screens and whether it has unsaved changes. Loading one transitions
  every screen rather than cutting, and **New** clears everything back to blank
  for building the next show (monitor routing is kept — that is the hall's
  wiring, not the event).
- **Start with Windows** — optionally open the app at login and put a chosen
  preset on the screens, after a delay that lets LED processors finish booting.
- **Compact bar** — shrink the dashboard to a strip that floats above
  everything: which screen the arrows drive and what is on it, play/pause,
  preset, the eight cues with what is running, silence and blackout.
- **DJ desk** — two animated turntables with beat-grid waveforms, sync, loops
  and hot cues, a kill-EQ/filter/echo mixer with headphone cue and recording,
  and a synthesised techno machine (drums + acid bass) that can lock to a deck.
- **Running order** — an event as steps (screens, sound, text, marquee, notes,
  auto-advance), run with one NEXT button, `Page Down` or a presenter clicker.
- **Slides** — PDF and PowerPoint straight from the app, with presenter view
  (next slide, notes, timer), a clicker that works whichever window is in
  front, and a phone page for turning slides.
- **Phone remote** — NEXT, BLACKOUT, sound cues and presets from any phone on
  the Wi-Fi, behind a PIN.
- **Blackout** — clears every stage screen at once.
- Stage windows are frameless, cannot be closed by the audience, and stay out of
  the taskbar (`Qt.Tool`), so only the dashboard appears there.

## Install

```
pip install PySide6 numpy
python main.py
```

Python 3.9+. Windows is the target platform; video playback uses Qt's Windows
Media Foundation backend, so codec support is whatever the machine has (H.264 /
MP4 is the safe choice).

## Running a show

1. **Screens & Setup** → assign the monitors → **Apply routing / Open outputs**.
   Use *Identify monitors* if Windows has shuffled the order.
2. Back on **Live**, drop the prepared media onto each card.
3. During the event, click a playlist entry (or the ◀ ▶ arrows) to switch.
4. Save it all as a preset so the next assembly is one click away.

The dashboard opens filling the screen and comes back the size it was left.
Applying a preset never moves or un-maximises it — that used to drag the window
to one side before every show.

`Escape` on a stage screen closes just that window; press **OPEN OUTPUTS** to
bring it back. Quitting while outputs are live asks first — closing the app
blacks out the hall.

### Keys

| | |
| --- | --- |
| `1` `2` `3` | choose the screen the keyboard drives (it gets an accent border) |
| `←` `→` | previous / next entry in that screen's playlist |
| `Space` | play / pause that screen |
| `F1`–`F8` | play / pause that sound cue |
| `Shift`+`F1`–`F8` | stop it and rewind |
| `Ctrl`+`Space` | fade out every sound cue |
| `Ctrl`+`→` / `Ctrl`+`←` | next / previous name on the Text tab |
| `Ctrl`+`H` | hide the text |
| `B` | blackout every screen (pictures only — sound keeps playing) |
| `Ctrl`+`O` | apply routing / open outputs |
| `Page Down` / `Page Up` | next / previous step of the running order — what a wireless presenter clicker sends; while slides are on screen, next / previous slide |

While slides are on screen the clicker's other keys work as in PowerPoint:
`→` `↓` `Space` `Enter` next, `←` `↑` `Backspace` back, `B` or `.` black, `F5`
back from black, `Esc` ends the presentation (it never closes a stage screen).

## Running order (one button: NEXT)

![Show tab](docs/show.png)

The **Show** tab turns an event into a list of steps — *Doors open, Welcome,
Anthem, Director's speech, Awards, Closing* — and runs it with one button. Each
step says what happens, and everything it does not mention is left alone:

- **each screen** (Main, Sides, Top): show a file (repeat or play once, with or
  without the video's own sound), go black, or leave it.
- **sound**: play a file (it fades over from whatever the previous step was
  playing), fade the music out, fade out *all* sound, or leave it.
- **words on screen**: show a name (and a second line) on any screen, styled as
  on the Text tab, or hide it.
- **the ceiling marquee**: scroll a text, or stop.
- **then**: wait for NEXT, go on by itself after so many seconds, or when the
  Main Stage video or the step's sound ends.
- **notes** for whoever runs the show — who speaks, what to wait for — shown
  large under NOW.

During the event: **NEXT** (the big button, `Page Down`, a presenter clicker,
the compact bar, or the phone) runs the next step; **Back** goes one step back;
double-click any step (or *Go to this step*) jumps to it. Back and jumps land
exactly where walking there would have: the app replays what the earlier steps
set up, and leaves anything already right untouched — a background that is
already playing is not restarted, and a one-off fanfare from an earlier step is
not replayed. NOW and NEXT are shown at the top with a countdown when a step
goes on by itself; closed outputs open by themselves when a step needs them.

**From stage** adds a step that recreates whatever is on the screens right now
— set the look up on the Live tab, capture it, name it. Steps can be reordered
(▲ ▼ or drag), duplicated and deleted, also while the show runs: NOW stays on
the step that is actually running. Running orders are saved as you edit, in
`shows.json` next to the app, and can be copied for the next event. Missing
files are flagged in the toolbar before the show, not during it.

## Slides (presentations)

![Slides tab](docs/presentation.png)

The **Slides** tab shows a presentation on any stage screen without leaving the
app — no PowerPoint window on the stage, no switching programs.

- **Opens** PDF, PowerPoint (`.pptx`, `.ppt`, `.ppsx`, …) and a folder of
  pictures. PDFs are drawn by the app itself; PowerPoint files are converted by
  the PowerPoint installed on this PC — hidden slides are skipped and the
  speaker notes are kept. Without PowerPoint, save the deck as PDF.
- **Prepared in the background and cached**: a PDF's first slide is ready at
  once; a PowerPoint deck shows its slides as they convert (PowerPoint's own
  start-up takes 10–20 s the first time). Opened again, a deck is ready
  instantly. Slides are rendered at the screen's size, 1920×1080 on the Main
  Stage.
- **Presenter view**: the current slide (marked LIVE, BLACK or PREVIEW), the
  next slide, the speaker notes, a slide counter and how long the slides have
  been on screen; thumbnails of every slide — tap one to jump.
- **Show on screen** puts the slides over the screen's background with a quick
  dissolve; **End** puts the background back exactly as it was. **Black** blacks
  out just that screen.
- Slides can be moved before going on screen, so the talk starts on the right
  slide.

**The clicker.** Page Down / Page Up (what almost every clicker sends), the
arrows, Space and Enter turn slides; B blacks out; Esc ends. It works:

- when a **stage window** has focus as well as the dashboard;
- when **another program is in front** — while slides are on screen, the
  clicker's keys are registered with Windows for the app
  (*Works even when another program is in front*, on by default, released the
  moment the talk ends);
- with **unusual clickers**: *Learn my clicker…* asks you to press its buttons
  once and remembers whatever keys they send.

The clicker bar shows the last key it received and what it did, so a dead
battery is obvious before the show. When no slides are on screen, the clicker's
forward / back walk the running order instead.

**In the running order**, a step can *start this presentation* on a chosen
screen or *end the presentation*; a later step that puts something else on that
screen takes it over.

## Phone remote

**Show → Phone remote** puts the running order on any phone or tablet on the
same Wi-Fi — nothing to install: switch it on, open the address it shows (for
example `http://192.168.1.23:8765`) in the phone's browser, and type the
four-digit PIN once.

- **SHOW**: NOW with the step's notes and running time, a thumb-sized **NEXT**,
  Back, Start over, and the whole running order — tap a step, then GO.
- **STAGE**: BLACKOUT, which file each screen shows, the eight sound cues
  (tap to play / pause), Silence, the master volume, and the presets.
- **SLIDES** (`/slides`, a page of its own for the presenter or whoever is
  standing in for a flat clicker battery): the current and next slide as
  pictures, the notes, the slide counter and time, a huge NEXT, Back, Black and
  Show / End. A Bluetooth clicker paired with the phone drives this page too.

It is off until switched on, and it stays on across restarts once it is. Every
request needs the PIN; *New PIN* locks out phones that knew the old one; an
address that gets the PIN wrong five times is locked out for a minute. A double
tap on NEXT cannot skip a step. The first time it is switched on, Windows asks
whether Python may use the network — allow it on private networks. The page can
be added to the phone's home screen as a shortcut.

## Building a show from a folder

![Event folder](docs/event.png)

An event's material already lives in one folder — the backgrounds, the clips,
the fanfares. **Library → Build a show from a folder…** reads that folder,
works out where each file belongs, and fills the three playlists and the sound
cues in one step.

It decides by two things:

- **Name.** Any word in the file name or the folders under the event that says
  where it goes — `top`, `zeda`, `ზედა`, `ceiling`, `strip`, `ჭერ` for the
  ceiling; `side`, `gverd`, `გვერდ` for the sides; `main`, `ცენტრ` for the
  middle. A folder called `Top` does it too.
- **Shape.** Failing a name, the pixels decide: `≥ 4:1` is the ceiling strip,
  anything taller than it is wide goes to the mirrored side screens, the rest to
  the main screen, and audio becomes a sound cue.

Name beats shape on purpose: a 1280×720 clip called
`ლაზერების ფონი გვერდების.mp4` is 16:9 but the operator wrote "of the sides" in
its name, and meant it.

Sizes come from container metadata rather than decoded frames — six clips take
about 0.2 s — so a whole folder is sorted while you wait. Nothing is applied
until you have seen the list, and every row has a dropdown to move it or skip
it.

## The compact bar

![Compact bar](docs/mini.png)

The ⤡ button in the header shrinks the dashboard to this strip, which stays on
top of whatever else is running and can be dragged anywhere. It carries only
what gets used under pressure: pick a preset and load it, step the running
order, fire the eight cues, silence the sound, blackout. Cue buttons light green
while playing and gold while paused, exactly as the full pads do. ⤢ brings the
dashboard back where it was.

## Sound

The desk sits along the bottom of the Live tab rather than behind a tab of its
own: during a ceremony the operator changes a background and fires a fanfare in
the same minute, and looking away from the screens is exactly the wrong thing to
ask for. Drop a sound file on a pad, or click an empty one to browse.

Each pad is a small player — play/pause, stop, elapsed and remaining, and a bar
you can drag to move through the sound. `F1` plays and pauses; `Shift`+`F1`
stops and rewinds. Clicking the pad body plays or pauses too, because during a
ceremony that is the fast path.

Each cue owns a separate `QMediaPlayer`, which is what lets a fanfare play over
music. Pausing and stopping animate the level to zero first
(`QAudioOutput.volume`) and starting fades up — a PA cut dead is far more
noticeable than the sound itself. Blackout is deliberately visual only;
`Ctrl`+`Space` is the sound equivalent.

**Output device** picks which sound card everything plays through — cues *and*
video audio. On a hall PC feeding a mixing console this matters: the default
Windows device is rarely the one going to the PA.

## Text slides

![Text tab](docs/text.png)

Built for award ceremonies. The running order is a plain text box, one slide per
line, because the list already exists in a document and can be pasted straight
in; a line may carry a second, smaller line after `|`. Click a slide, or use
`Ctrl`+`→`, and it appears on the chosen screen.

The text is drawn into the same `QGraphicsScene` as the background, so it
composites over live video — the reason the outputs stopped using `QVideoWidget`.
A dark band behind it keeps it readable over busy footage, and anything wider
than the screen is scaled down rather than clipped at the edges. Clearing a
screen takes the text with it, so a blackout cannot leave a name floating.

## Library

![Library tab](docs/library.png)

Pin the folders an event's material lives in and they stay in the picker. The
grid shows what each file actually is — a frame pulled from every clip, the
picture itself for images — on fixed-size tiles so the rows stay even whatever
shape the media is, including the 2816×128 strips cut for the ceiling.

Selecting one item enables **Show now on**; selecting several enables **Add to
playlist**, which is how an event gets prepared. Sound files offer the cue slots
instead, and the buttons that do not apply are simply disabled.

## Transitions

![A crossfade between two backgrounds](docs/crossfade.png)

Set the length and style in **Screens & Setup → Transition**.

**Crossfade** takes a still of what is on screen, swaps the media behind it, then
dissolves the still away — the hall never goes dark. This is why every output is
drawn through a `QGraphicsScene` rather than a `QVideoWidget`: a video widget
renders to its own surface, which cannot be captured, so there would be nothing
to dissolve *from*. It works for image→video, video→video and video→image alike.

**Through black** fades out, swaps while nothing is visible, and fades back in.
Blackouts always use this — there is nothing to dissolve into.

Loading a preset transitions too. A screen whose window has only just been
opened cuts straight in, because there is no previous picture to dissolve away
from.

Mechanically each output owns a black top-level window, faded with
`windowOpacity`. Two things that had to be right: the overlay is constructed
*with the output as its parent*, because an owned window stays above its owner
and setting a transient parent after the native window exists is too late; and it
mirrors the output's always-on-top flag, since a topmost window sits above a
non-topmost one whoever owns whom.

## When a file will not play

Nothing reaches a screen unchecked. `describe_media()` verifies the file exists,
is not empty, has a known extension, and — for images — actually decodes, by
reading a 32×32 version first, which catches the half-copied files that pass a
header check. Videos are matched against the containers the machine's backend
reports it can demux.

This build of Qt decodes **H.264, MPEG-1/2/4, WMV and MotionJPEG**. It cannot
decode H.265/HEVC, VP9 or AV1, and it cannot open WebM or FLV at all — those are
refused up front with the reason and a conversion recipe rather than freezing the
player. Playback errors that only surface at decode time are caught too: the
screen is cleared rather than left on a frozen half-frame.

Sound files are checked the same way, and a sound file dropped on a screen (or a picture dropped on a cue) is refused with a note saying where it does belong.

Supported image types come from `QImageReader.supportedImageFormats()` at
startup, so whatever the installed Qt can read — SVG, ICO, JFIF, TGA and the rest
— is accepted rather than rejected by a hardcoded list.

## DJ desk

![The DJ tab](docs/dj.png)

A **DJ** tab with two turntables, a three-channel mixer, a techno machine and a
crate. It runs its own audio engine on a separate thread, so a busy dashboard
never makes the sound stutter, and it is only started the first time the tab
opens. The preset bar steps aside on this tab to give the desk the height; the
header, with BLACKOUT, stays.

**Loading.** Tracks are decoded in a separate process (`dj_decoder.py`) straight
into shared memory, so decoding never competes with the sound or the screen.
A deck is playable about **0.05 s** after a drop, even while the other deck and
the machine are playing; the waveform draws itself in as the file decodes, and
the tempo and beat grid follow a couple of seconds later (a 7.5-minute MP3:
~2 s). Tempo, grid and length are remembered per file, so a known track shows
its BPM at once, and a correction (×2, ÷2, "beat 1 is here") sticks for next
time. The crate lists the remembered BPM and length next to each track.

**Accuracy.** Tempo is found by autocorrelation and then refined against the
whole track by folding every onset onto the beat period: on test tracks from
87.5 to 174 BPM it lands on the exact tempo (within 0.01) and the beat grid
within 3 ms. Every track is loudness-matched on load. The waveform, turntable
and clock show what the hall is *hearing*, not what was just sent to the sound
card (about 80 ms earlier), and CUE, hot cues and loops land on that same
moment. The pill at the top left shows the sound card's lag, and turns amber if
the audio ever runs dry.

Each deck shows:

- a turntable whose record turns with the audio. Hold the record to scratch;
  drag the outer ring or use the mouse wheel to nudge the tempo.
- a scrolling three-band waveform (blue lows, gold mids, white highs) with the
  beat grid. Tap it to zoom; with the deck paused, drag it to move through the
  track. Below it, the four beats of the bar, and the whole track: tap to jump.
- a pitch fader (±8 / ±16 / ±50 %, widening by itself when SYNC needs more) and
  **SYNC**, which matches the tempo and locks the beat to the other deck, or to
  the machine.
- CUE, PLAY, four hot cues (tap to set or jump, hold or right-click to clear),
  beat loops of 1–16 beats, and 4-beat jumps.

If the detected tempo is off by an octave, tap the BPM for ×2 / ÷2, or to set
beat 1 at the current position.

**Mixer.** HI / MID / LOW with full kill, a resonant FILTER (left = low-pass,
right = high-pass), a tempo-synced ECHO send, channel faders with meters, a
crossfader, and MASTER. The EQ and filter work in the frequency domain (75 %
overlapped FFT frames), so every knob can move while a track plays without
clicks or phase smear. **REC** records the master output to
`Music\DJ Mixes\Mix <date>.wav`.

**Headphones.** Pick a second sound device under HEADPHONES. The CUE buttons
send a channel there, and CUE/MST blends cued channels with the master, so the
next track can be lined up without the hall hearing it.

**Techno machine.** A 16-step drum machine (kick, clap, hat, open hat, rim,
chord stab) with a 303-style acid bass line, all synthesised: nothing is
sampled. Tap steps on and off, hold (or right-click) for accents and — on the
acid row — slides, drag an acid step up or down (or use the wheel) to change its
note, tap a row name to mute it. It includes:

- a pattern bank: Berlin, Acid, Minimal, Detroit, Hard and Rolling.
- RANDOM, which writes a new pattern that still grooves.
- tempo with TAP, SWING, KEY, and a delay send.
- SYNC, which makes the machine follow the playing deck, so drums and acid
  lock onto a record.

The acid filter is rendered a bar at a time on a helper thread. Knob moves are
heard within about a tenth of a second. The pattern and knobs are remembered.

On the DJ tab, Space, the arrows and 1–3 stop driving the stage screens, so a
key press cannot pause a background mid-mix. BLACKOUT and the F-key sound cues
still work.

**On a touch screen** every control takes its own finger, so a scratch, a fader
move and a knob turn can happen at the same time. Knobs turn by dragging up or
down and reset with a double-tap; a long press does what right-click does with
a mouse; the crate scrolls with a flick while the mouse can still drag tracks
onto decks.

## Touch screens

**Screens & Setup → Touch screen** — *Automatic* (the default) switches to
finger-sized controls when Windows reports a touch screen; *Larger controls* and
*Mouse sizes* force it either way. It enlarges what is hard to hit with a finger
— slider handles, check boxes, scroll bars, list rows, tabs — and makes lists
scroll with a flick, while keeping every tab on one 1080p screen. Nothing that
matters is shown only on hover: the position handles are always visible and
the step-sequencer instructions are written out under the grid. The DJ tab
picks up a change the next time the app starts.

## Keeping it light

Measured on the hall PC (Python 3.12, a 7.5-minute MP3):

| | before | now |
| --- | --- | --- |
| dashboard idle, CPU | 6.6 % | 0 % |
| DJ tab idle, CPU | 31.6 % | under 1 % |
| one deck playing, CPU | 48 % | 23–28 % |
| deck + techno machine, CPU | 63 % | 38 % |
| track playable after a drop | 15.5 s | 0.04 s |
| load while the other deck plays | 11 s | 0.02 s playable, 2 s analysed |
| memory at start-up (peak) | 227 MB | 88 MB |
| memory with the DJ tab open | 410 MB | 242 MB |

What made the difference:

- **Nothing repaints unless it changed.** The sound-cue pads used to re-resolve
  the whole stylesheet four times a second; the DJ widgets now compare what
  they show before redrawing, and the DJ tab's refresh drops from 60 to 8 times
  a second when nothing is moving.
- **Silence costs nothing.** An idle deck, machine or echo skips its DSP
  entirely (0.03 ms per block instead of ~1 ms).
- **Decoding lives in another process**, so it never queues behind the sound
  and the screen for Python's lock.
- **numpy's maths library is held to one thread**; it used to reserve ~180 MB
  on import for threads the desk never uses.
- **The Library fills its thumbnails when first opened**, not at start-up.

## Lighting backgrounds

`tools/make_light_backgrounds.py` renders ambient loops that match the hall's
stage lighting — soft beams swinging from the truss like the moving heads,
lit haze, drifting bokeh and glints, and flowing light ribbons for the ceiling
strip. Six moods (Blue, Red, Purple, Gold, Emerald, Party), each as three clips
cut for their screen:

![Lighting presets live on Main, Sides and Top](docs/lights.png)

| Screen | Size | Play as |
| --- | --- | --- |
| Main Stage | 1920×1080 | FIT |
| Side Screens | 512×1280 (portrait 2:5) | STRETCH |
| Top strip | 2816×128 | CROP |

```
python tools/make_light_backgrounds.py "<out folder>" [blue red ...] [--screens=main,top]
```

Every movement repeats a whole number of times in the 20-second clip, so the loop
has no visible seam. Frames are drawn with `QPainter` and encoded to H.264 through
Qt Multimedia (`QVideoFrameInput` → `QMediaRecorder`), so nothing else needs
installing. A full set of 18 clips takes about four minutes.

## Starting with Windows

**Screens & Setup → Start with Windows** ticks a per-user `HKCU\…\Run` entry
(no administrator rights, this account only) that launches:

```
pythonw.exe main.py --preset "<name>" --delay <seconds>
```

`pythonw.exe` keeps a console window off the stage. The delay matters: LED
processors and video walls often finish enumerating long after the desktop
appears, and applying the routing too early lands the outputs on the wrong
monitors — 20 seconds is a sensible starting point. Untick the box to remove the
entry. The same switches work by hand for testing.

## Layout

Everything lives in `main.py`:

| Class | Role |
| --- | --- |
| `Icons` | line icons drawn with `QPainter` — no image assets |
| `MediaEngine` | `QMediaPlayer` wrapper: looping, safe source swapping, audio |
| `SoundCue`, `SoundDeck` | one sound per key, with fade-out and its own level |
| `CuePad` | one cue as a small player: drop target, transport, seek bar |
| `BaseOutputWindow` | frameless, un-closable, taskbar-less stage window |
| `SceneOutputWindow` | any output, drawn through a `QGraphicsScene` |
| `StandardOutputWindow` / `TopOutputWindow` | Main+Sides / the ceiling strip |
| `VideoThumbnailer` | pulls one real frame out of a clip; a failure flags it as unplayable |
| `MediaProblem`, `describe_media` | why a file was refused, in plain language |
| `FadeOverlay` | crossfades or dips one output between pictures |
| `DropZone`, `Playlist` | drag & drop target and the prepared-media list |
| `MediaLibrary` | folder browser with thumbnails, feeding screens and cues |
| `TextSlides` | the running order of names, and how they are styled |
| `OutputCard`, `TopCard` | one output's live controls |
| `RoutingRow`, `PresetStore` | setup and persistence |
| `Autostart` | the per-user "run at login" registry entry |
| `classify_media`, `scan_event_folder` | where each file in an event folder belongs |
| `EventFolderDialog` | the plan, shown before anything is applied |
| `MiniBar` | the floating strip the dashboard shrinks to |
| `ControlPanel` | the dashboard |

The DJ desk is kept apart, because it is the one part that needs numpy and is
only imported the first time its tab opens:

| Module | Role |
| --- | --- |
| `dj_engine.py` | tempo/beat analysis, decks, spectral EQ, echo, the techno machine, the audio thread, and `DecoderClient`, which drives the decoder process |
| `dj_decoder.py` | the decoder process: QAudioDecoder into shared memory, waveform levels as it goes, tempo at the end |
| `dj.py` | the DJ tab: `Platter`, `WaveDetail`, `BeatBar`, `WaveOverview`, `Knob`, `Fader`, `Meter`, `StepGrid`, deck/mixer/machine/crate views, and `TouchInput`, which gives every control touch, long-press and double-tap |

The running order and the remote are separate modules too; the dashboard
(`ControlPanel`) runs the steps and answers the phone:

| Module | Role |
| --- | --- |
| `show.py` | steps, `fold` (the state a step lands in), `ShowStore`, and the Show tab: NOW / NEXT, the step list and its editor |
| `remote.py` | `RemoteServer` (QTcpServer, PIN, lock-out), `RemoteDialog`, and the phone pages themselves |
| `presentation.py` | `Deck` (PDF via QtPdf, PowerPoint via its COM export, picture folders; cached), `Presenter`, the Slides tab and `LearnDialog` |

`presets.json` and `shows.json` are deliberately git-ignored: they hold absolute
paths to media on one particular machine.
