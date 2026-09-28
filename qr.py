"""
QR codes for the phone links, with no extra packages.

A small byte-mode encoder after Project Nayuki's reference design (MIT):
error correction level M, the smallest version that fits, and the mask with
the lowest penalty. Enough for a URL; rendered straight to a QImage.
"""

from __future__ import annotations

from typing import List

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter

# Level M: error correction codewords per block, and the number of blocks, by version.
_ECC_PER_BLOCK = (-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26,
                  26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28)
_BLOCKS = (-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16,
           17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49)
_FORMAT_BITS_M = 0   # level M is 00 in the format information


def _raw_modules(version: int) -> int:
    result = (16 * version + 128) * version + 64
    if version >= 2:
        count = version // 7 + 2
        result -= (25 * count - 10) * count - 55
        if version >= 7:
            result -= 36
    return result


def _data_codewords(version: int) -> int:
    return _raw_modules(version) // 8 - _ECC_PER_BLOCK[version] * _BLOCKS[version]


def _gf_multiply(x: int, y: int) -> int:
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z & 0xFF


def _rs_divisor(degree: int) -> List[int]:
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_multiply(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_multiply(root, 0x02)
    return result


def _rs_remainder(data: List[int], divisor: List[int]) -> List[int]:
    result = [0] * len(divisor)
    for byte in data:
        factor = byte ^ result.pop(0)
        result.append(0)
        for i, coefficient in enumerate(divisor):
            result[i] ^= _gf_multiply(coefficient, factor)
    return result


def _alignment_positions(version: int) -> List[int]:
    if version == 1:
        return []
    count = version // 7 + 2
    step = 26 if version == 32 else (version * 4 + count * 2 + 1) // (count * 2 - 2) * 2
    result = [version * 4 + 10 - i * step for i in range(count - 1)]
    return [6] + list(reversed(result))


class QrCode:
    """A finished symbol: `size` x `size` modules, `module(x, y)` is True for dark."""

    def __init__(self, text: str) -> None:
        payload = text.encode("utf-8")
        for version in range(1, 41):
            capacity = _data_codewords(version) * 8
            used = 4 + (8 if version < 10 else 16) + len(payload) * 8
            if used <= capacity:
                break
        else:
            raise ValueError("Too long for a QR code")
        self.version = version
        self.size = version * 4 + 17
        self._dark = [[False] * self.size for _ in range(self.size)]
        self._fixed = [[False] * self.size for _ in range(self.size)]

        # data bits: byte mode, length, bytes, terminator, padding
        bits: List[int] = []

        def put(value: int, length: int) -> None:
            bits.extend((value >> i) & 1 for i in reversed(range(length)))

        put(0b0100, 4)
        put(len(payload), 8 if version < 10 else 16)
        for byte in payload:
            put(byte, 8)
        capacity = _data_codewords(version) * 8
        put(0, min(4, capacity - len(bits)))
        put(0, (-len(bits)) % 8)
        pad = 0xEC
        while len(bits) < capacity:
            put(pad, 8)
            pad ^= 0xEC ^ 0x11
        data = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]

        self._draw_function_patterns()
        self._draw_codewords(self._interleave(data))
        best, best_penalty = 0, None
        for mask in range(8):
            self._apply_mask(mask)
            self._draw_format(mask)
            penalty = self._penalty()
            if best_penalty is None or penalty < best_penalty:
                best, best_penalty = mask, penalty
            self._apply_mask(mask)          # XOR again: undo
        self._apply_mask(best)
        self._draw_format(best)

    def module(self, x: int, y: int) -> bool:
        return 0 <= x < self.size and 0 <= y < self.size and self._dark[y][x]

    # -- building ------------------------------------------------------------ #
    def _set(self, x: int, y: int, dark: bool) -> None:
        self._dark[y][x] = dark
        self._fixed[y][x] = True

    def _draw_function_patterns(self) -> None:
        size = self.size
        for i in range(size):
            self._set(6, i, i % 2 == 0)
            self._set(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < size and 0 <= y < size:
                        distance = max(abs(dx), abs(dy))
                        self._set(x, y, distance not in (2, 4))
        positions = _alignment_positions(self.version)
        last = len(positions) - 1
        for i, ax in enumerate(positions):
            for j, ay in enumerate(positions):
                if (i, j) in ((0, 0), (0, last), (last, 0)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self._set(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)
        self._draw_format(0)                # reserve the area; redrawn per mask
        if self.version >= 7:
            remainder = self.version
            for _ in range(12):
                remainder = (remainder << 1) ^ ((remainder >> 11) * 0x1F25)
            value = self.version << 12 | remainder
            for i in range(18):
                bit = (value >> i) & 1 == 1
                a, b = size - 11 + i % 3, i // 3
                self._set(a, b, bit)
                self._set(b, a, bit)

    def _draw_format(self, mask: int) -> None:
        data = _FORMAT_BITS_M << 3 | mask
        remainder = data
        for _ in range(10):
            remainder = (remainder << 1) ^ ((remainder >> 9) * 0x537)
        value = (data << 10 | remainder) ^ 0x5412
        size = self.size
        bit = lambda i: (value >> i) & 1 == 1  # noqa: E731
        for i in range(6):
            self._set(8, i, bit(i))
        self._set(8, 7, bit(6))
        self._set(8, 8, bit(7))
        self._set(7, 8, bit(8))
        for i in range(9, 15):
            self._set(14 - i, 8, bit(i))
        for i in range(8):
            self._set(size - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self._set(8, size - 15 + i, bit(i))
        self._set(8, size - 8, True)        # the dark module

    def _interleave(self, data: List[int]) -> List[int]:
        version = self.version
        blocks_total = _BLOCKS[version]
        ecc_length = _ECC_PER_BLOCK[version]
        raw = _raw_modules(version) // 8
        short_count = blocks_total - raw % blocks_total
        short_length = raw // blocks_total
        divisor = _rs_divisor(ecc_length)
        blocks = []
        k = 0
        for i in range(blocks_total):
            length = short_length - ecc_length + (0 if i < short_count else 1)
            chunk = data[k:k + length]
            k += length
            ecc = _rs_remainder(chunk, divisor)
            if i < short_count:
                chunk = chunk + [0]
            blocks.append(chunk + ecc)
        result = []
        for i in range(len(blocks[0])):
            for j, block in enumerate(blocks):
                if i != short_length - ecc_length or j >= short_count:
                    result.append(block[i])
        return result

    def _draw_codewords(self, codewords: List[int]) -> None:
        size = self.size
        i = 0
        total = len(codewords) * 8
        right = size - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vertical in range(size):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = size - 1 - vertical if upward else vertical
                    if not self._fixed[y][x] and i < total:
                        self._dark[y][x] = (codewords[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def _apply_mask(self, mask: int) -> None:
        tests = (
            lambda x, y: (x + y) % 2 == 0,
            lambda x, y: y % 2 == 0,
            lambda x, y: x % 3 == 0,
            lambda x, y: (x + y) % 3 == 0,
            lambda x, y: (x // 3 + y // 2) % 2 == 0,
            lambda x, y: x * y % 2 + x * y % 3 == 0,
            lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
            lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
        )
        test = tests[mask]
        for y in range(self.size):
            for x in range(self.size):
                if not self._fixed[y][x] and test(x, y):
                    self._dark[y][x] = not self._dark[y][x]

    def _penalty(self) -> int:
        size = self.size
        grid = self._dark
        result = 0
        lines = [row for row in grid] + [[grid[y][x] for y in range(size)] for x in range(size)]
        finder_a = [True, False, True, True, True, False, True, False, False, False, False]
        finder_b = list(reversed(finder_a))
        for line in lines:
            run, previous = 0, None
            for value in line:
                if value == previous:
                    run += 1
                else:
                    if run >= 5:
                        result += run - 2
                    run, previous = 1, value
            if run >= 5:
                result += run - 2
            padded = [False] * 4 + line + [False] * 4
            for i in range(len(padded) - 10):
                window = padded[i:i + 11]
                if window == finder_a or window == finder_b:
                    result += 40
        for y in range(size - 1):
            for x in range(size - 1):
                colour = grid[y][x]
                if colour == grid[y][x + 1] == grid[y + 1][x] == grid[y + 1][x + 1]:
                    result += 3
        dark = sum(sum(row) for row in grid)
        total = size * size
        k = (abs(dark * 20 - total * 10) + total - 1) // total - 1
        result += max(0, k) * 10
        return result


def qr_image(text: str, pixels: int = 360, dark: str = "#000000", light: str = "#ffffff") -> QImage:
    """The code for `text` as a square picture, with the quiet zone scanners need."""
    code = QrCode(text)
    border = 4
    cells = code.size + border * 2
    scale = max(1, pixels // cells)
    side = cells * scale
    image = QImage(side, side, QImage.Format_RGB32)
    image.fill(QColor(light))
    painter = QPainter(image)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(dark))
    for y in range(code.size):
        for x in range(code.size):
            if code.module(x, y):
                painter.drawRect(QRect((x + border) * scale, (y + border) * scale, scale, scale))
    painter.end()
    return image
