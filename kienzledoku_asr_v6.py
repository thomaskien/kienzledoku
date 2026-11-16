#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kienzledoku ASR-Kern auf Basis von Kienzlefon v6.2
Natürliche Pausen -> Final-Block-ASR -> Wortzeitachse -> pyannote -> LLM

Basis: exakt die vorhandene v5.2.2-Clientdatei
rolling_sentence_asr_diarization_llm_v5_2_2.py. Die WLK-WebSocket-/Rolling-
Logik wird für Kienzledoku nicht verwendet.

Prinzip:
- Mikrofon bzw. WAV läuft lückenlos in einen Gesamtpuffer / eine Gesamt-WAV.
- Pausen werden am Nullsignal nach der benutzergesteuerten Stilleschwelle erkannt.
- Jeder Kernblock wird spätestens nach 20 Sekunden (plus Segmentframe) begrenzt.
- Nach natürlicher Pause wird ein fertiger logischer Kernblock erzeugt.
- Jeder ASR-Auftrag enthält zusätzlich kleinen Vor-/Nachkontext.
- Der Server-Endpunkt /v1/asr/final-block nutzt das bereits residente
  faster-whisper large-v3 direkt (Beam 5, VAD aus, previous_text aus).
- Wörter werden ausschließlich anhand ihres Zeitmittelpunkts genau einem
  logischen Kernblock zugeordnet. Kein Fuzzy-Merge, keine Text-Deduplizierung.
- Fertige Blöcke erscheinen unveränderlich im Terminal, während weiter
  aufgenommen wird.
- ENTER beendet die Aufnahme; der letzte Block wird mit Stille gepolstert,
  anschließend Gesamt-WAV -> pyannote -> Sprechertranskript -> LLM.

Ubuntu 24.04 sowie macOS Mojave und aktuelle macOS-Versionen mit Python >= 3.9 kompatibel.
"""

import argparse
import asyncio
import io
import json
import math
import os
import re
import sys
import threading
import time
import uuid
import wave
from array import array
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from kienzledoku_commander_client import CommanderClient, FINALIZED_HEADER, direct_open

SR = 16000
CHANNELS = 1
EVENT_PREFIX = 'KIENZLEDOKU_EVENT '


def configure_output_encoding():
    # The Windows embeddable runtime ignores PYTHONIOENCODING in isolated mode.
    # Record reads this pipe as UTF-8, including live transcripts and device names.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')


def emit_event(event_type, **fields):
    event = {'type': event_type}
    event.update(fields)
    print(EVENT_PREFIX + json.dumps(event, ensure_ascii=False, separators=(',', ':')), flush=True)


def emit_for(args, event_type, **fields):
    callback = getattr(args, 'event_callback', None)
    if callback is not None:
        event = {'type': event_type}
        event.update(fields)
        callback(event)
    else:
        emit_event(event_type, **fields)


def diagnostic_print(args, *values, **kwargs):
    if not getattr(args, 'quiet', False):
        print(*values, **kwargs)
SAMPLE_WIDTH = 2
BYTES_PER_SEC = SR * CHANNELS * SAMPLE_WIDTH


def pcm16_rms(frame):
    """RMS für little-endian PCM16 ohne audioop (ab Python 3.13 entfernt).

    Die Berechnung ist für PCM16 bitgenau äquivalent zu audioop.rms(frame, 2).
    """
    if not frame:
        return 0
    if len(frame) % SAMPLE_WIDTH:
        frame = frame[:len(frame) - (len(frame) % SAMPLE_WIDTH)]
    if not frame:
        return 0
    samples = array('h')
    samples.frombytes(frame)
    if sys.byteorder != 'little':
        samples.byteswap()
    if not samples:
        return 0
    mean_square = sum(int(value) * int(value) for value in samples) / float(len(samples))
    return int(math.sqrt(mean_square))


# ---------------------------------------------------------------------------
# Audio / URL helpers
# ---------------------------------------------------------------------------

def normalize_final_asr_url(base):
    if '://' not in base:
        base = 'http://' + base
    p = urlsplit(base)
    scheme = p.scheme
    if scheme == 'ws':
        scheme = 'http'
    elif scheme == 'wss':
        scheme = 'https'
    path = p.path.rstrip('/')
    if not path or path == '':
        path = '/v1/asr/final-block'
    elif not path.endswith('/v1/asr/final-block'):
        path = path + '/v1/asr/final-block'
    return urlunsplit((scheme, p.netloc, path, p.query, ''))


def fmt_clock(seconds):
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return '%02d:%02d:%02d' % (h, m, s)
    return '%02d:%02d' % (m, s)


def aligned_byte(seconds):
    value = int(round(float(seconds) * BYTES_PER_SEC))
    value -= value % SAMPLE_WIDTH
    return max(0, value)


MAX_SECTION_SECONDS = 2 * 60 * 60


class AudioState:
    def __init__(self, max_seconds=MAX_SECTION_SECONDS, controls=None):
        self.max_bytes = aligned_byte(max_seconds)
        self.limit_reached = False
        self._pcm = bytearray()
        self._working = bytearray()
        from kienzledoku_vad import SilenceGate
        self._gate = SilenceGate(controls) if controls is not None else None
        self._lock = threading.Lock()

    def append(self, chunk):
        with self._lock:
            remaining = self.max_bytes - len(self._pcm)
            accepted = chunk[:remaining]
            self._pcm.extend(accepted)
            if self._gate:
                self._working.extend(self._gate.feed(accepted))
            if len(self._pcm) >= self.max_bytes:
                self.limit_reached = True

    def length_bytes(self):
        with self._lock:
            return len(self._pcm)

    def duration(self):
        return self.length_bytes() / float(BYTES_PER_SEC)

    def bytes_between(self, start_byte, end_byte=None):
        with self._lock:
            if end_byte is None:
                end_byte = len(self._pcm)
            start_byte = max(0, min(start_byte, len(self._pcm)))
            end_byte = max(start_byte, min(end_byte, len(self._pcm)))
            return bytes(self._pcm[start_byte:end_byte])

    def working_length(self):
        with self._lock:
            return len(self._working if self._gate else self._pcm)

    def working_bytes(self, start, end=None):
        with self._lock:
            return bytes((self._working if self._gate else self._pcm)[start:end])

    def finish_gate(self):
        with self._lock:
            if self._gate:
                self._working.extend(self._gate.finish())
                assert len(self._working) == len(self._pcm)

    def all_pcm(self):
        with self._lock:
            return bytes(self._pcm)

    def clear(self):
        with self._lock:
            self._pcm.clear()
            self._working.clear()
            if self._gate: self._gate.clear()


def load_replay_wav(path):
    """16 kHz, mono, PCM16-WAV exakt laden."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError('Replay-WAV nicht gefunden: %s' % p)

    with wave.open(str(p), 'rb') as wf:
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        rate = wf.getframerate()
        comptype = wf.getcomptype()
        frames = wf.getnframes()

        if channels != CHANNELS:
            raise ValueError('Replay-WAV muss mono sein; gefunden: %d Kanäle' % channels)
        if width != SAMPLE_WIDTH:
            raise ValueError('Replay-WAV muss 16-bit PCM sein; Samplebreite=%d Byte' % width)
        if rate != SR:
            raise ValueError('Replay-WAV muss 16000 Hz haben; gefunden: %d Hz' % rate)
        if comptype != 'NONE':
            raise ValueError('Replay-WAV muss unkomprimiertes PCM sein; gefunden: %s' % comptype)

        return wf.readframes(frames)


