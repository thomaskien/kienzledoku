#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kienzledoku record 1.8.2 <-> T2med FHIR client.

Target: Python 3.9+ (macOS, Ubuntu 24.04 LTS) and bundled Python 3.12 (Windows).
Platform-independent FHIR/UI core with optional compiled Connect transport.

Security model inherited from the confirmed T2med v0.1.2 round-trip:
- accepts only loopback and the T2med FHIR host selected during installation
- OAuth token is kept in memory only and never logged/displayed
- T2med's public demo API key is used only if no Keychain/env override exists
- installation-specific APS certificates are accepted only for the configured endpoint
"""

from __future__ import print_function

import argparse
import errno
import html
import json
import os
import secrets
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import kienzledoku_config as record_config
from kienzledoku_connect import ConnectProxy
from kienzledoku_http import SecureLocalHandler, configure_server
from kienzledoku_session import (ActiveSessionError, acquire as acquire_record_session,
    cleanup_legacy_patient_data, session_dir, register_window, start_active_broker,
    unregister_window)

from kienzledoku_document import (
    DOCUMENT_FIELDS,
    DOCUMENT_CODES,
    DEFAULT_DOCUMENT_FIELDS,
    DOCUMENT_LABELS,
    OUTPUT_MODE_SINGLE,
    OUTPUT_MODE_STRUCTURED,
    compose_single_block,
    empty_documentation,
    nonempty_fields,
    normalize_documentation,
    normalize_entry_code,
    normalize_output_mode,
    parse_documentation_json,
    validate_fields,
)
from kienzledoku_speech import (
    ACTIVE_STATUSES,
    STATUS_ERROR,
    STATUS_PROCESSING,
    STATUS_READY,
    STATUS_RECORDING,
    SpeechRecognitionManager,
)

APP_NAME = "kienzledoku record"
VERSION = "1.8.2"
LINUX_NATIVE_WINDOW_PATH = "/usr/local/libexec/kienzledoku/kienzledoku_window_linux"

# Public test/demo key from T2med's reference application (not a secret).
# Demo/test/integration only; never use for production.
DEMO_API_KEY = "7QwA7931lJSQfMKuTH4MQXLn4YEiNhE5tggnYKlY4HE"
KEYCHAIN_SERVICE = "Kienzledoku-T2med-API-Key"
LEGACY_KEYCHAIN_SERVICE = "WhisperDoku-T2med-API-Key"
if sys.platform == "darwin":
    LOG_PATH = os.path.expanduser("~/Library/Logs/Kienzledoku.log")
    SERVICE_CONFIG_PATH = os.path.expanduser(
        "~/Library/Application Support/Kienzledoku/config.json"
    )
    INSTALLER_NAME = "install_macos.command"
elif sys.platform.startswith("linux"):
    def _xdg_home(name, fallback):
        value = os.path.expanduser(os.environ.get(name, "").strip())
        return value if value and os.path.isabs(value) else os.path.expanduser(fallback)

    _XDG_CONFIG_HOME = _xdg_home("XDG_CONFIG_HOME", "~/.config")
    _XDG_STATE_HOME = _xdg_home("XDG_STATE_HOME", "~/.local/state")
    LOG_PATH = os.path.join(_XDG_STATE_HOME, "kienzledoku", "kienzledoku.log")
    SERVICE_CONFIG_PATH = os.path.join(
        _XDG_CONFIG_HOME, "kienzledoku", "config.json"
    )
    INSTALLER_NAME = "install_linux.sh"
else:
    LOG_PATH = os.path.expanduser("~/.kienzledoku/kienzledoku.log")
    SERVICE_CONFIG_PATH = os.path.expanduser("~/.kienzledoku/config.json")
    INSTALLER_NAME = "den Plattform-Installer"
SERVICE_CONFIG_PATH = str(record_config.config_path())
if sys.platform == 'win32':
    LOG_PATH = str(record_config.config_dir() / 'record.log')
    INSTALLER_NAME = 'den Windows-Installer'
_LOG_LOCK = threading.Lock()
_SESSION_LOCK_HANDLE = None

IDENTIFIER_SYSTEM_KONTEXT = "https://fhir.t2med.de/identifier/kontext"
PROFILE_PATIENT = "https://fhir.t2med.de/StructureDefinition/FhirApiPatient|1.0.0"
PROFILE_ANAMNESE = "https://fhir.t2med.de/StructureDefinition/FhirApiObservationAnamnese|1.0.0"
PROFILE_BEFUND = "https://fhir.t2med.de/StructureDefinition/FhirApiObservationBefund|1.0.0"
PROFILE_FREITEXT = "https://fhir.t2med.de/StructureDefinition/FhirApiObservationFreitext|1.0.0"
PROFILE_THERAPIE = "https://fhir.t2med.de/StructureDefinition/FhirApiProcedureTherapie|1.0.0"
PROFILE_PROZEDERE = "https://fhir.t2med.de/StructureDefinition/FhirApiProcedureProcedere|1.0.0"
EXTENSION_FREITEXT_KUERZEL = "https://fhir.t2med.de/StructureDefinition/FhirApiFreitextKuerzel"

LOOPBACK_FHIR_HOSTS = frozenset(("127.0.0.1", "localhost", "::1"))

DEFAULT_OUTPUT_MODE = os.environ.get(
    "KIENZLEDOKU_T2MED_OUTPUT_MODE", OUTPUT_MODE_STRUCTURED
).strip().lower()
if DEFAULT_OUTPUT_MODE not in (OUTPUT_MODE_STRUCTURED, OUTPUT_MODE_SINGLE):
    DEFAULT_OUTPUT_MODE = OUTPUT_MODE_STRUCTURED
DEFAULT_SINGLE_CODE = os.environ.get("KIENZLEDOKU_T2MED_KUERZEL", "KI").strip() or "KI"


class FhirError(Exception):
    def __init__(self, message, status=None, body=None):
        super(FhirError, self).__init__(message)
        self.status = status
        self.body = body


class FhirTransactionRejected(FhirError):
    """A complete T2med transaction outcome explicitly confirms rollback."""


def safe_log(event, **fields):
    """Append diagnostic metadata without OAuth token/API key contents."""
    try:
        parent = os.path.dirname(LOG_PATH)
        if parent:
            os.makedirs(parent, mode=0o700, exist_ok=True)
        parts = [datetime.now().astimezone().isoformat(timespec="seconds"), str(event)]
        for key in sorted(fields):
            value = fields[key]
            if value is None:
                value = ""
            text = str(value).replace("\n", " ").replace("\r", " ")
            parts.append("%s=%s" % (key, text))
        line = " | ".join(parts) + "\n"
        with _LOG_LOCK:
            descriptor = os.open(
                LOG_PATH,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o600,
            )
            with os.fdopen(descriptor, "a", encoding="utf-8") as fh:
                fh.write(line)
    except Exception:
        pass


def read_deep_link_stdin(stream=None):
    """Read a one-shot deep link from a pipe without persisting it."""
    source = stream or sys.stdin
    value = source.read(65537)
    if len(value) > 65536:
        raise ValueError("Deep Link ist unerwartet groß")
    value = value.strip()
    if not value:
        raise ValueError("Deep-Link-Pipe ist leer")
    return value


def notify_start_failure(error=None):
    """Show startup failures even when the launcher discards stderr.

    Only an allowlisted category reaches the native dialog, never exception
    text, a deep link, a token or a patient identity.
    """
    if sys.platform == 'darwin':
        from kienzledoku_commander_client import CommanderRequestError
        category = 'generic'
        if isinstance(error, CommanderRequestError):
            category = 'commander-auth' if error.status == 401 else 'commander'
        try:
            subprocess.run([str(Path(__file__).with_name('kienzledoku_window')),
                            '--startup-error', category], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           check=False)
        except OSError:
            safe_log('Startup error dialog unavailable')
        return
    if not sys.platform.startswith("linux") or not shutil.which("notify-send"):
        return
    try:
        subprocess.run(
            [
                "notify-send",
                "--app-name=kienzledoku record",
                "kienzledoku record konnte nicht gestartet werden",
                "Details stehen im geschützten Diagnoseprotokoll.",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False,
        )
    except Exception:
        pass


def acquire_session_lock():
    """Allow only one active Linux documentation session per desktop user."""
    global _SESSION_LOCK_HANDLE
    if not sys.platform.startswith("linux") or _SESSION_LOCK_HANDLE is not None:
        return

    import fcntl

    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "").strip()
    if not runtime_dir or not os.path.isabs(runtime_dir):
        runtime_dir = os.path.dirname(LOG_PATH)
    os.makedirs(runtime_dir, mode=0o700, exist_ok=True)
    lock_path = os.path.join(runtime_dir, "kienzledoku-session.lock")
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    handle = os.fdopen(descriptor, "w")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        if exc.errno not in (errno.EACCES, errno.EAGAIN):
            raise
        raise RuntimeError(
            "Es ist bereits eine Kienzledoku-Sitzung aktiv. "
            "Bitte zuerst das vorhandene Fenster abschließen oder schließen."
        )
    handle.write(str(os.getpid()))
    handle.flush()
    _SESSION_LOCK_HANDLE = handle


def deep_link_metadata(url):
    """Extract only non-secret metadata for diagnostics; never returns query values."""
    try:
        parsed = urllib.parse.urlparse(url or "")
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        fhir_values = query.get("fhirBasisUrl", [])
        fhir_url = fhir_values[0] if fhir_values else ""
        fhir_parsed = urllib.parse.urlparse(fhir_url) if fhir_url else None
        return {
            "scheme": parsed.scheme or "(leer)",
            "path": parsed.path or "",
            "kontextId_present": "yes" if query.get("kontextId") else "no",
            "fhirBasisUrl_present": "yes" if fhir_values else "no",
            "fhir_host": (fhir_parsed.hostname if fhir_parsed else "") or "",
            "fhir_port": (fhir_parsed.port if fhir_parsed else "") or "",
            "oauthToken_present": "yes" if query.get("oAuthToken") else "no",
        }
    except Exception as exc:
        return {"metadata_error": type(exc).__name__}


def mask(value, keep=5):
    if not value:
        return "(leer)"
    if len(value) <= keep * 2:
        return "***"
    return value[:keep] + "…" + value[-keep:]


def get_api_key():
    """Private production build, otherwise environment/store/public demo key."""
    from kienzledoku_product_key import embedded_api_key
    embedded = embedded_api_key()
    if embedded is not None:
        return embedded
    for env_name in ("KIENZLEDOKU_T2MED_API_KEY", "WHISPERDOKU_T2MED_API_KEY"):
        env_key = os.environ.get(env_name, "").strip()
        if env_key:
            return env_key, "Umgebungsvariable %s" % env_name

    windows_key = record_config.read_windows_key()
    if windows_key:
        return windows_key, 'Windows-Zugangsdaten (DPAPI)'

    if sys.platform == "darwin":
        for service, label in (
            (KEYCHAIN_SERVICE, "macOS-Schlüsselbund"),
            (LEGACY_KEYCHAIN_SERVICE, "macOS-Schlüsselbund (Altname)"),
        ):
            try:
                proc = subprocess.run(
                    ["/usr/bin/security", "find-generic-password", "-s", service, "-w"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=3,
                    check=False,
                )
                key = proc.stdout.strip()
                if proc.returncode == 0 and key:
                    return key, label
            except Exception:
                pass

    if sys.platform.startswith("linux") and shutil.which("secret-tool"):
        try:
            proc = subprocess.run(
                [
                    "secret-tool", "lookup",
                    "application", "kienzledoku",
                    "service", "t2med-api-key",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=5,
                check=False,
            )
            key = proc.stdout.strip()
            if proc.returncode == 0 and key:
                return key, "Linux-Schlüsselbund (Secret Service)"
        except Exception:
            pass

    return DEMO_API_KEY, "öffentlicher T2med-Demo-Key (max. 100 FHIR-Requests pro APS-Serverprozess)"


def parse_deep_link(url, config_path=None):
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme:
        raise ValueError("Deep Link hat kein URL-Schema")
    if parsed.scheme.lower() not in ("kienzledoku", "kienzledoku-record", "t2demo", "whisperdoku"):
        raise ValueError("Deep Link verwendet kein erlaubtes kienzledoku record-URL-Schema")
    if parsed.scheme.lower() == 'kienzledoku-record' and (parsed.netloc != 'record' or parsed.path not in ('', '/') or parsed.fragment):
        raise ValueError('Direkter Aufruf benötigt kienzledoku-record://record')

    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

    def one(name):
        values = query.get(name, [])
        if not values and name == "oAuthToken":
            return ""
        if len(values) != 1 or not values[0].strip():
            raise ValueError('T2med-Aufruf benötigt genau einen Wert für ' + name)
        value = values[0].strip()
        if any(ord(char) < 32 for char in value):
            raise ValueError('Ungültiger Kontextparameter')
        return value

    context_id = one("kontextId")
    fhir_base_url = one("fhirBasisUrl")
    oauth_token = one("oAuthToken")

    if not context_id:
        raise ValueError("Deep Link enthält keine kontextId")
    if not fhir_base_url:
        raise ValueError("Deep Link enthält keine fhirBasisUrl")

    validate_local_fhir_url(fhir_base_url, config_path=config_path)

    return {
        "scheme": parsed.scheme,
        "context_id": context_id,
        "fhir_base_url": fhir_base_url.rstrip("/"),
        "oauth_token": oauth_token,
    }


def configured_fhir_hosts(config_path=None):
    """Return loopback plus the exact T2med FHIR host selected by the installer."""
    path = config_path or SERVICE_CONFIG_PATH
    hosts = set(LOOPBACK_FHIR_HOSTS)
    if str(path).endswith('.toml'):
        cfg = record_config.load(path)
        hosts.add(urllib.parse.urlsplit(cfg['connection']['target']).hostname)
        return hosts
    try:
        with open(path, "r", encoding="utf-8") as handle:
            configured = json.load(handle).get("t2med", {}).get("fhir_host", "")
        if isinstance(configured, str) and configured.strip():
            hosts.add(configured.strip().lower())
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return hosts


def validate_local_fhir_url(url, config_path=None):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() != "https":
        raise ValueError("kienzledoku record %s akzeptiert ausschließlich HTTPS-FHIR-URLs" % VERSION)
    host = (parsed.hostname or "").lower()
    allowed_hosts = configured_fhir_hosts(config_path=config_path)
    if host not in allowed_hosts:
        raise ValueError(
            "kienzledoku record %s akzeptiert nur explizit freigegebene T2med-FHIR-Hosts. "
            "Erlaubt sind %s; erhalten: %s. Bitte %s erneut ausführen."
            % (
                VERSION,
                ", ".join(sorted(allowed_hosts)),
                host or "(kein Host)",
                INSTALLER_NAME,
            )
        )
    if "/aps/fhir/api/r4" not in parsed.path:
        raise ValueError("FHIR-Basis-URL enthält nicht den erwarteten Pfad /aps/fhir/api/r4")


def local_ssl_context():
    # Test/integration only: T2med explicitly uses installation-specific local certs.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def operation_outcome_text(obj):
    if not isinstance(obj, dict) or obj.get("resourceType") != "OperationOutcome":
        return ""
    parts = []
    for issue in obj.get("issue", []) or []:
        if not isinstance(issue, dict):
            continue
        severity = issue.get("severity", "")
        diagnostics = issue.get("diagnostics", "")
        details = issue.get("details", {}) or {}
        text = details.get("text", "") if isinstance(details, dict) else ""
        msg = diagnostics or text or issue.get("code", "")
        if msg:
            parts.append((severity + ": " if severity else "") + str(msg))
    return "; ".join(parts)


def operation_outcome_errors(obj):
    """Return only error/fatal diagnostics from an OperationOutcome."""
    if not isinstance(obj, dict) or obj.get("resourceType") != "OperationOutcome":
        return []
    errors = []
    for issue in obj.get("issue", []) or []:
        if not isinstance(issue, dict) or issue.get("severity") not in ("error", "fatal"):
            continue
        details = issue.get("details", {}) or {}
        detail_text = details.get("text", "") if isinstance(details, dict) else ""
        message = issue.get("diagnostics") or detail_text or issue.get("code") or "FHIR-Fehler"
        errors.append(str(message))
    return errors


class T2medFhirClient(object):
    def __init__(self, base_url, context_id, oauth_token, api_key, connection=None):
        validate_local_fhir_url(base_url)
        self.base_url = base_url.rstrip("/")
        self.context_id = context_id
        self.oauth_token = oauth_token or ""
        self.api_key = api_key
        self.proxy = None
        if connection is not None:
            candidate = record_config.defaults()
            candidate['connection'] = connection
            record_config.validate_target(base_url, candidate)
        self.ssl_context = record_config.ssl_context(connection) if connection else local_ssl_context()
        if connection and connection['mode'] == 'connect':
            self.proxy = ConnectProxy(connection)
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(), urllib.request.HTTPSHandler(context=self.ssl_context))

    def close(self):
        if self.proxy:
            self.proxy.close()
        self.oauth_token = ''
        self.api_key = ''

    def _headers(self, content=False, patient_profile=False):
        headers = {
            "Accept": "application/fhir+json",
            "Prefer": "return=OperationOutcome",
            "X-API-Key": self.api_key,
            "X-TreatWarningAsError": "true",
            "User-Agent": "kienzledoku-record/%s" % VERSION,
        }
        if self.proxy:
            headers['X-Kienzledoku-Connect-Token'] = self.proxy.token
        if self.oauth_token:
            headers["Authorization"] = "Bearer " + self.oauth_token
        if content:
            headers["Content-Type"] = "application/fhir+json"
        if patient_profile:
            headers["X-FHIR-Profile"] = PROFILE_PATIENT
        return headers

    def _request(self, method, path, body=None, patient_profile=False):
        url = (self.proxy.url if self.proxy else self.base_url) + (path or "/" if self.proxy else path)
        resource = path.split("?", 1)[0] or "/"
        safe_log("FHIR request", method=method, resource=resource)
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=data,
            headers=self._headers(content=(body is not None), patient_profile=patient_profile),
            method=method,
        )
        try:
            with self.opener.open(req, timeout=60) as response:
                raw = response.read().decode("utf-8", errors="replace")
                status = response.getcode()
        except urllib.error.HTTPError as exc:
            safe_log("FHIR HTTP error", method=method, resource=resource, status=exc.code)
            raw = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            try:
                obj = json.loads(raw) if raw else None
            except Exception:
                obj = None
            outcome = operation_outcome_text(obj)
            msg = "FHIR HTTP %s" % exc.code
            if outcome:
                msg += ": " + outcome
            elif raw:
                msg += ": " + raw[:500]
            raise FhirError(msg, status=exc.code, body=obj)
        except urllib.error.URLError as exc:
            safe_log("FHIR connection error", method=method, resource=resource, error=type(exc.reason).__name__)
            raise FhirError("FHIR-Verbindung fehlgeschlagen. Ziel und Zertifikat prüfen.") from None
        except Exception as exc:
            safe_log("FHIR call error", method=method, resource=resource, error=type(exc).__name__)
            raise FhirError("FHIR-Antwort fehlt oder ist ungültig. Schreibausgang gegebenenfalls in T2med prüfen.") from None

        safe_log("FHIR response", method=method, resource=resource, status=status)
        if not raw:
            return status, None
        try:
            obj = json.loads(raw)
        except Exception:
            raise FhirError("FHIR-Antwort ist kein gültiges JSON (HTTP %s)" % status, status=status)
        return status, obj

    def get_patient_by_context(self):
        identifier = IDENTIFIER_SYSTEM_KONTEXT + "|" + self.context_id
        query = urllib.parse.urlencode({"identifier": identifier})
        status, obj = self._request("GET", "/Patient?" + query, patient_profile=True)
        patient = normalize_patient_result(obj)
        if patient is None:
            raise FhirError("Keine eindeutige Patientenzuordnung für den T2med-Kontext. Übernahme gesperrt.", status=status, body=obj)
        return patient

    def get_encounter(self):
        path = "/Encounter/" + urllib.parse.quote(self.context_id, safe="")
        _status, obj = self._request("GET", path)
        if not isinstance(obj, dict) or obj.get("resourceType") != "Encounter":
            raise FhirError("Encounter-Antwort ist unerwartet", body=obj)
        return obj

    def build_observation(self, kind, text, timestamp=None):
        if kind == "anamnese":
            profile = PROFILE_ANAMNESE
        elif kind == "befund":
            profile = PROFILE_BEFUND
        else:
            raise ValueError("Unbekannter Observation-Typ: %s" % kind)

        text = (text or "").strip()
        if not text:
            raise ValueError("Text ist leer")

        return {
            "resourceType": "Observation",
            "meta": {"profile": [profile]},
            "identifier": [
                {"system": IDENTIFIER_SYSTEM_KONTEXT, "value": self.context_id}
            ],
            "status": "final",
            "effectiveDateTime": timestamp or datetime.now().astimezone().isoformat(timespec="seconds"),
            "valueString": text,
        }

    def build_procedure(self, kind, text, timestamp=None):
        if kind == "therapie":
            profile = PROFILE_THERAPIE
        elif kind == "prozedere":
            profile = PROFILE_PROZEDERE
        else:
            raise ValueError("Unbekannter Procedure-Typ: %s" % kind)

        text = (text or "").strip()
        if not text:
            raise ValueError("Text ist leer")

        return {
            "resourceType": "Procedure",
            "meta": {"profile": [profile]},
            "identifier": [
                {"system": IDENTIFIER_SYSTEM_KONTEXT, "value": self.context_id}
            ],
            "status": "completed",
            "code": {"text": text},
            "performedDateTime": timestamp or datetime.now().astimezone().isoformat(timespec="seconds"),
        }

    def build_freetext_observation(self, text, entry_code, timestamp=None):
        text = (text or "").strip()
        if not text:
            raise ValueError("Text ist leer")
        entry_code = normalize_entry_code(entry_code)
        return {
            "resourceType": "Observation",
            "meta": {"profile": [PROFILE_FREITEXT]},
            "identifier": [
                {"system": IDENTIFIER_SYSTEM_KONTEXT, "value": self.context_id}
            ],
            "extension": [
                {"url": EXTENSION_FREITEXT_KUERZEL, "valueString": entry_code}
            ],
            "status": "final",
            "effectiveDateTime": timestamp or datetime.now().astimezone().isoformat(timespec="seconds"),
            "valueString": text,
        }

    def build_documentation_resources(self, documentation, output_mode, single_code, fields=None):
        fields = validate_fields(fields)
        document = normalize_documentation(documentation, fields)
        mode = normalize_output_mode(output_mode)
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")

        if mode == OUTPUT_MODE_SINGLE:
            combined = compose_single_block(document, fields)
            if not combined:
                raise ValueError("Alle aktiven Dokumentationsfelder sind leer")
            return [
                ("Einzelblock %s" % normalize_entry_code(single_code),
                 self.build_freetext_observation(combined, single_code, timestamp))
            ]

        resources = []
        for kind, text in nonempty_fields(document, fields):
            if kind in ("anamnese", "befund"):
                resource = self.build_observation(kind, text, timestamp)
            elif kind in ("therapie", "prozedere"):
                resource = self.build_procedure(kind, text, timestamp)
            else:
                resource = self.build_freetext_observation(
                    text, DOCUMENT_CODES[kind], timestamp)
            resources.append((DOCUMENT_LABELS[kind], resource))
        if not resources:
            raise ValueError("Alle aktiven Dokumentationsfelder sind leer")
        return resources

    def build_transaction_bundle(self, resources):
        entries = []
        for resource in resources:
            resource_type = resource.get("resourceType") if isinstance(resource, dict) else ""
            if resource_type not in ("Observation", "Procedure"):
                raise ValueError("Nicht unterstützte Transaction-Ressource: %s" % resource_type)
            entries.append({
                "request": {"method": "POST", "url": resource_type},
                "resource": resource,
            })
        if not entries:
            raise ValueError("Transaction Bundle enthält keine Einträge")
        return {"resourceType": "Bundle", "type": "transaction", "entry": entries}

    def write_documentation(self, documentation, output_mode, single_code, fields=None):
        labeled = self.build_documentation_resources(documentation, output_mode, single_code, fields)
        labels = [label for label, _resource in labeled]
        bundle = self.build_transaction_bundle([resource for _label, resource in labeled])
        status, response = self._request("POST", "", body=bundle)
        validate_transaction_response(response, labels)
        return status, response, labels


def validate_transaction_response(obj, labels):
    """Validate every entry of T2med's atomic transaction response."""
    if not isinstance(obj, dict) or obj.get("resourceType") != "Bundle":
        raise FhirError("FHIR-Transaction lieferte kein Bundle", body=obj)
    if obj.get("type") != "transaction-response":
        raise FhirError("FHIR-Antwort ist kein transaction-response Bundle", body=obj)

    entries = obj.get("entry", [])
    if not isinstance(entries, list):
        raise FhirError("FHIR-Transaction enthält keine gültige Ergebnisliste", body=obj)
    if len(entries) != len(labels):
        raise FhirError(
            "FHIR-Transaction meldet %d statt %d Ergebnissen" % (len(entries), len(labels)),
            body=obj,
        )

    failures = []
    rollback_confirmed = False
    malformed_status = False
    for index, label in enumerate(labels):
        entry = entries[index] if isinstance(entries[index], dict) else {}
        response = entry.get("response", {}) if isinstance(entry, dict) else {}
        if not isinstance(response, dict):
            response = {}
        raw_status = str(response.get("status", "") or "")
        try:
            status_code = int(raw_status.split()[0])
        except Exception:
            status_code = 0
        if not 100 <= status_code <= 599:
            malformed_status = True
        outcome_errors = operation_outcome_errors(response.get("outcome"))
        # T2med's integration guide explicitly guarantees whole-transaction
        # rollback for error/fatal entry outcomes. Other failures stay uncertain.
        if outcome_errors:
            rollback_confirmed = True
        if status_code < 200 or status_code >= 300 or outcome_errors:
            detail = "; ".join(outcome_errors) or raw_status or "Status fehlt"
            failures.append("%s: %s" % (label, detail))

    if failures:
        detail = " | ".join(failures)
        if rollback_confirmed and not malformed_status:
            message = "Nicht gespeichert: T2med hat die gesamte Transaktion zurückgerollt. " + detail
            if any('behandlungsort' in error.lower() and 'nicht gesetzt' in error.lower()
                   for error in failures):
                message += (" Bitte in T2med den Behandlungsort für den Aufruf prüfen. "
                            "Der Ort gehört zum T2med-Kontext; Record legt ihn nicht selbst fest.")
            raise FhirTransactionRejected(message, body=obj)
        raise FhirError("FHIR-Transaction nicht bestätigt; Schreibausgang in T2med prüfen: " + detail, body=obj)
    return True


