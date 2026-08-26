#!/bin/bash
set -eu

if command -v secret-tool >/dev/null 2>&1; then
    secret-tool clear application kienzledoku service t2med-api-key || true
fi
echo "Eigener Kienzledoku-Key entfernt. Es wird wieder der öffentliche T2med-Demo-Key verwendet."
echo "WICHTIG: Maximal 100 einzelne FHIR-Requests pro APS-Serverprozess."
echo "Nach Ausschöpfen muss der T2med-/APS-Serverprozess neu gestartet werden."
