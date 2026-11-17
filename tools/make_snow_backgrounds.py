"""
Render a winter night with falling snow, one seamless loop per screen:
    main   1920 x 1080   (played FIT)     - snowy hills, pines, the moon, a soft aurora
    sides   512 x 1280   (played STRETCH) - the same night, tall
    top    2816 x  128   (played CROP)    - a line of pines under the snow on the ceiling strip

Drawn with QPainter and encoded through Qt Multimedia, like make_light_backgrounds.py; every
movement repeats a whole number of times per clip, so the last frame runs into the first.

    python tools/make_snow_backgrounds.py [out_folder] [--screens main,sides,top]
"""
import math
import os
import random
import sys
import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPolygonF, QRadialGradient
from PySide6.QtWidgets import QApplication

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_light_backgrounds as lights  # noqa: E402 - the encoder and the clip length

FRAMES, TAU = lights.FRAMES, math.tau
SCREENS = {
    "main": (1920, 1080, 18_000_000),
    "sides": (512, 1280, 8_000_000),
    "top": (2816, 128, 8_000_000),
}
SKY_TOP, SKY_MID, SKY_LOW = QColor("#02040d"), QColor("#0a1638"), QColor("#1d3d6e")
MOON = QColor("#f4f1e6")
AURORA = [QColor("#2bffc0"), QColor("#3d9bff"), QColor("#9d6bff")]


def qc(colour, alpha):
    c = QColor(colour)
    c.setAlpha(max(0, min(255, int(alpha))))
    return c