def normalize_patient_result(obj):
    if not isinstance(obj, dict):
        return None
    if obj.get("resourceType") == "Patient":
        return obj
    if obj.get("resourceType") == "Bundle":
        entries = obj.get("entry", [])
        if not isinstance(entries, list) or not entries:
            return None
        total = obj.get("total")
        if "total" in obj and (type(total) is not int or total != 1):
            return None
        links = obj.get("link", [])
        if not isinstance(links, list) or any(
                not isinstance(link, dict) or link.get("relation") == "next" for link in links):
            return None
        patient = None
        for entry in entries:
            resource = entry.get("resource") if isinstance(entry, dict) else None
            if not isinstance(resource, dict) or resource.get("resourceType") != "Patient":
                return None
            if patient is not None and resource != patient:
                return None
            patient = resource
        return patient
    return None


def patient_summary(patient):
    names = patient.get("name", []) if isinstance(patient, dict) else []
    family = ""
    given = ""
    if names:
        name = names[0] if isinstance(names[0], dict) else {}
        family = str(name.get("family", "") or "")
        givens = name.get("given", []) or []
        if isinstance(givens, list):
            given = " ".join(str(x) for x in givens if x)
    return {
        "id": str(patient.get("id", "") or ""),
        "family": family,
        "given": given,
        "name": (
            (family + ", " + given).strip(", ")
            or "(Name nicht geliefert)"
        ),
        "birth_date": str(patient.get("birthDate", "") or ""),
        "gender": str(patient.get("gender", "") or ""),
    }


