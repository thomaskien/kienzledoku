"""Gemessene Ein-GPU-Profile; Konfiguration und Qualitätswahl sind getrennt."""
from dataclasses import dataclass, field, replace
from pathlib import Path
import os
import subprocess
import tomllib
from urllib.parse import urlsplit

from .errors import InvalidRequest

QUALITIES = ("basis", "gruendlich", "sehr_gruendlich")
LABELS = {"basis": "Basis", "gruendlich": "Gründlich", "sehr_gruendlich": "Sehr gründlich"}
ALLOWED = {8: ("basis",), 16: ("basis", "gruendlich"), 24: ("gruendlich", "sehr_gruendlich")}
DEFAULTS = {8: "basis", 16: "basis", 24: "gruendlich"}


@dataclass(frozen=True)
class Model:
    quality: str
    path: str
    context: int
    slots: int
    kv: str = "q8_0"

    @property
    def context_per_slot(self):
        # llama.cpp b9637 rounds this measured 3-slot profile to 256-token blocks.
        return 87552 if self.slots == 3 else self.context


@dataclass(frozen=True)
class Settings:
    tier: int = 24
    default_quality: str = "auto"
    host: str = "127.0.0.1"
    port: int = 8185
    token_env: str = "KIENZLEDOKU_COMMANDER_TOKEN"
    asr_url: str = "http://127.0.0.1:8179"
    diar_url: str = "http://127.0.0.1:8183"
    llm_url: str = "http://127.0.0.1:8086"
    llama_binary: str = "/opt/kienzlefon-ai/bin/llama-server"
    control_dir: str = "/run/kienzledoku-commander"
    diar_control_dir: str | None = None
    prompt_path: str = str(Path(__file__).resolve().parents[1] / "prompt_documentation.txt")
    gpu_index: int = 0
    diar_allocator_mib: int = 2048
    max_pending: int = 128
    max_remembered: int = 256
    max_payload_mib: int = 256
    remember_seconds: float = 300
    backend_timeout: float = 600
    load_timeout: float = 180
    control_timeout: float = 180
    queue_timeout: float = 900
    asr_parallel: int = 1
    diar_parallel: int = 1
    model_paths: dict = field(default_factory=lambda: {
        "basis": "/opt/kienzlefon-ai/models/Qwen_Qwen3.5-9B-Q4_K_M.gguf",
        "gruendlich": "/opt/kienzlefon-ai/models/Qwen_Qwen3.5-9B-Q6_K.gguf",
        "sehr_gruendlich": "/opt/kienzlefon-ai/models/Qwen3.8-27B-UD-Q4_K_M.gguf",
    })

    def validate(self):
        for key in ("tier", "port", "gpu_index", "diar_allocator_mib", "max_pending", "max_remembered", "max_payload_mib", "asr_parallel", "diar_parallel"):
            if type(getattr(self, key)) is not int:
                raise ValueError("Ganzzahlige Einstellung erwartet: " + key)
        for key in ("remember_seconds", "backend_timeout", "load_timeout", "control_timeout", "queue_timeout"):
            if type(getattr(self, key)) not in (int, float):
                raise ValueError("Numerische Zeitgrenze erwartet: " + key)
        for key in ("default_quality", "host", "token_env", "asr_url", "diar_url", "llm_url", "llama_binary", "control_dir", "prompt_path"):
            if not isinstance(getattr(self, key), str) or not getattr(self, key):
                raise ValueError("Texteinstellung erwartet: " + key)
        if self.tier not in ALLOWED:
            raise ValueError("VRAM-Profil muss 8, 16 oder 24 sein.")
        if self.default_quality != "auto" and self.default_quality not in self.allowed:
            raise ValueError("Die Standardstufe ist auf diesem VRAM-Profil nicht erlaubt.")
        for value in (self.asr_url, self.diar_url, self.llm_url):
            u = urlsplit(value)
            if u.scheme != "http" or u.hostname not in ("127.0.0.1", "localhost", "::1") or not u.port or u.username or u.password or u.query or u.fragment or u.path not in ("", "/"):
                raise ValueError("Interne Backends müssen lokale HTTP-Adressen mit Port sein.")
        if self.llm_url.rstrip("/") in (self.asr_url.rstrip("/"), self.diar_url.rstrip("/")):
            raise ValueError("Das LLM benötigt einen eigenen internen Port.")
        if urlsplit(self.llm_url).port == self.port:
            raise ValueError("Commander und internes LLM benötigen unterschiedliche Ports.")
        if self.host not in ("127.0.0.1", "localhost", "::1") and not os.environ.get(self.token_env):
            raise ValueError("Für einen LAN-Bind muss das konfigurierte Bearer-Token gesetzt sein.")
        if not 1 <= self.port <= 65535 or not Path(self.control_dir).is_absolute():
            raise ValueError("Port oder Steuerungsverzeichnis ist ungültig.")
        if self.diar_control_dir is not None and (not isinstance(self.diar_control_dir, str) or not Path(self.diar_control_dir).is_absolute()):
            raise ValueError("Diarisierungs-Steuerverzeichnis benötigt einen absoluten Pfad.")
        if not Path(self.llama_binary).is_absolute() or not Path(self.prompt_path).is_absolute():
            raise ValueError("Binärdatei und Prompt benötigen absolute Pfade.")
        if self.gpu_index < 0 or not 256 <= self.diar_allocator_mib <= 6144:
            raise ValueError("GPU-Index oder pyannote-Budget ist ungültig.")
        if not 1 <= self.max_pending <= self.max_remembered <= 4096:
            raise ValueError("Die Anfragelimits sind ungültig.")
        if not 1 <= self.max_payload_mib <= 4096:
            raise ValueError("Das Queue-Speicherbudget ist ungültig.")
        if not 0 < self.remember_seconds <= 3600 or not 0 < self.backend_timeout <= 3600 or not 0 < self.load_timeout <= 600 or not 0 < self.control_timeout <= 600 or not 0 < self.queue_timeout <= 3600:
            raise ValueError("Zeitgrenzen sind ungültig.")
        if not 1 <= self.asr_parallel <= 16 or not 1 <= self.diar_parallel <= 16:
            raise ValueError("Die Worker-Anzahl ist ungültig.")
        if not isinstance(self.model_paths, dict) or set(self.model_paths) != set(QUALITIES) or any(not isinstance(p, str) or not Path(p).is_absolute() for p in self.model_paths.values()):
            raise ValueError("Modellpfade müssen für alle drei Stufen absolut angegeben werden.")
        return self

    @property
    def allowed(self):
        return ALLOWED[self.tier]

    @property
    def default(self):
        return DEFAULTS[self.tier] if self.default_quality == "auto" else self.default_quality

    def quality(self, value=None):
        q = self.default if value is None else value
        if q not in self.allowed:
            raise InvalidRequest("Diese Verarbeitungsstufe ist auf dem konfigurierten VRAM-Profil nicht erlaubt.")
        return q

    def model(self, quality):
        quality = self.quality(quality)
        context, slots, kv = 32768, 1, "q8_0"
        if quality == "gruendlich":
            context, slots = (87552, 1) if self.tier == 16 else (262144, 3)
        elif quality == "sehr_gruendlich":
            context, kv = 262144, "q4_0"
        return Model(quality, self.model_paths[quality], context, slots, kv)

    def persistent(self, quality):
        return (self.tier, quality) in ((16, "basis"), (24, "gruendlich"))

    @property
    def baseline_llm(self):
        return self.default if self.persistent(self.default) else None

    def fallback(self, quality):
        index = QUALITIES.index(quality)
        candidate = QUALITIES[index - 1] if index else None
        return candidate if candidate in self.allowed else None


