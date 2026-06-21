# WIRING-U5 — Job protocol upgrade (queue + list + retry + metadata)

Unit U5 changed `sidecar/media_studio/jobs.py` + `sidecar/media_studio/protocol.py`
(+ `sidecar/tests/test_jobs.py`). This file lists everything the WIRING agent needs.

## 0. TL;DR — nothing is REQUIRED for the sidecar to work

- `job.list` and `job.retry` are **built-ins in `protocol.py`** (registered via
  `@method`, beside `job.cancel`/`job.status`). They self-register when
  `protocol` is imported — `handlers.register_all` needs **no change** for them.
- The retry source (`record_request`) is wired **inside `protocol.dispatch`**:
  every handler whose result carries a `jobId` automatically gets its
  method+params recorded on the registry. No per-handler change needed.
- **No new native modules** — `__main__._preimport_native_modules` needs **no
  additions** from U5 (stdlib only: `copy`, `time`, `threading`).
- Existing `ctx.jobs.start(handler)` call sites keep working unchanged (the
  pool spawns immediately when a slot is free; metadata defaults are
  backfilled from the recorded request).

## 1. REQUESTED: `app/renderer/src/lib/rpc.ts` (shared file — wiring owns)

Add the A3 `JobInfo` type and the two new client methods.

**(a) After the `DoneEvent` interface (the "Notification payloads" section):**

```ts
/** A3 JobInfo — one entry of `job.list`'s {jobs:[...]} payload. */
export interface JobInfo {
  jobId: string;
  feature: string;
  label: string;
  videoId?: string;
  status: 'queued' | 'running' | 'done' | 'error' | 'cancelled';
  pct: number;
}
```

**(b) Replace the `job:` block inside `export const client = {...}` with:**

```ts
  job: {
    cancel: (jobId: string): Promise<{ ok: boolean }> => rpc('job.cancel', { jobId }),
    status: (jobId: string): Promise<{ status: string; pct: number }> =>
      rpc('job.status', { jobId }),
    list: (): Promise<{ jobs: JobInfo[] }> => rpc('job.list'),
    retry: (jobId: string): Promise<{ jobId: string }> => rpc('job.retry', { jobId }),
  },
```

## 2. OPTIONAL (recommended polish): explicit metadata at `jobs.start` call sites

`JobRegistry.start` now accepts `start(handler, *, feature="", label="",
videoId=None, gpu=False)`. Without kwargs, the dispatch hook backfills
`feature` = method prefix (e.g. `"transcribe"`), `label` = method name, and
`videoId` from the request params — so job.list is already meaningful. For
nicer labels, the wiring agent MAY upgrade `handlers.py` call sites, e.g.:

```python
# handlers.py — transcribe_start (whisper is the GPU-class workload):
job = ctx.jobs.start(
    job_body,
    feature="transcribe",
    label=f"Transcribe {Path(audio_path).name}",
    videoId=video_id,
    gpu=True,
)
```

```python
# handlers.py — convert_start:
job = ctx.jobs.start(body, feature="convert", label="Convert video")
```

Notes:
- `gpu=True` serializes that job against other gpu-tagged jobs (max 1 at a
  time) while still counting toward the general pool (default 2). Recommended
  for whisper transcription and any future heavy-model job (tts dub synth,
  remotion render if GPU-bound). Untagged jobs are unaffected.
- The `videoId` kwarg name is intentionally camelCase to match the A2/A3 wire
  spelling (CONTRACT-NOTE in jobs.py).

## 3. Behavior notes the wiring/UI agents should know

- **Queue semantics:** the registry is a bounded pool — `max_workers=2`
  general slots, `max_gpu_workers=1` gpu slot (constructor kwargs on
  `JobRegistry`). Excess jobs wait with JobInfo status `"queued"` (internally
  `JobStatus.PENDING`; the legacy `job.status` RPC still reports `"pending"`
  pre-run — its §2 shape is unchanged).
- **`job.list()`** -> `{jobs:[JobInfo]}`, most-recent-first, capped at 100.
  `videoId` is omitted (not null) when unknown.
- **`job.retry({jobId})`** -> `{jobId}` (a NEW job). Works for any job whose
  originating request went through `protocol.dispatch` (i.e., every real RPC
  call). Retrying a job that was started directly on the registry (tests) is
  an INVALID_PARAMS error: "job has no stored request".
- **Cancelling a queued job** finishes it `cancelled` immediately (it never
  runs); no `job.done` is emitted for cancels (unchanged P1 behavior).
- `JobRegistry.join(timeout)` now treats `timeout` as a total deadline and
  also waits for queued jobs that have no worker thread yet.
