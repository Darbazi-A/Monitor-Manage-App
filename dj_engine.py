"""
The sound side of the DJ desk: decoding, analysis, two decks, a mixer and a
techno machine.

Nothing here draws anything. The engine lives on its own QThread and pushes
16-bit PCM into a QAudioSink, so a busy dashboard never starves the speakers.
All DSP is numpy on 512-frame blocks; the one piece that has to run sample by
sample (the acid bass filter) is rendered a bar at a time on a helper thread.
"""
from __future__ import annotations

import collections
import math
import os
import random
import threading
import wave
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
from PySide6.QtCore import QObject, QThread, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtMultimedia import (QAudio, QAudioDecoder, QAudioFormat, QAudioSink,
                                  QMediaDevices)

BLOCK = 512                 # frames rendered per step of the engine
HOP = 256                   # spectral EQ hop; BLOCK must be a multiple of it
FFT = 1024                  # spectral EQ / analysis frame
LATENCY = 0.075             # seconds queued in the sound card
DETAIL_FPS = 100            # scrolling-waveform columns per second of audio
DETAIL_H = 72               # scrolling-waveform height in pixels
OVERVIEW_BINS = 1200        # whole-track waveform resolution

AUDIO_EXTENSIONS = (".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".oga", ".opus",
                    ".wma", ".aif", ".aiff")

# ARGB colours of the three waveform bands (low / mid / high).
BAND_ARGB = (0xFF2F6BFF, 0xFFE3B23C, 0xFFF2F4F8)


