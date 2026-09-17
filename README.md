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
- **Keyboard control** — `1` `2` `3` pick a screen, `←` `→` step through its
  playlist, `Space` plays/pauses, `B` blacks out, `F5` opens the outputs.
- **Drag & drop** everywhere; drop several files at once to fill a playlist.
- **Scaling modes** — Stretch, Fit (keep aspect), Fill (crop to cover).
- **Repeat** — on by default, per screen.
- **Marquee** — text, typeface, pixel size, colour and scroll speed, drawn over
  live video via a `QGraphicsScene`.
- **Presets** — routing, geometry, playlists, scaling, volumes and marquee
  settings saved as JSON.
- **Start with Windows** — optionally open the app at login and put a chosen
  preset on the screens, after a delay that lets LED processors finish booting.
- **Blackout** — clears every stage screen at once.
- Stage windows are frameless, cannot be closed by the audience, and stay out of
  the taskbar (`Qt.Tool`), so only the dashboard appears there.

## Install

```
pip install PySide6
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

`Escape` on a stage screen closes just that window; press **OPEN OUTPUTS** to
bring it back. Quitting while outputs are live asks first — closing the app
blacks out the hall.

### Keys

| | |
| --- | --- |
| `1` `2` `3` | choose the screen the keyboard drives (it gets an accent border) |
| `←` `→` | previous / next entry in that screen's playlist |
| `Space` | play / pause that screen |
| `B` | blackout every screen |
| `F5` | apply routing / open outputs |

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
| `ImageView` | paints a `QPixmap` with the selected scale mode |
| `BaseOutputWindow` | frameless, un-closable, taskbar-less stage window |
| `StandardOutputWindow` | Main / Sides — `QVideoWidget` + `ImageView` in a stack |
| `TopOutputWindow` | Top — `QGraphicsScene` so text composites over video |
| `VideoThumbnailer` | pulls one real frame out of a clip, queued and cached |
| `DropZone`, `Playlist` | drag & drop target and the prepared-media list |
| `OutputCard`, `TopCard` | one output's live controls |
| `RoutingRow`, `PresetStore` | setup and persistence |
| `Autostart` | the per-user "run at login" registry entry |
| `ControlPanel` | the dashboard |

`presets.json` is deliberately git-ignored: it holds absolute paths to media on
one particular machine.