def display_birth_date(value):
    text = str(value or "").strip()
    try:
        return datetime.strptime(text, "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError:
        return text or "—"


def encounter_summary(encounter):
    def ref_from(value):
        if isinstance(value, dict):
            return str(value.get("reference", "") or "")
        return ""

    subject = ref_from(encounter.get("subject"))
    practitioner = ""
    for participant in encounter.get("participant", []) or []:
        if not isinstance(participant, dict):
            continue
        individual = ref_from(participant.get("individual"))
        if individual.startswith("Practitioner/"):
            practitioner = individual
            break

    service_provider = ref_from(encounter.get("serviceProvider"))
    episode = ""
    episodes = encounter.get("episodeOfCare", []) or []
    if episodes and isinstance(episodes[0], dict):
        episode = ref_from(episodes[0])

    return {
        "id": str(encounter.get("id", "") or ""),
        "patient_ref": subject,
        "practitioner_ref": practitioner,
        "organization_ref": service_provider,
        "episode_ref": episode,
    }


class SessionState(object):
    def __init__(self, link_data, client, key_source):
        self.link_data = link_data
        self.client = client
        self.key_source = key_source
        self.csrf = secrets.token_urlsafe(24)
        self.write_uncertain = False
        self.write_succeeded = False
        self.closing = False
        self.patient = None
        self.patient_error = ""
        self.patient_loading = False
        self.initial_work_started = False
        self.encounter = None
        self.message = ""
        self.error = ""
        self.active_fields = DEFAULT_DOCUMENT_FIELDS
        self.documentation = empty_documentation(self.active_fields)
        self.output_mode = DEFAULT_OUTPUT_MODE
        self.single_code = DEFAULT_SINGLE_CODE
        self.speech = None
        self.completed_event = threading.Event()
        self.document_revision = 0
        self.ui_process = None
        self.t2med_status = "checking"
        self.t2med_message = "T2med-Verbindung wird geprüft."
        self.t2med_host = (
            urllib.parse.urlparse(link_data.get("fhir_base_url", "")).hostname
            or "unbekannt"
        )
        self.lock = threading.RLock()
        self.last_activity = time.time()

    def touch(self):
        self.last_activity = time.time()


def start_patient_load(state):
    """Read context in the background so microphone controls stay responsive."""
    with state.lock:
        if state.closing or state.patient_loading:
            return
        state.patient_loading = True
        # A stale successful lookup must never authorize a write after a failed reload.
        state.patient = None
        state.patient_error = ""
        state.t2med_status = "checking"
        state.t2med_message = "T2med-Verbindung wird geprüft."

    def load_patient():
        try:
            patient = state.client.get_patient_by_context()
            with state.lock:
                if not state.closing:
                    state.patient = patient
                    state.t2med_status = "ok"
                    state.t2med_message = "T2med-FHIR erreichbar."
            safe_log("Patient load OK")
        except Exception as exc:
            with state.lock:
                if not state.closing:
                    state.patient_error = str(exc)
                    state.t2med_status = "error"
                    state.t2med_message = "T2med-FHIR nicht erreichbar."
            safe_log("Patient load failed", error=type(exc).__name__, status=getattr(exc, "status", ""))
        finally:
            with state.lock:
                state.patient_loading = False

    worker = threading.Thread(target=load_patient, name="Kienzledoku-Patient", daemon=True)
    worker.start()
    return worker


def start_initial_work(state):
    """Start each fresh recording once, independently of the FHIR read latency."""
    with state.lock:
        if state.initial_work_started or state.closing:
            return
        state.initial_work_started = True
        try:
            state.speech.start()
            safe_log("Automatic speech recording started")
        except Exception as exc:
            state.error = "Spracherkennung konnte nicht automatisch starten: %s" % exc
            safe_log("Automatic speech recording failed", error=type(exc).__name__)
    return start_patient_load(state)


WINDOWS_STATUS_LAYOUT = True  # Common natural pills and adaptive no-wrap header on every platform.

# Use the Mac/Linux pill styling on Windows too. Reclaim the byline's space
# before shortening any status text; the service row must never wrap.
WINDOWS_STATUS_CSS = """
.topbar { align-items:center; flex-direction:row; gap:18px; }
.topbar h1 { flex:0 0 auto; }
.topbar.with-temperatures h1 { flex:0 1 auto; min-width:100px; }
.topbar.with-temperatures .brand-link { overflow:hidden; text-overflow:ellipsis; }
.topbar.measure-status h1 { flex-shrink:0; }
.topbar.compact-brand h1 { gap:0; }
.topbar.compact-brand .brand-byline { display:none; }
.server-row { flex:0 1 auto; min-width:0; flex-wrap:nowrap; justify-content:flex-end; }
.server-badge { min-width:0; }
#gpu-temperatures { display:contents; }
.gpu-temperature { flex:0 0 auto; font-variant-numeric:tabular-nums; }
.server-dot, .server-label { flex-shrink:0; }
.server-name { display:flex; gap:4px; min-width:3.5em; overflow:hidden; }
.server-host { min-width:0; overflow:hidden; text-overflow:ellipsis; }
.server-state { min-width:1ch; overflow:hidden; text-overflow:ellipsis; }
.topbar.measure-status .server-row, .topbar.measure-status .server-badge,
.topbar.measure-status .server-name, .topbar.measure-status .server-host,
.topbar.measure-status .server-state { flex-shrink:0; }
"""

WINDOWS_STATUS_JS = """
  const statusHeader = document.querySelector('.topbar');
  function fitStatusHeader() {
    // Measure natural pill widths, without painting the temporary layout.
    statusHeader.classList.remove('compact-brand');
    statusHeader.classList.add('measure-status');
    const title = statusHeader.querySelector('h1');
    const row = statusHeader.querySelector('.server-row');
    const gap = parseFloat(getComputedStyle(statusHeader).columnGap) || 0;
    const needed = title.getBoundingClientRect().width + row.scrollWidth + gap;
    statusHeader.classList.toggle('compact-brand', needed > statusHeader.clientWidth);
    statusHeader.classList.remove('measure-status');
  }
  new ResizeObserver(fitStatusHeader).observe(statusHeader);
  document.fonts.ready.then(fitStatusHeader);
  fitStatusHeader();
"""

CSS = """
* { box-sizing:border-box; }
html, body { min-height:100%; }
body { font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin:0; background:#f2f3f5; color:#1d1d1f; }
main { max-width:1440px; margin:0 auto; padding:12px 18px 42px; }
.primary-screen { min-height:calc(100vh - 24px); display:flex; flex-direction:column; gap:10px; }
.record-heading { display:flex; gap:18px; align-items:center; } .logo-slot { width:100px; height:100px; display:flex; align-items:center; justify-content:center; flex-shrink:0; } .logo-slot>img { width:66%; height:66%; object-fit:contain; } .record-heading>div:not(.logo-slot) { flex:1; min-width:0; }
.topbar { display:flex; align-items:center; justify-content:space-between; gap:18px; min-height:38px; }
h1 { display:flex; align-items:baseline; gap:9px; margin:0; white-space:nowrap; } h2 { font-size:17px; margin:0; }
.brand-link { color:#1d1d1f; font-size:22px; font-weight:760; letter-spacing:-.025em; text-decoration:none; }
.brand-link:hover { color:#0071e3; }
.brand-byline { color:#77777c; font-size:13px; font-weight:500; letter-spacing:0; }
.server-row { display:flex; justify-content:flex-end; gap:8px; flex-wrap:wrap; }
.server-badge { display:inline-flex; align-items:center; gap:6px; padding:5px 9px; border:1px solid #d8d8dc; background:white; border-radius:999px; font-size:12px; white-space:nowrap; }
.server-dot { width:8px; height:8px; border-radius:50%; background:#8e8e93; }
.server-badge.ok .server-dot { background:#248a3d; } .server-badge.error .server-dot { background:#d70015; }
.server-badge.checking .server-dot, .server-badge.loading .server-dot, .server-badge.standby .server-dot { background:#ff9f0a; }
.server-badge.ready .server-dot, .server-badge.busy .server-dot { background:#248a3d; }
.patient-row { display:flex; align-items:baseline; justify-content:space-between; gap:24px; background:white; border-radius:14px; padding:15px 20px; box-shadow:0 1px 5px rgba(0,0,0,.08); }
.patient-name { font-size:30px; line-height:1.1; font-weight:750; letter-spacing:-.02em; }
.patient-birth { color:#4c4c50; font-size:17px; white-space:nowrap; }
.notice { padding:8px 12px; border-radius:9px; font-size:13px; }
.ok { background:#e9f7ef; } .err { background:#fdecec; white-space:pre-wrap; } .warn { background:#fff5d6; }
.workspace { display:flex; flex-direction:column; flex:1; min-height:560px; background:white; border-radius:14px; padding:14px; box-shadow:0 1px 7px rgba(0,0,0,.09); overflow:hidden; }
.recording-workspace { display:flex; flex-direction:column; gap:10px; }
.workspace-head { display:flex; align-items:center; justify-content:space-between; gap:16px; min-height:38px; }
.status-line { display:flex; align-items:center; gap:7px; min-width:0; }
.recording-dot { flex:0 0 auto; width:11px; height:11px; border-radius:50%; background:#d70015; animation:pulse 1.2s infinite; }
@keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:.28; } }
.small { color:#6e6e73; font-size:12px; }
.work-grid { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:12px; flex:1; width:100%; min-height:0; }
.panel { display:flex; flex-direction:column; min-width:0; min-height:0; border:1px solid #dedee3; border-radius:11px; padding:12px; background:#fff; }
.panel-head { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:8px; }
.panel form { display:flex; flex-direction:column; flex:1; min-height:0; }
textarea { width:100%; padding:9px 10px; border:1px solid #c7c7cc; border-radius:8px; font:14px/1.35 -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; resize:none; color:inherit; background:white; }
.live-text, .diarization { flex:1; min-height:0; background:#fafafc; }
.documentation-grid { display:grid; grid-auto-rows:minmax(68px,1fr); gap:6px; flex:1; min-height:0; }
.doc-field { display:flex; flex-direction:column; min-height:0; }
label.block { display:block; margin:0 0 3px; font-size:11px; font-weight:750; letter-spacing:.045em; color:#55555a; }
.doc-field textarea { flex:1; min-height:0; }
select, input, button { font:inherit; padding:8px 11px; border-radius:8px; }
select, input { border:1px solid #c7c7cc; background:white; color:inherit; }
button { border:0; background:#0071e3; color:white; cursor:pointer; font-weight:600; }
button.secondary { background:#6e6e73; } button.subtle { background:#e8e8ed; color:#1d1d1f; }
button:disabled { cursor:default; opacity:.45; }
.button-row { display:flex; align-items:center; justify-content:space-between; gap:8px; margin-top:9px; flex-wrap:nowrap; }
.quality-control { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin:8px 0; }
.quality-control label { font-size:12px; font-weight:600; }
.button-group { display:flex; align-items:center; gap:8px; flex-wrap:nowrap; }
.button-group button { white-space:nowrap; }
.device-select { min-width:0; max-width:175px; }
.output-options { margin-top:7px; border-top:1px solid #ececf0; padding-top:6px; }
.output-options summary { cursor:pointer; color:#6e6e73; font-size:12px; }
.mode-grid { display:grid; grid-template-columns:1fr minmax(150px,220px); gap:8px; margin-top:7px; }
.mode-grid label { display:block; color:#6e6e73; font-size:11px; margin-bottom:3px; }
.mode-grid select, .mode-grid input { width:100%; }
.technical { margin-top:72px; background:white; border-radius:14px; padding:16px 18px; box-shadow:0 1px 6px rgba(0,0,0,.07); }
.technical summary { cursor:pointer; font-weight:700; }
.technical-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:16px; margin-top:14px; }
.prompt-tooltip summary { cursor:pointer; font-weight:600; } .prompt-tooltip pre { white-space:pre-wrap; max-height:260px; overflow:auto; padding:10px; background:#f5f5f7; border-radius:8px; }
dt { color:#6e6e73; font-size:11px; margin-top:7px; } dd { margin:2px 0 0; font-weight:600; overflow-wrap:anywhere; }
code { font-size:11px; }
@media (max-width:900px) {
  .topbar, .patient-row { align-items:flex-start; flex-direction:column; gap:7px; }
  .server-row { justify-content:flex-start; }
  .patient-birth { font-size:15px; }
  .work-grid { grid-template-columns:1fr; height:auto; }
  .workspace { overflow:visible; }
  .panel { min-height:520px; }
  .technical-grid { grid-template-columns:1fr; }
}
"""

CSS += """
.audio-settings{margin-top:72px;background:white;border-radius:14px;padding:16px 18px;box-shadow:0 1px 6px rgba(0,0,0,.07)}
.audio-settings summary{cursor:pointer;font-weight:700}
.audio-settings + .technical{margin-top:12px}
.audio-controls{display:flex;flex-wrap:wrap;align-items:center;gap:10px 18px;background:#fff;padding:12px 16px;border-radius:14px;margin:10px 0;border:1px solid #d9e1ea}
.audio-controls label{display:inline-flex;align-items:center;gap:8px;margin:0}
.audio-controls input[type=checkbox]{width:18px;height:18px;margin:0;accent-color:#326cae}
.level-control{flex:1 1 360px;min-width:0;max-width:640px}
.level-labels{display:flex;justify-content:space-between;gap:8px 18px;flex-wrap:wrap;font-size:13px}
.level-meter{position:relative;height:36px;margin-top:4px}
.input-meter{position:absolute;inset:10px 0;height:16px;border-radius:8px;background:#e9edf2;overflow:hidden;box-shadow:inset 0 0 0 1px #d3dbe3}
.input-meter-fill{display:block;width:var(--level);height:100%;background:#2d9954;transition:width .1s linear}
.level-meter input[type=range]{position:absolute;top:0;left:calc(16.666667% - 10px);width:calc(62.5% + 20px);height:36px;margin:0;padding:0;border:0;border-radius:0;background:transparent;appearance:none;-webkit-appearance:none;cursor:ew-resize}
.level-meter input[type=range]::-webkit-slider-runnable-track{height:36px;border:0;background:transparent}
.level-meter input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;box-sizing:border-box;width:20px;height:32px;margin-top:2px;border:2px solid #245f9c;border-radius:6px;background:transparent}
.level-meter input[type=range]::-moz-range-track{height:36px;border:0;background:transparent}
.level-meter input[type=range]::-moz-range-progress{background:transparent}
.level-meter input[type=range]::-moz-range-thumb{box-sizing:border-box;width:20px;height:32px;border:2px solid #245f9c;border-radius:6px;background:transparent}
.level-meter input[type=range]:focus-visible{outline:2px solid #245f9c;outline-offset:3px;border-radius:6px}
.level-scale{position:relative;height:14px;color:#6e6e73;font-size:11px;font-variant-numeric:tabular-nums}
.level-scale span{position:absolute;transform:translateX(-50%)}
.level-scale span:first-child{left:0;transform:none}.level-scale span:nth-child(2){left:25%}.level-scale span:nth-child(3){left:50%}.level-scale span:nth-child(4){left:75%}.level-scale span:last-child{right:0;transform:none}
.audio-controls output{font-variant-numeric:tabular-nums;white-space:nowrap}
#audio-controls-hint{flex-basis:100%}
"""


def _server_badge(element_id, label, host, status, message):
    normalized = status if status in ("ok", "error", "checking", "loading", "standby", "ready", "busy", "disabled") else "checking"
    status_text = {"ok": "OK", "error": "FEHLER", "checking": "PRÜFUNG",
                   "loading": "WIRD GELADEN", "standby": "STANDBY", "ready": "BEREIT",
                   "busy": "AKTIV", "disabled": "DEAKTIVIERT"}[normalized]
    markup = (
        '<span id="{element_id}" class="server-badge {status}" data-label="{label}" title="{message}">'
        '<span class="server-dot"></span><span class="server-name" title="{label} {host}">'
        '<span class="server-label">{label}</span><span class="server-host">{host}</span></span>'
        '<strong class="server-state" title="{status_text}">{status_text}</strong></span>'
    ) if WINDOWS_STATUS_LAYOUT else (
        '<span id="{element_id}" class="server-badge {status}" title="{message}">'
        '<span class="server-dot"></span><span>{label} {host}</span> '
        '<strong class="server-state">{status_text}</strong></span>'
    )
    return markup.format(
        element_id=html.escape(element_id),
        status=normalized,
        message=html.escape(message or ""),
        label=html.escape(label),
        host=html.escape(host or "unbekannt"),
        status_text=status_text,
    )


def page_html(state):
    patient = patient_summary(state.patient) if state.patient else None
    encounter = encounter_summary(state.encounter) if state.encounter else None
    speech = state.speech.snapshot() if state.speech is not None else {
        "status": STATUS_ERROR,
        "message": "Spracherkennung ist nicht initialisiert.",
        "elapsed_seconds": 0,
        "active": False,
        "live_transcript": "",
        "diarized_text": "",
        "speaker_labels": False,
        "can_regenerate": False,
        "audio_devices": [],
        "selected_device": "",
        "selected_device_name": "System-Standardgerät",
        "service_status": "error",
        "service_message": "Kienzlefon-Dienste nicht initialisiert.",
        "service_host": "unbekannt",
        "config_source": "nicht initialisiert",
        "services": {
            "asr": {"host": "unbekannt", "url": "—", "status": "error", "message": "ASR nicht initialisiert."},
            "diarization": {"host": "unbekannt", "url": "—", "status": "error", "message": "Diarisierung nicht initialisiert."},
            "llm": {"host": "unbekannt", "url": "—", "status": "error", "message": "LLM nicht initialisiert."},
        },
    }
    services = speech.get("services") or {}
    asr_service = services.get("asr") or {}
    diarization_service = services.get("diarization") or {}
    llm_service = services.get("llm") or {}

    quality_control = ""
    if speech.get('commander_enabled'):
        profiles = speech.get('quality_profiles') or []
        selected_quality = speech.get('selected_quality') or 'auto'
        default_profile = next((profile for profile in profiles if profile.get('default')), profiles[0] if profiles else None)
        default_label = default_profile['label'] if default_profile else 'wird geprüft'
        if len(profiles) == 1:
            quality_control = ('<div class="quality-control" id="processing-quality-control"><strong>Verarbeitung: %s</strong>'
                               '<input type="hidden" name="quality" value="%s"></div>' %
                               (html.escape(profiles[0]['label']), html.escape(profiles[0]['id'], quote=True)))
        else:
            options = ['<option value="auto"%s>Standard (%s)</option>' % (
                ' selected' if selected_quality == 'auto' else '', html.escape(default_label))]
            for profile in profiles:
                options.append('<option value="%s"%s>%s</option>' % (
                    html.escape(profile['id'], quote=True),
                    ' selected' if selected_quality == profile['id'] else '',
                    html.escape(profile['label'])))
            quality_control = (
                '<div class="quality-control" id="processing-quality-control"><label for="processing-quality">Verarbeitung</label>'
                '<select id="processing-quality" name="quality" aria-label="Verarbeitungsqualität"%s>%s</select>'
                '<span class="small">Wird erst nach dem Ende der Aufnahme angewendet.</span></div>'
            ) % (' disabled' if not profiles else '', ''.join(options))

    status_notices = []
    if state.error:
        status_notices.append(
            '<div class="notice err"><strong>Fehler:</strong> %s</div>'
            % html.escape(state.error)
        )
    elif state.message:
        status_notices.append(
            '<div class="notice ok">%s</div>' % html.escape(state.message)
        )
    if state.write_uncertain:
        status_notices.append('<div class="notice warn">Schreibausgang unklar. Vor jeder Wiederholung in T2med prüfen.<form method="post" action="/action"><input type="hidden" name="csrf" value="%s"><button name="do" value="write_resolved">In T2med geprüft: Es wurde NICHT übernommen</button></form></div>' % html.escape(state.csrf))
    if speech.get('commander_notice'):
        status_notices.append('<div class="notice warn" role="status">%s</div>' % html.escape(speech['commander_notice']))
    status_notices = "".join(status_notices)

    patient_name = html.escape(patient["name"] if patient else "Patient wird geladen …")
    birth_date = display_birth_date(patient["birth_date"] if patient else "")
    patient_id = html.escape(patient["id"] if patient else "—")
    patient_gender = html.escape(patient["gender"] if patient else "—")
    context_masked = html.escape(mask(state.link_data.get("context_id", "")))
    fhir_base = html.escape(state.link_data.get("fhir_base_url", ""))

    selected_device = str(speech.get("selected_device") or "")
    device_options = [
        '<option value=""%s>Standardmikrofon</option>'
        % (" selected" if not selected_device else "")
    ]
    for device in speech.get("audio_devices") or []:
        device_index = str(device.get("index"))
        device_options.append(
            '<option value="{value}"{selected}>{label}</option>'.format(
                value=html.escape(device_index),
                selected=" selected" if device_index == selected_device else "",
                label=html.escape(str(device.get("name") or device_index)),
            )
        )
    device_options = "".join(device_options)

    requested_label = speech.get('requested_quality_label') or ''
    used_label = speech.get('used_quality_label') or ''
    if requested_label and used_label:
        quality_result = 'Angefordert: %s · Erstellt mit: %s' % (requested_label, used_label)
    elif used_label:
        quality_result = 'Erstellt mit: ' + used_label
    else:
        quality_result = 'vollständig editierbar'

    elapsed = int(speech.get("elapsed_seconds") or 0)
    elapsed_text = "%02d:%02d" % (elapsed // 60, elapsed % 60) if elapsed else ""
    recording_dot = (
        '<span class="recording-dot" aria-hidden="true"></span>'
        if speech["status"] == STATUS_RECORDING else ""
    )

    if speech["status"] in ACTIVE_STATUSES:
        if speech["status"] == STATUS_RECORDING:
            action = (
                '<form method="post" action="/action">'
                '<input type="hidden" name="csrf" value="{csrf}">'
                '{quality_control}'
                '<button type="submit" name="do" value="speech_stop">Aufnahme stoppen</button>'
                '</form>'
            ).format(csrf=html.escape(state.csrf), quality_control=quality_control)
            workspace_title = "Aufnahme läuft"
        else:
            action = '<span class="small">Bitte einen Moment warten …</span>'
            workspace_title = "Gespräch wird verarbeitet"
        workspace = """
        <section class="workspace recording-workspace">
          <div class="workspace-head">
            <div>
              <div class="status-line">{recording_dot}<h2>{workspace_title}</h2>
                <span id="speech-elapsed" class="small">{elapsed_text}</span></div>
              <div id="speech-message" class="small">{speech_message}</div>
            </div>
            {action}
          </div>
          <div class="small">Mikrofon: <span id="speech-device">{device}</span></div>
          <textarea id="live-transcript" class="live-text" readonly aria-label="Live-Transkript">{live_transcript}</textarea>
        </section>
        """.format(
            recording_dot=recording_dot,
            workspace_title=workspace_title,
            elapsed_text=elapsed_text,
            speech_message=html.escape(speech.get("message") or ""),
            action=action,
            device=html.escape(speech.get("selected_device_name") or "System-Standardgerät"),
            live_transcript=html.escape(speech.get("live_transcript") or ""),
        )
    else:
        documentation_fields = []
        for field in state.active_fields:
            documentation_fields.append(
                '<div class="doc-field"><label class="block" for="{field}">{label}</label>'
                '<textarea id="{field}" name="{field}" autocomplete="off">{value}</textarea></div>'.format(
                    field=field,
                    label=html.escape(DOCUMENT_LABELS[field].upper()),
                    value=html.escape(state.documentation.get(field, "")),
                )
            )
        documentation_fields = "".join(documentation_fields)
        regenerate_disabled = "" if speech.get("can_regenerate") else " disabled"
        continue_label = (
            "Aufnahme fortsetzen" if (speech.get("diarized_text") or "").strip()
            else "Aufnahme starten"
        )
        structured_selected = (
            " selected" if state.output_mode == OUTPUT_MODE_STRUCTURED else ""
        )
        single_selected = (
            " selected" if state.output_mode == OUTPUT_MODE_SINGLE else ""
        )
        workspace = """
        <section class="workspace">
          <div class="work-grid">
            <div class="panel">
              <div class="panel-head"><h2>Diarisiertes Gespräch</h2>
                <span id="speech-message" class="small">{speech_message}</span></div>
              <form method="post" action="/action">
                <input type="hidden" name="csrf" value="{csrf}">
                <textarea id="diarized-text" class="diarization" name="diarized_text" aria-label="Diarisiertes Gespräch">{diarized_text}</textarea>
                {quality_control}
                <div class="button-row">
                  <select id="audio-device" class="device-select" name="audio_device" aria-label="Mikrofon">{device_options}</select>
                  <div class="button-group">
                    <button type="submit" class="secondary" name="do" value="speech_start">{continue_label}</button>
                    <button id="regenerate-button" type="submit" name="do" value="llm_regenerate"{regenerate_disabled}>Neu zusammenfassen</button>
                  </div>
                </div>
              </form>
            </div>
            <div class="panel">
              <div class="panel-head"><h2>LLM-Dokumentation</h2><span class="small">{quality_result}</span></div>
              <form method="post" action="/action">
                <input type="hidden" name="csrf" value="{csrf}">
                <input type="hidden" name="do" value="write">
                <div class="documentation-grid">{documentation_fields}</div>
                <details class="output-options">
                  <summary>T2med-Ausgabe konfigurieren</summary>
                  <div class="mode-grid">
                    <div><label for="output_mode">Ausgabeform</label><select id="output_mode" name="output_mode">
                      <option value="structured"{structured_selected}>Strukturierte Einträge</option>
                      <option value="single"{single_selected}>Ein gemeinsamer Freitext-Eintrag</option>
                    </select></div>
                    <div><label for="single_code">Kürzel des Einzelblocks</label><input id="single_code" name="single_code" maxlength="20" value="{single_code}" list="single-code-options" autocomplete="off">
                    <datalist id="single-code-options"><option value="A"><option value="KI"><option value="AI"></datalist></div>
                  </div>
                </details>
                <div class="button-row"><span class="small">Die Übernahme schreibt direkt in T2med.</span>
                  <button type="submit">In T2med übernehmen</button></div>
              </form>
            </div>
          </div>
        </section>
        """.format(
            speech_message=html.escape(speech.get("message") or ""),
            csrf=html.escape(state.csrf),
            diarized_text=html.escape(speech.get("diarized_text") or ""),
            device_options=device_options,
            quality_control=quality_control,
            quality_result=html.escape(quality_result),
            continue_label=continue_label,
            regenerate_disabled=regenerate_disabled,
            documentation_fields=documentation_fields,
            structured_selected=structured_selected,
            single_selected=single_selected,
            single_code=html.escape(state.single_code),
        )

    audio_controls = """
    <details class="audio-settings" id="audio-settings">
    <summary>Aufnahme-Einstellungen</summary>
    <div class="audio-controls" aria-label="Aufnahme-Einstellungen">
      <label class="vad-switch"><input id="vad-enabled" type="checkbox" {checked}> Sprache erkennen (VAD)</label>
      <div class="level-control">
        <div class="level-labels">
          <label for="silence-threshold">Stilleschwelle <output id="threshold-value">{threshold} dBFS</output></label>
          <span>Eingangspegel <output id="input-dbfs">{level} dBFS</output></span>
        </div>
        <div class="level-meter">
          <div id="input-meter" class="input-meter" role="meter" aria-label="Eingangspegel" aria-valuemin="-96" aria-valuemax="0" aria-valuenow="{level}" aria-valuetext="{level} dBFS" style="--level:{level_percent}%"><span class="input-meter-fill"></span></div>
          <input id="silence-threshold" type="range" min="-80" max="-20" step="1" value="{threshold}" aria-valuetext="{threshold} dBFS" aria-describedby="audio-controls-hint">
        </div>
        <div class="level-scale" aria-hidden="true"><span>−96</span><span>−72</span><span>−48</span><span>−24</span><span>0 dBFS</span></div>
      </div>
      <div id="audio-controls-hint" class="small">Griff im Pegelbalken verschieben, um die Stilleschwelle einzustellen. Unterhalb der Schwelle wird stummgeschaltet; Pausen bleiben erhalten. Für diesen Client gespeichert. Änderungen gelten für kommende Verarbeitung.</div>
      <div id="audio-controls-message" class="small" role="status" aria-live="polite"></div>
    </div></details>""".format(checked='checked' if speech.get('vad_enabled', True) else '',
                  threshold=int(speech.get('silence_threshold_dbfs', -50)), level=speech.get('audio_dbfs', -96),
                  level_percent=max(0, min(100, (float(speech.get('audio_dbfs', -96)) + 96) / 96 * 100)))
    if speech['status'] != STATUS_RECORDING:
        audio_controls = ''

    if encounter:
        encounter_details = """
        <dl><dt>FHIR-Encounter-ID</dt><dd><code>{eid}</code></dd>
        <dt>Patientenreferenz</dt><dd><code>{patient_ref}</code></dd>
        <dt>Arztrolle</dt><dd><code>{practitioner}</code></dd>
        <dt>Organisation</dt><dd><code>{organization}</code></dd>
        <dt>Episode</dt><dd><code>{episode}</code></dd></dl>
        """.format(
            eid=html.escape(encounter["id"] or "—"),
            patient_ref=html.escape(encounter["patient_ref"] or "—"),
            practitioner=html.escape(encounter["practitioner_ref"] or "—"),
            organization=html.escape(encounter["organization_ref"] or "—"),
            episode=html.escape(encounter["episode_ref"] or "—"),
        )
    else:
        encounter_details = (
            '<p class="small">Nicht geladen; für die Dokumentationsübernahme nicht erforderlich.</p>'
        )

    technical = """
    <details class="technical">
      <summary>Technische Informationen</summary>
      <div class="technical-grid">
        <section><h2>Verbindung</h2><dl>
          <dt>FHIR-Basis</dt><dd><code>{base}</code></dd>
          <dt>ASR</dt><dd><code>{asr_url}</code></dd>
          <dt>Diarisierung</dt><dd><code>{diarization_url}</code></dd>
          <dt>LLM</dt><dd><code>{llm_url}</code></dd>
          <dt>Konfiguration</dt><dd><code>{config_source}</code></dd>
          <dt>OAuth</dt><dd>{oauth}</dd>
          <dt>API-Schlüssel</dt><dd>{key_source}</dd>
        </dl></section>
        <section><h2>T2med-Kontext</h2><dl>
          <dt>Kontext-ID</dt><dd><code>{context}</code></dd>
          <dt>Patienten-ID</dt><dd><code id="patient-id">{patient_id}</code></dd>
          <dt>Geschlecht (FHIR)</dt><dd id="patient-gender">{gender}</dd>
        </dl><form method="post" action="/action"><input type="hidden" name="csrf" value="{csrf}">
          <button class="subtle" type="submit" name="do" value="patient">Patient neu laden</button></form></section>
        <section><h2>Behandlungsfall (FHIR Encounter)</h2>{encounter_details}
          <form method="post" action="/action"><input type="hidden" name="csrf" value="{csrf}">
          <button class="subtle" type="submit" name="do" value="encounter">Behandlungsfall laden</button></form></section>
      </div>
      <details class="prompt-tooltip"><summary title="{active_prompt}&#10;&#10;Dieser Prompt kann im Installer angepasst werden.">Aktiver Dokumentations-Prompt</summary>
        <pre>{active_prompt}</pre><p class="small">Dieser Prompt kann im Installer angepasst werden.</p>
      </details>
      <p class="small">OAuth-Token wird nur im Arbeitsspeicher gehalten. Die Zertifikatsprüfung folgt den T2med-Einstellungen.</p>
    </details>
    """.format(
        base=fhir_base,
        asr_url=html.escape(asr_service.get("url") or "—"),
        diarization_url=html.escape(diarization_service.get("url") or "—"),
        llm_url=html.escape(llm_service.get("url") or "—"),
        config_source=html.escape(speech.get("config_source") or "—"),
        oauth="vorhanden" if state.link_data.get("oauth_token") else "leer",
        key_source=html.escape(state.key_source),
        context=context_masked,
        patient_id=patient_id,
        gender=patient_gender,
        csrf=html.escape(state.csrf),
        encounter_details=encounter_details,
        active_prompt=html.escape(speech.get('active_prompt') or 'Für diese Legacy-Konfiguration wird kein Prompttext bereitgestellt.'),
    )

    t2med_badge = _server_badge(
        "t2med-server", "T2med", state.t2med_host, state.t2med_status,
        state.t2med_message,
    )
    asr_badge = _server_badge(
        "asr-server", "ASR", asr_service.get("host") or "unbekannt",
        asr_service.get("status") or "checking",
        asr_service.get("message") or "",
    )
    diarization_badge = _server_badge(
        "diarization-server", "Diar.",
        diarization_service.get("host") or "unbekannt",
        diarization_service.get("status") or "checking",
        diarization_service.get("message") or "",
    )
    llm_badge = _server_badge(
        "llm-server", "LLM", llm_service.get("host") or "unbekannt",
        llm_service.get("status") or "checking",
        llm_service.get("message") or "",
    )

    return """<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>kienzledoku record {version}</title><style>{css}</style></head>
<body><main>
  <div class="primary-screen">
    <div class="record-heading"><div class="logo-slot"><img src="/logo.svg" alt="kienzledoku record"></div><div><header class="topbar"><h1><a class="brand-link" href="https://kienzledoku.de" rel="noopener noreferrer">kienzledoku record</a>
      <span class="brand-byline">v{version} · von Dr. Thomas Kienzle</span></h1>
      <div class="server-row">{t2med_badge}{asr_badge}{diarization_badge}{llm_badge}<span id="gpu-temperatures">{temperature_badges}</span></div></header>
    <section class="patient-row"><div class="patient-name" id="patient-name">{patient_name}</div>
      <div class="patient-birth">Geburtsdatum: <strong id="patient-birth">{birth_date}</strong></div></section></div></div>
    <div class="notice err" id="patient-error" {patient_error_hidden}>{patient_error}</div>
    {status_notices}
    {workspace}
    <form method="post" action="/action"><input type="hidden" name="csrf" value="{csrf}"><button class="subtle" name="do" value="discard" onclick="return confirm('Aufnahme und Entwurf wirklich verwerfen? Unklare Übernahme zuvor in T2med prüfen.')">Fenster schließen und verwerfen</button></form>
  </div>
  {audio_controls}
  {technical}
</main>
<script>
(function() {{
  const initialStatus = {initial_status};
  const csrf = {csrf_json};
  const vadToggle = document.getElementById('vad-enabled');
  const thresholdSlider = document.getElementById('silence-threshold');
  const controlsMessage = document.getElementById('audio-controls-message');
  let controlsPending = false, controlsSending = false, controlsTimer;
  let acknowledgedControls = vadToggle ? {{vad_enabled:vadToggle.checked, silence_threshold_dbfs:Number(thresholdSlider.value)}} : null;
  async function saveAudioControls() {{
    if (controlsSending) return;
    controlsSending = true;
    try {{
      while (controlsPending) {{
        controlsPending = false;
        const body = new URLSearchParams({{csrf, do:'speech_audio_controls',
          vad_enabled:vadToggle.checked ? 'true':'false', threshold:thresholdSlider.value}});
        const response = await fetch('/action', {{method:'POST', body}});
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Audio-Einstellungen konnten nicht gespeichert werden.');
        acknowledgedControls = result;
        controlsMessage.textContent = 'Für diesen Client gespeichert. Gilt ab dem nächsten Audioblock.';
      }}
    }} catch(error) {{
      controlsPending = false;
      vadToggle.checked = acknowledgedControls.vad_enabled;
      thresholdSlider.value = acknowledgedControls.silence_threshold_dbfs;
      thresholdSlider.setAttribute('aria-valuetext', thresholdSlider.value + ' dBFS');
      document.getElementById('threshold-value').textContent = thresholdSlider.value + ' dBFS';
      controlsMessage.textContent = error.message;
    }} finally {{ controlsSending = false; }}
  }}
  function audioControlsChanged() {{
    document.getElementById('threshold-value').textContent = thresholdSlider.value + ' dBFS';
    thresholdSlider.setAttribute('aria-valuetext', thresholdSlider.value + ' dBFS');
    controlsMessage.textContent = 'Wird gespeichert …';
    controlsPending = true;
    clearTimeout(controlsTimer);
    controlsTimer = setTimeout(saveAudioControls, 100);
  }}
  if (vadToggle && thresholdSlider) {{
    vadToggle.addEventListener('change', audioControlsChanged);
    thresholdSlider.addEventListener('input', audioControlsChanged);
    thresholdSlider.addEventListener('change', audioControlsChanged);
  }}
  let draftTimer;
  async function saveDraft() {{
    const body = new URLSearchParams({{csrf:csrf, do:'draft'}});
    for (const name of {field_names}) {{
      const field = document.querySelector('[name="'+name+'"]');
      if (field) body.set(name, field.value);
    }}
    await fetch('/action', {{method:'POST', body}});
  }}
  document.addEventListener('input', () => {{clearTimeout(draftTimer); draftTimer=setTimeout(()=>saveDraft().catch(()=>{{}}),400);}});
  document.addEventListener('submit', async event => {{
    const action = event.submitter && event.submitter.value;
    if (action !== 'discard') return;
    event.preventDefault(); clearTimeout(draftTimer);
    const response = await fetch('/action', {{method:'POST',body:new URLSearchParams({{csrf,do:action}})}});
    if (response.ok) {{ if(window.chrome && window.chrome.webview) window.chrome.webview.postMessage('record-close'); else window.close(); }}
  }});
  async function closeRequested() {{
    const response = await fetch('/action', {{method:'POST', body:new URLSearchParams({{csrf, do:'discard'}})}});
    if(response.ok) {{ if(window.chrome && window.chrome.webview) window.chrome.webview.postMessage('record-close'); else window.close(); }}
  }}
  window.addEventListener('kienzledoku-close-request', closeRequested);
  window.addEventListener('kienzledoku-audio-interrupted', () => fetch('/action', {{method:'POST', body:new URLSearchParams({{csrf, do:'speech_stop'}})}}));
  const initialRevision = {initial_revision};
  {status_layout_script}
  function setServer(id, status, host) {{
    const badge = document.getElementById(id);
    if (!badge) return;
    const normalized = ['ok','error','checking','loading','standby','ready','busy','disabled'].includes(status) ? status : 'checking';
    badge.className = 'server-badge ' + normalized;
    const state = badge.querySelector('.server-state');
    if (state) {{
      state.textContent = ({{ok:'OK',error:'FEHLER',checking:'PRÜFUNG',loading:'WIRD GELADEN',standby:'STANDBY',ready:'BEREIT',busy:'AKTIV',disabled:'DEAKTIVIERT'}})[normalized];
      state.title = state.textContent;
    }}
    const name = badge.querySelector('.server-name');
    if (name && host) {{
      name.querySelector('.server-host').textContent = host;
      name.title = badge.dataset.label + ' ' + host;
    }}
  }}
  async function updateStatus() {{
    try {{
      const response = await fetch('/status', {{cache:'no-store'}});
      if (!response.ok) return;
      const data = await response.json();
      if (data.status !== initialStatus || Number(data.document_revision || 0) !== initialRevision) {{
        window.location.reload(); return;
      }}
      const message = document.getElementById('speech-message');
      if (message) message.textContent = data.message || '';
      const elapsed = document.getElementById('speech-elapsed');
      const seconds = Number(data.elapsed_seconds || 0);
      if (elapsed) elapsed.textContent = seconds ? String(Math.floor(seconds/60)).padStart(2,'0') + ':' + String(seconds%60).padStart(2,'0') : '';
      const live = document.getElementById('live-transcript');
      if (live) live.value = data.live_transcript || '';
      const device = document.getElementById('speech-device');
      if (device) device.textContent = data.selected_device_name || 'System-Standardgerät';
      const meter = document.getElementById('input-meter');
      if (meter) {{
        const level = Math.max(-96, Math.min(0, Number(data.audio_dbfs ?? -96)));
        meter.style.setProperty('--level', ((level + 96) / 96 * 100) + '%');
        meter.setAttribute('aria-valuenow', String(level));
        meter.setAttribute('aria-valuetext', level.toFixed(1) + ' dBFS');
        document.getElementById('input-dbfs').textContent = level.toFixed(1) + ' dBFS';
      }}
      const services = data.services || {{}};
      const quality = document.getElementById('processing-quality');
      const control = document.getElementById('processing-quality-control');
      const profiles = data.quality_profiles || [];
      const signature = JSON.stringify(profiles);
      if (control && profiles.length && control.dataset.profiles !== signature && (!quality || document.activeElement !== quality)) {{
        const chosen = quality && !quality.disabled ? quality.value : (data.selected_quality || 'auto');
        control.replaceChildren();
        if (profiles.length === 1) {{
          const label = document.createElement('strong'); label.textContent = 'Verarbeitung: ' + profiles[0].label;
          const value = document.createElement('input'); value.type = 'hidden'; value.name = 'quality'; value.value = profiles[0].id;
          control.append(label, value);
        }} else {{
          const label = document.createElement('label'); label.htmlFor = 'processing-quality'; label.textContent = 'Verarbeitung';
          const select = document.createElement('select'); select.id = 'processing-quality'; select.name = 'quality'; select.setAttribute('aria-label', 'Verarbeitungsqualität');
          const defaultProfile = profiles.find(p => p.default) || profiles[0];
          select.add(new Option('Standard (' + defaultProfile.label + ')', 'auto'));
          profiles.forEach(p => select.add(new Option(p.label, p.id)));
          select.value = [...select.options].some(option => option.value === chosen) ? chosen : 'auto';
          select.dataset.profiles = signature;
          const hint = document.createElement('span'); hint.className = 'small'; hint.textContent = 'Wird erst nach dem Ende der Aufnahme angewendet.';
          control.append(label, select, hint);
        }}
        control.dataset.profiles = signature;
      }}
      setServer('asr-server', (services.asr || {{}}).status || 'checking', (services.asr || {{}}).host || '');
      setServer('diarization-server', (services.diarization || {{}}).status || 'checking', (services.diarization || {{}}).host || '');
      setServer('llm-server', (services.llm || {{}}).status || 'checking', (services.llm || {{}}).host || '');
      setServer('t2med-server', data.t2med_status || 'checking', data.t2med_host || '');
      document.querySelector('.topbar').classList.toggle('with-temperatures',Boolean((data.gpu_temperatures || []).length));
      const temperatures = document.getElementById('gpu-temperatures');
      temperatures.replaceChildren();
      for (const item of data.gpu_temperatures || []) {{
        if (!Number.isFinite(item.value)) continue;
        const badge = document.createElement('span');
        badge.className = 'server-badge gpu-temperature';
        badge.textContent = 'GPU ' + Math.round(item.value) + ' °C';
        badge.title = item.tooltip || item.address || '';
        temperatures.append(badge);
      }}
      {status_layout_update}
      const patient = data.patient || {{}};
      for (const [id, value] of Object.entries({{
        'patient-name': patient.name || 'Patient wird geladen …',
        'patient-birth': data.patient_birth || '—',
        'patient-id': patient.id || '—',
        'patient-gender': patient.gender || '—',
      }})) document.getElementById(id).textContent = value;
      const patientError = document.getElementById('patient-error');
      patientError.textContent = data.patient_error || '';
      patientError.hidden = !data.patient_error;
      document.getElementById('t2med-server').title = data.t2med_message || '';
    }} catch (_error) {{}}
  }}
  window.setInterval(updateStatus, 500);
}})();
</script></body></html>""".format(
        version=VERSION,
        css=CSS + (WINDOWS_STATUS_CSS if WINDOWS_STATUS_LAYOUT else ''),
        status_layout_script=WINDOWS_STATUS_JS if WINDOWS_STATUS_LAYOUT else '',
        status_layout_update='fitStatusHeader();' if WINDOWS_STATUS_LAYOUT else '',
        t2med_badge=t2med_badge,
        asr_badge=asr_badge,
        diarization_badge=diarization_badge,
        llm_badge=llm_badge,
        patient_name=patient_name,
        birth_date=html.escape(birth_date),
        status_notices=status_notices,
        workspace=workspace,
        audio_controls=audio_controls,
        technical=technical,
        csrf=html.escape(state.csrf),
        csrf_json=json.dumps(state.csrf),
        temperature_badges=''.join('<span class="server-badge gpu-temperature" title="%s">GPU %s °C</span>' %
            (html.escape(v.get('tooltip','')),html.escape(str(v['value']))) for v in speech.get('gpu_temperatures',[])),
        initial_status=json.dumps(speech["status"]),
        initial_revision=int(state.document_revision),
        patient_error=html.escape(state.patient_error),
        patient_error_hidden='' if state.patient_error else 'hidden',
        field_names=json.dumps(list(state.active_fields) + ['diarized_text','output_mode','single_code']),
    )


def close_page_html():
    return """<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>kienzledoku record {version}</title><style>{css}</style></head>
<body><main><div class="card"><h1>Dokumentation übernommen</h1>
<p class="ok">Die Dokumentation wurde in T2med gespeichert. Dieses Fenster wird geschlossen.</p>
<button type="button" onclick="window.close()">Fenster schließen</button>
</div></main><script>window.setTimeout(function(){{ window.close(); }}, 150);</script></body></html>""".format(
        css=CSS,
        version=VERSION,
    )


def patient_conflict_html(open_patient=None, new_patient=None, open_error='', new_error='', csrf=''):
    def line(patient, error, loading):
        if patient:
            return '%s * %s' % (html.escape(patient.get('name') or 'Name unbekannt'),
                                html.escape(display_birth_date(patient.get('birth_date') or '')))
        if error:
            return 'Nicht ermittelbar: ' + html.escape(error)
        return loading
    return """<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>ACHTUNG Gefahr der Patientenverwechslung!</title>
<style>{css}.danger{{color:#b00020;font-size:28px;white-space:normal}}.warning-card{{max-width:760px;margin:8vh auto;background:white;padding:28px;border-radius:16px;box-shadow:0 4px 24px #0002}}.patient-warning{{font-size:20px;padding:12px;background:#fff4f4;margin:12px 0}}</style></head>
<body><main><section class="warning-card" role="alertdialog" aria-labelledby="danger-title">
<h1 id="danger-title" class="danger">ACHTUNG Gefahr der Patientenverwechslung!</h1>
<p class="patient-warning"><strong>Offene Aufnahme:</strong> {open_line}</p>
<p class="patient-warning"><strong>Neue Aufnahme:</strong> {new_line}</p>
<p>Bitte schließen Sie zuerst das alte Fenster. Der neue Aufruf startet keine Aufnahme und ersetzt keinen Patientenkontext.</p>
<form method="post" action="/action"><input type="hidden" name="csrf" value="{csrf}">
<button name="do" value="show">Offenes Fenster anzeigen</button>
<button class="subtle" name="do" value="close">Hinweis schließen</button></form>
</section></main></body></html>""".format(
        css=CSS, open_line=line(open_patient, open_error, 'Patient wird im offenen Fenster noch geladen …'),
        new_line=line(new_patient, new_error, 'Neue Person wird noch geladen …'),
        csrf=html.escape(csrf))


def show_patient_conflict(active, new_patient=None, new_error='', no_browser=False):
    """Show a separate, non-recording warning window for a rejected second call."""
    try:
        current = active.request()
        open_patient = current.get('patient') if isinstance(current, dict) else None
        open_error = current.get('error', '') if isinstance(current, dict) else ''
    except Exception as exc:
        open_patient, open_error = None, str(exc)
    csrf = secrets.token_urlsafe(24)
    completed = threading.Event()
    class WarningHandler(SecureLocalHandler, BaseHTTPRequestHandler):
        def log_message(self, *_args): return
        def send_page(self):
            data = patient_conflict_html(open_patient, new_patient, open_error, new_error, csrf).encode('utf-8')
            self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(data))); self.send_header('Cache-Control', 'no-store')
            self.end_headers(); self.wfile.write(data)
        def do_GET(self):
            if not self.authorize(): return
            self.send_page()
        def do_POST(self):
            if not self.authorize(): return
            try: form = self.read_form()
            except Exception: self.send_error(400); return
            if not secrets.compare_digest((form.get('csrf') or [''])[0], csrf):
                self.send_error(403); return
            if (form.get('do') or [''])[0] == 'show':
                try: active.request(show=True)
                except Exception: pass
            completed.set(); self.send_page()
    server = ThreadingHTTPServer(('127.0.0.1', 0), WarningHandler)
    url = configure_server(server)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    process = None
    try:
        if no_browser:
            print('ACHTUNG Gefahr der Patientenverwechslung!')
            return
        process, _kind = open_ui_window(url, os.path.dirname(os.path.abspath(__file__)))
        while not completed.wait(.25):
            if process is not None and process.poll() is not None: break
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
        server.shutdown(); server.server_close()


