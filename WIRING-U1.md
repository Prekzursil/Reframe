# WIRING-U1 — Real video player + media compatibility

Unit U1 lane files (all written, tested, no shared files touched):

- `app/main/mediaProtocol.ts` (+ `app/main/mediaProtocol.test.ts`)
- `app/renderer/src/components/Player.tsx` (+ `Player.test.tsx`)
- `sidecar/media_studio/features/media_compat.py` (+ `sidecar/tests/test_media_compat.py`)

The wiring agent applies the snippets below to the SHARED files. Nothing else
is required — U1 registers no preload changes (the Player uses `<video src>`,
not IPC).

---

## 1. `app/main/main.ts` — mount the `mstream://` protocol

**(a) Module top level, BEFORE `app.whenReady()`** (Electron requires scheme
privileges to be declared before the `ready` event — put it right after the
imports):

```ts
import { registerMediaProtocol, registerMediaSchemePrivileges } from './mediaProtocol';

// mstream:// must be declared privileged BEFORE app ready (U1).
registerMediaSchemePrivileges();
```

> NOTE: `registerSchemesAsPrivileged` may only be called ONCE per app. If
> another unit ever needs its own scheme, merge the entries into this one call.

**(b) Inside `bootstrap()`, after `sidecar.start()` / `registerIpc(...)`**
(i.e. after `app.whenReady()` has fired — `bootstrap()` runs inside
`app.whenReady().then(...)`, so this is safe):

```ts
  // U1: stream local media to <video> with Range support. The resolver returns
  // the PLAYABLE path for a videoId: the cached remux/proxy when media.playable
  // reports one, otherwise the original library path.
  const sc = sidecar; // capture for the closure (sidecar is module-level let)
  registerMediaProtocol(async (videoId) => {
    if (!sc) return null;
    try {
      const verdict = await sc.request<{ playable: boolean; proxyPath?: string }>(
        'media.playable',
        { videoId },
      );
      if (verdict.proxyPath) return verdict.proxyPath;
      const { videos } = await sc.request<{ videos: { id: string; path: string }[] }>(
        'library.list',
      );
      return videos.find((v) => v.id === videoId)?.path ?? null;
    } catch {
      return null; // resolver failure -> handler responds 404 (never hangs)
    }
  });
```

Why `media.playable` first: it is a cheap ffprobe sniff (and a pure cache
lookup once a proxy exists), and it makes proxy pickup automatic — after a
`media.proxy.start` job completes, the next `<video>` load of the SAME
`mstream://media/<id>` URL transparently streams the cached proxy. The UI only
needs to reload the video element (set `src` again or call `load()`).

## 2. `sidecar/media_studio/handlers.py` — register the A2 methods

In the imports block:

```python
from .features import media_compat as _media_compat
```

In `register_all(...)`, next to the other feature registrations (media_compat
ships its own imperative `register()` per the U-unit convention — pass the
test-injectable registrar through):

```python
    _media_compat.register(
        resolver=svc._resolve_video_path,
        settings_provider=svc.settings.get,
        register_fn=reg,
    )
```

Optional seams (used by `test_media_compat.py`, available if `Services` ever
wants to own them): `proxies_dir=...`, `probe=...`, `run=...`. Defaults:
proxies cache at `%APPDATA%/media-studio/proxies` (same
`settings_store.default_config_dir()` root), real ffprobe sniff, real
`ffmpeg.run` (stderr-drained).

## 3. `sidecar/media_studio/__main__.py` — pre-imports

**No change needed.** U1 uses only ffmpeg/ffprobe subprocesses; no new native
module enters any job body (A6 lesson 1 checked: nothing to add to
`_preimport_native_modules`).

## 4. `app/renderer/src/lib/rpc.ts` — optional typed surface

If the typed client mirrors methods, add:

```ts
export interface MediaPlayableResult {
  playable: boolean;
  reason?: string;
  proxyPath?: string;
}
// media.playable({videoId})    -> MediaPlayableResult        (direct)
// media.proxy.start({videoId}) -> {jobId} -> job.done {path} (job)
```

## 5. How Workspace gets the Player

`Player` is a self-contained component in `src/components/Player.tsx`
(default + named export; no new deps). Suggested Workspace mount — a player
strip above the existing `TabBar` (Workspace.tsx is U-shared, so the wiring
agent owns the actual placement):

```tsx
import { Player } from '../components/Player';
import { rpc } from '../components/api';
```

```tsx
  // Inside the Workspace component:
  const [playerNote, setPlayerNote] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    rpc<{ playable: boolean; reason?: string; proxyPath?: string }>('media.playable', {
      videoId: video.id,
    })
      .then((v) => {
        if (!alive || v.playable) return;
        setPlayerNote(v.reason ?? 'building playback proxy…');
        // Kick the proxy build; progress can ride the shared useJob/toast path.
        return rpc<{ jobId: string }>('media.proxy.start', { videoId: video.id });
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [video.id]);
```

```tsx
  <div className="workspace__player">
    <Player videoId={video.id} key={video.id} />
    {playerNote ? <div className="workspace__player-note">{playerNote}</div> : null}
  </div>
```

After the proxy job's `job.done`, remount/reload the player (e.g. bump a
`key`/state) — the mstream resolver then serves the cached proxy for the same
URL. Operations (convert/burn/export) MUST keep using the original path; the
proxy is playback-only.

## 6. How ShortMaker previews a candidate window

`Player` window mode plays exactly `sourceStart → sourceStart + durationSec`
(seeks the in-point once metadata is ready, stops + snaps at the out-point,
optional loop). Candidate preview:

```tsx
import { Player, type PlayerHandle } from '../components/Player';
```

```tsx
  const previewRef = useRef<PlayerHandle>(null);

  {selected ? (
    <Player
      ref={previewRef}
      videoId={videoId}
      window={{ start: selected.sourceStart, end: selected.sourceStart + selected.durationSec }}
      autoPlay
      loop={false}
      controls
    />
  ) : null}
```

Imperative surface for keyboard review (`PlayerHandle`): `play()`, `pause()`,
`seek(t)` / `scrub(t)` (both clamp into the active window), `currentTime()`,
`isPlaying()`, `element()`.

## 7. Contract notes / assumptions made in this lane

- URL shape is `mstream://media/<encodeURIComponent(videoId)>` — the fixed
  `media` host keeps the id in the path because a `standard:true` scheme
  lower-cases its host during normalization. `Player.mediaUrl()` and
  `mediaProtocol.videoIdFromUrl()` are the two ends of this frozen seam (the
  bare `mstream://<id>` host form is also accepted for lowercase ids).
- Range handling follows RFC 7233 single-range: open-ended `bytes=0-`
  (Chromium always sends it) and bounded/suffix forms → 206 + Content-Range;
  malformed/multi-range → 200 full; unsatisfiable → 416 `bytes */size`.
- `media.proxy.start` on an ALREADY-playable source returns the original path
  as `{path}` (nothing to build) — A2 only types the result as `{path}`.
- Proxy cache key = sanitized videoId + source `st_mtime_ns`; stale-mtime
  siblings are evicted after a successful build; builds go to a `.partial.mp4`
  then `os.replace` so a crash/cancel never publishes a torn file.
- The remux derivative drops subtitle/data/attachment streams (`-map -0:s
  -0:d -0:t`): mkv subtitle codecs are not mp4-legal under `-c copy`, and
  track operations read the ORIGINAL file anyway.
