"""
Render seamless-loop ambient backgrounds that match the hall's stage lighting.

One clip per screen for each lighting mood:
    main   1920 x 1080   (played FIT)
    sides   512 x 1280   (played STRETCH - portrait 2:5, like the other side clips)
    top    2816 x  128   (played CROP onto the 2818 x 132 ceiling strip)

Everything is drawn with QPainter and encoded through Qt Multimedia, so nothing
extra has to be installed. Every movement repeats a whole number of times per
clip, so the last frame runs straight back into the first.

    python tools/make_light_backgrounds.py [out_folder] [mood ...] [--screens main,sides,top]
"""
import math
import os
import random
import sys
import time
import zlib

from PySide6.QtCore import QPointF, QRectF, QTimer, QUrl, Qt
from PySide6.QtGui import (QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPolygonF, QRadialGradient)
from PySide6.QtMultimedia import (QMediaCaptureSession, QMediaFormat, QMediaRecorder,
                                  QVideoFrame, QVideoFrameInput)
from PySide6.QtWidgets import QApplication

FPS = 30
SECONDS = 20
FRAMES = FPS * SECONDS
TAU = math.tau

SCREENS = {
    "main": (1920, 1080, 3, 18_000_000),
    "sides": (512, 1280, 2, 8_000_000),
    "top": (2816, 128, 2, 8_000_000),
}

# base: the dark room colour; beams: fixture colours (cycled across fixtures);
# haze: the air the beams light up; accent: small glints.
MOODS = {
    "blue": dict(title="Blue", base="#03081a", haze="#123a9c",
                 beams=["#2d6bff", "#4fb0ff", "#2d6bff", "#7a8cff"], accent="#ffd88a"),
    "red": dict(title="Red", base="#120208", haze="#7a0a1c",
                beams=["#ff1e3c", "#ff4a2a", "#ff1e3c", "#ff3f7a"], accent="#ffc27a"),
    "purple": dict(title="Purple", base="#0b0418", haze="#4a1690",
                   beams=["#9b3dff", "#ff3fd0", "#7a46ff", "#d23dff"], accent="#ffd6f6"),
    "gold": dict(title="Gold", base="#120903", haze="#7a4210",
                 beams=["#ffb030", "#ffd27a", "#ff9a2a", "#ffe2a0"], accent="#fff4d6"),
    "green": dict(title="Emerald", base="#02110f", haze="#0b5a4a",
                  beams=["#18e0a0", "#2bc8ff", "#3dff8a", "#18e0c8"], accent="#dffff0"),
    "party": dict(title="Party", base="#07041a", haze="#3a1a80",
                  beams=["#ff2a55", "#2d6bff", "#3dff8a", "#ffb030", "#b43dff", "#2bd8ff"],
                  accent="#ffffff", cycle=True),
}


def qcolor(value, alpha=255):
    colour = QColor(value)
    colour.setAlpha(max(0, min(255, int(alpha))))
    return colour


def hue_shift(value, degrees):
    colour = QColor(value)
    h, s, v, _ = colour.getHsv()
    return QColor.fromHsv(int((max(h, 0) + degrees) % 360), s, v)


