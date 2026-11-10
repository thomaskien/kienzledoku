"""Öffentliche Fehler enthalten weder Backend-Antworten noch medizinische Daten."""


class CommanderError(Exception):
    code = "commander_error"
    status = 503
    message = "Die Verarbeitung ist derzeit nicht verfügbar."

    def __init__(self, message=None):
        super().__init__(message or self.message)


class InvalidRequest(CommanderError):
    code = "invalid_request"
    status = 400
    message = "Die Anfrage ist ungültig."


class Busy(CommanderError):
    code = "model_in_use"
    status = 409
    message = "Ein laufender Auftrag benötigt das Modell noch."


class BackendFailure(CommanderError):
    code = "backend_failed"
    status = 502
    message = "Das angeforderte Modell konnte die Verarbeitung nicht abschließen."


class QueueFull(CommanderError):
    code = "queue_full"
    status = 429
    message = "Die Warteschlange ist voll. Bitte dieselbe Aufnahme später erneut verarbeiten."


class Conflict(CommanderError):
    code = "request_id_conflict"
    status = 409
    message = "Diese Anfrage-ID wurde bereits für einen anderen Inhalt verwendet."


class QueueExpired(CommanderError):
    code = "queue_timeout"
    message = "Die Anfrage wartet zu lange auf ein verfügbares Modell. Bitte dieselbe Aufnahme erneut verarbeiten."


class RecordingNotFinalized(CommanderError):
    code, status = "recording_not_finalized", 409
    message = "Die Aufnahme am beauftragenden Arbeitsplatz muss zuerst vollständig beendet und transkribiert sein."