def is_audio(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in AUDIO_EXTENSIONS


def engine_sample_rate() -> int:
    rate = QMediaDevices.defaultAudioOutput().preferredFormat().sampleRate()
    return rate if rate in (44100, 48000) else 48000


# --------------------------------------------------------------------------- #
# Tracks
# --------------------------------------------------------------------------- #

@dataclass
class Track:
    path: str
    title: str
    sr: int
    pcm: np.ndarray                         # (frames, 2) int16
    bpm: Optional[float] = None
    confidence: float = 0.0
    first_beat: float = 0.0                 # seconds to the first beat of the grid
    norm: float = 1.0                       # loudness match to a common level
    overview: Optional[np.ndarray] = None   # (OVERVIEW_BINS, 3) band heights 0..1
    detail: Optional[np.ndarray] = None     # (DETAIL_H, columns) ARGB uint32

    @property
    def frames(self) -> int:
        return int(self.pcm.shape[0])

    @property
    def duration(self) -> float:
        return self.frames / self.sr

    def beat_frames(self) -> Optional[float]:
        return self.sr * 60.0 / self.bpm if self.bpm else None

    def beat_phase(self, pos: float) -> float:
        """Where `pos` (frames) sits inside its beat, 0..1."""
        if not self.bpm:
            return 0.0
        return ((pos / self.sr - self.first_beat) * self.bpm / 60.0) % 1.0

    def nearest_beat(self, pos: float) -> float:
        if not self.bpm:
            return pos
        beat = self.beat_frames()
        first = self.first_beat * self.sr
        return first + round((pos - first) / beat) * beat


def _smooth(values: np.ndarray, width: int) -> np.ndarray:
    if width <= 1:
        return values
    kernel = np.ones(width, np.float32) / width
    return np.convolve(values, kernel, mode="same")


def analyse(track: Track) -> None:
    """Fill in tempo, beat grid, loudness and both waveforms. Pure numpy."""
    sr = track.sr
    mono = track.pcm.astype(np.float32).mean(axis=1) * (1.0 / 32768.0)
    rms = float(np.sqrt(np.mean(mono ** 2))) if len(mono) else 0.0
    track.norm = float(np.clip(0.16 / rms, 0.35, 3.0)) if rms > 1e-5 else 1.0

    hop = sr // DETAIL_FPS
    if len(mono) < FFT + hop:
        mono = np.pad(mono, (0, FFT + hop - len(mono)))
    frames = (len(mono) - FFT) // hop + 1
    view = np.lib.stride_tricks.sliding_window_view(mono, FFT)[::hop][:frames]
    window = np.hanning(FFT).astype(np.float32)
    freqs = np.fft.rfftfreq(FFT, 1.0 / sr)
    low, high = freqs < 150, freqs >= 2500
    mid = ~low & ~high
    bands = np.zeros((frames, 3), np.float32)
    flux = np.zeros(frames, np.float32)
    top = int(np.searchsorted(freqs, 9000))
    weight = np.ones(top, np.float32)
    weight[: int(np.searchsorted(freqs, 300))] = 3.0
    previous = None
    for start in range(0, frames, 2048):
        chunk = view[start:start + 2048] * window
        mag = np.abs(np.fft.rfft(chunk, axis=1)).astype(np.float32)
        power = mag ** 2
        bands[start:start + len(chunk)] = np.stack(
            [power[:, low].sum(1), power[:, mid].sum(1), power[:, high].sum(1)], axis=1)
        logm = np.log1p(mag[:, :top] * 20.0)
        before = previous if previous is not None else logm[:1]
        diff = np.diff(np.vstack([before, logm]), axis=0)
        flux[start:start + len(chunk)] = (np.maximum(diff, 0.0) * weight).sum(1)
        previous = logm[-1:]

    # -- waveforms -------------------------------------------------------- #
    level = np.sqrt(bands)
    for band in range(3):
        ref = float(np.percentile(level[:, band], 99.5)) or 1.0
        level[:, band] = np.clip(level[:, band] / ref, 0.0, 1.0)
    level[:, 1] *= 0.82
    level[:, 2] *= 0.6
    track.overview = _bin_max(level, OVERVIEW_BINS)
    track.detail = _detail_image(level)

    # -- tempo ------------------------------------------------------------ #
    bpm, confidence, first = estimate_tempo(flux, DETAIL_FPS)
    track.bpm, track.confidence = bpm, confidence
    track.first_beat = first + (FFT / 2) / sr if bpm else 0.0


def _bin_max(level: np.ndarray, bins: int) -> np.ndarray:
    count = len(level)
    edges = np.linspace(0, count, bins + 1).astype(int)
    out = np.zeros((bins, 3), np.float32)
    for i in range(bins):
        a, b = edges[i], max(edges[i + 1], edges[i] + 1)
        out[i] = level[a:min(b, count)].max(axis=0) if a < count else 0.0
    return out


def _detail_image(level: np.ndarray) -> np.ndarray:
    half = (DETAIL_H - 1) / 2.0
    distance = (np.abs(np.arange(DETAIL_H, dtype=np.float32) - half) / (half + 1.0))[:, None]
    image = np.zeros((DETAIL_H, len(level)), np.uint32)
    for band in range(3):
        image[distance <= level[:, band][None, :] * 0.98] = BAND_ARGB[band]
    return image


def estimate_tempo(flux: np.ndarray, fps: int) -> Tuple[Optional[float], float, float]:
    """Tempo (BPM), a confidence ratio and the first beat (seconds) from an onset curve."""
    onset = flux - _smooth(flux, fps)
    onset = np.maximum(onset, 0.0).astype(np.float64)
    if len(onset) < fps * 6 or onset.max() <= 0:
        return None, 0.0, 0.0
    onset /= onset.max()

    size = 1 << int(math.ceil(math.log2(len(onset) * 2)))
    spectrum = np.fft.rfft(onset - onset.mean(), size)
    ac = np.fft.irfft(np.abs(spectrum) ** 2)[: len(onset)]
    bpms = np.arange(60.0, 200.0, 0.5)
    lags = 60.0 * fps / bpms

    def ac_at(lag):
        return np.interp(lag, np.arange(len(ac)), ac)

    score = ac_at(lags) + 0.5 * ac_at(lags * 2) + 0.25 * ac_at(lags / 2)
    prior = np.exp(-0.5 * (np.log2(bpms / 124.0) / 0.75) ** 2)
    rough = float(bpms[int(np.argmax(score * prior))])

    # Refine against the whole track with a comb of beat positions.
    sharp = _smooth(onset, 3)
    best = (-1.0, rough, 0.0, 1.0)
    for bpm in np.arange(rough - 1.5, rough + 1.5, 0.02):
        period = 60.0 * fps / bpm
        beats = np.arange(int((len(sharp) - 1) / period))
        if len(beats) < 8:
            continue
        phases = np.arange(0.0, period, 0.5)
        idx = np.rint(phases[:, None] + beats[None, :] * period).astype(np.int64)
        np.clip(idx, 0, len(sharp) - 1, out=idx)
        sums = sharp[idx].sum(axis=1)
        j = int(np.argmax(sums))
        if sums[j] > best[0]:
            best = (float(sums[j]), float(bpm), float(phases[j]), float(sums.mean()) or 1.0)
    total, bpm, phase, mean = best
    if total <= 0:
        return None, 0.0, 0.0
    while bpm < 85:
        bpm *= 2
    while bpm >= 175:
        bpm /= 2
    if abs(bpm - round(bpm)) < 0.06:
        bpm = float(round(bpm))
    return round(bpm, 2), total / mean, phase / fps


class TrackLoader(QObject):
    """Decodes a file with QAudioDecoder, then analyses it on a worker thread."""

    progress = Signal(float)
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, path: str, sr: int, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.path, self.sr = path, sr
        self.chunks: List[np.ndarray] = []
        self.rate = sr
        self._worker: Optional[_Analyser] = None
        fmt = QAudioFormat()
        fmt.setSampleRate(sr)
        fmt.setChannelCount(2)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)
        self.decoder = QAudioDecoder(self)
        self.decoder.setAudioFormat(fmt)
        self.decoder.bufferReady.connect(self._on_buffer)
        self.decoder.finished.connect(self._on_finished)
        self.decoder.error.connect(self._on_error)
        self.decoder.setSource(QUrl.fromLocalFile(os.path.abspath(path)))

    def start(self) -> None:
        self.decoder.start()

    def cancel(self) -> None:
        self.decoder.stop()

    @Slot()
    def _on_buffer(self) -> None:
        buffer = self.decoder.read()
        if not buffer.isValid():
            return
        fmt = buffer.format()
        raw = bytes(buffer.constData())
        kind = fmt.sampleFormat()
        if kind == QAudioFormat.SampleFormat.Float:
            data = np.frombuffer(raw, np.float32)
        elif kind == QAudioFormat.SampleFormat.Int16:
            data = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
        elif kind == QAudioFormat.SampleFormat.Int32:
            data = np.frombuffer(raw, np.int32).astype(np.float32) / 2147483648.0
        else:
            data = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128.0) / 128.0
        channels = max(1, fmt.channelCount())
        data = data[: len(data) // channels * channels].reshape(-1, channels)
        data = np.repeat(data, 2, axis=1) if channels == 1 else data[:, :2]
        self.rate = fmt.sampleRate() or self.sr
        self.chunks.append((np.clip(data, -1.0, 1.0) * 32767.0).astype(np.int16))
        duration = self.decoder.duration()
        if duration > 0:
            self.progress.emit(min(0.95, self.decoder.position() / duration * 0.8))

    @Slot()
    def _on_finished(self) -> None:
        if not self.chunks:
            self.failed.emit("The file decoded to nothing - is it really audio?")
            return
        pcm = np.concatenate(self.chunks)
        self.chunks = []
        if self.rate != self.sr:
            # The backend ignored the requested rate: resample linearly.
            count = int(len(pcm) * self.sr / self.rate)
            where = np.linspace(0, len(pcm) - 1, count)
            pcm = np.stack([np.interp(where, np.arange(len(pcm)), pcm[:, c]) for c in (0, 1)],
                           axis=1).astype(np.int16)
        title = os.path.splitext(os.path.basename(self.path))[0]
        track = Track(self.path, title, self.sr, pcm)
        self.progress.emit(0.85)
        self._worker = _Analyser(track, self)
        self._worker.done.connect(self._on_analysed)
        self._worker.start()

    @Slot(object)
    def _on_analysed(self, track: Track) -> None:
        self.progress.emit(1.0)
        self.loaded.emit(track)

    @Slot()
    def _on_error(self, *_args) -> None:
        self.failed.emit(self.decoder.errorString() or "This file could not be decoded.")


class _Analyser(QThread):
    done = Signal(object)

    def __init__(self, track: Track, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.track = track

    def run(self) -> None:
        try:
            analyse(self.track)
        except Exception:  # analysis is a nicety; a track without it still plays
            self.track.bpm = None
        self.done.emit(self.track)


# --------------------------------------------------------------------------- #
# DSP building blocks
# --------------------------------------------------------------------------- #

class SpectralEQ:
    """
    Three-band kill EQ plus a resonant low/high-pass "filter" knob, applied in
    the frequency domain with 75 % overlapped frames. Zero phase, no ringing
    from recursive filters, and every knob can move freely while playing.
    """

    def __init__(self, sr: int) -> None:
        self.sr = sr
        self.window = np.sqrt(0.5 - 0.5 * np.cos(2 * np.pi * np.arange(FFT) / FFT)).astype(np.float32)
        f = np.fft.rfftfreq(FFT, 1.0 / sr).astype(np.float32)
        f[0] = 1.0
        self.freqs = f
        self.w_low = 1.0 / (1.0 + (f / 220.0) ** 4)
        self.w_high = 1.0 / (1.0 + (2600.0 / f) ** 4)
        self.w_mid = np.clip(1.0 - self.w_low - self.w_high, 0.0, 1.0)
        self.history = np.zeros((FFT, 2), np.float32)
        self.acc = np.zeros((FFT, 2), np.float32)
        self.curve = np.ones(len(f), np.float32)
        self._key = None
        self._target = self.curve

    @staticmethod
    def band_gain(knob: float) -> float:
        """-1 = full kill, 0 = unity, +1 = +6 dB."""
        if knob < 0:
            return (1.0 + knob) ** 2
        return 10 ** (knob * 6.0 / 20.0)

    def _target_curve(self, eq: Tuple[float, float, float], filt: float) -> np.ndarray:
        key = (round(eq[0], 3), round(eq[1], 3), round(eq[2], 3), round(filt, 3))
        if key == self._key:
            return self._target
        self._key = key
        f = self.freqs
        curve = (self.w_low * self.band_gain(eq[0]) + self.w_mid * self.band_gain(eq[1])
                 + self.w_high * self.band_gain(eq[2]))
        amount = abs(filt)
        if amount > 0.03:
            a = (amount - 0.03) / 0.97
            if filt < 0:
                fc = 18000.0 * (70.0 / 18000.0) ** a
                shape = 1.0 / np.sqrt(1.0 + (f / fc) ** 4)
            else:
                fc = 25.0 * (7000.0 / 25.0) ** a
                shape = 1.0 / np.sqrt(1.0 + (fc / f) ** 4)
            bump = 1.0 + 0.7 * min(1.0, a * 3) * np.exp(-0.5 * (np.log2(f / fc) / 0.16) ** 2)
            curve = curve * shape * bump
        self._target = curve.astype(np.float32)
        return self._target

    def process(self, x: np.ndarray, eq, filt: float) -> np.ndarray:
        target = self._target_curve(eq, filt)
        out = np.empty_like(x)
        w = self.window[:, None]
        for i in range(0, len(x), HOP):
            self.curve += (target - self.curve) * 0.35
            self.history = np.concatenate([self.history[HOP:], x[i:i + HOP]])
            spec = np.fft.rfft(self.history * w, axis=0) * self.curve[:, None]
            self.acc += np.fft.irfft(spec, n=FFT, axis=0).astype(np.float32) * w
            out[i:i + HOP] = self.acc[:HOP] * 0.5
            self.acc = np.concatenate([self.acc[HOP:], np.zeros((HOP, 2), np.float32)])
        return out


class Echo:
    """Feedback delay on a send: the tail keeps ringing after the send closes."""

    def __init__(self, sr: int, seconds: float = 3.0) -> None:
        self.buf = np.zeros((int(sr * seconds), 2), np.float32)
        self.w = 0
        self.quiet = True

    def process(self, x: np.ndarray, delay: float, send: float, feedback: float) -> np.ndarray:
        n, size = len(x), len(self.buf)
        if send <= 0.0005 and self.quiet:
            return np.zeros_like(x)
        delay = int(min(max(delay, n), size - 1))
        read = (self.w - delay + np.arange(n)) % size
        write = (self.w + np.arange(n)) % size
        delayed = self.buf[read]
        self.buf[write] = x * send + delayed * feedback
        self.w = (self.w + n) % size
        self.quiet = send <= 0.0005 and float(np.abs(delayed).max(initial=0.0)) < 1e-4
        return delayed


def soft_clip(x: np.ndarray, knee: float = 0.9) -> np.ndarray:
    over = np.abs(x) > knee
    if over.any():
        span = 1.0 - knee
        x = x.copy()
        x[over] = np.sign(x[over]) * (knee + span * np.tanh((np.abs(x[over]) - knee) / span))
    return x


def fader_gain(value: float) -> float:
    return value * value


# --------------------------------------------------------------------------- #
# Decks
# --------------------------------------------------------------------------- #

class DeckState:
    """One player. The GUI writes the knobs; structural changes go through Engine.post."""

    def __init__(self, name: str, sr: int) -> None:
        self.name, self.sr = name, sr
        self.track: Optional[Track] = None
        self.pos = 0.0              # frames
        self.playing = False
        self.pitch = 0.0            # tempo change, fraction (+0.02 = +2 %)
        self.bend = 0.0             # temporary nudge from the jog wheel
        self.scratching = False
        self.scratch_rate = 0.0
        self.rate_now = 0.0         # what actually played in the last block
        self.sync = False
        self.snap_pending = False
        self.sync_corr = 0.0
        self.volume = 0.85
        self.trim = 0.0             # -1..1 = -12..+12 dB
        self.eq = [0.0, 0.0, 0.0]   # low, mid, high knobs
        self.filt = 0.0
        self.echo_send = 0.0
        self.pfl = False
        self.cue = 0.0
        self.hot: List[Optional[float]] = [None] * 4
        self.loop: Optional[Tuple[float, float]] = None
        self.loop_beats = 0
        self.peak = 0.0
        self.eqp = SpectralEQ(sr)
        self.echo = Echo(sr)

    def effective_bpm(self) -> Optional[float]:
        if self.track is None or not self.track.bpm:
            return None
        return self.track.bpm * (1.0 + self.pitch)

    def render(self, n: int) -> np.ndarray:
        track = self.track
        if self.scratching:
            target = self.scratch_rate
            slew = 1.5
        else:
            target = (1.0 + self.pitch + self.bend + self.sync_corr) if self.playing else 0.0
            slew = 0.3
        r0 = self.rate_now
        r1 = r0 + max(-slew, min(slew, target - r0))
        self.rate_now = r1
        if track is None or (abs(r0) < 1e-6 and abs(r1) < 1e-6):
            raw = np.zeros((n, 2), np.float32)
        else:
            rates = np.linspace(r0, r1, n, endpoint=False)
            steps = np.cumsum(rates)
            p = self.pos + np.concatenate(([0.0], steps[:-1]))
            end = self.pos + steps[-1]
            if self.loop is not None and r1 > 0:
                a, b = self.loop
                length = b - a
                if length > 1 and end >= b:
                    p = np.where(p >= b, a + (p - a) % length, p)
                    end = a + (end - a) % length
            self.pos = end
            idx = np.floor(p).astype(np.int64)
            frac = (p - idx).astype(np.float32)[:, None]
            valid = (idx >= 0) & (idx < track.frames - 1)
            safe = np.clip(idx, 0, max(0, track.frames - 2))
            first = track.pcm[safe].astype(np.float32)
            second = track.pcm[safe + 1].astype(np.float32)
            raw = (first + (second - first) * frac) * (track.norm / 32768.0)
            raw[~valid] = 0.0
            if self.pos >= track.frames - 1 and self.playing and not self.scratching:
                self.playing = False
                self.pos = float(track.frames - 1)
            if self.pos < 0:
                self.pos = 0.0
        gain = 10 ** (self.trim * 12.0 / 20.0)
        out = self.eqp.process(raw * gain, self.eq, self.filt)
        beat = (60.0 / self.effective_bpm()) * self.sr if self.effective_bpm() else self.sr * 0.375
        out = out + self.echo.process(out, beat * 0.75, self.echo_send, 0.5)
        self.peak = max(self.peak, float(np.abs(out).max(initial=0.0)))
        return out


# --------------------------------------------------------------------------- #
# Techno machine
# --------------------------------------------------------------------------- #

ROWS = ("kick", "clap", "hat", "open", "rim", "stab")
ROW_LABELS = {"kick": "KICK", "clap": "CLAP", "hat": "HAT", "open": "OPEN HAT",
              "rim": "RIM", "stab": "STAB", "acid": "ACID"}
ROW_GAIN = {"kick": 0.95, "clap": 0.5, "hat": 0.3, "open": 0.3, "rim": 0.32, "stab": 0.3}
ROW_SEND = {"kick": 0.0, "clap": 0.35, "hat": 0.0, "open": 0.12, "rim": 0.55, "stab": 1.0,
            "acid": 0.3}
ACID_GAIN = 0.45
MACHINE_LEVEL = 0.32        # sits the machine at a loudness-matched deck's level
NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

MACHINE_DEFAULTS = {
    "kick_tune": 0.0, "kick_decay": 0.45, "kick_drive": 0.3,
    "hat_decay": 0.35, "stab_tone": 0.5,
    "cutoff": 0.35, "reso": 0.72, "envmod": 0.55, "decay": 0.4, "accent": 0.6, "drive": 0.35,
    "send": 0.25, "feedback": 0.45,
}


def _pattern(text: str) -> List[int]:
    return [2 if c == "X" else 1 if c == "x" else 0 for c in text.replace(" ", "")]


def _acid(notes: str) -> List[dict]:
    """'a0 . a12s A3 ...' - a=on, A=accent, trailing s=slide, number=semitone."""
    steps = []
    for token in notes.split():
        if token == ".":
            steps.append(dict(on=False, note=0, accent=False, slide=False))
            continue
        slide = token.endswith("s")
        body = token[:-1] if slide else token
        steps.append(dict(on=True, note=int(body[1:]), accent=body[0] == "A", slide=slide))
    return steps


PATTERNS: Dict[str, dict] = {
    "Berlin": dict(bpm=130, swing=0.0, rows=dict(
        kick="x...x...x...x...", clap="....x.......x...", hat="..x...x...x...x.",
        open="................", rim="...x.....x....x.", stab="......x.......x."),
        acid=". . . . . . . . . . . . . . . ."),
    "Acid": dict(bpm=133, swing=0.08, rows=dict(
        kick="X...x...X...x...", clap="....x.......x...", hat="x.x.x.x.x.x.x.x.",
        open="..x...x...x...x.", rim="................", stab="................"),
        acid="A0 a0 a12s a12 . a0 A3 a0s a7 . a10 A0 a12s a0 a3 ."),
    "Minimal": dict(bpm=126, swing=0.12, rows=dict(
        kick="x...x...x...x...", clap="............x...", hat="x.xx..x.x.x...xx",
        open="................", rim="..x..x.....x..x.", stab="................"),
        acid="a0 . . . . . a0 . . . a7 . . . . ."),
    "Detroit": dict(bpm=128, swing=0.06, rows=dict(
        kick="x...x...x...x...", clap="....x.......x...", hat="..x...x...x...x.",
        open="......x.......x.", rim="................", stab="..x..x....x..x.."),
        acid=". . . . . . . . . . . . . . . ."),
    "Hard": dict(bpm=145, swing=0.0, rows=dict(
        kick="X...x...X...x...", clap="....X.......X...", hat="xxxxxxxxxxxxxxxx",
        open="..x...x...x...x.", rim="x..x..x..x..x...", stab="................"),
        acid="A0 a0 a0 a0 A12 a0 a0 a0 A0 a0 a3 a0 A12 a0 a7s a5"),
    "Rolling": dict(bpm=132, swing=0.04, rows=dict(
        kick="x...x...x...x...", clap="....x.......x...", hat="..x...x...x...x.",
        open="................", rim="........x.......", stab="................"),
        acid="a0 a0 a12 a0 a0 a12 a0 a0 a12 a0 a0 a12 a0 a12 a0 a10"),
}


def default_pattern() -> dict:
    preset = PATTERNS["Berlin"]
    return dict(rows={row: _pattern(text) for row, text in preset["rows"].items()},
                acid=_acid(preset["acid"]))


def random_pattern(seed: Optional[int] = None) -> dict:
    """Something that still sounds like techno: fixed kick, probabilistic rest."""
    rnd = random.Random(seed)
    rows = {row: [0] * 16 for row in ROWS}
    for s in range(0, 16, 4):
        rows["kick"][s] = 2 if s in (0, 8) and rnd.random() < 0.5 else 1
    if rnd.random() < 0.3:
        rows["kick"][rnd.choice([3, 7, 11, 14, 15])] = 1
    for s in (4, 12):
        rows["clap"][s] = 1
    offbeat = rnd.random() < 0.7
    for s in range(16):
        if offbeat and s % 4 == 2:
            rows["hat"][s] = 1
        elif not offbeat and rnd.random() < 0.6:
            rows["hat"][s] = 1 + (s % 4 == 2)
    if rnd.random() < 0.5:
        for s in range(2, 16, 4):
            rows["open"][s] = 1
    for s in range(16):
        if s % 4 and rnd.random() < 0.18:
            rows["rim"][s] = 1
    if rnd.random() < 0.45:
        for s in rnd.sample([2, 3, 5, 6, 10, 11, 14], 3):
            rows["stab"][s] = 1
    scale = [0, 0, 0, 3, 5, 7, 7, 10, 12, 12, 15]
    acid = []
    for s in range(16):
        on = rnd.random() < 0.72
        acid.append(dict(on=on, note=rnd.choice(scale), accent=on and rnd.random() < 0.25,
                         slide=on and rnd.random() < 0.2))
    return dict(rows=rows, acid=acid)


def _fft_band(x: np.ndarray, sr: int, lo: float, hi: float) -> np.ndarray:
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1.0 / sr)
    f[0] = 1.0
    shape = np.ones_like(f)
    if lo > 0:
        shape *= 1.0 / np.sqrt(1.0 + (lo / f) ** 4)
    if hi > 0:
        shape *= 1.0 / np.sqrt(1.0 + (f / hi) ** 4)
    return np.fft.irfft(spec * shape, n=len(x)).astype(np.float32)


def _fade_tail(x: np.ndarray, sr: int, ms: float = 4.0) -> np.ndarray:
    k = min(len(x), int(sr * ms / 1000))
    if k:
        x[-k:] *= np.linspace(1.0, 0.0, k, dtype=np.float32)
    return x


def _norm(x: np.ndarray, peak: float = 0.95) -> np.ndarray:
    m = float(np.abs(x).max(initial=0.0))
    return (x * (peak / m)).astype(np.float32) if m > 0 else x.astype(np.float32)


def render_drums(sr: int, p: dict, root_hz: float) -> Dict[str, np.ndarray]:
    rng = np.random.default_rng(7)
    out: Dict[str, np.ndarray] = {}

    # Kick: sine with a fast pitch drop, a click, and optional drive.
    decay = 0.07 + p["kick_decay"] * 0.5
    t = np.arange(int(sr * (decay * 4 + 0.05))) / sr
    base = 49.0 * 2 ** (p["kick_tune"] * 6 / 12)
    freq = base + base * 2.8 * np.exp(-t / 0.03)
    body = np.sin(2 * np.pi * np.cumsum(freq) / sr) * np.exp(-t / decay)
    click = np.sin(2 * np.pi * 2200 * t) * np.exp(-t / 0.0022) * 0.4
    drive = 1.0 + p["kick_drive"] * 7.0
    kick = np.tanh((body + click) * drive) / np.tanh(drive)
    out["kick"] = _fade_tail(_norm(kick), sr)

    # Clap: three quick noise bursts and a tail, band-passed.
    t = np.arange(int(sr * 0.35)) / sr
    env = np.zeros_like(t)
    for d in (0.0, 0.011, 0.022):
        env += np.where(t >= d, np.exp(-np.maximum(t - d, 0) / 0.006), 0.0)
    env += np.where(t >= 0.03, np.exp(-np.maximum(t - 0.03, 0) / 0.11) * 0.8, 0.0)
    clap = _fft_band(rng.standard_normal(len(t)) * env, sr, 900, 3200)
    out["clap"] = _fade_tail(_norm(clap), sr)

    # Hats: six detuned square waves (the 808 recipe) plus noise, high-passed.
    def metal(length):
        tt = np.arange(int(sr * length)) / sr
        sq = sum(np.sign(np.sin(2 * np.pi * f * tt)) for f in (205.3, 304.4, 369.6, 522.7, 540.0, 800.0))
        return tt, _fft_band(sq * 0.5 + rng.standard_normal(len(tt)) * 0.8, sr, 6500, 0)

    tt, raw = metal(0.35)
    out["hat"] = _fade_tail(_norm(raw * np.exp(-tt / (0.012 + p["hat_decay"] * 0.05))), sr)
    tt, raw = metal(1.2)
    out["open"] = _fade_tail(_norm(raw * np.exp(-tt / (0.09 + p["hat_decay"] * 0.35))), sr)

    # Rim: two short tones and a click.
    t = np.arange(int(sr * 0.12)) / sr
    rim = (np.sin(2 * np.pi * 1650 * t) * np.exp(-t / 0.009)
           + 0.6 * np.sin(2 * np.pi * 480 * t) * np.exp(-t / 0.016))
    rim += _fft_band(rng.standard_normal(len(t)) * np.exp(-t / 0.003), sr, 2000, 7000) * 0.6
    out["rim"] = _fade_tail(_norm(rim), sr)

    # Stab: a minor-seventh chord of detuned saws, low-passed, short.
    t = np.arange(int(sr * 0.45)) / sr
    chord = np.zeros_like(t)
    for semis in (0, 3, 7, 10, 12):
        f0 = root_hz * 4 * 2 ** (semis / 12)
        for cents in (-7, 7):
            f = f0 * 2 ** (cents / 1200)
            chord += 2 * ((f * t) % 1.0) - 1
    tone = 900 + p["stab_tone"] * 4200
    stab = _fft_band(chord, sr, 120, tone) * np.exp(-t / 0.13)
    out["stab"] = _fade_tail(_norm(stab), sr)
    return out


def render_acid(sr: int, bpm: float, swing: float, steps: List[dict], root_hz: float,
                p: dict) -> np.ndarray:
    """One bar of 303-style bass: saw -> resonant SVF low-pass with envelope, accent, slide."""
    step_len = sr * 60.0 / bpm / 4.0
    length = int(round(16 * step_len))
    pre = int(step_len)                              # pre-roll so the loop point is settled
    total = length + pre
    starts = [int(pre + (s + (swing if s % 2 else 0.0)) * step_len) for s in range(16)]
    starts.append(total)
    freq = np.full(total, root_hz, np.float32)
    gate = np.zeros(total, np.float32)
    fenv = np.zeros(total, np.float32)
    accent = np.zeros(total, np.float32)
    decay = 0.04 + p["decay"] * 0.5
    last_f = root_hz
    note_start = None
    note_accent = 0.0
    for s in range(16):
        a, b = starts[s], starts[s + 1]
        step = steps[s]
        nxt = steps[(s + 1) % 16]
        if not step["on"]:
            freq[a:b] = last_f
            continue
        f = root_hz * 2 ** (step["note"] / 12.0)
        prev = steps[s - 1] if s > 0 else None
        tied = prev is not None and prev["on"] and prev["slide"]
        t = np.arange(b - a) / sr
        freq[a:b] = f + (last_f - f) * np.exp(-t / 0.02) if tied else f
        last_f = f
        if not tied or note_start is None:
            note_start = a
            note_accent = 1.0 if step["accent"] else 0.0
        hold = step["slide"] and nxt["on"] and s < 15
        gate[a:b if hold else a + int(step_len * 0.55)] = 1.0
        seg = np.arange(a, b)
        fenv[a:b] = np.exp(-(seg - note_start) / (decay * sr))
        accent[a:b] = note_accent
    if pre:
        # the pre-roll repeats the end of the bar so the filter enters the loop warm
        for arr in (freq, gate, fenv, accent):
            arr[:pre] = arr[length:length + pre] if length >= pre else arr[pre]
    kernel = np.ones(int(sr * 0.003), np.float32)
    amp = np.convolve(gate, kernel / kernel.sum(), mode="same")
    amp *= 1.0 + 0.7 * p["accent"] * accent

    phase = np.cumsum(freq / sr)
    t = phase % 1.0
    dt = freq / sr
    saw = 2.0 * t - 1.0
    # polyBLEP: soften the reset of the saw so it does not alias
    lo = t < dt
    x1 = t[lo] / dt[lo]
    saw[lo] -= x1 + x1 - x1 * x1 - 1.0
    hi = t > 1.0 - dt
    x2 = (t[hi] - 1.0) / dt[hi]
    saw[hi] -= x2 * x2 + x2 + x2 + 1.0

    cutoff = 55.0 * 2 ** (p["cutoff"] * 7.4)
    octaves = fenv * (p["envmod"] * 4.2 + accent * p["accent"] * 1.6)
    fc = np.clip(cutoff * 2 ** octaves, 30.0, sr * 0.42)
    g = np.tan(np.pi * fc / sr)
    k = 2.0 - 1.94 * p["reso"]
    a1 = 1.0 / (1.0 + g * (g + k))
    a2 = g * a1
    a3 = g * a2
    xs, a1l, a2l, a3l = saw.tolist(), a1.tolist(), a2.tolist(), a3.tolist()
    ic1 = ic2 = 0.0
    y = [0.0] * total
    for i in range(total):
        v3 = xs[i] - ic2
        v1 = a1l[i] * ic1 + a2l[i] * v3
        v2 = ic2 + a2l[i] * ic1 + a3l[i] * v3
        ic1 = 2.0 * v1 - ic1
        ic2 = 2.0 * v2 - ic2
        y[i] = v2
    out = np.asarray(y, np.float32)[pre:] * amp[pre:]
    drive = 1.0 + p["drive"] * 5.0
    return (np.tanh(out * drive) / np.tanh(drive) * 0.9).astype(np.float32)


class AcidRenderer(threading.Thread):
    """Renders acid bars off the audio thread; newer requests replace older ones."""

    def __init__(self, deliver: Callable[[np.ndarray, float], None]) -> None:
        super().__init__(daemon=True)
        self.deliver = deliver
        self.cond = threading.Condition()
        self.request = None
        self.alive = True

    def submit(self, *args) -> None:
        with self.cond:
            self.request = args
            self.cond.notify()

    def stop(self) -> None:
        with self.cond:
            self.alive = False
            self.cond.notify()

    def run(self) -> None:
        while True:
            with self.cond:
                while self.request is None and self.alive:
                    self.cond.wait()
                if not self.alive:
                    return
                args, self.request = self.request, None
            try:
                buffer = render_acid(*args)
            except Exception:
                continue
            self.deliver(buffer, args[1])


class Machine:
    """16-step drum machine with a 303-style bass line."""

    def __init__(self, sr: int) -> None:
        self.sr = sr
        self.bpm = 130.0
        self.playing = False
        self.step_pos = 0.0
        self.swing = 0.0
        self.key = 9                     # A
        self.params = dict(MACHINE_DEFAULTS)
        pattern = default_pattern()
        self.rows: Dict[str, List[int]] = pattern["rows"]
        self.acid: List[dict] = pattern["acid"]
        self.mutes: set = set()
        self.volume = 0.8
        self.pfl = False
        self.sync = False
        self.samples: Dict[str, np.ndarray] = {}
        self.acid_buf: Optional[np.ndarray] = None
        self.voices: List[list] = []
        self.echo = Echo(sr, 4.0)
        self.current_step = -1
        self.peak = 0.0
        self.spf_scale = 1.0

    def root_hz(self) -> float:
        hz = 55.0 * 2 ** ((self.key - 9) / 12.0)
        return hz * 2 if hz < 41 else hz

    def acid_active(self) -> bool:
        return any(step["on"] for step in self.acid)

    def render(self, n: int) -> np.ndarray:
        spf = self.bpm / 60.0 * 4.0 / self.sr * self.spf_scale
        dry = np.zeros(n, np.float32)
        send = np.zeros(n, np.float32)
        if self.playing:
            start = self.step_pos
            end = start + n * spf
            for k in range(int(math.floor(start)) - 1, int(math.floor(end)) + 1):
                t = k + (self.swing if k % 2 else 0.0)
                if start <= t < end:
                    self._trigger(k % 16, int((t - start) / spf))
            if self.acid_buf is not None and "acid" not in self.mutes and self.acid_active():
                size = len(self.acid_buf)
                where = ((start + np.arange(n) * spf) / 16.0 % 1.0) * size
                i0 = where.astype(np.int64) % size
                frac = (where - np.floor(where)).astype(np.float32)
                acid = self.acid_buf[i0] + (self.acid_buf[(i0 + 1) % size] - self.acid_buf[i0]) * frac
                dry += acid * ACID_GAIN
                send += acid * ACID_GAIN * ROW_SEND["acid"]
            self.step_pos = end % 16.0
        else:
            self.current_step = -1
        alive = []
        for voice in self.voices:
            sample, offset, gain, row = voice
            a = max(0, -offset)
            s0 = max(0, offset)
            count = min(n - a, len(sample) - s0)
            if count > 0:
                chunk = sample[s0:s0 + count] * (gain * ROW_GAIN[row])
                dry[a:a + count] += chunk
                if ROW_SEND[row]:
                    send[a:a + count] += chunk * ROW_SEND[row]
            voice[1] = offset + n
            if voice[1] < len(sample):
                alive.append(voice)
        self.voices = alive
        stereo = np.repeat(dry[:, None], 2, axis=1)
        delay = 3.0 / spf if spf > 0 else self.sr * 0.35
        wet = self.echo.process(np.repeat(send[:, None], 2, axis=1), delay,
                                self.params["send"], self.params["feedback"])
        out = (stereo + wet) * MACHINE_LEVEL
        self.peak = max(self.peak, float(np.abs(out).max(initial=0.0)))
        return out

    def _trigger(self, step: int, offset: int) -> None:
        self.current_step = step
        for row in ROWS:
            level = self.rows[row][step]
            if not level or row in self.mutes or row not in self.samples:
                continue
            if row == "hat":
                self.voices = [v for v in self.voices if v[3] != "open"]
            self.voices.append([self.samples[row], -offset, 1.0 if level == 1 else 1.4, row])


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #

class Engine(QObject):
    """Owns the decks, the machine and the sound cards. Lives on its own thread."""

    status = Signal(str)

    def __init__(self, sr: int) -> None:
        super().__init__()
        self.sr = sr
        self.decks = [DeckState("A", sr), DeckState("B", sr)]
        self.machine = Machine(sr)
        self.crossfader = 0.5
        self.master_volume = 0.8
        self.cue_mix = 0.0               # 0 = only cued channels, 1 = master in the phones
        self.cue_volume = 0.8
        self.commands: collections.deque = collections.deque()
        self.master_peak = [0.0, 0.0]
        self.frames_out = 0
        self.rec_file: Optional[wave.Wave_write] = None
        self.rec_path = ""
        self.rec_frames = 0
        self._main_name: Optional[str] = None
        self._cue_name: Optional[str] = None
        self._sink = self._io = self._cue_sink = self._cue_io = None
        self._timer: Optional[QTimer] = None
        self._retry = 0
        self.acid_renderer = AcidRenderer(self._acid_ready)
        self.acid_renderer.start()

    # -- plumbing ----------------------------------------------------------- #

    def post(self, fn: Callable[[], None]) -> None:
        """Run `fn` on the engine thread before the next block."""
        self.commands.append(fn)

    @Slot()
    def start(self) -> None:
        self._timer = QTimer()
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._timer.start(3)
        self._open()

    @Slot()
    def shutdown(self) -> None:
        if self._timer is not None:
            self._timer.stop()
        self._stop_recording()
        for sink in (self._sink, self._cue_sink):
            if sink is not None:
                sink.stop()
        self._sink = self._io = self._cue_sink = self._cue_io = None
        self.acid_renderer.stop()

    def set_devices(self, main: Optional[str], cue: Optional[str]) -> None:
        def apply():
            self._main_name, self._cue_name = main, cue
            self._open()
        self.post(apply)

    def _format(self) -> QAudioFormat:
        fmt = QAudioFormat()
        fmt.setSampleRate(self.sr)
        fmt.setChannelCount(2)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        return fmt

    def _device(self, name: Optional[str]):
        devices = QMediaDevices.audioOutputs()
        if name:
            for device in devices:
                if device.description() == name:
                    return device
            return None
        return QMediaDevices.defaultAudioOutput()

    def _open(self) -> None:
        for sink in (self._sink, self._cue_sink):
            if sink is not None:
                sink.stop()
                sink.deleteLater()
        self._sink = self._io = self._cue_sink = self._cue_io = None
        fmt = self._format()
        size = int(math.ceil(self.sr * LATENCY / BLOCK)) * BLOCK * 4
        device = self._device(self._main_name) or QMediaDevices.defaultAudioOutput()
        if device.isNull():
            self.status.emit("No sound output found.")
            return
        self._sink = QAudioSink(device, fmt)
        self._sink.setBufferSize(size)
        self._io = self._sink.start()
        note = f"Playing out of {device.description()}"
        if self._cue_name:
            cue = self._device(self._cue_name)
            if cue is not None and not cue.isNull() and cue.isFormatSupported(fmt):
                self._cue_sink = QAudioSink(cue, fmt)
                self._cue_sink.setBufferSize(size)
                self._cue_io = self._cue_sink.start()
                note += f" · headphones on {cue.description()}"
            else:
                note += " · headphone device unavailable"
        self.status.emit(note)

    def _tick(self) -> None:
        while self.commands:
            try:
                self.commands.popleft()()
            except Exception as exc:  # a bad command must never kill the audio
                self.status.emit(f"DJ engine: {exc}")
        if self._sink is None or self._io is None:
            return
        if self._sink.error() != QAudio.Error.NoError and self._sink.state() == QAudio.State.StoppedState:
            self._retry += 1
            if self._retry % 300 == 0:
                self._open()
            return
        block_bytes = BLOCK * 4
        guard = 0
        while self._sink.bytesFree() >= block_bytes and guard < 24:
            master, cue = self._render(BLOCK)
            self._io.write(_pcm16(master))
            if self._cue_io is not None and self._cue_sink.bytesFree() >= block_bytes:
                self._cue_io.write(_pcm16(cue))
            guard += 1

    # -- sync --------------------------------------------------------------- #

    def _master_clock(self, deck: Optional[DeckState]):
        """(bpm, beat phase, running) of whatever `deck` should follow."""
        others = [d for d in self.decks if d is not deck]
        for other in others:
            if other.track is not None and other.track.bpm and other.playing and not other.sync:
                return other.effective_bpm(), other.track.beat_phase(other.pos), True
        if self.machine.playing and not self.machine.sync and deck is not None:
            return self.machine.bpm, (self.machine.step_pos / 4.0) % 1.0, True
        for other in others:
            if other.track is not None and other.track.bpm and not other.sync:
                return other.effective_bpm(), other.track.beat_phase(other.pos), False
        return None

    def _apply_sync(self) -> None:
        for deck in self.decks:
            deck.sync_corr = 0.0
            if not deck.sync or deck.track is None or not deck.track.bpm:
                continue
            clock = self._master_clock(deck)
            if clock is None:
                continue
            bpm, phase, running = clock
            deck.pitch = max(-0.5, min(0.5, bpm / deck.track.bpm - 1.0))
            if not (deck.playing and running) or deck.scratching:
                continue
            if abs(deck.rate_now - (1.0 + deck.pitch)) > 0.02:
                continue              # still spinning up: snapping now would slip
            diff = (phase - deck.track.beat_phase(deck.pos) + 0.5) % 1.0 - 0.5
            if deck.snap_pending or abs(diff) > 0.08:
                deck.pos += diff * deck.track.beat_frames()
                deck.snap_pending = False
            else:
                deck.sync_corr = max(-0.015, min(0.015, diff * 0.4))
        machine = self.machine
        machine.spf_scale = 1.0
        if machine.sync:
            clock = None
            for deck in sorted(self.decks, key=lambda d: -d.volume):
                if deck.playing and deck.track is not None and deck.track.bpm:
                    clock = (deck.effective_bpm(), deck.track.beat_phase(deck.pos))
                    break
            if clock is not None:
                machine.bpm = clock[0]
                if machine.playing:
                    diff = (clock[1] - (machine.step_pos / 4.0) % 1.0 + 0.5) % 1.0 - 0.5
                    if abs(diff) > 0.08:
                        machine.step_pos = (machine.step_pos + diff * 4.0) % 16.0
                    else:
                        machine.spf_scale = 1.0 + max(-0.01, min(0.01, diff * 0.25))

    # -- mixing ------------------------------------------------------------- #

    def _render(self, n: int):
        self._apply_sync()
        a = self.decks[0].render(n)
        b = self.decks[1].render(n)
        m = self.machine.render(n)
        x = self.crossfader
        xa, xb = math.cos(x * math.pi / 2), math.sin(x * math.pi / 2)
        # constant power, but the centre is not a dip: both sides at unity there
        xa, xb = min(1.0, xa * math.sqrt(2)), min(1.0, xb * math.sqrt(2))
        ga = fader_gain(self.decks[0].volume) * xa
        gb = fader_gain(self.decks[1].volume) * xb
        gm = fader_gain(self.machine.volume)
        master = (a * ga + b * gb + m * gm) * (1.25 * self.master_volume ** 2)
        master = soft_clip(master)
        self.master_peak[0] = max(self.master_peak[0], float(np.abs(master[:, 0]).max()))
        self.master_peak[1] = max(self.master_peak[1], float(np.abs(master[:, 1]).max()))
        self.frames_out += n
        if self.rec_file is not None:
            self.rec_file.writeframesraw(_pcm16(master))
            self.rec_frames += n
        cue = None
        if self._cue_io is not None:
            cue = np.zeros_like(master)
            for deck, sig in ((self.decks[0], a), (self.decks[1], b)):
                if deck.pfl:
                    cue += sig
            if self.machine.pfl:
                cue += m
            cue = soft_clip((cue * (1.0 - self.cue_mix) + master * self.cue_mix) * self.cue_volume)
        return master, cue

    def _acid_ready(self, buffer: np.ndarray, bpm: float) -> None:
        def apply():
            self.machine.acid_buf = buffer
        self.post(apply)

    # -- actions the GUI posts --------------------------------------------- #

    def request_acid(self) -> None:
        m = self.machine
        steps = [dict(step) for step in m.acid]
        self.acid_renderer.submit(self.sr, max(60.0, m.bpm), m.swing, steps, m.root_hz(), dict(m.params))

    def rebuild_drums(self) -> None:
        samples = render_drums(self.sr, dict(self.machine.params), self.machine.root_hz())
        self.post(lambda: setattr(self.machine, "samples", samples))

    def start_recording(self, path: str) -> None:
        def apply():
            self._stop_recording()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            handle = wave.open(path, "wb")
            handle.setnchannels(2)
            handle.setsampwidth(2)
            handle.setframerate(self.sr)
            self.rec_file, self.rec_path, self.rec_frames = handle, path, 0
        self.post(apply)

    def stop_recording(self) -> None:
        self.post(self._stop_recording)

    def _stop_recording(self) -> None:
        if self.rec_file is not None:
            try:
                self.rec_file.close()
            except Exception:
                pass
        self.rec_file = None


def _pcm16(x: np.ndarray) -> bytes:
    return (np.clip(x, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()


class EngineHost(QObject):
    """Starts the engine on its own thread and stops it cleanly."""

    def __init__(self, sr: int, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.engine = Engine(sr)
        self.thread = QThread()
        self.thread.setObjectName("DJ audio")
        self.engine.moveToThread(self.thread)
        self.thread.started.connect(self.engine.start)
        self.thread.start(QThread.TimeCriticalPriority)

    def stop(self) -> None:
        if self.thread.isRunning():
            from PySide6.QtCore import QMetaObject
            QMetaObject.invokeMethod(self.engine, "shutdown", Qt.BlockingQueuedConnection)
            self.thread.quit()
            self.thread.wait(2000)
