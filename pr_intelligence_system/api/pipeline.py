"""Background pipeline runner with status tracking."""

import os
import sys
import uuid
import threading
import subprocess
import logging
from datetime import datetime, timezone
from collections import deque
from typing import Optional

logger = logging.getLogger(__name__)

_MAX_LOG_LINES = 200

# Shared state (process-level singleton — single-worker deployment)
_state = {
    'status':      'idle',      # idle | running | done | failed
    'job_id':      None,
    'started_at':  None,
    'finished_at': None,
    'exit_code':   None,
    'log_lines':   deque(maxlen=_MAX_LOG_LINES),
    '_lock':       threading.Lock(),
}


def _resolve_run_all() -> str:
    """Return absolute path to run_all.py."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, '..', 'run_all.py')


def _stream_process(proc: subprocess.Popen, log_deque: deque) -> None:
    """Read subprocess stdout/stderr and append to deque."""
    for line in proc.stdout:
        stripped = line.rstrip('\n')
        log_deque.append(stripped)
        logger.info(f"[pipeline] {stripped}")
    proc.wait()


def _run_pipeline_thread(job_id: str) -> None:
    run_all_path = _resolve_run_all()
    project_root = os.path.dirname(run_all_path)

    with _state['_lock']:
        _state['log_lines'].clear()

    logger.info(f"Pipeline job {job_id}: starting {run_all_path}")
    try:
        proc = subprocess.Popen(
            [sys.executable, run_all_path],
            cwd=project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        _stream_process(proc, _state['log_lines'])
        exit_code = proc.returncode
    except Exception as exc:
        logger.error(f"Pipeline job {job_id} exception: {exc}")
        exit_code = -1
        _state['log_lines'].append(f"EXCEPTION: {exc}")

    with _state['_lock']:
        _state['exit_code']   = exit_code
        _state['finished_at'] = datetime.now(timezone.utc).isoformat()
        _state['status']      = 'done' if exit_code == 0 else 'failed'

    logger.info(f"Pipeline job {job_id}: finished (exit={exit_code})")


def trigger_pipeline() -> dict:
    """Start the pipeline in a background thread if not already running.

    Returns a dict with status and job_id.
    """
    with _state['_lock']:
        if _state['status'] == 'running':
            return {'status': 'already_running', 'job_id': _state['job_id']}

        job_id = str(uuid.uuid4())[:8]
        _state['status']      = 'running'
        _state['job_id']      = job_id
        _state['started_at']  = datetime.now(timezone.utc).isoformat()
        _state['finished_at'] = None
        _state['exit_code']   = None

    t = threading.Thread(target=_run_pipeline_thread, args=(job_id,), daemon=True)
    t.start()
    return {'status': 'started', 'job_id': job_id}


def get_status() -> dict:
    """Return a snapshot of the current pipeline state."""
    with _state['_lock']:
        return {
            'status':      _state['status'],
            'job_id':      _state['job_id'],
            'started_at':  _state['started_at'],
            'finished_at': _state['finished_at'],
            'exit_code':   _state['exit_code'],
            'log_tail':    list(_state['log_lines'])[-50:],
        }
