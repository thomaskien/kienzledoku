#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local pyannote Community-1 service, accelerated by Apple MPS only."""

from __future__ import annotations

import argparse
import io
import json
import os
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


HOST = os.environ.get("KIENZLEDOKU_DIARIZATION_HOST", "127.0.0.1")
PORT = int(os.environ.get("KIENZLEDOKU_DIARIZATION_PORT", "8183"))
MODEL_DIR = os.environ.get("KIENZLEDOKU_PYANNOTE_MODEL", "")
MODEL_ID = "pyannote/speaker-diarization-community-1"
MODEL_REVISION = "3533c8cf8e369892e6b79ff1bf80f7b0286a54ee"
MAX_BYTES = int(
    os.environ.get("KIENZLEDOKU_DIARIZATION_MAX_BYTES", str(100 * 1024 * 1024))
)

RUNTIME: dict[str, object] = {}
PIPELINE_LOCK = threading.Lock()


def validate_pcm16_mono_16k(wav_bytes: bytes) -> bytes:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        compression = wav_file.getcomptype()
        frames = wav_file.readframes(wav_file.getnframes())
    if (channels, sample_width, sample_rate, compression) != (1, 2, 16000, "NONE"):
        raise ValueError(
            "Erwartet wird PCM-WAV mono/16-bit/16-kHz; erhalten: "
            "Kanäle=%d, Samplebreite=%d, Rate=%d, Kompression=%s"
            % (channels, sample_width, sample_rate, compression)
        )
    return frames


def pcm16_mono_16k(wav_bytes: bytes):
    import numpy as np

    frames = validate_pcm16_mono_16k(wav_bytes)
    waveform = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    return waveform


def annotation_segments(annotation) -> list[dict]:
    output = []
    if annotation is None:
        return output
    try:
        for turn, speaker in annotation:
            output.append(
                {"start": float(turn.start), "end": float(turn.end), "speaker": str(speaker)}
            )
        return output
    except Exception:
        output = []
    try:
        for turn, _track, speaker in annotation.itertracks(yield_label=True):
            output.append(
                {"start": float(turn.start), "end": float(turn.end), "speaker": str(speaker)}
            )
    except Exception as exc:
        raise RuntimeError("Unbekanntes pyannote-Ausgabeformat: %s" % exc) from exc
    return output


def load_runtime() -> None:
    if not MODEL_DIR or not os.path.isdir(MODEL_DIR):
        raise RuntimeError("Lokales pyannote-Modellverzeichnis fehlt: %s" % MODEL_DIR)

    import importlib.metadata
    import torch
    from pyannote.audio import Pipeline

    if not torch.backends.mps.is_built() or not torch.backends.mps.is_available():
        raise RuntimeError("PyTorch MPS ist nicht verfügbar; kein CPU-Fallback")
    if os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK", "0") not in ("0", "false", "False"):
        raise RuntimeError("PYTORCH_ENABLE_MPS_FALLBACK muss deaktiviert bleiben")

    device = torch.device("mps")
    pipeline = Pipeline.from_pretrained(MODEL_DIR)
    pipeline.to(device)
    torch.mps.synchronize()
    RUNTIME.update(
        {
            "torch": torch,
            "pipeline": pipeline,
            "device": device,
            "torch_version": torch.__version__,
            "pyannote_version": importlib.metadata.version("pyannote.audio"),
        }
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "KienzledokuPyannoteMPS/1.0"

    def log_message(self, fmt, *args):
        # Only technical HTTP metadata. Never log audio or transcript content.
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def send_json(self, status: int, payload: dict) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if urlsplit(self.path).path != "/health":
            self.send_json(404, {"error": "not_found"})
            return
        torch = RUNTIME["torch"]
        self.send_json(
            200,
            {
                "ok": True,
                "model": MODEL_ID,
                "revision": MODEL_REVISION,
                "device": "mps",
                "resident": True,
                "mps_available": torch.backends.mps.is_available(),
                "torch": RUNTIME["torch_version"],
                "pyannote_audio": RUNTIME["pyannote_version"],
                "allocated_memory_mb": round(
                    torch.mps.current_allocated_memory() / 1024 / 1024, 1
                ),
            },
        )

    def do_POST(self):
        parsed = urlsplit(self.path)
        if parsed.path != "/v1/diarize":
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
            query = parse_qs(parsed.query)

            def one_int(name):
                values = query.get(name)
                if not values:
                    return None
                value = int(values[0])
                if not 1 <= value <= 20:
                    raise ValueError("%s muss zwischen 1 und 20 liegen" % name)
                return value

            num_speakers = one_int("num_speakers")
            min_speakers = one_int("min_speakers")
            max_speakers = one_int("max_speakers")
            if min_speakers and max_speakers and min_speakers > max_speakers:
                raise ValueError("min_speakers darf nicht größer als max_speakers sein")

            call_kwargs = {}
            if num_speakers is not None:
                call_kwargs["num_speakers"] = num_speakers
            else:
                if min_speakers is not None:
                    call_kwargs["min_speakers"] = min_speakers
                if max_speakers is not None:
                    call_kwargs["max_speakers"] = max_speakers

            waveform = pcm16_mono_16k(self.rfile.read(length))
            torch = RUNTIME["torch"]
            audio_input = {
                "waveform": torch.from_numpy(waveform.copy()).unsqueeze(0),
                "sample_rate": 16000,
            }
            with PIPELINE_LOCK, torch.inference_mode():
                result = RUNTIME["pipeline"](audio_input, **call_kwargs)
                torch.mps.synchronize()

            annotation = getattr(result, "exclusive_speaker_diarization", None)
            mode = "exclusive"
            if annotation is None:
                annotation = getattr(result, "speaker_diarization", None)
                mode = "regular"
            segments = annotation_segments(annotation)
            self.send_json(
                200,
                {
                    "ok": True,
                    "model": MODEL_ID,
                    "revision": MODEL_REVISION,
                    "device": "mps",
                    "mode": mode,
                    "speakers": sorted({item["speaker"] for item in segments}),
                    "segments": segments,
                },
            )
        except ValueError as exc:
            self.send_json(400, {"error": "invalid_request", "detail": str(exc)})
        except Exception as exc:
            print("Diarisierungsfehler: %r" % (exc,), flush=True)
            self.send_json(500, {"error": "diarization_failed", "detail": str(exc)})


def self_test() -> None:
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\0\0" * 1600)
    frames = validate_pcm16_mono_16k(wav_buffer.getvalue())
    assert len(frames) == 3200

    class Turn:
        start = 0.1
        end = 0.2

    segments = annotation_segments([(Turn(), "SPEAKER_00")])
    assert segments == [{"start": 0.1, "end": 0.2, "speaker": "SPEAKER_00"}]
    json.dumps(segments)
    print("Pyannote-Selbsttest erfolgreich.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    load_runtime()
    print(
        "pyannote Community-1 resident | MPS-only | %s:%d | Modell=%s"
        % (HOST, PORT, MODEL_DIR),
        flush=True,
    )
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
