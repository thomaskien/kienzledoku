#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kienzledoku Final-Block-ASR with resident Whisper large-v3 on MLX/Metal."""

from __future__ import annotations

import argparse
import io
import json
import os
import time
import wave
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit


HOST = os.environ.get("KIENZLEDOKU_ASR_HOST", "127.0.0.1")
PORT = int(os.environ.get("KIENZLEDOKU_ASR_PORT", "8179"))
MODEL_DIR = os.environ.get("KIENZLEDOKU_WHISPER_MODEL", "")
MODEL_ID = "mlx-community/whisper-large-v3-mlx"
MAX_BYTES = int(os.environ.get("KIENZLEDOKU_ASR_MAX_BYTES", str(100 * 1024 * 1024)))

RUNTIME: dict[str, object] = {}


def json_default(value):
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "tolist"):
        return value.tolist()
    raise TypeError("Nicht JSON-serialisierbar: %s" % type(value).__name__)


def parse_multipart(content_type: str, body: bytes) -> tuple[bytes, str]:
    if not content_type.lower().startswith("multipart/form-data"):
        raise ValueError("Content-Type muss multipart/form-data sein")
    raw = (
        b"Content-Type: "
        + content_type.encode("ascii", errors="strict")
        + b"\r\nMIME-Version: 1.0\r\n\r\n"
        + body
    )
    message = BytesParser(policy=policy.default).parsebytes(raw)
    audio = None
    language = "de"
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        payload = part.get_payload(decode=True) or b""
        if name == "file":
            audio = payload
        elif name == "language":
            language = payload.decode("utf-8", errors="strict").strip() or "de"
    if not audio:
        raise ValueError("Multipart-Feld 'file' fehlt oder ist leer")
    if len(language) > 16:
        raise ValueError("Sprachkennung ist zu lang")
    return audio, language


def validate_pcm16_mono_16k(wav_bytes: bytes) -> tuple[bytes, float]:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        frame_count = wav_file.getnframes()
        compression = wav_file.getcomptype()
        frames = wav_file.readframes(frame_count)
    if (channels, sample_width, sample_rate, compression) != (1, 2, 16000, "NONE"):
        raise ValueError(
            "Erwartet wird PCM-WAV mono/16-bit/16-kHz; erhalten: "
            "Kanäle=%d, Samplebreite=%d, Rate=%d, Kompression=%s"
            % (channels, sample_width, sample_rate, compression)
        )
    return frames, frame_count / 16000.0


def pcm16_mono_16k(wav_bytes: bytes):
    import numpy as np

    frames, duration = validate_pcm16_mono_16k(wav_bytes)
    audio = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    return audio, duration


def normalize_result(result: dict, processing_seconds: float, duration: float) -> dict:
    segments = []
    words = []
    for source_segment in result.get("segments") or []:
        segment = {
            "start": float(source_segment.get("start", 0.0)),
            "end": float(source_segment.get("end", 0.0)),
            "text": str(source_segment.get("text") or "").strip(),
        }
        segments.append(segment)
        for source_word in source_segment.get("words") or []:
            word = {
                "start": float(source_word.get("start", 0.0)),
                "end": float(source_word.get("end", 0.0)),
                "word": str(source_word.get("word") or ""),
            }
            probability = source_word.get("probability")
            if isinstance(probability, (int, float)):
                word["probability"] = float(probability)
            words.append(word)
    return {
        "text": str(result.get("text") or "").strip(),
        "language": str(result.get("language") or "de"),
        "segments": segments,
        "words": words,
        "processing_seconds": processing_seconds,
        "rtf": (processing_seconds / duration) if duration > 0 else None,
        "duration": duration,
        "decoder": "mlx-whisper-large-v3",
        "model": MODEL_ID,
        "device": "metal",
    }


