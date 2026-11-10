#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Optionaler lokaler pyannote Community-1-Dienst für Kienzlefon AI 2.0."""

import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import torch
import torchaudio
from pyannote.audio import Pipeline

HOST = os.environ.get('DIARIZATION_HOST', '0.0.0.0')
PORT = int(os.environ.get('DIARIZATION_PORT', '8183'))
MODEL = os.environ.get('PYANNOTE_MODEL', 'pyannote/speaker-diarization-community-1')
DEVICE = os.environ.get('DIARIZATION_DEVICE', 'cuda:0').strip().lower()
TOKEN = os.environ.get('HF_TOKEN') or os.environ.get('HUGGINGFACE_TOKEN')
MAX_BYTES = int(os.environ.get('DIARIZATION_MAX_BYTES', str(100 * 1024 * 1024)))

print('Lade Diarisierungsmodell:', MODEL, flush=True)
kwargs = {}
if TOKEN:
    kwargs['token'] = TOKEN
if not DEVICE.startswith('cuda'):
    raise RuntimeError(
        'Dieser WhisperDoku-Dienst ist absichtlich GPU-only. '
        'DIARIZATION_DEVICE muss cuda oder cuda:N sein.'
    )

if not torch.cuda.is_available():
    raise RuntimeError(
        'CUDA ist für PyTorch nicht verfügbar. Kein CPU-Fallback erlaubt.'
    )

device = torch.device(DEVICE)
gpu_index = 0 if device.index is None else device.index
if gpu_index >= torch.cuda.device_count():
    raise RuntimeError(
        'Angeforderte GPU %d existiert nicht; verfügbar: %d'
        % (gpu_index, torch.cuda.device_count())
    )

gpu_name = torch.cuda.get_device_name(gpu_index)
torch.set_float32_matmul_precision('high')

pipeline = Pipeline.from_pretrained(MODEL, **kwargs)
pipeline.to(device)

print(
    'Diarisierungsmodell bereit | device=%s | gpu=%s | torch_cuda=%s | port=%d'
    % (DEVICE, gpu_name, torch.version.cuda, PORT),
    flush=True,
)

pipeline_lock = threading.Lock()


def annotation_segments(annotation):
    out = []
    if annotation is None:
        return out
    try:
        for turn, speaker in annotation:
            out.append({
                'start': float(turn.start),
                'end': float(turn.end),
                'speaker': str(speaker),
            })
        return out
    except Exception:
        pass
    try:
        for turn, track, speaker in annotation.itertracks(yield_label=True):
            out.append({
                'start': float(turn.start),
                'end': float(turn.end),
                'speaker': str(speaker),
            })
    except Exception as exc:
        raise RuntimeError('Unbekanntes pyannote-Ausgabeformat: %s' % exc)
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = 'KienzlefonDiarization/2.0'

    def log_message(self, fmt, *args):
        # Nur technische HTTP-Metadaten; niemals Audio/Transkriptinhalt loggen.
        print('%s - %s' % (self.address_string(), fmt % args), flush=True)

    def send_json(self, status, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if urlsplit(self.path).path == '/health':
            self.send_json(200, {
                'ok': True,
                'model': MODEL,
                'device': DEVICE,
                'gpu': gpu_name,
                'torch_cuda': torch.version.cuda,
                'cuda_available': torch.cuda.is_available(),
                'vram_allocated_mb': round(torch.cuda.memory_allocated(gpu_index) / 1024 / 1024, 1),
                'vram_reserved_mb': round(torch.cuda.memory_reserved(gpu_index) / 1024 / 1024, 1),
            })
        else:
            self.send_json(404, {'error': 'not_found'})

    def do_POST(self):
        parsed = urlsplit(self.path)
        if parsed.path != '/v1/diarize':
            self.send_json(404, {'error': 'not_found'})
            return

        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BYTES:
            self.send_json(413, {'error': 'invalid_content_length'})
            return

        body = self.rfile.read(length)
        query = parse_qs(parsed.query)

        def one_int(name):
            values = query.get(name)
            if not values:
                return None
            return int(values[0])

        num_speakers = one_int('num_speakers')
        min_speakers = one_int('min_speakers')
        max_speakers = one_int('max_speakers')

        call_kwargs = {}
        if num_speakers is not None:
            call_kwargs['num_speakers'] = num_speakers
        else:
            if min_speakers is not None:
                call_kwargs['min_speakers'] = min_speakers
            if max_speakers is not None:
                call_kwargs['max_speakers'] = max_speakers

        tmp_name = None
        try:
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                tmp.write(body)
                tmp_name = tmp.name

            # Audio einmal in den Speicher laden. Pyannote empfiehlt diese
            # Form für schnellere Verarbeitung und vermeidet wiederholtes
            # Dateidecoding innerhalb der Pipeline.
            waveform, sample_rate = torchaudio.load(tmp_name)
            audio_input = {
                'waveform': waveform,
                'sample_rate': sample_rate,
            }

            with pipeline_lock, torch.inference_mode():
                output = pipeline(audio_input, **call_kwargs)

            exclusive = getattr(output, 'exclusive_speaker_diarization', None)
            if exclusive is not None:
                annotation = exclusive
                mode = 'exclusive'
            else:
                annotation = getattr(output, 'speaker_diarization', None)
                mode = 'regular'

            segments = annotation_segments(annotation)
            speakers = sorted({x['speaker'] for x in segments})
            self.send_json(200, {
                'ok': True,
                'model': MODEL,
                'device': DEVICE,
                'mode': mode,
                'speakers': speakers,
                'segments': segments,
            })
        except Exception as exc:
            print('Diarisierungsfehler: %r' % (exc,), flush=True)
            self.send_json(500, {'error': 'diarization_failed', 'detail': str(exc)})
        finally:
            if tmp_name:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass


if __name__ == '__main__':
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print('WhisperDoku Diarisierung auf %s:%d' % (HOST, PORT), flush=True)
    httpd.serve_forever()
