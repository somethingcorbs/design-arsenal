"""File-backed store for Design Arsenal records.

Layout (all under the repo root):
  data/resources/<id>.json   approved library
  data/inbox/<id>.json       researched candidates awaiting a decision
  data/snoozed/<id>.json     "Maybe" decisions, resurface after snooze_until
  data/rejected.jsonl        {id, dedupe_keys, name, url, reason, decided_at}
  data/leads.jsonl           unvetted discovery queue
  data/decisions_applied.jsonl, data/runs/<YYYY-Www>.json
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
CONFIG = ROOT / "config"
SCHEMA = ROOT / "schema"
STATES = ("resources", "inbox", "snoozed")

# Hosts where many unrelated projects live; identity comes from the path, not the host.
SHARED_HOSTS = {
    "github.com": "github", "npmjs.com": "npm", "pub.dev": "pub",
    "gitlab.com": "host", "codepen.io": "host", "medium.com": "host", "uxplanet.org": "host",
    "figma.com": "host", "dribbble.com": "host", "behance.net": "host", "gumroad.com": "host",
    "youtube.com": "host", "x.com": "host", "twitter.com": "host",
}


def today() -> str:
    return dt.date.today().isoformat()


def iso_week(d: dt.date | None = None) -> str:
    y, w, _ = (d or dt.date.today()).isocalendar()
    return f"{y}-W{w:02d}"


def slugify(text: str, max_words: int = 4) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return "-".join(s.split("-")[:max_words]) or "item"


def host_of(url: str) -> str:
    h = (urlparse(url if "://" in url else "https://" + url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def url_keys(url: str) -> list[str]:
    """Identity keys implied by a URL."""
    if not url:
        return []
    h = host_of(url)
    if not h:
        return []
    kind = SHARED_HOSTS.get(h)
    if not kind:
        return [f"host:{h}"]
    parts = [p for p in urlparse(url if "://" in url else "https://" + url).path.lower().split("/") if p]
    if kind == "github" and len(parts) >= 2:
        return [f"github:{parts[0]}/{parts[1]}"]
    if kind == "npm" and len(parts) >= 2 and parts[0] == "package":
        return [f"npm:{'/'.join(parts[1:3]) if parts[1].startswith('@') else parts[1]}"]
    if kind == "pub" and len(parts) >= 2 and parts[0] == "packages":
        return [f"pub:{parts[1]}"]
    return [f"host:{h}/{'/'.join(parts[:2])}"] if parts else [f"host:{h}"]


def name_key(name: str) -> str:
    base = re.split(r"\s[\(\-–—:/|]\s?|\s\(|:", name)[0]
    return f"name:{slugify(base, 6)}"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def field_order() -> list[str]:
    return read_json(SCHEMA / "record.schema.json")["required"]


def load_state(state: str) -> dict[str, dict]:
    d = DATA / state
    return {p.stem: read_json(p) for p in sorted(d.glob("*.json"))} if d.exists() else {}


def load_all() -> dict[str, dict[str, dict]]:
    return {s: load_state(s) for s in STATES}


def save_record(state: str, rec: dict) -> Path:
    order = field_order()
    ordered = {k: rec[k] for k in order if k in rec}
    ordered.update({k: v for k, v in rec.items() if k not in ordered})
    path = DATA / state / f"{rec['id']}.json"
    write_json(path, ordered)
    return path


def move_record(rec_id: str, src: str, dst: str) -> Path:
    src_path = DATA / src / f"{rec_id}.json"
    rec = read_json(src_path)
    path = save_record(dst, rec)
    src_path.unlink()
    return path


def taxonomy() -> dict:
    return read_json(CONFIG / "taxonomy.json")


def config() -> dict:
    return read_json(CONFIG / "arsenal.config.json")
