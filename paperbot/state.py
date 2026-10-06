"""Atomic JSON state with optional immediate bot-state Git checkpoints."""
import json
import os
from pathlib import Path
import subprocess


class State:
    def __init__(self, path, dry_run=False, git=False, persistent=True):
        self.path = Path(path).resolve()
        self.dry_run, self.git = dry_run, git
        self.persistent = persistent
        if git and not persistent:
            raise ValueError('Git checkpoints require persistent state')
        self.lock = self.path.with_suffix('.lock')
        self.data = {'schema': 1, 'papers': {}, 'attempts': {}}

    def __enter__(self):
        if not self.persistent:
            return self
        if not self.dry_run:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.fd = os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            if self.git and not self.dry_run and not self.path.exists():
                raise ValueError('Missing state in bot-state checkout; refusing reset')
            if self.path.exists():
                self.data = json.loads(self.path.read_text(encoding='utf-8'))
                if self.data.get('schema') != 1 or not isinstance(self.data.get('papers'), dict) or not isinstance(self.data.get('attempts'), dict):
                    raise ValueError('Invalid state; refusing reset')
            if self.git and not self.dry_run:
                if Path(self._git('rev-parse', '--show-toplevel').strip()).resolve() != self.path.parent:
                    raise ValueError('State must live at dedicated checkout root')
                if self._git('branch', '--show-current').strip() != 'bot-state':
                    raise ValueError('State checkout must use bot-state branch')
            return self
        except BaseException:
            self.__exit__()
            raise

    def __exit__(self, *args):
        if not self.dry_run and hasattr(self, 'fd'):
            os.close(self.fd)
            self.lock.unlink(missing_ok=True)
            del self.fd

    def _git(self, *args):
        result = subprocess.run(['git', '-C', str(self.path.parent), *args], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError('State Git checkpoint failed')
        return result.stdout

    def save(self):
        if self.dry_run or not self.persistent:
            return
        temporary = self.path.with_suffix('.tmp')
        with temporary.open('w', encoding='utf-8') as output:
            json.dump(self.data, output, ensure_ascii=False, indent=2)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, self.path)
        if self.git:
            self._git('add', '--', self.path.name)
            if self._git('diff', '--cached', '--name-only').strip():
                self._git('commit', '-m', 'Checkpoint paper bot state')
            self._git('push', 'origin', 'HEAD:bot-state')  # No force push; conflicts stop processing.
