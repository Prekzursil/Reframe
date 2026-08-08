# Reframe Model Re-Hosting Dossier

> **Status:** SUPERSEDED BY docs/plans/v1.5/PROGRAM.md (2026-07-11)

**Scope:** personal / non-commercial use. **Verify-before-load is mandatory** — every hosted artifact is sha256-pinned in `assets/manifest.py`, verified at download (and recommended again at load), and the pickle load-path is eliminated where feasible.

**Manifest (single source of truth for pins):**
`C:/Users/Prekzursil/Documents/GitHub/Reframe/sidecar/media_studio/assets/manifest.py`
- `installer="download"` requires `url` + `dest` + `sha256` (64-hex), validated in `AssetEntry.__post_init__`.
- An HF `resolve/<ref>/…` URL forces `<ref>` to be a **40-hex commit hash** (branch/tag rejected via `_HF_RESOLVE_RE` + `_COMMIT_HASH_RE`). GitHub-raw URLs get **no** ref enforcement — sha256 is the only anchor.
- `installer="hf"` requires `hf_repo` + a 40-hex `hf_revision`.

**Three models covered:**
| model | role | current manifest state | license |
|---|---|---|---|
| ViNet-S | video saliency (crop-track subject) | **unregistered** — `saliency.py` has a dead `ASSET_URL`; backend seam unimplemented | CC BY-NC-SA 4.0 |
| TransNetV2 | shot/scene transition detection | **no-op registration** — `register_scene_transnet_assets()` intentionally unregistered; degrades to PySceneDetect | MIT |
| LR-ASD (S3FD + ASD) | multi-speaker active-speaker reframe | **registered** as `.pth`/`.model` pickles (G-5 re-host target) | MIT |

---

## MODEL 1 — ViNet-S (video saliency)

### 1.1 Canonical author source (VERIFIED)
- **Paper:** "Minimalistic Video Saliency Prediction via Efficient Decoder & Spatio-Temporal Action Cues", **arXiv:2502.00397**, ICASSP 2025. DOI `10.1109/ICASSP49660.2025.10888852` (IEEE Xplore doc 10888852). Authors: Rohit Girmaji, Siddharth Jain, Bhav Beri, Sarthak Bansal, Vineet Gandhi (IIIT Hyderabad). Repo brands it **"ViNet++"**.
- **Official GitHub:** `https://github.com/ViNet-Saliency/vinet_v2` (default branch `main`) — the ICASSP-2025 model.
- **NOT** `samyak0210/ViNet` (the 2020 ViNet, arXiv 2012.06170 — a different model). `saliency.py`'s docstring correctly cites 2502.00397.

### 1.2 Weight distribution + the discrepancy (VERIFIED)
- **Author distribution:** a single Google Drive bundle from the README "Checkpoints" section:
  `https://drive.google.com/file/d/12UeAsdiD2xPLmoLRDcE_HjAUjxFdmw5N/view`
  - Headers confirm `Content-Disposition: filename="checkpoints.tar.gz"`, `Content-Length: 3044476724` → **~2.83 GiB** — an archive of **all** checkpoints (ViNet_S + ViNet_A across DHF1K/UCF/Hollywood2/MVVA/audio-visual), **not** a single 36 MB file.
  - Direct-download (bypasses the large-file virus-scan interstitial):
    `https://drive.usercontent.google.com/download?id=12UeAsdiD2xPLmoLRDcE_HjAUjxFdmw5N&export=download&confirm=t`
- **Individual ViNet-S weight inside the archive:** a per-dataset raw `state_dict` `.pt`. From the inference bash script the canonical visual-only file is:
  `DHF1K_vinet_s_rootgrouped_32_bs8_kld_cc.pt` (~36 MB, ~9.4M params × 4 bytes). **DHF1K** is the general visual-only saliency model — the right pick for the no-face crop-track use case.
- **Discrepancy to fix:** the `ASSET_URL` pinned in `saliency.py` (`drive.usercontent.google.com/download?id=1Tt5pPq4La8a-Nm5oN2g0K3sQ8aJpVfXk`) is a **dead file id** (already flagged 404 in a code comment 2026-06-28). The live canonical id resolves to the **2.8 GB bundle, not a 36 MB `.pt`**. **The re-host cannot be a straight URL swap** — you must download the archive, extract the single DHF1K `.pt`, and re-host **that** ~36 MB file.

