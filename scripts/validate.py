#!/usr/bin/env python3
"""Validate every data file. Exit 1 on any error.

Checks: JSON schema, filename == id, ids unique across states, dedupe keys unique across
resources/inbox/snoozed, category in taxonomy, parent_id exists, no spreadsheet-formula
injection, quote length, pricing consistency, and evidence rules for scout-origin records.

  python3 scripts/validate.py            human-readable
  python3 scripts/validate.py --json     machine-readable summary
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import store  # noqa: E402

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:  # pragma: no cover
    sys.exit("jsonschema is required: pip install -r requirements.txt")

FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
FREE_MODELS = {"Free", "Open source (free)"}
QUOTE_MAX_WORDS = 25


def strings_in(obj, path=""):
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from strings_in(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from strings_in(v, f"{path}[{i}]")


def number_in_quote(value: float, quote: str) -> bool:
    nums = {float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", quote)}
    return any(abs(n - value) < 0.011 for n in nums)


def check_record(rec: dict, state: str, fname: str, validator, categories: set[str]) -> list[str]:
    errs = []
    where = f"{state}/{fname}"
    for e in sorted(validator.iter_errors(rec), key=lambda e: list(e.path)):
        loc = "/".join(str(p) for p in e.path) or "(root)"
        errs.append(f"{where}: schema {loc}: {e.message[:200]}")
    if errs:
        return errs  # structural errors make the rest noisy

    if rec["id"] != Path(fname).stem:
        errs.append(f"{where}: id '{rec['id']}' does not match filename")
    for p, s in strings_in(rec):
        if s.startswith(FORMULA_START):
            errs.append(f"{where}: {p} starts with a spreadsheet formula character")
        if "javascript:" in s.lower() and ("url" in p.lower()):
            errs.append(f"{where}: {p} contains a javascript: URL")
    for p, s in strings_in({"evidence_urls": rec["evidence_urls"], "pricing_source_url": rec["pricing_source_url"]}):
        if s and not s.startswith("https://") and s not in ("N/A", "Unconfirmed"):
            errs.append(f"{where}: {p} is not an https URL")
    if categories and rec["category"] not in categories:
        errs.append(f"{where}: category '{rec['category']}' not in config/taxonomy.json")

    for q in ("pricing_quote", "license_quote"):
        if rec[q] and len(rec[q].split()) > QUOTE_MAX_WORDS:
            errs.append(f"{where}: {q} exceeds {QUOTE_MAX_WORDS} words")

    if rec["pricing_model"] in FREE_MODELS and rec["paid_entry_usd_month"] not in (None, 0):
        errs.append(f"{where}: pricing_model '{rec['pricing_model']}' but paid_entry_usd_month is set")

    if rec["origin"].startswith("scout-"):
        priced = rec["paid_entry_usd_month"] or rec["one_time_usd"]
        if priced:
            if not rec["pricing_quote"] or not rec["pricing_fetched_at"]:
                errs.append(f"{where}: scout record has a price but no pricing_quote/pricing_fetched_at "
                            "(null the price and list it in unverified_fields instead)")
            elif not number_in_quote(float(priced), rec["pricing_quote"]):
                errs.append(f"{where}: pricing_quote does not contain the stored price {priced}")
        if rec["pricing_source_url"].startswith("https://") and rec["paid_entry_usd_month"] and \
                store.host_of(rec["pricing_source_url"]) != store.host_of(rec["url"]) and \
                not store.host_of(rec["pricing_source_url"]).endswith("." + store.host_of(rec["url"])):
            errs.append(f"{where}: pricing_source_url host differs from the product host (use the product's own pricing page)")
    return errs


def check_jsonl(path: Path, required: tuple[str, ...]) -> list[str]:
    errs = []
    if not path.exists():
        return errs
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            errs.append(f"{path.name}:{n}: invalid JSON ({e})")
            continue
        missing = [k for k in required if k not in row]
        if missing:
            errs.append(f"{path.name}:{n}: missing {missing}")
        for p, s in strings_in(row):
            if s.startswith(FORMULA_START):
                errs.append(f"{path.name}:{n}: {p} starts with a spreadsheet formula character")
    return errs


def main() -> int:
    schema = store.read_json(store.SCHEMA / "record.schema.json")
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    tax = store.taxonomy()
    categories = {c["category"] for c in tax.get("categories", [])}

    errors: list[str] = []
    ids: dict[str, str] = {}
    keys: dict[str, str] = {}
    counts = {}
    all_recs = {}
    for state in store.STATES:
        d = store.DATA / state
        files = sorted(d.glob("*.json")) if d.exists() else []
        counts[state] = len(files)
        for f in files:
            try:
                rec = store.read_json(f)
            except json.JSONDecodeError as e:
                errors.append(f"{state}/{f.name}: invalid JSON ({e})")
                continue
            errs = check_record(rec, state, f.name, validator, categories)
            errors.extend(errs)
            rid = rec.get("id", f.stem)
            if rid in ids:
                errors.append(f"{state}/{f.name}: id '{rid}' also exists in {ids[rid]}")
            ids[rid] = state
            all_recs[rid] = rec
            for k in rec.get("dedupe_keys", []):
                if k in keys and keys[k] != rid:
                    errors.append(f"{state}/{f.name}: dedupe key '{k}' collides with '{keys[k]}'")
                keys.setdefault(k, rid)

    for rid, rec in all_recs.items():
        if rec.get("parent_id") and rec["parent_id"] not in all_recs:
            errors.append(f"{ids[rid]}/{rid}.json: parent_id '{rec['parent_id']}' does not exist")

    errors += check_jsonl(store.DATA / "leads.jsonl", ("key", "name", "url", "status", "added_at"))
    errors += check_jsonl(store.DATA / "rejected.jsonl", ("id", "dedupe_keys", "name", "url", "reason", "decided_at"))
    errors += check_jsonl(store.DATA / "decisions_applied.jsonl", ("record_id", "decision", "applied_at"))

    summary = {"ok": not errors, "counts": counts, "error_count": len(errors), "errors": errors[:200]}
    if "--json" in sys.argv:
        print(json.dumps(summary, indent=2))
    else:
        print(f"records: {counts}")
        for e in errors[:200]:
            print("ERROR", e)
        print("OK" if not errors else f"{len(errors)} error(s)")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
