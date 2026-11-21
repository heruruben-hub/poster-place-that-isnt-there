#!/usr/bin/env python3
"""VELLMERE — a travel poster for a place that isn't there.

Draws a 1024x1024 travel poster for Vellmere, a white cliff town with
lantern stairs above a turquoise lagoon at golden hour, crowned by a tall
lighthouse-observatory. Pure Python 3 stdlib, no network, deterministic.

Writes /output/entry.png when /output exists, otherwise entry.png next
to this file.
"""

import math
import os
import struct
import sys
import zlib

W = 1024
H = 1024

# ---------------------------------------------------------------- canvas

class Canvas:
    def __init__(self, w, h):
        self.w = w
        self.h = h
        self.px = bytearray(w * h * 3)

    def _idx(self, x, y):
        return (y * self.w + x) * 3

    def set(self, x, y, rgb):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = self._idx(x, y)
            self.px[i] = rgb[0]
            self.px[i + 1] = rgb[1]
            self.px[i + 2] = rgb[2]

    def blend(self, x, y, rgb, alpha):
        """Blend rgb over the pixel with alpha 0..255."""
        if alpha <= 0 or not (0 <= x < self.w and 0 <= y < self.h):
            return
        if alpha >= 255:
            self.set(x, y, rgb)
            return
        i = self._idx(x, y)
        a = alpha
        ia = 255 - a
        self.px[i] = (rgb[0] * a + self.px[i] * ia) // 255
        self.px[i + 1] = (rgb[1] * a + self.px[i + 1] * ia) // 255
        self.px[i + 2] = (rgb[2] * a + self.px[i + 2] * ia) // 255

    def fill_rect(self, x0, y0, x1, y1, rgb):
        x0 = max(0, x0)
        y0 = max(0, y0)
        x1 = min(self.w, x1)
        y1 = min(self.h, y1)
        if x1 <= x0 or y1 <= y0:
            return
        row = bytes(rgb) * (x1 - x0)
        for y in range(y0, y1):
            i = self._idx(x0, y)
            self.px[i:i + len(row)] = row

    def blend_rect(self, x0, y0, x1, y1, rgb, alpha):
        x0 = max(0, x0)
        y0 = max(0, y0)
        x1 = min(self.w, x1)
        y1 = min(self.h, y1)
        for y in range(y0, y1):
            for x in range(x0, x1):
                self.blend(x, y, rgb, alpha)

    def vgrad(self, y0, y1, top, bottom):
        """Vertical linear gradient between two rgb colours."""
        y0 = max(0, y0)
        y1 = min(self.h, y1)
        span = max(1, y1 - y0)
        for y in range(y0, y1):
            t = (y - y0) / span
            c = tuple(int(top[k] + (bottom[k] - top[k]) * t) for k in range(3))
            self.fill_rect(0, y, self.w, y + 1, c)

    def hline(self, x0, x1, y, rgb, alpha=255):
        if not (0 <= y < self.h):
            return
        x0 = max(0, x0)
        x1 = min(self.w - 1, x1)
        if x1 < x0:
            return
        if alpha >= 255:
            i = self._idx(x0, y)
            self.px[i:i + (x1 - x0 + 1) * 3] = bytes(rgb) * (x1 - x0 + 1)
        else:
            for x in range(x0, x1 + 1):
                self.blend(x, y, rgb, alpha)

    def circle(self, cx, cy, r, rgb, alpha=255):
        if r <= 0:
            return
        r2 = r * r
        for dy in range(-r, r + 1):
            y = cy + dy
            if not (0 <= y < self.h):
                continue
            dx = int(math.sqrt(max(0, r2 - dy * dy)))
            self.hline(cx - dx, cx + dx, y, rgb, alpha)

    def ring(self, cx, cy, r0, r1, rgb, alpha=255):
        if r1 <= r0:
            return
        for dy in range(-r1, r1 + 1):
            y = cy + dy
            if not (0 <= y < self.h):
                continue
            d1 = int(math.sqrt(max(0, r1 * r1 - dy * dy)))
            d0 = int(math.sqrt(max(0, r0 * r0 - dy * dy))) if abs(dy) < r0 else 0
            self.hline(cx - d1, cx - d0, y, rgb, alpha)
            self.hline(cx + d0, cx + d1, y, rgb, alpha)

    def polygon(self, pts, rgb, alpha=255):
        """Scanline fill of a simple polygon."""
        if len(pts) < 3:
            return
        ys = [p[1] for p in pts]
        ymin = max(0, min(ys))
        ymax = min(self.h - 1, max(ys))
        n = len(pts)
        for y in range(ymin, ymax + 1):
            xs = []
            for i in range(n):
                x0, y0 = pts[i]
                x1, y1 = pts[(i + 1) % n]
                if y0 == y1:
                    continue
                if (y0 <= y < y1) or (y1 <= y < y0):
                    t = (y - y0) / (y1 - y0)
                    xs.append(x0 + t * (x1 - x0))
            xs.sort()
            for j in range(0, len(xs) - 1, 2):
                self.hline(int(math.ceil(xs[j])), int(math.floor(xs[j + 1])), y, rgb, alpha)

    def thick_line(self, x0, y0, x1, y1, w, rgb, alpha=255):
        """A line drawn as a chain of filled circles."""
        dx = x1 - x0
        dy = y1 - y0
        steps = max(abs(dx), abs(dy), 1)
        r = max(1, w // 2)
        for s in range(steps + 1):
            t = s / steps
            self.circle(int(x0 + dx * t), int(y0 + dy * t), r, rgb, alpha)

    def line(self, x0, y0, x1, y1, rgb, alpha=255):
        self.thick_line(x0, y0, x1, y1, 1, rgb, alpha)


def lerp(a, b, t):
    return tuple(int(a[k] + (b[k] - a[k]) * t) for k in range(3))


# ---------------------------------------------------------------- 5x7 font
# Each glyph: 7 rows of 5 bits, top to bottom.

FONT = {
    'A': ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    'B': ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    'C': ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    'D': ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    'E': ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    'F': ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    'G': ("01110", "10001", "10000", "10111", "10001", "10001", "01111"),
    'H': ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    'I': ("01110", "00100", "00100", "00100", "00100", "00100", "01110"),
    'J': ("00111", "00010", "00010", "00010", "00010", "10010", "01100"),
    'K': ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    'L': ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    'M': ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    'N': ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    'O': ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    'P': ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    'Q': ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    'R': ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    'S': ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    'T': ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    'U': ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    'V': ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    'W': ("10001", "10001", "10001", "10101", "10101", "11011", "10001"),
    'X': ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    'Y': ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    'Z': ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    '0': ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    '1': ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    '2': ("01110", "10001", "00001", "00110", "01000", "10000", "11111"),
    '3': ("11111", "00010", "00100", "00010", "00001", "10001", "01110"),
    '4': ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    '5': ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    '6': ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    '7': ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    '8': ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    '9': ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
    ' ': ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
    '-': ("00000", "00000", "00000", "01110", "00000", "00000", "00000"),
    '.': ("00000", "00000", "00000", "00000", "00000", "01100", "01100"),
    ',': ("00000", "00000", "00000", "00000", "01100", "00100", "01000"),
    "'": ("00100", "00100", "01000", "00000", "00000", "00000", "00000"),
    '!': ("00100", "00100", "00100", "00100", "00100", "00000", "00100"),
    ':': ("00000", "01100", "01100", "00000", "01100", "01100", "00000"),
    '\u2022': ("00000", "00100", "01110", "01110", "01110", "00100", "00000"),
}

BLANK = ("00000", "00000", "00000", "00000", "00000", "00000", "00000")


def text_width(text, scale, spacing=1):
    return len(text) * (5 + spacing) * scale - spacing * scale


def draw_text(cv, text, x, y, scale, rgb, spacing=1, alpha=255):
    """Draw text with the top-left corner at (x, y)."""
    cx = x
    for ch in text.upper():
        glyph = FONT.get(ch, BLANK)
        for r, row in enumerate(glyph):
            for c, bit in enumerate(row):
                if bit == '1':
                    cv.blend_rect(cx + c * scale, y + r * scale,
                                  cx + (c + 1) * scale, y + (r + 1) * scale,
                                  rgb, alpha)
        cx += (5 + spacing) * scale
    return cx


def draw_text_centered(cv, text, cy, scale, rgb, shadow=None, spacing=1, alpha=255):
    w = text_width(text, scale, spacing)
    x = (W - w) // 2
    y = cy - (7 * scale) // 2
    if shadow is not None:
        draw_text(cv, text, x + max(2, scale // 3), y + max(3, scale // 2),
                  scale, shadow, spacing, alpha)
    draw_text(cv, text, x, y, scale, rgb, spacing, alpha)
    return y


# ---------------------------------------------------------------- helpers

def sun_glow(cv, cx, cy):
    """Layered translucent halo around the sun."""
    for r, a in ((150, 22), (120, 30), (96, 44), (78, 70)):
        cv.circle(cx, cy, r, (255, 214, 140), a)


def draw_bird(cv, x, y, s, rgb):
    cv.thick_line(x - s, y, x, y - s // 2, 2, rgb)
    cv.thick_line(x, y - s // 2, x + s, y, 2, rgb)


def draw_cloud(cv, x, y, w, h, rgb, alpha=255):
    """A flat, soft cloud: a rounded bar in one solid pastel tone."""
    cv.fill_rect(x + h // 2, y, x + w - h // 2, y + h, rgb)
    cv.circle(x + h // 2, y + h // 2, h // 2, rgb)
    cv.circle(x + w - h // 2, y + h // 2, h // 2, rgb)
    cv.circle(x + w // 3, y + h // 4, h // 3, rgb)
    cv.circle(x + 2 * w // 3, y + h // 4, h // 3, rgb)


def draw_building(cv, x, y, w, h, body, roof, lit):
    """A whitewashed house with a terracotta roof and lit windows."""
    # body
    cv.fill_rect(x, y, x + w, y + h, body)
    # roof: shallow trapezoid
    over = max(2, w // 10)
    cv.polygon([(x - over, y), (x + w + over, y),
                (x + w - max(3, w // 5), y - max(6, h // 5)),
                (x + max(3, w // 5), y - max(6, h // 5))], roof)
    # windows, warm lit
    win = max(4, w // 6)
    gap = max(5, w // 8)
    wy = y + max(5, h // 5)
    wx = x + gap
    while wx + win <= x + w - 2:
        cv.fill_rect(wx, wy, wx + win, wy + win + 2, lit)
        wx += win + gap
    # door arch on the ground floor
    dw = max(5, w // 5)
    dh = max(8, h // 3)
    dx = x + (w - dw) // 2
    cv.fill_rect(dx, y + h - dh, dx + dw, y + h, (96, 58, 40))
    cv.circle(dx + dw // 2, y + h - dh, dw // 2, (96, 58, 40))


def draw_sailboat(cv, x, y, s, hull, sail_a, sail_b):
    """Small sailboat, hull at waterline y, size s."""
    mast_h = int(s * 1.9)
    # reflection
    for i in range(3):
        cv.hline(x - s // 2 + i * 3, x + s // 2 - i * 3, y + 6 + i * 5,
                 (255, 240, 200), 60 - i * 16)
    # sails
    cv.polygon([(x, y - mast_h), (x, y - 4), (x + int(s * 0.62), y - 4)], sail_a)
    cv.polygon([(x - 2, y - mast_h + 4), (x - 2, y - 4),
                (x - int(s * 0.5), y - 4)], sail_b)
    # mast
    cv.thick_line(x, y - mast_h, x, y - 2, 2, (70, 45, 30))
    # hull
    cv.polygon([(x - s // 2, y), (x + s // 2, y),
                (x + s // 3, y + s // 4), (x - s // 3, y + s // 4)], hull)


# ---------------------------------------------------------------- poster

def build():
    cv = Canvas(W, H)

    NAVY = (26, 38, 74)
    CREAM = (255, 244, 214)
    GOLD = (255, 196, 110)
    INK = (30, 32, 56)

    # ---- sky: dusty violet at the top melting into golden hour ----
    cv.vgrad(0, 300, (88, 94, 158), (214, 138, 122))
    cv.vgrad(300, 620, (214, 138, 122), (255, 198, 118))

    # ---- sun, low and warm, over the lagoon on the right ----
    SX, SY = 772, 430
    sun_glow(cv, SX, SY)
    cv.circle(SX, SY, 62, (255, 238, 190))
    cv.circle(SX, SY, 52, (255, 224, 158))

    # ---- soft clouds catching the light ----
    draw_cloud(cv, 60, 300, 220, 26, (255, 208, 176))
    draw_cloud(cv, 620, 250, 260, 30, (255, 200, 164))
    draw_cloud(cv, 870, 168, 130, 18, (242, 176, 176))
    draw_cloud(cv, 850, 330, 150, 20, (255, 212, 178))

    # ---- birds ----
    for bx, by, bs in ((660, 210, 12), (700, 232, 9), (620, 246, 8),
                       (880, 250, 10), (920, 272, 8)):
        draw_bird(cv, bx, by, bs, (58, 52, 96))

    # ---- distant headland on the far right horizon ----
    cv.polygon([(1024, 560), (1024, 622), (880, 622), (930, 585),
                (985, 568)], (146, 96, 110))

    # ---- lagoon: turquoise at the horizon, deep teal below ----
    cv.vgrad(600, 1024, (72, 196, 184), (14, 96, 118))
    # horizon shimmer
    cv.hline(0, W - 1, 600, (255, 226, 160), 110)
    cv.hline(0, W - 1, 601, (255, 226, 160), 70)

    # ---- sun glitter on the water ----
    seed = 1234567

    def rnd():
        nonlocal seed
        seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
        return seed

    for row in range(610, 980, 9):
        t = (row - 600) / 424.0
        cx = int(SX + (SX - 512) * t * 0.25)
        spread = int(30 + t * 130)
        for _ in range(7):
            off = rnd() % (spread * 2) - spread
            ln = 8 + rnd() % 26
            a = 150 - int(t * 90)
            cv.hline(cx + off - ln // 2, cx + off + ln // 2, row,
                     (255, 232, 170), max(28, a))

    # ---- gentle wave strokes ----
    for row in range(640, 1010, 26):
        t = (row - 600) / 424.0
        for k in range(5):
            x0 = (k * 211 + int(t * 90)) % 1024
            ln = 40 + (k * 37) % 60
            cv.hline(x0, min(1023, x0 + ln), row,
                     (150, 225, 215), 46)

    # ---- the cliff: a great ochre headland rising from the lagoon ----
    # cliff face, darker toward the water
    cliff_top = [(0, 470), (120, 420), (250, 380), (360, 400),
                 (470, 470), (560, 560), (620, 640), (560, 700),
                 (380, 730), (180, 720), (0, 660)]
    # vertical gradient baked into the polygon via horizontal bands
    for y in range(380, 731):
        t = (y - 380) / 350.0
        c = lerp((214, 146, 96), (128, 74, 52), t)
        xs = []
        n = len(cliff_top)
        for i in range(n):
            x0, y0 = cliff_top[i]
            x1, y1 = cliff_top[(i + 1) % n]
            if y0 == y1:
                continue
            if (y0 <= y < y1) or (y1 <= y < y0):
                xs.append(x0 + (y - y0) / (y1 - y0) * (x1 - x0))
        xs.sort()
        for j in range(0, len(xs) - 1, 2):
            cv.hline(int(xs[j]), int(xs[j + 1]), y, c)
    # sunlit rim along the cliff top edge
    rim = [(0, 470), (120, 420), (250, 380), (360, 400), (470, 470),
           (560, 560), (620, 640)]
    for i in range(len(rim) - 1):
        cv.thick_line(rim[i][0], rim[i][1], rim[i + 1][0], rim[i + 1][1],
                      4, (255, 214, 150), 200)
    # a few shadow cracks
    for x0, y0, x1, y1 in ((150, 470, 190, 560), (300, 430, 330, 540),
                           (430, 500, 470, 610), (90, 520, 130, 620)):
        cv.thick_line(x0, y0, x1, y1, 3, (110, 62, 44), 90)

    # ---- terrace bands across the cliff face ----
    def cliff_span(y):
        xs = []
        n = len(cliff_top)
        for i in range(n):
            x0, y0 = cliff_top[i]
            x1, y1 = cliff_top[(i + 1) % n]
            if y0 == y1:
                continue
            if (y0 <= y < y1) or (y1 <= y < y0):
                xs.append(x0 + (y - y0) / (y1 - y0) * (x1 - x0))
        xs.sort()
        return (int(xs[0]), int(xs[-1])) if len(xs) >= 2 else None

    for band_y in (505, 585):
        span = cliff_span(band_y)
        if span:
            cv.hline(span[0], span[1], band_y, (110, 62, 44), 70)
            cv.hline(span[0], span[1], band_y + 3, (255, 214, 150), 46)
    # foam where the cliff meets the lagoon
    base = [(0, 660), (180, 720), (380, 730), (560, 700), (620, 640)]
    for i in range(len(base) - 1):
        cv.thick_line(base[i][0], base[i][1] + 4, base[i + 1][0],
                      base[i + 1][1] + 4, 3, (190, 240, 225), 110)

    # ---- the lighthouse-observatory: the town's landmark ----
    # tower stands on the highest point of the cliff
    TX = 255
    cv.polygon([(TX - 26, 430), (TX + 26, 430), (TX + 16, 312),
                (TX - 16, 312)], (250, 240, 214))
    cv.polygon([(TX - 26, 430), (TX - 6, 430), (TX - 11, 312),
                (TX - 16, 312)], (228, 208, 176))
    # gallery ring
    cv.fill_rect(TX - 30, 305, TX + 30, 315, (52, 44, 66))
    # lantern room, glowing
    cv.circle(TX, 291, 26, (255, 214, 130), 60)
    cv.fill_rect(TX - 17, 273, TX + 17, 307, (255, 226, 150))
    cv.fill_rect(TX - 17, 273, TX + 17, 279, (52, 44, 66))
    cv.fill_rect(TX - 19, 307, TX + 19, 311, (52, 44, 66))
    # dome
    cv.polygon([(TX - 20, 273), (TX + 20, 273), (TX, 249)], (196, 84, 70))
    cv.circle(TX, 247, 4, (255, 226, 150))
    # light beam sweeping out to sea
    cv.polygon([(TX + 8, 291), (1024, 400), (1024, 490), (TX + 8, 301)],
               (255, 240, 190), 38)
    # tower windows, lit
    for wy in (350, 385, 415):
        cv.fill_rect(TX - 5, wy, TX + 5, wy + 12, (255, 200, 110))

    # ---- the white town cascading down the cliff ----
    BODY = (250, 242, 224)
    BODY2 = (240, 226, 200)
    ROOF = (198, 96, 62)
    ROOF2 = (178, 80, 54)
    LIT = (255, 206, 120)
    # upper terrace
    draw_building(cv, 60, 430, 62, 52, BODY, ROOF, LIT)
    draw_building(cv, 138, 448, 54, 44, BODY2, ROOF2, LIT)
    draw_building(cv, 310, 428, 66, 56, BODY, ROOF, LIT)
    draw_building(cv, 392, 452, 52, 42, BODY2, ROOF2, LIT)
    # mid terrace
    draw_building(cv, 30, 520, 70, 56, BODY, ROOF, LIT)
    draw_building(cv, 116, 540, 58, 46, BODY2, ROOF2, LIT)
    draw_building(cv, 190, 528, 64, 52, BODY, ROOF, LIT)
    draw_building(cv, 268, 556, 56, 44, BODY2, ROOF2, LIT)
    draw_building(cv, 340, 548, 60, 46, BODY, ROOF, LIT)
    draw_building(cv, 416, 566, 54, 42, BODY2, ROOF2, LIT)
    # lower terrace, near the water
    draw_building(cv, 60, 620, 66, 52, BODY, ROOF, LIT)
    draw_building(cv, 140, 636, 56, 44, BODY2, ROOF2, LIT)
    draw_building(cv, 210, 626, 60, 48, BODY, ROOF, LIT)
    draw_building(cv, 290, 648, 52, 40, BODY2, ROOF2, LIT)

    # ---- lantern stairs zig-zagging down to the pier ----
    stairs = [(330, 500), (300, 540), (340, 570), (310, 610),
              (350, 640), (330, 672), (380, 690)]
    for i in range(len(stairs) - 1):
        cv.thick_line(stairs[i][0], stairs[i][1],
                      stairs[i + 1][0], stairs[i + 1][1],
                      3, (240, 214, 170), 220)
    for i in range(len(stairs) - 1):
        x0, y0 = stairs[i]
        x1, y1 = stairs[i + 1]
        steps = max(abs(x1 - x0), abs(y1 - y0)) // 16
        for s in range(steps + 1):
            t = s / max(1, steps)
            lx = int(x0 + (x1 - x0) * t)
            ly = int(y0 + (y1 - y0) * t)
            cv.circle(lx, ly, 7, (255, 200, 100), 60)
            cv.circle(lx, ly, 3, (255, 220, 140))

    # ---- little pier at the waterline ----
    cv.fill_rect(380, 688, 470, 698, (120, 84, 52))
    cv.fill_rect(392, 698, 398, 716, (96, 66, 40))
    cv.fill_rect(452, 698, 458, 716, (96, 66, 40))
    cv.circle(425, 690, 4, (255, 220, 140))
    cv.circle(425, 690, 8, (255, 200, 100), 50)

    # ---- sailboats on the lagoon ----
    draw_sailboat(cv, 700, 760, 46, (44, 52, 78), CREAM, (232, 120, 84))
    draw_sailboat(cv, 860, 830, 34, (52, 48, 70), (255, 244, 214), (214, 140, 110))
    draw_sailboat(cv, 580, 880, 28, (44, 52, 78), (255, 244, 214), (240, 180, 120))
    draw_sailboat(cv, 320, 930, 30, (44, 52, 78), (255, 244, 214), (232, 120, 84))

    # ---- title: VELLMERE, big and warm, set into the sky ----
    # soft dark panel is not used: the sky behind the title is deep
    # violet, so cream type with a navy shadow reads cleanly.
    draw_text_centered(cv, "VELLMERE", 100, 17, CREAM, shadow=NAVY)
    # thin gold rule under the title
    tw = text_width("VELLMERE", 17)
    x0 = (W - tw) // 2
    cv.fill_rect(x0 + 40, 178, x0 + tw - 40, 182, GOLD)
    # one short tagline
    draw_text_centered(cv, "THE TOWN ABOVE THE TURQUOISE SEA", 210, 4,
                       (255, 238, 200), shadow=(40, 36, 70))

    # ---- poster frame ----
    cv.fill_rect(0, 0, W, 10, NAVY)
    cv.fill_rect(0, H - 10, W, H, NAVY)
    cv.fill_rect(0, 0, 10, H, NAVY)
    cv.fill_rect(W - 10, 0, W, H, NAVY)
    cv.fill_rect(14, 14, W - 14, 16, GOLD)
    cv.fill_rect(14, H - 16, W - 14, H - 14, GOLD)
    cv.fill_rect(14, 14, 16, H - 14, GOLD)
    cv.fill_rect(W - 16, 14, W - 14, H - 14, GOLD)

    return cv


# ---------------------------------------------------------------- PNG

def _chunk(kind, data):
    c = struct.pack(">I", len(data)) + kind + data
    c += struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return c


def write_png(cv, path):
    raw = bytearray()
    w = cv.w
    for y in range(cv.h):
        raw.append(0)  # filter: none
        i = y * w * 3
        raw += cv.px[i:i + w * 3]
    ihdr = struct.pack(">IIBBBBB", w, cv.h, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n"
    png += _chunk(b"IHDR", ihdr)
    png += _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += _chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)
    return len(png)


def main():
    cv = build()
    if os.path.isdir("/output"):
        out = "/output/entry.png"
    else:
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "entry.png")
    size = write_png(cv, out)
    print(f"wrote {out}: {W}x{H}, {size} bytes")
    if size > 1048576:
        print("WARNING: over the 1 MiB limit", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