def open_ui_window(url, script_dir):
    """Open the local UI in Kienzledoku's native WebKit window."""
    if sys.platform == "darwin":
        helper = os.path.join(script_dir, "kienzledoku_window")
    elif sys.platform.startswith("linux"):
        helper = LINUX_NATIVE_WINDOW_PATH
        if not (os.path.isfile(helper) and os.access(helper, os.X_OK)):
            # Source-tree fallback for development outside an installed client.
            helper = os.path.join(script_dir, "kienzledoku_window_linux")
    elif sys.platform == 'win32':
        helper = os.path.join(script_dir, 'kienzledoku_window.exe')
    else:
        helper = ""

    if helper and os.path.isfile(helper) and os.access(helper, os.X_OK):
        command = [helper, '--url-stdin']
        icon_path = os.path.join(script_dir, 'assets', 'kienzledoku-record.icns')
        if sys.platform == 'win32':
            profile = tempfile.mkdtemp(prefix='webview-', dir=str(session_dir()))
            command.extend([profile, os.path.join(script_dir, 'assets', 'kienzledoku-record.ico')])
        if sys.platform == "darwin" and os.path.isfile(icon_path):
            command.append(icon_path)
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            # Inherit the launcher's protected log descriptor. Native GTK,
            # WebKit and bubblewrap failures must remain diagnosable.
            start_new_session=True,
        )
        # The UI capability must not be readable in another user's process list.
        try:
            process.stdin.write((url + '\n').encode('utf-8'))
            process.stdin.close()
        except Exception:
            process.terminate()
            raise RuntimeError('Das Record-Fenster konnte nicht initialisiert werden') from None
        if sys.platform == "win32":
            process.record_profile = profile
        return process, ('native-webview2' if sys.platform == 'win32' else
                         'native-webkit' if sys.platform == 'darwin' else 'native-webkitgtk')
    if sys.platform == 'win32':
        raise RuntimeError('WebView2-Fenster fehlt. Bitte das vollständige Windows-Paket installieren.')
    if sys.platform == 'darwin' or sys.platform.startswith('linux'):
        raise RuntimeError('Natives Record-Fenster fehlt. Bitte den Plattform-Installer erneut ausführen.')
    opened = webbrowser.open(url, new=1, autoraise=True)
    return None, "browser" if opened else "none"