class SnowScene:
    def __init__(self, screen, seed):
        self.screen = screen
        self.w, self.h, _ = SCREENS[screen]
        self.rnd = random.Random(seed)
        self.base = self._paint_base()
        self.front = self._paint_front()
        rnd = self.rnd
        span = self.h if screen != "top" else self.h * 4
        # three depths of snow: far (tiny, slow), middle, near (large, soft, quick)
        counts = {"main": (320, 150, 24), "sides": (130, 70, 12), "top": (260, 120, 18)}[screen]
        sizes = ((0.7, 1.6), (1.8, 3.4), (7, 16)) if screen != "top" else ((0.6, 1.3), (1.4, 2.6), (3.5, 7))
        loops = ((1,), (2,), (3, 4)) if screen != "top" else ((2, 3), (4, 5), (6, 7))
        alphas = ((90, 160), (150, 225), (55, 110))
        self.flakes = []
        for depth, n in enumerate(counts):
            for _ in range(n):
                self.flakes.append(dict(
                    depth=depth, u=rnd.random(), v=rnd.random(), r=rnd.uniform(*sizes[depth]),
                    loops=rnd.choice(loops[depth]), sway=rnd.uniform(0.004, 0.02) * (depth + 1),
                    k=rnd.choice([1, 2, 3]), p=rnd.uniform(0, TAU), a=rnd.uniform(*alphas[depth])))
        self.span = span
        self.stars = [dict(u=rnd.random(), v=rnd.random() ** 1.6 * (0.55 if screen != "top" else 1.0),
                           s=rnd.uniform(0.6, 1.8), k=rnd.choice([1, 2, 3, 4]), p=rnd.uniform(0, TAU))
                      for _ in range({"main": 140, "sides": 60, "top": 90}[screen])]
        self.fog = [dict(y=rnd.uniform(0.55, 0.8), r=rnd.uniform(0.25, 0.45), u=rnd.random(),
                         loops=rnd.choice([1, -1]), a=rnd.uniform(18, 34)) for _ in range(5)]

    # -- what does not move: the sky, the moon, the hills, the pines ------------------
    def _paint_base(self):
        w, h = self.w, self.h
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        sky = QLinearGradient(0, 0, 0, h)
        sky.setColorAt(0.0, SKY_TOP)
        sky.setColorAt(0.55, SKY_MID)
        sky.setColorAt(1.0, SKY_LOW)
        p.fillRect(0, 0, w, h, sky)
        if self.screen == "top":
            p.end()
            return img
        mx, my = (w * 0.78, h * 0.2) if self.screen == "main" else (w * 0.66, h * 0.13)
        mr = min(w, h) * (0.06 if self.screen == "main" else 0.1)
        glow = QRadialGradient(QPointF(mx, my), mr * 7)
        glow.setColorAt(0.0, qc("#9fc4ff", 90))
        glow.setColorAt(0.3, qc("#5a86d8", 34))
        glow.setColorAt(1.0, qc("#5a86d8", 0))
        p.fillRect(0, 0, w, h, glow)
        disc = QRadialGradient(QPointF(mx - mr * 0.25, my - mr * 0.25), mr * 1.2)
        disc.setColorAt(0.0, MOON)
        disc.setColorAt(0.85, QColor("#d9dccf"))
        disc.setColorAt(1.0, QColor("#c3c8c0"))
        p.setPen(Qt.NoPen)
        p.setBrush(disc)
        p.drawEllipse(QPointF(mx, my), mr, mr)
        p.setBrush(qc("#b9beb4", 70))           # a few soft craters
        for dx, dy, rr in ((-0.3, 0.2, 0.18), (0.25, -0.15, 0.12), (0.1, 0.38, 0.1)):
            p.drawEllipse(QPointF(mx + dx * mr, my + dy * mr), rr * mr, rr * mr)
        # hills, far to near: paler and bluer far away
        layers = (("#2a4a7a", 0.62, 0.05, 2), ("#3d6296", 0.7, 0.06, 3), ("#cfdcf0", 0.8, 0.05, 2),
                  ("#eef4ff", 0.88, 0.04, 3))
        for n, (colour, level, amp, waves) in enumerate(layers):
            path = QPainterPath(QPointF(0, h))
            phase = self.rnd.uniform(0, TAU)
            waves *= w / 1920 if self.screen != "main" else 1     # the same hills, not squeezed
            for s in range(121):
                x = w * s / 120
                y = h * (level - amp * math.sin(TAU * waves * s / 120 / 2 + phase)
                         - amp * 0.4 * math.sin(TAU * (waves + 3) * s / 120 + phase * 2))
                path.lineTo(x, y)
            path.lineTo(w, h)
            fill = QLinearGradient(0, h * (level - amp), 0, h)
            fill.setColorAt(0.0, QColor(colour))
            fill.setColorAt(1.0, QColor(colour).darker(150 if n < 2 else 125))
            p.setBrush(fill)
            p.drawPath(path)
            if n in (1, 2):
                self._pines(p, level - amp * 0.6, 26 if self.screen == "main" else 8,
                            0.07 if n == 1 else 0.11, "#0f2340" if n == 1 else "#173357", snowy=n == 2)
        p.end()
        return img

    def _pines(self, p, level, count, size, colour, snowy=False, rng=None):
        w, h = self.w, self.h
        rnd = rng or self.rnd
        for _ in range(count):
            x = rnd.uniform(-0.02, 1.02) * w
            tall = h * size * rnd.uniform(0.7, 1.3) if self.screen != "top" else h * rnd.uniform(0.3, 0.6)
            base = h * (level + rnd.uniform(-0.01, 0.03)) if self.screen != "top" else h + 2
            wide = tall * 0.42
            p.setBrush(QColor(colour))
            for tier in range(3):           # three tiers of branches
                top = base - tall * (1 - tier * 0.22)
                bottom = base - tall * (0.42 - tier * 0.2)
                half = wide * (0.55 + tier * 0.25)
                p.drawPolygon(QPolygonF([QPointF(x, top), QPointF(x - half, bottom), QPointF(x + half, bottom)]))
                if snowy:
                    p.setBrush(qc("#e8f0ff", 200))
                    p.drawPolygon(QPolygonF([QPointF(x, top), QPointF(x - half * 0.35, top + (bottom - top) * 0.35),
                                             QPointF(x + half * 0.35, top + (bottom - top) * 0.35)]))
                    p.setBrush(QColor(colour))
            p.drawRect(QRectF(x - wide * 0.06, base - tall * 0.22, wide * 0.12, tall * 0.22))

    def _paint_front(self):
        """The ceiling strip's line of pines along its lower edge, drawn over the snow."""
        if self.screen != "top":
            return None
        img = QImage(self.w, self.h, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        ground = QLinearGradient(0, self.h * 0.82, 0, self.h)
        ground.setColorAt(0.0, qc("#dfe9fb", 0))
        ground.setColorAt(0.5, qc("#dfe9fb", 160))
        ground.setColorAt(1.0, qc("#f4f8ff", 230))
        p.fillRect(0, 0, self.w, self.h, ground)
        self._pines(p, 1.0, 70, 0, "#0e2140", snowy=True, rng=random.Random(7))
        p.end()
        return img

    # -- what moves ------------------------------------------------------------------
    def render(self, i):
        t = i / FRAMES
        ph = TAU * t
        frame = self.base.copy()
        p = QPainter(frame)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        self.paint_stars(p, ph)
        if self.screen != "top":
            self.paint_aurora(p, ph)
            self.paint_fog(p, t)
        self.paint_snow(p, t, ph)
        if self.front is not None:
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            p.drawImage(0, 0, self.front)
            self.paint_sheen(p, t)
        self.paint_vignette(p)
        p.end()
        return frame

    def paint_stars(self, p, ph):
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        for s in self.stars:
            level = 0.45 + 0.55 * (0.5 + 0.5 * math.sin(s["k"] * ph + s["p"]))
            p.setBrush(qc("#dfe8ff", 210 * level))
            p.drawEllipse(QPointF(s["u"] * self.w, s["v"] * self.h), s["s"], s["s"])
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)

    def paint_aurora(self, p, ph):
        """Soft curtains of light swaying over the hills - slow, and faint enough to stay calm."""
        w, h = self.w, self.h
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        for n, colour in enumerate(AURORA):
            path = QPainterPath()
            top = []
            for s in range(61):
                x = w * s / 60
                y = h * (0.12 + 0.04 * n + 0.04 * math.sin(TAU * (s / 60) * (1.5 + n * 0.5) + ph * (1 if n % 2 else -1) + n)
                         + 0.03 * math.sin(TAU * (s / 60) * 3 + 2 * ph))
                top.append(QPointF(x, y))
            path.moveTo(top[0])
            for point in top[1:]:
                path.lineTo(point)
            depth = h * (0.1 + 0.03 * math.sin(ph + n))
            for point in reversed(top):
                path.lineTo(point.x(), point.y() + depth)
            path.closeSubpath()
            level = 0.6 + 0.4 * math.sin(ph * (n + 1) + n * 2)
            grad = QLinearGradient(0, h * 0.12, 0, h * 0.6)
            grad.setColorAt(0.0, qc(colour, 0))
            grad.setColorAt(0.35, qc(colour, 16 * level))
            grad.setColorAt(1.0, qc(colour, 0))
            p.setBrush(grad)
            p.drawPath(path)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)

    def paint_fog(self, p, t):
        w, h = self.w, self.h
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        for f in self.fog:
            r = f["r"] * max(w, h)
            x = ((f["u"] + f["loops"] * t) % 1.0) * (w + 2 * r) - r
            for shift in (-(w + 2 * r), 0, w + 2 * r):
                # a flat cloud: a round soft spot squeezed, so its edge stays soft
                p.save()
                p.translate(x + shift, f["y"] * h)
                p.scale(1.0, 0.35)
                g = QRadialGradient(QPointF(0, 0), r)
                g.setColorAt(0.0, qc("#9fb8e0", f["a"]))
                g.setColorAt(1.0, qc("#9fb8e0", 0))
                p.setBrush(g)
                p.drawEllipse(QPointF(0, 0), r, r)
                p.restore()
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)

    def paint_snow(self, p, t, ph):
        w, h = self.w, self.h
        for f in self.flakes:
            r = f["r"]
            span = h + 4 * r
            y = (f["v"] + f["loops"] * t) % 1.0 * span - 2 * r
            x = (f["u"] + f["sway"] * math.sin(f["k"] * ph + f["p"])) * w
            if f["depth"] == 2:                       # near: large and out of focus
                g = QRadialGradient(QPointF(x, y), r)
                g.setColorAt(0.0, qc("#ffffff", f["a"]))
                g.setColorAt(0.6, qc("#e6eeff", f["a"] * 0.5))
                g.setColorAt(1.0, qc("#e6eeff", 0))
                p.setBrush(g)
            else:
                p.setBrush(qc("#f4f8ff", f["a"]))
            p.drawEllipse(QPointF(x, y), r, r)

    def paint_sheen(self, p, t):
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        x = (t % 1.0) * self.w * 1.4 - self.w * 0.2
        g = QLinearGradient(x - self.w * 0.1, 0, x + self.w * 0.1, 0)
        g.setColorAt(0.0, qc("#bcd4ff", 0))
        g.setColorAt(0.5, qc("#bcd4ff", 40))
        g.setColorAt(1.0, qc("#bcd4ff", 0))
        p.fillRect(0, 0, self.w, self.h, g)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)

    def paint_vignette(self, p):
        w, h = self.w, self.h
        if self.screen == "top":
            g = QLinearGradient(0, 0, 0, h)
            g.setColorAt(0.0, QColor(0, 0, 0, 80))
            g.setColorAt(0.3, QColor(0, 0, 0, 0))
            p.fillRect(0, 0, w, h, g)
            return
        g = QRadialGradient(QPointF(w / 2, h / 2), math.hypot(w, h) / 2)
        g.setColorAt(0.6, QColor(0, 0, 0, 0))
        g.setColorAt(1.0, QColor(0, 0, 0, 130))
        p.fillRect(0, 0, w, h, g)


