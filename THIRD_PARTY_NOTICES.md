# Third-party notices

Reframe's own source code is licensed under the MIT License (see `LICENSE`).
That license does **not** apply to the third-party components below. Each one stays
under its own license. See the upstream licenses and the detailed notices already in
this repository:

- `NOTICE`: bundled ML models and fonts, with attributions
- `docs/THIRD-PARTY-LICENSES.md`: redistributed binaries and the FFmpeg written source offer
- In-app: Settings → Licenses (`app/renderer/src/features/ThirdPartyNotices.tsx`)

## Redistributed in the Windows build (per `electron-builder.yml`)

| Component | License (see upstream) | Where |
|---|---|---|
| FFmpeg / FFprobe (BtbN win64 GPL static build, version pinned in `docs/THIRD-PARTY-LICENSES.md`) | GPL (see upstream); run as a separate process, not linked | `resources/bin/` |
| Embeddable CPython (python.org) | PSF License (see upstream) | `resources/python/`, `resources/python-chatterbox/` |
| Remotion render CLI and its dependencies | see upstream licenses | `resources/render-cli/` |

## Models and fonts (listed in `NOTICE`)

- ViNet-S / ViNet: CC-BY-NC-SA-4.0. **Non-commercial**: while it is included, Reframe as shipped is non-commercial.
- YuNet: MIT · EdgeTAM: Apache-2.0 · TransNetV2: MIT · LR-ASD: MIT
- Inter, Newsreader, IBM Plex Mono: SIL OFL 1.1

Vendored code with its own license files: `sidecar/media_studio/features/_vinet_s/`,
`_transnetv2/`, `_lightasd/`, and `vendor/remotion-captions/`.

Model weights and Python packages installed on first run are downloaded from their
upstream sources and are governed by their own licenses.