def close_ui_window(state):
    process = state.ui_process
    if process is None or process.poll() is not None:
        return False
    try:
        time.sleep(0.2)
        process.terminate()
        process.wait(timeout=3)
        safe_log("UI close requested", window="native-webkit-container", closed="yes")
        return True
    except Exception:
        try:
            process.kill()
        except Exception:
            pass
        safe_log("UI close requested", window="native-webkit-container", closed="forced")
        return True


def make_handler(state):
    class Handler(SecureLocalHandler, BaseHTTPRequestHandler):
        server_version = "kienzledoku-record/%s" % VERSION

        def log_message(self, fmt, *args):
            # Never log URL/query/token. Keep test client quiet.
            return

        def _send_html(self, content, status=200):
            data = content.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _send_json(self, value, status=200):
            data = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self.authorize():
                return
            state.touch()
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == '/logo.svg':
                data = Path(__file__).with_name('assets').joinpath('kienzledoku-record.svg').read_bytes()
                self.send_response(200); self.send_header('Content-Type','image/svg+xml')
                self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
                return
            if parsed.path == "/":
                with state.lock:
                    self._send_html(page_html(state))
                return
            if parsed.path == "/health":
                self._send_html("OK")
                return
            if parsed.path == "/status":
                if getattr(state.speech, 'commander', None):
                    state.speech.start_service_check(background=True)
                with state.lock:
                    snapshot = state.speech.snapshot()
                    snapshot["document_revision"] = state.document_revision
                    snapshot["t2med_status"] = state.t2med_status
                    snapshot["t2med_host"] = state.t2med_host
                    snapshot["t2med_message"] = state.t2med_message
                    snapshot["patient"] = patient_summary(state.patient) if state.patient else None
                    snapshot["patient_birth"] = display_birth_date(snapshot["patient"]["birth_date"]) if state.patient else ""
                    snapshot["patient_error"] = state.patient_error
                    self._send_json(snapshot)
                return
            self._send_html("Nicht gefunden", 404)

        def do_POST(self):
            if not self.authorize():
                return
            state.touch()
            if urllib.parse.urlparse(self.path).path != "/action":
                self._send_html("Nicht gefunden", 404)
                return
            try:
                form = self.read_form()
            except (ValueError, UnicodeError):
                self.send_error(400); return
            csrf = (form.get("csrf") or [""])[0]
            if not secrets.compare_digest(csrf, state.csrf):
                self._send_html("Ungültige Sitzung", 403)
                return
            action = (form.get("do") or [""])[0]
            safe_log("UI action", action=action or "(leer)")
            with state.lock:
                state.message = ""
                state.error = ""
                try:
                    if state.write_succeeded or state.completed_event.is_set() or state.closing:
                        raise ValueError('Dieser Vorgang wird geschlossen')
                    if action == 'speech_audio_controls':
                        try:
                            raw = form.get('vad_enabled') or []
                            thresholds = form.get('threshold') or []
                            if len(raw) != 1 or raw[0] not in ('true', 'false') or len(thresholds) != 1:
                                raise ValueError('Ungültige Audio-Einstellungen')
                            controls = state.speech.set_audio_controls(raw[0] == 'true', int(thresholds[0]))
                        except (ValueError, OSError):
                            self._send_json({'error': 'Audio-Einstellungen konnten nicht gespeichert werden. Schwelle und Schreibrechte prüfen.'}, 400)
                            return
                        self._send_json({'ok': True, **controls})
                        return
                    if action in ('draft', 'discard'):
                        if action == 'draft':
                            for field in state.active_fields:
                                if field in form:
                                    state.documentation[field] = form[field][0]
                            if 'diarized_text' in form and state.speech.status not in ACTIVE_STATUSES:
                                state.speech.set_diarized_text(form['diarized_text'][0])
                            if 'output_mode' in form:
                                state.output_mode = normalize_output_mode(form['output_mode'][0])
                            if 'single_code' in form:
                                state.single_code = normalize_entry_code(form['single_code'][0])
                        else:
                            state.closing = True
                            state.speech.cancel()
                            state.completed_event.set()
                        self._send_json({'ok': True})
                        return
                    elif action == 'write_resolved':
                        state.write_uncertain = False
                        state.message = 'Erneute Übertragung ist nach Ihrer Prüfung wieder möglich.'
                    elif action == "patient":
                        start_patient_load(state)
                    elif action == "encounter":
                        state.encounter = state.client.get_encounter()
                        state.message = "Behandlungsfall geladen."
                    elif action == "speech_start":
                        if state.patient is None:
                            raise ValueError("Bitte zuerst den Patienten laden/prüfen.")
                        audio_device = (form.get("audio_device") or [""])[0]
                        diarized_text = (form.get("diarized_text") or [""])[0]
                        state.speech.set_diarized_text(diarized_text)
                        state.speech.set_audio_device(audio_device)
                        state.speech.set_quality((form.get('quality') or [None])[0])
                        state.speech.start()
                        state.message = ""
                    elif action == "speech_stop":
                        state.speech.set_quality((form.get('quality') or [None])[0])
                        state.speech.stop()
                        state.message = ""
                    elif action == "llm_regenerate":
                        diarized_text = (form.get("diarized_text") or [""])[0]
                        state.speech.set_quality((form.get('quality') or [None])[0])
                        state.speech.regenerate(diarized_text)
                        state.message = ""
                    elif action == "write":
                        if state.write_uncertain:
                            raise ValueError('Schreibausgang zuerst in T2med prüfen und unten ausdrücklich klären.')
                        if state.speech.status in ACTIVE_STATUSES:
                            raise ValueError('Zuerst Aufnahme und Verarbeitung abschließen.')
                        if state.patient is None:
                            raise ValueError("Bitte zuerst den Patienten laden/prüfen.")
                        incoming = {
                            field: (form.get(field) or [""])[0]
                            for field in state.active_fields
                        }
                        state.documentation = normalize_documentation(incoming, state.active_fields)
                        state.output_mode = normalize_output_mode(
                            (form.get("output_mode") or [OUTPUT_MODE_STRUCTURED])[0]
                        )
                        requested_code = (form.get("single_code") or [""])[0].strip()
                        if not requested_code and state.output_mode != OUTPUT_MODE_SINGLE:
                            requested_code = state.single_code or DEFAULT_SINGLE_CODE
                        state.single_code = normalize_entry_code(
                            requested_code
                        )
                        state.write_uncertain = True
                        status, _obj, labels = state.client.write_documentation(
                            state.documentation, state.output_mode, state.single_code,
                            state.active_fields,
                        )
                        # Commit the business outcome before logging or any UI operation.
                        # A lost local response must never make this write repeatable.
                        state.write_uncertain = False
                        state.write_succeeded = True
                        state.completed_event.set()
                        safe_log(
                            "Documentation transaction OK",
                            mode=state.output_mode,
                            entries=len(labels),
                            status=status,
                        )
                        state.message = (
                            "Dokumentation atomar in T2med übernommen (HTTP %s): %s"
                            % (status, ", ".join(labels))
                        )
                        self._send_html(close_page_html())
                        close_ui_window(state)
                        return
                    else:
                        raise ValueError("Unbekannte Aktion")
                except Exception as exc:
                    if state.write_succeeded:
                        # Persistence already succeeded. UI delivery/cleanup is best-effort;
                        # run_session also cleans up after completed_event is set.
                        safe_log("UI completion failed after successful write", error=type(exc).__name__)
                        return
                    if action == "write" and isinstance(exc, FhirTransactionRejected):
                        state.write_uncertain = False
                        safe_log("Documentation transaction rejected", rollback="confirmed")
                    if action == "patient":
                        state.t2med_status = "error"
                        state.t2med_message = "T2med-FHIR nicht erreichbar."
                    state.error = str(exc)
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

    return Handler


