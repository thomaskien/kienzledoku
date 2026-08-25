#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gemeinsamer Dokumentationsvertrag für Kienzledoku 1.2.

Dieses Modul enthält bewusst weder FHIR- noch ASR-/LLM-Transportlogik. Es ist
die stabile Grenze zwischen der Kienzlefon-Pipeline und dem T2med-Adapter.
"""

from __future__ import print_function

import json


DOCUMENT_FIELDS = ("anamnese", "befund", "therapie", "prozedere")
DOCUMENT_LABELS = {
    "anamnese": "Anamnese",
    "befund": "Befund",
    "therapie": "Therapie",
    "prozedere": "Prozedere",
}

OUTPUT_MODE_STRUCTURED = "structured"
OUTPUT_MODE_SINGLE = "single"
OUTPUT_MODES = (OUTPUT_MODE_STRUCTURED, OUTPUT_MODE_SINGLE)


def empty_documentation():
    return {field: "" for field in DOCUMENT_FIELDS}


def normalize_documentation(value):
    """Return a strict four-field document without inventing missing content."""
    if not isinstance(value, dict):
        raise ValueError("Dokumentation muss ein JSON-Objekt sein")

    unknown = sorted(set(value) - set(DOCUMENT_FIELDS))
    if unknown:
        raise ValueError("Unbekannte Dokumentationsfelder: %s" % ", ".join(unknown))

    normalized = empty_documentation()
    for field in DOCUMENT_FIELDS:
        item = value.get(field, "")
        if item is None:
            item = ""
        if not isinstance(item, str):
            raise ValueError("Dokumentationsfeld %s muss Text enthalten" % field)
        normalized[field] = item.strip()
    return normalized


def parse_documentation_json(raw):
    """Parse the pure JSON contract; tolerate only an enclosing Markdown fence."""
    if isinstance(raw, dict):
        value = raw
    else:
        if not isinstance(raw, str):
            raise ValueError("LLM-Dokumentation muss Text oder ein JSON-Objekt sein")

        text = raw.strip()
        if text.startswith("```") and text.endswith("```"):
            lines = text.splitlines()
            if len(lines) < 3:
                raise ValueError("Leerer Markdown-JSON-Block")
            text = "\n".join(lines[1:-1]).strip()

        def unique_object(pairs):
            result = {}
            for key, item in pairs:
                if key in result:
                    raise ValueError("Doppeltes JSON-Feld: %s" % key)
                result[key] = item
            return result

        try:
            value = json.loads(text, object_pairs_hook=unique_object)
        except Exception as exc:
            raise ValueError("LLM-Dokumentation ist kein gültiges JSON: %s" % exc)

    if isinstance(value, dict):
        missing = sorted(set(DOCUMENT_FIELDS) - set(value))
        if missing:
            raise ValueError("Fehlende Dokumentationsfelder: %s" % ", ".join(missing))
    return normalize_documentation(value)


def normalize_output_mode(value):
    mode = str(value or "").strip().lower()
    if mode not in OUTPUT_MODES:
        raise ValueError("Unbekannter T2med-Ausgabemodus: %s" % (mode or "(leer)"))
    return mode


def normalize_entry_code(value):
    code = str(value or "").strip()
    if not code:
        raise ValueError("Für den Einzelblock fehlt das T2med-Kürzel")
    if len(code) > 20:
        raise ValueError("Das T2med-Kürzel darf höchstens 20 Zeichen lang sein")
    if not code.isprintable() or any(ch in "\r\n\t" for ch in code):
        raise ValueError("Das T2med-Kürzel enthält unzulässige Steuerzeichen")
    return code


def nonempty_fields(documentation):
    document = normalize_documentation(documentation)
    return [(field, document[field]) for field in DOCUMENT_FIELDS if document[field]]


def compose_single_block(documentation):
    """Combine non-empty fields deterministically, preserving their order."""
    sections = []
    for field, text in nonempty_fields(documentation):
        sections.append("%s\n%s" % (DOCUMENT_LABELS[field].upper(), text))
    return "\n\n".join(sections)
