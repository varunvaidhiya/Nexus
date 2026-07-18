"""Incremental-sync state: per-tool map of session path -> mtime at last push.

A session file is re-sent only when its mtime moves past the recorded value;
the backend's dedupe makes re-sends harmless, so losing this file just costs
one redundant sync.
"""

import json
from pathlib import Path


class SyncState:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict[str, dict[str, float]] = {}

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return
        if isinstance(raw, dict):
            self._data = {
                tool: {str(k): float(v) for k, v in files.items()}
                for tool, files in raw.items()
                if isinstance(files, dict)
            }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2))
        tmp.replace(self.path)

    def needs_sync(self, tool: str, path: Path, mtime: float) -> bool:
        return self._data.get(tool, {}).get(str(path), -1.0) < mtime

    def mark_synced(self, tool: str, path: Path, mtime: float) -> None:
        self._data.setdefault(tool, {})[str(path)] = mtime
