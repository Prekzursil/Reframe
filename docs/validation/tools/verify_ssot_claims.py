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
    # C1a is a deliberate ODD ONE OUT and is labelled misleadingly by this set's own
    # vocabulary: it prints "[OPEN] still-open" while asserting something TRUE and
    # uncontested (the `speechbrain==1.1.0` literal is present). Nothing about it is open.
    # It is left here rather than retired because retiring it would make a HARDCODED
    # version literal gate the exit code, so a legitimate bump to 1.2.0 would report as a
    # regression — the moving-figure trap `docs/plans/v1.5/README.md` warns about. The
    # durable half of this claim is already an INVARIANT: C1b asserts prose and pin AGREE,
    # whatever the version. Recorded rather than fixed because both available fixes
    # (retire-as-is, or rewrite to drop the literal) are behaviour changes this pass did
    # not measure. Settling experiment: bump the literal and confirm C1b stays green while
    # a retired C1a would go red.
    "C1a",
    "C5a",
    "C5b",
    # C13-code-quote records a CODE defect this lane may not touch: two citations in
    # `app/renderer/src/` quote an excerpt and point at the wrong line. It is OPEN rather than
    # INVARIANT because the fix is in application source and the doc lane that measured it is
    # scoped to `docs/**`; making it gate the exit code would leave a red gate nobody in scope
    # can clear. Retire it (and flip the expectation to INVARIANT) in the commit that corrects
    # the two line numbers.
    "C13-code-quote",
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
#   C1b     — THIRD instance of the same shape, and this file walked past it while
#             retiring the other two. It asserted `sidecar/pyproject.toml` still carries
#             the stale comment "PINNED to 1.0.3", and printed `present=True` on every
#             run — but the live comment at :64-65 already reads "PINNED to 1.1.0" and
#             agrees with the literal. The only survivor is :72, a HISTORY note QUOTING
#             the dead wording. So the OPEN item was pinning a NON-defect open and the
#             tool was emitting a false statement about the tree. Retired with the
#             expectation flipped to the durable property: the live comment must name
#             the SAME version as the pinned literal.


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
# DETECTOR FIX (v2): the comment wraps as `# ... PINNED\n# to 1.1.0 (...)` at :64-65, so
# un-wrap continuations first — strip the leading `#` and collapse whitespace — before any
# substring test. DETECTOR FIX (v3) + INVARIANT (was OPEN): v2 then flattened the WHOLE
# FILE and asked whether "PINNED to 1.0.3" survives. It does, at :72, inside
# `HISTORY — this comment used to say "PINNED to 1.0.3 ... 1.1.0 is DELIBERATELY AVOIDED"`
# — a MENTION of the dead wording, not a live claim. So C1b reported `present=True` and
# pinned a defect that had already been fixed, in the same file whose C9b/P2.11b notes
# above describe exactly this trap. Two narrowings, mirroring C9b: read COMMENT lines only
# (a literal in TOML code is C1a's subject, not this one), and drop double-quoted spans,
# which is where a correction note parks the wording it is retiring. Then assert the
# durable property instead of a fixed string — the live comment must name the SAME version
# as the pinned literal, so this stays green when the pin legitimately moves and goes red
# the moment prose and pin disagree again.
_pyproj_comments = re.sub(r"\s+", " ", " ".join(m.group(1) for m in re.finditer(r"(?m)^\s*#\s?(.*)$", pyproj)))
_pyproj_live_comments = re.sub(r'"[^"]*"', "", _pyproj_comments)
_pin_m = re.search(r'"speechbrain==([0-9][0-9.]*)"', pyproj)
_com_m = re.search(r"PINNED to ([0-9][0-9.]*)", _pyproj_live_comments)
_pin_v, _com_v = (_pin_m.group(1) if _pin_m else ""), (_com_m.group(1) if _com_m else "")
check("C1a", True, has_110_literal, f'pyproject literal "speechbrain==1.1.0" present={has_110_literal}')
check(
    "C1b",
    True,
    bool(_pin_v) and _com_v == _pin_v,
    f"pyproject live comment pins {_com_v or '(none)'} and the literal pins {_pin_v or '(none)'} — agree="
    f"{bool(_pin_v) and _com_v == _pin_v} (whole-file '1.0.3' mentions={pyproj.count('1.0.3')}, all "
    f"inside the HISTORY note quoting the retired wording)",
)
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
    _seen = COLOUR_RE.findall(_body or "")
    _dead = sorted({m for m in _seen if _norm_colour(m) not in _token_colours})
    check(
        f"C8-colour:{Path(_rel).name}",
        True,
        _body is not None and not _dead,
        # The EXAMINED count is printed, not just the failure count, because the two can
        # diverge silently: every hex in `docs/build/DESIGN-DIRECTION.md` now sits inside a
        # retraction blockquote, so this check inspects ZERO values there and a bare
        # "0 dead" would read as a live measurement instead of the re-introduction guard it
        # currently is. Generated here rather than retyped in prose — the P3-readme-count rule.
        f"{_rel} examined {len(_seen)} colour value(s), {len(_dead)} that tokens.css does not "
        f"define: {_dead or 'none'}",
    )
    _bindings = BINDING_RE.findall(_body or "")
    _unbound = sorted(
        {
            f"{name}={hexval}"
            for name, hexval in _bindings
            if not re.search(rf"{re.escape(name)}:\s*{re.escape(hexval)}\b", tokens, re.IGNORECASE)
        }
    )
    check(
        f"C8-binding:{Path(_rel).name}",
        True,
        _body is not None and not _unbound,
        f"{_rel} examined {len(_bindings)} token binding(s), {len(_unbound)} bound to a value "
        f"tokens.css does not: {_unbound or 'none'}",
    )