def load_runtime() -> None:
    if not MODEL_DIR or not os.path.isdir(MODEL_DIR):
        raise RuntimeError("Lokales Whisper-Modellverzeichnis fehlt: %s" % MODEL_DIR)

    import importlib.metadata
    import mlx.core as mx
    import mlx_whisper
    from mlx_whisper.transcribe import ModelHolder

    if not mx.metal.is_available():
        raise RuntimeError("MLX meldet Metal als nicht verfügbar; kein CPU-Fallback")

    # Populate mlx-whisper's own process-wide model holder. Subsequent
    # transcriptions reuse these weights instead of loading them again.
    model = ModelHolder.get_model(MODEL_DIR, mx.float16)
    mx.eval(model.parameters())
    RUNTIME.update(
        {
            "mx": mx,
            "mlx_whisper": mlx_whisper,
            "mlx_version": importlib.metadata.version("mlx"),
            "mlx_whisper_version": importlib.metadata.version("mlx-whisper"),
            "metal_device": mx.metal.device_info(),
        }
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "KienzledokuMLXASR/1.0"

    def log_message(self, fmt, *args):
        # Only technical request metadata. Never log audio or transcripts.
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def send_json(self, status: int, payload: dict) -> None:
        raw = json.dumps(payload, ensure_ascii=False, default=json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/health":
            mx = RUNTIME["mx"]
            self.send_json(
                200,
                {
                    "ok": True,
                    "model": MODEL_ID,
                    "device": "metal",
                    "resident": True,
                    "mlx": RUNTIME["mlx_version"],
                    "mlx_whisper": RUNTIME["mlx_whisper_version"],
                    "metal": RUNTIME["metal_device"],
                    "active_memory_mb": round(mx.metal.get_active_memory() / 1024 / 1024, 1),
                },
            )
        elif path == "/v1/models":
            self.send_json(
                200,
                {"object": "list", "data": [{"id": "whisper-large-v3", "object": "model"}]},
            )
        else:
            self.send_json(404, {"error": "not_found"})

    def do_POST(self):
        if urlsplit(self.path).path != "/v1/asr/final-block":
            self.send_json(404, {"error": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BYTES:
            self.send_json(413, {"error": "invalid_content_length"})
            return

        try:
            wav_bytes, language = parse_multipart(
                self.headers.get("Content-Type", ""), self.rfile.read(length)
            )
            audio, duration = pcm16_mono_16k(wav_bytes)
            started = time.monotonic()
            # MLX streams are thread-local. load_runtime() and inference must
            # therefore stay on the same server thread. Kienzledoku already
            # queues Final-ASR blocks serially, so a single HTTPServer is the
            # correct execution model for one resident Whisper instance.
            result = RUNTIME["mlx_whisper"].transcribe(
                audio,
                path_or_hf_repo=MODEL_DIR,
                language=language,
                word_timestamps=True,
                condition_on_previous_text=False,
                verbose=None,
                fp16=True,
            )
            elapsed = time.monotonic() - started
            self.send_json(200, normalize_result(result, elapsed, duration))
        except ValueError as exc:
            self.send_json(400, {"error": "invalid_request", "detail": str(exc)})
        except Exception as exc:
            print("Final-Block-ASR-Fehler: %r" % (exc,), flush=True)
            self.send_json(500, {"error": "asr_failed", "detail": str(exc)})


def self_test() -> None:
    boundary = "----test-boundary"
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\0\0" * 1600)
    body = (
        ("--%s\r\n" % boundary).encode()
        + b'Content-Disposition: form-data; name="file"; filename="test.wav"\r\n'
        + b"Content-Type: audio/wav\r\n\r\n"
        + wav_buffer.getvalue()
        + ("\r\n--%s\r\n" % boundary).encode()
        + b'Content-Disposition: form-data; name="language"\r\n\r\nde\r\n'
        + ("--%s--\r\n" % boundary).encode()
    )
    audio_bytes, language = parse_multipart(
        "multipart/form-data; boundary=%s" % boundary, body
    )
    assert language == "de"
    _, duration = validate_pcm16_mono_16k(audio_bytes)
    assert abs(duration - 0.1) < 1e-9
    normalized = normalize_result(
        {"text": "Test", "language": "de", "segments": []}, 0.05, duration
    )
    assert normalized["decoder"] == "mlx-whisper-large-v3"
    json.dumps(normalized)
    print("ASR-Selbsttest erfolgreich.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    load_runtime()
    print(
        "Whisper large-v3 resident | MLX/Metal | %s:%d | Modell=%s"
        % (HOST, PORT, MODEL_DIR),
        flush=True,
    )
    HTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
