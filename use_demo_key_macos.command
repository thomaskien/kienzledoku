#!/bin/bash
SERVICE="Kienzledoku-T2med-API-Key"
LEGACY_SERVICE="WhisperDoku-T2med-API-Key"
/usr/bin/security delete-generic-password -s "$SERVICE" >/dev/null 2>&1 || true
/usr/bin/security delete-generic-password -s "$LEGACY_SERVICE" >/dev/null 2>&1 || true
echo "Eigene Kienzledoku-/Alt-Schlüsselbund-Keys entfernt. Es wird wieder der öffentliche T2med-Demo-Key verwendet."
echo "WICHTIG: Maximal 100 einzelne FHIR-Requests pro APS-Serverprozess."
echo "Nach Ausschöpfen muss der T2med-/APS-Serverprozess neu gestartet werden."
