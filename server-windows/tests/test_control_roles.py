import importlib.util,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'linux'))
import control
class RoleStopTests(unittest.TestCase):
 def test_stop_and_model_removal_do_not_require_uninstalled_workers(self):
  for role,expected in [('llm',[control.UNITS[0]]),('diar',[control.UNITS[0],control.UNITS[2]]),('full',control.UNITS)]:
   with tempfile.TemporaryDirectory() as directory:
    state=Path(directory);(state/'windows-config.json').write_text(json.dumps(dict(ServerRole=role)))
    with patch.object(control,'STATE',state),patch.object(control.os,'geteuid',return_value=0),patch.dict(os.environ,WSL_DISTRO_NAME='kienzledoku-server'),patch.object(control.subprocess,'run') as run:
     run.return_value.returncode=3
     control.execute('stop')
     self.assertEqual(['systemctl','stop',*expected],run.call_args_list[0].args[0])
     self.assertEqual(len(expected)+1,len(run.call_args_list))