def save_wav(path, pcm):
    with wave.open(str(path), 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SR)
        wf.writeframes(pcm)


def wav_bytes_from_pcm(pcm, pad_tail_seconds=0.0):
    if pad_tail_seconds > 0:
        pad_samples = int(round(float(pad_tail_seconds) * SR))
        pcm = pcm + (b'\x00\x00' * pad_samples)
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SR)
        wf.writeframes(pcm)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Lokale Pausenerkennung: entscheidet NUR Schnitte, verwirft niemals Audio.
# ---------------------------------------------------------------------------

class PauseSegmenter:
    def __init__(self, args):
        self.args = args
        self.core_start_s = 0.0
        self.speech_seen = False
        self.silence_start_s = None
        self.last_rms = 0

    def _reset_after_cut(self, cut_s, currently_silent):
        self.core_start_s = float(cut_s)
        self.speech_seen = not currently_silent
        self.silence_start_s = None

    def feed(self, frame, frame_start_s, frame_end_s):
        """Return list of logical cut events for one PCM frame."""
        events = []
        self.last_rms = pcm16_rms(frame)  # diagnostic only, never a second gate
        # Frames already passed the user's SilenceGate. Even very quiet
        # surviving audio must reach VAD; only actual digital zero is a pause.
        silent = not any(frame)

        if silent:
            if self.speech_seen and self.silence_start_s is None:
                self.silence_start_s = frame_start_s
        else:
            self.speech_seen = True
            self.silence_start_s = None

        if self.speech_seen and self.silence_start_s is not None:
            silence_dur = frame_end_s - self.silence_start_s
            if silence_dur >= self.args.pause_seconds:
                # Schnitt so früh in die bestätigte Pause legen, dass rechts noch
                # ungefähr context_seconds echter Nachlauf verfügbar ist.
                cut_offset = max(0.0, self.args.pause_seconds - self.args.context_seconds)
                cut = self.silence_start_s + cut_offset
                core_age = cut - self.core_start_s

                normal_ok = core_age >= self.args.min_block_seconds
                short_ok = silence_dur >= self.args.short_block_pause_seconds
                if normal_ok or short_ok:
                    reason = 'pause' if normal_ok else 'long_pause_short_block'
                    events.append({
                        'core_start': self.core_start_s,
                        'core_end': cut,
                        'reason': reason,
                    })
                    self._reset_after_cut(cut, currently_silent=True)
                    return events

        # Bound every core, including silence. VAD skips non-speech afterwards;
        # it must not depend on an earlier amplitude-based speech decision.
        if (frame_end_s - self.core_start_s) >= self.args.max_block_seconds:
            cut = frame_end_s
            events.append({
                'core_start': self.core_start_s,
                'core_end': cut,
                'reason': 'failsafe_max',
            })
            self._reset_after_cut(cut, currently_silent=silent)
            return events

        # v6.1: Kein destruktives Idle-Trim mehr. core_start_s wird ausschließlich
        # durch einen tatsächlich emittierten Schnitt weitergeschoben. Damit gibt
        # es in der logischen Kernzeitachse keine stillen, nicht-ASR-geprüften Lücken.

        return events


# ---------------------------------------------------------------------------
# Final-ASR HTTP client
# ---------------------------------------------------------------------------

def _multipart_final_block(wav_bytes, language, filename='block.wav'):
    boundary = '----KienzledokuBoundary' + uuid.uuid4().hex
    b = boundary.encode('ascii')
    body = bytearray()

    def add_line(line=b''):
        body.extend(line)
        body.extend(b'\r\n')

    add_line(b'--' + b)
    add_line(('Content-Disposition: form-data; name="file"; filename="%s"' % filename).encode('utf-8'))
    add_line(b'Content-Type: audio/wav')
    add_line()
    body.extend(wav_bytes)
    body.extend(b'\r\n')

    add_line(b'--' + b)
    add_line(b'Content-Disposition: form-data; name="language"')
    add_line()
    add_line(str(language or 'de').encode('utf-8'))

    add_line(b'--' + b + b'--')
    return bytes(body), 'multipart/form-data; boundary=' + boundary


