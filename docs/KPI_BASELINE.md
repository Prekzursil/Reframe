# KPI Baseline (Phase 3/4)

This document defines the weekly KPI baseline for AI-assisted engineering operations.

## Core metrics

1. Intake-to-PR lead time
2. PR cycle time
3. Queue failure rate
4. Agent rework rate
5. Evidence completeness rate
6. Regression incident count

## Collection cadence

- Weekly digest issue generated automatically.
- Human reviewer validates outliers and annotates root causes.
- Metrics are compared week-over-week to detect drift.

## Operating notes

- Keep merges human-reviewed.
- Treat failed deterministic verification as a hard stop.
- Use risk labels consistently (`risk:low`, `risk:medium`, `risk:high`).
