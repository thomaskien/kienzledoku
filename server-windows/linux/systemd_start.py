"""Reconcile a lost systemctl reply without repeating a restart."""
import os
import subprocess
import time

TRANSPORT_ERRORS=('D-Bus connection terminated','Connection reset by peer',
                  'Transport endpoint is not connected','Connection timed out')


def unit_state(unit):
    result=subprocess.run(['systemctl','show',unit,'--no-pager',
        '-p','ActiveState,SubState,Result,InvocationID,LoadState'],capture_output=True,
        text=True,timeout=15,env=dict(os.environ,LC_ALL='C'))
    if result.returncode:return None
    return dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)


def start_unit(unit,restart=False,timeout=600):
    before=unit_state(unit)
    if before is None or before.get('LoadState')=='not-found':
        raise RuntimeError('Dienstverwaltung ist nicht erreichbar oder der Kienzledoku-Dienst fehlt. Es wurde kein Start ausgelöst.')
    if not restart and before.get('ActiveState')=='active':return
    action='restart' if restart else 'start'
    try:
        result=subprocess.run(['systemctl',action,unit],capture_output=True,text=True,
            timeout=timeout+30,env=dict(os.environ,LC_ALL='C'))
    except subprocess.TimeoutExpired:
        lost=True
    else:
        if result.returncode==0:return
        lost=any(message in (result.stderr or '') for message in TRANSPORT_ERRORS)
    if not lost:
        raise RuntimeError('Kienzledoku-Dienststart fehlgeschlagen. Dienstprotokoll prüfen; kein automatischer Neustart.')
    print('Rückmeldung der Dienstverwaltung unterbrochen. Tatsächlichen Dienststart prüfen; kein erneuter Neustart.',flush=True)
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        try:current=unit_state(unit)
        except (OSError,subprocess.TimeoutExpired):current=None
        if current:
            if current.get('ActiveState')=='failed' or current.get('Result') not in (None,'','success'):
                raise RuntimeError('Der Kienzledoku-Dienst meldet einen Startfehler. Dienstprotokoll prüfen.')
            if current.get('ActiveState')=='active' and current.get('SubState')=='running':
                if restart and (not current.get('InvocationID') or current['InvocationID']==before.get('InvocationID')):
                    raise RuntimeError('Der neue Dienststart ist nicht bestätigt; die alte Instanz wird nicht als Update-Erfolg gewertet.')
                return
        time.sleep(.5)
    raise RuntimeError('Dienststart nach unterbrochener Rückmeldung nicht bestätigt. Dienstprotokoll prüfen.')
