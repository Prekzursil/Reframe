"""REFRAME v1.1.0 - vendored-vs-reference LR-ASD numerical EQUIVALENCE proof.

Loads (a) our VENDORED model ``media_studio.features._lightasd.asd.ASD`` and
(b) the REFERENCE ``~/LR-ASD`` ``model.Model.ASD_Model`` + ``loss.lossAV``, both
with the SAME ``finetuning_TalkSet.model`` weight, runs BOTH on the SAME
deterministic seeded input (the exact 112-crop / 13-cep-MFCC shapes the
production ``_lightasd_infer._score_track`` feeds) through the full forward +
``lossAV`` head, and asserts per-frame ASD scores are IDENTICAL
(max-abs-diff < 1e-4). PASS => the vendored integration is a faithful copy of
LR-ASD and inherits its published accuracy (Columbia avg F1 96.4% TalkSet-ft /
86.1% AVA-trained; AVA val mAP ~94%).

This is a VALIDATION harness, not part of the shipped package: it imports torch
and lives OUTSIDE ``media_studio`` / ``tests`` so it is never collected by the
sidecar pytest run and never measured by ``--cov=media_studio`` (coverage-neutral
by construction, mirroring the heavy GPU seam convention).

Run (WSL, RTX 4050, venv ``~/reframe-gpu-venv``)::

    wsl.exe -e bash -lc "~/reframe-gpu-venv/bin/python \
      /mnt/c/Users/Prekzursil/Documents/GitHub/Reframe/docs/validation/lr_asd_equivalence.py"

Exit 0 == PASS (faithful), 1 == FAIL. Recorded result (2026-06-29): max-abs-diff
``0.000e+00`` (bit-identical) -> PASS. See ``docs/V1.1-BUILD-NOTES.md``.
"""
import hashlib
import math
import os
import sys

import numpy as np
import torch

SIDECAR = "/mnt/c/Users/Prekzursil/Documents/GitHub/Reframe/sidecar"
REFREPO = os.path.expanduser("~/LR-ASD")
WEIGHT = os.path.expanduser("~/LR-ASD/weight/finetuning_TalkSet.model")
ASD_FPS = 25
DURATIONS = (1, 1, 1, 2, 2, 2, 3, 3, 4, 5, 6)
DEV = "cpu"  # CPU => fully deterministic for both models

torch.manual_seed(0)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_subset(module, ckpt, prefix):
    sd = module.state_dict()
    n = 0
    missing = []
    for k, v in ckpt.items():
        if k.startswith(prefix):
            name = k[len(prefix):]
            if name in sd and sd[name].size() == v.size():
                sd[name].copy_(v)
                n += 1
            else:
                missing.append(k)
    return n, missing


def score_arr(model, loss_av, af, vf, dev):
    """Exact replica of _lightasd_infer._score_track scoring loop -> raw per-window scores."""
    length = min((af.shape[0] - af.shape[0] % 4) / 100, vf.shape[0] / ASD_FPS)
    af = af[: int(round(length * 100)), :]
    vf = vf[: int(round(length * ASD_FPS)), :, :]
    all_score = []
    for dur in DURATIONS:
        batch = int(math.ceil(length / dur))
        sc = []
        with torch.no_grad():
            for i in range(batch):
                ia = torch.FloatTensor(af[i * dur * 100 : (i + 1) * dur * 100, :]).unsqueeze(0).to(dev)
                iv = torch.FloatTensor(vf[i * dur * ASD_FPS : (i + 1) * dur * ASD_FPS, :, :]).unsqueeze(0).to(dev)
                ea = model.forward_audio_frontend(ia)
                ev = model.forward_visual_frontend(iv)
                out = model.forward_audio_visual_backend(ea, ev)
                sc.extend(loss_av.forward(out, labels=None))
        all_score.append(np.asarray(sc, dtype=np.float64))
    n = min(len(s) for s in all_score)
    stacked = np.stack([s[:n] for s in all_score], axis=0)  # (len(DURATIONS), n) raw
    mean_raw = stacked.mean(axis=0)
    prod_round = np.round(mean_raw, 1)  # production emitted value
    return stacked, mean_raw, prod_round