def transcribe_final_block_http(url, wav_bytes, language, api_key=None, timeout=120.0, commander=False):
    body, content_type = _multipart_final_block(wav_bytes, language)
    headers = {
        'Accept': 'application/json',
        'Content-Type': content_type,
        'User-Agent': 'Kienzledoku-ASR/1.8',
    }
    if api_key:
        headers['Authorization'] = 'Bearer ' + api_key

    req = Request(url, data=body, headers=headers, method='POST')
    try:
        opener = direct_open if commander else urlopen
        with opener(req, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as exc:
        if commander:
            raise RuntimeError('Commander-ASR fehlgeschlagen (HTTP %d). Audio wurde nicht vollständig transkribiert.' % exc.code) from None
        try:
            detail = exc.read().decode('utf-8', errors='replace')
        except Exception:
            detail = ''
        raise RuntimeError('Final-ASR HTTP %s: %s' % (exc.code, detail or exc.reason))
    except URLError as exc:
        raise RuntimeError('Final-ASR nicht erreichbar: %s' % exc)

    try:
        return json.loads(raw.decode('utf-8'))
    except Exception as exc:
        raise RuntimeError('Final-ASR lieferte ungültiges JSON: %s' % exc)


def _select_result_for_core(result, physical_start_s, core_start_s, core_end_s, is_final=False):
    words = []
    for word in result.get('words') or []:
        try:
            gs = float(physical_start_s) + float(word['start'])
            ge = float(physical_start_s) + float(word['end'])
        except Exception:
            continue
        mid = (gs + ge) / 2.0
        if mid + 0.002 < core_start_s:
            continue
        if is_final:
            if mid > core_end_s + 0.002:
                continue
        else:
            if mid >= core_end_s - 0.002:
                continue
        item = {
            'start': gs,
            'end': ge,
            'text': str(word.get('word', '')),
        }
        prob = word.get('probability')
        if isinstance(prob, (int, float)):
            item['probability'] = float(prob)
        words.append(item)

    segments = []
    for seg in result.get('segments') or []:
        try:
            gs = float(physical_start_s) + float(seg['start'])
            ge = float(physical_start_s) + float(seg['end'])
        except Exception:
            continue
        mid = (gs + ge) / 2.0
        if mid + 0.002 < core_start_s:
            continue
        if is_final:
            if mid > core_end_s + 0.002:
                continue
        else:
            if mid >= core_end_s - 0.002:
                continue
        segments.append({
            'start': gs,
            'end': ge,
            'text': str(seg.get('text', '')).strip(),
        })

    if words:
        text = ''.join(x['text'] for x in words).strip()
        mode = 'words_midpoint'
    else:
        text = ' '.join(x['text'] for x in segments if x['text']).strip()
        mode = 'segments_midpoint_fallback'

    return text, words, segments, mode


# ---------------------------------------------------------------------------
# v5.2.2-bewährte pyannote-/LLM-Helfer, ohne ASR-Rekonstruktion
# ---------------------------------------------------------------------------

def http_json(url, method='GET', payload=None, api_key=None, timeout=120):
    data = None
    headers = {'Accept': 'application/json'}
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    if api_key:
        headers['Authorization'] = 'Bearer ' + api_key
    req = Request(url, data=data, headers=headers, method=method)
    with urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8'))


def diarize_wav(base_url, wav_path, min_speakers, max_speakers, num_speakers,
                timeout, api_key=None, recording_finalized=False, commander=False):
    body = Path(wav_path).read_bytes()
    return diarize_audio(base_url, body, min_speakers, max_speakers, num_speakers,
                         timeout, api_key=api_key,
                         recording_finalized=recording_finalized, commander=commander)


def diarize_audio(base_url, wav_body, min_speakers, max_speakers, num_speakers,
                  timeout, api_key=None, recording_finalized=False, commander=False):
    """Diarize WAV bytes directly, without creating a patient-data file."""
    params = {}
    if num_speakers is not None:
        params['num_speakers'] = int(num_speakers)
    else:
        if min_speakers is not None:
            params['min_speakers'] = int(min_speakers)
        if max_speakers is not None:
            params['max_speakers'] = int(max_speakers)
    url = base_url.rstrip('/') + '/v1/diarize'
    if params:
        url += '?' + urlencode(params)
    headers = {'Content-Type': 'audio/wav', 'Accept': 'application/json'}
    if api_key:
        headers['Authorization'] = 'Bearer ' + api_key
    if recording_finalized:
        headers[FINALIZED_HEADER] = 'true'
    req = Request(
        url,
        data=wav_body,
        headers=headers,
        method='POST',
    )
    opener = direct_open if commander else urlopen
    try:
        with opener(req, timeout=timeout) as response:
            return json.loads(response.read().decode('utf-8'))
    except HTTPError as exc:
        # Error responses may echo patient input. Show only stage and status.
        raise RuntimeError('Sprecherzuordnung fehlgeschlagen (HTTP %d).' % exc.code) from None


def nearest_speaker(mid, diar_segments):
    best = None
    best_dist = None
    for d in diar_segments:
        ds = float(d['start'])
        de = float(d['end'])
        if ds <= mid <= de:
            return str(d['speaker'])
        dist = (ds - mid) if mid < ds else (mid - de)
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best = str(d['speaker'])
    return best or 'SPEAKER_UNKNOWN'


def speaker_for_word(word, diar_segments):
    start = float(word['start'])
    end = float(word['end'])
    scores = {}
    for d in diar_segments:
        ds = float(d['start'])
        de = float(d['end'])
        overlap = max(0.0, min(end, de) - max(start, ds))
        if overlap > 0:
            speaker = str(d['speaker'])
            scores[speaker] = scores.get(speaker, 0.0) + overlap
    if scores:
        return max(scores.items(), key=lambda kv: kv[1])[0]
    return nearest_speaker((start + end) / 2.0, diar_segments)


def speaker_transcript_words(asr_words, diar_segments):
    if not asr_words or not diar_segments:
        return '', []

    labeled = []
    for word in asr_words:
        labeled.append({
            'speaker': speaker_for_word(word, diar_segments),
            'start': word['start'],
            'end': word['end'],
            'text': word['text'],
        })

    paragraphs = []
    for item in labeled:
        if paragraphs and paragraphs[-1]['speaker'] == item['speaker']:
            paragraphs[-1]['text'] += item['text']
            paragraphs[-1]['end'] = item['end']
        else:
            paragraphs.append(dict(item))

    rendered = '\n'.join(
        '[%s] %s' % (p['speaker'], p['text'].strip())
        for p in paragraphs
        if p['text'].strip()
    )
    return rendered.strip(), paragraphs


def dominant_speaker(start, end, diar_segments):
    scores = {}
    for d in diar_segments:
        ds = float(d['start'])
        de = float(d['end'])
        overlap = max(0.0, min(end, de) - max(start, ds))
        if overlap > 0:
            speaker = str(d['speaker'])
            scores[speaker] = scores.get(speaker, 0.0) + overlap
    if scores:
        return max(scores.items(), key=lambda kv: kv[1])[0]

    mid = (start + end) / 2.0
    best = None
    best_dist = None
    for d in diar_segments:
        dmid = (float(d['start']) + float(d['end'])) / 2.0
        dist = abs(mid - dmid)
        if best_dist is None or dist < best_dist:
            best = str(d['speaker'])
            best_dist = dist
    return best or 'SPEAKER_UNKNOWN'


def speaker_transcript(asr_segments, diar_segments):
    if not asr_segments or not diar_segments:
        return '', []

    labeled = []
    for seg in asr_segments:
        speaker = dominant_speaker(seg['start'], seg['end'], diar_segments)
        labeled.append({
            'speaker': speaker,
            'start': seg['start'],
            'end': seg['end'],
            'text': seg['text'],
        })

    paragraphs = []
    for item in labeled:
        if paragraphs and paragraphs[-1]['speaker'] == item['speaker']:
            paragraphs[-1]['text'] += ' ' + item['text']
            paragraphs[-1]['end'] = item['end']
        else:
            paragraphs.append(dict(item))

    rendered = '\n'.join(
        '[%s] %s' % (p['speaker'], p['text'].strip())
        for p in paragraphs
        if p['text'].strip()
    )
    return rendered.strip(), paragraphs


def llm_root(base):
    base = base.rstrip('/')
    return base if base.endswith('/v1') else base + '/v1'


def choose_model(root, api_key, explicit):
    if explicit:
        return explicit
    result = http_json(root + '/models', api_key=api_key, timeout=10)
    data = result.get('data') or []
    if not data:
        raise RuntimeError('LLM /v1/models liefert kein Modell.')
    return data[0]['id']


def call_llm(args, transcript):
    root = llm_root(args.llm)
    model = choose_model(root, args.llm_api_key, args.llm_model)
    prompt = Path(args.prompt_file).read_text(encoding='utf-8').strip()
    from kienzledoku_document import validate_fields
    fields = validate_fields(getattr(args, 'active_fields', None))
    prompt += '\n\nGib ausschließlich ein JSON-Objekt mit exakt diesen Textfeldern aus. Nicht belegte Felder bleiben leer:\n' + json.dumps({field: '' for field in fields}, ensure_ascii=False)
    payload = {
        'model': model,
        'temperature': args.temperature,
        'max_tokens': args.max_tokens,
        'response_format': {'type': 'json_object'},
        'messages': [
            {'role': 'system', 'content': prompt},
            {'role': 'user', 'content': 'TRANSKRIPT:\n\n' + transcript},
        ],
    }
    result = http_json(
        root + '/chat/completions',
        method='POST',
        payload=payload,
        api_key=args.llm_api_key,
        timeout=300,
    )
    return result['choices'][0]['message']['content']


# ---------------------------------------------------------------------------
# Replay / ASR queue
# ---------------------------------------------------------------------------

async def replay_pcm(audio, pcm, chunk_ms, speed):
    chunk_bytes = max(SAMPLE_WIDTH, int(round(BYTES_PER_SEC * float(chunk_ms) / 1000.0)))
    chunk_bytes -= chunk_bytes % SAMPLE_WIDTH
    start = time.monotonic()
    sent = 0

    while sent < len(pcm):
        chunk = pcm[sent:sent + chunk_bytes]
        audio.append(chunk)
        sent += len(chunk)

        if speed > 0:
            target = start + (sent / float(BYTES_PER_SEC)) / float(speed)
            delay = target - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            else:
                await asyncio.sleep(0)
        else:
            # Fast-Replay: kooperativ bleiben, damit Segmentierung/ASR-Queue laufen.
            await asyncio.sleep(0)

    return sent / float(BYTES_PER_SEC)


class RecordingCancelled(Exception):
    pass


def cancellation_requested(args):
    event = getattr(args, 'cancel_event', None)
    return event is not None and event.is_set()


async def daemon_http_call(args, function, *call_args):
    """Await blocking HTTP without registering work in asyncio's exit-joined pool."""
    if cancellation_requested(args):
        raise RecordingCancelled()
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    def deliver_result(value=None, error=None):
        if future.done():
            return
        if error is not None:
            future.set_exception(error)
        else:
            future.set_result(value)

    def request_worker():
        try:
            value = function(*call_args)
        except BaseException as exc:
            try:
                loop.call_soon_threadsafe(deliver_result, None, exc)
            except RuntimeError:
                pass
        else:
            try:
                loop.call_soon_threadsafe(deliver_result, value, None)
            except RuntimeError:
                pass

    thread = threading.Thread(target=request_worker, name='Kienzledoku-ASR-HTTP')
    thread.daemon = True
    thread.start()
    try:
        while True:
            if cancellation_requested(args):
                future.cancel()
                raise RecordingCancelled()
            try:
                return await asyncio.wait_for(asyncio.shield(future), timeout=.05)
            except asyncio.TimeoutError:
                continue
    except asyncio.CancelledError:
        future.cancel()
        raise


async def transcribe_vad_block(args, url, pcm, job, physical_start):
    from kienzledoku_vad import speech_spans
    controls = getattr(args, 'audio_controls', None)
    enabled = controls.snapshot()['vad_enabled'] if controls else False
    # Snapshot before the asynchronous work: toggles apply to the next block.
    spans = await asyncio.to_thread(speech_spans, pcm, enabled)
    combined = {'words': [], 'segments': [], 'text': '', 'processing_seconds': 0.0,
                'decoder': 'silero-v6+whisper' if enabled else 'whisper'}
    texts = []
    for span in spans:
        offset, end = span['start'] / SR, span['end'] / SR
        if physical_start + end <= job['core_start'] or physical_start + offset >= job['core_end']:
            continue
        if cancellation_requested(args):
            raise RecordingCancelled()
        tail = float(job.get('pad_tail', 0)) if span['end'] * 2 == len(pcm) else 0
        result = await daemon_http_call(args, transcribe_final_block_http, url,
            wav_bytes_from_pcm(pcm[span['start']*2:span['end']*2], pad_tail_seconds=tail),
            args.language, args.asr_api_key, args.asr_timeout, bool(getattr(args, 'commander', None)))
        for key in ('words', 'segments'):
            for item in result.get(key) or []:
                shifted = dict(item)
                shifted['start'] = float(item['start']) + offset
                shifted['end'] = float(item['end']) + offset
                combined[key].append(shifted)
        texts.append(str(result.get('text') or ''))
        if isinstance(result.get('processing_seconds'), (float, int)):
            combined['processing_seconds'] += result['processing_seconds']
    combined['text'] = ' '.join(texts).strip()
    return combined


async def asr_worker(args, audio, queue, block_results, stats):
    url = normalize_final_asr_url(args.asr)
    while True:
        job = await queue.get()
        try:
            if job is None:
                return
            if cancellation_requested(args):
                raise RecordingCancelled()

            start_byte = aligned_byte(job['physical_start'])
            end_byte = aligned_byte(job['physical_end'])
            pcm = audio.working_bytes(start_byte, end_byte)
            actual_physical_start = start_byte / float(BYTES_PER_SEC)
            t0 = time.monotonic()
            result = await transcribe_vad_block(args, url, pcm, job, actual_physical_start)
            client_elapsed = time.monotonic() - t0

            if cancellation_requested(args):
                raise RecordingCancelled()

            text, words, segments, ownership_mode = _select_result_for_core(
                result,
                actual_physical_start,
                job['core_start'],
                job['core_end'],
                is_final=bool(job.get('is_final')),
            )

            item = dict(job)
            item.update({
                'physical_start': actual_physical_start,
                'text': text,
                'words': words,
                'segments': segments,
                'ownership_mode': ownership_mode,
                'server_processing_seconds': result.get('processing_seconds'),
                'server_rtf': result.get('rtf'),
                'client_seconds': client_elapsed,
                'decoder': result.get('decoder'),
                'error': None,
            })
            block_results.append(item)
            stats['completed'] += 1
            stats['asr_client_seconds_sum'] += client_elapsed
            if isinstance(result.get('processing_seconds'), (int, float)):
                stats['asr_server_seconds_sum'] += float(result['processing_seconds'])

            diagnostic_print(args,
                '\n[FINAL %03d] %.2f..%.2fs | %s | Wörter=%d | ASR=%.3fs'
                % (
                    job['id'],
                    job['core_start'],
                    job['core_end'],
                    job['reason'],
                    len(words),
                    client_elapsed,
                )
            )
            diagnostic_print(args, text or '(kein Text)')
            emit_for(args,
                'final_block',
                block_id=job['id'],
                start=job['core_start'],
                end=job['core_end'],
                text=text or '',
            )

        except RecordingCancelled:
            return
        except Exception as exc:
            stats['failed'] += 1
            item = dict(job or {})
            item.update({
                'text': '',
                'words': [],
                'segments': [],
                'error': str(exc),
            })
            if job is not None:
                block_results.append(item)
                diagnostic_print(args, '\n[FINAL %03d FEHLER] %s' % (job['id'], exc), file=sys.stderr)
                emit_for(args, 'asr_error', block_id=job['id'])
        finally:
            queue.task_done()


def _run_payload(block_results, duration, final_wav_path, args, stats, diarization=None, speaker_text=None, llm=None):
    ordered = sorted(block_results, key=lambda x: x.get('id', 0))
    words = []
    segments = []
    texts = []
    for b in ordered:
        words.extend(b.get('words') or [])
        segments.extend(b.get('segments') or [])
        if (b.get('text') or '').strip():
            texts.append(b['text'].strip())

    words.sort(key=lambda x: (x['start'], x['end']))
    segments.sort(key=lambda x: (x['start'], x['end']))
    transcript = ' '.join(texts).strip()

    return {
        'version': '6.1',
        'architecture': 'natural-pause-final-block',
        'audio_duration': duration,
        'wav': final_wav_path,
        'final_asr': normalize_final_asr_url(args.asr),
        'segmentation': {
            'pause_seconds': args.pause_seconds,
            'short_block_pause_seconds': args.short_block_pause_seconds,
            'min_block_seconds': args.min_block_seconds,
            'max_block_seconds': args.max_block_seconds,
            'context_seconds': args.context_seconds,
            'segment_frame_ms': args.segment_frame_ms,
            'pause_detection': 'silence-gate-zero',
        },
        'metrics': dict(stats),
        'blocks': ordered,
        'transcript': transcript,
        'words': words,
        'segments': segments,
        'diarization': diarization,
        'speaker_transcript': speaker_text,
        'llm': llm,
        'recording_finalized': bool(getattr(args, 'recording_finalized', False)),
        'commander': getattr(args, 'commander_metadata', None),
    }


def save_json(path, payload):
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


async def run_recording(args):
    from kienzledoku_vad import AudioControls
    if not hasattr(args, "audio_controls"):
        args.audio_controls = AudioControls()
    audio = AudioState(controls=args.audio_controls)
    args._recording_tasks = []
    args._recording_stream = None
    try:
        return await _run_recording(args, audio)
    finally:
        event = getattr(args, 'stop_event', None)
        if event is not None:
            event.set()
        stream = args._recording_stream
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        tasks = args._recording_tasks
        for task in tasks:
            if not task.done(): task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        audio.clear()
        args._recording_tasks = []
        args._recording_stream = None


async def _run_recording(args, audio):
    if args.pause_seconds <= 0:
        raise ValueError('--pause-seconds muss > 0 sein.')
    if args.context_seconds < 0:
        raise ValueError('--context-seconds muss >= 0 sein.')
    if args.context_seconds > args.short_block_pause_seconds:
        raise ValueError('--context-seconds darf nicht größer als --short-block-pause-seconds sein.')
    if args.min_block_seconds <= 0:
        raise ValueError('--min-block-seconds muss > 0 sein.')
    if args.max_block_seconds <= args.min_block_seconds:
        raise ValueError('--max-block-seconds muss größer als --min-block-seconds sein.')
    if args.segment_frame_ms <= 0:
        raise ValueError('--segment-frame-ms muss > 0 sein.')

    loop = asyncio.get_running_loop()
    segmenter = PauseSegmenter(args)
    asr_queue = asyncio.Queue()
    block_results = []
    stats = {
        'blocks_enqueued': 0,
        'completed': 0,
        'failed': 0,
        'natural_cuts': 0,
        'short_block_cuts': 0,
        'failsafe_cuts': 0,
        'final_cuts': 0,
        'max_queue': 0,
        'asr_client_seconds_sum': 0.0,
        'asr_server_seconds_sum': 0.0,
    }
    worker = asyncio.create_task(asr_worker(args, audio, asr_queue, block_results, stats))
    args._recording_tasks.append(worker)

    pending = []
    next_block_id = 1
    detect_cursor = 0
    frame_bytes = max(SAMPLE_WIDTH, int(round(BYTES_PER_SEC * args.segment_frame_ms / 1000.0)))
    frame_bytes -= frame_bytes % SAMPLE_WIDTH
    last_status_audio_s = -999.0

    def register_cut(ev):
        nonlocal next_block_id
        core_start = float(ev['core_start'])
        core_end = float(ev['core_end'])
        if core_end <= core_start + 0.01:
            return
        job = {
            'id': next_block_id,
            'core_start': core_start,
            'core_end': core_end,
            'physical_start': max(0.0, core_start - args.context_seconds),
            'physical_end_required': core_end + args.context_seconds,
            'reason': ev['reason'],
            'is_final': False,
        }
        next_block_id += 1
        pending.append(job)
        if ev['reason'] == 'pause':
            stats['natural_cuts'] += 1
        elif ev['reason'] == 'long_pause_short_block':
            stats['short_block_cuts'] += 1
        elif ev['reason'] == 'failsafe_max':
            stats['failsafe_cuts'] += 1
        diagnostic_print(args,
            '\n[SCHNITT %03d] %.2f..%.2fs | %s | ASR-Kontext ±%.2fs'
            % (job['id'], core_start, core_end, ev['reason'], args.context_seconds)
        )

    async def enqueue_ready(force=False):
        nonlocal pending
        total = audio.working_length() / float(BYTES_PER_SEC)
        keep = []
        for job in pending:
            required = float(job['physical_end_required'])
            if (not force) and total + 0.001 < required:
                keep.append(job)
                continue
            physical_end = min(total, required)
            pad_tail = max(0.0, required - physical_end) if force else 0.0
            queued = dict(job)
            queued['physical_end'] = physical_end
            queued['pad_tail'] = pad_tail
            await asr_queue.put(queued)
            stats['blocks_enqueued'] += 1
            stats['max_queue'] = max(stats['max_queue'], asr_queue.qsize())
        pending = keep

    def process_available_frames():
        nonlocal detect_cursor
        end = audio.working_length()
        while detect_cursor + frame_bytes <= end:
            frame = audio.working_bytes(detect_cursor, detect_cursor + frame_bytes)
            frame_start = detect_cursor / float(BYTES_PER_SEC)
            detect_cursor += frame_bytes
            frame_end = detect_cursor / float(BYTES_PER_SEC)
            for ev in segmenter.feed(frame, frame_start, frame_end):
                register_cut(ev)

    device = args.device
    if device is not None and str(device).isdigit():
        device = int(device)

    stream = None
    replay_task = None
    replay_data = None
    waiter = None

    if args.input_wav:
        replay_data = load_replay_wav(args.input_wav)
        replay_task = asyncio.create_task(
            replay_pcm(audio, replay_data, args.audio_chunk_ms, args.replay_speed)
        )
        args._recording_tasks.append(replay_task)
    else:
        try:
            import sounddevice as sd
        except Exception as exc:
            raise RuntimeError('sounddevice fehlt für Mikrofonbetrieb: %s' % exc)

        from kienzledoku_audio import create_input
        stream, audio_failure = create_input(
            sd, device, audio.append,
            lambda kind, **data: emit_for(args, kind, **data), args.audio_chunk_ms)
        waiter = loop.create_future()
        def wait_for_stop():
            stop_event = getattr(args, 'stop_event', None)
            if stop_event is None:
                sys.stdin.readline()
            else:
                stop_event.wait()
            try:
                loop.call_soon_threadsafe(lambda: None if waiter.done() else waiter.set_result(None))
            except RuntimeError:
                pass
        threading.Thread(target=wait_for_stop, daemon=True).start()
        args._recording_stream = stream
        stream.start()

    diagnostic_print(args, '\n=== kienzledoku record 1.8 Final-Block-ASR ===')
    diagnostic_print(args, 'Final-ASR:         %s' % normalize_final_asr_url(args.asr))
    diagnostic_print(args, 'Pausenschnitt:     %.2f s bestätigt' % args.pause_seconds)
    diagnostic_print(args, 'Kurze Äußerung:    Schnitt spätestens nach %.2f s Stille' % args.short_block_pause_seconds)
    diagnostic_print(args, 'Min. Normalblock:  %.2f s' % args.min_block_seconds)
    diagnostic_print(args, 'Max. Kernblock:    %.2f s (Failsafe)' % args.max_block_seconds)
    diagnostic_print(args, 'ASR-Kontext:       ±%.2f s' % args.context_seconds)
    diagnostic_print(args, 'Pausenerkennung:   Nullsignal nach Client-Stilleschwelle; keine zweite Pegelschwelle')
    diagnostic_print(args, 'Audiochunk:        %d ms' % args.audio_chunk_ms)
    if args.input_wav:
        dur = len(replay_data) / float(BYTES_PER_SEC)
        diagnostic_print(args, 'Quelle:            WAV-Replay')
        diagnostic_print(args, 'Input-WAV:         %s' % args.input_wav)
        diagnostic_print(args, 'Replay-Dauer:      %.2f s' % dur)
        diagnostic_print(args, 'Replay-Speed:      %s' % ('maximal' if args.replay_speed == 0 else '%.2fx' % args.replay_speed))
        diagnostic_print(args, 'Ende:              automatisch am WAV-Ende')
    else:
        diagnostic_print(args, 'Quelle:            Mikrofon')
        diagnostic_print(args, 'ENTER:             Aufnahme stoppen')

    ram_only = bool(getattr(args, 'ram_only', False))
    journal = None
    if not ram_only:
        journal_path = str(args.wav) + '.partial.wav'
        journal = wave.open(journal_path, 'wb')
        journal.setnchannels(CHANNELS); journal.setsampwidth(SAMPLE_WIDTH); journal.setframerate(SR)
    journal_cursor = 0
    last_journal = 0.0
    try:
        while True:
            if cancellation_requested(args):
                raise RecordingCancelled()
            if stream is not None and (audio_failure or not stream.active):
                raise RuntimeError(audio_failure[0] if audio_failure else 'Mikrofonverbindung unterbrochen')
            if journal is not None and time.monotonic()-last_journal > .5:
                chunk = audio.bytes_between(journal_cursor)
                journal.writeframes(chunk); journal_cursor += len(chunk)
                last_journal = time.monotonic()
            process_available_frames()
            await enqueue_ready(force=False)

            now = audio.duration()
            if audio.limit_reached:
                emit_for(args, 'recording_limit', seconds=MAX_SECTION_SECONDS)
                if replay_task is not None and not replay_task.done():
                    replay_task.cancel()
                    await asyncio.gather(replay_task, return_exceptions=True)
                if waiter is not None and not waiter.done():
                    waiter.set_result(None)
                stop_event = getattr(args, 'stop_event', None)
                if stop_event is not None: stop_event.set()
            source_done = replay_task.done() if replay_task is not None else waiter.done()

            if now - last_status_audio_s >= args.status_seconds:
                last_status_audio_s = now
                diagnostic_print(args,
                    '[STATUS] Aufnahme=%s | Blöcke=%d/%d fertig | Queue=%d | RMS=%d'
                    % (
                        fmt_clock(now),
                        stats['completed'],
                        stats['blocks_enqueued'],
                        asr_queue.qsize(),
                        segmenter.last_rms,
                    )
                )

            # Erst beenden, wenn alle vollständigen Detektorframes abgearbeitet sind.
            if source_done and detect_cursor + frame_bytes > audio.working_length():
                break
            await asyncio.sleep(0.02)
    finally:
        if journal is not None:
            journal.writeframes(audio.bytes_between(journal_cursor))
            journal.close()
        if stream is not None:
            stream.stop()
            stream.close()
            args._recording_stream = None

    if cancellation_requested(args):
        raise RecordingCancelled()

    if replay_task is not None and not replay_task.cancelled():
        await replay_task

    emit_for(args, 'phase', phase='audio_stopped')

    # Flush delayed gate frames without shortening the recording.
    audio.finish_gate()
    # Eventuelle letzte Frames noch verarbeiten.
    process_available_frames()

    total = audio.duration()

    # Bereits erzeugte Blöcke, denen am Aufnahmeende echter Nachkontext fehlt,
    # bekommen äquivalente Nullstille; kein Audio wird abgeschnitten.
    await enqueue_ready(force=True)

    # Offenen letzten Kern immer finalisieren. So kann auch sehr leise Sprache,
    # die vom lokalen RMS-Detektor nie als "speech" klassifiziert wurde, nicht
    # allein wegen der Segmentierung verloren gehen.
    if total > segmenter.core_start_s + 0.02:
        final_job = {
            'id': next_block_id,
            'core_start': segmenter.core_start_s,
            'core_end': total,
            'physical_start': max(0.0, segmenter.core_start_s - args.context_seconds),
            'physical_end': total,
            'pad_tail': args.context_seconds,
            'reason': 'final',
            'is_final': True,
        }
        await asr_queue.put(final_job)
        stats['blocks_enqueued'] += 1
        stats['final_cuts'] += 1
        stats['max_queue'] = max(stats['max_queue'], asr_queue.qsize())
        diagnostic_print(args,
            '\n[SCHNITT %03d] %.2f..%.2fs | final | +%.2fs Nullstille'
            % (next_block_id, segmenter.core_start_s, total, args.context_seconds)
        )

    joined = asyncio.create_task(asr_queue.join())
    args._recording_tasks.append(joined)
    while not joined.done():
        if cancellation_requested(args):
            raise RecordingCancelled()
        await asyncio.sleep(.02)
    await joined
    if cancellation_requested(args):
        raise RecordingCancelled()
    await asr_queue.put(None)
    await worker

    # The input source is closed and every queued final block has completed.
    # Only now may later stages attest finalization to Commander.
    args.recording_finalized = not bool(stats['failed'])
    emit_for(args, 'phase', phase='recording_finalized')

    block_results.sort(key=lambda x: x.get('id', 0))

    pcm = audio.all_pcm()
    if ram_only:
        final_wav_path = None
    else:
        output_wav = Path(args.wav)
        input_wav = Path(args.input_wav).resolve() if args.input_wav else None
        if input_wav is not None and output_wav.resolve() == input_wav:
            diagnostic_print(args, '[WAV] Replay-Quelldatei bleibt unverändert: %s' % input_wav)
            final_wav_path = str(input_wav)
        else:
            save_wav(output_wav, pcm)
            final_wav_path = str(output_wav)

    payload = _run_payload(block_results, total, final_wav_path, args, stats)
    if ram_only:
        payload['_audio_wav'] = wav_bytes_from_pcm(pcm)
    else:
        save_json(args.json, payload)

    return payload


# ---------------------------------------------------------------------------
# CLI / Hauptablauf
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description='kienzledoku record 1.8: natürliche Pausen + residenter Final-Block-ASR + pyannote + LLM'
    )
    p.add_argument('--asr', '--final-asr', dest='asr', default='http://127.0.0.1:8179')
    p.add_argument(
        '--asr-api-key',
        default=os.environ.get('KIENZLEDOKU_ASR_API_KEY') or os.environ.get('WLK_API_TOKEN'),
    )
    p.add_argument('--asr-timeout', type=float, default=120.0)
    p.add_argument('--language', default='de')

    p.add_argument('--pause-seconds', type=float, default=0.8)
    p.add_argument('--short-block-pause-seconds', type=float, default=1.5)
    p.add_argument('--min-block-seconds', type=float, default=4.0)
    p.add_argument('--max-block-seconds', type=float, default=20.0)
    p.add_argument('--context-seconds', type=float, default=0.7)
    p.add_argument('--segment-frame-ms', type=int, default=30)

    # Accept old replay scripts without restoring their removed second gate.
    for obsolete in ('--silence-rms', '--auto-rms-min', '--auto-rms-max', '--auto-rms-factor'):
        p.add_argument(obsolete, type=float, default=None, help=argparse.SUPPRESS)

    p.add_argument('--audio-chunk-ms', type=int, default=100)
    p.add_argument('--status-seconds', type=float, default=5.0)
    p.add_argument('--input-wav', default=None,
                   help='Vorhandene 16-kHz/mono/16-bit-WAV statt Mikrofon.')
    p.add_argument('--replay-speed', type=float, default=1.0,
                   help='WAV-Replay: 1=Echtzeit, 0=maximal schnell, 2=doppelte Geschwindigkeit.')
    p.add_argument('--device', default=None)
    p.add_argument('--list-devices', action='store_true')
    p.add_argument('--wav', default='letzte_kienzledoku_aufnahme.wav')
    p.add_argument('--json', default='letzte_kienzledoku_asr.json')

    p.add_argument('--diarization', default='http://127.0.0.1:8183')
    p.add_argument('--no-diarization', action='store_true')
    p.add_argument('--require-diarization', action='store_true')
    p.add_argument('--num-speakers', type=int, default=None)
    p.add_argument('--min-speakers', type=int, default=1)
    p.add_argument('--max-speakers', type=int, default=4)
    p.add_argument('--diarization-timeout', type=float, default=300.0)

    p.add_argument('--llm', default='http://127.0.0.1:8080')
    p.add_argument('--llm-api-key', default=os.environ.get('KIENZLEDOKU_LLM_API_KEY'))
    p.add_argument('--llm-model', default=None)
    p.add_argument('--prompt-file', default=str(Path(__file__).with_name('prompt.txt')))
    p.add_argument('--temperature', type=float, default=0.1)
    p.add_argument('--max-tokens', type=int, default=1600)
    p.add_argument('--no-llm', action='store_true')
    p.add_argument('--commander', default=None,
                   help='Commander-Basisadresse; übernimmt alle drei KI-Dienste.')
    p.add_argument('--commander-token-env', default='KIENZLEDOKU_COMMANDER_TOKEN')
    p.add_argument('--commander-timeout', type=float, default=14400)
    p.add_argument('--quality', default='auto')
    p.add_argument('--allow-partial-asr', action='store_true',
                   help='Trotz fehlgeschlagener ASR-Blöcke Diarisierung/LLM fortsetzen.')
    args = p.parse_args()
    args.commander_client = None
    args.commander_metadata = None
    args.recording_finalized = False
    if args.commander:
        try:
            client = CommanderClient(args.commander, args.commander_token_env,
                                     args.commander_timeout)
            args.asr = args.diarization = args.llm = client.url
            args.asr_api_key = args.llm_api_key = client.token
            args.asr_timeout = args.diarization_timeout = client.timeout
            args.commander_client = client
        except ValueError as exc:
            p.error(str(exc))
    return args


