"""Client-local audio controls, time-preserving gate and CPU speech detection."""
from array import array
from collections import deque
import math
import sys
import threading

SAMPLE_RATE = 16000
DEFAULT_THRESHOLD = -50
MIN_THRESHOLD = -80
MAX_THRESHOLD = -20


def dbfs(rms):
    return max(-96.0, min(0.0, 20 * math.log10(max(float(rms), 0.00001) / 32768)))


def pcm_samples(pcm):
    samples = array('h', pcm)
    if sys.byteorder != 'little':
        samples.byteswap()
    return samples


def rms(pcm):
    samples = pcm_samples(pcm)
    return math.sqrt(sum(value * value for value in samples) / len(samples)) if samples else 0.0


class AudioControls:
    """Each recording window owns its state; no shared mutable user defaults."""
    def __init__(self, enabled=True, threshold=DEFAULT_THRESHOLD):
        self._lock = threading.Lock()
        self.update(enabled, threshold)

    @staticmethod
    def validate(enabled, threshold):
        if type(enabled) is not bool or type(threshold) is not int or not MIN_THRESHOLD <= threshold <= MAX_THRESHOLD:
            raise ValueError('VAD benötigt an/aus und eine Stilleschwelle zwischen −80 und −20 dBFS.')

    def update(self, enabled, threshold):
        self.validate(enabled, threshold)
        with self._lock:
            self.enabled, self.threshold = enabled, threshold

    def snapshot(self):
        with self._lock:
            return {'vad_enabled': self.enabled, 'silence_threshold_dbfs': self.threshold}


class SilenceGate:
    """20 ms frames; 200 ms lookahead and 300 ms release, never removes samples.

    Only the ASR copy is gated. Pending frames remember their capture threshold.
    A 5 ms fade inside protected margins avoids discontinuities at open/close.
    """
    FRAME_BYTES = 640
    PRE_FRAMES = 10
    POST_FRAMES = 15

    def __init__(self, controls):
        self.controls = controls
        self.pending = deque()
        self.partial = bytearray()
        self.hold = 0
        self.open = False

    def _frame(self, frame):
        threshold = self.controls.snapshot()['silence_threshold_dbfs']
        loud = dbfs(rms(frame)) >= threshold
        if loud:
            for item in self.pending:
                item[1] = True
            self.hold = self.POST_FRAMES
        keep = loud or self.hold > 0
        if not loud:
            self.hold = max(0, self.hold - 1)
        self.pending.append([frame, keep])

    def _emit(self):
        frame, keep = self.pending.popleft()
        next_keep = self.pending[0][1] if self.pending else keep
        if not keep:
            self.open = False
            return bytes(len(frame))
        samples = pcm_samples(frame)
        fade = min(80, len(samples))
        if not self.open:
            for i in range(fade):
                samples[i] = round(samples[i] * i / fade)
        if not next_keep:
            for i in range(fade):
                samples[-1-i] = round(samples[-1-i] * i / fade)
        self.open = True
        if sys.byteorder != 'little':
            samples.byteswap()
        return samples.tobytes()

    def feed(self, pcm):
        self.partial.extend(pcm)
        output = bytearray()
        while len(self.partial) >= self.FRAME_BYTES:
            frame = bytes(self.partial[:self.FRAME_BYTES])
            del self.partial[:self.FRAME_BYTES]
            self._frame(frame)
            if len(self.pending) > self.PRE_FRAMES:
                output.extend(self._emit())
        return bytes(output)

    def finish(self):
        if self.partial:
            self._frame(bytes(self.partial))
            self.partial.clear()
        result = bytearray()
        while self.pending:
            result.extend(self._emit())
        return bytes(result)

    def clear(self):
        self.partial.clear()
        self.pending.clear()
        self.hold = 0
        self.open = False


def speech_spans(pcm, enabled=True):
    """Padded sample ranges. Pure silence never loads VAD or calls Whisper."""
    if not pcm or not any(pcm):
        return []
    if not enabled:
        return [{'start': 0, 'end': len(pcm)//2}]
    try:
        from kienzledoku_vad_model import get_speech_timestamps, np
        audio = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768.0
        return get_speech_timestamps(audio)
    except Exception as exc:
        raise RuntimeError('VAD konnte nicht ausgeführt werden. Client-Installation prüfen oder VAD für kommende Blöcke ausschalten.') from exc


def self_test():
    from kienzledoku_vad_model import get_vad_model, np
    output = get_vad_model()(np.zeros(512, dtype=np.float32))
    if output.size != 1 or not np.isfinite(output).all():
        raise RuntimeError('VAD-Laufzeitprüfung fehlgeschlagen.')
    print('VAD-Selbsttest OK: Silero v6, lokale CPU, ohne Download.')


if __name__ == '__main__':
    self_test()
