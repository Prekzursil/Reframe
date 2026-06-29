# WU R0 — ML Eval Harness (the regression gate R1 must clear)

**Status:** implemented on `feat/v1.1.0`.
**Module:** `sidecar/media_studio/features/reframe_eval.py` ·
**Pure tier:** `sidecar/tests/test_reframe_eval.py` (100% line+branch, in the gate) ·
**GPU/real-frame tier:** `sidecar/tests/test_reframe_eval_golden_e2e.py` (`@e2e`, NOT in the gate) ·
**RPC:** `reframe.eval` · **CLI:** `python -m media_studio.features.reframe_eval`

R0 is the **prerequisite gate for R1**: the hybrid multi-speaker engine may only be
promoted to a default once a run of this harness on the golden set returns
`passed: true`. See the design decision in basic-memory note
`reframe-multi-speaker-engine-approach-decided-hybrid` and `docs/V1.1-FEATURES.md`
§GATE-2 (R0 private-data hygiene).

## 1. Two tiers (private data + heavy deps stay OUT of the 100% gate)

| Tier | What runs | In the coverage gate? | Needs the golden set? |
|------|-----------|-----------------------|-----------------------|
| **Pure** | every metric + validators + gate + RPC + CLI, on synthetic path-injected fixtures | **Yes** (100% line+branch) | **No** |
| **GPU / real-frame** | harness against the real OpusClip golden set (`@pytest.mark.e2e`) | **No** (`addopts = -m 'not e2e'`) | Yes (opt-in) |

**Golden-set hygiene (mechanically enforced).** The golden reference — the private
`razvan_gandu` RO talk-show + OpusClip's 41 derived clips — is third-party and is
**never committed**:

- The GPU tier sources it from the **`REFRAME_GOLDEN_DIR` env var** (an external,
  gitignored path) — never a committed repo-relative path.
- `.gitignore` carries `razvan_gandu/` (+ `**/razvan_gandu/`, `testdata/razvan_gandu/`)
  to defend against an accidental repo-relative copy.
- The GPU tier is **collection-guarded**: it `pytest.skip`s when `REFRAME_GOLDEN_DIR`
  is unset or the path is absent, so CI never imports or requires the private bytes.
- The pure tier proves every metric on synthetic fixtures, so 100% holds without the
  golden set ever being present.

Run the GPU tier on a machine that has the set:

```
REFRAME_GOLDEN_DIR=/path/to/razvan_gandu pytest -m e2e tests/test_reframe_eval_golden_e2e.py
```

## 2. Data contract (the committed shapes)

A **trace** (`ReframeTrace`) is one clip's engine output OR the golden reference; the
harness compares two. JSON shape (camelCase on the wire; loud `HarnessError` on any
bad shape):

```jsonc
{
  "shotBoundaries": [30, 90],                 // int frame indices of hard cuts
  "speakerPerFrame": ["a", "a", "b", ...],    // active-speaker id per frame ("" = none)
  "segments": [                               // per-segment layout decisions
    {"startFrame": 0, "endFrame": 30, "layout": "single"}   // [start, end); no overlap
  ],
  "crops": [[x, y, w, h], ...]                // per-frame crop rectangle
}
```

- `layout` ∈ `{single, split, composite}`; frames no segment covers default to `none`.
- Segments must be a clean partition: an out-of-range or overlapping segment raises.
- The **reference** defines the canonical frame count; the predicted trace's
  `speakerPerFrame` and `crops` must match that length (loud otherwise).

## 3. Metrics

| Metric | Function | Meaning |
|--------|----------|---------|
| Shot-boundary F1 | `shot_boundary_f1` | cut detection P/R/F1, greedy ±2-frame match |
| Layout match | `layout_match_accuracy` | per-frame single/split/composite agreement |
| Switch latency | `switch_latency` | ms lag of predicted speaker switches vs reference (∞ on a missed switch) |
| Static-shot jitter | `static_shot_jitter` | mean per-frame crop-centre travel (lower = stiller) |
| Crop IoU | `crop_iou` / `mean_crop_iou` | intersection-over-union vs the reference rect |
| Speaker attribution | `speaker_attribution_accuracy` | per-frame active-speaker agreement |

## 4. Gate thresholds (deterministic — no "~0.9" / "within tolerance")

`GATE_THRESHOLDS` in `reframe_eval.py`. `passed` = the AND of every check.

| Gate key | Threshold | Direction | Rationale |
|----------|-----------|-----------|-----------|
| `shot_f1_min` | **0.90** | ≥ | design note "shot-boundary F1 ≥ ~0.9", pinned to 0.90 |
| `layout_match_min` | **0.85** | ≥ | per-frame layout-agreement floor |
| `switch_latency_max_ms` | **150.0** | ≤ (max) | design note "switch latency < 150 ms" |
| `speaker_attr_min` | **0.80** | ≥ | active-speaker accuracy, within tolerance of OpusClip |
| `crop_iou_min` | **0.60** | ≥ | crop overlap vs the reference rect |
| `static_jitter_max` | **3.1739130434782608** | ≤ | the **captured current-engine baseline** (below) |

### Captured current-engine jitter baseline

`STATIC_JITTER_BASELINE = 3.1739130434782608` is the mean per-frame crop-centre
travel the **shipped single-speaker engine** (`reframe_claudeshorts.smooth_centers`)
produces on the canonical `BASELINE_SWAY_CENTERS` track (a seated talking head
drifting ±0.03 normalised-x sinusoidally over 24 windows) at 1920×1080 → 9:16. The
hybrid engine **must not regress it** (`static_jitter_max`). The value is an exact
rational of integer pixel positions (so byte-reproducible across platforms), and
`test_reframe_eval.py::test_static_jitter_baseline_matches_current_engine`
**re-derives it from the real engine** and asserts equality — a change to the
smoother trips the guard rather than silently drifting the gate.

## 5. CLI / RPC

- **RPC** `reframe.eval({predicted, reference, fps?})` → the metric report (pure;
  a bad trace surfaces as `INVALID_PARAMS`).
- **CLI** scores a predicted trace, or runs an engine seam, vs a golden reference:

  ```
  # score two trace files
  python -m media_studio.features.reframe_eval --reference ref.json --predicted pred.json [--fps 30] [--out report.json]
  # run an engine on a source first (seam UNWIRED at R0 — R1 wires the real runner)
  python -m media_studio.features.reframe_eval --reference ref.json --source clip.mp4 --engine multispeaker
  ```

  Exit code: `0` = gate passed, `1` = gate failed, `2` = usage error — usable
  directly as the R1 regression gate. The `--source/--engine` path runs through an
  injectable seam; at R0 the default runner fails **loud** (no silent fabricated
  trace) — R1 wires the real engine, or a caller/e2e tier injects one.
