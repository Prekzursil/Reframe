// windowsBroadcast.ts — the shared notification fan-out to live renderer windows.
//
// Every `broadcast*` helper in main.ts (bootstrap progress/error, the WU-1a
// provisioning signal, playback-proxy state, auto-update status) pushes a payload
// to each renderer. This centralises the identical "skip a window whose
// webContents was destroyed mid-flight" guard so it lives in ONE tested place
// instead of being duplicated per broadcaster. Pure over the window list — the
// caller passes an already-filtered live-WINDOW list (main.ts `liveWindows()`
// drops destroyed windows); this additionally guards a destroyed webContents,
// which a window can have transiently while it is being torn down.
import type { BrowserWindow } from 'electron';

/**
 * Send `payload` on `channel` to every window whose webContents is still alive.
 * A window with a destroyed webContents is skipped (its `.send` would throw).
 */
export function broadcastToLiveWindows(
  windows: readonly BrowserWindow[],
  channel: string,
  payload: unknown,
): void {
  for (const win of windows) {
    if (!win.webContents.isDestroyed()) {
      win.webContents.send(channel, payload);
    }
  }
}