def run_session(deep_link, no_browser=False):
    safe_log("Python session start", **deep_link_metadata(deep_link))
    link = parse_deep_link(deep_link)
    try:
        acquire_record_session(link)
    except ActiveSessionError as active:
        new_patient = None
        new_error = ''
        conflict_client = None
        try:
            cfg = record_config.load()
            record_config.validate_target(link['fhir_base_url'], cfg)
            api_key, _source = ((DEMO_API_KEY, 'Connect') if cfg['connection']['mode'] == 'connect'
                                else get_api_key())
            conflict_client = T2medFhirClient(
                link['fhir_base_url'], link['context_id'], link['oauth_token'], api_key,
                connection=cfg['connection'])
            new_patient = patient_summary(conflict_client.get_patient_by_context())
        except Exception as exc:
            new_error = str(exc)
        finally:
            if conflict_client is not None:
                conflict_client.close()
        show_patient_conflict(active, new_patient, new_error, no_browser=no_browser)
        return
    cleanup_legacy_patient_data()
    safe_log(
        "Deep link parsed",
        scheme=link.get("scheme", ""),
        context_present="yes" if link.get("context_id") else "no",
        fhir_host=urllib.parse.urlparse(link.get("fhir_base_url", "")).hostname or "",
        oauth_present="yes" if link.get("oauth_token") else "no",
    )
    cfg = record_config.load()
    record_config.validate_target(link['fhir_base_url'], cfg)
    api_key, key_source = (DEMO_API_KEY, 'Connect') if cfg['connection']['mode'] == 'connect' else get_api_key()
    safe_log("API key selected", source=key_source)
    client = T2medFhirClient(
        link["fhir_base_url"], link["context_id"], link["oauth_token"], api_key, connection=cfg["connection"]
    )
    if client.proxy:
        from kienzledoku_product_key import production_build
        key_source = ('In Connect eingebetteter KienzleDoku-Hersteller-Key' if production_build()
                      else 'In Connect eingebetteter Key (Demo-Build)')
    state = SessionState(link, client, key_source)
    state.output_mode = cfg['record']['output_mode']
    state.single_code = cfg['record']['single_code']
    def accept_speech_document(document):
        with state.lock:
            if state.closing:
                return
            state.documentation = normalize_documentation(document, state.active_fields)
            state.document_revision += 1
            state.message = "Spracherkennung abgeschlossen; Dokumentation zur Prüfung übernommen."

    state.speech = SpeechRecognitionManager(
        os.path.dirname(os.path.abspath(__file__)),
        on_document=accept_speech_document,
        config_path=SERVICE_CONFIG_PATH,
    )
    if state.speech.commander:
        try:
            state.speech.load_documentation_settings()
        except Exception:
            client.close()
            unregister_window()
            raise
    state.active_fields = tuple(state.speech.active_fields)
    state.documentation = empty_documentation(state.active_fields)
    safe_log(
        "Speech configuration loaded",
        source=state.speech.config_source,
        asr_host=state.speech.services["asr"]["host"],
        diarization_host=state.speech.services["diarization"]["host"],
        llm_host=state.speech.services["llm"]["host"],
    )
    state.speech.start_service_check()

    def active_snapshot():
        with state.lock:
            return {
                'patient': patient_summary(state.patient) if state.patient else None,
                'error': state.patient_error,
                'loading': state.patient_loading,
                'open': not state.closing,
            }
    start_active_broker(active_snapshot)

    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    port = server.server_address[1]
    url = configure_server(server)

    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.5})
    thread.daemon = True
    thread.start()

    if not no_browser:
        try:
            state.ui_process, window_kind = open_ui_window(
                url, os.path.dirname(os.path.abspath(__file__))
            )
            register_window(link, state.ui_process)
            safe_log("UI window open requested", window=window_kind, ui_port=port)
        except Exception as exc:
            safe_log("UI window open failed", error=type(exc).__name__, ui_port=port)
            state.closing = True
            state.speech.cancel()
            client.close()
            server.shutdown(); server.server_close()
            unregister_window()
            raise
    else:
        safe_log("Browser suppressed", ui_port=port)
        print(url)

    start_initial_work(state)

    # The open window owns the RAM-only work. There is deliberately no timeout.
    try:
        while not state.completed_event.wait(2):
            if state.ui_process is not None:
                window_status = state.ui_process.poll()
                if window_status is not None:
                    safe_log("UI window exited", exit_code=window_status)
                    break
    except KeyboardInterrupt:
        pass
    finally:
        if state.speech is not None:
            state.closing = True
            state.speech.cancel()
        client.close()
        close_ui_window(state)
        server.shutdown()
        server.server_close()
        unregister_window()
        profile = getattr(state.ui_process, 'record_profile', None)
        if profile:
            shutil.rmtree(profile, ignore_errors=True)


