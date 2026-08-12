"""Deterministic verifier for every load-bearing factual claim in the SSOT plan.

The plan itself lives in the disposable `.audit/` scratch tree and is deliberately
NOT tracked; the CLAIMS are what matter and they are all re-derived below from the
tree at HEAD, so this file stands alone.  ssot-allow: names the scratch input only.

Rationale (rules/common/fan-out-contract.md C4): the plan's claims are all
mechanically decidable — does this file exist, does this string appear, what
version literal is on this line. Handing that class of question to agent
judgement measured 86% accurate with 100% of errors in the dangerous direction.
So: check them in code, act only on what passes, and report every miss.

A claim that FAILS here is not "the plan is wrong" — it may be that the repo moved
since the plan was written. Either way the plan's edit must not be applied blind.

Usage:  python docs/validation/tools/verify_ssot_claims.py
Exit 0 if every claim resolved as predicted, 1 otherwise.
"""

from __future__ import annotations

import gzip
import json
import re
import subprocess
from pathlib import Path


def _find_root() -> Path:
    """Walk up to the repo root instead of assuming a fixed depth.

    This script was authored at `.audit/` (where `parent.parent` IS the root) and then
    moved to `docs/validation/tools/`, where the same expression resolves to
    `docs/validation/`. Every relative read then missed and it reported 26 of 36 claims
    as mismatched — a detector failing loudly in the wrong direction, blaming the repo
    for its own relocation. Anchor on markers that exist only at the root.
    """
    here = Path(__file__).resolve()
    for cand in (here.parent, *here.parents):
        if (cand / ".git").exists() and (cand / "app/package.json").is_file():
            return cand
    raise SystemExit(f"FAILED:ssot-verify cannot locate the repo root from {here}")


ROOT = _find_root()
results: list[tuple[str, bool, str]] = []


def read(rel: str) -> str | None:
    p = ROOT / rel
    if not p.is_file():
        return None
    return p.read_text(encoding="utf-8", errors="replace")


# Claim ids that describe a KNOWN-STALE doc the reconciliation has not corrected yet.
# They are reported but never fail the run: their "expected" value is the broken state,
# so a mismatch there means someone FIXED it — good news, not a regression. Delete an id
# from this set (and flip its expectation) as each is corrected.
OPEN_ITEMS = {
    "C1a",
    "C1b",
    "C5a",
    "C5b",
    "P1-corpus",
}

# RETIRED from OPEN_ITEMS, each with its expectation FLIPPED so the correction is now a
# permanent guard rather than a note:
#   C2b     — phase 3. The false clause was deleted (not merely moved); the check now
#             reads the ARCHIVED path, so it asserts CONTENT, not path existence. A
#             path-keyed retirement would have gone green on the `git mv` alone.
#   C9b     — DETECTOR ARTIFACT, not an open defect. "no keystore" is True whole-file
#             and False outside blockquotes: the only survivor is the correction note at
#             CONTRACTS.md:126 QUOTING the dead clause.
#   P2.11b  — same shape. "1.4.1" survives only inside the HTML comment at README.md:32-38
#             that explains why the asset table is version-agnostic.


def check(cid: str, predicted: bool, actual: bool, detail: str) -> None:
    """Record one claim. INVARIANT claims gate the exit code; OPEN ones only report."""
    agreed = predicted == actual
    kind = "OPEN" if cid in OPEN_ITEMS else "INV "
    if agreed:
        label = "still-open" if kind == "OPEN" else "holds"
    else:
        label = "NOW-FIXED (retire it from OPEN_ITEMS)" if kind == "OPEN" else "BROKEN"
    results.append((cid, agreed or kind == "OPEN", f"[{kind}] {label} :: {detail}"))


