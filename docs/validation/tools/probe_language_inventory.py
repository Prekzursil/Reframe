"""Re-derive the language inventory from its PINNED upstream sources and diff it.

`sidecar/media_studio/features/languages.py` is the language SSOT, and its two
engine sets are not opinions — they are the exact language lists of two pinned
model/library versions. Hand-editing them is the bug class the SSOT exists to
kill, so this probe is how they get REGENERATED (and how a version bump gets
audited) instead of retyped.

It fetches, per run:

  * `faster_whisper/tokenizer.py` at the tag matching the `faster-whisper` pin in
    `sidecar/requirements.lock.txt` -> `_LANGUAGE_CODES`.
  * `openai-whisper`'s `tokenizer.py` -> the `LANGUAGES` dict. This is a
    MECHANICALLY DIFFERENT artifact (different repo, different file, different
    binding) and is used as the second signal on the code set plus the source of
    the English display labels.
  * the `nvidia/parakeet-tdt-0.6b-v3` model card at the revision pinned in
    `sidecar/media_studio/features/parakeet_asr.py` -> its `language:` YAML block,
    cross-checked against the card's own prose count.

It then compares the derived sets against what `languages.py` currently commits
and prints a per-set diff.

LIVE NETWORK: this is a deliberate out-of-band tool, NOT part of any pytest run
(`rules/common/ci-hygiene.md` §2 — the fast suite asserts against the committed
table, which is exactly what `sidecar/tests/test_languages.py` and
`app/renderer/src/lib/languages.conformance.test.ts` do). Nothing imports it.

FAIL CLOSED: a fetch failure, an unparseable source, or an empty extraction is a
non-zero exit, never a silent pass.

Usage:  python docs/validation/tools/probe_language_inventory.py
Exit 0 only when every derived set matches the committed one.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

FW_REPO = "https://raw.githubusercontent.com/SYSTRAN/faster-whisper"
OW_URL = "https://raw.githubusercontent.com/openai/whisper/v20250625/whisper/tokenizer.py"
HF_MODEL = "nvidia/parakeet-tdt-0.6b-v3"
TIMEOUT_SEC = 30

# Display-label overrides: each is a deliberate UI choice over openai-whisper's
# lowercase name (endonym, ambiguity, or a code that map does not carry at all).
LABEL_OVERRIDES: dict[str, str] = {
    "ba": "Bashkir",
    "el": "Greek",
    "fa": "Persian",
    "haw": "Hawaiian",
    "he": "Hebrew",
    "ht": "Haitian Creole",
    "jw": "Javanese",
    "my": "Burmese",
    # nb / zu are LOCAL-MT-only codes; openai-whisper's map has no entry for them.
    "nb": "Norwegian Bokmal",
    "nn": "Norwegian Nynorsk",
    "no": "Norwegian",
    "pt": "Portuguese",
    "sn": "Shona",
    "tl": "Tagalog",
    "yue": "Cantonese",
    "zh": "Chinese",
    "zu": "Zulu",
}


def _find_root() -> Path:
    """Anchor on markers that exist only at the repo root (not `parent.parent`)."""
    here = Path(__file__).resolve()
    for cand in (here.parent, *here.parents):
        if (cand / ".git").exists() and (cand / "app/package.json").is_file():
            return cand
    print(f"FAILED:langprobe cannot locate the repo root from {here}")
    raise SystemExit(1)


ROOT = _find_root()


def _get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=TIMEOUT_SEC) as resp:  # noqa: S310 - fixed https hosts
        return resp.read().decode("utf-8")


def _quoted(body: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r'"([^"]*)"', body)]


def _frozenset_body(src: str, name: str, where: str) -> str:
    m = re.search(rf"{name}[^=]*=\s*frozenset\(\s*\{{([\s\S]*?)\}}\s*\)", src)
    if not m:
        print(f"FAILED:langprobe could not parse {name} in {where}")
        raise SystemExit(1)
    return m.group(1)


def _pinned_faster_whisper_tag() -> str:
    lock = (ROOT / "sidecar/requirements.lock.txt").read_text(encoding="utf-8")
    m = re.search(r"^faster-whisper==([0-9][^\s;]*)", lock, re.MULTILINE)
    if not m:
        print("FAILED:langprobe no faster-whisper pin in sidecar/requirements.lock.txt")
        raise SystemExit(1)
    return f"v{m.group(1)}"


def _pinned_parakeet_revision() -> str:
    src = (ROOT / "sidecar/media_studio/features/parakeet_asr.py").read_text(encoding="utf-8")
    m = re.search(r'"([0-9a-f]{40})"', src)
    if not m:
        print("FAILED:langprobe no 40-hex HF revision pin in parakeet_asr.py")
        raise SystemExit(1)
    return m.group(1)


def _diff(name: str, derived: set[str], committed: set[str]) -> bool:
    if derived == committed:
        print(f"  {name}: MATCH ({len(derived)})")
        return True
    print(f"  {name}: DRIFT derived={len(derived)} committed={len(committed)}")
    print(f"    only upstream: {sorted(derived - committed)}")
    print(f"    only committed: {sorted(committed - derived)}")
    return False


def main() -> int:
    tag = _pinned_faster_whisper_tag()
    rev = _pinned_parakeet_revision()
    print(f"faster-whisper pin: {tag}")
    print(f"parakeet revision pin: {rev}")

    try:
        fw = _get(f"{FW_REPO}/{tag}/faster_whisper/tokenizer.py")
        ow = _get(OW_URL)
        card = _get(f"https://huggingface.co/{HF_MODEL}/raw/{rev}/README.md")
    except Exception as exc:  # noqa: BLE001 - any fetch failure is a fail-closed exit
        print(f"FAILED:langprobe fetch error {exc!r}")
        return 1

    m = re.search(r"_LANGUAGE_CODES\s*=\s*\(([\s\S]*?)\)\s*\n", fw)
    if not m:
        print("FAILED:langprobe could not parse _LANGUAGE_CODES from faster-whisper")
        return 1
    whisper = set(_quoted(m.group(1)))

    m = re.search(r"\nLANGUAGES\s*=\s*\{([\s\S]*?)\n\}", ow)
    if not m:
        print("FAILED:langprobe could not parse LANGUAGES from openai-whisper")
        return 1
    names = dict(re.findall(r'"([a-z]{2,3})"\s*:\s*"([^"]+)"', m.group(1)))

    ym = re.search(r"^---\n([\s\S]*?)\n---", card)
    lm = re.search(r"\nlanguage:\n((?:\s*-\s*[a-z]{2,3}\n)+)", ym.group(1)) if ym else None
    if not lm:
        print("FAILED:langprobe could not parse the language: YAML block from the model card")
        return 1
    parakeet = set(re.findall(r"-\s*([a-z]{2,3})", lm.group(1)))
    prose = re.findall(r"(\d+)\s+(?:European\s+)?languages", card)

    if not whisper or not parakeet or not names:
        print("FAILED:langprobe an extraction was EMPTY (fail closed)")
        return 1

    ok = True
    print("cross-checks:")
    if whisper == set(names):
        print(f"  whisper code set: two independent sources AGREE ({len(whisper)})")
    else:
        ok = False
        print(f"  whisper code set: SOURCES DISAGREE fw={len(whisper)} openai={len(names)}")
        print(f"    only faster-whisper: {sorted(whisper - set(names))}")
        print(f"    only openai-whisper: {sorted(set(names) - whisper)}")
    if str(len(parakeet)) in prose:
        print(f"  parakeet count: YAML block agrees with the card prose ({len(parakeet)})")
    else:
        ok = False
        print(f"  parakeet count: YAML says {len(parakeet)}, card prose says {prose}")

    langs_src = (ROOT / "sidecar/media_studio/features/languages.py").read_text(encoding="utf-8")
    print("committed vs derived:")
    ok = (
        _diff("WHISPER_LANGS", whisper, set(_quoted(_frozenset_body(langs_src, "WHISPER_LANGS", "languages.py"))))
        and ok
    )
    ok = (
        _diff("PARAKEET_LANGS", parakeet, set(_quoted(_frozenset_body(langs_src, "PARAKEET_LANGS", "languages.py"))))
        and ok
    )

    lab = re.search(r"LANGUAGE_LABELS[^=]*=\s*\{([\s\S]*?)\n\}", langs_src)
    if not lab:
        print("FAILED:langprobe could not parse LANGUAGE_LABELS from languages.py")
        return 1
    committed_labels = dict(re.findall(r'"([^"]+)":\s*"([^"]+)"', lab.group(1)))
    t1 = set(_quoted(_frozenset_body(langs_src, "TIER1_LANGS", "languages.py")))
    t2 = set(_quoted(_frozenset_body(langs_src, "TIER2_LANGS", "languages.py")))
    union = whisper | parakeet | t1 | t2
    ok = _diff("LANGUAGE_LABELS keys", union, set(committed_labels)) and ok

    bad_labels = []
    for code in sorted(union):
        want = LABEL_OVERRIDES.get(code) or " ".join(w.capitalize() for w in names.get(code, "").split())
        if want and committed_labels.get(code) != want:
            bad_labels.append((code, committed_labels.get(code), want))
    if bad_labels:
        ok = False
        print(f"  LABEL drift ({len(bad_labels)}): {json.dumps(bad_labels)}")
    else:
        print(f"  labels: MATCH ({len(union)})")

    print(
        f"SUCCESS:langprobe inventory matches the pins ({len(union)} languages)"
        if ok
        else "FAILED:langprobe inventory DRIFTED from the pinned upstream sources (see the diffs above)"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
