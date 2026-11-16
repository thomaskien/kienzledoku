"""Bounded, read-only hardware queries. No sampler, retained readings or history."""
import csv
from datetime import datetime, timezone
import io
import json
import math
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import time


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def number(value, scale=1):
    try:
        result = float(value) * scale
        return int(result) if math.isfinite(result) and result.is_integer() else (result if math.isfinite(result) else None)
    except (ValueError, TypeError):
        return None


def group(source, **values):
    missing = {k: 'not_available_from_source' for k, v in values.items() if v is None}
    return dict(values, source=source, unavailable=missing)


class HardwareProbe:
    def __init__(self, system=None, root='/', runner=None):
        self.system = system or platform.system()
        self.root = Path(root)
        self.runner = runner or self._run

    def _read(self, path):
        try:
            return (self.root / path.lstrip('/')).read_text(errors='replace')[:262144].strip()
        except OSError:
            return ''

    @staticmethod
    def _run(argv, timeout):
        env = dict(os.environ, LC_ALL='C', LANG='C')
        result = subprocess.run(argv, capture_output=True, timeout=timeout, check=True, env=env)
        if len(result.stdout) > 2 * 1024 * 1024:
            raise ValueError('response_limit')
        return result.stdout

    def _command(self, argv, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return b''
        try:
            return self.runner(argv, min(2.0, remaining))
        except (OSError, ValueError, subprocess.SubprocessError):
            return b''

    def _json(self, argv, deadline):
        try:
            return json.loads(self._command(argv, deadline).decode('utf-8-sig'))
        except (ValueError, UnicodeError):
            return {}

    def _plist(self, argv, deadline):
        try:
            return plistlib.loads(self._command(argv, deadline))
        except (ValueError, plistlib.InvalidFileException):
            return {}

    def _is_wsl(self):
        return 'microsoft' in self._read('/proc/sys/kernel/osrelease').lower()

    def _nvidia(self, deadline, temperature=False):
        fields = 'index,name,temperature.gpu' if temperature else 'index,name,memory.total'
        raw = self._command(['nvidia-smi', '--query-gpu='+fields, '--format=csv,noheader,nounits'], deadline)
        rows = []
        for row in csv.reader(io.StringIO(raw.decode(errors='replace'))):
            if len(row) != 3:
                continue
            index, name, value = (x.strip() for x in row)
            if not index.isdigit():
                continue
            if temperature:
                rows.append(self._sensor('gpu', 'nvidia:'+index, name, number(value), 'nvidia-smi'))
            else:
                rows.append(group('nvidia-smi', id='nvidia:'+index, model=name,
                                  memory_bytes=number(value, 1048576), memory_kind='dedicated'))
        return rows

    @staticmethod
    def _sensor(kind, sensor_id, name, value, source, reason=None):
        if value is not None and not -40 <= value <= 200:
            value, reason = None, 'invalid_sensor_value'
        return dict(kind=kind, id=sensor_id, name=name, value=value, unit='celsius',
                    source=source, measured_at=timestamp(), status='available' if value is not None else 'unavailable',
                    reason=None if value is not None else (reason or 'sensor_not_available'))

    def temperatures(self):
        deadline = time.monotonic()+3
        sensors = []
        if self.system == 'Linux':
            base = self.root/'sys/class/hwmon'
            for directory in sorted(base.glob('hwmon*'))[:64]:
                chip = self._read(str(directory.relative_to(self.root))+'/name')
                # Generic ACPI/mainboard sensors cannot reliably be labelled CPU.
                kind = 'cpu' if chip in ('coretemp','k10temp','zenpower','cpu_thermal') else ('gpu' if chip in ('amdgpu','nouveau') else None)
                if not kind:
                    continue
                for sensor in sorted(directory.glob('temp*_input'))[:128]:
                    prefix = str(sensor.relative_to(self.root))
                    label = self._read(prefix.replace('_input','_label')) or chip
                    sensors.append(self._sensor(kind, chip+':'+directory.name+':'+sensor.stem,
                                                label, number(self._read(prefix), .001), 'linux-hwmon'))
        if self.system == 'Darwin':
            rows = self._json([sys.executable, str(Path(__file__).with_name('mac_sensors.py'))], deadline)
            if isinstance(rows, list):
                for row in rows[:256]:
                    if isinstance(row, dict) and row.get('kind') in ('cpu', 'gpu'):
                        sensors.append(self._sensor(row['kind'], str(row.get('id','smc')), str(row.get('name','SMC')),
                            number(row.get('value')), 'apple-smc'))
        else:
            sensors.extend(self._nvidia(deadline, temperature=True))
        for kind in ('cpu','gpu'):
            if not any(s['kind']==kind for s in sensors):
                reason = 'no_supported_unprivileged_sensor' if self.system == 'Darwin' else 'sensor_not_exposed'
                sensors.append(self._sensor(kind, kind+':unavailable', kind.upper(), None, self.system, reason))
        return dict(schema_version=1, measured_at=timestamp(), execution='wsl' if self._is_wsl() else self.system.lower(), sensors=sensors)

    def _windows_host(self, deadline):
        # Fixed query only; no request-supplied commands, paths or credentials.
        script = "$ErrorActionPreference='Stop';[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false);" \
            "$p=@(Get-CimInstance Win32_Processor|Select-Object Name,Manufacturer,NumberOfCores,NumberOfLogicalProcessors);" \
            "$m=@(Get-CimInstance Win32_PhysicalMemory|Select-Object Capacity,Speed,SMBIOSMemoryType);" \
            "$b=@(Get-CimInstance Win32_BaseBoard|Select-Object Manufacturer,Product);" \
            "$o=Get-CimInstance Win32_OperatingSystem|Select-Object Caption,Version,TotalVisibleMemorySize,FreePhysicalMemory;" \
            "$d=@(Get-CimInstance Win32_DiskDrive|Select-Object Model,Size,MediaType,InterfaceType);" \
            "@{cpu=$p;memory=$m;board=$b;system=$o;disks=$d}|ConvertTo-Json -Depth 5 -Compress"
        return self._json(['powershell.exe','-NoProfile','-NonInteractive','-Command',script], deadline)

    def _volumes(self, model_paths, deadline):
        # Network mounts can block even stat/statvfs: isolate filesystem calls in
        # a disposable, timed child rather than leave an unkillable probe thread.
        paths = ['/'] + list(model_paths)
        code = """import json, pathlib, shutil, sys
result=[]
for name in json.loads(sys.argv[1]):
 p=pathlib.Path(name); existing=p
 try:
  present=p.exists()
  while not existing.exists() and existing.parent!=existing:existing=existing.parent
  usage=shutil.disk_usage(existing)
  result.append(dict(path=str(existing),present=present,total=usage.total,free=usage.free))
 except OSError:result.append({})
print(json.dumps(result))
"""
        data=self._json([sys.executable,'-I','-c',code,json.dumps(paths)],deadline)
        if not isinstance(data,list):data=[]
        volumes=[]
        for index,path in enumerate(paths):
            item=data[index] if index<len(data) and isinstance(data[index],dict) else {}
            volumes.append(group('filesystem',role='system' if index==0 else 'model:'+str(index-1),
                volume_total_bytes=item.get('total'),volume_free_bytes=item.get('free'),
                model_path_exists=item.get('present'),model_filename=Path(path).name if index else None,
                device=None,model=None,type=None,capacity_bytes=None,_probe_path=item.get('path')))
        return volumes

    def _linux_storage(self, volumes, model_paths, deadline):
        raw=self._json(['lsblk','--json','--bytes','--paths','-o','NAME,PKNAME,MODEL,VENDOR,SIZE,ROTA,TRAN,TYPE'],deadline)
        devices={}
        def visit(items, parent=None):
            for item in items if isinstance(items,list) else []:
                if not isinstance(item,dict):continue
                item=dict(item);item['_parent']=parent;devices[item.get('name')]=item
                visit(item.get('children',[]),item.get('name'))
        visit(raw.get('blockdevices',[]) if isinstance(raw,dict) else [])
        for volume,path in zip(volumes,[Path('/')]+[Path(p) for p in model_paths]):
            existing=volume.get('_probe_path')
            if not existing:continue
            mounts=self._json(['findmnt','-J','-T',str(existing),'-o','SOURCE,FSTYPE'],deadline)
            entries=mounts.get('filesystems',[]) if isinstance(mounts,dict) else []
            entry=entries[0] if entries else {};source=entry.get('source','');fstype=entry.get('fstype','')
            device=devices.get(source.split('[')[0]);seen=set()
            while device and device.get('_parent') and device['_parent'] not in seen:
                seen.add(device['_parent']);device=devices.get(device['_parent'],device)
            kind='network' if fstype.startswith(('nfs','cifs','smb','9p')) else ('virtual' if self._is_wsl() else None)
            if device:
                kind=kind or ('ssd' if device.get('rota') is False or device.get('rota')==0 else 'hdd')
                volume.update(model=(device.get('model') or '').strip() or None,capacity_bytes=number(device.get('size')),
                              interface=device.get('tran'),device=device.get('name'))
            volume['type']=kind;volume['filesystem']=fstype or None
            volume['unavailable']={k:'not_available_from_source' for k,v in volume.items() if v is None}

    def inventory(self, model_paths=()):
        model_paths=tuple(dict.fromkeys(str(p) for p in model_paths))[:64]
        deadline=time.monotonic()+8
        wsl=self.system=='Linux' and self._is_wsl()
        result=dict(schema_version=1, measured_at=timestamp(),
            system=group('platform',os=self.system,version=platform.release(),architecture=platform.machine(),
                         execution='wsl' if wsl else 'native',model=None),
            cpu=group(self.system,manufacturer=None,model=None,physical_cores=None,logical_processors=os.cpu_count(),architecture=platform.machine()),
            memory=group(self.system,installed_bytes=None,visible_bytes=None,available_bytes=None,type=None,speed_mhz=None,unified=False),
            board=group(self.system,manufacturer=None,model=None,firmware=None),storage=self._volumes(model_paths,deadline),gpus=[])
        if self.system=='Linux':
            raw=self._read('/proc/cpuinfo');blocks=[dict(re.findall(r'^([^:\n]+)\s*:\s*(.*)$',block,re.M)) for block in raw.split('\n\n') if block.strip()]
            blocks=[{k.strip():v for k,v in block.items()} for block in blocks]
            first=blocks[0] if blocks else {}
            cores={(b.get('physical id'),b['core id']) for b in blocks if 'core id' in b}
            result['cpu']=group('proc-cpuinfo',manufacturer=first.get('vendor_id'),model=first.get('model name'),
                                physical_cores=len(cores) or None,logical_processors=len(blocks) or os.cpu_count(),architecture=platform.machine())
            memory=dict(re.findall(r'^(\w+):\s+(\d+) kB',self._read('/proc/meminfo'),re.M))
            result['memory']=group('proc-meminfo',installed_bytes=None,visible_bytes=number(memory.get('MemTotal'),1024),
                                    available_bytes=number(memory.get('MemAvailable'),1024),type=None,speed_mhz=None,unified=False)
            result['board']=group('sysfs-dmi',manufacturer=self._read('/sys/class/dmi/id/board_vendor') or None,
                                   model=self._read('/sys/class/dmi/id/board_name') or None,firmware=self._read('/sys/class/dmi/id/bios_version') or None)
            result['system']['model']=self._read('/sys/class/dmi/id/product_name') or None
            if not wsl and ('hypervisor' in first.get('flags','').split() or any(tag in (result['system']['model'] or '').lower() for tag in ('virtual','vmware','kvm','qemu','hvm'))):
                result['system']['execution']='vm'
            # SMBIOS type 17 is only read when available to this service; no privilege elevation.
            total=0; found=False
            for p in (self.root/'sys/firmware/dmi/entries').glob('17-*/raw'):
                try:
                    data=p.read_bytes();size=int.from_bytes(data[12:14],'little')
                    if size==0:continue
                    if size==0x7fff and len(data)>=32:size=int.from_bytes(data[28:32],'little')*1048576
                    elif size==0xffff:raise ValueError()
                    else:size=(size&0x7fff)*(1024 if size&0x8000 else 1048576)
                    total+=size;found=True
                except (OSError,ValueError):found=False;break
            if found:result['memory']['installed_bytes']=total;result['memory']['unavailable'].pop('installed_bytes',None)
            self._linux_storage(result['storage'],model_paths,deadline)
        elif self.system=='Darwin':
            def sysctl(key):return self._command(['/usr/sbin/sysctl','-n',key],deadline).decode(errors='replace').strip() or None
            model=sysctl('hw.model');ram=number(sysctl('hw.memsize'))
            if sysctl('kern.hv_vmm_present')=='1':result['system']['execution']='vm'
            result['system']['model']=model
            result['cpu']=group('sysctl',manufacturer='Apple' if platform.machine()=='arm64' else 'Intel',model=sysctl('machdep.cpu.brand_string'),
                                physical_cores=number(sysctl('hw.physicalcpu')),logical_processors=number(sysctl('hw.logicalcpu')),architecture=platform.machine())
            vm=self._command(['/usr/bin/vm_stat'],deadline).decode(errors='replace')
            page=re.search(r'page size of (\d+) bytes',vm);counts=dict(re.findall(r'^(Pages [^:]+):\s+(\d+)\.',vm,re.M))
            available=(sum(int(counts.get(k,0)) for k in ('Pages free','Pages inactive'))*int(page[1])) if page else None
            result['memory']=group('sysctl/vm_stat',installed_bytes=ram,visible_bytes=ram,available_bytes=None,free_plus_inactive_bytes=available,
                                   type='unified' if platform.machine()=='arm64' else None,speed_mhz=None,unified=platform.machine()=='arm64')
            result['board']=group('sysctl',manufacturer='Apple',model=model,firmware=None)
            info=self._json(['/usr/sbin/system_profiler','-json','SPDisplaysDataType'],deadline)
            for index,gpu in enumerate(info.get('SPDisplaysDataType',[]) if isinstance(info,dict) else []):
                result['gpus'].append(group('system_profiler',id='gpu:'+str(index),model=gpu.get('sppci_model') or gpu.get('_name'),
                                          memory_bytes=ram if platform.machine()=='arm64' else None,memory_kind='unified' if platform.machine()=='arm64' else 'dedicated'))
            for volume,path in zip(result['storage'],[Path('/')]+[Path(p) for p in model_paths]):
                existing=volume.get('_probe_path')
                if not existing:continue
                df=self._command(['/bin/df','-P',str(existing)],deadline).decode(errors='replace').splitlines()
                source=df[-1].split()[0] if len(df)>1 else ''
                info=self._plist(['/usr/sbin/diskutil','info','-plist',source],deadline) if source.startswith('/dev/') else {}
                if not source.startswith('/dev/'):
                    volume['type']='network' if ':' in source or source.startswith('//') else None
                stores=info.get('APFSPhysicalStores',[]) or []
                device=stores[0].get('APFSPhysicalStore') if stores and isinstance(stores[0],dict) else info.get('ParentWholeDisk')
                physical=self._plist(['/usr/sbin/diskutil','info','-plist',device],deadline) if device else info
                whole=physical.get('ParentWholeDisk')
                if whole and whole!=device:
                    device=whole;physical=self._plist(['/usr/sbin/diskutil','info','-plist',whole],deadline)
                volume.update(device=device,model=physical.get('MediaName') or physical.get('DeviceOrMediaName') or None,
                              type='ssd' if physical.get('SolidState') is True else ('hdd' if physical.get('SolidState') is False else volume['type']),interface=physical.get('BusProtocol'),
                              capacity_bytes=physical.get('TotalSize') if device else None)
                volume['unavailable']={k:'not_available_from_source' for k,v in volume.items() if v is None}
        if wsl or self.system=='Windows':
            host=self._windows_host(deadline)
            if isinstance(host,dict) and host:
                result['host']=group('windows-cim',os=(host.get('system') or {}).get('Caption'),version=(host.get('system') or {}).get('Version'))
                cpu=(host.get('cpu') or [{}])[0];board=(host.get('board') or [{}])[0];mem=host.get('memory') or []
                result['cpu']=group('windows-cim',manufacturer=cpu.get('Manufacturer'),model=cpu.get('Name'),
                                    physical_cores=sum(x.get('NumberOfCores',0) for x in host.get('cpu',[])) or None,
                                    logical_processors=sum(x.get('NumberOfLogicalProcessors',0) for x in host.get('cpu',[])) or None,architecture=platform.machine())
                result['board']=group('windows-cim',manufacturer=board.get('Manufacturer'),model=board.get('Product'),firmware=None)
                result['memory']['installed_bytes']=sum(number(m.get('Capacity')) or 0 for m in mem) or None
                result['memory']['installed_source']='windows-cim'
                result['memory']['speed_mhz']=sorted({m['Speed'] for m in mem if m.get('Speed')}) or None
                result['memory']['type']=sorted({m['SMBIOSMemoryType'] for m in mem if m.get('SMBIOSMemoryType')}) or None
                if self.system=='Windows':
                    result['memory']['visible_bytes']=number((host.get('system') or {}).get('TotalVisibleMemorySize'),1024)
                    result['memory']['available_bytes']=number((host.get('system') or {}).get('FreePhysicalMemory'),1024)
                result['memory']['unavailable']={k:'not_available_from_source' for k,v in result['memory'].items() if v is None}
                result['host_storage']=[group('windows-cim',model=d.get('Model'),capacity_bytes=number(d.get('Size')),interface=d.get('InterfaceType'),type=d.get('MediaType'),model_volume_mapping=None) for d in host.get('disks',[])]
            else:result['host']=group('windows-cim',status='unavailable',reason='host_query_unavailable')
        if self.system!='Darwin':result['gpus']=self._nvidia(deadline)
        if not result['gpus']:result['gpus']=[group('platform',id='gpu:unavailable',model=None,memory_bytes=None,memory_kind=None)]
        for key in ('cpu','memory','board','system'):
            result[key]['unavailable']={k:'not_available_from_source' for k,v in result[key].items() if v is None}
        for volume in result['storage']:
            volume.pop('_probe_path',None);volume['unavailable'].pop('_probe_path',None)
        if self.system=='Darwin':result['memory']['unavailable']['available_bytes']='no_exact_available_counter; free_plus_inactive_bytes_reported_separately'
        return result
