import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.json"
LOG_DIR = BASE_DIR / "logs"

DEFAULTS = {
    "pairs": [],
    "timeframes": [
        {"tf": "1W", "column": "W"},
        {"tf": "1D", "column": "D"},
        {"tf": "240", "column": "4H"},
        {"tf": "60", "column": "1H"},
        {"tf": "15", "column": "15m"},
        {"tf": "5", "column": "5m"},
    ],
    "load_delay_sec": 2,
    "snapshot_timeout_sec": 10,
    "snapshot_retries": 1,
    "cdp_url": "http://127.0.0.1:9222",
    "notion": {
        "database_id": "98afde40ea144c7e85cd584016a8411e",
        "pair_property": "Pair",
        "date_property": "Date",
        "setup_property": "Setup",
    },
}


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))
    if CONFIG_PATH.exists():
        user = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        notion = {**cfg["notion"], **user.get("notion", {})}
        cfg.update(user)
        cfg["notion"] = notion
    return cfg


def notion_token() -> str:
    load_dotenv(BASE_DIR / ".env")
    token = os.getenv("NOTION_TOKEN", "").strip()
    if not token:
        raise RuntimeError("NOTION_TOKEN не задан в .env")
    return token


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / f"tvsnap_{datetime.now():%Y%m%d}.log"
    root = logging.getLogger()
    if not root.handlers:
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        root.addHandler(fh)
        root.addHandler(sh)
        root.setLevel(logging.INFO)
    return logging.getLogger("tvsnap")
