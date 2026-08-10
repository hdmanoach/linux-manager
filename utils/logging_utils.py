"""Journal d'audit sans données sensibles."""
import json
from datetime import datetime, timezone
from pathlib import Path

LOG_FILE_PATH = Path("var/log/audit.jsonl")


def log_user_event(username, event_type, actor="unknown", success=True):
    """Enregistre l'action, jamais le mot de passe ni des données secrètes."""
    LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        "target": username,
        "actor": actor,
        "success": success,
    }
    with LOG_FILE_PATH.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
