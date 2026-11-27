"""
Render an elegant New Year scene, one seamless loop per screen:
    main   1920 x 1080   (played FIT)     - a tree of light turning slowly, children's silhouettes
                                            dancing round it, golden bokeh, a mirror floor
    sides   512 x 1280   (played STRETCH) - glass baubles on golden threads, bokeh, gold dust
    top    2816 x  128   (played CROP)    - a string of warm lights and a stream of gold dust

Midnight blue and gold, a touch of deep red; light drawn small and sharp, then bloomed.
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
from PySide6.QtGui import (QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPainterPathStroker, QPen,
                           QRadialGradient)
from PySide6.QtWidgets import QApplication

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_light_backgrounds as lights  # noqa: E402 - the encoder and the clip length

FRAMES, TAU = lights.FRAMES, math.tau
SCREENS = {
    "main": (1920, 1080, 24_000_000),
    "sides": (512, 1280, 10_000_000),
    "top": (2816, 128, 10_000_000),
}
WARM = ["#fff3d6", "#ffe2a3", "#ffd27a", "#ffc04d", "#fff8ea"]
GOLD, RED, NIGHT = QColor("#e8b85a"), QColor("#b3122e"), QColor("#040814")


def qc(colour, alpha=255):
    c = QColor(colour)
    c.setAlpha(max(0, min(255, int(alpha))))
    return c


def blank(w, h):
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    return img


def bloom(p, light, w, h, strength=1.0):
    """The glow round every light: the light layer, blurred by shrinking and enlarging, added."""
    p.setCompositionMode(QPainter.CompositionMode_Plus)
    for div, alpha in ((6, 0.9), (18, 0.75), (48, 0.6)):
        small = light.scaled(max(1, w // div), max(1, h // div), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        p.setOpacity(min(1.0, alpha * strength))
        p.drawImage(QRectF(0, 0, w, h), small.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
    p.setOpacity(1.0)
    p.drawImage(0, 0, light)
    p.setCompositionMode(QPainter.CompositionMode_SourceOver)


class Scene:
    def __init__(self, screen, seed=2027):
        self.screen = screen
        self.w, self.h, _ = SCREENS[screen]
        rnd = self.rnd = random.Random(seed)
        self.base = self._paint_base()
        # out-of-focus lights in the room, drifting slowly
        n = {"main": 30, "sides": 22, "top": 34}[screen]
        size = {"main": (18, 70), "sides": (16, 60), "top": (8, 30)}[screen]
        self.bokeh = [dict(u=rnd.random(), v=rnd.random(), r=rnd.uniform(*size), a=rnd.uniform(8, 28),
                           c=rnd.choice(WARM[1:4] + ["#ffb347", "#ff6a5a"] if rnd.random() < 0.15 else WARM[1:4]),
                           kx=rnd.choice([-1, 1]), ky=rnd.choice([1, 2]), p=rnd.uniform(0, TAU),
                           amp=rnd.uniform(0.01, 0.04)) for _ in range(n)]
        # gold dust falling, glinting now and then
        n = {"main": 220, "sides": 110, "top": 160}[screen]
        self.dust = [dict(u=rnd.random(), v=rnd.random(), r=rnd.uniform(0.7, 2.0), loops=rnd.choice([1, 1, 2]),
                          k=rnd.choice([1, 2, 3]), p=rnd.uniform(0, TAU), sway=rnd.uniform(0.003, 0.012),
                          g=rnd.choice([3, 4, 5, 6]), gp=rnd.uniform(0, TAU)) for _ in range(n)]
        getattr(self, "_setup_" + screen)()

    def _paint_base(self):
        w, h = self.w, self.h
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        sky = QLinearGradient(0, 0, 0, h)
        sky.setColorAt(0.0, QColor("#03060f"))
        sky.setColorAt(0.6, QColor("#0a1430"))
        sky.setColorAt(1.0, QColor("#050914"))
        p.fillRect(0, 0, w, h, sky)
        centre = QPointF(w / 2, h * (0.55 if self.screen == "main" else 0.5))
        warm = QRadialGradient(centre, max(w, h) * (0.5 if self.screen == "main" else 0.7))
        warm.setColorAt(0.0, qc("#5a3a12", 150))
        warm.setColorAt(0.5, qc("#2a1a0a", 70))
        warm.setColorAt(1.0, qc("#2a1a0a", 0))
        p.fillRect(0, 0, w, h, warm)
        if self.screen == "main":
            floor = QLinearGradient(0, h * 0.8, 0, h)
            floor.setColorAt(0.0, QColor("#0b0f1e"))
            floor.setColorAt(1.0, QColor("#02040a"))
            p.fillRect(QRectF(0, h * 0.8, w, h * 0.2), floor)
            line = QLinearGradient(0, 0, w, 0)
            for s, a in ((0.0, 0), (0.5, 90), (1.0, 0)):
                line.setColorAt(s, qc("#e8b85a", a))
            p.fillRect(QRectF(0, h * 0.8 - 1, w, 2), line)
        p.end()
        return img

    # -- main: the tree of light --------------------------------------------------------
    def _setup_main(self):
        w, h, rnd = self.w, self.h, self.rnd
        self.cx, self.top, self.bottom = w / 2, h * 0.13, h * 0.79
        self.radius = (self.bottom - self.top) * 0.42
        self.points = []
        for k in range(1700):                          # a spiral of lights, and lights between
            if k < 700:
                hh = (k + 0.5) / 700
                a0 = TAU * 9 * hh
                depth = 1.0
            else:
                hh = rnd.random() ** 0.8
                a0 = rnd.uniform(0, TAU)
                depth = rnd.uniform(0.55, 1.0)
            self.points.append(dict(h=hh, a0=a0, d=depth, c=rnd.choice(WARM), s=rnd.uniform(1.2, 2.6),
                                    k=rnd.choice([2, 3, 4, 5, 6]), p=rnd.uniform(0, TAU)))
        self.balls = [dict(h=rnd.uniform(0.15, 0.95), a0=rnd.uniform(0, TAU),
                           c=GOLD if rnd.random() < 0.65 else RED, r=rnd.uniform(9, 15)) for _ in range(46)]
        self.kids = [dict(a0=TAU * k / 12, tall=rnd.uniform(0.85, 1.05), p=rnd.uniform(0, TAU),
                          dress=k % 2 == 0, hat=rnd.random() < 0.4) for k in range(12)]
        self.bursts = [dict(s=k / 4 + rnd.uniform(0.02, 0.1), x=rnd.choice([rnd.uniform(0.1, 0.28), rnd.uniform(0.72, 0.9)]),
                            y=rnd.uniform(0.12, 0.3), n=rnd.choice([48, 60, 72])) for k in range(4)]

    def _tree_point(self, hh, a0, depth, ph):
        a = a0 + ph                                    # once round per clip
        r = self.radius * hh * depth
        x = self.cx + math.cos(a) * r
        z = math.sin(a) * depth                         # +1 towards us
        y = self.top + hh * (self.bottom - self.top) + z * r * 0.12
        return x, y, z

    def render_main(self, p, t, ph):
        w, h = self.w, self.h
        light = blank(w, h)
        lp = QPainter(light)
        lp.setRenderHint(QPainter.Antialiasing)
        lp.setPen(Qt.NoPen)
        self.paint_fireworks(lp, t)
        # the tree's faint body, so the lights have something to sit on
        body = QPainterPath(QPointF(self.cx, self.top))
        body.lineTo(self.cx + self.radius * 1.02, self.bottom)
        body.quadTo(QPointF(self.cx, self.bottom + self.radius * 0.18), QPointF(self.cx - self.radius * 1.02, self.bottom))
        body.closeSubpath()
        g = QLinearGradient(self.cx - self.radius, 0, self.cx + self.radius, 0)
        g.setColorAt(0.0, qc("#06140e", 40))           # soft at the edges, as needles are
        g.setColorAt(0.3, qc("#0a2217", 170))
        g.setColorAt(0.5, qc("#0e2c1e", 210))
        g.setColorAt(0.7, qc("#0a2217", 170))
        g.setColorAt(1.0, qc("#06140e", 40))
        p.setPen(Qt.NoPen)
        self.paint_kids(p, ph, behind=True)
        p.setBrush(g)
        p.drawPath(body)
        # lights and baubles, far to near
        items = []
        for pt in self.points:
            x, y, z = self._tree_point(pt["h"], pt["a0"], pt["d"], ph)
            items.append((z, "light", x, y, pt))
        for b in self.balls:
            x, y, z = self._tree_point(b["h"], b["a0"], 1.0, ph)
            items.append((z, "ball", x, y, b))
        items.sort(key=lambda item: item[0])
        for z, kind, x, y, it in items:
            near = 0.5 + 0.5 * z                       # 0 behind .. 1 in front
            if kind == "light":
                tw = 0.55 + 0.45 * math.sin(it["k"] * ph + it["p"])
                lp.setBrush(qc(it["c"], (70 + 185 * near) * (0.5 + 0.5 * tw)))
                r = it["s"] * (0.7 + 0.5 * near)
                lp.drawEllipse(QPointF(x, y), r, r)
            else:
                r = it["r"] * (0.75 + 0.35 * near)
                base = QColor(it["c"])
                shade = QRadialGradient(QPointF(x - r * 0.35, y - r * 0.4), r * 1.4)
                shade.setColorAt(0.0, base.lighter(170))
                shade.setColorAt(0.35, base)
                shade.setColorAt(1.0, base.darker(260))
                p.setBrush(shade)
                p.setOpacity(0.35 + 0.65 * near)
                p.drawEllipse(QPointF(x, y), r, r)
                p.setOpacity(1.0)
                lp.setBrush(qc("#fff6e0", 220 * near))             # the highlight that blooms
                lp.drawEllipse(QPointF(x - r * 0.35, y - r * 0.4), r * 0.18, r * 0.18)
        self.paint_star(lp, ph)
        self.paint_dust(lp, t, ph)
        lp.end()
        bloom(p, light, w, h, 1.35)
        self.paint_kids(p, ph, behind=False)
        self.paint_reflection(p, light)

    def paint_star(self, p, ph):
        x, y = self.cx, self.top - 6
        pulse = 0.85 + 0.15 * math.sin(2 * ph)
        p.setBrush(qc("#fff4d6", 255))
        star = QPainterPath()
        for k in range(8):
            a = -TAU / 4 + TAU * k / 8
            r = (34 if k % 2 == 0 else 12) * pulse
            point = QPointF(x + math.cos(a) * r, y + math.sin(a) * r)
            (star.moveTo if k == 0 else star.lineTo)(point)
            mid = -TAU / 4 + TAU * (k + 0.5) / 8
            star.lineTo(QPointF(x + math.cos(mid) * 5, y + math.sin(mid) * 5))
        star.closeSubpath()
        p.drawPath(star)
        # a thin anamorphic streak and a soft core
        for width, alpha in ((420, 70), (220, 140)):
            g = QLinearGradient(x - width, 0, x + width, 0)
            g.setColorAt(0.0, qc("#ffd88a", 0))
            g.setColorAt(0.5, qc("#fff1c8", alpha * pulse))
            g.setColorAt(1.0, qc("#ffd88a", 0))
            p.setBrush(g)
            p.drawRect(QRectF(x - width, y - 1.2, width * 2, 2.4))
        core = QRadialGradient(QPointF(x, y), 60)
        core.setColorAt(0.0, qc("#fff6e0", 200 * pulse))
        core.setColorAt(1.0, qc("#ffd88a", 0))
        p.setBrush(core)
        p.drawEllipse(QPointF(x, y), 60, 60)

    def paint_fireworks(self, p, t):
        """Gold chrysanthemums far off, soft and few."""
        w, h = self.w, self.h
        for b in self.bursts:
            age = (t - b["s"]) % 1.0
            if age > 0.16:
                continue
            k = age / 0.16
            ox, oy = b["x"] * w, b["y"] * h
            spread = 150 * (1 - (1 - k) ** 2.5)
            fade = (1 - k) ** 1.6
            for n in range(b["n"]):
                a = TAU * n / b["n"]
                for trail in range(4):                   # a short trail behind each spark
                    s = spread * (1 - trail * 0.06)
                    x = ox + math.cos(a) * s
                    y = oy + math.sin(a) * s + 70 * k * k
                    p.setBrush(qc("#ffd27a" if n % 3 else "#fff3d6", 200 * fade * (1 - trail * 0.25)))
                    p.drawEllipse(QPointF(x, y), 1.6, 1.6)

    def paint_kids(self, p, ph, behind):
        """Children's silhouettes holding hands round the tree, its light on their edges."""
        places = []
        for kid in self.kids:
            a = kid["a0"] - ph                           # the other way from the tree's turn
            z = math.sin(a)
            x = self.cx + math.cos(a) * self.radius * 1.45
            scale = (0.8 + 0.2 * (z + 1) / 2) * kid["tall"]
            feet = self.bottom + 18 + z * 26 - abs(math.sin(12 * ph + kid["p"])) * 7 * scale
            places.append((x, feet, scale, z))
        for n in sorted(range(len(self.kids)), key=lambda i: places[i][3]):
            x, feet, s, z = places[n]
            if (z < 0) != behind:
                continue
            H = 150 * s
            shape = self._kid_shape(self.kids[n], x, feet, H, places[(n - 1) % len(places)],
                                    places[(n + 1) % len(places)], ph)
            rim = 1 if x < self.cx else -1               # the tree lights the side that faces it
            p.setBrush(qc("#ffcf7a", 150 if z > 0 else 60))
            p.drawPath(shape.translated(rim * 2.2, -1.2))
            p.setBrush(QColor("#03050c") if z > 0 else QColor("#0a0f1e"))
            p.drawPath(shape)

    def _kid_shape(self, kid, x, feet, H, left, right, ph):
        path = QPainterPath()
        path.setFillRule(Qt.WindingFill)
        step = math.sin(12 * ph + kid["p"]) * H * 0.05
        for side, swing in ((-1, step), (1, -step)):     # legs
            path.addRoundedRect(QRectF(x + side * H * 0.055 - H * 0.03 + swing, feet - H * 0.32, H * 0.06, H * 0.32), 4, 4)
        shoulder = feet - H * 0.66
        flare = 0.19 if kid["dress"] else 0.12
        body = QPainterPath(QPointF(x - H * 0.09, shoulder))
        body.lineTo(x + H * 0.09, shoulder)
        body.lineTo(x + H * flare, feet - H * 0.27)
        body.lineTo(x - H * flare, feet - H * 0.27)
        body.closeSubpath()
        path.addPath(body)
        hr = H * 0.12
        path.addEllipse(QPointF(x, shoulder - hr * 0.95), hr, hr)
        if kid["hat"]:
            hat = QPainterPath(QPointF(x - hr * 1.05, shoulder - hr * 1.2))
            hat.quadTo(QPointF(x + hr * 0.2, shoulder - hr * 3.1), QPointF(x + hr * 1.05, shoulder - hr * 1.2))
            hat.closeSubpath()
            path.addPath(hat)
        for other in (left, right):                      # arms to the neighbours' hands
            if abs(other[0] - x) > self.radius * 1.2:
                continue
            hx = (x + other[0]) / 2
            hy = (shoulder + other[1] - 150 * other[2] * 0.66) / 2 + H * 0.1
            arm = QPainterPath(QPointF(x, shoulder + H * 0.03))
            arm.lineTo(hx, hy)
            stroker = QPainterPathStroker()
            stroker.setWidth(H * 0.05)
            stroker.setCapStyle(Qt.RoundCap)
            stroke = stroker.createStroke(arm)
            path.addPath(stroke)
        return path

    def paint_reflection(self, p, light):
        """The tree on the polished floor, faint and fading."""
        w, h = self.w, self.h
        floor = h * 0.8
        band = h - floor
        source = light.copy(0, int(floor - band * 1.6), w, int(band * 1.6)).mirrored(False, True)
        faded = blank(w, int(band))
        fp = QPainter(faded)
        fp.drawImage(QRectF(0, 0, w, band), source)
        fp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        g = QLinearGradient(0, 0, 0, band)
        g.setColorAt(0.0, QColor(0, 0, 0, 120))
        g.setColorAt(1.0, QColor(0, 0, 0, 0))
        fp.fillRect(0, 0, w, int(band), g)
        fp.end()
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        p.drawImage(0, int(floor), faded.scaled(w // 10, max(1, int(band) // 10), Qt.IgnoreAspectRatio,
                                                Qt.SmoothTransformation).scaled(w, int(band), Qt.IgnoreAspectRatio,
                                                                                Qt.SmoothTransformation))
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)

    # -- sides: glass baubles --------------------------------------------------------------
    def _setup_sides(self):
        rnd = self.rnd
        self.baubles = [dict(x=x, length=rnd.uniform(0.14, 0.6), r=rnd.uniform(30, 52), c=c,
                             k=rnd.choice([1, 2]), a=rnd.uniform(3, 7), p=rnd.uniform(0, TAU))
                        for x, c in zip((0.18, 0.42, 0.66, 0.86, 0.3, 0.56, 0.78),
                                        (GOLD, RED, GOLD, QColor("#d8dce6"), GOLD, QColor("#d8dce6"), RED))]

    def render_sides(self, p, t, ph):
        w, h = self.w, self.h
        light = blank(w, h)
        lp = QPainter(light)
        lp.setRenderHint(QPainter.Antialiasing)
        lp.setPen(Qt.NoPen)
        self.paint_lights_string(lp, t, h * 0.035, 3, 0.03)
        for b in sorted(self.baubles, key=lambda b: b["r"]):
            angle = math.radians(b["a"] * math.sin(b["k"] * ph + b["p"]))
            ax, ay = b["x"] * w, 0
            length = b["length"] * h
            bx, by = ax + math.sin(angle) * length, ay + math.cos(angle) * length
            p.setPen(QPen(qc("#c9a25a", 150), 1.2))
            p.drawLine(QPointF(ax, ay), QPointF(bx, by))
            p.setPen(Qt.NoPen)
            r = b["r"]
            cy = by + r
            p.setBrush(QColor("#b89a5a"))
            p.drawRoundedRect(QRectF(bx - r * 0.22, by - 3, r * 0.44, r * 0.26), 3, 3)
            shade = QRadialGradient(QPointF(bx - r * 0.3, cy - r * 0.35), r * 1.5)
            shade.setColorAt(0.0, b["c"].lighter(165))
            shade.setColorAt(0.3, b["c"])
            shade.setColorAt(0.85, b["c"].darker(300))
            shade.setColorAt(1.0, b["c"].darker(200))
            p.setBrush(shade)
            p.drawEllipse(QPointF(bx, cy), r, r)
            rim = QRadialGradient(QPointF(bx, cy), r)            # light caught on the far edge
            rim.setColorAt(0.8, qc("#ffd88a", 0))
            rim.setColorAt(0.97, qc("#ffd88a", 60))
            rim.setColorAt(1.0, qc("#ffd88a", 0))
            p.setBrush(rim)
            p.drawEllipse(QPointF(bx, cy), r, r)
            glint = 0.6 + 0.4 * math.sin(b["k"] * ph + b["p"] + 1)
            lp.setBrush(qc("#fff6e0", 230 * glint))
            lp.drawEllipse(QPointF(bx - r * 0.38, cy - r * 0.42), r * 0.13, r * 0.09)
        self.paint_dust(lp, t, ph)
        lp.end()
        bloom(p, light, w, h, 0.8)

    # -- top: a string of warm lights ---------------------------------------------------------
    def _setup_top(self):
        pass

    def render_top(self, p, t, ph):
        w, h = self.w, self.h
        light = blank(w, h)
        lp = QPainter(light)
        lp.setRenderHint(QPainter.Antialiasing)
        lp.setPen(Qt.NoPen)
        self.paint_lights_string(lp, t, h * 0.18, 14, 0.3)
        # a ribbon of gold dust flowing along the strip
        for k in range(260):
            u = (k * 0.6180339 + 2 * t) % 1.0
            x = u * w
            y = h * (0.6 + 0.18 * math.sin(TAU * 3 * u + ph))
            tw = 0.5 + 0.5 * math.sin(k * 1.7 + ph * 4)
            lp.setBrush(qc(WARM[k % len(WARM)], 160 * tw))
            lp.drawEllipse(QPointF(x, y + (k % 7 - 3) * 2.2), 1.3, 1.3)
        self.paint_dust(lp, t, ph)
        lp.end()
        bloom(p, light, w, h, 1.0)

    # -- shared ---------------------------------------------------------------------------
    def paint_lights_string(self, p, t, y, swags, sag):
        """Warm white bulbs on a fine wire, breathing in a slow wave."""
        w, h = self.w, self.h
        per = 11
        for s in range(swags):
            x0, x1 = w * s / swags, w * (s + 1) / swags
            depth = h * sag
            for b in range(per + 1):
                u = b / per
                bx = (1 - u) ** 2 * x0 + 2 * (1 - u) * u * (x0 + x1) / 2 + u * u * x1
                by = (1 - u) ** 2 * y + 2 * (1 - u) * u * (y + depth * 2) + u * u * y
                index = s * per + b
                level = 0.45 + 0.55 * (0.5 + 0.5 * math.cos(TAU * index / 22 - TAU * t * 4))
                p.setBrush(qc("#fff1cc", 255 * level))
                size = 2.6 if self.screen == "top" else 3.2
                p.drawEllipse(QPointF(bx, by + 3), size, size)

    def paint_bokeh(self, p, ph):
        w, h = self.w, self.h
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        p.setPen(Qt.NoPen)
        for b in self.bokeh:
            x = (b["u"] + b["amp"] * math.sin(b["kx"] * ph + b["p"])) * w
            y = (b["v"] + b["amp"] * 0.6 * math.cos(b["ky"] * ph + b["p"])) * h
            r = b["r"]
            g = QRadialGradient(QPointF(x, y), r)
            g.setColorAt(0.0, qc(b["c"], b["a"] * 0.55))
            g.setColorAt(0.85, qc(b["c"], b["a"] * 0.7))           # a lens's disc: a brighter rim
            g.setColorAt(0.96, qc(b["c"], b["a"]))
            g.setColorAt(1.0, qc(b["c"], 0))
            p.setBrush(g)
            p.drawEllipse(QPointF(x, y), r, r)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)

    def paint_dust(self, p, t, ph):
        for d in self.dust:
            span = self.h + 8
            y = (d["v"] + d["loops"] * t) % 1.0 * span - 4
            x = (d["u"] + d["sway"] * math.sin(d["k"] * ph + d["p"])) * self.w
            glint = max(0.0, math.sin(d["g"] * ph + d["gp"])) ** 8
            p.setBrush(qc("#ffe2a3", 90 + 165 * glint))
            p.drawEllipse(QPointF(x, y), d["r"] * (1 + glint), d["r"] * (1 + glint))

    def render(self, i):
        t = i / FRAMES
        ph = TAU * t
        frame = self.base.copy()
        p = QPainter(frame)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        self.paint_bokeh(p, ph)
        getattr(self, "render_" + self.screen)(p, t, ph)
        vignette = QRadialGradient(QPointF(self.w / 2, self.h / 2), math.hypot(self.w, self.h) / 2)
        vignette.setColorAt(0.6, QColor(0, 0, 0, 0))
        vignette.setColorAt(1.0, QColor(0, 0, 0, 150 if self.screen != "top" else 60))
        p.fillRect(0, 0, self.w, self.h, vignette)
        p.end()
        return frame


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
        path = os.path.join(out, f"New Year Gold - {screen}.mp4")
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
