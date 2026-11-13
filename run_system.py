"""Start a fresh demo/eval system, including managed table initialization."""
import os
from pathlib import Path
import sys


if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    python = root/'ai-services/.venv/bin/python'
    if not python.is_file():
        raise SystemExit('Create ai-services/.venv and install its requirements first')
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(root/'ai-services'), str(root)]))
    os.chdir(root)
    os.execve(str(python), [str(python), '-m', 'app.system_start', *sys.argv[1:]], env)