class Scene:
    """Draws one frame of one mood for one screen shape."""

    def __init__(self, screen, mood, seed):
        self.screen = screen
        self.mood = MOODS[mood]
        self.w, self.h, self.div, _ = SCREENS[screen]
        self.lw, self.lh = self.w // self.div, self.h // self.div
        rnd = random.Random(seed)
        self.rnd = rnd
        self.cycle = self.mood.get("cycle", False)

        # Light fixtures hanging along the top edge (main + sides only).
        count = {"main": 6, "sides": 2, "top": 0}[screen]
        self.fixtures = []
        for k in range(count):
            fx = (k + 0.5) / count if count else 0.5
            self.fixtures.append(dict(
                x=fx + rnd.uniform(-0.03, 0.03),
                aim=rnd.uniform(-8, 8) + (fx - 0.5) * -18,
                swing=rnd.uniform(14, 24) if screen == "main" else rnd.uniform(8, 13),
                speed=rnd.choice([1, 1, 2]),
                phase=rnd.uniform(0, TAU),
                pulse=rnd.choice([2, 3, 4]),
                pulse_phase=rnd.uniform(0, TAU),
                spread=rnd.uniform(7.0, 9.5) if screen == "main" else rnd.uniform(8, 11),
                colour=self.mood["beams"][k % len(self.mood["beams"])],
                hue0=k * 360 / max(count, 1),
            ))

        # Slow clouds of lit haze.
        self.hazes = [dict(ax=rnd.uniform(0.15, 0.35), ay=rnd.uniform(0.08, 0.2),
                           cx=rnd.uniform(0.2, 0.8), cy=rnd.uniform(0.25, 0.7),
                           fx=rnd.choice([1, 2]), fy=rnd.choice([1, 2]),
                           p=rnd.uniform(0, TAU), r=rnd.uniform(0.35, 0.6))
                      for _ in range(4)]

        # Out-of-focus particles drifting upward (or sideways on the top strip).
        n_bokeh = {"main": 34, "sides": 18, "top": 40}[screen]
        self.bokeh = [dict(u=rnd.random(), v=rnd.random(),
                           r=rnd.uniform(0.012, 0.05) * (self.h if screen == "main" else self.w)
                           if screen != "top" else rnd.uniform(8, 26),
                           loops=rnd.choice([1, 1, 2]), wob=rnd.choice([1, 2, 3]),
                           amp=rnd.uniform(0.005, 0.025), p=rnd.uniform(0, TAU),
                           a=rnd.uniform(28, 80), accent=rnd.random() < 0.25,
                           colour_index=rnd.randrange(len(self.mood["beams"])))
                      for _ in range(n_bokeh)]

        n_glint = {"main": 40, "sides": 22, "top": 60}[screen]
        self.glints = [dict(u=rnd.random(), v=rnd.random(), k=rnd.choice([1, 2, 3, 4, 5]),
                            p=rnd.uniform(0, TAU), size=rnd.uniform(1.5, 3.5))
                       for _ in range(n_glint)]

        # Ribbons of light running along the ceiling strip.
        self.waves = [dict(m=rnd.choice([2, 3, 4, 5]), k=rnd.choice([1, 2]) * rnd.choice([-1, 1]),
                           y=rnd.uniform(0.35, 0.65), amp=rnd.uniform(0.12, 0.3),
                           p=rnd.uniform(0, TAU), width=rnd.uniform(1.5, 3.0),
                           colour_index=k)
                      for k in range(4)] if screen == "top" else []

        self.base = QColor(self.mood["base"])
        self.haze = QColor(self.mood["haze"])
        self.accent = QColor(self.mood["accent"])

    # -- colour helpers -------------------------------------------------------
    def beam_colour(self, index, t):
        colour = self.mood["beams"][index % len(self.mood["beams"])]
        if self.cycle:
            return hue_shift(colour, 360 * t)
        return QColor(colour)

    def haze_colour(self, t):
        return hue_shift(self.haze, 360 * t) if self.cycle else QColor(self.haze)

    # -- frame ----------------------------------------------------------------
    def render(self, i):
        t = i / FRAMES                 # 0..1 over the loop
        ph = TAU * t
        low = QImage(self.lw, self.lh, QImage.Format_ARGB32_Premultiplied)
        p = QPainter(low)
        p.setRenderHint(QPainter.Antialiasing)
        self.paint_room(p, t, ph)
        if self.screen == "top":
            self.paint_ribbons(p, t, ph)
        else:
            self.paint_beams(p, t, ph)
        p.end()

        frame = low.scaled(self.w, self.h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation) \
            .convertToFormat(QImage.Format_ARGB32_Premultiplied)
        p = QPainter(frame)
        p.setRenderHint(QPainter.Antialiasing)
        self.paint_bokeh(p, t, ph)
        self.paint_glints(p, ph)
        self.paint_vignette(p)
        p.end()
        return frame

    def paint_room(self, p, t, ph):
        w, h = self.lw, self.lh
        haze = self.haze_colour(t)
        grad = QLinearGradient(0, 0, 0, h) if self.screen != "top" else QLinearGradient(0, 0, w, 0)
        grad.setColorAt(0.0, self.base.lighter(135))
        grad.setColorAt(0.55, self.base)
        grad.setColorAt(1.0, self.base.darker(130))
        p.fillRect(0, 0, w, h, grad)

        p.setCompositionMode(QPainter.CompositionMode_Plus)
        span = max(w, h)
        for cloud in self.hazes:
            x = (cloud["cx"] + cloud["ax"] * math.sin(cloud["fx"] * ph + cloud["p"])) * w
            y = (cloud["cy"] + cloud["ay"] * math.cos(cloud["fy"] * ph + cloud["p"])) * h
            r = cloud["r"] * span
            rg = QRadialGradient(QPointF(x, y), r)
            rg.setColorAt(0.0, qcolor(haze, 56))
            rg.setColorAt(0.5, qcolor(haze, 20))
            rg.setColorAt(1.0, qcolor(haze, 0))
            p.fillRect(0, 0, w, h, rg)

        if self.screen != "top":
            # warm pool of light on the stage floor
            pool = self.beam_colour(0, t)
            rg = QRadialGradient(QPointF(w / 2, h * 1.08), w * 0.7)
            rg.setColorAt(0.0, qcolor(pool, 55))
            rg.setColorAt(1.0, qcolor(pool, 0))
            p.fillRect(0, 0, w, h, rg)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)

    def paint_beams(self, p, t, ph):
        w, h = self.lw, self.lh
        length = math.hypot(w, h) * 1.15
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        p.setPen(Qt.NoPen)
        for k, fx in enumerate(self.fixtures):
            angle = fx["aim"] + fx["swing"] * math.sin(fx["speed"] * ph + fx["phase"])
            level = 0.62 + 0.38 * (0.5 + 0.5 * math.sin(fx["pulse"] * ph + fx["pulse_phase"]))
            colour = self.beam_colour(k, t)
            ox, oy = fx["x"] * w, -h * 0.03
            rad = math.radians(90 + angle)
            dx, dy = math.cos(rad), math.sin(rad)
            # nested cones fake the soft edge of a real beam in haze
            for scale, alpha in ((1.0, 12), (0.84, 14), (0.68, 16), (0.53, 18),
                                 (0.39, 20), (0.26, 22), (0.14, 24)):
                half = math.radians(fx["spread"] * scale)
                left = QPointF(ox + length * math.cos(rad - half), oy + length * math.sin(rad - half))
                right = QPointF(ox + length * math.cos(rad + half), oy + length * math.sin(rad + half))
                lg = QLinearGradient(QPointF(ox, oy), QPointF(ox + dx * length, oy + dy * length))
                lg.setColorAt(0.0, qcolor(colour, alpha * 2.2 * level))
                lg.setColorAt(0.25, qcolor(colour, alpha * 0.95 * level))
                lg.setColorAt(0.7, qcolor(colour, alpha * 0.25 * level))
                lg.setColorAt(1.0, qcolor(colour, 0))
                p.setBrush(lg)
                p.drawPolygon(QPolygonF([QPointF(ox, oy), left, right]))
            # the lens itself
            rg = QRadialGradient(QPointF(ox, oy + h * 0.01), w * 0.05)
            rg.setColorAt(0.0, qcolor(QColor("white"), 200 * level))
            rg.setColorAt(0.3, qcolor(colour, 150 * level))
            rg.setColorAt(1.0, qcolor(colour, 0))
            p.setBrush(rg)
            p.drawEllipse(QPointF(ox, oy + h * 0.01), w * 0.05, w * 0.05)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)

    def paint_ribbons(self, p, t, ph):
        w, h = self.lw, self.lh
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        p.setBrush(Qt.NoBrush)
        steps = 220
        for wave in self.waves:
            colour = self.beam_colour(wave["colour_index"], t)
            path = QPainterPath()
            for s in range(steps + 1):
                x = w * s / steps
                y = h * (wave["y"] + wave["amp"] * math.sin(TAU * wave["m"] * s / steps
                                                           + wave["k"] * ph + wave["p"]))
                if s == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            for width, alpha in ((wave["width"] * 7, 26), (wave["width"] * 3, 60),
                                 (wave["width"], 170)):
                pen = QPen(qcolor(colour, alpha), width)
                pen.setCapStyle(Qt.RoundCap)
                p.setPen(pen)
                p.drawPath(path)
        # a sheen that sweeps the full length twice per loop
        for n in range(2):
            x = ((t * 2 + n * 0.5) % 1.0) * (w * 1.4) - w * 0.2
            lg = QLinearGradient(x - w * 0.12, 0, x + w * 0.12, 0)
            lg.setColorAt(0.0, qcolor(self.accent, 0))
            lg.setColorAt(0.5, qcolor(self.accent, 60))
            lg.setColorAt(1.0, qcolor(self.accent, 0))
            p.fillRect(0, 0, w, h, lg)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)

    def paint_bokeh(self, p, t, ph):
        w, h = self.w, self.h
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        p.setPen(Qt.NoPen)
        for b in self.bokeh:
            r = b["r"]
            colour = self.accent if b["accent"] else self.beam_colour(b["colour_index"], t)
            if self.screen == "top":
                span = w + 4 * r
                x = (b["u"] * span + b["loops"] * span * t) % span - 2 * r
                y = h * (0.5 + 0.35 * math.sin(b["wob"] * ph + b["p"]))
            else:
                span = h + 4 * r
                y = (b["v"] * span - b["loops"] * span * t) % span - 2 * r
                x = w * (b["u"] + b["amp"] * math.sin(b["wob"] * ph + b["p"]))
            fade = 0.55 + 0.45 * math.sin(b["wob"] * ph + b["p"] * 1.7)
            rg = QRadialGradient(QPointF(x, y), r)
            rg.setColorAt(0.0, qcolor(colour, b["a"] * fade))
            rg.setColorAt(0.75, qcolor(colour, b["a"] * 0.6 * fade))
            rg.setColorAt(1.0, qcolor(colour, 0))
            p.setBrush(rg)
            p.drawEllipse(QPointF(x, y), r, r)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)

    def paint_glints(self, p, ph):
        w, h = self.w, self.h
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        p.setPen(Qt.NoPen)
        for g in self.glints:
            level = max(0.0, math.sin(g["k"] * ph + g["p"])) ** 6
            if level < 0.02:
                continue
            x, y, s = g["u"] * w, g["v"] * h, g["size"] * (1 + level)
            rg = QRadialGradient(QPointF(x, y), s * 3)
            rg.setColorAt(0.0, qcolor(self.accent, 230 * level))
            rg.setColorAt(1.0, qcolor(self.accent, 0))
            p.setBrush(rg)
            p.drawEllipse(QPointF(x, y), s * 3, s * 3)
            p.setBrush(qcolor(self.accent, 120 * level))
            p.drawRect(QRectF(x - s * 5, y - 0.6, s * 10, 1.2))
            p.drawRect(QRectF(x - 0.6, y - s * 5, 1.2, s * 10))
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)

    def paint_vignette(self, p):
        w, h = self.w, self.h
        if self.screen == "top":
            lg = QLinearGradient(0, 0, 0, h)
            lg.setColorAt(0.0, QColor(0, 0, 0, 90))
            lg.setColorAt(0.25, QColor(0, 0, 0, 0))
            lg.setColorAt(0.75, QColor(0, 0, 0, 0))
            lg.setColorAt(1.0, QColor(0, 0, 0, 90))
            p.fillRect(0, 0, w, h, lg)
            return
        rg = QRadialGradient(QPointF(w / 2, h / 2), math.hypot(w, h) / 2)
        rg.setColorAt(0.55, QColor(0, 0, 0, 0))
        rg.setColorAt(1.0, QColor(0, 0, 0, 150))
        p.fillRect(0, 0, w, h, rg)