### 1.3 Original-author SHA-256
- **NONE published.** Authors provide no checksums anywhere (README/repo/Drive). Trust root = "downloaded from the authors' Drive, then hash-pinned by us." You compute SHA-256 after extracting the file and pin *that*.

### 1.4 License + attribution text (VERIFIED)
- **CC BY-NC-SA 4.0** — confirmed in the repo `LICENSE` (full CC "Attribution-NonCommercial-ShareAlike 4.0 International" legal text) **and** the README footer badge. Matches `saliency.py` docstring.
- **NC = non-commercial → permitted for personal use** with attribution + **ShareAlike** (redistributed weights/derivatives must carry the same CC BY-NC-SA 4.0). The re-host MUST reproduce license + attribution.
- **Attribution text to ship alongside the re-hosted weight:**
  > ViNet-S / ViNet++ saliency weights © 2025 Rohit Girmaji, Siddharth Jain, Bhav Beri, Sarthak Bansal, Vineet Gandhi (IIIT Hyderabad). "Minimalistic Video Saliency Prediction via Efficient Decoder & Spatio-Temporal Action Cues", ICASSP 2025 (arXiv:2502.00397). Licensed under CC BY-NC-SA 4.0 (https://creativecommons.org/licenses/by-nc-sa/4.0/). Redistributed unmodified/derived under the same license for non-commercial use.

### 1.5 Format: `.pt` pickle (NOT safetensors) + conversion plan
- Weights are **PyTorch `.pt` pickle**, saved as a **bare `state_dict`** (`OrderedDict` of tensors), not a wrapped checkpoint dict.
- Load path in `ViNet_S/ViNet_S_inferences_metrics.py:193`: `model.load_state_dict(torch.load(args.checkpoint_path))` — no `["model"]`/`["state_dict"]` unwrap, no `strict=False` → exact key match.
- **Conversion plan (recommended):** load once (`weights_only=True` works — pure tensors on torch ≥2.6) → `save_file(sd, "vinet-s-saliency.safetensors")` (bare tensor dict converts cleanly) → re-host the `.safetensors`. Eliminates the pickle load-path, consistent with the LR-ASD safetensors mandate. If `.pt` is kept, gate the loader to `weights_only=True`.

### 1.6 Load-compat requirements (backend must be ported — seam is empty)
Source of truth: `ViNet_S/ViNet_S_model.py`. **The sibling `saliency_backend.py` referenced by `_default_backend_factory` does NOT exist in the Reframe tree** — the backend seam is declared but unimplemented, so there is no vendored model def to diff against. Port from upstream.

**ViNet-S instantiation (exact config for the DHF1K/root-grouped weight):**
```python
VideoSaliencyModel(
    use_upsample=True, num_hier=3, num_clips=32,
    grouped_conv=True, root_grouping=True, depth=False,
    efficientnet=False, BiCubic=False, maxpool3d=True,
)   # -> decoder = DecoderConvUpGrouped(root_grouping=True, BiCubic=False)
```

**state_dict top-level prefixes (exact-match required):**
- `backbone.*` — S3D encoder: `backbone.base1.*`, `backbone.base2.*` (`Mixed_3b/3c`), `backbone.base3.*` (`Mixed_4b..4f`), `backbone.base4.*` (`Mixed_5b/5c`). MaxPool layers carry no params.
- `decoder.*` — `decoder.convtsp1.*` … `convtsp4.*` (grouped `Conv3d` + `Upsample`/`Sigmoid`; groups=32/16/8/4/2 root-grouped).

**Porting requirements (break the load if missed):**
1. Also vendor `ViNet_S/model_utils.py` (`ViNet_S_model.py` does `from model_utils import *`) — defines `SepConv3d`, `BasicConv3d`, `Mixed_3b/3c/4b/4c/4d/4e/4f/5b/5c`, `BackBone_Maxpool_Base1`, and the bare `reshape` helper. Missing/renamed submodules shift key names → `load_state_dict` mismatch.
2. Model I/O: input = clip of **32 RGB frames** (S3D Kinetics-pretrained encoder); output = single-channel HxW map through `Sigmoid`, per clip. The Reframe `SaliencyBackend.infer(frames) -> NxHxW` seam must window frames into 32-frame clips and map clip outputs back to per-frame maps (current pure code assumes one map per input frame — reconcile).
3. Raw `state_dict` → `torch.load(...); model.load_state_dict(...)` no unwrap; prefer `weights_only=True` / safetensors after re-host.

### 1.7 Manifest registration fields (ViNet-S)
Currently unregistered — add a `register_saliency_assets()` mirroring the other tracks. Post-conversion values:
```python
SALIENCY_VINET_S_ASSET_NAME = "vinet-s-saliency"
# PROVENANCE: ViNet-Saliency/vinet_v2 checkpoints.tar.gz (Google Drive id
#   12UeAsdiD2xPLmoLRDcE_HjAUjxFdmw5N, ~2.83 GiB) -> extract
#   DHF1K_vinet_s_rootgrouped_32_bs8_kld_cc.pt (~36 MB) -> save_file to safetensors.
#   NO upstream sha256 exists; hash computed by us on the converted file. CC BY-NC-SA 4.0.
SALIENCY_VINET_S_COMMIT = "<40-hex commit of the HF re-host repo>"
SALIENCY_VINET_S_URL = f"https://huggingface.co/<you>/reframe-vinet-s/resolve/{SALIENCY_VINET_S_COMMIT}/vinet-s-saliency.safetensors"
SALIENCY_VINET_S_SHA256 = "<sha256 of the HOSTED .safetensors bytes>"   # 64 hex
SALIENCY_VINET_S_DEST = "models/vinet-s-saliency.safetensors"
SALIENCY_VINET_S_SIZE_MB = 36

register_asset(AssetEntry(
    name=SALIENCY_VINET_S_ASSET_NAME, kind="model", size_mb=SALIENCY_VINET_S_SIZE_MB,
    dest=SALIENCY_VINET_S_DEST, label="ViNet-S video saliency (ICASSP 2025, CC BY-NC-SA 4.0)",
    installer="download", url=SALIENCY_VINET_S_URL, sha256=SALIENCY_VINET_S_SHA256,
))
```
NOTE: CC BY-NC-SA ShareAlike means the HF re-host repo card must carry the license + attribution (§1.4). If you cannot self-host on HF, a self-owned asset CDN + the sha256 pin is equivalent (GitHub-raw gets no ref-enforcement — sha256 is the only anchor).

---

## MODEL 2 — TransNetV2 (shot-transition detection)

### 2.1 Canonical author & source (VERIFIED)
- **Author:** Tomáš Souček & Jakub Lokoč (soCzech). Paper: "TransNet V2: An Effective Deep Network Architecture for Fast Shot Transition Detection."
- **Canonical repo:** `https://github.com/soCzech/TransNetV2` — a **GitHub** repo, **MIT** (LICENSE at root, confirmed).
- **Layout:** `inference/` (TF SavedModel — original weights, git-lfs), `inference-pytorch/` (PyTorch reimpl), `training/`, `configs/`.

### 2.2 Correct the vendored "HF 404" assumption
`scene_transnet.py` sets `HF_REPO = "soCzech/TransNetV2"` and claims "the upstream HF repo now returns HTTP 404 (removed)." **Wrong framing.** `soCzech/TransNetV2` is a **GitHub** repo and was **never a HF model repo** — `huggingface.co/soCzech/TransNetV2` 404s because it never existed on HF, not because it was removed. **There is no official soCzech HF mirror to restore.** Re-host must point at a third-party HF mirror or a self-owned copy.

### 2.3 Where the PyTorch weights actually live
- The **GitHub repo ships NO `.pth`.** `inference-pytorch/` has only `README.md`, `convert_weights.py`, `transnetv2_pytorch.py`. The `.pth` is **generated locally** by `python convert_weights.py` against the TF SavedModel weights (`inference/transnetv2-weights/`, git-lfs). So the "canonical" PyTorch weight is a **derived artifact**, not an upstream download.
- **Third-party HF mirrors** of the pre-converted `transnetv2-pytorch-weights.pth` (~30.5 MB pickle):
  - `Sn4kehead/TransNetV2` → `https://huggingface.co/Sn4kehead/TransNetV2/blob/main/transnetv2-pytorch-weights.pth` (most direct "official conversion")
  - `MiaoshouAI/transnetv2-pytorch-weights` (**no license stated — avoid for redistribution**)
  - `ByteDance/shot2story` (pinned commit `ff853c5…`) — same filename

### 2.4 Format, size, original-author SHA-256 (important caveat)
- **Format:** `.pth` pickle (torch `state_dict`). HF pickle scanner reports only benign imports (`OrderedDict`, `_rebuild_tensor_v2`, `LongStorage`, `FloatStorage`) → clean pure-tensor state_dict, no code objects.
- **Size:** ~**30.5 MB** (~31,977,472 B). Vendored `ASSET_SIZE_MB = 40` is an over-estimate → correct to ~31.
- **NO single canonical SHA-256** — mirrors are **not** byte-identical (re-saved under different torch/pickle versions), so the hash must be pinned to the **specific mirror+revision you choose**:
  - Sn4kehead: `834b10f25ae9e1b4e4f2652fe2843bd2b1388057a435d68b7c52635578fcc04d` (Xet `3b73e109…`)
  - ByteDance/shot2story: `a313d0b3bebfa9a71914b375bfdf918a30b5c3b1e6be51972d35dd8078b442de` (Xet `1ffa3972…`)
  - MiaoshouAI: not shown.
  - **CONFIDENCE FLAG:** these were extracted from HF pages by a small fetch model — **re-verify by downloading + `sha256sum` locally before pinning.** Do not trust blind. There is no "author-original" hash because the author never shipped a `.pth`.

### 2.5 Load-compat with the vendored loader
- `inference-pytorch/README` recipe: `from transnetv2_pytorch import TransNetV2; sd = torch.load("transnetv2-pytorch-weights.pth"); model.load_state_dict(sd)`. **Input shape** `(batch, frames, H=27, W=48, 3)` uint8 RGB (e.g. `(1,100,27,48,3)`).
- `scene_transnet.py` `_default_frame_loader` does `cv2.resize(rgb,(48,27))` → NumPy `(27,48)` — **consistent** with the model's 27×48.
- The real backend is a **lazy seam that does not yet exist:** `_default_backend_factory` imports `from .scene_transnet_backend import RealTransNetBackend`, but **there is no `scene_transnet_backend.py`** in the tree. The backend must be written, and it must **also vendor `transnetv2_pytorch.py`** (the `.pth` is only a state_dict, not a full pickled model).
- `register_scene_transnet_assets()` is a **no-op** today → `default_models_present` honestly returns False → pipeline degrades to PySceneDetect. `ASSET_REVISION = "85cef72"` is a short GitHub commit, **not a valid HF revision** — an HF asset needs the **full 40-hex commit** of the chosen mirror.

### 2.6 License + attribution text
- **MIT.** Attribution to ship:
  > TransNet V2 © Tomáš Souček & Jakub Lokoč. "TransNet V2: An Effective Deep Network Architecture for Fast Shot Transition Detection." Source: https://github.com/soCzech/TransNetV2 (MIT License). PyTorch weights converted from the upstream TensorFlow SavedModel.

### 2.7 Format decision + conversion plan
- **Convert to safetensors (recommended)** — clean state_dict, zero custom-object risk:
  `python -c "import torch; from safetensors.torch import save_file; sd=torch.load('transnetv2-pytorch-weights.pth', map_location='cpu'); save_file(sd, 'transnetv2.safetensors')"`
  Load via `from safetensors.torch import load_file; model.load_state_dict(load_file('transnetv2.safetensors'))`. Removes the pickle-execution surface.
- **Cleanest MIT-provenance path:** regenerate the `.pth` yourself from the GitHub TF weights via `convert_weights.py`, then convert to safetensors — guarantees provenance. Otherwise adopt **Sn4kehead** (licensed, most direct); **avoid MiaoshouAI** (no license).

### 2.8 Manifest registration fields (TransNetV2)
Replace the no-op with a real registration (post-conversion, using YOUR re-host):
```python
# Vendored def: sidecar/media_studio/features/scene_transnet.py (asset "transnetv2-pytorch")
SCENE_TRANSNET_ASSET_NAME = "transnetv2-pytorch"
# PROVENANCE: soCzech/TransNetV2 (GitHub, MIT) TF SavedModel -> convert_weights.py -> .pth
#   -> save_file to safetensors. sha256 pins the HOSTED safetensors bytes (mirrors differ).
SCENE_TRANSNET_COMMIT = "<40-hex commit of your re-host repo>"
SCENE_TRANSNET_URL = f"https://huggingface.co/<you>/reframe-transnetv2/resolve/{SCENE_TRANSNET_COMMIT}/transnetv2.safetensors"
SCENE_TRANSNET_SHA256 = "<sha256 of the HOSTED .safetensors bytes>"   # 64 hex, re-verified locally
SCENE_TRANSNET_DEST = "models/transnetv2.safetensors"
SCENE_TRANSNET_SIZE_MB = 31        # not 40

register_asset(AssetEntry(
    name=SCENE_TRANSNET_ASSET_NAME, kind="model", size_mb=SCENE_TRANSNET_SIZE_MB,
    dest=SCENE_TRANSNET_DEST, label="TransNetV2 shot-transition detector (MIT)",
    installer="download", url=SCENE_TRANSNET_URL, sha256=SCENE_TRANSNET_SHA256,
))
```
Ship `scene_transnet_backend.py` + a vendored `transnetv2_pytorch.py` alongside, and flip `default_models_present` on.

---

## MODEL 3 — LR-ASD (S3FD + ASD) — G-5 re-host + verify-before-load

Two weights, currently **registered as pickles** in `manifest.py` (lines 362-413). The G-5 task re-hosts both as **safetensors** and eliminates `torch.load`.

### 3.1 The two weights + current problem
| asset name | file | size | current URL (problem) | original-author SHA-256 |
|---|---|---|---|---|
| `lightasd-s3fd` | `sfd_face.pth` | 89,844,381 B (~86 MB) | `huggingface.co/lithiumice/syncnet/resolve/345f55fc…/sfd_face.pth` — **third-party mirror**, not the author; can be deleted/rewritten | `d54a87c2b7543b64729c9a25eafd188da15fd3f6e02f0ecec76ae1b30d86c491` |
| `lightasd-asd` | `finetuning_TalkSet.model` | 3,426,337 B (~4 MB) | `github.com/Junhua-Liao/LR-ASD/raw/1b6dcd2d…/weight/…` — author repo, but **GitHub-raw (non-LFS, no ref enforcement)**; sha256 is the only anchor | `6b4ef53694e874e96cf630198dc479c78aebb3993bbf166aee3d926dfe7d9342` |

Both are **torch pickles** unpickled today at:
- `sidecar/media_studio/features/_lightasd/s3fd/__init__.py:37` — `torch.load(weights_path, map_location=…, weights_only=True)`
- `sidecar/media_studio/features/_lightasd/asd.py:83` — `torch.load(path, map_location=…, weights_only=True)`
`weights_only=True` is a mitigation, not a guarantee (CVEs, torch-version-dependent). Requirement: eliminate the pickle load-path entirely.

### 3.2 The core tension + resolution (READ FIRST)
The ask has two clauses in direct conflict:
- "manifest sha256 = author-original hash" → argues for a **byte-verbatim** re-host (pin stays `d54a87c2…` / `6b4ef536…`).
- "safetensors mandatory, torch.load FORBIDDEN" → the hosted artifact must be `.safetensors`, whose bytes are **not** the author-original `.pth`.

You cannot have both literally. **Resolution:**
> **Re-host CONVERTED `.safetensors`. The manifest `sha256` pins the FINAL HOSTED (safetensors) bytes. The author-original `.pth` hash is preserved as a documented PROVENANCE anchor (code comment + tensor-equality proof), NOT the manifest pin.**

"Author-original" is honored at the **tensor** level (pure re-container, no value change), proven by load-both-and-assert key/shape/dtype/value equality. A byte-verbatim `.pth` re-host is **rejected** — it keeps `torch.load` alive. The manifest verifies downloaded bytes against the pin, so the pin MUST equal the hosted safetensors hash or every download hard-fails preflight.

### 3.3 WHERE to re-host
**Primary: one HuggingFace repo** (e.g. `Prekzursil/reframe-asd-weights`) holding **both** `.safetensors` in a **single commit**; pin that 40-hex commit. Reasons: LFS-backed/resumable/content-addressed; the manifest **already enforces HF commit-hash pinning** (`_HF_RESOLVE_RE`) giving a **second** anchor beyond sha256 (GitHub tags are mutable → no enforcement); matches the whisper `installer="hf"` pattern; user already operates HF.

**Keep `installer="download"`** (single-file + mandatory-sha semantics), both entries referencing the same repo@commit, different paths.

**Secondary (optional): a GitHub release asset** as cold-standby. Bytes identical → **same sha256 works for either URL** (one-line `url` failover, no re-hash). Do **not** build multi-URL fallback into the manifest. Recommendation: **HF canonical, GitHub release documented as swap-in mirror.**

### 3.4 Verify-before-load gate (three layers, in order)
1. **Download-time (exists):** `AssetManager.ensure` streams + verifies sha256 vs pin; mismatch raises. Unchanged.
2. **Load-time format gate (NEW, mandatory):** before touching the model —
   - Assert the artifact **is safetensors** (`safetensors.safe_open` / `.safetensors` extension); **refuse** anything else — a `.pth`/`.model` reaching the loader is a hard error, never a fallback.
   - **Delete `torch.load` entirely.** Replace both call sites with `safetensors.torch.load_file(path, device=…)` → `load_state_dict`. Ban even `weights_only=True` (defense-in-depth; safetensors cannot execute code).
   - **Recommended:** re-verify on-disk sha256 vs the manifest pin **at load time** (catches cache tampering / bit-rot).
3. **"convert + re-hash if only `.pth`" is a HOSTING-time, offline, trusted step — NEVER runtime.** Converting a pickle needs `torch.load` (unpickle), which is forbidden on the user's machine. The maintainer unpickles the author file **once** in a controlled env (`weights_only=True`), re-saves as safetensors, proves tensor-equality, re-hashes, hosts *that*. The user's machine never receives or unpickles a `.pth`.

### 3.5 License + attribution text (MIT for both)
> S3FD face detector + LR-ASD active-speaker model. LR-ASD (Junhua Liao et al., IJCV 2025) — https://github.com/Junhua-Liao/LR-ASD (MIT), successor to Light-ASD. S3FD weight (`sfd_face.pth`) fetched by the upstream via Google Drive; mirrored at `lithiumice/syncnet`. Weights re-containered to safetensors (tensor values unchanged) and redistributed under MIT for non-commercial use.

### 3.6 Manifest registration fields (G-5a deliverable — the join point)
Keep the **asset names stable** (`_lightasd_infer._resolve_weights` resolves via `manifest.LIGHTASD_S3FD_ASSET_NAME` / `LIGHTASD_ASD_ASSET_NAME`). Change url / sha256 / dest / size_mb:
```python
# --- lightasd-s3fd ---
# PROVENANCE (author-original, verbatim .pth): lithiumice/syncnet@345f55fc…/sfd_face.pth
#   author-original sha256 = d54a87c2b7543b64729c9a25eafd188da15fd3f6e02f0ecec76ae1b30d86c491 (89,844,381 B)
#   converted to safetensors offline (weights_only=True load -> save_file); tensor-equality VERIFIED.
LIGHTASD_S3FD_COMMIT = "<40-hex commit of Prekzursil/reframe-asd-weights>"
LIGHTASD_S3FD_URL = f"https://huggingface.co/Prekzursil/reframe-asd-weights/resolve/{LIGHTASD_S3FD_COMMIT}/sfd_face.safetensors"
LIGHTASD_S3FD_SHA256 = "<sha256 of the HOSTED .safetensors bytes>"   # 64 hex — MUST match hosted file
LIGHTASD_S3FD_DEST = "models/lightasd-sfd-face.safetensors"
LIGHTASD_S3FD_SIZE_MB = 86        # measure post-conversion (~raw tensor size)

register_asset(AssetEntry(
    name=LIGHTASD_S3FD_ASSET_NAME, kind="model", size_mb=LIGHTASD_S3FD_SIZE_MB,
    dest=LIGHTASD_S3FD_DEST, label="S3FD face detector (Light-ASD visual ASD, MIT)",
    installer="download", url=LIGHTASD_S3FD_URL, sha256=LIGHTASD_S3FD_SHA256,
))

# --- lightasd-asd ---
# PROVENANCE (author-original): Junhua-Liao/LR-ASD@1b6dcd2d…/weight/finetuning_TalkSet.model
#   author-original sha256 = 6b4ef53694e874e96cf630198dc479c78aebb3993bbf166aee3d926dfe7d9342 (3,426,337 B)
#   converted to safetensors offline; tensor-equality VERIFIED (state_dict is flat str->Tensor).
LIGHTASD_ASD_COMMIT = "<same 40-hex commit>"
LIGHTASD_ASD_URL = f"https://huggingface.co/Prekzursil/reframe-asd-weights/resolve/{LIGHTASD_ASD_COMMIT}/finetuning_TalkSet.safetensors"
LIGHTASD_ASD_SHA256 = "<sha256 of the HOSTED .safetensors bytes>"    # 64 hex
LIGHTASD_ASD_DEST = "models/lightasd-finetuning-talkset.safetensors"
LIGHTASD_ASD_SIZE_MB = 4          # measure post-conversion

register_asset(AssetEntry(
    name=LIGHTASD_ASD_ASSET_NAME, kind="model", size_mb=LIGHTASD_ASD_SIZE_MB,
    dest=LIGHTASD_ASD_DEST, label="LR-ASD active-speaker model (finetuning_TalkSet, MIT)",
    installer="download", url=LIGHTASD_ASD_URL, sha256=LIGHTASD_ASD_SHA256,
))
```
`installer="download"` forces non-empty `url`+`dest` and 64-hex `sha256` (validated in `AssetEntry.__post_init__`). HF `resolve` URL additionally forces the ref to be a **40-hex commit** (branch/tag rejected). `hf_repo`/`hf_revision`/`requirements` stay unset.

### 3.7 LOADER-stream code touchpoints
- `_lightasd/s3fd/__init__.py:37-38` — replace `torch.load(...weights_only=True)` with `safetensors.torch.load_file(weights_path, device=self.device)`, keep `self.net.load_state_dict(state_dict)`.
- `_lightasd/asd.py:83` — replace `torch.load(...weights_only=True)` with `safetensors.torch.load_file(path, device=self.device)`. Downstream `module.`-strip / size-check loop over `loadedState.items()` unchanged (safetensors returns flat `dict[str,Tensor]`).
- `_lightasd/__init__.py:45-46` — `S3FD_WEIGHT_NAME = "sfd_face.safetensors"`, `ASD_WEIGHT_NAME = "finetuning_TalkSet.safetensors"` (used by the `lightAsdWeightsDir` override path).
- Add `safetensors` to the heavy-seam dependency set (torch already present).
- Tests: `sidecar/tests/test_assets.py`, `test_phase8_backend_surfaces.py` — update expected url/sha/dest.

### 3.8 HOST/VERIFY gotchas
- **ASD `.model` is a full checkpoint** (`model.*` / `lossAV.*` / `lossV.*`). safetensors requires a **flat `str→Tensor`** map, no non-tensor metadata, no aliased/shared storage. Drop non-tensor keys (`loadParameters` only copies tensors) and `.contiguous().clone()` storage-sharing tensors, else `save_file` raises. Verify tensor-equality *after* normalization.
- **S3FD `sfd_face.pth`** is a plain flat state_dict → converts cleanly.
- **Measure `size_mb` + sha256 on the actual converted files** — do not carry `.pth` sizes forward.
- **Immutable-release hygiene** if also on GitHub: publish as a release asset under a fixed tag (immutable), not `raw`/branch.

### 3.9 G-5 split
**G-5a — Manifest registration (CRITICAL / serial / the join point).** The load-bearing correctness gate; can't be authored until final bytes are hosted (sha256 must equal hosted bytes). Deliverable: exact `AssetEntry` edits (url+sha256+dest+size_mb) + provenance comment + updated `test_assets.py`. Lands **last**, must be right — a wrong hash fails download preflight and blocks the whole feature.

**G-5b — Host + Verify + Loader (PARALLELIZABLE — three streams converging on G-5a):**
1. **HOST** — offline convert `.pth`/`.model` → `.safetensors` (trusted env, `weights_only=True` unpickle once), upload both to `Prekzursil/reframe-asd-weights` (+ optional GitHub release), capture pinned commit + each file's sha256. Produces the inputs G-5a consumes.
2. **VERIFY** — prove lossless: load author-original + converted, assert identical keys/shapes/dtypes/values; record author-original `.pth` sha256 as provenance anchor; sha256 the hosted files. Runs alongside HOST.
3. **LOADER** — the two loader edits + `WEIGHT_NAME` changes + load-time gate + `safetensors` dep. **Developable against a locally-converted file — does not need the hosted URL** → fully parallel to HOST. Must agree with G-5a's new `dest` extension.

---

## Cross-model summary

| model | canonical source | orig-author SHA-256 | license | current format | re-host format | manifest state |
|---|---|---|---|---|---|---|
| ViNet-S | `ViNet-Saliency/vinet_v2` (Drive `checkpoints.tar.gz` 2.83 GiB → extract DHF1K `.pt` ~36 MB) | **none published** (compute your own) | CC BY-NC-SA 4.0 (NC ok personal; ShareAlike) | `.pt` pickle (bare state_dict) | safetensors | unregistered (dead ASSET_URL; backend seam empty) |
| TransNetV2 | `soCzech/TransNetV2` (GitHub, MIT; `.pth` is derived via `convert_weights.py`) | **no canonical** (mirrors differ; Sn4kehead `834b10f2…`, ByteDance `a313d0b3…` — re-verify locally) | MIT | `.pth` pickle (~30.5 MB) | safetensors | no-op registration; backend seam empty; wrongly claims HF-404 |
| LR-ASD S3FD | `lithiumice/syncnet` mirror (author uses Drive) | `d54a87c2…` (89,844,381 B) | MIT | `.pth` pickle (~86 MB) | safetensors (pin = hosted bytes) | registered as `.pth` (G-5 target) |
| LR-ASD ASD | `Junhua-Liao/LR-ASD` (GitHub-raw) | `6b4ef536…` (3,426,337 B) | MIT | `.model` pickle (full ckpt, ~4 MB) | safetensors (flatten first) | registered as `.model` (G-5 target) |

**Universal re-host recipe:** download author bytes → (verify author sha where one exists) → offline `torch.load(weights_only=True)` in a trusted env → normalize to flat `str→Tensor` (drop non-tensor keys, `.contiguous().clone()` shared storage) → `save_file(...)` safetensors → **prove tensor-equality vs original** → `sha256sum` the hosted file → host on HF (single commit) → pin `url`+`sha256`+`dest`+`size_mb` in `manifest.py` → loaders use `safetensors.torch.load_file` only (no `torch.load`).

**Blocking caveats to resolve before "done":**
1. ViNet-S + TransNetV2 backend seams (`saliency_backend.py`, `scene_transnet_backend.py`) don't exist — must be ported/written, each vendoring its upstream model-def module.
2. TransNetV2 has no canonical sha256; LR-ASD/ViNet-S have no upstream sha (LR-ASD's are our own verified hashes). Every hash must be re-computed locally on the exact hosted bytes before pinning.
3. ViNet-S ShareAlike obligation: the re-host repo card must carry CC BY-NC-SA 4.0 + attribution.

**Sources:** arXiv:2502.00397 · github.com/ViNet-Saliency/vinet_v2 · IEEE Xplore 10888852 · Drive id 12UeAsdiD2xPLmoLRDcE_HjAUjxFdmw5N · github.com/soCzech/TransNetV2 (MIT) · huggingface.co/Sn4kehead/TransNetV2 · huggingface.co/ByteDance/shot2story · github.com/Junhua-Liao/LR-ASD (MIT) · huggingface.co/lithiumice/syncnet · CC BY-NC-SA 4.0 (creativecommons.org/licenses/by-nc-sa/4.0/)
