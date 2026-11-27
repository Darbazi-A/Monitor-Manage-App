"""
Render a Miami sunset, one seamless loop per screen:
    main   1920 x 1080   (played FIT)     - the sun going down into the sea, an art-deco skyline
                                            in neon, palms swaying, clouds and gulls drifting
    sides   512 x 1280   (played STRETCH) - a tall palm against the sunset, a neon sun, the sea
    top    2816 x  128   (played CROP)    - the sunset with a row of palms and a neon line running

Pink, orange and violet with teal neon. Drawn with QPainter and encoded through Qt Multimedia,
like the other backgrounds; every movement repeats a whole number of times per clip.

    python tools/make_miami_backgrounds.py [out_folder] [--screens main,sides,top] [--stills]
"""
import math
import os
import random
import sys
import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QApplication

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_light_backgrounds as lights  # noqa: E402 - the encoder and the clip length
from make_newyear_backgrounds import blank, bloom, qc  # noqa: E402

FRAMES, TAU = lights.FRAMES, math.tau
SCREENS = {"main": (1920, 1080, 24_000_000), "sides": (512, 1280, 10_000_000), "top": (2816, 128, 10_000_000)}
PINK, TEAL, ORANGE = QColor("#ff3fa4"), QColor("#2ef2e0"), QColor("#ff9a3c")


