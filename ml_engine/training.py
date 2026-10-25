"""Retraining the grade forecaster in the background, and the status of the last run.

Training reads every school's grades and takes about a minute, so it never runs inside a web request. It runs as
`python manage.py train_ml_models --model forecast --record` in a process of its own, and a status file next to the
model says whether a run is going, why it started, who started it and how the last one ended. Two things start a
run: the System Administrator (Admin Portal, Grade Forecaster) and the registrar locking a grading period, which
makes that period's grades final. Pages pick up the new model by themselves (ml_engine.forecast.load).
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from .forecast import MODEL_DIR

STATUS_FILE = MODEL_DIR / 'training.json'      # git-ignored with the model
LOG_FILE = MODEL_DIR / 'training.log'
STALE = timedelta(minutes=20)                    # a run that never reported back is treated as stopped after this


def _read():
    try:
        return json.loads(STATUS_FILE.read_text(encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        return {}


def _write(data):
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATUS_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2), encoding='utf-8')
    os.replace(tmp, STATUS_FILE)


def status():
    """{'state': 'idle' | 'running' | 'done' | 'failed' | 'stopped', 'reason', 'by', 'started_at', 'finished_at', 'detail'}."""
    data = _read() or {'state': 'idle'}
    if data.get('state') == 'running':
        try:
            started = datetime.fromisoformat(data['started_at'])
        except (KeyError, ValueError):
            started = None
        if started is None or timezone.now() - started > STALE:
            data['state'] = 'stopped'
    return data


def running():
    return status().get('state') == 'running'


def start(reason, by=''):
    """Start a background run unless one is going. True when it started."""
    if running():
        return False
    _write({'state': 'running', 'reason': reason, 'by': by, 'started_at': timezone.now().isoformat()})
    flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == 'nt' else 0
    try:
        with open(LOG_FILE, 'w', encoding='utf-8') as log:
            subprocess.Popen([sys.executable, str(Path(settings.BASE_DIR) / 'manage.py'), 'train_ml_models', '--model', 'forecast', '--record'],
                             cwd=settings.BASE_DIR, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             creationflags=flags, close_fds=True, start_new_session=os.name != 'nt')
    except OSError as exc:
        finish(False, f'Could not start the training process: {exc}')
        return False
    return True


def finish(ok, detail=''):
    """Called by the training command when a recorded run ends."""
    data = _read()
    data.update(state='done' if ok else 'failed', finished_at=timezone.now().isoformat(), detail=detail)
    _write(data)


def log_tail(lines=12):
    try:
        return LOG_FILE.read_text(encoding='utf-8', errors='replace').splitlines()[-lines:]
    except FileNotFoundError:
        return []
