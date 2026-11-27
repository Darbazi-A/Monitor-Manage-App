"""
Render a bright New Year scene, one seamless loop per screen:
    main   1920 x 1080   (played FIT)     - a decorated tree, children dancing round it, fireworks
    sides   512 x 1280   (played STRETCH) - baubles swinging under a garland, presents, snow
    top    2816 x  128   (played CROP)    - a garland of chasing lights on the ceiling strip

Drawn with QPainter and encoded through Qt Multimedia, like make_light_backgrounds.py; every
movement repeats a whole number of times per clip, so the last frame runs into the first.

    python tools/make_newyear_backgrounds.py [out_folder] [--screens main,sides,top] [--stills]
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

FRAMES, TAU = lights.FRAMES, math.tau
SCREENS = {
    "main": (1920, 1080, 20_000_000),
    "sides": (512, 1280, 8_000_000),
    "top": (2816, 128, 8_000_000),
}
BRIGHT = ["#ff3b5c", "#ffd23f", "#3ddc84", "#3da9ff", "#c86bff", "#ff8a3d"]
SKIN = ["#f6d2b4", "#e9b48f", "#c98e64", "#8d5b3c", "#f3c9a6"]
HAIR = ["#3a2516", "#6b3e1f", "#e0b04a", "#1d1410", "#a0522d"]


def qc(colour, alpha=255):
    c = QColor(colour)
    c.setAlpha(max(0, min(255, int(alpha))))
    return c


def glow(p, x, y, r, colour, alpha):
    g = QRadialGradient(QPointF(x, y), r)
    g.setColorAt(0.0, qc(colour, alpha))
    g.setColorAt(0.4, qc(colour, alpha * 0.35))
    g.setColorAt(1.0, qc(colour, 0))
    p.setBrush(g)
    p.drawEllipse(QPointF(x, y), r, r)


class Scene:
    def __init__(self, screen, seed=2027):
        self.screen = screen
        self.w, self.h, _ = SCREENS[screen]
        self.rnd = random.Random(seed)
        rnd = self.rnd
        self.base = self._paint_base()
        n_snow = {"main": 160, "sides": 90, "top": 120}[screen]
        self.snow = [dict(u=rnd.random(), v=rnd.random(), r=rnd.uniform(1.2, 3.6) if screen != "top" else rnd.uniform(0.8, 2.2),
                          loops=rnd.choice([1, 2, 2, 3]) if screen != "top" else rnd.choice([4, 5, 6]),
                          k=rnd.choice([1, 2, 3]), p=rnd.uniform(0, TAU), sway=rnd.uniform(0.004, 0.015))
                     for _ in range(n_snow)]
        self.sparkles = [dict(u=rnd.random(), v=rnd.random(), k=rnd.choice([2, 3, 4, 5]), p=rnd.uniform(0, TAU),
                              s=rnd.uniform(2, 5), c=rnd.choice(["#fff6d6", "#ffd23f", "#ffffff"]))
                         for _ in range({"main": 50, "sides": 30, "top": 70}[screen])]
        if screen == "main":
            self._setup_main()
        elif screen == "sides":
            self._setup_sides()

    # -- the parts that do not move ----------------------------------------------------
    def _paint_base(self):
        w, h = self.w, self.h
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        sky = QLinearGradient(0, 0, 0, h)
        sky.setColorAt(0.0, QColor("#140a3a"))
        sky.setColorAt(0.55, QColor("#3a1670"))
        sky.setColorAt(1.0, QColor("#7a2a7a"))
        p.fillRect(0, 0, w, h, sky)
        if self.screen == "main":
            warm = QRadialGradient(QPointF(w / 2, h * 0.62), w * 0.55)
            warm.setColorAt(0.0, qc("#ffb347", 150))
            warm.setColorAt(0.45, qc("#ff6a8a", 60))
            warm.setColorAt(1.0, qc("#ff6a8a", 0))
            p.fillRect(0, 0, w, h, warm)
            ground = QPainterPath(QPointF(0, h))
            for s in range(61):
                x = w * s / 60
                ground.lineTo(x, h * (0.8 - 0.02 * math.sin(TAU * s / 60 * 1.5 + 0.7)))
            ground.lineTo(w, h)
            fill = QLinearGradient(0, h * 0.76, 0, h)
            fill.setColorAt(0.0, QColor("#fbfdff"))
            fill.setColorAt(1.0, QColor("#c9d8f2"))
            p.setBrush(fill)
            p.drawPath(ground)
            pool = QRadialGradient(QPointF(w / 2, h * 0.86), w * 0.34)
            pool.setColorAt(0.0, qc("#ffd98a", 120))
            pool.setColorAt(1.0, qc("#ffd98a", 0))
            p.setBrush(pool)
            p.drawEllipse(QPointF(w / 2, h * 0.86), w * 0.34, h * 0.1)
        elif self.screen == "sides":
            ground = QLinearGradient(0, h * 0.86, 0, h)
            ground.setColorAt(0.0, QColor("#eef4ff"))
            ground.setColorAt(1.0, QColor("#c9d8f2"))
            p.setBrush(ground)
            p.drawRect(QRectF(0, h * 0.88, w, h * 0.12))
        p.end()
        return img

    def _setup_main(self):
        w, h, rnd = self.w, self.h, self.rnd
        self.cx, self.ground_y = w / 2, h * 0.84
        self.tree_top, self.tree_base = h * 0.1, h * 0.8
        # baubles on the branches, in front, fixed in place
        self.baubles = []
        for tier in range(5):
            y0 = self.tree_top + (self.tree_base - self.tree_top) * (0.18 + tier * 0.17)
            half = (y0 - self.tree_top) * 0.5
            for _ in range(3 + tier * 2):
                self.baubles.append(dict(x=self.cx + rnd.uniform(-0.85, 0.85) * half, y=y0 + rnd.uniform(-10, 30),
                                         r=rnd.uniform(9, 15), c=rnd.choice(BRIGHT), p=rnd.uniform(0, TAU),
                                         k=rnd.choice([1, 2, 3])))
        # the lights: four swags round the tree, chasing
        self.swags = []
        for tier in range(4):
            y = self.tree_top + (self.tree_base - self.tree_top) * (0.25 + tier * 0.19)
            self.swags.append((y, (y - self.tree_top) * 0.52))
        # presents under the tree
        self.gifts = []
        for k in range(7):
            gw = rnd.uniform(50, 90)
            self.gifts.append(dict(x=self.cx + (k - 3) * 78 + rnd.uniform(-10, 10), w=gw, h=gw * rnd.uniform(0.7, 1.1),
                                   c=rnd.choice(BRIGHT), ribbon=rnd.choice(["#ffffff", "#ffd23f", "#ff3b5c"])))
        # children holding hands, round the tree, once round per clip
        self.kids = []
        coats = ["#ff3b5c", "#3da9ff", "#ffd23f", "#3ddc84", "#c86bff", "#ff8a3d", "#ff5fa2", "#2bd8c8", "#ffb000"]
        for k in range(14):
            self.kids.append(dict(a0=TAU * k / 14, coat=coats[k % len(coats)], skin=SKIN[k % len(SKIN)], hair=HAIR[(k * 2) % len(HAIR)],
                                  hat=rnd.choice([None, "#ff3b5c", "#3da9ff", "#ffffff", "#3ddc84"]),
                                  dress=k % 2 == 0, tall=rnd.uniform(0.9, 1.08), p=rnd.uniform(0, TAU)))
        # fireworks bursting at their own moments of the loop
        self.bursts = [dict(s=k / 6 + rnd.uniform(0, 0.08), x=rnd.choice([rnd.uniform(0.08, 0.3), rnd.uniform(0.7, 0.92)]),
                            y=rnd.uniform(0.1, 0.32), c=rnd.choice(BRIGHT), c2=rnd.choice(BRIGHT), n=rnd.choice([28, 34, 40]))
                       for k in range(6)]

    def _setup_sides(self):
        rnd = self.rnd
        self.ornaments = [dict(x=rnd.uniform(0.12, 0.88), length=rnd.uniform(0.12, 0.55), r=rnd.uniform(26, 46),
                               c=BRIGHT[k % len(BRIGHT)], k=rnd.choice([1, 2]), a=rnd.uniform(4, 9),
                               p=rnd.uniform(0, TAU), star=k % 4 == 3) for k in range(8)]
        self.gifts = []
        x = 10
        while x < self.w - 40:
            gw = rnd.uniform(70, 120)
            self.gifts.append(dict(x=x + gw / 2, w=gw, h=gw * rnd.uniform(0.6, 1.0), c=rnd.choice(BRIGHT),
                                   ribbon=rnd.choice(["#ffffff", "#ffd23f"])))
            x += gw + rnd.uniform(4, 14)

    # -- one frame -----------------------------------------------------------------------
    def render(self, i):
        t = i / FRAMES
        ph = TAU * t
        frame = self.base.copy()
        p = QPainter(frame)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        if self.screen == "main":
            self.paint_fireworks(p, t)
            self.paint_snow(p, t, ph)
            self.paint_kids(p, ph, behind=True)
            self.paint_tree(p, t, ph)
            self.paint_gifts(p, self.ground_y + 6)
            self.paint_kids(p, ph, behind=False)
        elif self.screen == "sides":
            self.paint_snow(p, t, ph)
            self.paint_garland(p, t, self.h * 0.03, 3, 0.05)
            self.paint_ornaments(p, ph)
            self.paint_gifts(p, self.h * 0.93)
        else:
            self.paint_snow(p, t, ph)
            self.paint_garland(p, t, self.h * 0.1, 18, 0.42)
        self.paint_sparkles(p, ph)
        p.end()
        return frame

    def paint_snow(self, p, t, ph):
        for f in self.snow:
            span = self.h + 4 * f["r"]
            y = (f["v"] + f["loops"] * t) % 1.0 * span - 2 * f["r"]
            x = (f["u"] + f["sway"] * math.sin(f["k"] * ph + f["p"])) * self.w
            p.setBrush(qc("#ffffff", 200))
            p.drawEllipse(QPointF(x, y), f["r"], f["r"])

    def paint_sparkles(self, p, ph):
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        for s in self.sparkles:
            level = max(0.0, math.sin(s["k"] * ph + s["p"])) ** 4
            if level < 0.03:
                continue
            x, y, r = s["u"] * self.w, s["v"] * self.h, s["s"] * (1 + level)
            glow(p, x, y, r * 4, s["c"], 220 * level)
            p.setBrush(qc(s["c"], 200 * level))
            p.drawRect(QRectF(x - r * 4, y - 0.7, r * 8, 1.4))
            p.drawRect(QRectF(x - 0.7, y - r * 4, 1.4, r * 8))
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)

    def paint_fireworks(self, p, t):
        w, h = self.w, self.h
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        for b in self.bursts:
            age = (t - b["s"]) % 1.0
            if age > 0.14:
                continue
            k = age / 0.14                               # 0..1 over the burst
            ox, oy = b["x"] * w, b["y"] * h
            if k < 0.12:                                 # the flash
                glow(p, ox, oy, 120 * (1 - k * 4), "#fff4d6", 200)
            spread = 190 * (1 - (1 - k) ** 2.2)
            fade = (1 - k) ** 1.3
            for n in range(b["n"]):
                a = TAU * n / b["n"]
                x = ox + math.cos(a) * spread
                y = oy + math.sin(a) * spread + 90 * k * k   # falling a little
                colour = b["c"] if n % 2 else b["c2"]
                glow(p, x, y, 9, colour, 255 * fade)
                trail = QPen(qc(colour, 120 * fade), 2.2)
                p.setPen(trail)
                p.drawLine(QPointF(x, y), QPointF(ox + math.cos(a) * spread * 0.7, oy + math.sin(a) * spread * 0.7 + 60 * k * k))
                p.setPen(Qt.NoPen)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)

    def paint_tree(self, p, t, ph):
        cx, top, base = self.cx, self.tree_top, self.tree_base
        height = base - top
        # glow behind
        glow(p, cx, top + height * 0.55, height * 0.65, "#ffcf6a", 70)
        # trunk
        p.setBrush(QColor("#6b3a1e"))
        p.drawRect(QRectF(cx - 26, base - 30, 52, 70))
        # five tiers of branches, back to front
        for tier in range(5):
            t_top = top + height * (0.02 + tier * 0.15)
            t_bot = top + height * (0.26 + tier * 0.185)
            half = (t_bot - top) * 0.5
            path = QPainterPath(QPointF(cx, t_top))
            # a scalloped hem
            steps = 6 + tier * 2
            path.lineTo(cx - half, t_bot)
            for s in range(steps):
                x0 = cx - half + 2 * half * s / steps
                x1 = cx - half + 2 * half * (s + 1) / steps
                path.quadTo(QPointF((x0 + x1) / 2, t_bot + 16), QPointF(x1, t_bot))
            path.closeSubpath()
            g = QLinearGradient(cx - half, 0, cx + half, 0)
            g.setColorAt(0.0, QColor("#0f6b3a"))
            g.setColorAt(0.5, QColor("#1fa055"))
            g.setColorAt(1.0, QColor("#0b5a30"))
            p.setBrush(g)
            p.drawPath(path)
        # tinsel and chasing lights
        for n, (y, half) in enumerate(self.swags):
            pen = QPen(qc("#ffd86b", 210), 4)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            path = QPainterPath(QPointF(self.cx - half, y - 20))
            path.quadTo(QPointF(self.cx, y + 45), QPointF(self.cx + half, y - 30))
            p.drawPath(path)
            p.setPen(Qt.NoPen)
            bulbs = 9 + n * 3
            for b in range(bulbs):
                s = (b + 0.5) / bulbs
                x = (1 - s) ** 2 * (self.cx - half) + 2 * (1 - s) * s * self.cx + s * s * (self.cx + half)
                yy = (1 - s) ** 2 * (y - 20) + 2 * (1 - s) * s * (y + 45) + s * s * (y - 30)
                colour = BRIGHT[(b + n) % len(BRIGHT)]
                on = 0.35 + 0.65 * (0.5 + 0.5 * math.cos(TAU * (b / 4.0) - ph * 8))
                p.setCompositionMode(QPainter.CompositionMode_Plus)
                glow(p, x, yy + 6, 22, colour, 170 * on)
                p.setCompositionMode(QPainter.CompositionMode_SourceOver)
                p.setBrush(qc(colour, 140 + 115 * on))
                p.drawEllipse(QPointF(x, yy + 6), 5.5, 7)
        # baubles
        for b in self.baubles:
            shine = 0.5 + 0.5 * math.sin(b["k"] * ph + b["p"])
            g = QRadialGradient(QPointF(b["x"] - b["r"] * 0.35, b["y"] - b["r"] * 0.35), b["r"] * 1.3)
            g.setColorAt(0.0, QColor("#ffffff"))
            g.setColorAt(0.25, QColor(b["c"]).lighter(120))
            g.setColorAt(1.0, QColor(b["c"]).darker(140))
            p.setBrush(g)
            p.drawEllipse(QPointF(b["x"], b["y"]), b["r"], b["r"])
            p.setCompositionMode(QPainter.CompositionMode_Plus)
            glow(p, b["x"] - b["r"] * 0.35, b["y"] - b["r"] * 0.35, b["r"] * 0.9, "#ffffff", 90 * shine)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        # the star, turning its rays
        sx, sy = cx, top + 4
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        glow(p, sx, sy, 140 + 25 * math.sin(ph * 4), "#ffd23f", 170)
        for r in range(12):
            a = TAU * r / 12 + ph
            length = 170 if r % 2 else 110
            g = QLinearGradient(QPointF(sx, sy), QPointF(sx + math.cos(a) * length, sy + math.sin(a) * length))
            g.setColorAt(0.0, qc("#fff1b0", 120))
            g.setColorAt(1.0, qc("#fff1b0", 0))
            p.setBrush(g)
            a1, a2 = a - 0.05, a + 0.05
            p.drawPolygon(QPolygonF([QPointF(sx, sy), QPointF(sx + math.cos(a1) * length, sy + math.sin(a1) * length),
                                     QPointF(sx + math.cos(a2) * length, sy + math.sin(a2) * length)]))
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        star = QPolygonF()
        for k in range(10):
            a = -TAU / 4 + TAU * k / 10
            r = 46 if k % 2 == 0 else 19
            star.append(QPointF(sx + math.cos(a) * r, sy + math.sin(a) * r))
        g = QRadialGradient(QPointF(sx, sy - 8), 50)
        g.setColorAt(0.0, QColor("#fffbe0"))
        g.setColorAt(1.0, QColor("#ffb800"))
        p.setBrush(g)
        p.drawPolygon(star)

    def paint_gifts(self, p, floor):
        for g in self.gifts:
            x, w, h = g["x"], g["w"], g["h"]
            rect = QRectF(x - w / 2, floor - h, w, h)
            grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
            grad.setColorAt(0.0, QColor(g["c"]).lighter(125))
            grad.setColorAt(1.0, QColor(g["c"]).darker(125))
            p.setBrush(grad)
            p.drawRoundedRect(rect, 4, 4)
            p.setBrush(QColor(g["ribbon"]))
            p.drawRect(QRectF(x - w * 0.07, floor - h, w * 0.14, h))
            p.drawRect(QRectF(x - w / 2, floor - h * 0.62, w, h * 0.12))
            p.drawEllipse(QPointF(x - w * 0.16, floor - h - 7), w * 0.16, 8)
            p.drawEllipse(QPointF(x + w * 0.16, floor - h - 7), w * 0.16, 8)

    # -- the children ---------------------------------------------------------------------
    def _kid_place(self, kid, ph):
        a = kid["a0"] + ph                                # once round the tree per clip
        depth = math.sin(a)                               # +1 in front, -1 behind
        x = self.cx + math.cos(a) * self.w * 0.25
        feet = self.ground_y + depth * self.h * 0.06
        scale = (0.78 + 0.22 * (depth + 1) / 2) * kid["tall"]
        hop = abs(math.sin(10 * ph + kid["p"])) * 10 * scale    # ten little skips per clip, each
        return x, feet - hop, scale, depth

    def paint_kids(self, p, ph, behind):
        places = [self._kid_place(k, ph) for k in self.kids]
        order = sorted(range(len(self.kids)), key=lambda n: places[n][3])
        for n in order:
            depth = places[n][3]
            if (depth < 0) != behind:
                continue
            left = places[(n - 1) % len(self.kids)]
            right = places[(n + 1) % len(self.kids)]
            self._paint_kid(p, self.kids[n], places[n], left, right, ph)

    def _paint_kid(self, p, kid, place, left, right, ph):
        x, feet, s, depth = place
        H = 200 * s
        front = depth > -0.15
        skirt_top, shoulder = feet - H * 0.62, feet - H * 0.64
        # legs, stepping
        step = math.sin(10 * ph + kid["p"]) * H * 0.04
        p.setBrush(QColor("#2b2340"))
        for side, swing in ((-1, step), (1, -step)):
            p.drawRoundedRect(QRectF(x + side * H * 0.06 - H * 0.035 + swing, feet - H * 0.3, H * 0.07, H * 0.3), 6, 6)
            p.setBrush(QColor("#3a2a20"))
            p.drawEllipse(QPointF(x + side * H * 0.06 + swing, feet - H * 0.01), H * 0.055, H * 0.03)
            p.setBrush(QColor("#2b2340"))
        # arms, to the neighbours' hands
        pen = QPen(QColor(kid["coat"]).darker(110), H * 0.06)
        pen.setCapStyle(Qt.RoundCap)
        for other in (left, right):
            if abs(other[0] - x) > self.w * 0.2:
                continue
            hx = (x + other[0]) / 2
            hy = (shoulder + other[1] - 200 * other[2] * 0.64) / 2 + H * 0.08
            p.setPen(pen)
            p.drawLine(QPointF(x, shoulder + H * 0.04), QPointF(hx, hy))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(kid["skin"]))
            p.drawEllipse(QPointF(hx, hy), H * 0.035, H * 0.035)
        # coat or dress
        body = QPainterPath(QPointF(x - H * 0.1, shoulder))
        flare = 0.2 if kid["dress"] else 0.13
        body.lineTo(x + H * 0.1, shoulder)
        body.lineTo(x + H * flare, feet - H * 0.26)
        body.lineTo(x - H * flare, feet - H * 0.26)
        body.closeSubpath()
        g = QLinearGradient(x - H * 0.2, 0, x + H * 0.2, 0)
        g.setColorAt(0.0, QColor(kid["coat"]).lighter(115))
        g.setColorAt(1.0, QColor(kid["coat"]).darker(120))
        p.setBrush(g)
        p.drawPath(body)
        p.setBrush(qc("#ffffff", 220))                    # a fluffy hem
        p.drawRoundedRect(QRectF(x - H * flare, feet - H * 0.28, H * flare * 2, H * 0.04), 4, 4)
        # head
        hr = H * 0.13
        hy = shoulder - hr * 0.95
        p.setBrush(QColor(kid["skin"]))
        p.drawEllipse(QPointF(x, hy), hr, hr)
        p.setBrush(QColor(kid["hair"]))
        if front:
            hair = QPainterPath(QPointF(x - hr, hy))
            hair.arcTo(QRectF(x - hr, hy - hr, hr * 2, hr * 2), 180, -180)
            hair.quadTo(QPointF(x, hy - hr * 0.35), QPointF(x - hr, hy))
            p.drawPath(hair)
            # face: eyes, cheeks, a smile
            p.setBrush(QColor("#2a1a12"))
            for side in (-1, 1):
                p.drawEllipse(QPointF(x + side * hr * 0.38, hy + hr * 0.1), hr * 0.1, hr * 0.13)
            p.setBrush(qc("#ff7a8a", 120))
            for side in (-1, 1):
                p.drawEllipse(QPointF(x + side * hr * 0.58, hy + hr * 0.42), hr * 0.17, hr * 0.11)
            smile = QPen(QColor("#7a2a2a"), max(1.5, hr * 0.08))
            smile.setCapStyle(Qt.RoundCap)
            p.setPen(smile)
            p.setBrush(Qt.NoBrush)
            p.drawArc(QRectF(x - hr * 0.3, hy + hr * 0.15, hr * 0.6, hr * 0.45), 200 * 16, 140 * 16)
            p.setPen(Qt.NoPen)
        else:
            p.drawEllipse(QPointF(x, hy), hr * 1.02, hr * 1.02)
        if kid["hat"]:
            hat = QPainterPath(QPointF(x - hr * 1.05, hy - hr * 0.3))
            hat.quadTo(QPointF(x, hy - hr * 2.0), QPointF(x + hr * 1.05, hy - hr * 0.3))
            hat.closeSubpath()
            p.setBrush(QColor(kid["hat"]))
            p.drawPath(hat)
            p.setBrush(QColor("#ffffff"))
            p.drawRoundedRect(QRectF(x - hr * 1.1, hy - hr * 0.45, hr * 2.2, hr * 0.32), 5, 5)
            p.drawEllipse(QPointF(x, hy - hr * 1.25), hr * 0.25, hr * 0.25)

    # -- the tall screens and the strip ---------------------------------------------------------
    def paint_garland(self, p, t, y, swags, sag):
        """Swags of bulbs across the top, the colours chasing along them."""
        w = self.w
        pen = QPen(qc("#1f7a3a"), 5 if self.screen == "sides" else 3)
        bulbs_per = 9 if self.screen == "sides" else 12
        for s in range(swags):
            x0, x1 = w * s / swags, w * (s + 1) / swags
            depth = self.h * sag
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            path = QPainterPath(QPointF(x0, y))
            path.quadTo(QPointF((x0 + x1) / 2, y + depth * 2), QPointF(x1, y))
            p.drawPath(path)
            p.setPen(Qt.NoPen)
            for b in range(bulbs_per):
                u = (b + 0.5) / bulbs_per
                bx = (1 - u) ** 2 * x0 + 2 * (1 - u) * u * (x0 + x1) / 2 + u * u * x1
                by = (1 - u) ** 2 * y + 2 * (1 - u) * u * (y + depth * 2) + u * u * y
                index = s * bulbs_per + b
                colour = BRIGHT[index % len(BRIGHT)]
                on = 0.3 + 0.7 * (0.5 + 0.5 * math.cos(TAU * index / 6 - TAU * t * 12))
                size = 6 if self.screen == "sides" else 5
                p.setCompositionMode(QPainter.CompositionMode_Plus)
                glow(p, bx, by + size * 1.6, size * 5, colour, 200 * on)
                p.setCompositionMode(QPainter.CompositionMode_SourceOver)
                p.setBrush(qc(colour, 120 + 135 * on))
                p.drawEllipse(QPointF(bx, by + size * 1.6), size, size * 1.35)

    def paint_ornaments(self, p, ph):
        w, h = self.w, self.h
        for o in self.ornaments:
            angle = math.radians(o["a"] * math.sin(o["k"] * ph + o["p"]))
            ax, ay = o["x"] * w, h * 0.06
            length = o["length"] * h
            bx, by = ax + math.sin(angle) * length, ay + math.cos(angle) * length
            p.setPen(QPen(qc("#ffd86b", 200), 2))
            p.drawLine(QPointF(ax, ay), QPointF(bx, by))
            p.setPen(Qt.NoPen)
            r = o["r"]
            if o["star"]:
                star = QPolygonF()
                for k in range(10):
                    a = -TAU / 4 + TAU * k / 10 + angle
                    rr = r * 1.2 if k % 2 == 0 else r * 0.5
                    star.append(QPointF(bx + math.cos(a) * rr, by + r + math.sin(a) * rr))
                p.setCompositionMode(QPainter.CompositionMode_Plus)
                glow(p, bx, by + r, r * 2.4, "#ffd23f", 120)
                p.setCompositionMode(QPainter.CompositionMode_SourceOver)
                p.setBrush(QColor("#ffd23f"))
                p.drawPolygon(star)
                continue
            p.setBrush(QColor("#d9b14a"))
            p.drawRoundedRect(QRectF(bx - r * 0.25, by - 4, r * 0.5, r * 0.3), 3, 3)
            g = QRadialGradient(QPointF(bx - r * 0.35, by + r * 0.65), r * 1.3)
            g.setColorAt(0.0, QColor("#ffffff"))
            g.setColorAt(0.25, QColor(o["c"]).lighter(120))
            g.setColorAt(1.0, QColor(o["c"]).darker(150))
            p.setBrush(g)
            p.drawEllipse(QPointF(bx, by + r), r, r)
            p.setBrush(qc("#ffffff", 90))                 # a band of glitter
            p.drawRect(QRectF(bx - r * 0.95, by + r * 0.9, r * 1.9, r * 0.18))


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
            scene = Scene(screen)
            for i in (0, FRAMES // 3):
                scene.render(i).save(os.path.join(out, f"New Year - {screen} - {i}.png"))
        return 0
    failures = 0
    for screen in screens:
        path = os.path.join(out, f"New Year - {screen}.mp4")
        if os.path.exists(path):
            os.remove(path)
        scene = Scene(screen)
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
