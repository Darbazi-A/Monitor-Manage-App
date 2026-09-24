"""
Decoder process for the DJ desk.

Started by dj_engine.DecoderClient; not meant to be run by hand. It decodes
audio files with QAudioDecoder straight into shared memory, computes the
waveform levels as the audio arrives, and finishes with tempo, beat grid and
loudness. Running in its own process means it never competes with the
dashboard for Python's lock: a deck is playable a fraction of a second after a
drop, even while the other deck and the machine are playing.

Protocol, one JSON object per line:
    in   {"cmd": "load", "id", "path", "sr"} | {"cmd": "cancel", "id"}
         {"cmd": "release", "names": [...]}  | {"cmd": "quit"}
    out  {"event": "open" | "grow", "id", "pcm", "capacity", "levels", "cols_capacity", "duration"}
         {"event": "progress", "id", "frames", "cols", "fraction"}
         {"event": "done", "id", "frames", "cols", "bpm", "confidence", "first_beat", "norm", "refs"}
         {"event": "error", "id", "message"}
"""
from __future__ import annotations

import json
import os
import sys
import threading
from multiprocessing import shared_memory

# numpy's BLAS reserves memory per CPU core on import (about 180 MB here). The
# desk only uses FFTs and array arithmetic, so one thread is all it needs.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np
from PySide6.QtCore import QCoreApplication, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtMultimedia import QAudioDecoder, QAudioFormat

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dj_engine as de  # noqa: E402  (shared analysis code)

OUT = sys.stdout.buffer


def emit(message: dict) -> None:
    OUT.write((json.dumps(message) + "\n").encode("ascii"))
    OUT.flush()


class Block:
    """One shared-memory block and whether we still write to / the parent still needs it."""

    def __init__(self, size: int) -> None:
        self.shm = shared_memory.SharedMemory(create=True, size=max(16, size))
        self.writing = True
        self.released = False

    def maybe_close(self) -> bool:
        if not self.writing and self.released:
            try:
                self.shm.close()
            except BufferError:
                return False
            return True
        return False


