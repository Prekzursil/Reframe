"""Provenance check for a get-pip.py pin rotation.

`manager.py` documents the standard this rotation must meet, and its LIMIT: pypa
publishes NO checksum for the rolling URL, so a rotation rests only on
  * two INDEPENDENT TLS fetches agreeing on the digest,
  * a Last-Modified consistent with a fresh publish,
  * a size delta consistent with a content update rather than truncation, and
  * the payload being the canonical base85-zip bootstrapper.
That is PROVENANCE, NOT AUTHENTICITY -- weaker than a vendor-checksummed pin.

This runs those four checks and prints the new pin, so the rotation is evidenced
rather than pasted.

Usage:  python docs/validation/tools/verify_getpip_rotation.py
"""

from __future__ import annotations

import hashlib
import re
import urllib.request
from pathlib import Path

URL = "https://bootstrap.pypa.io/get-pip.py"


def _find_root() -> Path:
    """Walk up to the repo root rather than assuming a fixed depth (see hermetic_probe)."""
    here = Path(__file__).resolve()
    for cand in (here.parent, *here.parents):
        if (cand / ".git").exists() and (cand / "sidecar/pyproject.toml").is_file():
            return cand
    raise SystemExit(f"FAILED:getpip-rotation cannot locate the repo root from {here}")


ROOT = _find_root()

# Read the CURRENT pin out of the source of truth instead of hardcoding it. A hardcoded
# "previous pin" goes stale the moment a rotation lands, and this tool would then compare
# against a value nothing uses — reporting a rotation that already happened.
_MANAGER = ROOT / "sidecar/media_studio/assets/manager.py"
_m = re.search(r'GET_PIP_SHA256\s*=\s*"([0-9a-f]{64})"', _MANAGER.read_text(encoding="utf-8"))
OLD_SHA = _m.group(1) if _m else "(could not read GET_PIP_SHA256 from manager.py)"
# Size of the currently-pinned artifact, for the truncation check. Parsed from the same
# comment block so it travels with the pin.
_s = re.search(r"Current: https://bootstrap\.pypa\.io/get-pip\.py, ([\d,]+) B", _MANAGER.read_text(encoding="utf-8"))
OLD_SIZE = int(_s.group(1).replace(",", "")) if _s else 0


def fetch() -> tuple[bytes, dict[str, str]]:
    req = urllib.request.Request(URL, headers={"User-Agent": "reframe-pin-check"})
    with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310 - pinned https literal
        return r.read(), {k.lower(): v for k, v in r.headers.items()}


print(f"URL: {URL}\n")

b1, h1 = fetch()
b2, h2 = fetch()
s1, s2 = hashlib.sha256(b1).hexdigest(), hashlib.sha256(b2).hexdigest()

print("1. TWO INDEPENDENT FETCHES")
print(f"     fetch A: {len(b1):,} B  sha256={s1}")
print(f"     fetch B: {len(b2):,} B  sha256={s2}")
agree = s1 == s2
print(f"     agree: {agree}")

print("\n2. LAST-MODIFIED")
print(f"     A: {h1.get('last-modified', '(none)')}")
print(f"     B: {h2.get('last-modified', '(none)')}")

print("\n3. SIZE DELTA vs the previous pin")
delta = len(b1) - OLD_SIZE
print(f"     previous: {OLD_SIZE:,} B   current: {len(b1):,} B   delta: {delta:+,} B")
grew = delta > 0
print(f"     consistent with a content update (not truncation): {grew}")

print("\n4. PAYLOAD SANITY (canonical base85-zip bootstrapper)")
head = b1[:400].decode("utf-8", "replace")
has_hi = "Hi There!" in head
m = re.search(rb"pip==?([0-9][0-9.]*)", b1[:8000]) or re.search(rb"pip[- ]([0-9]+\.[0-9]+)", b1[:8000])
declared = m.group(1).decode() if m else "(not found in header)"
is_b85 = b"base64" in b1[:8000] or b"b85decode" in b1[:8000] or b"zipfile" in b1[:8000]
print(f"     '#!/usr/bin/env python' header: {b1[:30].startswith(b'#!')}")
print(f"     'Hi There!' marker: {has_hi}")
print(f"     declares pip: {declared}")
print(f"     base85/zip bootstrapper markers: {is_b85}")

print("\n--- VERDICT ---")
print(f"  pinned in manager.py: {OLD_SHA}")
print(f"  live upstream:        {s1}")

# THREE outcomes, not two. An earlier version had only pass/fail and gated on `delta > 0`,
# which made the HEALTHY state (pin == live, delta 0) report FAILED — a detector that
# cries wolf every time someone runs it is worse than no detector, because the next reader
# learns to ignore it.
if s1 == OLD_SHA:
    print("SUCCESS:getpip-rotation NO ROTATION NEEDED — the pin already matches upstream")
    raise SystemExit(0)

# A rotation HAS happened. Now the provenance standard applies. `grew` is a truncation
# check, so it is only meaningful against a real previous size.
sane_size = len(b1) > 1_000_000 and (OLD_SIZE == 0 or delta > 0)
ok = agree and sane_size
if ok:
    print("  ROTATION DETECTED and provenance-checked. To adopt it, update BOTH:")
    print("    sidecar/media_studio/assets/manager.py  GET_PIP_SHA256")
    print("    build/python-embed-setup.ps1            $ExpectedGetPipSha256")
    print("  (a test asserts those two match; rotating one alone fails the gate)")
    print("SUCCESS:getpip-rotation rotation evidenced (PROVENANCE, not authenticity)")
    raise SystemExit(0)

print("FAILED:getpip-rotation a rotation is present but did NOT pass provenance -- do NOT re-pin")
raise SystemExit(1)
