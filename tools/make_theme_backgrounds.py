"""
Render themed backgrounds, one seamless loop per screen (main 1920x1080 FIT, sides 512x1280
STRETCH, top 2816x128 CROP), like the lighting and New Year backgrounds:

    awards  - gold light rays turning slowly, a laurel wreath, gold confetti and dust
    aurora  - the northern lights over snowy mountains, mirrored in a still lake
    disco   - a mirror ball turning, its spots sweeping the walls, beams in the haze

    python tools/make_theme_backgrounds.py <theme> [out_folder] [--screens main,sides,top] [--stills]
"""
import math
import os
import random
import sys
import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF,
                           QRadialGradient)
from PySide6.QtWidgets import QApplication

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_light_backgrounds as lights  # noqa: E402 - the encoder and the clip length
from make_newyear_backgrounds import blank, bloom, qc  # noqa: E402

FRAMES, TAU = lights.FRAMES, math.tau
SCREENS = {"main": (1920, 1080, 24_000_000), "sides": (512, 1280, 10_000_000), "top": (2816, 128, 10_000_000)}


class Base:
    def __init__(self, screen, seed):
        self.screen = screen
        self.w, self.h, _ = SCREENS[screen]
        self.rnd = random.Random(seed)

    def start(self):
        frame = self.backdrop.copy()
        p = QPainter(frame)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        return frame, p

    def vignette(self, p, strength=150):
        g = QRadialGradient(QPointF(self.w / 2, self.h / 2), math.hypot(self.w, self.h) / 2)
        g.setColorAt(0.6, QColor(0, 0, 0, 0))
        g.setColorAt(1.0, QColor(0, 0, 0, strength if self.screen != "top" else strength // 2))
        p.fillRect(0, 0, self.w, self.h, g)


# =========================================================================================
# Awards: gold and midnight, made for names to be read over it
# =========================================================================================
class Awards(Base):
    def __init__(self, screen, seed=101):
        super().__init__(screen, seed)
        w, h, rnd = self.w, self.h, self.rnd
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        p = QPainter(img)
        sky = QLinearGradient(0, 0, 0, h)
        sky.setColorAt(0.0, QColor("#05070f"))
        sky.setColorAt(0.5, QColor("#0b1328"))
        sky.setColorAt(1.0, QColor("#04060c"))
        p.fillRect(0, 0, w, h, sky)
        p.end()
        self.backdrop = img
        self.origin = QPointF(w / 2, h * (0.42 if screen == "main" else 0.0 if screen == "sides" else 0.5))
        self.rays = 24 if screen != "top" else 0
        n = {"main": 70, "sides": 40, "top": 60}[screen]
        self.confetti = [dict(u=rnd.random(), v=rnd.random(), s=rnd.uniform(5, 11) if screen != "top" else rnd.uniform(3, 6),
                              loops=rnd.choice([1, 1, 2]), spin=rnd.choice([2, 3, 4, 5]), p=rnd.uniform(0, TAU),
                              tilt=rnd.uniform(0, 180), sway=rnd.uniform(0.005, 0.02), k=rnd.choice([1, 2]),
                              c=rnd.choice(["#e8b85a", "#f5d88f", "#c9952e", "#fff1c8"])) for _ in range(n)]
        n = {"main": 160, "sides": 80, "top": 140}[screen]
        self.dust = [dict(u=rnd.random(), v=rnd.random(), r=rnd.uniform(0.7, 1.9), loops=rnd.choice([1, 2]),
                          g=rnd.choice([3, 4, 5]), gp=rnd.uniform(0, TAU), k=rnd.choice([1, 2]), p=rnd.uniform(0, TAU))
                     for _ in range(n)]
        self.leaves = self._laurel() if screen == "main" else []

    def _laurel(self):
        """Two branches of a laurel wreath, as leaf positions round a wide oval."""
        leaves, self.stems = [], []
        cx, cy, rx, ry = self.w / 2, self.h * 0.47, self.w * 0.27, self.h * 0.37
        for side in (-1, 1):
            stem = QPainterPath()
            for k in range(23):
                u = k / 22
                phi = math.pi * (0.1 + 0.78 * u)          # from near the bottom, up the side
                x, y = cx + side * rx * math.sin(phi), cy + ry * math.cos(phi)
                (stem.moveTo if k == 0 else stem.lineTo)(QPointF(x, y))
                tangent = math.atan2(-ry * math.sin(phi), side * rx * math.cos(phi))
                size = 52 * (1 - 0.5 * u)
                for out in (-1, 1):
                    leaves.append((x, y, tangent + out * 0.55, size, u))
            self.stems.append(stem)
        return leaves

    def render(self, i):
        t = i / FRAMES
        ph = TAU * t
        frame, p = self.start()
        light = blank(self.w, self.h)
        lp = QPainter(light)
        lp.setRenderHint(QPainter.Antialiasing)
        lp.setPen(Qt.NoPen)
        w, h, o = self.w, self.h, self.origin
        # the warm heart of the stage
        core = QRadialGradient(o, max(w, h) * 0.55)
        core.setColorAt(0.0, qc("#c99a45", 120))
        core.setColorAt(0.35, qc("#6a4a1c", 60))
        core.setColorAt(1.0, qc("#6a4a1c", 0))
        p.fillRect(0, 0, w, h, core)
        # rays turning one ray's width per clip: seamless
        if self.rays:
            length = math.hypot(w, h)
            for k in range(self.rays):
                a = TAU * (k + t) / self.rays
                spread = 0.035 if k % 2 else 0.018
                g = QRadialGradient(o, length * 0.8)
                g.setColorAt(0.0, qc("#ffe2a3", 26 if k % 2 else 14))
                g.setColorAt(1.0, qc("#ffe2a3", 0))
                p.setBrush(g)
                p.drawPolygon(QPolygonF([o, QPointF(o.x() + math.cos(a - spread) * length, o.y() + math.sin(a - spread) * length),
                                         QPointF(o.x() + math.cos(a + spread) * length, o.y() + math.sin(a + spread) * length)]))
        else:                                            # the strip: a shine running along it twice
            for n in range(2):
                x = ((t * 2 + n * 0.5) % 1.0) * w * 1.3 - w * 0.15
                g = QLinearGradient(x - w * 0.08, 0, x + w * 0.08, 0)
                g.setColorAt(0.0, qc("#ffe2a3", 0))
                g.setColorAt(0.5, qc("#ffe2a3", 90))
                g.setColorAt(1.0, qc("#ffe2a3", 0))
                lp.fillRect(0, 0, w, h, g)
            for y in (5, h - 6):                         # fine gold rules along both edges
                rule = QLinearGradient(0, 0, w, 0)
                for s, a in ((0, 40), (0.5, 200), (1, 40)):
                    rule.setColorAt(s, qc("#e8b85a", a))
                p.fillRect(QRectF(0, y, w, 1.6), rule)
        # the laurel wreath, gold leaves glinting in a wave
        for stem in getattr(self, "stems", []):
            p.setPen(QPen(qc("#b8893a", 170), 2.2))
            p.setBrush(Qt.NoBrush)
            p.drawPath(stem)
            p.setPen(Qt.NoPen)
        for x, y, angle, size, u in self.leaves:
            glint = max(0.0, math.cos(TAU * u - 2 * ph)) ** 6
            p.save()
            p.translate(x, y)
            p.rotate(math.degrees(angle))
            leaf = QPainterPath(QPointF(0, 0))
            leaf.quadTo(QPointF(size * 0.5, -size * 0.28), QPointF(size, 0))
            leaf.quadTo(QPointF(size * 0.5, size * 0.28), QPointF(0, 0))
            g = QLinearGradient(0, -size * 0.3, 0, size * 0.3)
            g.setColorAt(0.0, QColor("#f5d88f"))
            g.setColorAt(1.0, QColor("#8a6420"))
            p.setBrush(g)
            p.setOpacity(0.85)
            p.drawPath(leaf)
            p.setOpacity(1.0)
            p.restore()
            if glint > 0.05:
                lp.setBrush(qc("#fff1c8", 200 * glint))
                lp.drawEllipse(QPointF(x, y), 3 + 3 * glint, 3 + 3 * glint)
        # confetti: gold foil turning as it falls
        for c in self.confetti:
            span = h + 40
            y = (c["v"] + c["loops"] * t) % 1.0 * span - 20
            x = (c["u"] + c["sway"] * math.sin(c["k"] * ph + c["p"])) * w
            turn = math.cos(c["spin"] * ph + c["p"])
            p.save()
            p.translate(x, y)
            p.rotate(c["tilt"] + 40 * math.sin(c["k"] * ph + c["p"]))
            colour = QColor(c["c"]).lighter(100 + int(40 * abs(turn)))
            p.setBrush(colour)
            p.drawRect(QRectF(-c["s"] / 2, -c["s"] * 0.3 * abs(turn) - 0.4, c["s"], c["s"] * 0.6 * abs(turn) + 0.8))
            p.restore()
            if abs(turn) > 0.97:
                lp.setBrush(qc("#fff1c8", 160))
                lp.drawEllipse(QPointF(x, y), 2.5, 2.5)
        for d in self.dust:                              # dust rising in the warm air
            y = (d["v"] - d["loops"] * t) % 1.0 * (h + 8) - 4
            x = (d["u"] + 0.01 * math.sin(d["k"] * ph + d["p"])) * w
            glint = max(0.0, math.sin(d["g"] * ph + d["gp"])) ** 8
            lp.setBrush(qc("#ffe2a3", 70 + 170 * glint))
            lp.drawEllipse(QPointF(x, y), d["r"] * (1 + glint), d["r"] * (1 + glint))
        lp.end()
        bloom(p, light, w, h, 1.1)
        self.vignette(p, 170)
        p.end()
        return frame


# =========================================================================================
# Aurora: the northern lights over mountains and a lake
# =========================================================================================
class Aurora(Base):
    def __init__(self, screen, seed=202):
        super().__init__(screen, seed)
        w, h, rnd = self.w, self.h, self.rnd
        self.horizon = h * {"main": 0.7, "sides": 0.82, "top": 1.2}[screen]
        self.stars = [dict(u=rnd.random(), v=rnd.random() * (self.horizon / h) * 0.95, s=rnd.uniform(0.5, 1.6),
                           k=rnd.choice([1, 2, 3, 4]), p=rnd.uniform(0, TAU)) for _ in range({"main": 380, "sides": 160, "top": 160}[screen])]
        self.curtains = [dict(base=b, length=l, f1=f1, f2=f2, p=rnd.uniform(0, TAU), dir=d, hue=hue)
                         for b, l, f1, f2, d, hue in ((0.38, 0.26, 1.2, 3, 1, 0), (0.3, 0.2, 1.7, 4, -1, 1), (0.46, 0.16, 2.3, 5, 1, 0))]
        self.backdrop = self._paint_backdrop()
        self.mountains = self._paint_mountains() if screen != "top" else None
        self.shooting = dict(s=0.62, x=0.2, y=0.12, a=math.radians(18))

    def _paint_backdrop(self):
        w, h = self.w, self.h
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        p = QPainter(img)
        sky = QLinearGradient(0, 0, 0, self.horizon)
        sky.setColorAt(0.0, QColor("#02040b"))
        sky.setColorAt(0.6, QColor("#06142a"))
        sky.setColorAt(1.0, QColor("#0d2a3a"))
        p.fillRect(0, 0, w, h, sky)
        p.end()
        return img

    def _paint_mountains(self):
        w, h, rnd = self.w, self.h, self.rnd
        img = blank(w, h)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        for layer, (colour, top, rough) in enumerate((("#0d1b2e", 0.62, 0.22), ("#08121f", 0.66, 0.13), ("#040a12", 0.69, 0.05))):
            level = self.horizon - h * (0.7 - top) * (1.0 if self.screen == "main" else 0.55)
            peaks = []
            x = -50
            while x < w + 50:
                peaks.append((x, level - rnd.uniform(0.3, 1.0) * h * rough * (1.0 if self.screen == "main" else 0.5)))
                x += rnd.uniform(90, 220) if self.screen == "main" else rnd.uniform(60, 140)
            path = QPainterPath(QPointF(-50, self.horizon))
            for px, py in peaks:
                path.lineTo(px, py)
            path.lineTo(w + 50, self.horizon)
            path.closeSubpath()
            p.setBrush(QColor(colour))
            p.drawPath(path)
            if layer < 2:                                # snow on the high peaks, lying on their slopes
                for (ax, ay), (px, py), (bx, by) in zip(peaks, peaks[1:], peaks[2:]):
                    if not (py < ay and py < by) or level - py < h * rough * 0.45:
                        continue
                    f = 0.32
                    lx, ly = px + (ax - px) * f, py + (ay - py) * f
                    rx_, ry_ = px + (bx - px) * f, py + (by - py) * f
                    cap = QPolygonF([QPointF(px, py), QPointF(lx, ly), QPointF(lx + (px - lx) * 0.35, ly + 6),
                                     QPointF((lx + rx_) / 2, (ly + ry_) / 2 - 4), QPointF(rx_ + (px - rx_) * 0.35, ry_ + 8),
                                     QPointF(rx_, ry_)])
                    g = QLinearGradient(px, py, px, max(ly, ry_))
                    g.setColorAt(0.0, qc("#cfe6f2", 150 if layer == 0 else 110))
                    g.setColorAt(1.0, qc("#7fa6bd", 70))
                    p.setBrush(g)
                    p.drawPolygon(cap)
        p.end()
        return img

    def paint_aurora(self, p, t, ph):
        """Curtains as many thin vertical strokes, bright at the foot and fading up."""
        w, h = self.w, self.h
        scale = self.horizon / h if self.screen != "top" else 1.0
        strips = 260 if self.screen == "main" else 140 if self.screen == "sides" else 320
        for c in self.curtains:
            for s in range(strips):
                u = s / strips
                foot = h * scale * (c["base"] + 0.07 * math.sin(TAU * c["f1"] * u + c["dir"] * ph + c["p"])
                                    + 0.03 * math.sin(TAU * c["f2"] * u - 2 * ph))
                if self.screen == "top":
                    foot = h * (0.85 + 0.08 * math.sin(TAU * c["f1"] * 2 * u + c["dir"] * ph + c["p"]))
                length = h * scale * c["length"] * (0.7 + 0.3 * math.sin(TAU * 3 * u + ph + c["p"]))
                if self.screen == "top":
                    length = h * 0.8
                level = (0.5 + 0.5 * math.sin(TAU * c["f2"] * u - c["dir"] * 2 * ph + c["p"])) ** 2
                level *= 0.6 + 0.4 * math.sin(TAU * 7 * u + 3 * ph)
                if level < 0.03:
                    continue
                x = u * w
                g = QLinearGradient(0, foot, 0, foot - length)
                green = QColor("#57ffa8") if not c["hue"] else QColor("#4dffd8")
                g.setColorAt(0.0, qc(green, 0))
                g.setColorAt(0.04, qc(green, 150 * level))
                g.setColorAt(0.35, qc("#2bd97a", 70 * level))
                g.setColorAt(0.75, qc("#a24dff", 26 * level))
                g.setColorAt(1.0, qc("#a24dff", 0))
                p.setBrush(g)
                p.drawRect(QRectF(x, foot - length, w / strips + 1.2, length))

    def render(self, i):
        t = i / FRAMES
        ph = TAU * t
        frame, p = self.start()
        w, h = self.w, self.h
        light = blank(w, h)
        lp = QPainter(light)
        lp.setRenderHint(QPainter.Antialiasing)
        lp.setPen(Qt.NoPen)
        for s in self.stars:
            level = 0.4 + 0.6 * (0.5 + 0.5 * math.sin(s["k"] * ph + s["p"]))
            lp.setBrush(qc("#e6f0ff", 200 * level))
            lp.drawEllipse(QPointF(s["u"] * w, s["v"] * h), s["s"], s["s"])
        age = (t - self.shooting["s"]) % 1.0              # a shooting star, once
        if age < 0.04 and self.screen == "main":
            k = age / 0.04
            sx = (self.shooting["x"] + 0.25 * k) * w
            sy = (self.shooting["y"] + 0.25 * k * math.tan(self.shooting["a"])) * h
            g = QLinearGradient(sx, sy, sx - 160, sy - 160 * math.tan(self.shooting["a"]))
            g.setColorAt(0.0, qc("#ffffff", 230 * (1 - k)))
            g.setColorAt(1.0, qc("#ffffff", 0))
            lp.setPen(QPen(g, 2))
            lp.drawLine(QPointF(sx, sy), QPointF(sx - 160, sy - 160 * math.tan(self.shooting["a"])))
            lp.setPen(Qt.NoPen)
        lp.setCompositionMode(QPainter.CompositionMode_Plus)
        self.paint_aurora(lp, t, ph)
        lp.end()
        bloom(p, light, w, h, 0.9)
        if self.mountains is not None:
            p.drawImage(0, 0, self.mountains)
            self.paint_lake(p, frame, ph)
        self.vignette(p, 140)
        p.end()
        return frame

    def paint_lake(self, p, frame, ph):
        """The sky upside down in the water, broken into slow ripples."""
        w, h = self.w, self.h
        top = int(self.horizon)
        depth = h - top
        if depth <= 4:
            return
        reach = min(top, depth * 2)                       # the sky above, squeezed into the water
        sky = frame.copy(0, top - reach, w, reach).mirrored(False, True).scaled(
            w, depth, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        water = blank(w, depth)
        wp = QPainter(water)
        wp.fillRect(0, 0, w, depth, QColor("#02060c"))
        band = 3
        for y in range(0, depth, band):
            shift = 6 * math.sin(y * 0.09 + ph * 3) * (y / depth + 0.2)
            wp.setOpacity(0.55 * (1 - y / depth) + 0.1)
            wp.drawImage(QPointF(shift, y), sky, QRectF(0, y, w, band))
        wp.end()
        p.drawImage(0, top, water)
        line = QLinearGradient(0, 0, w, 0)
        for s, a in ((0, 0), (0.5, 60), (1, 0)):
            line.setColorAt(s, qc("#7fe8c0", a))
        p.fillRect(QRectF(0, top - 1, w, 1.5), line)


# =========================================================================================
# Disco: a mirror ball and its spots
# =========================================================================================
class Disco(Base):
    def __init__(self, screen, seed=303):
        super().__init__(screen, seed)
        w, h, rnd = self.w, self.h, self.rnd
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        p = QPainter(img)
        room = QLinearGradient(0, 0, 0, h)
        room.setColorAt(0.0, QColor("#07031a"))
        room.setColorAt(0.6, QColor("#120632"))
        room.setColorAt(1.0, QColor("#05020f"))
        p.fillRect(0, 0, w, h, room)
        p.end()
        self.backdrop = img
        self.ball = {"main": (w / 2, h * 0.24, 118), "sides": (w / 2, h * 0.14, 110), "top": None}[screen]
        n = {"main": 480, "sides": 220, "top": 300}[screen]
        self.spots = [dict(lat=math.asin(rnd.uniform(-0.95, 0.95)), lon=rnd.uniform(0, TAU), s=rnd.uniform(0.6, 1.4),
                           group=rnd.randrange(3)) for _ in range(n)]
        self.haze = [dict(u=rnd.random(), v=rnd.random(), r=rnd.uniform(0.25, 0.5), k=rnd.choice([1, -1]),
                          c=rnd.choice(["#5a1aa0", "#1a3aa0", "#a01a6a"])) for _ in range(5)]
        self.colours = [QColor("#ffffff"), QColor("#ff4fd8"), QColor("#4fd8ff")]

    def render(self, i):
        t = i / FRAMES
        ph = TAU * t
        frame, p = self.start()
        w, h = self.w, self.h
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        for z in self.haze:                               # coloured haze drifting across
            r = z["r"] * max(w, h)
            x = ((z["u"] + z["k"] * t) % 1.0) * (w + 2 * r) - r
            g = QRadialGradient(QPointF(x, z["v"] * h), r)
            g.setColorAt(0.0, qc(z["c"], 46))
            g.setColorAt(1.0, qc(z["c"], 0))
            p.setBrush(g)
            p.drawEllipse(QPointF(x, z["v"] * h), r, r)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        light = blank(w, h)
        lp = QPainter(light)
        lp.setRenderHint(QPainter.Antialiasing)
        lp.setPen(Qt.NoPen)
        turn = ph                                          # once round per clip
        bx, by = (self.ball[0], self.ball[1]) if self.ball else (w / 2, -h * 3)
        reach = max(w, h) * (0.75 if self.screen != "top" else 0.55)
        # the spots, and faint beams to them through the haze
        for s in self.spots:
            a = s["lon"] + turn
            facing = math.cos(a)
            if facing <= 0.05:
                continue
            # the room's walls and floor, all round: spots fill the whole picture
            x = w / 2 + math.sin(a) * math.cos(s["lat"]) * w * 0.78
            y = h * 0.02 + (math.sin(s["lat"]) / 0.95 + 1) / 2 * h * 0.98
            if self.ball and math.hypot(x - bx, y - by) < self.ball[2] * 1.1:
                continue
            if self.screen == "top":
                x = w / 2 + math.sin(a) * w * 0.62
                y = h * (0.5 + 0.42 * math.sin(s["lat"]) / 0.95)
            colour = self.colours[(s["group"] + int(t * 6)) % 3] if s["group"] else self.colours[0]
            size = (2.2 + 3.6 * s["s"]) * (0.6 + 0.4 * facing)
            if self.ball and self.screen != "top":
                beam = QLinearGradient(QPointF(bx, by), QPointF(x, y))
                beam.setColorAt(0.0, qc(colour, 16 * facing))
                beam.setColorAt(1.0, qc(colour, 6 * facing))
                p.setPen(QPen(beam, 1.4))
                p.drawLine(QPointF(bx, by), QPointF(x, y))
                p.setPen(Qt.NoPen)
            lp.setBrush(qc(colour, 230 * facing))
            lp.save()
            lp.translate(x, y)
            lp.rotate(math.degrees(math.atan2(y - by, x - bx)))
            lp.drawEllipse(QPointF(0, 0), size * (1.0 + 0.6 * (1 - facing)), size)
            lp.restore()
        if self.ball:
            for side, colour in ((-1, "#ff4fd8"), (1, "#4fd8ff")):   # two spotlights on the ball
                sx, sy = w / 2 + side * w * 0.55, h * 1.05
                sway = 0.04 * math.sin(2 * ph + side)
                cone = QLinearGradient(QPointF(sx, sy), QPointF(bx, by))
                cone.setColorAt(0.0, qc(colour, 0))
                cone.setColorAt(1.0, qc(colour, 60))
                p.setBrush(cone)
                d = math.hypot(bx - sx, by - sy)
                nx, ny = -(by - sy) / d, (bx - sx) / d
                p.drawPolygon(QPolygonF([QPointF(sx, sy), QPointF(bx + nx * (40 + 900 * sway), by + ny * 40),
                                         QPointF(bx - nx * 40, by - ny * 40)]))
            self.paint_ball(p, lp, bx, by, self.ball[2], turn, ph)
            lp.setBrush(qc("#ffffff", 200))                         # the glint where the light meets it
            for length, width in ((90, 2.0), (50, 3.0)):
                lp.drawRect(QRectF(bx - self.ball[2] * 0.45 - length, by - self.ball[2] * 0.45 - width / 2, length * 2, width))
                lp.drawRect(QRectF(bx - self.ball[2] * 0.45 - width / 2, by - self.ball[2] * 0.45 - length, width, length * 2))
        lp.end()
        bloom(p, light, w, h, 1.2)
        self.vignette(p, 160)
        p.end()
        return frame

    def paint_ball(self, p, lp, cx, cy, r, turn, ph):
        p.setPen(QPen(qc("#8a8fa0", 160), 2))           # the chain
        p.drawLine(QPointF(cx, 0), QPointF(cx, cy - r))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#0c0c14"))
        p.drawEllipse(QPointF(cx, cy), r, r)
        rows, cols = 16, 32
        for row in range(rows):
            lat0 = -math.pi / 2 + math.pi * row / rows
            lat1 = lat0 + math.pi / rows
            for col in range(cols):
                lon0 = TAU * col / cols + turn
                lon1 = lon0 + TAU / cols
                mid = (lon0 + lon1) / 2
                z = math.cos(mid) * math.cos((lat0 + lat1) / 2)
                if z <= 0:
                    continue
                corners = []
                for la, lo in ((lat0, lon0), (lat0, lon1), (lat1, lon1), (lat1, lon0)):
                    corners.append(QPointF(cx + r * math.sin(lo) * math.cos(la) * 0.985,
                                           cy + r * math.sin(la) * 0.985))
                # light from up-left: facets turned to it flash
                nx, ny = math.sin(mid) * math.cos((lat0 + lat1) / 2), math.sin((lat0 + lat1) / 2)
                lit = max(0.0, -0.55 * nx - 0.55 * ny + 0.62 * z)
                sparkle = max(0.0, math.sin(row * 2.1 + col * 1.3 + 7 * ph)) ** 40
                shade = 50 + 150 * lit ** 2 + 40 * z
                p.setBrush(QColor(int(min(255, shade * 0.95)), int(min(255, shade * 0.97)), int(min(255, shade * 1.05))))
                p.drawPolygon(QPolygonF(corners))
                if sparkle > 0.2:
                    centre = QPointF(sum(c.x() for c in corners) / 4, sum(c.y() for c in corners) / 4)
                    lp.setBrush(qc("#ffffff", 255 * sparkle))
                    lp.drawEllipse(centre, 2.5 + 3 * sparkle, 2.5 + 3 * sparkle)


THEMES = {"awards": (Awards, "Awards"), "aurora": (Aurora, "Aurora"), "disco": (Disco, "Disco")}


def main(argv):
    theme = argv[0]
    screens = list(SCREENS)
    args = []
    for arg in argv[1:]:
        if arg.startswith("--screens="):
            screens = arg.split("=", 1)[1].split(",")
        elif arg != "--stills":
            args.append(arg)
    cls, title = THEMES[theme]
    out = args[0] if args else os.path.join(os.path.expanduser("~"), "Desktop", "Light Backgrounds")
    os.makedirs(out, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    if "--stills" in argv:
        for screen in screens:
            cls(screen).render(FRAMES // 3).save(os.path.join(out, f"preview - {screen}.png"))
        return 0
    failures = 0
    for screen in screens:
        path = os.path.join(out, f"{title} - {screen}.mp4")
        if os.path.exists(path):
            os.remove(path)
        scene = cls(screen)
        started = time.time()
        encoder = lights.Encoder(app, scene, path, SCREENS[screen][2])
        ok = encoder.run()
        size = os.path.getsize(path) / 1e6 if os.path.exists(path) else 0
        print(f"{'ok ' if ok else 'FAIL'} {theme} {screen:6s} {encoder.i:4d} frames {time.time() - started:5.1f}s "
              f"{size:5.1f} MB {encoder.error}", flush=True)
        failures += 0 if ok else 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