def self_test():
    test_url = (
        "T2demo://demo/start?kontextId=test-123&"
        "fhirBasisUrl=https%3A%2F%2F127.0.0.1%3A16567%2Faps%2Ffhir%2Fapi%2Fr4&"
        "oAuthToken=test-token"
    )
    link = parse_deep_link(test_url)
    assert link["context_id"] == "test-123"
    assert link["fhir_base_url"] == "https://127.0.0.1:16567/aps/fhir/api/r4"
    assert link["oauth_token"] == "test-token"

    lan_url = (
        "T2demo://demo/start?kontextId=test-lan&"
        "fhirBasisUrl=https%3A%2F%2F10.0.83.120%3A16567%2Faps%2Ffhir%2Fapi%2Fr4&"
        "oAuthToken=test-token"
    )
    with tempfile.TemporaryDirectory() as config_dir:
        config_path = os.path.join(config_dir, "config.json")
        with open(config_path, "w", encoding="utf-8") as handle:
            json.dump({"t2med": {"fhir_host": "10.0.83.120"}}, handle)
        lan_link = parse_deep_link(lan_url, config_path=config_path)
        assert lan_link["fhir_base_url"] == "https://10.0.83.120:16567/aps/fhir/api/r4"

    patient = {
        "resourceType": "Patient",
        "id": "p1",
        "name": [{"family": "Mustermann", "given": ["Max"]}],
        "birthDate": "1980-04-12",
    }
    assert normalize_patient_result(patient)["id"] == "p1"
    bundle = {"resourceType": "Bundle", "entry": [{"resource": patient}]}
    assert normalize_patient_result(bundle)["id"] == "p1"
    assert patient_summary(patient)["name"] == "Mustermann, Max"

    try:
        validate_local_fhir_url("https://example.org/aps/fhir/api/r4")
        raise AssertionError("remote URL was not rejected")
    except ValueError:
        pass

    document = parse_documentation_json(
        '{"anamnese":"A","befund":"B","therapie":"T","prozedere":"P"}'
    )
    client = T2medFhirClient(
        "https://127.0.0.1:16567/aps/fhir/api/r4",
        "test-123",
        "test-token",
        "test-key",
    )
    labeled = client.build_documentation_resources(document, OUTPUT_MODE_STRUCTURED, "KI")
    assert [label for label, _resource in labeled] == [
        "Anamnese", "Befund", "Therapie", "Prozedere"
    ]
    assert [resource["resourceType"] for _label, resource in labeled] == [
        "Observation", "Observation", "Procedure", "Procedure"
    ]
    assert labeled[2][1]["status"] == "completed"
    assert labeled[2][1]["code"]["text"] == "T"
    assert labeled[3][1]["meta"]["profile"] == [PROFILE_PROZEDERE]

    transaction = client.build_transaction_bundle([resource for _label, resource in labeled])
    assert transaction["type"] == "transaction"
    assert [entry["request"]["url"] for entry in transaction["entry"]] == [
        "Observation", "Observation", "Procedure", "Procedure"
    ]

    single = client.build_documentation_resources(document, OUTPUT_MODE_SINGLE, "AI")
    assert len(single) == 1
    single_resource = single[0][1]
    assert single_resource["meta"]["profile"] == [PROFILE_FREITEXT]
    assert single_resource["extension"][0] == {
        "url": EXTENSION_FREITEXT_KUERZEL,
        "valueString": "AI",
    }
    assert single_resource["valueString"].startswith("ANAMNESE\nA")
    assert "\n\nPROZEDERE\nP" in single_resource["valueString"]

    extended = {field: field.upper() for field in DOCUMENT_FIELDS}
    extended_resources = client.build_documentation_resources(
        extended, OUTPUT_MODE_STRUCTURED, "KI", DOCUMENT_FIELDS)
    assert [label for label, _resource in extended_resources] == [
        "Anamnese", "Befund", "EKG", "Sonografie", "Therapie", "Prozedere", "Notiz"
    ]
    assert [resource["extension"][0]["valueString"]
            for label, resource in extended_resources
            if label in ("EKG", "Sonografie", "Notiz")] == ["EKG", "SON", "NOT"]

    response = {
        "resourceType": "Bundle",
        "type": "transaction-response",
        "entry": [
            {"response": {"status": "201 Created", "outcome": {
                "resourceType": "OperationOutcome",
                "issue": [{"severity": "information", "code": "processing"}],
            }}}
            for _label, _resource in labeled
        ],
    }
    assert validate_transaction_response(response, [label for label, _resource in labeled])

    failed_response = {
        "resourceType": "Bundle",
        "type": "transaction-response",
        "entry": [{"response": {"status": "422", "outcome": {
            "resourceType": "OperationOutcome",
            "issue": [{"severity": "error", "diagnostics": "Testfehler"}],
        }}}],
    }
    try:
        validate_transaction_response(failed_response, ["Anamnese"])
        raise AssertionError("transaction error was not rejected")
    except FhirError as exc:
        assert "zurückgerollt" in str(exc)

    print("SELF-TEST OK - kienzledoku record %s (Python %s)" % (VERSION, sys.version.split()[0]))