print("=== WEIGHT ===")
print("path:", WEIGHT)
print("sha256:", sha256(WEIGHT))

ckpt = torch.load(WEIGHT, map_location=DEV, weights_only=True)

# ---- (b) REFERENCE model (~/LR-ASD) ----
sys.path.insert(0, REFREPO)
from model.Model import ASD_Model as RefASD  # noqa: E402
from loss import lossAV as RefLossAV  # noqa: E402

ref_model = RefASD().to(DEV)
ref_loss = RefLossAV().to(DEV)
nm, mm = load_subset(ref_model, ckpt, "model.")
nl, ml = load_subset(ref_loss, ckpt, "lossAV.")
ref_model.eval()
ref_loss.eval()
ref_params = sum(p.numel() for p in ref_model.parameters())
print("\n=== REFERENCE (~/LR-ASD) ===")
print(f"loaded model.* tensors={nm} missing={mm}; lossAV.* tensors={nl} missing={ml}")
print(f"ASD_Model params={ref_params/1e6:.4f}M")

# ---- (a) VENDORED model (sidecar) ----
sys.path.insert(0, SIDECAR)
from media_studio.features._lightasd.asd import ASD as VendASD  # noqa: E402

vend = VendASD(device=DEV)
vend.loadParameters(WEIGHT)  # the REAL production loader (stderr empty == zero mismatch)
vend.eval()
vend_params = sum(p.numel() for p in vend.model.parameters())
print("\n=== VENDORED (sidecar) ===")
print(f"ASD_Model params={vend_params/1e6:.4f}M")

# ---- structural: every parameter tensor element-wise identical ----
ref_sd = dict(ref_model.state_dict())
vend_sd = dict(vend.model.state_dict())
assert set(ref_sd) == set(vend_sd), "param-name set differs!"
max_param_diff = 0.0
for k in ref_sd:
    d = (ref_sd[k].double() - vend_sd[k].double()).abs().max().item()
    max_param_diff = max(max_param_diff, d)
print(f"\n=== STRUCTURAL ===\nparam-name sets identical=True; max per-tensor weight diff={max_param_diff:.3e}")

# ---- deterministic SAME input (production shapes) ----
rng = np.random.default_rng(1234)
n_v = 125  # 5 s of 25-fps video crops
n_a = 500  # 5 s of 100-fps MFCC
vf = rng.random((n_v, 112, 112), dtype=np.float64) * 255.0  # 112-crop grayscale [0,255]
af = rng.standard_normal((n_a, 13))  # 13-cep MFCC

ref_stack, ref_mean, ref_round = score_arr(ref_model, ref_loss, af, vf, DEV)
vend_stack, vend_mean, vend_round = score_arr(vend.model, vend.lossAV, af, vf, DEV)

raw_max = float(np.abs(ref_stack - vend_stack).max())  # every window, every duration, unrounded
mean_max = float(np.abs(ref_mean - vend_mean).max())
prod_max = float(np.abs(ref_round - vend_round).max())

print("\n=== EQUIVALENCE (same weight, same seeded input) ===")
print(f"per-frame score vector length n={len(ref_mean)}")
print(f"reference  score stats: min={ref_mean.min():+.4f} max={ref_mean.max():+.4f} std={ref_mean.std():.4f}")
print(f"vendored   score stats: min={vend_mean.min():+.4f} max={vend_mean.max():+.4f} std={vend_mean.std():.4f}")
print(f"MAX-ABS-DIFF raw per-window scores (all durations) = {raw_max:.3e}")
print(f"MAX-ABS-DIFF averaged per-frame scores            = {mean_max:.3e}")
print(f"MAX-ABS-DIFF production-rounded scores            = {prod_max:.3e}")

THRESH = 1e-4
non_degenerate = ref_mean.std() > 1e-3  # guard against trivial all-equal-constant
verdict = (raw_max < THRESH) and (max_param_diff < THRESH) and non_degenerate
print(f"\nnon-degenerate output (std>1e-3)={non_degenerate}")
print(f"EQUIVALENCE: max-abs-diff={raw_max:.3e}  {'PASS' if verdict else 'FAIL'} (threshold {THRESH})")
sys.exit(0 if verdict else 1)