class Miami:
    def __init__(self, screen, seed=305):
        self.screen = screen
        self.w, self.h, _ = SCREENS[screen]
        rnd = self.rnd = random.Random(seed)
        w, h = self.w, self.h
        self.horizon = h * {"main": 0.62, "sides": 0.74, "top": 0.78}[screen]
        self.sun = QPointF(w * (0.5 if screen != "main" else 0.56), self.horizon - h * {"main": 0.08, "sides": 0.12, "top": 0.25}[screen])
        self.sun_r = {"main": 170, "sides": 120, "top": 60}[screen]
        self.sky = self._paint_sky()
        self.clouds = [dict(y=rnd.uniform(0.12, 0.45) * self.horizon, len=rnd.uniform(0.25, 0.55) * w,
                            th=rnd.uniform(10, 26) if screen != "top" else rnd.uniform(4, 9), u=rnd.random(),
                            loops=rnd.choice([1, -1]), a=rnd.uniform(70, 140)) for _ in range({"main": 9, "sides": 7, "top": 6}[screen])]
        self.buildings = self._skyline() if screen == "main" else []
        self.palms = {"main": [(-0.02, 1.0, 0.62, 1), (0.1, 1.0, 0.5, 1), (0.93, 1.0, 0.66, -1), (1.04, 1.0, 0.52, -1)],
                      "sides": [(0.1, 1.0, 0.42, 1), (0.95, 1.0, 0.3, -1)],
                      "top": [(x / 14 + 0.02, 1.0, 0.95, 1 if k % 2 else -1) for k, x in enumerate(range(14))]}[screen]
        self.palm_phase = [rnd.uniform(0, TAU) for _ in self.palms]
        self.gulls = [dict(s=rnd.random(), y=rnd.uniform(0.15, 0.35), size=rnd.uniform(8, 14)) for _ in range(4)] \
            if screen != "top" else []
        self.glints = [dict(x=rnd.gauss(0, 1), y=rnd.random(), k=rnd.choice([3, 4, 5, 6]), p=rnd.uniform(0, TAU),
                            wd=rnd.uniform(10, 40)) for _ in range(160 if screen != "top" else 40)]

    # -- what does not move -------------------------------------------------------------
    def _paint_sky(self):
        w, h = self.w, self.h
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        sky = QLinearGradient(0, 0, 0, self.horizon)
        sky.setColorAt(0.0, QColor("#1a0b3d"))
        sky.setColorAt(0.35, QColor("#5a1a7a"))
        sky.setColorAt(0.62, QColor("#d63a8a"))
        sky.setColorAt(0.85, QColor("#ff7a5a"))
        sky.setColorAt(1.0, QColor("#ffc27a"))
        p.fillRect(QRectF(0, 0, w, self.horizon + 1), sky)
        haze = QRadialGradient(self.sun, w * 0.6)
        haze.setColorAt(0.0, qc("#ffd98a", 140))
        haze.setColorAt(0.4, qc("#ff8a6a", 50))
        haze.setColorAt(1.0, qc("#ff8a6a", 0))
        p.fillRect(QRectF(0, 0, w, self.horizon), haze)
        # the sun, banded low down as the haze cuts it
        r = self.sun_r
        disc = QLinearGradient(0, self.sun.y() - r, 0, self.sun.y() + r)
        disc.setColorAt(0.0, QColor("#fff2b0"))
        disc.setColorAt(0.6, QColor("#ffb35a"))
        disc.setColorAt(1.0, QColor("#ff5a7a"))
        clip = QPainterPath()
        clip.addEllipse(self.sun, r, r)
        bands = QPainterPath()
        bands.addRect(QRectF(self.sun.x() - r, self.sun.y() - r, 2 * r, r * 1.15))
        y, gap = self.sun.y() + r * 0.15, r * 0.05
        while y < self.sun.y() + r:
            bands.addRect(QRectF(self.sun.x() - r, y, 2 * r, gap * 1.6))
            y += gap * 1.6 + gap
            gap *= 1.25
        p.setPen(Qt.NoPen)
        p.setBrush(disc)
        p.drawPath(clip.intersected(bands))
        # the sea
        sea = QLinearGradient(0, self.horizon, 0, h)
        sea.setColorAt(0.0, QColor("#c2508e"))
        sea.setColorAt(0.25, QColor("#6a2a7a"))
        sea.setColorAt(1.0, QColor("#140a2e"))
        p.fillRect(QRectF(0, self.horizon, w, h - self.horizon), sea)
        p.end()
        return img

    def _skyline(self):
        w, h, rnd = self.w, self.h, self.rnd
        out, x = [], w * 0.18
        while x < w * 0.86:
            bw = rnd.uniform(40, 110)
            if abs(x + bw / 2 - self.sun.x()) < self.sun_r * 0.9:     # a gap where the sun sets
                x += bw * 0.6
                continue
            bh = rnd.uniform(0.08, 0.3) * h * (1.25 if abs(x - w * 0.4) < w * 0.12 else 1)
            windows = [(rnd.random(), rnd.random() < 0.45, rnd.choice([1, 2, 3]), rnd.uniform(0, TAU))
                       for _ in range(int(bw // 12) * int(bh // 16))]
            out.append(dict(x=x, w=bw, h=bh, steps=rnd.choice([0, 1, 2]), neon=rnd.choice([None, PINK, TEAL, None]),
                            windows=windows, flick=rnd.uniform(0, TAU)))
            x += bw + rnd.uniform(2, 10)
        return out

    # -- one frame -----------------------------------------------------------------------
    def render(self, i):
        t = i / FRAMES
        ph = TAU * t
        w, h = self.w, self.h
        frame = self.sky.copy()
        p = QPainter(frame)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        light = blank(w, h)
        lp = QPainter(light)
        lp.setRenderHint(QPainter.Antialiasing)
        lp.setPen(Qt.NoPen)
        self.paint_clouds(p, t)
        self.paint_sea(p, lp, ph)
        if self.buildings:
            self.paint_skyline(p, lp, ph)

        for n, (x, base, size, lean) in enumerate(self.palms):
            self.paint_palm(p, x * w, h * base + 4, size * h * (1 if self.screen != "top" else 1.0), lean,
                            ph, self.palm_phase[n])
        self.paint_gulls(p, t, ph)
        if self.screen == "top":
            self.paint_neon_line(lp, t)
        lp.end()
        bloom(p, light, w, h, 1.2)
        grade = QLinearGradient(0, 0, 0, h)                  # a little warmth over everything
        grade.setColorAt(0.0, qc("#2a0a4a", 40))
        grade.setColorAt(1.0, qc("#ff6a8a", 18))
        p.fillRect(0, 0, w, h, grade)
        vignette = QRadialGradient(QPointF(w / 2, h / 2), math.hypot(w, h) / 2)
        vignette.setColorAt(0.65, QColor(0, 0, 0, 0))
        vignette.setColorAt(1.0, QColor(0, 0, 0, 120 if self.screen != "top" else 50))
        p.fillRect(0, 0, w, h, vignette)
        p.end()
        return frame

    def paint_clouds(self, p, t):
        """Long thin clouds lit pink from below, drifting across."""
        w = self.w
        for c in self.clouds:
            span = w + c["len"]
            x = ((c["u"] + c["loops"] * t) % 1.0) * span - c["len"]
            for shift in (0, -span) if c["loops"] > 0 else (0, span):
                rect = QRectF(x + shift, c["y"], c["len"], c["th"])
                g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
                g.setColorAt(0.0, qc("#7a3a8a", c["a"] * 0.6))
                g.setColorAt(1.0, qc("#ffb08a", c["a"]))
                p.setBrush(g)
                p.drawRoundedRect(rect, c["th"] / 2, c["th"] / 2)

    def paint_sea(self, p, lp, ph):
        """The sun's road on the water, broken into shimmering dashes, and long swells."""
        w, h, top = self.w, self.h, self.horizon
        depth = h - top
        for g in self.glints:
            y = top + 3 + g["y"] ** 1.5 * depth
            spread = (0.1 + 0.9 * (y - top) / depth) * self.sun_r * 1.4
            x = self.sun.x() + g["x"] * spread * 0.5
            level = max(0.0, math.sin(g["k"] * ph + g["p"]))
            width = g["wd"] * (0.4 + (y - top) / depth) * (0.5 + 0.5 * level)
            lp.setBrush(qc("#ffd9a0", 200 * level))
            lp.drawRect(QRectF(x - width / 2, y, width, 1.6 + 2 * (y - top) / depth))
        p.setBrush(Qt.NoBrush)
        for k in range(14 if self.screen != "top" else 3):
            y = top + depth * ((k + 1) / 15) ** 1.6
            pen = QPen(qc("#ff9ad0", 40), 1.2)
            p.setPen(pen)
            path = QPainterPath(QPointF(0, y))
            for s in range(41):
                x = w * s / 40
                path.lineTo(x, y + 2 * math.sin(TAU * s / 40 * (3 + k % 3) + ph * (1 + k % 2) + k))
            p.drawPath(path)
        p.setPen(Qt.NoPen)

    def paint_skyline(self, p, lp, ph):
        base = self.horizon + 2
        for b in self.buildings:
            x, bw, bh = b["x"], b["w"], b["h"]
            body = QPainterPath()
            body.addRect(QRectF(x, base - bh, bw, bh))
            for s in range(b["steps"]):                     # art-deco steps at the top
                inset = bw * 0.18 * (s + 1)
                body.addRect(QRectF(x + inset, base - bh - 14 * (s + 1), bw - 2 * inset, 14))
            g = QLinearGradient(0, base - bh, 0, base)
            g.setColorAt(0.0, QColor("#3a1450"))
            g.setColorAt(1.0, QColor("#1a0a2e"))
            p.setBrush(g)
            p.drawPath(body)
            cols, rows = int(bw // 12), int(bh // 16)
            for n, (u, lit, k, phase) in enumerate(b["windows"][:cols * rows]):
                if not lit:
                    continue
                cx, cy = n % cols, n // cols
                level = 0.6 + 0.4 * math.sin(k * ph + phase)
                lp.setBrush(qc("#ffd27a" if u < 0.7 else "#7af2ff", 120 * level))
                lp.drawRect(QRectF(x + 4 + cx * 12, base - bh + 6 + cy * 16, 5, 7))
            if b["neon"] is not None:                        # a neon line round the top, buzzing a little
                flick = 0.75 + 0.25 * math.sin(9 * ph + b["flick"]) if math.sin(2 * ph + b["flick"]) > -0.95 else 0.3
                lp.setPen(QPen(qc(b["neon"], 255 * flick), 2.4))     # the roof line and the corners
                lp.drawLine(QPointF(x + 1, base - bh + 1), QPointF(x + bw - 1, base - bh + 1))
                lp.drawLine(QPointF(x + 1, base - bh + 1), QPointF(x + 1, base - bh * 0.35))
                lp.drawLine(QPointF(x + bw - 1, base - bh + 1), QPointF(x + bw - 1, base - bh * 0.35))
                lp.setPen(Qt.NoPen)
        # their reflection, a soft dark band on the water
        g = QLinearGradient(0, base, 0, base + 60)
        g.setColorAt(0.0, qc("#1a0a2e", 160))
        g.setColorAt(1.0, qc("#1a0a2e", 0))
        p.fillRect(QRectF(self.buildings[0]["x"], base, self.buildings[-1]["x"] + self.buildings[-1]["w"] - self.buildings[0]["x"], 60), g)

    def paint_palm(self, p, x, base, height, lean, ph, phase):
        """A palm in silhouette: a curved trunk and fronds that sway in the breeze."""
        sway = math.sin(ph + phase) * 0.04 + math.sin(3 * ph + phase) * 0.012
        top_x = x + lean * height * (0.22 + sway)
        top_y = base - height
        trunk = QPainterPath(QPointF(x - height * 0.03, base))
        trunk.quadTo(QPointF(x + lean * height * 0.02, base - height * 0.55), QPointF(top_x - height * 0.012, top_y))
        trunk.lineTo(top_x + height * 0.012, top_y)
        trunk.quadTo(QPointF(x + lean * height * 0.06, base - height * 0.55), QPointF(x + height * 0.03, base))
        trunk.closeSubpath()
        colour = QColor("#12061e")
        p.setBrush(colour)
        p.drawPath(trunk)
        for k in range(9):                                   # fronds all round the crown
            a = math.radians(-90 + (k - 4) * 34 + 6 * math.sin(2 * ph + phase + k)) + sway * 2
            length = height * (0.42 if abs(k - 4) < 3 else 0.36)
            droop = height * 0.18 * (abs(k - 4) / 4 + 0.4)
            end = QPointF(top_x + math.cos(a) * length, top_y + math.sin(a) * length + droop)
            mid = QPointF(top_x + math.cos(a) * length * 0.55, top_y + math.sin(a) * length * 0.55 - droop * 0.1)
            # a curved rib, and fine leaflets hanging from both sides of it
            pts = []
            for s in range(23):
                u = s / 22
                pts.append(QPointF((1 - u) ** 2 * top_x + 2 * (1 - u) * u * mid.x() + u * u * end.x(),
                                   (1 - u) ** 2 * top_y + 2 * (1 - u) * u * mid.y() + u * u * end.y()))
            rib = QPen(colour, max(1.5, height * 0.008))
            rib.setCapStyle(Qt.RoundCap)
            p.setPen(rib)
            for a_, b_ in zip(pts, pts[1:]):
                p.drawLine(a_, b_)
            for s in range(2, 23):
                u = s / 22
                ax_, ay_ = pts[s].x(), pts[s].y()
                dx, dy = pts[s].x() - pts[s - 1].x(), pts[s].y() - pts[s - 1].y()
                d = math.hypot(dx, dy) or 1
                nx, ny = -dy / d, dx / d
                leaflet = height * 0.11 * math.sin(math.pi * min(1.0, u * 1.15)) + height * 0.01
                flutter = 0.15 * math.sin(5 * ph + phase + s)
                for side in (-1, 1):
                    ex = ax_ + (nx * side * 0.55 + dx / d * 0.5) * leaflet
                    ey = ay_ + (ny * side * 0.55 + dy / d * 0.5) * leaflet + leaflet * (0.55 + flutter)
                    leaf_pen = QPen(colour, max(1.2, height * 0.006 * (1.2 - u)))
                    leaf_pen.setCapStyle(Qt.RoundCap)
                    p.setPen(leaf_pen)
                    p.drawLine(QPointF(ax_, ay_), QPointF(ex, ey))
            p.setPen(Qt.NoPen)
    def paint_gulls(self, p, t, ph):
        for g in self.gulls:
            k = (t + g["s"]) % 1.0
            x = -60 + k * (self.w + 120)
            y = self.h * g["y"] * (self.horizon / self.h) + 18 * math.sin(TAU * 2 * k)
            flap = math.sin(30 * ph + g["s"] * 9) * 0.6
            s = g["size"]
            pen = QPen(QColor("#2a0a3a"), 2.2)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            wing = QPainterPath(QPointF(x - s, y - s * flap))
            wing.quadTo(QPointF(x - s * 0.4, y - s * 0.5), QPointF(x, y))
            wing.quadTo(QPointF(x + s * 0.4, y - s * 0.5), QPointF(x + s, y - s * flap))
            p.drawPath(wing)
            p.setPen(Qt.NoPen)

    def paint_neon_sun(self, lp, ph):
        """An outline of a sun in neon above the palm, humming."""
        c = QPointF(self.w * 0.6, self.h * 0.22)
        r = self.w * 0.24
        level = 0.85 + 0.15 * math.sin(6 * ph)
        lp.setBrush(Qt.NoBrush)
        lp.setPen(QPen(qc(PINK, 255 * level), 4))
        lp.drawEllipse(c, r, r)
        lp.setPen(QPen(qc(TEAL, 230 * level), 3))
        for k in range(12):
            a = TAU * k / 12 + ph / 6 * 0                     # rays still; the light hums
            lp.drawLine(QPointF(c.x() + math.cos(a) * r * 1.2, c.y() + math.sin(a) * r * 1.2),
                        QPointF(c.x() + math.cos(a) * r * 1.45, c.y() + math.sin(a) * r * 1.45))
        lp.setPen(Qt.NoPen)

    def paint_neon_line(self, lp, t):
        """Pink and teal neon along the strip's lower edge, a bright pulse running along it."""
        w, h = self.w, self.h
        for y, colour in ((h - 10, PINK), (h - 5, TEAL)):
            lp.setBrush(qc(colour, 200))
            lp.drawRect(QRectF(0, y, w, 1.8))
        for n in range(3):
            x = ((t * 3 + n / 3) % 1.0) * w
            g = QLinearGradient(x - 160, 0, x + 160, 0)
            g.setColorAt(0.0, qc("#ffffff", 0))
            g.setColorAt(0.5, qc("#ffffff", 220))
            g.setColorAt(1.0, qc("#ffffff", 0))
            lp.setBrush(g)
            lp.drawRect(QRectF(x - 160, h - 11, 320, 8))


def main(argv):
    screens = list(SCREENS)
    args = []
    for arg in argv:
        if arg.startswith("--screens="):
            screens = arg.split("=", 1)[1].split(",")
        elif arg != "--stills":
            args.append(arg)
    out = args[0] if args else os.path.join(os.path.expanduser("~"), "Desktop", "Light Backgrounds")
    os.makedirs(out, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    if "--stills" in argv:
        for screen in screens:
            Miami(screen).render(FRAMES // 3).save(os.path.join(out, f"preview - {screen}.png"))
        return 0
    failures = 0
    for screen in screens:
        path = os.path.join(out, f"Miami - {screen}.mp4")
        if os.path.exists(path):
            os.remove(path)
        scene = Miami(screen)
        started = time.time()
        encoder = lights.Encoder(app, scene, path, SCREENS[screen][2])
        ok = encoder.run()
        size = os.path.getsize(path) / 1e6 if os.path.exists(path) else 0
        print(f"{'ok ' if ok else 'FAIL'} miami {screen:6s} {encoder.i:4d} frames {time.time() - started:5.1f}s "
              f"{size:5.1f} MB {encoder.error}", flush=True)
        failures += 0 if ok else 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
