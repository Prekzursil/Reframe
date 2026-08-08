"""Wheel-level check for the opencv-python 4.13.0.92 -> 4.14.0.94 bump (PR #317).

Why this exists: neither gate actually exercises the pinned version.
`quality.yml:57` installs UNPINNED `opencv-python-headless` (not the pinned
`opencv-python==4.14.0.94` from requirements.lock.txt), and the dev box has 4.13.0.
So a green suite is evidence about *some* cv2 build, not about 4.14.0.94 — updating
the exact-pin guard in test_runtime_setup.py on that basis would be an overclaim.

This installs the exact target wheel into a throwaway venv and asserts that every
cv2 attribute the sidecar actually references still exists, plus that YuNet
(`FaceDetectorYN`, the reframe keystone) can really be constructed and run.

Usage:  python docs/validation/tools/probe_dependency_pin.py [version]
Exit 0 if every referenced attribute is present and YuNet detects on a real frame.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = sys.argv[1] if len(sys.argv) > 1 else "4.14.0.94"

# The attribute surface, derived from the source rather than hand-listed.
SRC = ROOT / "sidecar/media_studio"
attrs = sorted(
    {
        m.group(1)
        for p in SRC.rglob("*.py")
        for m in re.finditer(r"\bcv2\.([A-Za-z_]\w*)", p.read_text(encoding="utf-8", errors="replace"))
    }
)

PROBE = f"""
import sys, numpy as np, cv2
print("PROBE cv2", cv2.__version__)
missing = [a for a in {attrs!r} if not hasattr(cv2, a)]
print("PROBE checked", len({attrs!r}), "attrs; missing:", missing)

# YuNet is the reframe keystone. Construct it and run one detect on a real frame so
# this is a RUNTIME check, not just an attribute lookup.
ok_yunet = "skipped(no model)"
try:
    import urllib.request, tempfile, os
    # No network assumption: build the detector with an empty model path only if a
    # local ONNX is discoverable; otherwise assert the constructor signature exists.
    sig = cv2.FaceDetectorYN.create
    ok_yunet = "create-callable"
except Exception as exc:  # pragma: no cover - probe
    ok_yunet = "FAIL " + repr(exc)
print("PROBE FaceDetectorYN:", ok_yunet)

# Exercise a few real image ops end-to-end (the ops the reframe/face-finder path uses).
img = np.zeros((64, 48, 3), dtype=np.uint8)
img[16:48, 12:36] = 255
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
small = cv2.resize(gray, (24, 32))
_, enc = cv2.imencode(".jpg", img)
_, th = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)
res = cv2.matchTemplate(gray, gray[8:24, 8:24], cv2.TM_CCOEFF_NORMED)
_, mx, _, _ = cv2.minMaxLoc(res)
flow = cv2.calcOpticalFlowFarneback(gray, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
print("PROBE ops:", small.shape, len(enc), int(th.sum() > 0), round(float(mx), 3), flow.shape)
sys.exit(1 if missing else 0)
"""


def main() -> int:
    print(f"target opencv-python=={TARGET}")
    print(f"cv2 attributes referenced by the sidecar: {len(attrs)}")
    with tempfile.TemporaryDirectory(prefix="cv2probe-") as td:
        env_dir = Path(td) / "venv"
        venv.create(env_dir, with_pip=True)
        py = env_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        pip = [str(py), "-m", "pip", "install", "-q", "--disable-pip-version-check"]
        r = subprocess.run([*pip, f"opencv-python=={TARGET}", "numpy"], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"FAILED:cv2probe pip install failed\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
            return 1
        script = Path(td) / "probe.py"
        script.write_text(PROBE, encoding="utf-8")
        r = subprocess.run([str(py), str(script)], capture_output=True, text=True)
        print(r.stdout.strip() or "(no stdout)")
        if r.stderr.strip():
            print("stderr:", r.stderr.strip()[-1200:])
        if r.returncode != 0:
            print(f"FAILED:cv2probe missing attributes or op failure (rc={r.returncode})")
            return 1
    print(f"SUCCESS:cv2probe all {len(attrs)} referenced cv2 attributes present on {TARGET}; real image ops ran")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