def main():
    parser = argparse.ArgumentParser(description="kienzledoku record %s mit T2med FHIR" % VERSION)
    deep_link_group = parser.add_mutually_exclusive_group()
    deep_link_group.add_argument(
        "--deep-link",
        help="T2demo://, whisperdoku:// oder kienzledoku:// aus T2med",
    )
    deep_link_group.add_argument(
        "--deep-link-stdin",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--no-browser", action="store_true", help="print local UI URL instead of opening browser")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument('--settings', action='store_true')
    parser.add_argument('--setup', action='store_true', help='Server während der Installation abfragen')
    parser.add_argument('--from-connect', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--import-config', metavar='TOML')
    args = parser.parse_args()

    safe_log(
        "Process invoked",
        version=VERSION,
        python=sys.version.split()[0],
        deep_link_arg="yes" if (args.deep_link or args.deep_link_stdin) else "no",
    )

    if sys.version_info < (3, 9):
        safe_log("Python version rejected", python=sys.version.split()[0])
        print("Fehler: Python 3.9 oder neuer erforderlich.", file=sys.stderr)
        return 2

    if args.self_test:
        self_test()
        return 0
    if args.import_config:
        record_config.save(record_config.load(args.import_config))
        return 0
    if args.setup or args.settings or not (args.deep_link or args.deep_link_stdin):
        from kienzledoku_settings import run_settings
        from kienzledoku_update import Lease
        with Lease(record_config.config_dir() / 'update.lock'):
            saved = run_settings(no_browser=args.no_browser, window_opener=open_ui_window, setup=args.setup)
        return 1 if args.setup and not saved else 0
    deep_link = args.deep_link
    if args.deep_link_stdin:
        try:
            deep_link = read_deep_link_stdin()
        except Exception as exc:
            safe_log("Deep-link pipe read failed", error=type(exc).__name__)
            print("kienzledoku record: Startfehler: %s" % exc, file=sys.stderr)
            if not args.no_browser:
                notify_start_failure(exc)
            return 1
    if not deep_link:
        parser.error("--deep-link fehlt (normalerweise startet T2med die App über T2demo:// bzw. kienzledoku://)")

    try:
        run_session(deep_link, no_browser=args.no_browser)
        return 0
    except Exception as exc:
        # Never print/log the deep-link itself: it may contain OAuth material.
        safe_log("Session failed", error=type(exc).__name__, status=getattr(exc, "status", ""))
        print("kienzledoku record: %s" % exc, file=sys.stderr)
        if sys.platform == 'win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(exc), 'kienzledoku record 1.8.2', 0x10)
        if not args.no_browser:
            notify_start_failure(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
