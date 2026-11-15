"""Commander configuration, including legacy Linux profiles and 1.4 options."""
from dataclasses import dataclass, field, replace
from pathlib import Path
import os
import subprocess
import sys
import tomllib
from urllib.parse import urlsplit

from kienzledoku_document import DEFAULT_DOCUMENT_FIELDS, validate_fields
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
    model_id: str = ""
    label: str = ""

    @property
    def context_per_slot(self):
        if self.slots == 1:
            return self.context
        # llama.cpp rounds per-slot context to 256-token blocks.
        return ((self.context + self.slots * 256 - 1) // (self.slots * 256)) * 256


def _platform():
    return "macos" if sys.platform == "darwin" else "linux"


@dataclass(frozen=True)
class Settings:
    tier: int = 24
    default_quality: str = "auto"
    host: str = "127.0.0.1"
    port: int = 8185
    auth_enabled: bool = False
    token_env: str = "KIENZLEDOKU_COMMANDER_TOKEN"
    asr_url: str = "http://127.0.0.1:8179"
    diar_url: str = "http://127.0.0.1:8183"
    llm_url: str = "http://127.0.0.1:8086"
    llama_binary: str = "/opt/kienzlefon-ai/bin/llama-server"
    control_dir: str = "/run/kienzledoku-commander"
    diar_control_dir: str | None = None
    prompt_path: str = str(Path(__file__).resolve().parents[1] / "prompt_documentation.txt")
    platform: str = "linux"
    asr_command: tuple = ()
    diar_command: tuple = ()
    asr_model_path: str = ""
    diar_model_path: str = ""
    memory_mode: str | None = None
    diarization_mode: str | None = None
    asr_on_demand: bool = False
    enabled_roles: tuple = ("asr", "diar", "llm")
    enabled_fields: tuple = DEFAULT_DOCUMENT_FIELDS
    remote_llm_url: str = ""
    remote_llm_token_env: str = "KIENZLEDOKU_REMOTE_LLM_TOKEN"
    gpu_index: int = 0
    diar_allocator_mib: int = 2048
    max_pending: int = 128
    max_remembered: int = 256
    max_payload_mib: int = 512
    remember_seconds: float = 300
    backend_timeout: float = 7200
    load_timeout: float = 180
    control_timeout: float = 180
    queue_timeout: float = 900
    metadata_timeout: float = 5
    asr_parallel: int = 1
    diar_parallel: int = 1
    model_paths: dict = field(default_factory=lambda: {
        "basis": "/opt/kienzlefon-ai/models/Qwen_Qwen3.5-9B-Q4_K_M.gguf",
        "gruendlich": "/opt/kienzlefon-ai/models/Qwen_Qwen3.5-9B-Q6_K.gguf",
        "sehr_gruendlich": "/opt/kienzlefon-ai/models/Qwen3.8-27B-UD-Q4_K_M.gguf",
    })
    model_options: dict = field(default_factory=dict)
    explicit_models: bool = False

    def validate(self):
        ints = ("tier", "port", "gpu_index", "diar_allocator_mib", "max_pending", "max_remembered", "max_payload_mib", "asr_parallel", "diar_parallel")
        if any(type(getattr(self, key)) is not int for key in ints):
            raise ValueError("Ganzzahlige Einstellung erwartet.")
        times = ("remember_seconds", "backend_timeout", "load_timeout", "control_timeout", "queue_timeout", "metadata_timeout")
        if any(type(getattr(self, key)) not in (int, float) for key in times):
            raise ValueError("Numerische Zeitgrenze erwartet.")
        strings = ("default_quality", "host", "token_env", "asr_url", "diar_url", "llm_url", "llama_binary", "control_dir", "prompt_path", "platform", "remote_llm_token_env")
        if any(not isinstance(getattr(self, key), str) or not getattr(self, key) for key in strings):
            raise ValueError("Texteinstellung erwartet.")
        if type(self.auth_enabled) is not bool or type(self.asr_on_demand) is not bool:
            raise ValueError("Boolesche Einstellung erwartet.")
        if self.auth_enabled and not os.environ.get(self.token_env):
            raise ValueError("Aktivierte Authentifizierung benötigt den Inhalt von token_env.")
        if self.tier not in ALLOWED or self.platform not in ("linux", "macos"):
            raise ValueError("VRAM-Profil oder Plattform ist ungültig.")
        if self.memory_mode not in (None, "serial", "parallel"):
            raise ValueError("memory_mode muss serial oder parallel sein.")
        if self.diarization_mode not in (None, 'resident', 'with_asr', 'serial'):
            raise ValueError('diarization_mode muss resident, with_asr oder serial sein.')
        roles = tuple(self.enabled_roles)
        if not roles or len(set(roles)) != len(roles) or set(roles) - {"asr", "diar", "llm"}:
            raise ValueError("enabled_roles ist ungültig.")
        fields = validate_fields(tuple(self.enabled_fields))
        object.__setattr__(self, "enabled_roles", roles)
        object.__setattr__(self, "enabled_fields", fields)
        for value in (self.asr_url, self.diar_url, self.llm_url):
            u = urlsplit(value)
            if u.scheme != "http" or u.hostname not in ("127.0.0.1", "localhost", "::1") or not u.port or u.username or u.password or u.query or u.fragment or u.path not in ("", "/"):
                raise ValueError("Interne Backends müssen lokale HTTP-Adressen mit Port sein.")
        if self.llm_url.rstrip("/") in (self.asr_url.rstrip("/"), self.diar_url.rstrip("/")) or urlsplit(self.llm_url).port == self.port:
            raise ValueError("Commander und Backends benötigen getrennte Ports.")
        if self.remote_llm_url:
            u = urlsplit(self.remote_llm_url)
            if u.scheme not in ("http", "https") or not u.hostname or not u.port or u.username or u.password or u.query or u.fragment or u.path not in ("", "/"):
                raise ValueError("remote_llm.url benötigt ein explizites HTTP(S)-Ziel mit Port.")
            if u.port == self.port and u.hostname in (self.host, "127.0.0.1", "localhost", "::1", "0.0.0.0", "::"):
                raise ValueError("Der Commander darf sich nicht selbst als Remote-Ziel verwenden.")
        if not 1 <= self.port <= 65535 or not Path(self.control_dir).is_absolute():
            raise ValueError("Port oder Steuerungsverzeichnis ist ungültig.")
        if self.diar_control_dir is not None and (not isinstance(self.diar_control_dir, str) or not Path(self.diar_control_dir).is_absolute()):
            raise ValueError("Diarisierungs-Steuerverzeichnis benötigt einen absoluten Pfad.")
        if not Path(self.llama_binary).is_absolute() or not Path(self.prompt_path).is_absolute():
            raise ValueError("Binärdatei und Prompt benötigen absolute Pfade.")
        for command in (self.asr_command, self.diar_command):
            if command and (not isinstance(command, (tuple, list)) or len(command) < 2 or
                            any(not isinstance(v, str) or not v for v in command) or
                            not Path(command[0]).is_absolute() or not Path(command[1]).is_absolute()):
                raise ValueError("Worker-Kommandos benötigen absolute Python- und Scriptpfade.")
        if self.platform == "macos" and self.memory_mode is not None:
            for role, command, model_path in (("asr", self.asr_command, self.asr_model_path), ("diar", self.diar_command, self.diar_model_path)):
                if role in roles and (not command or not model_path or not Path(model_path).is_absolute()):
                    raise ValueError("Aktivierte macOS-Worker benötigen Kommando und absoluten Modellpfad.")
        if self.gpu_index < 0 or not 256 <= self.diar_allocator_mib <= 6144:
            raise ValueError("GPU-Index oder pyannote-Budget ist ungültig.")
        if not 1 <= self.max_pending <= self.max_remembered <= 4096 or not 1 <= self.max_payload_mib <= 4096:
            raise ValueError("Die Anfragelimits sind ungültig.")
        limits = {"remember_seconds": 3600, "backend_timeout": 7200, "load_timeout": 600,
                  "control_timeout": 600, "queue_timeout": 3600, "metadata_timeout": 30}
        if any(not 0 < getattr(self, key) <= limit for key, limit in limits.items()):
            raise ValueError("Zeitgrenzen sind ungültig.")
        if not 1 <= self.asr_parallel <= 16 or not 1 <= self.diar_parallel <= 16:
            raise ValueError("Die Worker-Anzahl ist ungültig.")
        if "llm" in roles and not self.remote_llm_url and not self.allowed:
            raise ValueError("Mindestens ein LLM-Profil muss konfiguriert sein.")
        if self.default_quality != "auto" and self.default_quality not in self.allowed:
            raise ValueError("Die Standardstufe ist nicht verfügbar.")
        if any(not isinstance(self.model_paths.get(q), str) or not Path(self.model_paths[q]).is_absolute() for q in self.allowed):
            raise ValueError("Modellpfade müssen absolut sein.")
        for q, options in self.model_options.items():
            if q not in self.model_paths or not isinstance(options, dict):
                raise ValueError("Modelloptionen sind ungültig.")
            if "model_id" in options and (not isinstance(options["model_id"], str) or not options["model_id"]):
                raise ValueError("model_id ist ungültig.")
            if "label" in options and (not isinstance(options["label"], str) or not options["label"]):
                raise ValueError("Modelllabel ist ungültig.")
            if "context" in options and (type(options["context"]) is not int or options["context"] < 1024):
                raise ValueError("Modellkontext ist ungültig.")
            if "slots" in options and (type(options["slots"]) is not int or not 1 <= options["slots"] <= 32):
                raise ValueError("Modellslots sind ungültig.")
            if "kv" in options and (not isinstance(options["kv"], str) or not options["kv"]):
                raise ValueError("KV-Typ ist ungültig.")
        return self

    @property
    def allowed(self):
        if "llm" not in self.enabled_roles or self.remote_llm_url:
            return ()
        return tuple(q for q in QUALITIES if q in self.model_paths) if self.explicit_models else ALLOWED[self.tier]

    @property
    def default(self):
        if not self.allowed:
            return None
        if self.default_quality != "auto":
            return self.default_quality
        preferred = DEFAULTS[self.tier]
        return preferred if preferred in self.allowed else self.allowed[0]

    def quality(self, value=None):
        q = self.default if value is None else value
        if q not in self.allowed:
            raise InvalidRequest("Diese Verarbeitungsstufe ist nicht verfügbar.")
        return q

    def model(self, quality):
        quality = self.quality(quality)
        context, slots, kv = 32768, 1, "q8_0"
        if quality == "gruendlich":
            context, slots = ((87552, 1) if self.tier == 16 else (262144, 3))
        elif quality == "sehr_gruendlich":
            context, kv = 262144, "q4_0"
        options = self.model_options.get(quality, {})
        return Model(quality, self.model_paths[quality], options.get("context", context), options.get("slots", slots),
                     options.get("kv", kv), options.get("model_id", quality), options.get("label", LABELS[quality]))

    def runtime_quality(self, quality):
        """Stable backend identity; public request qualities remain unchanged."""
        return quality

    def persistent(self, quality):
        if self.memory_mode == "serial": return False
        if self.memory_mode == "parallel": return True
        return (self.tier, quality) in ((16, "basis"), (24, "gruendlich"))

    @property
    def baseline_llm(self):
        if "llm" not in self.enabled_roles or self.remote_llm_url or self.memory_mode == "serial": return None
        return self.default if self.persistent(self.default) else None

    def fallback(self, quality):
        if self.remote_llm_url: return None
        index = QUALITIES.index(quality)
        candidate = QUALITIES[index - 1] if index else None
        return candidate if candidate in self.allowed else None


def detect_tier(index):
    try:
        value = subprocess.check_output(["nvidia-smi", "-i", str(index), "--query-gpu=memory.total", "--format=csv,noheader,nounits"], timeout=10, text=True)
        mib = int(value.strip())
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise ValueError("GPU-Speicher konnte nicht ermittelt werden; gpu.vram_gib explizit setzen.") from exc
    for tier in (24, 16, 8):
        if mib >= tier * 1024 - 256: return tier
    raise ValueError("Für weniger als 8 GiB ist kein Profil hinterlegt.")


def load_settings(path):
    with open(path, "rb") as f: data = tomllib.load(f)
    if set(data) - {"server", "gpu", "policy", "backends", "models", "remote_llm"}:
        raise ValueError("Unbekannter Konfigurationsabschnitt.")
    mapping = {
        "server": {k: k for k in ("host", "port", "token_env", "auth_enabled")},
        "gpu": {"index": "gpu_index", "vram_gib": "tier", "diar_allocator_mib": "diar_allocator_mib"},
        "policy": {k: k for k in ("default_quality", "memory_mode", "diarization_mode", "asr_on_demand", "enabled_roles", "enabled_fields", "max_pending", "max_remembered", "max_payload_mib", "remember_seconds", "backend_timeout", "load_timeout", "control_timeout", "queue_timeout", "metadata_timeout", "asr_parallel", "diar_parallel")},
        "backends": {k: k for k in ("platform", "asr_url", "diar_url", "llm_url", "llama_binary", "control_dir", "diar_control_dir", "prompt_path", "asr_command", "diar_command", "asr_model_path", "diar_model_path")},
        "remote_llm": {"url": "remote_llm_url", "token_env": "remote_llm_token_env"},
    }
    values = {}
    for section, names in mapping.items():
        block = data.get(section, {})
        if not isinstance(block, dict) or set(block) - set(names): raise ValueError("Unbekannte Einstellung in %s." % section)
        values.update({names[k]: v for k, v in block.items()})
    values.setdefault("platform", _platform())
    if values.get("tier", "auto") == "auto":
        values["tier"] = 24 if values.get("platform", _platform()) == "macos" else detect_tier(values.get("gpu_index", 0))
    if "models" in data:
        if not isinstance(data["models"], dict) or not data["models"]: raise ValueError("Modelle müssen eine nichtleere Tabelle sein.")
        explicit = any(isinstance(v, dict) and "model_id" in v for v in data["models"].values())
        paths = {} if explicit else dict(Settings().model_paths)
        options = {}
        permitted = {"path", "model_id", "label", "context", "slots", "kv"}
        for q, block in data["models"].items():
            if q not in QUALITIES or not isinstance(block, dict) or "path" not in block or set(block) - permitted:
                raise ValueError("Ein Modellabschnitt benötigt mindestens seinen Pfad.")
            paths[q] = block["path"]
            options[q] = {k: v for k, v in block.items() if k != "path"}
        values.update(model_paths=paths, model_options=options, explicit_models=explicit)
    for key in ("enabled_roles", "enabled_fields", "asr_command", "diar_command"):
        if key in values:
            if not isinstance(values[key], list):
                raise ValueError("Listen-Einstellung erwartet: " + key)
            values[key] = tuple(values[key])
    return replace(Settings(), **values).validate()
