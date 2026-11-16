from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from test_gemma_models import configuration,runtime_config
from test_commander import eventually
from test_commander_benchmark import BenchRuntime
from serial_server import SerialCommander
from kienzledoku_commander.benchmark import inventory

class CatalogueBenchmarkTests(unittest.TestCase):
 def test_real_serial_catalogue_aliases_and_explicit_nondefault_profile(self):
  with tempfile.TemporaryDirectory() as directory:
   cfg=runtime_config(configuration('gemma12-q8',['gemma12-q8','27b-q4'],'gemma12-q8'))
   for model,profile in cfg.profiles.items():
    path=Path(directory)/(model+'.gguf');path.touch();profile['path']=str(path)
   cfg=replace(cfg,diarization_mode='resident',default_quality='gruendlich',quality_models={'basis':'gemma12_q8','gruendlich':'gemma12_q8','sehr_gruendlich':'sehr_gruendlich'}).validate()
   data=inventory(cfg)
   self.assertEqual(2,len(data));self.assertEqual(['basis','gruendlich'],data[0]['aliases'])
   runtime=BenchRuntime(cfg);cmd=SerialCommander(cfg,runtime)
   try:
    eventually(lambda:not cmd._transition and not cmd._uncertain)
    sid=cmd.benchmark_begin('sehr_gruendlich','serial')['id']
    result=cmd.submit('llm',{'llm':{}},'sehr_gruendlich','selected',benchmark_session=sid).future.result(2)
    self.assertEqual('sehr_gruendlich',result['benchmark']['model_id'])
    cmd.benchmark_end(sid);eventually(lambda:cmd.benchmark_status(sid)['state']=='completed')
    self.assertEqual('@gemma12_q8',cmd.status()['loaded']['llm'])
   finally:cmd.close()
