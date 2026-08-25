#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "FEHLER: Bitte als root ausführen." >&2
  exit 1
fi

SERVICE=kienzlefon-ai-asr-backend.service
EXPECTED_SHA256=ae89062f8f7146a130e48b973187cd81f6451a672d93bc04e9ec1fcbb28fe78f
MARKER='WhisperDoku v6 final-block endpoint'

PY=""
for candidate in \
  /opt/kienzlefon-ai-v2/python/asr-venv/bin/python \
  /opt/kienzlefon-ai/python/asr-venv/bin/python
do
  if [[ -x "$candidate" ]]; then
    PY="$candidate"
    break
  fi
done

if [[ -z "$PY" ]]; then
  echo "FEHLER: ASR-Python weder im v2- noch im Legacy-Pfad gefunden." >&2
  echo "Zuerst den Linux-ASR-Server installieren." >&2
  exit 1
fi

WLK_DIR="$($PY - <<'PY'
import pathlib
import whisperlivekit
print(pathlib.Path(whisperlivekit.__file__).resolve().parent)
PY
)"
TARGET="$WLK_DIR/basic_server.py"

if [[ ! -f "$TARGET" ]]; then
  echo "FEHLER: basic_server.py nicht gefunden: $TARGET" >&2
  exit 1
fi

if grep -qF "$MARKER" "$TARGET"; then
  echo "BEREITS_INSTALLIERT: $TARGET"
  exit 0
fi

ACTUAL_SHA256="$(sha256sum "$TARGET" | awk '{print $1}')"
if [[ "$ACTUAL_SHA256" != "$EXPECTED_SHA256" ]]; then
  echo "FEHLER: basic_server.py entspricht nicht der hochgeladenen/analysierten Ausgangsdatei." >&2
  echo "Erwartet: $EXPECTED_SHA256" >&2
  echo "Gefunden: $ACTUAL_SHA256" >&2
  echo "ABBRUCH – es wird ausdrücklich nichts rekonstruiert oder auf unbekannten Code gepatcht." >&2
  exit 1
fi

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="/root/kienzlefon-final-block-v6-server-$STAMP"
mkdir -p "$BACKUP_DIR"
cp -a "$TARGET" "$BACKUP_DIR/basic_server.py"
printf '%s\n' "$BACKUP_DIR" > /root/kienzlefon-final-block-v6-server-LAST

echo "Backup: $BACKUP_DIR/basic_server.py"

TARGET="$TARGET" "$PY" - <<'PY'
from pathlib import Path
import os
import sys

p = Path(os.environ["TARGET"])
text = p.read_text(encoding="utf-8")

marker = "WhisperDoku v6 final-block endpoint"
if marker in text:
    print("BEREITS_INSTALLIERT")
    raise SystemExit(0)

old_imports = '''import asyncio
import hmac
import logging
import os
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, File, Form, Request, UploadFile, WebSocket, WebSocketDisconnect
'''
new_imports = '''import asyncio
import hmac
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import List, Optional

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
'''

old_lifespan = '''@asynccontextmanager
async def lifespan(app: FastAPI):
    global transcription_engine
    transcription_engine = TranscriptionEngine(config=config)
    yield
'''
new_lifespan = '''@asynccontextmanager
async def lifespan(app: FastAPI):
    global transcription_engine
    transcription_engine = TranscriptionEngine(config=config)
    # WhisperDoku v6 final-block endpoint: final jobs are serialized so that
    # multiple completed blocks never run through the resident CT2 model at once.
    app.state.final_asr_lock = asyncio.Lock()
    yield
'''

anchor = '''@app.get("/v1/models")
async def list_models():
'''

