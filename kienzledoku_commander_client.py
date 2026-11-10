"""Python-3.9-kompatibler Commander-Client ohne Server-Abhängigkeiten."""
import json
import math
import os
import re
import stat
import sys
import uuid
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

LEGACY_QUALITIES = ("basis", "gruendlich", "sehr_gruendlich")
LEGACY_LABELS = {
    "basis": "Basis",
    "gruendlich": "Gründlich",
    "sehr_gruendlich": "Sehr gründlich",
}
# Kept for callers which used the original integration's public constants.
QUALITIES = LEGACY_QUALITIES
LABELS = LEGACY_LABELS
FINALIZED_HEADER = "X-Kienzledoku-Recording-Finalized"
QUALITY_RE = re.compile(r"[a-z0-9][a-z0-9_]{0,63}\Z")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def direct_open(request, timeout):
    """Open directly: proxies and redirects must not receive medical data."""
    return build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=timeout)


def _valid_text(value, maximum):
    return (isinstance(value, str) and value.strip() and len(value) <= maximum
            and not any(ord(char) < 32 for char in value))


def _quality_id(value):
    return isinstance(value, str) and QUALITY_RE.fullmatch(value) is not None


def profile_label(quality, profiles):
    for profile in profiles or ():
        if profile.get("id") == quality:
            return profile.get("label") or quality
    return LEGACY_LABELS.get(quality, quality)


