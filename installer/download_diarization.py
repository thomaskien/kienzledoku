"""Download a pinned optional model. Token is passed only in the environment."""
import os
from pathlib import Path
import sys
os.environ["PYANNOTE_METRICS_ENABLED"] = "0"
from huggingface_hub import snapshot_download

repo='pyannote/speaker-diarization-community-1'
revision='3533c8cf8e369892e6b79ff1bf80f7b0286a54ee'
destination=Path(sys.argv[1])
marker=destination/'.kienzledoku-revision'
if not marker.exists() or marker.read_text().strip()!=revision:
    snapshot_download(repo_id=repo,revision=revision,local_dir=destination,token=os.environ.get('HF_TOKEN') or False)
    marker.write_text(revision+'\n')