endpoint = r'''
# ---------------------------------------------------------------------------
# WhisperDoku v6 final-block endpoint  (/v1/asr/final-block)
# ---------------------------------------------------------------------------

def _get_resident_faster_whisper_model():
    """Return the Faster-Whisper model already resident inside SimulStreaming."""
    global transcription_engine
    if transcription_engine is None:
        raise RuntimeError("transcription engine is not initialized")
    asr = getattr(transcription_engine, "asr", None)
    model = getattr(asr, "fw_encoder", None)
    if model is None:
        raise RuntimeError(
            "resident Faster-Whisper model is unavailable; "
            "this endpoint requires faster-whisper + simulstreaming"
        )
    return model


def _transcribe_final_block_sync(model, audio: np.ndarray, language: Optional[str]) -> dict:
    """Reference-quality final decode on the already loaded Faster-Whisper model."""
    segments_iter, info = model.transcribe(
        audio,
        language=language,
        task="transcribe",
        beam_size=5,
        best_of=5,
        temperature=0.0,
        vad_filter=False,
        word_timestamps=True,
        condition_on_previous_text=False,
    )

    out_segments = []
    out_words = []
    text_parts = []

    for seg in segments_iter:
        seg_text = str(getattr(seg, "text", "") or "")
        text_parts.append(seg_text)
        seg_words = []
        for word in (getattr(seg, "words", None) or []):
            item = {
                "start": float(word.start),
                "end": float(word.end),
                "word": str(word.word),
            }
            probability = getattr(word, "probability", None)
            if probability is not None:
                item["probability"] = float(probability)
            seg_words.append(item)
            out_words.append(item.copy())

        out_segments.append({
            "id": int(getattr(seg, "id", len(out_segments))),
            "seek": int(getattr(seg, "seek", 0)),
            "start": float(seg.start),
            "end": float(seg.end),
            "text": seg_text,
            "words": seg_words,
        })

    return {
        "text": "".join(text_parts).strip(),
        "language": getattr(info, "language", language),
        "language_probability": getattr(info, "language_probability", None),
        "segments": out_segments,
        "words": out_words,
    }


@app.post("/v1/asr/final-block")
async def create_final_block_transcription(
    request: Request,
    file: UploadFile = File(...),
    language: Optional[str] = Form(default=None),
):
    """Decode one completed audio block with the resident Faster-Whisper model.

    This deliberately bypasses AudioProcessor/SimulStreaming and therefore does
    not use provisional streaming hypotheses.  Parameters mirror the validated
    WhisperDoku offline-v2 reference run.
    """
    if not _token_ok(_bearer_token(request)):
        raise HTTPException(status_code=401, detail="invalid or missing API token")

    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file")

    max_upload_mb = 64
    if len(audio_bytes) > max_upload_mb * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"Audio block exceeds the {max_upload_mb} MB upload limit",
        )

    pcm_data = await _convert_to_pcm(audio_bytes)
    if not pcm_data:
        raise HTTPException(status_code=400, detail="Decoded audio is empty")

    # _convert_to_pcm guarantees mono, 16 kHz, signed PCM16 little-endian.
    audio = np.frombuffer(pcm_data, dtype="<i2").astype(np.float32) / 32768.0
    duration = len(audio) / 16000.0

    resolved_language = language or getattr(config, "lan", None) or "de"
    if resolved_language == "auto":
        resolved_language = None

    try:
        model = _get_resident_faster_whisper_model()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    started = time.perf_counter()
    lock = request.app.state.final_asr_lock
    try:
        async with lock:
            result = await asyncio.to_thread(
                _transcribe_final_block_sync,
                model,
                audio,
                resolved_language,
            )
    except Exception as exc:
        logger.exception("Final-block transcription failed")
        raise HTTPException(status_code=500, detail=f"Final-block transcription failed: {exc}") from exc

    elapsed = time.perf_counter() - started
    result.update({
        "duration": round(duration, 6),
        "processing_seconds": round(elapsed, 6),
        "rtf": round(elapsed / duration, 6) if duration > 0 else None,
        "mode": "final-block",
        "decoder": {
            "beam_size": 5,
            "best_of": 5,
            "temperature": 0.0,
            "vad_filter": False,
            "word_timestamps": True,
            "condition_on_previous_text": False,
        },
    })
    return JSONResponse(result)


'''

checks = [
    (old_imports, "Importblock"),
    (old_lifespan, "lifespan-Block"),
    (anchor, "v1/models-Anker"),
]
for needle, label in checks:
    count = text.count(needle)
    if count != 1:
        print(f"FEHLER: {label} nicht exakt einmal gefunden (count={count}).")
        sys.exit(1)

text = text.replace(old_imports, new_imports, 1)
text = text.replace(old_lifespan, new_lifespan, 1)
text = text.replace(anchor, endpoint + anchor, 1)
p.write_text(text, encoding="utf-8")
print("PATCH_OK")
PY

if ! "$PY" -m py_compile "$TARGET"; then
  echo "FEHLER: Python-Syntaxprüfung fehlgeschlagen; stelle Backup wieder her." >&2
  cp -a "$BACKUP_DIR/basic_server.py" "$TARGET"
  exit 1
fi

echo "Python-Syntax: OK"

systemctl restart "$SERVICE"
sleep 5

if ! systemctl is-active --quiet "$SERVICE"; then
  echo "FEHLER: ASR-Backend startet nach Patch nicht. Rollback wird ausgeführt." >&2
  systemctl --no-pager --full status "$SERVICE" || true
  journalctl -u "$SERVICE" -n 80 --no-pager || true
  cp -a "$BACKUP_DIR/basic_server.py" "$TARGET"
  systemctl restart "$SERVICE" || true
  exit 1
fi

if ! curl -fsS http://127.0.0.1:8179/health >/dev/null; then
  echo "FEHLER: Healthcheck fehlgeschlagen. Rollback wird ausgeführt." >&2
  cp -a "$BACKUP_DIR/basic_server.py" "$TARGET"
  systemctl restart "$SERVICE" || true
  exit 1
fi

echo
echo "INSTALL_OK"
echo "Endpoint: http://127.0.0.1:8179/v1/asr/final-block"
echo "ASR-Python: $PY"
echo "Modell wird beim Dienststart einmal geladen und danach pro Block wiederverwendet."
echo
echo "Prozess:"
pgrep -af '/wlk' || true
