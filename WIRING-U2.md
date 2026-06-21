# WIRING-U2 — Import UX: native picker + drag-drop

Unit U2 lane files (already written, no action needed): `app/main/dialogIpc.ts` (+ `dialogIpc.test.ts`),
`app/renderer/src/views/Library.tsx` (+ `Library.test.tsx`). This document lists the EXACT changes the
WIRING agent must apply to the shared files (`app/main/preload.ts`, `app/main/main.ts`, optionally
`app/renderer/src/lib/rpc.ts`, `App.tsx`).

No sidecar changes. No new JSON-RPC methods. No native modules to pre-import.
`dialog.openVideos` is a plain Electron ipc channel handled in the MAIN process — it never reaches
`protocol.py`.

---

## 1. `app/main/preload.ts` — expose `openVideos` + `pathForFile`

> Electron >= 32 removed the Chromium `File.path` extension. Dropped `File` objects can ONLY be
> resolved to filesystem paths via `webUtils.getPathForFile(file)` in the PRELOAD (it is in the
> sandboxed-preload module allowlist; available since Electron 29, so it also works on the currently
> pinned ^31). `Library.tsx` calls `window.api.pathForFile(file)` and falls back to legacy
> `file.path` only when this bridge is absent.

**1a. Replace the electron import line** (currently line 19):

```ts
import { contextBridge, ipcRenderer, webUtils, type IpcRendererEvent } from 'electron';
```

**1b. Add the channel constant** below the existing channel consts (`RPC_CHANNEL` / `PROGRESS_CHANNEL` / `DONE_CHANNEL`):

```ts
const DIALOG_OPEN_VIDEOS_CHANNEL = 'dialog.openVideos'; // must match app/main/dialogIpc.ts
```

**1c. Extend the `MediaApi` interface** (add after the `onJobDone` member):

```ts
  /** Native multi-select video picker; resolves with absolute paths ([] when cancelled). */
  openVideos(): Promise<string[]>;
  /**
   * Resolve a dropped File to its absolute filesystem path.
   * Electron >=32 removed File.path — webUtils.getPathForFile is the only path bridge.
   */
  pathForFile(file: File): string;
```

**1d. Extend the `api` object literal** (add after the `onJobDone` implementation, inside `const api: MediaApi = { ... }`):

```ts
  openVideos(): Promise<string[]> {
    return ipcRenderer.invoke(DIALOG_OPEN_VIDEOS_CHANNEL) as Promise<string[]>;
  },

  pathForFile(file: File): string {
    return webUtils.getPathForFile(file);
  },
```

---

## 2. `app/main/main.ts` — register the dialog handler

**2a. Add the import** (next to `import { registerIpc } from './ipc';`):

```ts
import { registerDialogIpc } from './dialogIpc';
```

**2b. Add module state** (next to `let disposeIpc: (() => void) | null = null;`):

```ts
let disposeDialogIpc: (() => void) | null = null;
```

**2c. In `bootstrap()`**, immediately after `disposeIpc = registerIpc(sidecar, liveWindows);`:

```ts
  disposeDialogIpc = registerDialogIpc();
```

**2d. In the `app.on('will-quit', ...)` handler**, next to the existing `disposeIpc` teardown:

```ts
  if (disposeDialogIpc) {
    disposeDialogIpc();
    disposeDialogIpc = null;
  }
```

---

## 3. OPTIONAL — canonical typing in `app/renderer/src/lib/rpc.ts` (wiring-owned)

`Library.tsx` reads `window.api.openVideos` / `window.api.pathForFile` STRUCTURALLY (safe cast with
runtime `typeof` checks), so nothing breaks if this step is skipped. For canonical typing, add the two
members to the `MediaApi` interface in `lib/rpc.ts` (and mirror in `components/api.ts` if desired) as
OPTIONAL members, so tests/SSR contexts without the bridge still typecheck:

```ts
  openVideos?(): Promise<string[]>;
  pathForFile?(file: File): string;
```

---

## 4. OPTIONAL — U3 toast integration in `App.tsx` (wiring-owned)

`Library` accepts an optional prop:

```ts
toast?: (toast: { kind: 'error' | 'success' | 'info'; message: string }) => void;
```

- **Without the prop** (current state): Library renders its own local fallback toast strip
  (`.library__toasts`, auto-expiring, dismissable) — no action required, nothing is silent.
- **When U3's toast system lands**: adapt U3's `useToast` to that shape and pass it down, e.g.

```tsx
// inside the U3 ToastProvider-wrapped tree:
const toast = useToast(); // U3 hook — adapt the call below to U3's actual surface
<Library onOpen={openVideo} toast={(t) => toast.show(t.kind, t.message)} />
```

(The adapter shape above is U2's only assumption; U3's real API was not frozen in CONTRACTS.md, so the
wiring agent owns the one-line adaptation.)

---

## 5. Conformance notes

- Channel name `dialog.openVideos` is defined in BOTH `dialogIpc.ts` (exported const
  `DIALOG_OPEN_VIDEOS_CHANNEL`) and the preload snippet (1b) — keep them identical.
- `registerDialogIpc()` returns a disposer (same pattern as `registerIpc`).
- Picker returns `[]` on cancel; Library treats `[]` as a no-op (no toast, no rpc call).
- Multi-add = one `library.add({path})` per picked/dropped path, sequential; per-file failures emit
  typed error toasts and the batch CONTINUES; successful inserts de-dupe by video `id`.