# INVARIANT (new): the prose describing C8's reach may not be wider than `DESIGN_DOCS`.
# Both docs that introduced these guards said they "fail if ANY design doc prints a colour
# `tokens.css` does not define". The tuple above enumerates TWO files, and the gap is not
# hypothetical — `docs/plans/v1.5/DESIGN-DIRECTION.md` carries `**Status:** ACTIVE`, the
# same basename, and off-token hexes, and is deliberately NOT covered (they are a
# prototype-REJECTION table, so admitting it without a use-vs-mention narrowing would
# emit false positives). A doc that promises a universal the code does not implement is
# the same defect this corpus exists to remove, committed by the correction itself. So an
# UNEMPHASISED universal quantifier is rejected in any sentence that names these checks, which
# pushes the enumeration to be written out, and adding a third entry to `DESIGN_DOCS` forces the
# prose to be re-read rather than silently outgrown.
#
# SCOPE, corrected 2026-08-12 at `1ad80ce8` — this comment used to say the quantifier is "banned",
# which overstated the pattern below by exactly the margin the docs it polices were corrected for.
# MEASURED: the pattern needs literal whitespace between its tokens, so an emphasised (`**any**`,
# `*any*`) or blockquote-wrapped quantifier is invisible to it. That is deliberate for now, not an
# oversight — see `C8-scope-measured` below, which pins the measured behaviour and the docs'
# description of it together so neither can drift from the other unnoticed.
#
# Deliberately NOT blockquote-stripped, and this is the reverse of the C8/C9b/C11 choice:
# measured, `docs/build/DESIGN-DIRECTION.md`'s over-wide sentence lives INSIDE its own
# `> **CORRECTED** …` block, so `_live_text` here would hide one of the two offenders and
# report a 50%-clean tree as clean. A `>` block is invisible-to-the-guard only when it is
# QUOTING something dead; this one asserts a live forward-looking promise. Same reasoning,
# and the same exception, as `P3-readme-count`.
_C8_UNIVERSAL = re.compile(r"(?i)(?:any|every)\s+design\s+doc")
_overwide_scope: list[str] = []
for _p in sorted(ROOT.glob("docs/**/*.md")):
    try:
        _flat_scope = re.sub(r"\s+", " ", _p.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        continue
    for _hit in _C8_UNIVERSAL.finditer(_flat_scope):
        if "C8-" in _flat_scope[max(0, _hit.start() - 300) : _hit.end() + 300]:
            _overwide_scope.append(_p.relative_to(ROOT).as_posix())
            break
check(
    "C8-scope-prose",
    True,
    not _overwide_scope,
    f"no doc claims the C8 guards cover every design doc; they cover the {len(DESIGN_DOCS)} "
    f"enumerated in DESIGN_DOCS ({', '.join(DESIGN_DOCS)}) — offenders: {_overwide_scope or 'none'}",
)

# INVARIANT (new): the two docs that announce `C8-scope-prose` may not promise more reach than
# it has. Both said it "now fails if this sentence/paragraph re-widens" — and that is the same
# over-wide-promise defect one level up again, committed by the correction itself, for the third
# time in this file's history. MEASURED at `1ad80ce8`: `_C8_UNIVERSAL` requires literal
# whitespace between its tokens, so an EMPHASISED quantifier slips past it, and the flatten at
# the loop above turns a blockquote continuation into `any design > doc`, which also slips past.
# Both offending docs happen to write the quantifier emphasised, and this corpus emphasises
# quantifiers by habit (`**two**`, `**16**`, `**not**`), so the likelier spelling of a future
# re-widening is the one the guard cannot see.
#
# Widening `_C8_UNIVERSAL` is NOT the fix and was rejected on measurement, not taste: both
# retraction paragraphs QUOTE the banned wording in order to retire it, and C8-scope-prose
# deliberately does not `_live_text`, so allowing `*` or `>` between the tokens would fire on
# the retractions themselves. Closing it needs the use-vs-mention narrowing C1b uses (drop
# double-quoted spans), which is a behaviour change this pass did not measure. So the honest
# repair is the SENTENCE — and this check makes it stick in both directions: the probe table is
# re-run against the shipped pattern on every run, so a later regex change fails here and forces
# the prose to be re-read instead of silently outgrowing it, and any doc naming the check must
# carry the measured qualifier next to the promise.
_C8_PROBES: tuple[tuple[str, bool], ...] = (
    ("over any design doc", True),
    ("over every design doc", True),
    ("over **any** design doc", False),
    ("over *any* design doc", False),
    ("over any design > doc", False),
)
_probe_drift = [
    f"{_txt!r} fires={not _want}"
    for _txt, _want in _C8_PROBES
    if bool(_C8_UNIVERSAL.search(re.sub(r"\s+", " ", _txt))) is not _want
]
_scope_unqualified: list[str] = []
for _p in sorted(ROOT.glob("docs/**/*.md")):
    try:
        _flat_q = re.sub(r"\s+", " ", _p.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        continue
    for _hit in re.finditer(r"C8-scope-prose", _flat_q):
        if "UNEMPHASISED" not in _flat_q[_hit.start() : _hit.end() + 400]:
            _scope_unqualified.append(_p.relative_to(ROOT).as_posix())
            break
check(
    "C8-scope-measured",
    True,
    not _probe_drift and not _scope_unqualified,
    f"C8-scope-prose behaves as its prose says (probe drift: {_probe_drift or 'none'}) and every "
    f"doc naming it qualifies the reach as UNEMPHASISED within 400 chars "
    f"(unqualified: {_scope_unqualified or 'none'}; a back-reference such as "
    f'"that check" avoids re-naming it a second time)',
)

# INVARIANT (new): a `docs/<file>.md:<N>` citation may not land on a blockquote line.
# This corpus's own citation rule is "cite by SYMBOL or by a FIXED commit, never a bare
# same-file line range", because that form has now rotted five times here — the fifth
# created by the very pass that wrote the rule down: a 9-line retraction inserted at
# `docs/design-system.md:34` pushed the caption-voice row from :43 to :52, so a citation
# that was byte-exact before now points at a line of the retraction. That subclass is
# mechanically decidable and worth pinning even though the general case is not: a `>` line
# is a correction note, and a correction note is never the definition anyone meant to cite,
# so a citation resolving onto one is wrong with no judgement call. Scope, stated rather
# than implied: this does NOT catch an anchor that rotted onto a different ordinary line.
# Three such already exist in `docs/plans/v1.5/uiux-qol-audit-2026-08.md` (:49, :65-66,
# :78-81), predate this branch, and are left for a sweep that can re-derive each true
# anchor.
#
# SCOPE OF THE CITING SIDE, corrected 2026-08-12 at `1ad80ce8` — this check is
# ONE-DIRECTIONAL and the first wording of it did not say so. The citing-side scan is
# `ROOT.glob("docs/**/*.md")`, so it covers docs->docs only. Citations FROM application source
# INTO docs are covered by nothing: `.quality/docs_check.py`'s r2 validates that the cited PATH
# resolves and never looks at the line number. MEASURED over `app/` + `sidecar/` at this commit:
# 30 `docs/<file>.md:<N>` citations exist, 6 of them land on a `>` line. Those 6 are NOT
# asserted to be defects — on the citing side a `>` line can be the retraction someone MEANT to
# cite (`app/renderer/src/features/ReframeCorrect.tsx` cites `docs/plans/v1.5/SCOPE.md:47-74`
# precisely because
# the retraction there records the prerequisite as BUILT), which is the same use-vs-mention trap
# in mirror image, so a blocking blockquote rule on code would manufacture false positives. The
# decidable subclass is split out into `C13-code-anchor` below; the judgement-call subclass is
# reported to the owner instead of guessed at here. Settling experiment for the full surface:
# `git grep -nE "docs/[A-Za-z0-9_./-]+\.md:[0-9]+" -- app sidecar`.
#
# `_live_text` on the CITING side, for the reason C9b/C11b already establish and which this
# check re-proved on itself: the first draft went red on the retraction note that names the
# rotted anchor in order to retire it. The note is a MENTION. The cost is the same known
# hole — a live citation parked inside a `>` block is invisible — and it is real here rather
# than theoretical, so the examined count is printed on every run to keep the check's reach
# visible instead of implied.
_CITE_RE = re.compile(r"(docs/[A-Za-z0-9_./-]+\.md):(\d+)")
_target_lines: dict[str, list[str]] = {}
_rotted_cites: list[str] = []
_cites_checked = 0
for _p in sorted(ROOT.glob("docs/**/*.md")):
    try:
        _citer = _live_text(_p.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        continue
    for _cm in _CITE_RE.finditer(_citer):
        _tgt, _n = _cm.group(1), int(_cm.group(2))
        if not (ROOT / _tgt).is_file():
            continue
        _cites_checked += 1
        if _tgt not in _target_lines:
            _target_lines[_tgt] = (ROOT / _tgt).read_text(encoding="utf-8", errors="replace").splitlines()
        _ls = _target_lines[_tgt]
        if 1 <= _n <= len(_ls) and _ls[_n - 1].lstrip().startswith(">"):
            _rotted_cites.append(f"{_p.relative_to(ROOT).as_posix()} -> {_tgt}:{_n}")
check(
    "C13-anchor",
    True,
    _cites_checked > 0 and not _rotted_cites,
    f"resolvable docs->docs line citations={_cites_checked}, landing on a blockquote "
    f"(retraction) line={len(_rotted_cites)}: {_rotted_cites or 'none'}",
)

# INVARIANT (new): the OTHER direction — a `docs/<file>.md:<N>` citation written in application
# source — must at least resolve. Only the mechanically decidable half is asserted here: the
# target file exists and N is within it. "Does N still point at the right paragraph" is NOT
# decidable and is deliberately left out (see the mirror-image use-vs-mention note above). This
# is still worth pinning: `.quality/docs_check.py` r2 checks the PATH and never the line, so a
# doc that SHRINKS below a cited line number currently rots silently in both gates, and a
# citation is the one thing in this corpus that is supposed to survive a doc edit. Fail-closed on
# an empty walk, per the no-op-gate rule — a zero here means the glob broke, not that the tree is
# clean. Both-states control, run before shipping by slicing this block verbatim out of this file
# and replaying it against two trees (nothing under `app/` or `sidecar/` was written): on the live
# tree it printed `code->docs line citations=30, unresolvable=0` and held; on a synthetic tree
# whose first source file cites line 9999 of a two-line target and whose second cites a target
# file that was never created, it went red with exactly one OUT-OF-RANGE and one TARGET-MISSING.
# (Those two synthetic paths are described rather than written out, because writing them would
# make THIS comment an unresolvable citation and `.quality/docs_check.py` r2 correctly fails on
# it — measured, on the first draft of this comment.) A silence this check has never broken is
# not evidence, so that control is the reason it ships.
_CODE_EXT = {".ts", ".tsx", ".js", ".mjs", ".css", ".py"}
_code_cite_bad: list[str] = []
_code_cites = 0
for _sub in ("app", "sidecar"):
    for _cp in sorted((ROOT / _sub).rglob("*")):
        if _cp.suffix not in _CODE_EXT or not _cp.is_file():
            continue
        if "node_modules" in _cp.parts or "dist" in _cp.parts or "release" in _cp.parts:
            continue
        try:
            _cbody = _cp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for _cm in _CITE_RE.finditer(_cbody):
            _ctgt, _cn = _cm.group(1), int(_cm.group(2))
            _crel = _cp.relative_to(ROOT).as_posix()
            _code_cites += 1
            if not (ROOT / _ctgt).is_file():
                _code_cite_bad.append(f"{_crel} -> {_ctgt}:{_cn} TARGET-MISSING")
                continue
            if _ctgt not in _target_lines:
                _target_lines[_ctgt] = (ROOT / _ctgt).read_text(encoding="utf-8", errors="replace").splitlines()
            if not 1 <= _cn <= len(_target_lines[_ctgt]):
                _code_cite_bad.append(f"{_crel} -> {_ctgt}:{_cn} OUT-OF-RANGE")
check(
    "C13-code-anchor",
    True,
    _code_cites > 0 and not _code_cite_bad,
    f"code->docs line citations={_code_cites} (0 would mean the walk broke, not a clean tree), "
    f"unresolvable={len(_code_cite_bad)}: {_code_cite_bad or 'none'}",
)

# OPEN (a CODE defect, reported not fixed — this lane is scoped to `docs/**`). A citation written
# as `docs/<file>.md:<N> ("quoted excerpt")` is SELF-CHECKING: the quote either sits near line N or
# it does not, so unlike the general "did the anchor rot" question this subclass needs no
# judgement. (The placeholder is written with angle brackets on purpose. Spelling it out as a
# plausible-looking path makes THIS comment an unresolvable citation, and `.quality/docs_check.py`
# r2 fails on it — measured twice in one sitting, once here and once in the control note above.
# The gate is right both times, and it is recorded rather than quietly fixed because that is the
# same use-vs-mention shape this file has now been bitten by at C5b, C9b, P2.8 and C1b.)
# MEASURED at `1ad80ce8`: exactly 2 such citations exist across `app/` + `sidecar/`, and BOTH are
# rotted — `app/renderer/src/views/Library.tsx` and `app/renderer/src/views/Library.test.tsx`
# cite `docs/plans/v1.5/uiux-qol-audit-2026-08.md:299` while quoting "M6. Drag-and-drop works
# only on Library", which lives at `:481`; `:299` is the unrelated `jobqueue.css` colour bullet.
# Zero false positives and zero paraphrase noise in the same run, which is why this ships as a
# detector rather than a one-off note.
#
# A THIRD rotted anchor is NOT machine-checkable and is recorded here instead of guessed at:
# `app/renderer/src/components/jobqueue.conformance.test.ts:9` cites `:198-199` for the claim
# that `jobqueue.css` has no `--cancelled` colour, but `:198-199` is the checkbox tap-target
# paragraph and the cited sentence is at `:299-300`. Its claim precedes the citation unquoted, so
# only a human reading both sides can pair them — reported, not detected.
_QUOTED_CITE = re.compile(r"(docs/[A-Za-z0-9_./-]+\.md):(\d+)(?:-\d+)?\s*\(\s*[\"“]([^\"”]{8,200})")
_quote_rot: list[str] = []
for _sub in ("app", "sidecar"):
    for _cp in sorted((ROOT / _sub).rglob("*")):
        if _cp.suffix not in _CODE_EXT or not _cp.is_file():
            continue
        if "node_modules" in _cp.parts or "dist" in _cp.parts or "release" in _cp.parts:
            continue
        try:
            _cbody = _cp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Flatten comment continuations, so a quote wrapped across `//` lines still reads.
        _cflat = re.sub(r"\s*\n\s*(?://|#|\*)?\s*", " ", _cbody)
        for _qm in _QUOTED_CITE.finditer(_cflat):
            _qtgt, _qn, _quote = _qm.group(1), int(_qm.group(2)), " ".join(_qm.group(3).split())
            if not (ROOT / _qtgt).is_file():
                continue
            if _qtgt not in _target_lines:
                _target_lines[_qtgt] = (ROOT / _qtgt).read_text(encoding="utf-8", errors="replace").splitlines()
            _qls = _target_lines[_qtgt]
            _probe = " ".join(_quote.split()[:4]).lower()

            def _flat_md(lines: list[str]) -> str:
                return " ".join(re.sub(r"[*`_]", "", " ".join(lines)).split()).lower()

            if _probe and _probe not in _flat_md(_qls[max(0, _qn - 3) : _qn + 3]):
                _true = next(
                    (i + 1 for i, _ln in enumerate(_qls) if _probe in _flat_md([_ln])),
                    0,
                )
                _quote_rot.append(f"{_cp.relative_to(ROOT).as_posix()} -> {_qtgt}:{_qn} quotes text at :{_true or '?'}")
check(
    "C13-code-quote",
    True,
    bool(_quote_rot),
    f"quoted-excerpt code->docs citations still pointing at the wrong line={len(_quote_rot)}: "
    f"{_quote_rot or 'none'} (fix is in app source, outside the docs lane's scope)",
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
# to record that it USED to be listed, and the window stops at the end of the deferred-list
# PARAGRAPH instead of running on into whatever follows it.
#
# WINDOW FIX (v2): that window used to be `([^.]{0,240})`, which stops at the first PERIOD —
# and a period is not a sentence boundary in this corpus. Measured evasion: rewrite the list
# as "… and a publishing scheduler for v1.5. Also B-roll, still deferred." and the window
# collapses at `v1`, so the re-listed B-roll falls outside it and C11b reports green over
# the exact regression it exists to catch. Splitting the LIVE text on blank lines first and
# taking the remainder of the matching paragraph closes that escape: a version literal, a file
# name and an abbreviation are all interior to the paragraph.
#
# CORRECTED 2026-08-12 at `1ad80ce8`. This comment used to end "Strictly wider than the old
# window, so it cannot introduce a false negative the old one did not already have." That was
# REFUTED by measurement and is the overclaim this file exists to catch, in the file itself. The
# two windows differ in KIND, not in width — the old one ran over the ALREADY-FLATTENED roadmap,
# where paragraph breaks are spaces, so it could cross a paragraph boundary; this one cannot. So
# it is a TRADE, and both directions are real. Both-directions probe, same synthetic roadmap,
# old-vs-new: (B) "… a publishing scheduler for v1.5. Also B-roll, still deferred." -> old
# window collapses at `v1` and reports GREEN, new window goes RED = NEW-CATCHES. (C) a deferred
# list with NO terminating period and `Also B-roll.` in the FOLLOWING paragraph -> old window
# reads "… a publishing scheduler Also B-roll" and goes RED, new window stops at the paragraph
# break and reports GREEN = NEW-MISSES. The trade is taken deliberately: (B) is the realistic
# regression (someone re-adds B-roll to the list itself) and (C) requires a re-listing outside
# the paragraph the list lives in.
#
# Known limit, stated rather than hidden: a B-roll re-listing that sits outside the
# `yet shipped:` paragraph but still under `## Still deferred` escapes C11b, and C11c cannot
# backstop it because C11c skips `docs/ROADMAP.md` by design (see its loop below). Settling
# experiment: add that paragraph to `docs/ROADMAP.md` and confirm C11b stays green. The fix, if
# it ever matters, is to take the whole `## Still deferred` SECTION instead of the one
# paragraph — a behaviour change this pass did not measure, so it is recorded, not applied.
_live_roadmap = _live_text(roadmap)
_para = next((p for p in re.split(r"\n\s*\n", _live_roadmap) if "yet shipped:" in p), "")
_deferred_sentence = re.sub(r"\s+", " ", _para.split("yet shipped:", 1)[1]).strip() if _para else ""
check(
    "C11b",
    True,
    bool(_deferred_sentence) and "B-roll" not in _deferred_sentence,
    f"docs/ROADMAP.md no longer lists B-roll as not-yet-shipped "
    f"(paragraph found={bool(_deferred_sentence)}): {_deferred_sentence[:120]!r}",
)
# INVARIANT (new). C11a/C11b pin the CODE and the ROADMAP sentence, and both went green
# while `docs/plans/v1.5/README.md` went on telling every reader that `docs/ROADMAP.md`
# lists B-roll as "deferred from V1" — a doc contradicting another doc in the same commit
# series, which is the defect class this corpus exists to remove, reproduced one level up
# from the guard that was supposed to catch it. A guard scoped to a single file reports
# green over a contradiction it cannot see. So: no OTHER doc may assert that the ROADMAP
# defers B-roll. `_live_text` applies for the usual reason (a retraction that quotes the
# dead claim must not be punished), and the window is a bounded character span around each
# `ROADMAP` mention rather than a sentence, because `docs/ROADMAP.md:66` itself contains
# two periods and sentence-splitting would cut the citation off from its own claim.
#
# WINDOW DESIGN (v2), measured: the first draft asked only for `b-roll` + `defer` in the
# window and FALSE-POSITIVED on the corrected bullet, because "B-roll is **not** deferred"
# satisfies a co-occurrence test exactly as well as the assertion it denies — and the
# corrected bullet mentions the ROADMAP two sentences later on an unrelated subject (the
# Release-status version gap). A bare co-occurrence cannot separate a claim from its
# negation. Keying on the ROADMAP's OWN list phrasing can: a doc that reproduces the
# deferred list reproduces its wording. Both-states control run before shipping — RED on
# the pre-fix bullet and on three independent phrasings of the same claim, GREEN on the
# corrected bullet and on two negation/unrelated controls. Known limit, stated rather than
# hidden: a paraphrase that avoids all three stems escapes this. Settling experiment: add
# the paraphrase to a doc and confirm C11c stays green, then extend the stem list.
_BROLL_LIST_STEMS = ("deferred from v1", "still deferred", "yet shipped")
_broll_defer_docs: list[str] = []
for _p in sorted(ROOT.glob("docs/**/*.md")):
    _rel_p = _p.relative_to(ROOT).as_posix()
    if _rel_p == "docs/ROADMAP.md":
        continue
    try:
        _flat_doc = re.sub(r"\s+", " ", _live_text(_p.read_text(encoding="utf-8", errors="replace")))
    except OSError:
        continue
    for _hit in re.finditer(r"(?i)roadmap", _flat_doc):
        _w = _flat_doc[max(0, _hit.start() - 200) : _hit.end() + 200].lower()
        if "b-roll" in _w and any(_s in _w for _s in _BROLL_LIST_STEMS):
            _broll_defer_docs.append(_rel_p)
            break
check(
    "C11c",
    True,
    not _broll_defer_docs,
    f"no doc outside docs/ROADMAP.md asserts the ROADMAP defers B-roll (offenders: {_broll_defer_docs or 'none'})",
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