def detect_tier(index):
    try:
        value = subprocess.check_output(["nvidia-smi", "-i", str(index), "--query-gpu=memory.total", "--format=csv,noheader,nounits"], timeout=10, text=True)
        mib = int(value.strip())
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise ValueError("GPU-Speicher konnte nicht ermittelt werden; gpu.vram_gib explizit setzen.") from exc
    # Some driver versions reserve a few MiB in the reported total.
    for tier in (24, 16, 8):
        if mib >= tier * 1024 - 256:
            return tier
    raise ValueError("Für weniger als 8 GiB ist kein Profil hinterlegt.")


def load_settings(path):
    with open(path, "rb") as f:
        data = tomllib.load(f)
    known = {"server", "gpu", "policy", "backends", "models"}
    if set(data) - known:
        raise ValueError("Unbekannter Konfigurationsabschnitt.")
    mapping = {
        "server": {"host": "host", "port": "port", "token_env": "token_env"},
        "gpu": {"index": "gpu_index", "vram_gib": "tier", "diar_allocator_mib": "diar_allocator_mib"},
        "policy": {k: k for k in ("default_quality", "max_pending", "max_remembered", "max_payload_mib", "remember_seconds", "backend_timeout", "load_timeout", "control_timeout", "queue_timeout", "asr_parallel", "diar_parallel")},
        "backends": {k: k for k in ("asr_url", "diar_url", "llm_url", "llama_binary", "control_dir", "diar_control_dir", "prompt_path")},
    }
    values = {}
    for section, names in mapping.items():
        block = data.get(section, {})
        if not isinstance(block, dict):
            raise ValueError("Konfigurationsabschnitt muss eine Tabelle sein.")
        if set(block) - set(names):
            raise ValueError("Unbekannte Einstellung in %s." % section)
        values.update({names[k]: v for k, v in block.items()})
    if values.get("tier", "auto") == "auto":
        values["tier"] = detect_tier(values.get("gpu_index", 0))
    if "models" in data:
        if not isinstance(data["models"], dict):
            raise ValueError("Modelle müssen eine Tabelle sein.")
        paths = dict(Settings().model_paths)
        for q, block in data["models"].items():
            if q not in QUALITIES or not isinstance(block, dict) or set(block) != {"path"}:
                raise ValueError("Ein Modellabschnitt benötigt ausschließlich seinen Pfad.")
            paths[q] = block["path"]
        values["model_paths"] = paths
    return replace(Settings(), **values).validate()
