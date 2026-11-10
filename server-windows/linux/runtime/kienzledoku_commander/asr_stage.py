"""Stage Whisper's checkpoint on CPU before moving the same model to CUDA.

The upstream loader otherwise keeps its CUDA checkpoint alive while also
constructing its CUDA module. Model weights, dtype and inference stay unchanged.
"""
import inspect
import ctypes
import gc
from pathlib import Path

def install():
    import whisperlivekit.simul_whisper.backend as backend
    if getattr(backend.load_model,'kienzledoku_cpu_staged',False):
        return
    original=backend.load_model
    signature=inspect.signature(original)
    if 'device' not in signature.parameters:
        raise RuntimeError('Whisper-Lader unterstützt kein CPU-Staging.')
    def cpu_staged(*args,**kwargs):
        import torch
        bound=signature.bind(*args,**kwargs)
        target=bound.arguments.get('device') or 'cuda'
        bound.arguments['device']='cpu'
        original_load=torch.load
        def mapped_load(file,*a,**kw):
            source=file if isinstance(file,(str,Path)) else getattr(file,'name',None)
            if source is None or Path(source).name!='large-v3.pt':
                raise RuntimeError('Unerwarteter Whisper-Checkpoint.')
            location=kw.get('map_location',a[0] if a else None)
            if str(location)!='cpu':
                raise RuntimeError('Whisper-Checkpoint muss auf CPU geladen werden.')
            kw['mmap']=True
            return original_load(str(Path(source).resolve()),*a,**kw)
        torch.load=mapped_load
        try:
            model=original(*bound.args,**bound.kwargs)
        finally:
            torch.load=original_load
        model=model.to(target)
        gc.collect()
        ctypes.CDLL(None).malloc_trim(0)
        return model
    cpu_staged.kienzledoku_cpu_staged=True
    backend.load_model=cpu_staged
