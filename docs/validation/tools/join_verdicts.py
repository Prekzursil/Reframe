"""Join adversarial verdicts back onto findings and emit ONLY the defensible subset.

Why this exists: the raw recovery has 2618 findings, but of the 673 that were actually
verified before the agent cap killed the run, 291 were REFUTED (43%). Agents self-rated
`high` confidence on 89% of everything. So the raw list is claims, not defects.

The verify agents were labelled `verify:<first 30 chars of title>`, which is the only
join key available, so matching is by normalised title prefix. That is lossy in ONE
direction (a title-prefix collision could mis-attribute a verdict), so collisions are
counted and reported rather than hidden.

Output tiers:
  CONFIRMED  - >=2 of 3 verifiers declined to refute  (defensible)
  REFUTED    - >=2 of 3 refuted                        (drop, but record it)
  SPLIT      - verifiers disagreed 1-1 or partial      (needs a human read)
  UNVERIFIED - the cap hit before any verifier ran     (a CLAIM, explicitly not a defect)
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

JOURNAL = Path(sys.argv[1])
OUT = Path(sys.argv[2])


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


findings: list[dict] = []
verdicts: list[dict] = []
prose: list[tuple[str, str]] = []

with JOURNAL.open("r", encoding="utf-8", errors="replace") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("type") != "result":
            continue
        key, val = str(rec.get("key") or ""), rec.get("result")
        if isinstance(val, dict) and isinstance(val.get("findings"), list):
            for f in val["findings"]:
                if isinstance(f, dict):
                    findings.append(f)
        elif isinstance(val, dict) and "refuted" in val:
            verdicts.append({**val, "_key": key})
        elif isinstance(val, str) and len(val) > 400:
            prose.append((key, val))

# verify label was `verify:${title.slice(0,30)}`
by_prefix: dict[str, list[dict]] = defaultdict(list)
for v in verdicts:
    k = v["_key"]
    if k.startswith("verify:"):
        by_prefix[norm(k[len("verify:"):])].append(v)

# prefix-collision audit: how many findings share a 30-char title prefix?
prefix_owners: dict[str, set[str]] = defaultdict(set)
for f in findings:
    prefix_owners[norm(str(f.get("title", ""))[:30])].add(norm(str(f.get("title", ""))))
ambiguous = {p for p, owners in prefix_owners.items() if len(owners) > 1}

tiers: dict[str, list[dict]] = {"CONFIRMED": [], "REFUTED": [], "SPLIT": [], "UNVERIFIED": []}
seen: set[str] = set()
for f in findings:
    title = str(f.get("title", ""))
    k = f"{norm(f.get('lens'))}|{norm(title)}"   # lens+title: surface was free-text noise
    if k in seen:
        continue
    seen.add(k)
    vs = by_prefix.get(norm(title[:30]), [])
    f = dict(f)
    f["_verifiers"] = len(vs)
    f["_ambiguous_join"] = norm(title[:30]) in ambiguous
    f["_corrections"] = [v["corrected_claim"] for v in vs if v.get("corrected_claim")]
    if not vs:
        tiers["UNVERIFIED"].append(f)
        continue
    ref = sum(1 for v in vs if v.get("refuted") is True)
    keep = sum(1 for v in vs if v.get("refuted") is False)
    if ref >= 2 or (ref > keep and len(vs) < 2):
        tiers["REFUTED"].append(f)
    elif keep >= 2:
        tiers["CONFIRMED"].append(f)
    else:
        tiers["SPLIT"].append(f)

SEV = {"critical": 0, "high": 1, "medium": 2, "low": 3}
for t in tiers.values():
    t.sort(key=lambda f: SEV.get(str(f.get("severity", "low")).lower(), 9))

print(f"findings (lens+title deduped): {len(seen)}  (raw {len(findings)})")
print(f"title-prefix collisions       : {len(ambiguous)}  <- verdict joins here are UNRELIABLE")
for name in ("CONFIRMED", "REFUTED", "SPLIT", "UNVERIFIED"):
    rows = tiers[name]
    sev = Counter(str(f.get("severity", "?")).lower() for f in rows)
    print(f"{name:11}: {len(rows):5}   {dict(sev)}")

crit_conf = [f for f in tiers["CONFIRMED"] if str(f.get("severity")).lower() == "critical"]
high_conf = [f for f in tiers["CONFIRMED"] if str(f.get("severity")).lower() == "high"]
print(f"\nACTIONABLE = confirmed critical ({len(crit_conf)}) + confirmed high ({len(high_conf)})")

with OUT.open("w", encoding="utf-8") as fh:
    fh.write("# Reframe v1.5 — Audit Ledger (verdict-joined, honest tiers)\n\n")
    fh.write(
        "The 320-agent sweep produced **2618 raw findings**, but of the 673 that were "
        "adversarially checked before the run hit the 1000-agent cap, **291 were REFUTED "
        "(43%)** — while agents self-rated `high` confidence on 89% of everything. "
        "Volume is therefore NOT evidence. Only the CONFIRMED tier below is defensible.\n\n"
    )
    fh.write("## Tier counts\n\n| tier | meaning | n |\n|---|---|---|\n")
    fh.write(f"| CONFIRMED | >=2 of 3 verifiers declined to refute | {len(tiers['CONFIRMED'])} |\n")
    fh.write(f"| REFUTED | >=2 refuted — dropped, recorded | {len(tiers['REFUTED'])} |\n")
    fh.write(f"| SPLIT | verifiers disagreed — needs a human | {len(tiers['SPLIT'])} |\n")
    fh.write(f"| UNVERIFIED | cap hit first — a CLAIM, not a defect | {len(tiers['UNVERIFIED'])} |\n\n")
    fh.write(
        f"⚠️ **Join caveat:** verifiers were labelled by a 30-char title prefix, the only key "
        f"available. **{len(ambiguous)}** prefixes are shared by more than one finding, so those "
        f"verdict attributions are unreliable and are flagged per-item.\n\n"
    )

    fh.write("# ACTIONABLE — confirmed CRITICAL\n\n")
    for f in crit_conf:
        fh.write(f"## {f.get('title')}\n")
        fh.write(f"- lens `{f.get('lens')}` · surface `{f.get('surface')}` · verifiers {f['_verifiers']}")
        fh.write(" · ⚠️AMBIGUOUS JOIN\n" if f["_ambiguous_join"] else "\n")
        fh.write(f"- evidence: {f.get('evidence')}\n- why: {f.get('why_it_matters')}\n- fix: {f.get('proposed_fix')}\n")
        for c in f["_corrections"]:
            fh.write(f"- scope correction: {c}\n")
        fh.write("\n")

    fh.write("# ACTIONABLE — confirmed HIGH\n\n")
    for f in high_conf:
        fh.write(f"## {f.get('title')}\n")
        fh.write(f"- lens `{f.get('lens')}` · surface `{f.get('surface')}` · verifiers {f['_verifiers']}")
        fh.write(" · ⚠️AMBIGUOUS JOIN\n" if f["_ambiguous_join"] else "\n")
        fh.write(f"- evidence: {f.get('evidence')}\n- fix: {f.get('proposed_fix')}\n")
        for c in f["_corrections"]:
            fh.write(f"- scope correction: {c}\n")
        fh.write("\n")

    fh.write("# REFUTED (recorded, not deleted — do not re-raise)\n\n")
    for f in tiers["REFUTED"][:200]:
        fh.write(f"- [{f.get('severity')}] {f.get('title')} — lens `{f.get('lens')}`\n")
    fh.write(f"\n_(showing 200 of {len(tiers['REFUTED'])})_\n\n")

    fh.write("# GROUND + RECONCILE prose artifacts\n\n")
    for key, text in prose:
        fh.write(f"## {key}\n\n{text}\n\n---\n\n")

print(f"wrote {OUT} ({OUT.stat().st_size/1024:.0f} KB)")
