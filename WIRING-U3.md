# WIRING-U3 — app-wide toast/error surface (for the WIRING agent)

U3 lane files (already written, nothing to change there):
- `app/renderer/src/components/toast/ToastProvider.tsx` (context + reducer + auto-dismiss)
- `app/renderer/src/components/toast/useToast.ts` (`useToast` / `useToastOptional`)
- `app/renderer/src/components/toast/ToastHost.tsx` (portal into document.body)
- `app/renderer/src/components/toast/toast.css`
- `app/renderer/src/components/toast/toast.test.tsx`
- `app/renderer/src/components/useJob.ts` (upgraded: job.done error payload -> error toast + onError hook + loose Retry wiring)
- `app/renderer/src/components/useJob.test.tsx`

No preload/main/sidecar changes are needed — the existing `window.api.onJobDone`
relay (preload.ts / ipc.ts / sidecar.ts) already carries `job.done`.

## 1. REQUIRED — mount ToastProvider + ToastHost in `App.tsx`

Add these imports to `app/renderer/src/App.tsx` (next to the existing
`./components/shell.css` import — App.tsx owns top-level CSS imports):

```tsx
import { ToastProvider } from './components/toast/ToastProvider';
import { ToastHost } from './components/toast/ToastHost';
import './components/toast/toast.css';
```

Then wrap the existing `App` return value (current body unchanged) and add the
host as a sibling of the app div, inside the provider:

```tsx
  return (
    <ToastProvider>
      <div className="app">
        <header className="app__bar">
          <span className="app__brand">media-studio</span>
          <QualityToggle quality={quality} onChange={changeQuality} />
        </header>

        <main className="app__main">
          {route.name === 'library' ? (
            <Library onOpen={openVideo} />
          ) : (
            <Workspace video={route.video} onBack={backToLibrary} />
          )}
        </main>
      </div>
      <ToastHost />
    </ToastProvider>
  );
```

`ToastHost` portals into `document.body`, so its position in JSX only matters
for context access — it must sit INSIDE `<ToastProvider>`.

## 2. REQUIRED once U5's `job.retry` ships — register the retry callable

The Retry button on error toasts appears ONLY when a retry callable is
registered (feature-detection by callable, per the U3 spec). After U5's
`job.retry({jobId}) -> {jobId}` RPC (A2) is registered in `handlers.register_all`,
add this once at renderer bootstrap (e.g. top of `App.tsx` module scope or in
`main.tsx`):

```tsx
import { registerJobRetry } from './components/useJob';
import { rpc } from './lib/rpc';

registerJobRetry((jobId) => rpc<{ jobId: string }>('job.retry', { jobId }));
```

If U5 has not landed, simply omit this — the Retry button stays hidden and
everything else works. (Alternative seam: exposing a `jobRetry(jobId)` callable
on the preload bridge is also auto-detected by `resolveJobRetry()`.)

## 3. OPTIONAL — barrel exports in `components/index.ts`

For convenience (not required by any current import):

```ts
export {
  ToastProvider,
  DEFAULT_DURATION_MS,
  type Toast,
  type ToastApi,
  type ToastKind,
  type ToastAction,
  type ToastOptions,
} from './toast/ToastProvider';
export { ToastHost } from './toast/ToastHost';
export { useToast, useToastOptional } from './toast/useToast';
export {
  registerJobRetry,
  resolveJobRetry,
  featureLabel,
  extractJobError,
  type UseJobOptions,
  type JobError,
  type JobRetryFn,
} from './useJob';
```

## Behavior notes (so wiring can sanity-check)

- `useJob` now: on `job.done` for ITS active job — success finishes the job
  (running=false, pct=100); the A3 error payload (`result.error.{message,type}`)
  sets `state.error`, fires `options.onError(JobError)`, and (when a provider is
  mounted) shows a sticky error toast `"<Feature label> failed: <message>"`.
  `type === 'JobCancelled'` finishes quietly (cancel is not a failure).
- Feature labels derive from the rpc method prefix (`transcribe.` -> "Transcribe",
  `tts.` -> "Dub", etc.); `useJob({ label })` overrides.
- Toast defaults: info/success auto-dismiss after 5s; errors sticky until
  dismissed; explicit `durationMs` (or `null`) overrides. Action buttons dismiss
  their toast after invoking the action.
- Sidecar RPC methods registered by U3: none. Native modules needing
  `__main__` pre-import from U3: none (renderer-only unit).
