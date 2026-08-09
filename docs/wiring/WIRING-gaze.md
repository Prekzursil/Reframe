# WIRING-gaze — C15 eye-contact / gaze correction

> **Status:** ACTIVE

Redirects a speaker's apparent gaze toward the camera when they are reading from an
off-camera script. Ships a **geometric** engine (no learned gaze weights). One
owner decision is open — see [§3](#3-owner-decision-open-a-higher-quality-engine).

## 1. Lane files

| File | Role | Coverage |
|---|---|---|
| `sidecar/media_studio/models/likeness.py` | FAIL-CLOSED likeness-attestation gate (the ethics gate) | 100% line+branch |
| `sidecar/media_studio/features/gaze.py` | pure geometry, planning, capability probe, `gaze.run` / `gaze.probe` | 100% line+branch |
| `sidecar/media_studio/features/gaze_backend.py` | heavy half: YuNet detect + `cv2.remap` + audio re-mux | surface only (`# pragma: no cover`) |
| `sidecar/tests/test_likeness.py` · `test_gaze_geometry.py` · `test_gaze_service.py` | the tests | — |

Wired in `sidecar/media_studio/handlers/composition.py`; both methods are pinned in
`sidecar/tests/test_handlers_rpc_surface.py`.

## 2. Why geometric, not generative — the licence finding

The owner's rule is **MIT / Apache-2.0 / BSD** for anything a commercial build ships.
The OpenRAIL relaxation granted for lip-sync was for that one named component and was
NOT assumed to transfer here.

**There is NO fully permissive end-to-end *generative* gaze-redirection path.** Every
purpose-built generative redirector surveyed is blocked:

| Candidate | Code | Weights | Verdict |
|---|---|---|---|
| STED-gaze (ETH/NVIDIA) | NVIDIA Source Code License §3.3 "only may be used… non-commercially" | same | RESTRICTIVE |
| HeadNeRF | "Academic or non-profit organization noncommercial research use only" | same | RESTRICTIVE |
| GazeAnimation | **no LICENSE file / no licence section = no grant** | CelebAGaze + VGG-16 taint | RESTRICTIVE |
| GazeGaussian (ICCV 2025) | no LICENSE file = no grant | ETH-XGaze (CC BY-NC-SA 4.0 + conditions) | RESTRICTIVE |
| interpGaze | MIT | weights BaiduYun, password-gated ⇒ unobtainable | UNUSABLE |
| HzDmS/gaze_redirection | MIT | **ships no pretrained weights at all** | UNUSABLE |
| LivePortrait (Kuaishou) | MIT — but its own LICENSE says "The models of InsightFace are for non-commercial research purposes only… you should remove and replace InsightFace's detection models" | HF card frontmatter says `license: mit`, yet the repo **ships** `insightface/models/buffalo_l/*.onnx` (non-commercial) | RESTRICTIVE as-downloaded; permissive only after a documented excision |
| NVIDIA Maxine Eye Contact | NVIDIA AI Enterprise SLA (text NOT-CHECKED) | proprietary | PROPRIETARY, and the NIM path is containerised ⇒ breaks local-offline |
| OpenFace | "NONCOMMERCIAL RESEARCH USE ONLY", and claims ownership of derivatives | — | RESTRICTIVE |
| dlib `shape_predictor_68_face_landmarks.dat` | — | iBUG 300-W: "the trained model therefore can't be used in a commercial product" | RESTRICTIVE (the classic trap) |

### What we ship instead — verified permissive

* **YuNet** (`opencv/face_detection_yunet`) — **MIT**, © 2020 Shiqi Yu. Verified by
  **three mechanically-independent probes**: a live web fetch, this repo's own
  `NOTICE`, and a GitHub API read — all returning blob SHA `4cdf89a`. Note the
  per-model licence DIFFERS from the `opencv_zoo` repo root (Apache-2.0); MIT is the
  one that governs the ONNX. No non-commercial clause, no field-of-use restriction.
* **numpy / OpenCV** — BSD / Apache-2.0.

Crucially this adds **no new model and no new download**: the ONNX is the
already-vendored, sha256-pinned `yunet-face-detection` asset the ASD path resolves via
`reframe_claudeshorts.resolve_yunet_model_path`. There is no second face detector, and
because there are no learned gaze weights there is no model licence to accept.

### Compliance items that are NOT introduced by this lane, but are real

* `opencv-python-headless` metadata says Apache-2.0, its wrapper `cv2/LICENSE.txt` is
  MIT, and `cv2/LICENSE-3RD-PARTY.txt` states verbatim "FFmpeg is redistributed within
  all opencv-python packages" followed by the full **LGPL-2.1** text. This is a
  **pre-existing** dependency of this repo (`.github/workflows/quality.yml` installs
  it for the gate), not something C15 adds — but it means an LGPL-2.1 binary already
  sits in the shipped tree, which carries duties (ship the licence text, name the
  components, permit relinking). Zero-copyleft mitigation if wanted: build OpenCV with
  `-DWITH_FFMPEG=OFF`. **UNVERIFIED against our actual pin** — the measurement was of
  `opencv_python_headless-5.0.0.93`; settle by re-running the bundled-licence
  extraction against the version in `sidecar/requirements.lock.txt`.
* **Licence-clean is not patent-clean.** A search surfaced US 11902690 and US 12167159
  ("Machine learning driven teleprompter"). **UNVERIFIED — the claims were not read**;
  settle with counsel before marketing this as eye-contact correction. Apache-2.0 §3
  grants only contributors' patents, nothing against third parties.
* Upstream now also publishes `face_detection_yunet_2026may.onnx`. Our pin is
  `2023mar`; that is a deliberate pin to record, not an accident.

## 3. OWNER DECISION OPEN — a higher-quality engine

The geometric engine has a **hard quality ceiling** (§4). If the product promise is
"locked to the lens from any angle", geometry does not meet it. The only near-miss
permissive option is **LivePortrait**, and only via the excision its own LICENSE
prescribes:

1. delete the bundled `insightface/` non-commercial detector models,
2. substitute a permissive detector (YuNet is already vendored here, so this is
   mechanical), then
3. the remaining ~636 MB of Kuaishou weights are separate files under the MIT card.

**This lane did NOT adopt it.** It is a portrait *animator* with gaze controls rather
than an eye-contact corrector, it is GPU-oriented and ~636 MB, and its training-data
provenance is **UNVERIFIED — settle by reading arXiv:2407.03168**. Adopting a
generative face model is a licence-and-ethics decision for the owner, not a default
an implementation lane should take silently.

## 4. Honest quality position — what this can and cannot do

**NOT-CHECKED on real footage.** No real video was processed: there is no GPU in this
lane and the suite is hermetic (`sidecar/tests/_hermetic.py` blocks egress, so weights
cannot be fetched in a test). Nothing here should be read as "gaze correction works on
real speakers".

**What IS executably verified** (`test_gaze_geometry.py`): the geometry is
self-consistent and the warp displaces pixels as specified. A synthetic eye with a dark
iris disc at a known offset is run through the real locator and the real warp map, and
the iris **moves by the requested shift** while the patch border stays byte-identical.
Zero shift yields a pixel-exact identity map.

**What is NOT established, and cannot be by this suite:** that the result looks natural
to a human. That is perceptual, and the settling experiment is explicit — process real
talking-head footage at several strengths and yaw angles, then run a side-by-side
human A/B against the source. Until that is done, treat quality as unmeasured.

**Known hard limits** (these are properties of the approach, not bugs):

* **~10-15° ceiling.** A warp cannot *synthesise* sclera, it stretches it. Push past
  that and you get the "melted eye" artifact.
* **Specular catchlights slide** off the pupil with the warp; there is no relighting.
* **No eyelid reshaping.** YuNet supplies no eyelid contour, so a redirect that would
  physiologically change the lid aperture cannot be represented.
* **No measured iris radius.** YuNet gives 5 coarse keypoints, not an iris contour, so
  the warp radius is derived from the eye-crop size rather than a detected iris.
* Glasses (frame edges and highlights warp like anything else), large head yaw, heavy
  eyelid occlusion, motion blur, and very low-resolution faces are NOT handled.

A reviewer correctly flagged that YuNet's 2 eye-centre points are far coarser than
MediaPipe's 10 iris landmarks. **Settled:** the warp does not use YuNet landmarks as
the iris position. YuNet supplies only (a) eye-region placement and (b) interocular
scale; the iris itself is located from **pixels** by `locate_iris` (darkest-quantile
weighted centroid), so landmark coarseness is absorbed by a crop box that is ~0.34×
interocular — much larger than the landmark error. The residual cost of using YuNet is
the missing *contour* information listed above, not iris position.

Design choices that follow from this, all pinned by tests: displacement capped at 12%
of interocular distance; default strength 0.7 rather than 1.0; a rigid warp core with a
smoothstep to exactly zero at the radius so eyelids never move; and per-face gating
that leaves a rejected frame **pristine** rather than mangled. Skipping is always
preferred to a bad warp.

## 5. The ethics gate, and what still needs reconciling

`gaze.run` is gated by `models/likeness.py`. It is **fail closed**: absent, `false`,
truthy-but-not-`True`, or malformed attestation state at any level all deny. The gate
runs BEFORE the media path is resolved and BEFORE any backend is constructed — the test
asserts the backend **factory was never called** on an unattested request, not merely
that an error was raised. Every successful run records `{subject, scope, source}` as an
audit trail of which attestation authorised altering that person's face.

This is deliberately NOT the per-provider egress consent in `models/consent.py`: that
answers "may this payload leave the machine", while this answers "may we alter this
person's likeness at all" — which stays required even for a fully offline run, because
the harm is the altered artifact, not the transport.

**RECONCILIATION REQUIRED BEFORE MERGE.** At `caf103ce` no likeness attestation existed
anywhere: `features/tts/voices.py` has none, `VoiceSample` is still
`{id, name, path, durationSec}`, and the sibling `feat/v15-voice-consent-gate` branch
had **zero commits** beyond main. So this lane defined the gate it requires rather than
waiting. Two open items for whoever lands the shared consent surface (WU-A2):

1. **`SCOPE_VOICE` already exists in `models/likeness.py`** so the voice-clone lane can
   adopt this module instead of growing a second, divergent gate. Scopes are
   independent — a face-alteration grant must never authorise a voice clone.
2. **There is no persisted-grant SETTER or UI, deliberately.** No
   `settings_store.DEFAULT_SETTINGS` entry was added because that key is parity-asserted
   against a typed `Settings` model (`sidecar/tests/test_contract_parity.py`), and the
   setter plus its consent UI belong to the shared lane. The gate reads defensively, so
   it is correct — and closed — before the setter exists. Until then the usable path is
   the explicit per-request attestation (`likenessAttested` + `likenessSubject`).

## 6. RPC surface

| Method | Shape | Notes |
|---|---|---|
| `gaze.probe` | `{}` -> `{available}` | direct-return, offline; false when the YuNet asset is absent so the UI can disable the control |
| `gaze.run` | `{videoId\|path, strength?, likenessAttested?, likenessSubject}` -> `{jobId}` | `job.done.result` = `{path, strength, report, likeness}`; refuses without an attestation |

`report` is `{framesTotal, framesCorrected, eyesCorrected, skipped}` — `skipped` counts
per reason (`low-confidence`, `eyes-too-small`, `extreme-roll`), so a run that corrected
almost nothing says so instead of reporting a bare success. An explicit request with the
YuNet asset missing fails with a typed `GazeUnavailableError` naming it, never a silent
pass-through.