class CommanderClient:
    def __init__(self, url, token_env="KIENZLEDOKU_COMMANDER_TOKEN",
                 request_timeout=2400, default_quality="auto", token_file=None,
                 token_loader=None, token_override=None):
        if not isinstance(url, str):
            raise ValueError("Commander-Adresse fehlt.")
        parsed = urlsplit(url)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or not parsed.port or parsed.path not in ("", "/")
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("Commander benötigt eine HTTP(S)-Basisadresse mit Port und ohne Zugangsdaten.")
        if not isinstance(token_env, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token_env):
            raise ValueError("Ungültige Commander-Tokenvariable.")
        if (type(request_timeout) not in (float, int) or not math.isfinite(request_timeout)
                or not 30 <= request_timeout <= 7200):
            raise ValueError("Commander-Zeitgrenze muss zwischen 30 und 7200 Sekunden liegen.")
        if default_quality != "auto" and not _quality_id(default_quality):
            raise ValueError("Unbekannte Commander-Standardqualität.")
        if token_file is not None and token_file != "" and (
                not isinstance(token_file, str)
                or not os.path.isabs(os.path.expanduser(token_file))):
            raise ValueError("Commander-Tokendatei benötigt einen absoluten Pfad.")
        if token_loader is not None and not callable(token_loader):
            raise ValueError("Ungültiger Commander-Zugangsspeicher.")
        self.url = url.rstrip("/")
        self.token_env = token_env
        self.timeout = request_timeout
        self.default_quality = default_quality
        self.token_file = os.path.expanduser(token_file) if token_file else None
        self.token_loader = token_loader
        self._token_override = (self._validate_token(token_override)
                                if token_override is not None else None)

    @staticmethod
    def _validate_token(token):
        if not isinstance(token, str):
            raise ValueError("Commander-Token ist ungültig.")
        token = token.strip()
        if token and (len(token) > 4096 or any(char.isspace() for char in token)):
            raise ValueError("Commander-Token ist ungültig.")
        return token

    @property
    def token(self):
        if self._token_override is not None:
            return self._token_override
        token = os.environ.get(self.token_env, "")
        if not token and self.token_file:
            try:
                info = os.lstat(self.token_file)
                owner_ok = True
                getuid = getattr(os, "getuid", None)
                if callable(getuid):
                    owner_ok = info.st_uid == getuid()
                if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077
                        or not owner_ok):
                    raise ValueError()
                with open(self.token_file, "r", encoding="utf-8") as handle:
                    token = handle.read(4097)
            except (OSError, ValueError):
                raise ValueError("Commander-Tokendatei muss privat und nur für den aktuellen Benutzer lesbar sein (0600).") from None
        if not token and self.token_loader:
            token = self.token_loader()
        token = self._validate_token(token)
        if not token and urlsplit(self.url).hostname not in ("localhost", "::1", "127.0.0.1"):
            raise ValueError("Commander-Token fehlt in der Umgebungsvariable %s." % self.token_env)
        return token

    def request(self, path, payload=None, timeout=None):
        if not isinstance(path, str) or not path.startswith("/") or "?" in path or "#" in path:
            raise ValueError("Ungültiger Commander-Pfad.")
        headers = {"Accept": "application/json"}
        token = self.token
        if token:
            headers["Authorization"] = "Bearer " + token
        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        try:
            with direct_open(Request(self.url + path, body, headers), timeout or self.timeout) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
                if len(raw) > 4 * 1024 * 1024:
                    raise ValueError()
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise ValueError()
                return value
        except HTTPError as exc:
            messages = {
                401: "Commander-Zugang abgelehnt. Token prüfen.",
                409: "Commander lehnt den Auftrag ab. Aufnahme muss zuerst vollständig beendet sein; Anfrage-ID prüfen.",
                429: "Commander-Queue ist voll. Gespräch später erneut zusammenfassen.",
                502: "Auch die erlaubte Ersatzstufe konnte keine vollständige Dokumentation erzeugen.",
                503: "Commander ist derzeit nicht bereit. Das Sprechertranskript bleibt erhalten.",
            }
            raise RuntimeError(messages.get(exc.code, "Commander-Anfrage fehlgeschlagen (HTTP %d)." % exc.code)) from None
        except (OSError, ValueError, UnicodeError):
            raise RuntimeError("Commander ist nicht erreichbar oder liefert keine gültige Antwort. Das Sprechertranskript bleibt zur erneuten Verarbeitung erhalten.") from None

    def profiles(self):
        value = self.request("/v1/runtime/profiles", timeout=3)
        try:
            raw_profiles = value["data"]
            if not isinstance(raw_profiles, list) or not raw_profiles or len(raw_profiles) > 64:
                raise ValueError()
            profiles = []
            ids = []
            default_count = 0
            for entry in raw_profiles:
                if not isinstance(entry, dict):
                    raise ValueError()
                quality = entry.get("id")
                label = entry.get("label", LEGACY_LABELS.get(quality, quality))
                persistent = entry.get("persistent")
                fallback = entry.get("fallback")
                is_default = entry.get("default", False)
                if (not _quality_id(quality) or quality in ids
                        or not _valid_text(label, 120)
                        or type(persistent) is not bool
                        or (fallback is not None and not _quality_id(fallback))
                        or type(is_default) is not bool):
                    raise ValueError()
                ids.append(quality)
                default_count += int(is_default)
                profiles.append({"id": quality, "label": label.strip(),
                                 "persistent": persistent,
                                 "default": is_default})
                if "fallback" in entry:
                    profiles[-1]["fallback"] = fallback
            if default_count > 1:
                raise ValueError()
            if any(profile.get("fallback") is not None and profile["fallback"] not in ids
                   for profile in profiles):
                raise ValueError()
            if self.default_quality != "auto" and self.default_quality not in ids:
                raise ValueError()
            return profiles
        except (KeyError, TypeError, ValueError):
            raise RuntimeError("Commander liefert keine gültigen Qualitätsprofile.") from None

    def extract(self, transcript, quality, profiles, recording_finalized=False):
        if recording_finalized is not True:
            raise ValueError("Die Aufnahme muss vor der Dokumentation vollständig beendet sein.")
        if not isinstance(transcript, str) or not transcript.strip():
            raise ValueError("Das Sprechertranskript ist leer.")
        allowed = [profile["id"] for profile in profiles]
        if not allowed or quality != "auto" and quality not in allowed:
            raise ValueError("Diese Qualitätsstufe ist auf dem Server nicht erlaubt.")
        payload = {"transcript": transcript, "recording_finalized": True,
                   "request_id": uuid.uuid4().hex}
        if quality != "auto":
            payload["quality"] = quality
        result = self.request("/v1/documentation/extract", payload)
        try:
            from kienzledoku_document import parse_documentation_json
            raw = result["documentation"]
            if not isinstance(raw, dict) or any(not isinstance(value, str) for value in raw.values()):
                raise ValueError()
            document = parse_documentation_json(raw)
            meta = result["commander"]
            requested = meta["requested_quality"]
            used = meta["used_quality"]
            fallback = meta["fallback_used"]
            if requested not in allowed or used not in allowed or type(fallback) is not bool:
                raise ValueError()
            if quality != "auto" and requested != quality:
                raise ValueError()
            if fallback != (requested != used):
                raise ValueError()
            requested_profile = next(profile for profile in profiles if profile["id"] == requested)
            declared_fallback = requested_profile.get("fallback")
            if fallback:
                if "fallback" in requested_profile:
                    if used != declared_fallback:
                        raise ValueError()
                elif (requested not in LEGACY_QUALITIES or used not in LEGACY_QUALITIES
                      or LEGACY_QUALITIES.index(requested) - LEGACY_QUALITIES.index(used) != 1):
                    # Compatibility with the first Linux API, whose reduced
                    # profile response did not expose its fixed one-step fallback.
                    raise ValueError()
            requested_label = profile_label(requested, profiles)
            used_label = profile_label(used, profiles)
            notice = ""
            if fallback:
                notice = ("Die Verarbeitung mit „%s“ ist fehlgeschlagen. "
                          "Die Dokumentation wurde mit „%s“ erstellt."
                          % (requested_label, used_label))
            return document, {
                "requested_quality": requested,
                "requested_quality_label": requested_label,
                "used_quality": used,
                "used_quality_label": used_label,
                "fallback_used": fallback,
                "notice": notice,
            }
        except (KeyError, StopIteration, TypeError, ValueError):
            raise RuntimeError("Commander hat keine vollständige Dokumentation mit gültiger Qualitätsangabe geliefert.") from None


def configured_client(block, token_override=None):
    if block is None:
        return None
    if not isinstance(block, dict) or type(block.get("enabled", False)) is not bool:
        raise ValueError("Commander-Konfiguration ist ungültig.")
    allowed = {"enabled", "url", "token_env", "token_file", "request_timeout", "default_quality"}
    if set(block) - allowed:
        raise ValueError("Unbekannte Commander-Einstellung.")
    if not block.get("enabled", False):
        return None
    # Import lazily: the transport and server's header constant remain usable
    # independently. An empty token_file uses the platform's private store.
    from kienzledoku_config import read_commander_token
    return CommanderClient(
        block.get("url"),
        block.get("token_env", "KIENZLEDOKU_COMMANDER_TOKEN"),
        block.get("request_timeout", 2400),
        block.get("default_quality", "auto"),
        block.get("token_file") or None,
        token_loader=read_commander_token,
        token_override=token_override,
    )