class Job(QObject):
    finished = Signal(int)

    def __init__(self, job_id: int, path: str, sr: int, blocks: dict) -> None:
        super().__init__()
        self.id, self.path, self.sr = job_id, path, sr
        self.blocks = blocks
        self.hop = sr // de.DETAIL_FPS
        self.pending = []
        self.pcm = None
        self.levels = None
        self.capacity = 0
        self.frames = 0
        self.cols = 0
        self.flux = []
        self.previous = None
        self.sumsq = 0.0
        self.measured = 0
        self.duration = 0.0
        self.own = []                       # names of our blocks
        self.over = False

        fmt = QAudioFormat()
        fmt.setSampleRate(sr)
        fmt.setChannelCount(2)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        self.decoder = QAudioDecoder(self)
        self.decoder.setAudioFormat(fmt)
        self.decoder.bufferReady.connect(self._on_buffer)
        self.decoder.finished.connect(self._on_finished)
        self.decoder.error.connect(self._on_error)
        self.decoder.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._pump)
        self.timer.start(150)
        self.decoder.start()

    # -- memory ------------------------------------------------------------- #
    def _allocate(self, frames_needed: int) -> None:
        estimate = int(self.duration * self.sr * 1.02) + self.sr
        capacity = max(frames_needed + self.sr * 30, estimate, self.sr * 10)
        if self.pcm is not None:
            capacity = max(capacity, int(self.capacity * 1.5))
        cols_capacity = capacity // self.hop + 4
        pcm_block = Block(capacity * 4)
        lev_block = Block(cols_capacity * 12)
        pcm = np.ndarray((capacity, 2), np.int16, buffer=pcm_block.shm.buf)
        levels = np.ndarray((cols_capacity, 3), np.float32, buffer=lev_block.shm.buf)
        event = "open" if self.pcm is None else "grow"
        if self.pcm is not None:
            pcm[: self.frames] = self.pcm[: self.frames]
            levels[: self.cols] = self.levels[: self.cols]
            for name in self.own:
                self.blocks[name].writing = False
        self.pcm, self.levels, self.capacity = pcm, levels, capacity
        for block in (pcm_block, lev_block):
            self.blocks[block.shm.name] = block
            self.own.append(block.shm.name)
        emit({"event": event, "id": self.id, "pcm": pcm_block.shm.name, "capacity": capacity,
              "levels": lev_block.shm.name, "cols_capacity": cols_capacity,
              "duration": self.duration})

    def _store(self, data: np.ndarray) -> None:
        if self.frames + len(data) > self.capacity:
            self._allocate(self.frames + len(data))
        self.pcm[self.frames:self.frames + len(data)] = data
        self.frames += len(data)

    # -- decoding ----------------------------------------------------------- #
    @Slot()
    def _on_buffer(self) -> None:
        buffer = self.decoder.read()
        if not buffer.isValid() or self.over:
            return
        fmt = buffer.format()
        raw = buffer.constData()
        if fmt.sampleFormat() == QAudioFormat.SampleFormat.Int16:
            data = np.frombuffer(raw, np.int16)
        else:
            floats = np.frombuffer(raw, np.float32) if fmt.sampleFormat() == QAudioFormat.SampleFormat.Float \
                else np.frombuffer(raw, np.int32).astype(np.float32) / 2147483648.0
            data = (np.clip(floats, -1, 1) * 32767).astype(np.int16)
        channels = max(1, fmt.channelCount())
        data = data[: len(data) // channels * channels].reshape(-1, channels)
        data = np.repeat(data, 2, axis=1) if channels == 1 else data[:, :2]
        if self.pcm is None:
            if not self.duration:
                self.duration = max(0.0, self.decoder.duration() / 1000.0)
            self.pending.append(data.copy())
            pending = sum(len(p) for p in self.pending)
            if self.duration > 0 or pending > self.sr * 20:
                self._allocate(pending)
                for part in self.pending:
                    self._store(part)
                self.pending = []
                self._pump()
            return
        self._store(data)

    def _pump(self, final: bool = False) -> None:
        """Analyse what has arrived since last time and tell the parent."""
        if self.pcm is None or self.over:
            return
        available = self.frames
        n_total = (available - de.FFT) // self.hop + 1 if available >= de.FFT else 0
        if final and available > 0:
            n_total = max(n_total, 1)
        if n_total > self.cols:
            start = self.cols * self.hop
            stop = min(available, (n_total - 1) * self.hop + de.FFT)
            mono = de.mono_of(self.pcm[start:stop])
            if len(mono) < (n_total - self.cols - 1) * self.hop + de.FFT:
                mono = np.pad(mono, (0, (n_total - self.cols - 1) * self.hop + de.FFT - len(mono)))
            levels, flux, self.previous = de.stft_features(mono, self.sr, self.previous)
            count = min(len(levels), len(self.levels) - self.cols)
            self.levels[self.cols:self.cols + count] = levels[:count]
            self.flux.append(flux[:count])
            self.cols += count
        if available > self.measured:
            chunk = de.mono_of(self.pcm[self.measured:available])
            self.sumsq += float(np.dot(chunk, chunk))
            self.measured = available
        fraction = available / (self.duration * self.sr) if self.duration else 0.0
        emit({"event": "progress", "id": self.id, "frames": self.frames, "cols": self.cols,
              "fraction": min(1.0, fraction)})

    @Slot()
    def _on_finished(self) -> None:
        if self.over:
            return
        if self.pcm is None:
            if not self.pending:
                self._fail("The file decoded to nothing - is it really audio?")
                return
            self._allocate(sum(len(p) for p in self.pending))
            for part in self.pending:
                self._store(part)
            self.pending = []
        self._pump(final=True)
        flux = np.concatenate(self.flux) if self.flux else np.zeros(0, np.float32)
        try:
            bpm, confidence, first = de.estimate_tempo(flux, de.DETAIL_FPS)
        except Exception:
            bpm, confidence, first = None, 0.0, 0.0
        rms = (self.sumsq / max(1, self.measured)) ** 0.5
        norm = float(np.clip(0.16 / rms, 0.35, 3.0)) if rms > 1e-5 else 1.0
        refs = de.level_refs(self.levels[: self.cols])
        emit({"event": "done", "id": self.id, "frames": self.frames, "cols": self.cols,
              "bpm": bpm, "confidence": confidence,
              "first_beat": (first + de.ONSET_OFFSET / self.sr) if bpm else 0.0,
              "norm": norm, "refs": list(refs)})
        self._end()

    @Slot()
    def _on_error(self, *_args) -> None:
        self._fail(self.decoder.errorString() or "This file could not be decoded.")

    def _fail(self, message: str) -> None:
        if not self.over:
            emit({"event": "error", "id": self.id, "message": message})
            self._end()

    def cancel(self) -> None:
        self.decoder.stop()
        self._end()

    def _end(self) -> None:
        self.over = True
        self.timer.stop()
        self.pcm = self.levels = None
        for name in self.own:
            block = self.blocks.get(name)
            if block is not None:
                block.writing = False
        self.finished.emit(self.id)


class Worker(QObject):
    command = Signal(dict)

    def __init__(self, app: QCoreApplication) -> None:
        super().__init__()
        self.app = app
        self.jobs = {}
        self.blocks = {}
        self.command.connect(self._on_command)
        sweeper = QTimer(self)
        sweeper.timeout.connect(self._sweep)
        sweeper.start(1000)
        self._sweeper = sweeper
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for raw in sys.stdin.buffer:
            try:
                self.command.emit(json.loads(raw.decode("utf-8")))
            except ValueError:
                continue
        self.command.emit({"cmd": "quit"})

    @Slot(dict)
    def _on_command(self, message: dict) -> None:
        cmd = message.get("cmd")
        if cmd == "load":
            job = Job(int(message["id"]), message["path"], int(message["sr"]), self.blocks)
            job.finished.connect(self._job_over)
            self.jobs[job.id] = job
        elif cmd == "cancel":
            job = self.jobs.get(int(message["id"]))
            if job is not None:
                job.cancel()
        elif cmd == "release":
            for name in message.get("names", []):
                if name in self.blocks:
                    self.blocks[name].released = True
            self._sweep()
        elif cmd == "quit":
            for job in list(self.jobs.values()):
                job.cancel()
            self.app.quit()

    @Slot(int)
    def _job_over(self, job_id: int) -> None:
        job = self.jobs.pop(job_id, None)
        if job is not None:
            job.deleteLater()
        self._sweep()

    def _sweep(self) -> None:
        for name in [n for n, block in self.blocks.items() if block.maybe_close()]:
            del self.blocks[name]


def main() -> int:
    app = QCoreApplication(sys.argv)
    worker = Worker(app)  # noqa: F841 - kept alive by the event loop
    code = app.exec()
    try:
        OUT.flush()
    except OSError:
        pass
    # Leave at once: a normal interpreter shutdown would wait on the thread
    # blocked reading stdin and crash on it. Windows frees our handles anyway.
    os._exit(code)


if __name__ == "__main__":
    main()
