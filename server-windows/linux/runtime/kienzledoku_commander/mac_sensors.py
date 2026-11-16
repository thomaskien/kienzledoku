"""One read-only Apple Silicon SMC temperature snapshot, run in a bounded child.

The private AppleSMC ABI and sensor prefixes are documented by macmon:
https://github.com/vladkens/macmon/blob/main/src/sources.rs
https://github.com/vladkens/macmon/blob/main/src/metrics.rs
No write command, sampling loop, saved reading, root helper or external dependency.
"""
import ctypes as C
import json
import math
import struct
import time


class Version(C.Structure):
    _fields_ = [('major',C.c_uint8),('minor',C.c_uint8),('build',C.c_uint8),
                ('reserved',C.c_uint8),('release',C.c_uint16)]
class Limits(C.Structure):
    _fields_ = [('version',C.c_uint16),('length',C.c_uint16),('cpu',C.c_uint32),
                ('gpu',C.c_uint32),('memory',C.c_uint32)]
class KeyInfo(C.Structure):
    _fields_ = [('size',C.c_uint32),('type',C.c_uint32),('attributes',C.c_uint8)]
class Message(C.Structure):
    _fields_ = [('key',C.c_uint32),('version',Version),('limits',Limits),('info',KeyInfo),
                ('result',C.c_uint8),('status',C.c_uint8),('command',C.c_uint8),
                ('index',C.c_uint32),('bytes',C.c_uint8*32)]


def sensor_kind(name):
    if name.startswith('Tg'): return 'gpu'
    if name.startswith(('Tp','Te')): return 'cpu'
    return None


def snapshot():
    io=C.CDLL('/System/Library/Frameworks/IOKit.framework/IOKit')
    lib=C.CDLL('/usr/lib/libSystem.B.dylib')
    def fn(name,args,result):
        f=getattr(io,name);f.argtypes=args;f.restype=result;return f
    matching=fn('IOServiceMatching',[C.c_char_p],C.c_void_p)
    services=fn('IOServiceGetMatchingServices',[C.c_uint32,C.c_void_p,C.POINTER(C.c_uint32)],C.c_int)
    next_service=fn('IOIteratorNext',[C.c_uint32],C.c_uint32)
    get_name=fn('IORegistryEntryGetName',[C.c_uint32,C.c_void_p],C.c_int)
    release=fn('IOObjectRelease',[C.c_uint32],C.c_int)
    opening=fn('IOServiceOpen',[C.c_uint32,C.c_uint32,C.c_uint32,C.POINTER(C.c_uint32)],C.c_int)
    closing=fn('IOServiceClose',[C.c_uint32],C.c_int)
    call=fn('IOConnectCallStructMethod',[C.c_uint32,C.c_uint32,C.c_void_p,C.c_size_t,C.c_void_p,C.POINTER(C.c_size_t)],C.c_int)
    task=C.c_uint32.in_dll(lib,'mach_task_self_').value
    iterator=C.c_uint32();connection=C.c_uint32();rows=[]
    if services(0,matching(b'AppleSMC'),C.byref(iterator)):return rows
    try:
        while True:
            device=next_service(iterator.value)
            if not device:break
            try:
                name=C.create_string_buffer(128)
                if not get_name(device,name) and name.value==b'AppleSMCKeysEndpoint':
                    if opening(device,task,0,C.byref(connection)):connection.value=0
            finally:release(device)
            if connection.value:break
    finally:release(iterator.value)
    if not connection.value:return rows
    deadline=time.monotonic()+1.4
    def request(message):
        output=Message();size=C.c_size_t(C.sizeof(output))
        if time.monotonic()>deadline:raise TimeoutError()
        if call(connection.value,2,C.byref(message),C.sizeof(message),C.byref(output),C.byref(size)) or output.result:
            raise ValueError('SMC read unavailable')
        return output
    def value(key):
        info=request(Message(key=key,command=9)).info
        if not 1<=info.size<=32:raise ValueError('SMC size invalid')
        return info,bytes(request(Message(key=key,info=info,command=5)).bytes)[:info.size]
    try:
        _,raw=value(int.from_bytes(b'#KEY','big'))
        for index in range(min(int.from_bytes(raw,'big'),8192)):
            try:
                key=request(Message(command=8,index=index)).key
                name=key.to_bytes(4,'big').decode('ascii')
                kind=sensor_kind(name)
                if not kind:continue
                info,raw=value(key)
                if info.size!=4 or info.type!=int.from_bytes(b'flt ','big'):continue
                temperature=struct.unpack('<f',raw)[0]
                if math.isfinite(temperature) and 10<temperature<150:
                    rows.append(dict(kind=kind,id='smc:'+name,name=name,value=round(temperature,2)))
            except (ValueError,UnicodeError):continue
    except TimeoutError:
        pass
    finally:closing(connection.value)
    return rows


if __name__=='__main__':
    try: result=snapshot()
    except (OSError,ValueError,AttributeError): result=[]
    print(json.dumps(result,allow_nan=False))
