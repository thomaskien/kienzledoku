"""PortAudio input negotiation and streaming conversion to mono PCM16 / 16 kHz."""
import json
import sys
import time


def devices(sd):
    hosts = sd.query_hostapis()
    return [{'index': json.dumps([str(item['name']), str(hosts[item['hostapi']]['name'])], ensure_ascii=False),
             'name': str(item['name']) + ' (' + str(hosts[item['hostapi']]['name']) + ')', 'number': number}
            for number, item in enumerate(sd.query_devices()) if item.get('max_input_channels', 0) > 0]


def select_device(sd, requested=None):
    available = devices(sd)
    if requested not in (None, ''):
        if str(requested).isdigit():
            number = int(requested)
        else:
            matches = [item for item in available if item['index'] == requested]
            if len(matches) != 1:
                raise ValueError('Das gewählte Mikrofon ist nicht mehr eindeutig verfügbar. Bitte erneut auswählen.')
            number = matches[0]['number']
    else:
        number = int(sd.default.device[0])
        if number < 0:
            raise ValueError('Kein Mikrofon verfügbar. Windows-Mikrofonfreigabe bzw. RDP-Umleitung prüfen.')
        if sys.platform == 'win32':
            name = sd.query_devices(number)['name']
            matches = [item for item in available if sd.query_devices(item['number'])['name'] == name and 'WASAPI' in item['name']]
            if len(matches) == 1:
                number = matches[0]['number']
    info = sd.query_devices(number)
    if info['max_input_channels'] < 1:
        raise ValueError('Das gewählte Gerät hat keinen Audioeingang')
    return number, info, available


class PcmConverter:
    def __init__(self, rate, channels):
        import audioop
        self.audioop = audioop
        self.rate, self.channels, self.state = rate, channels, None
    def feed(self, pcm):
        if self.channels == 2:
            pcm = self.audioop.tomono(pcm, 2, .5, .5)
        if self.rate != 16000:
            pcm, self.state = self.audioop.ratecv(pcm, 2, 1, self.rate, 16000, self.state)
        return pcm


def create_input(sd, requested, append, emit, chunk_ms=100):
    number, info, available = select_device(sd, requested)
    host = sd.query_hostapis(info['hostapi'])['name']
    extra = sd.WasapiSettings(exclusive=False) if sys.platform == 'win32' and 'WASAPI' in host else None
    rate = int(round(info['default_samplerate']))
    channels = 1
    try:
        sd.check_input_settings(device=number, channels=1, dtype='int16', samplerate=rate, extra_settings=extra)
    except Exception:
        channels = min(2, int(info['max_input_channels']))
        sd.check_input_settings(device=number, channels=channels, dtype='int16', samplerate=rate, extra_settings=extra)
    converter = PcmConverter(rate, channels)
    failure = []
    last_level = [0.0]
    def callback(indata, frames, timing, status):
        try:
            if status:
                failure.append('Audio-Unterbrechung: ' + str(status))
                raise sd.CallbackAbort
            pcm = converter.feed(bytes(indata))
            append(pcm)
            now = time.monotonic()
            if now-last_level[0] > .5:
                emit('audio_level', rms=converter.audioop.rms(pcm, 2))
                last_level[0] = now
        except sd.CallbackAbort:
            raise
        except Exception:
            failure.append('Audioverarbeitung unterbrochen')
            raise sd.CallbackAbort
    stream = sd.RawInputStream(device=number, samplerate=rate, channels=channels,
                               dtype='int16', blocksize=max(1, int(rate*chunk_ms/1000)),
                               extra_settings=extra, callback=callback)
    selected = next(item['index'] for item in available if item['number'] == number)
    emit('audio_devices', devices=available, selected=selected)
    return stream, failure
