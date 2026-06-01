"""Session management for benchmark runs."""
import json
import os
from typing import Any
from src.features.multi_run import write_session_meta

class SessionManager:
    """Manages multi-run session metadata and state."""
    def __init__(self, results_dir: str):
        self.results_dir = results_dir

    def create_session(self, session_id: str, meta: dict[str, Any]):
        """Create a new session metadata file."""
        write_session_meta(self.results_dir, session_id, meta)

    def update_session(self, session_id: str, updates: dict[str, Any]):
        """Update existing session metadata."""
        path = os.path.join(self.results_dir, f"session_{session_id}_meta.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                meta.update(updates)
                write_session_meta(self.results_dir, session_id, meta)
            except Exception:
                # Fallback to creating if update fails
                write_session_meta(self.results_dir, session_id, updates)
        else:
            write_session_meta(self.results_dir, session_id, updates)
