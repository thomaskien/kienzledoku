"""On-demand Whisper Turbo int8 final-block backend. Audio stays in memory."""
import gc
import io
import json
import os
import time
import wave
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, HTTPServer
from kienzledoku_commander.worker import Controller, serve_control, close_control

MODEL=None
MODEL_PATH=os.environ.get('KIENZLEDOKU_WHISPER_MODEL','')
MAX_BYTES=256*1024*1024

def load(_request):
    global MODEL
    if MODEL is None:
        from faster_whisper import WhisperModel
        MODEL=WhisperModel(MODEL_PATH,device='cuda',device_index=0,compute_type='int8_float32',local_files_only=True)

def park():
    global MODEL
    if MODEL is not None:
        MODEL.model.unload_model(to_cpu=False)
        MODEL=None
        gc.collect()


def audio_input(content_type,body):
    if not content_type.lower().startswith('multipart/form-data'):raise ValueError()
    msg=BytesParser(policy=policy.default).parsebytes(b'Content-Type: '+content_type.encode('ascii')+b'\r\nMIME-Version: 1.0\r\n\r\n'+body)
    audio=None;language='de'
    for part in msg.iter_parts():
        key=part.get_param('name',header='content-disposition')
        if key=='file':audio=part.get_payload(decode=True)
        if key=='language':language=part.get_payload(decode=True).decode().strip() or 'de'
    if not audio or len(language)>16:raise ValueError()
    with wave.open(io.BytesIO(audio),'rb') as f:
        if (f.getnchannels(),f.getsampwidth(),f.getframerate(),f.getcomptype())!=(1,2,16000,'NONE'):raise ValueError()
        if f.getnframes()>7200*16000:raise ValueError()
        frames=f.readframes(f.getnframes())
        if len(frames)!=f.getnframes()*2:raise ValueError()
    return frames,language


def transcribe(frames,language):
    import numpy as np
    started=time.monotonic();audio=np.frombuffer(frames,dtype='<i2').astype(np.float32)/32768.0
    parts,info=MODEL.transcribe(audio,language=language,word_timestamps=True,condition_on_previous_text=False,vad_filter=False,beam_size=5)
    segments=[];words=[]
    for part in parts:
        segments.append(dict(start=part.start,end=part.end,text=part.text))
        words.extend(dict(start=w.start,end=w.end,word=w.word,probability=w.probability) for w in (part.words or []))
    elapsed=time.monotonic()-started;duration=len(frames)/32000
    return dict(text=''.join(v['text'] for v in segments).strip(),segments=segments,words=words,
        language=info.language,duration=duration,processing_seconds=elapsed,rtf=elapsed/duration if duration else None,
        decoder='faster-whisper-turbo-int8_float32',model='whisper-large-v3-turbo',device='cuda')


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def reply(self,status,value):
        raw=json.dumps(value,allow_nan=False).encode();self.send_response(status)
        self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        self.reply(200 if self.path=='/health' else 404,dict(ok=True,resident=CONTROL.loaded))
    def do_POST(self):
        if self.path!='/v1/asr/final-block':self.reply(404,dict(error='not_found'));return
        try:
            if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length',[]))!=1:raise ValueError()
            length=int(self.headers['Content-Length'])
            if not 0<length<=MAX_BYTES:raise ValueError()
            body=self.rfile.read(length)
            if len(body)!=length:raise ValueError()
            frames,language=audio_input(self.headers.get('Content-Type',''),body)
        except (ValueError,TypeError,wave.Error,UnicodeError):self.reply(400,dict(error='invalid_audio'));return
        if not CONTROL.gate.enter_now():self.reply(503,dict(error='model_standby'));return
        try:self.reply(200,transcribe(frames,language))
        except Exception:self.reply(500,dict(error='asr_failed'))
        finally:CONTROL.gate.leave()


if __name__=='__main__':
    CONTROL=Controller(park,load,lambda:dict(model='whisper-large-v3-turbo',compute_type='int8_float32'))
    CONTROL.operate({'operation':'park'})
    control=serve_control(CONTROL,'whisper.sock')
    server=HTTPServer(('127.0.0.1',8179),Handler)
    try:server.serve_forever()
    finally:server.server_close();close_control(control);park()
