#!/usr/bin/env python3
"""
Start the PR Intelligence System API server.

Usage:
    python start_api.py [--port 8000] [--no-reload]

Sets PYTHONPATH to the project root before launching uvicorn so that the
'api' package is importable in both the main process and any reload/worker
subprocesses (which inherit the environment, not sys.path).
"""

import sys
import os
import argparse

# ── Make 'api', 'core', 'config' importable ───────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

# Propagate to subprocesses spawned by uvicorn --reload
existing = os.environ.get('PYTHONPATH', '')
os.environ['PYTHONPATH'] = (
    PROJECT_ROOT if not existing else f"{PROJECT_ROOT}{os.pathsep}{existing}"
)

import uvicorn  # noqa: E402 — must be after sys.path is patched


def main():
    parser = argparse.ArgumentParser(description='PR Intelligence System API')
    parser.add_argument('--host',     default='0.0.0.0')
    parser.add_argument('--port',     default=8000, type=int)
    parser.add_argument('--no-reload', dest='reload', action='store_false', default=True)
    args = parser.parse_args()

    print(f"Starting API — project root: {PROJECT_ROOT}")
    print(f"Swagger UI: http://{args.host}:{args.port}/docs")

    uvicorn.run(
        'api.main:app',
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_dirs=[PROJECT_ROOT],
    )


if __name__ == '__main__':
    main()
