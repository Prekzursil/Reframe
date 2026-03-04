# Coverage + Desktop Wave Baseline (2026-03-04)

## Branch and Commit
- branch: $branch
- head: $head

## Coverage Truth Baseline
- codecov.yml currently ignored major first-party paths (pps/api/**, services/worker/**, packages/media-core/**, scripts/**) and key web source files.
- pps/web/vite.config.ts currently excluded core product modules from coverage.
- pps/desktop/vitest.config.ts currently had ranches: 0 while other thresholds were 100.

## Desktop Release Baseline
- release: $(@{assets=System.Object[]; isPrerelease=True; publishedAt=03/03/2026 00:41:30; tagName=desktop-v0.1.8; url=https://github.com/Prekzursil/Reframe/releases/tag/desktop-v0.1.8}.tagName)
- prerelease: $(@{assets=System.Object[]; isPrerelease=True; publishedAt=03/03/2026 00:41:30; tagName=desktop-v0.1.8; url=https://github.com/Prekzursil/Reframe/releases/tag/desktop-v0.1.8}.isPrerelease)
- published at: $(@{assets=System.Object[]; isPrerelease=True; publishedAt=03/03/2026 00:41:30; tagName=desktop-v0.1.8; url=https://github.com/Prekzursil/Reframe/releases/tag/desktop-v0.1.8}.publishedAt)
- url: https://github.com/Prekzursil/Reframe/releases/tag/desktop-v0.1.8
- asset count: 17

### Windows assets present
- `Reframe_0.1.8_x64-setup.exe` -> https://github.com/Prekzursil/Reframe/releases/download/desktop-v0.1.8/Reframe_0.1.8_x64-setup.exe
- `Reframe_0.1.8_x64-setup.exe.sig` -> https://github.com/Prekzursil/Reframe/releases/download/desktop-v0.1.8/Reframe_0.1.8_x64-setup.exe.sig
- `Reframe_0.1.8_x64_en-US.msi` -> https://github.com/Prekzursil/Reframe/releases/download/desktop-v0.1.8/Reframe_0.1.8_x64_en-US.msi
- `Reframe_0.1.8_x64_en-US.msi.sig` -> https://github.com/Prekzursil/Reframe/releases/download/desktop-v0.1.8/Reframe_0.1.8_x64_en-US.msi.sig