class Encoder:
    """Feed frames to QMediaRecorder as fast as it will take them."""

    def __init__(self, app, scene, path, bitrate):
        self.app, self.scene, self.path = app, scene, path
        self.i = 0
        self.ok = False
        self.error = ""
        self.frame_input = QVideoFrameInput()
        self.session = QMediaCaptureSession()
        self.recorder = QMediaRecorder()
        self.session.setVideoFrameInput(self.frame_input)
        self.session.setRecorder(self.recorder)
        media = QMediaFormat(QMediaFormat.FileFormat.MPEG4)
        media.setVideoCodec(QMediaFormat.VideoCodec.H264)
        self.recorder.setMediaFormat(media)
        self.recorder.setVideoResolution(scene.w, scene.h)
        self.recorder.setVideoFrameRate(FPS)
        self.recorder.setEncodingMode(QMediaRecorder.EncodingMode.AverageBitRateEncoding)
        self.recorder.setVideoBitRate(bitrate)
        self.recorder.setOutputLocation(QUrl.fromLocalFile(path))
        self.frame_input.readyToSendVideoFrame.connect(self.pump)
        self.recorder.recorderStateChanged.connect(self.on_state)
        self.recorder.errorOccurred.connect(self.on_error)

    def run(self):
        self.recorder.record()
        self.app.exec()
        return self.ok

    def pump(self):
        while self.i < FRAMES:
            frame = QVideoFrame(self.scene.render(self.i))
            frame.setStartTime(self.i * 1_000_000 // FPS)
            frame.setEndTime((self.i + 1) * 1_000_000 // FPS)
            if not self.frame_input.sendVideoFrame(frame):
                return
            self.i += 1
        if self.recorder.recorderState() == QMediaRecorder.RecorderState.RecordingState:
            self.recorder.stop()

    def on_state(self, state):
        if state == QMediaRecorder.RecorderState.RecordingState:
            QTimer.singleShot(0, self.pump)
        elif state == QMediaRecorder.RecorderState.StoppedState:
            self.ok = self.i >= FRAMES and os.path.exists(self.path) and not self.error
            self.app.quit()

    def on_error(self, _error, text):
        self.error = text
        self.app.quit()


def main(argv):
    screens = list(SCREENS)
    args = []
    for arg in argv:
        if arg.startswith("--screens="):
            screens = arg.split("=", 1)[1].split(",")
        else:
            args.append(arg)
    out = args[0] if args else os.path.join(os.path.expanduser("~"), "Desktop", "Light Backgrounds")
    moods = args[1:] or list(MOODS)
    os.makedirs(out, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    failures = 0
    for mood in moods:
        for screen in screens:
            path = os.path.join(out, f"{MOODS[mood]['title']} - {screen}.mp4")
            if os.path.exists(path):
                os.remove(path)
            scene = Scene(screen, mood, seed=zlib.crc32(f"{mood}/{screen}".encode()))
            started = time.time()
            encoder = Encoder(app, scene, path, SCREENS[screen][3])
            ok = encoder.run()
            size = os.path.getsize(path) / 1e6 if os.path.exists(path) else 0
            print(f"{'ok ' if ok else 'FAIL'} {mood:7s} {screen:6s} {encoder.i:4d} frames "
                  f"{time.time() - started:5.1f}s {size:5.1f} MB {encoder.error}", flush=True)
            failures += 0 if ok else 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
