#!/usr/bin/env python3
"""One-time migration: 2026-09 seed audit -> schema v1 files.

Inputs (not committed; produced by the seed research workflows):
  --audit      resources.json from the 58-site audit (records + synthesis + corrections)
  --idmap      old id (s01..s58) -> slug id
  --migration  output of the portfolio re-lens / lead triage workflow
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import store  # noqa: E402

SEED_DATE = "2026-09-14"
PARENTS = {"s45": "s46", "s33": "s53"}  # FeralUI Gradient Builder -> FeralUI, Refero Styles -> Refero
DEPERSONALIZE = [
    ("absence from the user's full list", "absence from the original list"),
    ("the user's full list", "the original list"),
    ("when the user is not", "when the visitor is not"),
    ("the user's exact stack", "a React + Tailwind + Motion stack"),
    ("the user's stack", "a React/Next.js stack"),
    ("the user's", "a builder's"),
    ("the user", "a builder"),
]
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def scrub(obj):
    if isinstance(obj, str):
        s = obj
        for a, b in DEPERSONALIZE:
            s = s.replace(a, b).replace(a.capitalize(), b.capitalize())
        while s.startswith(FORMULA_START):
            s = s[1:].lstrip()
        return s
    if isinstance(obj, list):
        return [scrub(x) for x in obj]
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items()}
    return obj


def https(url: str) -> str:
    return url if url.startswith("https://") else "https://" + url.split("://", 1)[-1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", required=True)
    ap.add_argument("--idmap", required=True)
    ap.add_argument("--migration", required=True)
    a = ap.parse_args()

    audit = json.loads(Path(a.audit).read_text())
    idmap = json.loads(Path(a.idmap).read_text())
    mig = json.loads(Path(a.migration).read_text())
    assign = {x["id"]: x for x in audit["synthesis"]["assignments"]}
    relens = {x["old_id"]: x for x in mig["relens"]}
    cal = {x["old_id"]: x for x in mig["calibration"]["records"]}

    records = {}
    for r in audit["records"]:
        old = r["id"]
        new = idmap[old]
        rl, cb, asg = relens[old], cal[old], assign[old]
        url = https(r["final_url"] or r["input_url"])
        parent = idmap[PARENTS[old]] if old in PARENTS else None
        ident = rl["identity"]
        if parent:  # a sub-page: identity is host + path, never the bare parent host
            path = urlparse(url).path.strip("/").lower()
            keys = [f"host:{store.host_of(url)}/{path}" if path else f"host:{store.host_of(url)}"]
        else:
            keys = store.url_keys(url) + store.url_keys(r["input_url"])
            keys += [f"host:{h.lower().removeprefix('www.')}" for h in ident["other_hosts"]]
            keys += [f"github:{g.lower()}" for g in ident["github_repos"]]
            keys += [f"npm:{p.lower()}" for p in ident["npm_packages"]]
        keys.append(store.name_key(r["name"]))
        rec = {
            "id": new, "name": r["name"], "url": url,
            "status": "dead" if r["site_status"] == "down" else "active",
            "origin": "seed-2026-09", "added_at": SEED_DATE, "last_verified_at": SEED_DATE,
            "one_liner": r["one_liner"], "what_it_offers": r["what_it_offers"], "resource_type": r["resource_type"],
            "tags": r["tags"][:15], "output_type": r["output_type"], "tech_stack": r["tech_stack"],
            "skill_level": r["skill_level"], "design_stages": r["design_stages"],
            "portfolio_fit": cb["portfolio_fit"], "portfolio_fit_reason": rl["portfolio_fit_reason"],
            "portfolio_jobs": rl["portfolio_jobs"][:3], "client_ok": rl["client_ok"], "client_ok_note": rl["client_ok_note"],
            "best_use_for_portfolio": rl["best_use_for_portfolio"],
            "category": asg["category"], "subcategory": asg["subcategory"],
            "tier": cb["tier"], "tier_reason": cb["tier_reason"],
            "overlap_group": asg["overlap_group"], "pick_over_overlaps": asg["pick_over_overlaps"],
            "website_design_score": r["website_design_score"], "score_rationale": rl["score_rationale"],
            "pricing_model": r["pricing_model"], "billing_type": r["billing_type"], "free_tier": r["free_tier"],
            "paid_entry_usd_month": r["paid_entry_usd_month"], "paid_entry_label": r["paid_entry_label"],
            "paid_top_label": r["paid_top_label"], "one_time_usd": r["one_time_usd"],
            "pricing_source_url": r["pricing_source_url"], "pricing_quote": None, "pricing_fetched_at": None,
            "commercial_use_license": r["commercial_use_license"], "license_quote": None,
            "signup_required": r["signup_required"],
            "agent_friendly": r["agent_friendly"], "maintenance_signal": r["maintenance_signal"], "caveats": r["caveats"],
            "confidence": r["confidence"], "fact_checked": bool(r.get("verified")),
            "unverified_fields": r["unverified_fields"], "evidence_urls": [https(u) for u in r["evidence_urls"]][:30],
            "aliases": [old] + [n for n in ident["former_names"] if n],
            "dedupe_keys": list(dict.fromkeys(keys)), "parent_id": parent,
            "comparables": r.get("similar_sites_outside_list", [])[:5], "user_notes": "",
        }
        records[new] = scrub(rec)

    # Resolve dedupe-key collisions: a key stays with the record whose own URL implies it.
    owner = {}
    for rid, rec in records.items():
        for k in rec["dedupe_keys"]:
            owner.setdefault(k, []).append(rid)
    for k, rids in owner.items():
        if len(rids) < 2:
            continue
        natural = [rid for rid in rids if k in store.url_keys(records[rid]["url"])] or rids[:1]
        for rid in rids:
            if rid not in natural[:1]:
                records[rid]["dedupe_keys"].remove(k)
                print(f"collision {k}: dropped from {rid} (kept on {natural[0]})")

    for rec in records.values():
        store.save_record("resources", rec)

    # Leads: keep verdicts and drop reasons so dropped leads are never re-triaged.
    seed_leads = {L["key"]: L for L in json.loads(Path(a.migration).parent.joinpath("leads_seed.json").read_text())}
    rows = []
    for L in mig["leads"]:
        src = seed_leads.get(L["key"], {})
        dup = L["duplicate_of"] if L["duplicate_of"] in records else (idmap.get(L["duplicate_of"], "") if L["duplicate_of"] else "")
        status = "queued" if L["verdict"] == "keep" and not dup and not L["injection_suspected"] else "dropped"
        rows.append(scrub({
            "key": L["key"], "name": L["name"], "url": https(L["canonical_url"]), "kind": L["kind"],
            "one_liner": L["one_liner"], "portfolio_fit": L["portfolio_fit"], "status": status,
            "reason": ("duplicate of " + dup) if dup else L["reason"], "reachable": L["reachable"],
            "similar_to": src.get("similar_to", []), "source": "seed-research", "added_at": SEED_DATE,
            "attempts": 0, "last_triage_score": L["portfolio_fit"],
            "dedupe_keys": list(dict.fromkeys(store.url_keys(L["canonical_url"]) + store.url_keys(src.get("url", "")))),
            "injection_suspected": L["injection_suspected"],
        }))
    rows.sort(key=lambda x: (x["status"] != "queued", -x["portfolio_fit"], x["name"].lower()))
    store.write_jsonl(store.DATA / "leads.jsonl", rows)

    # Provenance: the seed fact-check log, re-keyed to slug ids.
    prov = [scrub({"record_id": idmap.get(c["id"], c["id"]), "field": c["field"], "first_pass": c["old"],
                   "corrected": c["new"], "evidence": c["evidence"]}) for c in audit["corrections"]]
    store.write_jsonl(store.DATA / "provenance" / "seed_fact_checks.jsonl", prov)
    store.write_json(store.DATA / "meta.json", {"schema_version": 1, "seeded_at": SEED_DATE,
                                               "seed_notes": "58 resources researched and independently fact-checked; portfolio fit calibrated across the set."})
    print(f"resources={len(records)} leads={len(rows)} queued={sum(r['status'] == 'queued' for r in rows)} provenance={len(prov)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
