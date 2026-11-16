import json
import sys
from pathlib import Path
import plistlib
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
from kienzledoku_commander.hardware import HardwareProbe


class HardwareTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def put(self,name,text):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
    def test_current_cpu_and_multiple_gpu_no_history_or_background_calls(self):
        self.put('sys/class/hwmon/hwmon0/name','coretemp')
        self.put('sys/class/hwmon/hwmon0/temp1_input','47500')
        calls=[]
        def run(argv,timeout):
            if argv[0]==sys.executable:return json.dumps([dict(path=p,present=True,total=1000,free=500) for p in json.loads(argv[-1])]).encode()
            calls.append((argv,timeout));return b'0, GPU A, 51\n1, GPU B, N/A\n'
        probe=HardwareProbe('Linux',self.root,run)
        self.assertEqual([],calls)
        first=probe.temperatures();self.assertEqual([47.5,51,None],[s['value'] for s in first['sensors']])
        self.put('sys/class/hwmon/hwmon0/temp1_input','bad')
        second=probe.temperatures();self.assertIsNone(second['sensors'][0]['value'])
        self.assertTrue(second['sensors'][0]['reason'])
        self.assertEqual(2,len(calls));self.assertLessEqual(calls[0][1],2)
        self.assertEqual({'system','root','runner'},set(vars(probe)))
    def test_timeout_does_not_invent_temperature(self):
        def timeout(argv,limit):raise subprocess.TimeoutExpired(argv,limit)
        response=HardwareProbe('Linux',self.root,timeout).temperatures()
        self.assertEqual({'cpu','gpu'},{s['kind'] for s in response['sensors']})
        self.assertTrue(all(s['value'] is None and s['reason'] for s in response['sensors']))
    def test_wsl_distinguishes_physical_host_memory_and_guest_limits(self):
        self.put('proc/sys/kernel/osrelease','6.6-microsoft-standard-WSL2')
        self.put('proc/meminfo','MemTotal: 4096 kB\nMemAvailable: 2048 kB')
        host={'cpu':[{'Name':'host CPU','Manufacturer':'vendor','NumberOfCores':12,'NumberOfLogicalProcessors':24}],
              'memory':[{'Capacity':'34359738368','Speed':5600,'SMBIOSMemoryType':34}],
              'board':[{'Manufacturer':'board vendor','Product':'board'}],
              'system':{'Caption':'Windows','Version':'11'},'disks':[{'Model':'Host disk','Size':'1000000000'}]}
        def run(argv,timeout):
            if argv[0]==sys.executable:return json.dumps([dict(path=p,present=True,total=1000,free=500) for p in json.loads(argv[-1])]).encode()
            if argv[0]=='powershell.exe':return json.dumps(host).encode()
            if argv[0]=='nvidia-smi':return b'0, RTX, 24576\n'
            return b'{}'
        response=HardwareProbe('Linux',self.root,run).inventory()
        self.assertEqual('wsl',response['system']['execution'])
        self.assertEqual(34359738368,response['memory']['installed_bytes'])
        self.assertEqual(4096*1024,response['memory']['visible_bytes'])
        self.assertEqual('host CPU',response['cpu']['model'])
        self.assertIsNone(response['host_storage'][0]['model_volume_mapping'])
    def test_linux_model_network_path_not_mislabelled_as_ssd(self):
        self.put('proc/cpuinfo','model name : CPU\nvendor_id : Vendor\ncore id : 0\nphysical id : 0')
        self.put('proc/meminfo','MemTotal: 4096 kB\nMemAvailable: 2048 kB')
        def run(argv,timeout):
            if argv[0]==sys.executable:return json.dumps([dict(path=p,present=True,total=1000,free=500) for p in json.loads(argv[-1])]).encode()
            if argv[0]=='findmnt':return b'{"filesystems":[{"source":"server:/models","fstype":"nfs4"}]}'
            return b'{}'
        response=HardwareProbe('Linux',self.root,run).inventory([self.root/'model.gguf'])
        self.assertEqual('network',response['storage'][1]['type'])
        for key in ('cpu','memory','board','storage','gpus','system'):self.assertIn(key,response)
        self.assertIsNone(response['memory']['installed_bytes'])
        self.assertIn('installed_bytes',response['memory']['unavailable'])
    def test_mac_unified_memory_and_physical_disk_mapping(self):
        def run(argv,timeout):
            if argv[0]==sys.executable:return json.dumps([dict(path=p,present=True,total=1000,free=500) for p in json.loads(argv[-1])]).encode()
            if 'sysctl' in argv[0]:return {'hw.model':b'Mac','hw.memsize':b'34359738368','machdep.cpu.brand_string':b'Apple M4','hw.physicalcpu':b'10','hw.logicalcpu':b'10'}.get(argv[-1],b'0')
            if 'system_profiler' in argv[0]:return b'{"SPDisplaysDataType":[{"sppci_model":"Apple M4"}]}'
            if 'df' in argv[0]:return b'Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/disk3s5 1000 100 900 10% /\n'
            if 'diskutil' in argv[0]:
                data={'APFSPhysicalStores':[{'APFSPhysicalStore':'disk0s2'}]} if argv[-1]=='/dev/disk3s5' else ({'ParentWholeDisk':'disk0'} if argv[-1]=='disk0s2' else {'MediaName':'APPLE SSD','TotalSize':1000000000,'SolidState':True})
                return plistlib.dumps(data)
            return b''
        with patch('platform.machine',return_value='arm64'):
            response=HardwareProbe('Darwin',self.root,run).inventory([self.root/'m.gguf'])
        self.assertTrue(response['memory']['unified'])
        self.assertEqual('unified',response['gpus'][0]['memory_kind'])
        self.assertEqual(response['memory']['installed_bytes'],response['gpus'][0]['memory_bytes'])
        self.assertEqual('APPLE SSD',response['storage'][1]['model'])
        self.assertEqual(1000000000,response['storage'][1]['capacity_bytes'])


if __name__=='__main__':unittest.main()
