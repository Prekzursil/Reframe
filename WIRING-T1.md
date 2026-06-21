# WIRING-T1 — Timeline subtitle editor

Unit T1 lane files (all written, tested, no shared files touched):

- `sidecar/media_studio/features/timeline.py` (+ `sidecar/tests/test_timeline.py`)
- `app/renderer/src/lib/timelineOps.ts` (+ `timelineOps.test.ts`)
- `app/renderer/src/features/Timeline.tsx` (+ `Timeline.test.tsx`)

The wiring agent applies the snippets below to the SHARED files.

**Native pre-imports (A6 lesson 1): NONE.** `timeline.py` is stdlib-only
(array/json/tempfile) — no addition to `__main__._preimport_native_modules`.

---

## 1. `sidecar/media_studio/handlers.py` — register `timeline.peaks`

In the imports block:

```python
from .features import timeline as _timeline
```

In `register_all(...)`, next to the other feature registrations (timeline
ships its own imperative `register()` per the unit convention — pass the
test-injectable registrar through):

```python
    _timeline.register(
        resolver=svc._resolve_video_path,
        settings_provider=svc.settings.get,
        register_fn=reg,
    )
```

`timeline.peaks` is a DIRECT-RETURN method (A2: no jobId), so nothing
job-registry-related is needed. The peaks cache lives in
`%APPDATA%/media-studio/peaks/<videoId>.json` (via
`settings_store.default_config_dir()`, so the `MEDIA_STUDIO_CONFIG_DIR` env
override used by tests redirects it automatically).

## 2. `app/renderer/src/lib/rpc.ts` — typed client method

Add to the `client` object (next to `tracks`):

```ts
  timeline: {
    peaks: (videoId: string): Promise<{ sampleRate: number; peaks: number[] }> =>
      rpc('timeline.peaks', { videoId }),
  },
```

## 3. `app/renderer/src/views/Workspace.tsx` — mount the Timeline panel

Following Workspace's existing `lazyPanel` pattern, declare the panel props
and lazy import:

```tsx
interface TimelinePanelProps {
  videoId: string;
  durationSec?: number;
  playerRef?: React.RefObject<PlayerHandle | null>;
  onSeek?: (timeSec: number) => void;
}
const TimelinePanel = lazyPanel<TimelinePanelProps>('../features/Timeline', 'Timeline');
```

Add a tab `{ id: 'timeline', label: 'Timeline' }` to the TabBar defs and
render the panel:

```tsx
<TimelinePanel
  videoId={video.id}
  durationSec={video.durationSec}
  playerRef={workspacePlayerRef}
/>
```

- `workspacePlayerRef` is the ref Workspace holds on the U1 `<Player>`
  (`useRef<PlayerHandle | null>(null)` passed as `<Player ref={...}>`).
  Timeline lane clicks call `playerRef.current.seek(t)` — that is the whole
  click-to-seek integration. If the Workspace player lives in a different tab
  and is unmounted, Timeline degrades gracefully (ref `current` is null; the
  optional `onSeek` callback can be wired instead if the Workspace wants to
  switch tabs + seek).
- `durationSec` should be passed (the Video row has it). Without it Timeline
  falls back to one extra `library.list` call, then to the cue extent.
- Timeline reads the bridge via `features/_api.getApi()` by default; no
  `preload.ts` / `main.ts` / `ipc.ts` changes are needed (one new sidecar
  method rides the existing generic `rpc` forwarding).

## 4. CONTRACTS conformance notes

- Method name registered: exactly `timeline.peaks` (A2). Result shape:
  `{sampleRate:int, peaks:[float 0..1]}`.
- CONTRACT-NOTE (documented in `timeline.py`): A2 leaves `sampleRate`
  semantics open; it is the PCM rate the peaks were computed from (8000).
  Peaks span the audio uniformly: bucket `i` -> `i / peaks.length *
  durationSec`.
- Saving goes through the EXISTING `subtitles.edit({trackId, cues})` (§2) and
  loading through `tracks.list({videoId})` — no new methods beyond A2.
