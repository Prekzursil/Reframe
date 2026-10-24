# AGENTS.md

`Prekzursil/Reframe` is governed by
[quality-zero-platform](https://github.com/Prekzursil/quality-zero-platform)
(QZP). These rules bind every contributor, human or automated:

- **Verify before claiming completion:** run `bash scripts/verify`. It runs
  every lane of the QZP lean gate at the exact commit CI pins. A finding of
  any severity is a failure.
- **Never weaken a gate to pass it:** no lowered thresholds, no new
  suppressions or allowlist entries, no skipped or deleted tests. Fix the
  code, or fix the gate in QZP (see [CONTRIBUTING.md](CONTRIBUTING.md)).
- **Tests ship with the change:** 100 % line **and** branch coverage.
- **Never push to `main`:** every change lands through a pull
  request whose required checks are green.
- **Security findings go private:** follow [SECURITY.md](SECURITY.md).