def main():
    configure_output_encoding()
    args = parse_args()

    if args.list_devices:
        try:
            import sounddevice as sd
        except Exception as exc:
            print('FEHLER sounddevice:', exc, file=sys.stderr)
            return 1
        print(sd.query_devices())
        return 0

    if args.replay_speed < 0:
        print('FEHLER: --replay-speed muss >= 0 sein.', file=sys.stderr)
        return 2

    try:
        payload = asyncio.run(run_recording(args))
    except KeyboardInterrupt:
        print('\nAbgebrochen.')
        return 130
    except Exception as exc:
        print('\nFEHLER ASR/AUDIO:', exc, file=sys.stderr)
        return 1

    transcript = payload.get('transcript') or ''
    asr_words = payload.get('words') or []
    asr_segments = payload.get('segments') or []
    stats = payload.get('metrics') or {}
    duration = float(payload.get('audio_duration') or 0.0)
    final_wav_path = payload.get('wav')

    print('\n=== TRANSKRIPT OHNE SPRECHER ===')
    print(transcript or '(leer)')
    print('\n=== METRIK ===')
    print('Audio:             %.2f s' % duration)
    print('Final-Blöcke:      %d' % stats.get('blocks_enqueued', 0))
    print('  natürliche Pause:%d' % stats.get('natural_cuts', 0))
    print('  kurze Äußerung:  %d' % stats.get('short_block_cuts', 0))
    print('  Failsafe max:    %d' % stats.get('failsafe_cuts', 0))
    print('  final:           %d' % stats.get('final_cuts', 0))
    print('ASR-Wörter:        %d' % len(asr_words))
    print('ASR-Segmente:      %d' % len(asr_segments))
    print('ASR-Fehler:        %d' % stats.get('failed', 0))
    print('Max. ASR-Queue:    %d' % stats.get('max_queue', 0))
    print('ASR-Server-Summe:  %.3f s' % stats.get('asr_server_seconds_sum', 0.0))
    print('WAV:               %s' % final_wav_path)
    print('JSON:              %s' % args.json)

    if stats.get('failed', 0) and (args.commander or not args.allow_partial_asr):
        print(
            '\nFEHLER: Mindestens ein Final-ASR-Block ist fehlgeschlagen. '
            'WAV und JSON wurden gespeichert; Diarisierung/LLM werden absichtlich nicht mit Teiltranskript gestartet.\n'
            'Mit --allow-partial-asr kann dieses Verhalten für Diagnosezwecke übersteuert werden.',
            file=sys.stderr,
        )
        return 3

    if not transcript.strip():
        print('Keine Sprache erkannt. Keine Diarisierung oder LLM-Dokumentation erstellt.')
        return 0

    llm_transcript = transcript
    diarization_result = None
    speaker_text = None

    if not args.no_diarization:
        print('\n=== SPRECHERDIARISIERUNG ===')
        emit_event('phase', phase='diarization')
        try:
            t0 = time.monotonic()
            result = diarize_wav(
                args.diarization,
                final_wav_path,
                args.min_speakers,
                args.max_speakers,
                args.num_speakers,
                args.diarization_timeout,
                api_key=args.commander_client.token if args.commander_client else None,
                recording_finalized=bool(args.commander and payload.get('recording_finalized')),
                commander=bool(args.commander),
            )
            diarization_result = result
            diar_segments = result.get('segments') or []
            print(
                'Diarisierung: %.2f s | Sprecher=%s | Segmente=%d | Modus=%s'
                % (
                    time.monotonic() - t0,
                    ','.join(result.get('speakers') or []),
                    len(diar_segments),
                    result.get('mode', '?'),
                )
            )
            if asr_words:
                rendered, paragraphs = speaker_transcript_words(asr_words, diar_segments)
                speaker_mode = 'wortzeitstempel'
            else:
                rendered, paragraphs = speaker_transcript(asr_segments, diar_segments)
                speaker_mode = 'segment_fallback'

            if rendered:
                print('\n=== TRANSKRIPT MIT SPRECHERN ===')
                print('[SPRECHER-MAPPING] Modus=%s' % speaker_mode)
                print(rendered)
                llm_transcript = rendered
                speaker_text = rendered
            else:
                print('WARNUNG: Sprecherzuordnung nicht möglich; verwende ASR-Text ohne Sprecher.')
        except Exception as exc:
            print('WARNUNG Diarisierung:', exc, file=sys.stderr)
            if args.require_diarization:
                return 2
            print('Fahre mit dem ASR-Text ohne Sprecher fort.')

    emit_event(
        'diarization',
        text=llm_transcript,
        speaker_labels=bool(speaker_text),
    )

    llm_answer = None
    if args.no_llm:
        print('\nLLM übersprungen (--no-llm).')
    elif not llm_transcript.strip():
        print('\nKein Transkript; LLM wird nicht aufgerufen.')
    else:
        print('\n=== LLM ===')
        emit_event('phase', phase='llm')
        try:
            t0 = time.monotonic()
            if args.commander_client:
                document, metadata = args.commander_client.extract(
                    llm_transcript, args.quality, args.commander_client.profiles(),
                    recording_finalized=payload.get('recording_finalized') is True)
                args.commander_metadata = metadata
                emit_event('commander_result', **metadata)
                llm_answer = json.dumps(document, ensure_ascii=False)
            else:
                llm_answer = call_llm(args, llm_transcript)
            print(llm_answer)
            print('\nLLM-Zeit: %.3f s' % (time.monotonic() - t0))
        except Exception as exc:
            print('FEHLER LLM:', exc, file=sys.stderr)
            # JSON trotzdem mit Diarisierung aktualisieren.
            final_payload = _run_payload(
                payload.get('blocks') or [], duration, final_wav_path, args, stats,
                diarization=diarization_result, speaker_text=speaker_text, llm=None,
            )
            save_json(args.json, final_payload)
            return 1

    final_payload = _run_payload(
        payload.get('blocks') or [], duration, final_wav_path, args, stats,
        diarization=diarization_result, speaker_text=speaker_text, llm=llm_answer,
    )
    save_json(args.json, final_payload)
    emit_event('complete')
    return 0


if __name__ == '__main__':
    sys.exit(main())
