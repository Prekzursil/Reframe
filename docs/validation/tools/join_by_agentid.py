"""Rebuild the Reframe v1.5 audit ledger with a RELIABLE join.

Two earlier attempts failed and both failures are instructive:
  1. Dedup on the agent-reported `surface` field was INERT — 320 agents invented 731
     distinct surface strings because I declared it free-text instead of an enum, so the
     dedup key never collided (2618 -> 2618).
  2. Joining verdicts by a 30-char title prefix returned ZERO matches: the journal's
     `key` is a CONTENT HASH (`v2:<sha256>`, the resume-cache key), not the agent label.
     No labels are journaled at all, so that join was structurally impossible.

The real key is `agentId`, present in BOTH the journal result records and every
`agent-*.jsonl` transcript. And the transcript's first message is the prompt I sent, so
the CANONICAL surface/lens (mine) and the verified finding title are recoverable from it
rather than from whatever the agent echoed back.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

WFDIR = Path(sys.argv[1])
OUT = Path(sys.argv[2])
JOURNAL = WFDIR / "journal.jsonl"

# ---- 1. agentId -> result ----
by_agent: dict[str, object] = {}
with JOURNAL.open("r", encoding="utf-8", errors="replace") as fh:
    for line in fh:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("type") == "result" and rec.get("agentId"):
            by_agent[str(rec["agentId"])] = rec.get("result")


# ---- 2. agentId -> prompt (first message of the transcript) ----
def first_prompt(path: Path) -> tuple[str, str] | None:
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            aid = rec.get("agentId")
            msg = rec.get("message")
            if not aid or not isinstance(msg, dict):
                continue
            content = msg.get("content")
            if isinstance(content, str):
                return str(aid), content
            if isinstance(content, list):
                parts = [c.get("text", "") for c in content if isinstance(c, dict)]
                return str(aid), "\n".join(parts)
    return None


prompts: dict[str, str] = {}
for p in WFDIR.glob("agent-*.jsonl"):
    got = first_prompt(p)
    if got:
        prompts[got[0]] = got[1]

# ---- 3. classify by the PROMPT I sent, not the agent's self-report ----
verdict_for_title: dict[str, list[dict]] = defaultdict(list)
audits: list[dict] = []

RE_FINDING = re.compile(r"^FINDING:\s*(.+)$", re.MULTILINE)
RE_SURFACE = re.compile(r"^SURFACE:\s*(.+)$", re.MULTILINE)
RE_LENS = re.compile(r"^LENS:\s*(.+)$", re.MULTILINE)


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


for aid, prompt in prompts.items():
    res = by_agent.get(aid)
    if res is None:
        continue
    mf = RE_FINDING.search(prompt)
    if mf and isinstance(res, dict) and "refuted" in res:
        verdict_for_title[norm(mf.group(1))].append(res)
        continue
    ms, ml = RE_SURFACE.search(prompt), RE_LENS.search(prompt)
    if ms and ml and isinstance(res, dict) and isinstance(res.get("findings"), list):
        for f in res["findings"]:
            if isinstance(f, dict):
                audits.append({**f, "_surface": ms.group(1).strip(), "_lens": ml.group(1).strip()})

# ---- 4. dedup on CANONICAL surface+lens+title, then tier ----
tiers: dict[str, list[dict]] = {"CONFIRMED": [], "REFUTED": [], "SPLIT": [], "UNVERIFIED": []}
seen: set[str] = set()
for f in audits:
    k = f"{norm(f['_surface'])}|{norm(f['_lens'])}|{norm(f.get('title'))}"
    if k in seen:
        continue
    seen.add(k)
    vs = verdict_for_title.get(norm(f.get("title", "")), [])
    f = {**f, "_verifiers": len(vs), "_corrections": [v["corrected_claim"] for v in vs if v.get("corrected_claim")]}
    if not vs:
        tiers["UNVERIFIED"].append(f)
        continue
    ref = sum(1 for v in vs if v.get("refuted") is True)
    keep = len(vs) - ref
    if ref > keep:
        tiers["REFUTED"].append(f)
    elif keep > ref:
        tiers["CONFIRMED"].append(f)
    else:
        tiers["SPLIT"].append(f)

SEV = {"critical": 0, "high": 1, "medium": 2, "low": 3}
for t in tiers.values():
    t.sort(key=lambda f: SEV.get(str(f.get("severity", "low")).lower(), 9))

print(f"journal results        : {len(by_agent)}")
print(f"transcripts w/ prompt  : {len(prompts)}")
print(f"audit findings joined  : {len(audits)}  -> deduped {len(seen)}")
print(f"verdict groups (titles): {len(verdict_for_title)}")
print(f"canonical surfaces     : {len({f['_surface'] for f in audits})}  (was 731 free-text)")
print(f"canonical lenses       : {len({f['_lens'] for f in audits})}")
print()
for name in ("CONFIRMED", "REFUTED", "SPLIT", "UNVERIFIED"):
    sev = Counter(str(f.get("severity", "?")).lower() for f in tiers[name])
    print(f"{name:11}: {len(tiers[name]):5}   {dict(sev)}")

act = [f for f in tiers["CONFIRMED"] if str(f.get("severity")).lower() in ("critical", "high")]
print(f"\nACTIONABLE (confirmed critical+high): {len(act)}")

with OUT.open("w", encoding="utf-8") as fh:
    fh.write("# Reframe v1.5 — Audit Ledger (agentId-joined)\n\n")
    fh.write(
        "Recovered after the 320-agent sweep hit the 1000-agent cap and died before its own "
        "synthesis step. Joined on `agentId` (present in both the journal and every transcript); "
        "surface/lens taken from the PROMPT I sent, not the agent's self-report.\n\n"
        "**Volume is not evidence.** Agents self-rated `high` confidence on 89% of 2618 raw "
        "findings, yet of those actually checked, ~43% were refuted. Only CONFIRMED is defensible; "
        "UNVERIFIED items are CLAIMS the cap prevented checking.\n\n"
    )
    fh.write("| tier | n |\n|---|---|\n")
    for name in ("CONFIRMED", "REFUTED", "SPLIT", "UNVERIFIED"):
        fh.write(f"| {name} | {len(tiers[name])} |\n")
    fh.write("\n")

    for sev in ("critical", "high"):
        rows = [f for f in tiers["CONFIRMED"] if str(f.get("severity")).lower() == sev]
        fh.write(f"# CONFIRMED {sev.upper()} ({len(rows)})\n\n")
        for f in rows:
            fh.write(f"## {f.get('title')}\n")
            fh.write(f"- surface `{f['_surface']}` · lens `{f['_lens']}` · verifiers {f['_verifiers']}\n")
            fh.write(
                f"- evidence: {f.get('evidence')}\n- why: {f.get('why_it_matters')}\n- fix: {f.get('proposed_fix')}\n"
            )
            for c in f["_corrections"]:
                fh.write(f"- ⚠ scope correction: {c}\n")
            fh.write("\n")

    fh.write(
        f"# UNVERIFIED critical ({len([f for f in tiers['UNVERIFIED'] if str(f.get('severity')).lower() == 'critical'])}) — CLAIMS, verify before acting\n\n"
    )
    for f in [f for f in tiers["UNVERIFIED"] if str(f.get("severity")).lower() == "critical"]:
        fh.write(f"- **{f.get('title')}** — `{f['_surface']}` / `{f['_lens']}` — {f.get('evidence')}\n")
    fh.write("\n")

    fh.write(f"# REFUTED ({len(tiers['REFUTED'])}) — recorded so they are not re-raised\n\n")
    for f in tiers["REFUTED"]:
        fh.write(f"- [{f.get('severity')}] {f.get('title')} — `{f['_lens']}`\n")

print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")