def main(argv):
    screens = list(SCREENS)
    args = []
    for arg in argv:
        if arg.startswith("--screens="):
            screens = arg.split("=", 1)[1].split(",")

        else:
            args.append(arg)
    out = args[0] if args else os.path.join(os.path.expanduser("~"), "Desktop", "Light Backgrounds")
    os.makedirs(out, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    if "--stills" in argv:                 # a few frames as pictures, to look at before encoding
        for screen in screens:
            scene = SnowScene(screen, seed=11)
            for i in (0, FRAMES // 2):
                scene.render(i).save(os.path.join(out, f"Snow - {screen} - {i}.png"))
        return 0
    failures = 0
    for screen in screens:
        path = os.path.join(out, f"Snow - {screen}.mp4")
        if os.path.exists(path):
            os.remove(path)
        scene = SnowScene(screen, seed=11)

        started = time.time()
        encoder = lights.Encoder(app, scene, path, SCREENS[screen][2])
        ok = encoder.run()
        size = os.path.getsize(path) / 1e6 if os.path.exists(path) else 0
        print(f"{'ok ' if ok else 'FAIL'} {screen:6s} {encoder.i:4d} frames {time.time() - started:5.1f}s "
              f"{size:5.1f} MB {encoder.error}", flush=True)
        failures += 0 if ok else 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
