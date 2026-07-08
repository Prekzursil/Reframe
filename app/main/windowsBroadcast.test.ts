// windowsBroadcast.test.ts — the shared notification fan-out behind every main.ts
// `broadcast*` helper (WU-1a review LOW: pin the provisioning fan-out). Pure over
// the window list (no Electron runtime needed — BrowserWindow is a type-only
// import), so fake windows exercise both the live-send path and the
// destroyed-webContents skip guard.
import { describe, it, expect, vi } from 'vitest';
import type { BrowserWindow } from 'electron';
import { broadcastToLiveWindows } from './windowsBroadcast';

/** A fake window whose webContents reports `destroyed` and records `.send` calls. */
function fakeWindow(destroyed: boolean): { win: BrowserWindow; send: ReturnType<typeof vi.fn> } {
  const send = vi.fn();
  const win = {
    webContents: { isDestroyed: () => destroyed, send },
  } as unknown as BrowserWindow;
  return { win, send };
}

describe('broadcastToLiveWindows', () => {
  it('sends the payload on the channel to a live window (the provisioning fan-out)', () => {
    const { win, send } = fakeWindow(false);
    const payload = { active: true };
    broadcastToLiveWindows([win], 'provisioning.state', payload);
    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith('provisioning.state', payload);
  });

  it('SKIPS a window whose webContents was destroyed (its .send would throw)', () => {
    const { win, send } = fakeWindow(true);
    broadcastToLiveWindows([win], 'provisioning.state', { active: false });
    expect(send).not.toHaveBeenCalled();
  });

  it('fans out to every live window and skips only the destroyed ones', () => {
    const live1 = fakeWindow(false);
    const dead = fakeWindow(true);
    const live2 = fakeWindow(false);
    broadcastToLiveWindows([live1.win, dead.win, live2.win], 'bootstrap.progress', 'line');
    expect(live1.send).toHaveBeenCalledWith('bootstrap.progress', 'line');
    expect(live2.send).toHaveBeenCalledWith('bootstrap.progress', 'line');
    expect(dead.send).not.toHaveBeenCalled();
  });

  it('is a no-op for an empty window list (a headless / pre-window fan-out)', () => {
    expect(() => broadcastToLiveWindows([], 'update.status', { state: 'none' })).not.toThrow();
  });
});