def count_occurrences(pattern: str, globs: tuple[str, ...]) -> tuple[int, int]:
    """(total occurrences, distinct files) over tracked files matching globs."""
    rx = re.compile(pattern, re.IGNORECASE)
    total = files = 0
    for g in globs:
        for p in ROOT.glob(g):
            if not p.is_file() or "node_modules" in p.parts or ".git" in p.parts:
                continue
            try:
                hits = len(rx.findall(p.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                continue
            if hits:
                total += hits
                files += 1
    return total, files


def git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", "--no-optional-locks", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=90,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


# ---------------------------------------------------------------- C1 SpeechBrain
pyproj = read("sidecar/pyproject.toml") or ""
has_110_literal = '"speechbrain==1.1.0"' in pyproj
# DETECTOR FIX (v2): the exact string "PINNED to 1.0.3" is NOT present — the comment
# wraps as `# ... PINNED\n# to 1.0.3 (GPU-validated ...)` at :64-65. A literal
# substring check reported the plan as wrong when the plan was right. Un-wrap comment
# continuations first: strip leading `#` + collapse whitespace.
_pyproj_flat = re.sub(r"\s+", " ", re.sub(r"(?m)^\s*#\s?", "", pyproj))
comment_says_103 = "PINNED to 1.0.3" in _pyproj_flat
check("C1a", True, has_110_literal, f'pyproject literal "speechbrain==1.1.0" present={has_110_literal}')
check("C1b", True, comment_says_103, f'pyproject comment "PINNED to 1.0.3" present={comment_says_103}')
c1_docs = [
    ("docs/WU-R1-MULTISPEAKER-ENGINE.md", "speechbrain==1.0.3"),
    ("docs/V1.2-FEATURES.md", "1.0.3"),
    ("docs/ROADMAP.md", "1.0.3"),
]
for rel, needle in c1_docs:
    body = read(rel)
    check(
        f"C1-doc:{Path(rel).name}",
        True,
        # INVARIANT (was OPEN): these three docs carried `speechbrain==1.0.3` while
        # pyproject pins 1.1.0 and two code sites are built for 1.1.0. Now corrected,
        # so assert the dead value STAYS gone.
        body is not None and needle not in body,
        f"{rel} no longer contains the dead {needle!r} = {body is not None and needle not in body}",
    )

# ---------------------------------------------------------- C2 coverage-thresholds
cov_exists = (ROOT / ".coverage-thresholds.json").is_file()
check("C2a", True, cov_exists, f".coverage-thresholds.json exists={cov_exists}")
# INVARIANT (was OPEN). Read the ARCHIVED path and assert the CONTENT. Keying this on
# the LIVE path would have flipped green the instant phase 3 ran `git mv` — laundering a
# false clause into a permanently-passing check with nobody having deleted it.
_AIPLAN = "docs/plans/_archive/ai-program/PLAN.md"
aiplan = read(_AIPLAN)
denial = aiplan is not None and "does NOT exist" in aiplan and "coverage-thresholds" in aiplan
check(
    "C2b",
    True,
    aiplan is not None and not denial,
    f"{_AIPLAN} present={aiplan is not None}; its "
    f'".coverage-thresholds.json does NOT exist" clause is gone={not denial}',
)
added_in = git("log", "--diff-filter=A", "--format=%h", "--", ".coverage-thresholds.json")
check(
    "C2c",
    True,
    added_in.startswith("e38d5d3a") or bool(added_in),
    f"added-in sha={added_in or '(none)'} (plan says e38d5d3a)",
)

# ------------------------------------------------------------------- C3 YuNet
yunet_n, yunet_files = count_occurrences(r"yunet", ("sidecar/**/*.py", "app/**/*.ts", "app/**/*.tsx", "docs/**/*.md"))
check(
    "C3",
    True,
    yunet_n > 0,
    f"YuNet occurrences={yunet_n} across {yunet_files} file(s) (plan: 357/47; audit doc claimed ZERO)",
)

# --------------------------------------------------------- C4 RPC registration
handlers_py_gone = not (ROOT / "sidecar/media_studio/handlers.py").is_file()
comp = read("sidecar/media_studio/handlers/composition.py") or ""
register_all_here = "def register_all" in comp
check("C4a", True, handlers_py_gone, f"sidecar/media_studio/handlers.py absent={handlers_py_gone}")
check("C4b", True, register_all_here, f"register_all in handlers/composition.py={register_all_here}")

# ------------------------------------------------------------------ C5 ViNet-S
vinet_dir = (ROOT / "sidecar/media_studio/features/_vinet_s").is_dir()
# DETECTOR FIX (v2): a raw count said 1 and the plan said 0. The single hit is
# `advisorMeta.test.ts:107`, where UNISAL is one alternative inside a model-name
# REGEX ALTERNATION — a mention, not an implementation (use-vs-mention, the recurring
# class). Exclude test files so this measures the SWAP, which is what C5 is about.
unisal_impl, _ = count_occurrences(
    r"unisal", ("sidecar/media_studio/**/*.py", "app/renderer/src/**/*.ts", "app/renderer/src/**/*.tsx")
)
unisal_tests, _ = count_occurrences(r"unisal", ("app/renderer/src/**/*.test.ts", "app/renderer/src/**/*.test.tsx"))
unisal_n = unisal_impl - unisal_tests
check("C5a", True, vinet_dir, f"features/_vinet_s/ on disk={vinet_dir}")
check(
    "C5b",
    True,
    unisal_n == 0,
    f"UNISAL implementation refs={unisal_n} (raw={unisal_impl}, of which {unisal_tests} are test-regex mentions) => swap not executed",
)

# ------------------------------------------------------------------ C6 oxlint
precommit = read(".pre-commit-config.yaml") or ""
m = re.search(r"oxlint.*?rev:\s*v?([0-9.]+)", precommit, re.S) or re.search(
    r"rev:\s*v?([0-9.]+)[^\n]*\n[^\n]*oxlint", precommit
)
oxlint_rev = m.group(1) if m else "?"
charter = read("QUALITY-CHARTER.md") or ""
charter_ox = re.search(r"oxlint\s+([0-9.]+)", charter)
charter_ver = charter_ox.group(1) if charter_ox else "?"
check(
    "C6a",
    True,
    oxlint_rev == charter_ver,
    f"pre-commit oxlint={oxlint_rev} == charter {charter_ver} — the charter must not document a version nothing runs",
)
pkg_has_oxlint = any(
    "oxlint" in (read(p) or "") for p in ("app/package.json", "app/render-cli/package.json", "package.json")
)
check("C6b", True, not pkg_has_oxlint, f"oxlint absent from every tracked package.json={not pkg_has_oxlint}")

# --------------------------------------------------------------- C7 torch pins
reqs = read("sidecar/runtime_setup/requirements-chatterbox.txt") or ""
cbpy = read("sidecar/media_studio/features/tts/chatterbox.py") or ""
req_torch = re.findall(r"^torch==([^\s]+)", reqs, re.M)
py_torch = re.findall(r'"torch==([^"]+)"', cbpy)
check(
    "C7",
    True,
    bool(req_torch) and bool(py_torch) and req_torch[0] == py_torch[0],
    f"requirements torch={req_torch or '-'} == chatterbox.py torch={py_torch or '-'} — manager.py:617 compares these lists; a mismatch re-downloads ~7.5 GB",
)

# ------------------------------------------------------------------ C8 palette
# INVARIANT (was two OPEN items, `C8:--surface-deep` and `C8:--text-muted`). Those
# two PINNED one wrong value each and asserted the doc still carried it — a guard that
# went green on the drift and would have gone green on ten more. `docs/INDEX.md` had
# meanwhile measured the real surface at NINE of sixteen and filed it as "phase-2 item
# 2.7, not done", so the count was known and unenforced. Generalised: a design doc may
# not print a colour value that `tokens.css` does not define, and may not bind a token
# NAME to a value `tokens.css` does not bind it to. Both directions are mechanically
# decidable, so neither is left to a reader's diff (fan-out-contract C4).
tokens = read("app/renderer/src/styles/tokens.css") or ""
# `#rrggbb` plus the FULL four-argument rgba form. The abbreviated `rgba(.14)` spelling
# `docs/design-system.md` uses for the accent washes names an ALPHA, not a colour, so
# requiring three numeric channels first is what keeps it out of the comparison.
COLOUR_RE = re.compile(r"#[0-9a-fA-F]{6}\b|rgba?\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*(?:,[^)]*)?\)")
# `--token` followed by a hex within a dozen characters — the table-cell (`| `--x` |
# `#hex` |`) and the prose (``--x` `#hex``) spellings both fit, and nothing else does.
BINDING_RE = re.compile(r"(--[a-z][a-z0-9-]*)`?[^#\n]{0,12}(#[0-9a-fA-F]{6})\b")
DESIGN_DOCS = ("docs/design-system.md", "docs/build/DESIGN-DIRECTION.md")


def _norm_colour(s: str) -> str:
    """Whitespace-, case- and leading-zero-insensitive form of one colour literal.

    `rgba(255,255,255,.09)` and `rgba(255, 255, 255, 0.09)` are the same colour written
    two ways; a raw string compare would report the doc as drifted for a formatting
    difference and burn the reader's trust on a non-finding.
    """
    return re.sub(r"(?<=[(,])0(?=\.)", "", re.sub(r"\s+", "", s).lower())


def _live_text(body: str) -> str:
    """Drop blockquote lines — a `>` block is where a retraction QUOTES the dead value.

    Same treatment, and the same reason, as C9b: without it the guard fires on the
    correction note that records what the value used to be, so writing the retraction
    down would be punished and deleting it silently rewarded. Known limit, stated rather
    than hidden: a live wrong claim parked inside a blockquote is invisible to this check.
    Settling experiment: move one dead hex out of the `>` block and confirm C8-colour
    goes red.
    """
    return re.sub(r"(?m)^\s*>.*$", "", body)


_token_colours = {_norm_colour(m) for m in COLOUR_RE.findall(tokens)}
for _rel in DESIGN_DOCS:
    _raw = read(_rel)
    _body = None if _raw is None else _live_text(_raw)
    _dead = sorted({m for m in COLOUR_RE.findall(_body or "") if _norm_colour(m) not in _token_colours})
    check(
        f"C8-colour:{Path(_rel).name}",
        True,
        _body is not None and not _dead,
        f"{_rel} states {len(_dead)} colour value(s) tokens.css does not define: {_dead or 'none'}",
    )
    _unbound = sorted(
        {
            f"{name}={hexval}"
            for name, hexval in BINDING_RE.findall(_body or "")
            if not re.search(rf"{re.escape(name)}:\s*{re.escape(hexval)}\b", tokens, re.IGNORECASE)
        }
    )
    check(
        f"C8-binding:{Path(_rel).name}",
        True,
        _body is not None and not _unbound,
        f"{_rel} binds {len(_unbound)} token name(s) to a value tokens.css does not: {_unbound or 'none'}",
    )

# ---------------------------------------------------- C9 keystore / consent gate
C9_FILES = [
    "app/main/keystore.ts",
    "sidecar/media_studio/models/consent.py",
    "sidecar/media_studio/models/spend_ledger.py",
    "app/renderer/src/components/ConsentToggle.tsx",
]
missing9 = [f for f in C9_FILES if not (ROOT / f).is_file()]
check("C9a", True, not missing9, f"all 4 keystore/consent files present (missing: {missing9 or 'none'})")
contracts = read("CONTRACTS.md") or ""
# DETECTOR FIX (v3) + INVARIANT (was OPEN): a whole-file substring says "no keystore" is
# STILL there, contradicting the code and PR #324. It is — at :126, inside a blockquote
# that reads `> **Corrected.** This clause used to read "no keystore, no consent
# framework"`. Reading the document instead of the LIVE TEXT is the same use-vs-mention
# error as C5b/P2.8. Strip blockquote lines, then ask whether the dead clause survives.
_contracts_noquote = re.sub(r"(?m)^\s*>.*$", "", contracts)
_dead_clause = "no keystore" in _contracts_noquote or "no consent framework" in _contracts_noquote
check(
    "C9b",
    True,
    not _dead_clause,
    f"CONTRACTS.md dead 'no keystore'/'no consent framework' clause gone outside blockquotes="
    f"{not _dead_clause} (whole-file mentions={contracts.count('no keystore')}, all in the correction note)",
)

# --------------------------------------------------------------- C10 test runner
jest_n, jest_files = count_occurrences(
    r"\bjest\b", ("app/package.json", "app/render-cli/package.json", "package.json", ".github/workflows/*.yml")
)
apppkg = read("app/package.json") or ""
check("C10a", True, jest_n == 0, f"jest references in package/workflow files={jest_n} ({jest_files} file(s))")
check(
    "C10b",
    True,
    '"vitest run"' in apppkg,
    f'app/package.json declares "vitest run"={chr(34) + "vitest run" + chr(34) in apppkg}',
)

# ------------------------------------------------------------------- C11 B-roll
# INVARIANT (was OPEN, expectation flipped). The old check asserted the ROADMAP still
# called B-roll deferred; the engine had meanwhile shipped, so the guard was pinning the
# defect open. Bidirectional on purpose: C11a measures the CODE and C11b measures the
# DOC, so deleting the feature fails C11a instead of quietly making C11b true — a
# one-sided "the doc no longer says X" check passes just as well when both are gone.
roadmap = read("docs/ROADMAP.md") or ""
_BROLL_CODE = (
    "app/renderer/src/features/BrollPanel.tsx",
    "sidecar/media_studio/features/broll_ops.py",
    "sidecar/media_studio/features/broll_plan.py",
    "sidecar/media_studio/features/broll_compose.py",
    "sidecar/media_studio/features/broll_index.py",
)
_broll_missing = [f for f in _BROLL_CODE if not (ROOT / f).is_file()]
check("C11a", True, not _broll_missing, f"B-roll engine+UI on disk (missing: {_broll_missing or 'none'})")
# Read the not-yet-shipped SENTENCE, not the whole file: `docs/ROADMAP.md` legitimately
# discusses B-roll elsewhere, and a whole-file substring cannot tell the two apart —
# the use-vs-mention class this file has already been bitten by at C5b, C9b and P2.8.
# Two independent narrowings, because the first draft of this check went red on its own
# retraction: `_live_text` drops the `> **CORRECTED** …` block that names B-roll in order
# to record that it USED to be listed, and `[^.]` stops the window at the end of the
# sentence instead of running 240 characters into whatever follows the paragraph.
_flat_roadmap = re.sub(r"\s+", " ", _live_text(roadmap))
_m = re.search(r"yet shipped:([^.]{0,240})", _flat_roadmap)
_deferred_sentence = _m.group(1) if _m else ""
check(
    "C11b",
    True,
    bool(_deferred_sentence) and "B-roll" not in _deferred_sentence,
    f"docs/ROADMAP.md no longer lists B-roll as not-yet-shipped "
    f"(sentence found={bool(_deferred_sentence)}): {_deferred_sentence[:120]!r}",
)

# ------------------------------------------------------------------- C12 ledger
ledger = read("docs/validation/v15-audit-ledger.md") or ""
refuted_hdr = ledger.count("# REFUTED")
check("C12a", True, "225" in ledger, f"tracked ledger cites 225 checked={'225' in ledger}")
# INVARIANT (this WAS the C12b defect, now fixed): the ledger advertises a REFUTED
# tier of 94 at :27, and the only reason that row exists is so a refuted finding is not
# re-raised. It used to contain zero of them. Assert it keeps its own promise, with the
# exact 4-critical / 90-high split its own summary table claims.
_refuted = re.findall(r"(?m)^- \[(critical|high|medium|low)\] ", ledger)
_crit, _high = _refuted.count("critical"), _refuted.count("high")
check(
    "C12b",
    True,
    refuted_hdr == 1 and len(_refuted) == 94 and _crit == 4 and _high == 90,
    f"ledger REFUTED section present={refuted_hdr == 1}, entries={len(_refuted)}/94 "
    f"({_crit} critical, {_high} high) — must match the row advertised at :27",
)
# INVARIANT: the full unverified set must be TRACKED (not a path on one machine) and
# must actually decompress — a corrupt blob would be a silent sole-copy loss.
_gz = ROOT / "docs/validation/v15-audit-ledger-unverified.md.gz"
_gz_ok = False
if _gz.is_file():
    try:
        _gz_ok = len(gzip.decompress(_gz.read_bytes())) > 1_000_000
    except (OSError, EOFError, gzip.BadGzipFile):
        _gz_ok = False
check("C12c", True, _gz_ok, f"unverified ledger tracked + decompresses={_gz_ok} ({_gz.name})")
check(
    "C12d",
    True,
    "untracked full ledger" not in ledger,
    f"ledger no longer points at an 'untracked full ledger'={'untracked full ledger' not in ledger}",
)
# INVARIANT: the regeneration recipe must live OUTSIDE the disposable .audit/ tree, or
# `git clean -xfd` destroys the property that makes deleting the derived bytes safe.
_tools = [
    p
    for p in ("extract_ledger.py", "join_verdicts.py", "join_by_agentid.py")
    if (ROOT / "docs/validation/tools" / p).is_file()
]
check("C12e", True, len(_tools) == 3, f"ledger recovery tools tracked under docs/validation/tools/={len(_tools)}/3")
# INVARIANT: a brand-new agent-config file must not be silently dropped by .gitignore.
_probe = subprocess.run(
    ["git", "--no-optional-locks", "check-ignore", "-q", ".claude/commands/_ssot_probe.md"],
    cwd=ROOT,
    capture_output=True,
    text=True,
)
check("C0.2", True, _probe.returncode != 0, f"a NEW .claude/commands/*.md is trackable={_probe.returncode != 0}")

# ------------------------------------------------- Phase 2 spot checks (2.9-2.12)
seed_wrong = (ROOT / "docs/providers/CATALOG-SEED.md").is_file()  # ssot-allow: asserts ABSENCE
seed_right = (ROOT / "docs/plans/_archive/provider-hub/CATALOG-SEED.md").is_file()
check(
    "P2.9a",
    True,
    not seed_wrong,
    f"docs/providers/CATALOG-SEED.md absent={not seed_wrong}",  # ssot-allow: asserts ABSENCE
)
check("P2.9b", True, seed_right, f"docs/plans/_archive/provider-hub/CATALOG-SEED.md present={seed_right}")

appt = read("app/renderer/src/App.tsx") or ""
RAILS = ["library", "makeshorts", "edit", "caption", "export", "deliver", "director", "settings"]
rails_found = [r for r in RAILS if f"'{r}'" in appt or f'"{r}"' in appt]
check("P2.10a", True, len(rails_found) == 8, f"App.tsx names {len(rails_found)}/8 rails: {rails_found}")
setts = read("app/renderer/src/views/Settings.tsx") or ""
SUBTABS = ["models", "setup", "providers", "storage", "preferences", "health", "licenses", "presets"]
subs_found = [s for s in SUBTABS if f"'{s}'" in setts or f'"{s}"' in setts]
check("P2.10b", True, len(subs_found) == 8, f"Settings.tsx names {len(subs_found)}/8 sub-tabs: {subs_found}")

ver = json.loads(apppkg or "{}").get("version", "?")
readme = read("README.md") or ""
# DERIVED, not pinned (2026-08-10, at the 1.4.2 -> 1.5.0 bump). Both this check and P2.12
# below hardcoded "1.4.2", so a legitimate bump made two SSOT probes report a false
# failure — the checker itself was the drift. The durable invariant is not "the version is
# <literal>" but "the version is well-formed AND the CHANGELOG has a section for it".
check("P2.11a", True, bool(re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", ver)), f"app/package.json version={ver}")
# DETECTOR FIX (v3) + INVARIANT (was OPEN): "1.4.1" IS still in README.md — only inside
# the HTML comment at :32-38 that explains why the asset table is version-agnostic. The
# durable assertion is not "no 1.4.1 anywhere" (prose may legitimately discuss a version)
# but "the asset table names no hardcoded version at all", which is what actually goes
# stale on a bump. electron-builder.yml derives the name from app/package.json.
_readme_nocomment = re.sub(r"<!--.*?-->", "", readme, flags=re.S)
_agnostic = "media-studio-<version>-win-x64" in _readme_nocomment
_hardcoded = re.findall(r"media-studio-\d+\.\d+\.\d+-win-x64", _readme_nocomment)
check(
    "P2.11b",
    True,
    _agnostic and not _hardcoded,
    f"README asset table is version-agnostic={_agnostic}, hardcoded asset names outside "
    f"comments={_hardcoded or 'none'} (whole-file '1.4.1' mentions={readme.count('1.4.1')}, all in the comment)",
)
changelog = read("CHANGELOG.md") or ""
check(
    "P2.12",
    True,
    f"[{ver}]" in changelog,
    f"CHANGELOG has the [{ver}] section for the CURRENT app/package.json version={f'[{ver}]' in changelog}",
)

# INVARIANT: the corpus README may not hand-write how many claims THIS tool registers.
# It said "the 40 REGISTERED claims hold" while the tool registered a different number,
# and its own surrounding paragraph had already identified the fix — "adding checks that
# pin this corpus's own literals" — and deferred it. Same reasoning as `waivers-applied=`
# in `.quality/docs_check.py`: a number the run GENERATES cannot drift from the thing it
# counts, and a number a human retypes always eventually does. Deliberately NOT
# blockquote-stripped, unlike C8/C11: the stale literal lived inside a `>` block, so
# reusing that helper here would pass vacuously — the wrong control for this claim.
_readme_v15 = read("docs/plans/v1.5/README.md") or ""
_hardcoded_n = sorted(set(re.findall(r"(?i)(\d+)\s+registered claims", _readme_v15)))
check(
    "P3-readme-count",
    True,
    bool(_readme_v15) and not _hardcoded_n,
    # No count in this message ON PURPOSE. The obvious `len(results)` is evaluated where
    # this check sits, roughly two thirds down the file, so it printed 40 while the run
    # went on to report 45 — a stale hand-adjacent number inside the check whose whole
    # subject is stale hand-written numbers. The authoritative total is the `total=` line
    # the report prints at the end, and it is not worth duplicating here to say so.
    f"docs/plans/v1.5/README.md hand-writes this tool's claim count={_hardcoded_n or 'none'} "
    f"(authoritative count = the `total=` line this run ends with)",
)

rpcdoc = read("docs/rpc-contract-v2.md") or ""
check(
    "P2.6",
    True,
    "Not merged" not in rpcdoc,
    f'docs/rpc-contract-v2.md no longer claims "Not merged"={"Not merged" not in rpcdoc}',
)

pmeta = read("app/renderer/src/features/providerMeta.ts") or ""
# DETECTOR FIX (v2): a whole-file substring said cloudflare IS present, contradicting
# the plan. It is — at :33, inside a comment that says "Cloudflare Workers AI is
# intentionally OMITTED". Reading the document instead of the FIELD is the same
# use-vs-mention error as C5b. Strip // and /* */ comments, then ask whether it is a
# real ENTRY.
_pmeta_code = re.sub(r"/\*.*?\*/", "", re.sub(r"(?m)//.*$", "", pmeta), flags=re.S)
check(
    "P2.8",
    True,
    "cloudflare" not in _pmeta_code.lower(),
    f"providerMeta.ts has no cloudflare ENTRY={'cloudflare' not in _pmeta_code.lower()} "
    f"(whole-file mentions={pmeta.lower().count('cloudflare')}, all in comments)",
)

# ------------------------------------------- Phase 1: does the untracked corpus exist?
review_dir = Path.home() / ".reframe-review"
# Two lists, not one. The single 14-entry list asked `~/.reframe-review` for two entries
# spelled as REPO paths (`docs/_archive/2026-07/…`) — files that had since been PROMOTED
# into the tracked tree, which was the entire point of the reconciliation. They can never
# be found under the scratch dir, so the probe stuck at 12/14 forever; and because
# P1-corpus is an OPEN item, that permanent mismatch printed
# "NOW-FIXED (retire it from OPEN_ITEMS)" on every run. A detector that reports a fix
# nobody made, and invites the next reader to retire the item on that basis, is worse
# than no detector. Split so each half asserts the property that is actually durable.
P1_SCRATCH = [
    "reframe-v1.5-program.md",
    "reframe-redesign-direction.md",
    "reframe-redesign.html",
    "reframe-flagship-active-speaker-plan.md",
    "reframe-flagship-transcript-editing-plan.md",
    "reframe-flagship-auto-broll-plan.md",
    "reframe-flagship-lip-sync-dub-plan.md",
    "reframe-signed-release-ci-plan.md",
    "reframe-model-rehosting-dossier.md",
    "reframe-techprep-dossier.md",
    "reframe-trust-plan.md",
    "reframe-competitor-research.md",
]
# INVARIANT: promoted out of the scratch corpus and into the repo. Machine-independent,
# unlike the OPEN probe below, which can only ever speak for the box it runs on.
P1_PROMOTED = [
    "docs/_archive/2026-07/reframe-visual-audit.md",
    "docs/_archive/2026-07/reframe-reconcile-audit.md",
]
_tracked = set(git("ls-files", "--", "docs/_archive/2026-07").splitlines())
_unpromoted = [f for f in P1_PROMOTED if f not in _tracked]
check(
    "P1-promoted",
    True,
    not _unpromoted,
    f"{len(P1_PROMOTED) - len(_unpromoted)}/{len(P1_PROMOTED)} promoted audit docs are TRACKED "
    f"(missing: {_unpromoted or 'none'})",
)
present = [f for f in P1_SCRATCH if (review_dir / f).is_file()]
check(
    "P1-corpus",
    True,
    len(present) == len(P1_SCRATCH),
    f"{len(present)}/{len(P1_SCRATCH)} untracked authority files found in {review_dir} "
    f"(missing: {[f for f in P1_SCRATCH if f not in present] or 'none'})",
)
shell_audit = review_dir / "shell-audit"
pngs = len(list(shell_audit.glob("*.png"))) if shell_audit.is_dir() else 0
check("P1-shell", True, pngs >= 8, f"shell-audit PNG count={pngs} (plan: 8)")

# --------------------------------------------------------------------- report
print("=== SSOT CLAIM VERIFICATION ===")
bad = 0
for cid, ok, detail in results:
    if not ok:
        bad += 1
    print(f"  {'OK  ' if ok else 'MISS'} {cid:<26} {detail}")
print()
print(f"total={len(results)}  as-predicted={len(results) - bad}  mismatched={bad}")
print(
    "SUCCESS:ssot-verify all claims as predicted"
    if bad == 0
    else f"FAILED:ssot-verify {bad} claim(s) mismatched — do NOT apply those edits blind"
)
raise SystemExit(0 if bad == 0 else 1)
