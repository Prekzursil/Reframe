// appMenu.test.ts — the application menu template (appMenu.ts).
//
// C2 (docs/plans/v1.5/uiux-qol-audit-2026-08.md §5): the app shipped Electron's
// STOCK menu, so `Edit ▸ Undo (Ctrl+Z)` advertised an undo the app does not have.
// Three independent signals that no app-wide undo exists:
//   1. `main.ts` imported no `Menu` and called no `setApplicationMenu` (§4.1),
//   2. docs/plans/v1.5/editing-surface-audit-2026-08.md row 25 — "PARTIAL, two
//      disjoint mechanisms, no app-wide stack": `director.undo`
//      (sidecar handlers/composition.py) inverts DIRECTOR ops only, and
//      `timelineOps.ts` keeps a 100-entry history for SUBTITLE CUES only,
//   3. neither is reachable from a global accelerator.
//
// So the stock item lied twice: the menu was named "Edit", which in this app's IA
// is a RAIL DESTINATION (views/Edit.tsx) meaning "edit this video", and the item
// was named a bare "Undo" with no scope. The roles themselves are honest — they
// really do undo TYPING in a focused field — so the fix scopes the labels rather
// than deleting working behaviour: a "Text" menu with "Undo typing"/"Redo typing".
//
// These tests hold that contract, and hold the dev-only View items off a packaged
// build (H1 — DevTools and Force Reload were shipped to end users).
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import type { MenuItemConstructorOptions } from 'electron';
import { buildAppMenuTemplate } from './appMenu';

/** Every item in the template tree, depth-first (top-level entries included). */
function flatten(items: readonly MenuItemConstructorOptions[]): MenuItemConstructorOptions[] {
  const out: MenuItemConstructorOptions[] = [];
  for (const item of items) {
    out.push(item);
    if (Array.isArray(item.submenu)) {
      out.push(...flatten(item.submenu as MenuItemConstructorOptions[]));
    }
  }
  return out;
}

function roles(items: readonly MenuItemConstructorOptions[]): string[] {
  return flatten(items)
    .map((item) => item.role)
    .filter((role): role is NonNullable<MenuItemConstructorOptions['role']> => role != null);
}

function labels(items: readonly MenuItemConstructorOptions[]): string[] {
  return flatten(items)
    .map((item) => item.label)
    .filter((label): label is string => typeof label === 'string');
}

function submenuOf(
  items: readonly MenuItemConstructorOptions[],
  label: string,
): MenuItemConstructorOptions[] {
  const found = items.find((item) => item.label === label);
  if (!found || !Array.isArray(found.submenu)) {
    throw new Error(`no top-level menu labelled "${label}"`);
  }
  return found.submenu as MenuItemConstructorOptions[];
}

describe('buildAppMenuTemplate', () => {
  it('never offers a bare "Undo"/"Redo" — the app has no app-wide undo stack', () => {
    for (const isDev of [true, false]) {
      const all = labels(buildAppMenuTemplate({ isDev }));
      expect(all).not.toContain('Undo');
      expect(all).not.toContain('Redo');
    }
  });

  it('never names a top-level menu "Edit" — that label is a rail destination here', () => {
    for (const isDev of [true, false]) {
      expect(buildAppMenuTemplate({ isDev }).map((item) => item.label)).not.toContain('Edit');
    }
  });

  it('keeps native text-field undo/redo, scoped honestly to typing', () => {
    const text = submenuOf(buildAppMenuTemplate({ isDev: false }), 'Text');
    expect(text).toContainEqual(expect.objectContaining({ role: 'undo', label: 'Undo typing' }));
    expect(text).toContainEqual(expect.objectContaining({ role: 'redo', label: 'Redo typing' }));
  });

  // SCOPE NOTE — an earlier draft of the test above also pinned
  // `accelerator: 'CmdOrCtrl+Shift+Z'` on redo. That is WRONG on this app's primary
  // platform: Windows' native redo is Ctrl+Y, and an explicit `accelerator`
  // OVERRIDES the role's per-platform default, so pinning it would have traded one
  // defect for a keyboard regression. The requirement is the inverse — leave the
  // accelerator unset so Electron supplies the platform-correct binding. Only the
  // LABEL is ours to change; the binding is the platform's.
  it('leaves the role accelerators to the platform (Windows redo is Ctrl+Y)', () => {
    const text = submenuOf(buildAppMenuTemplate({ isDev: false }), 'Text');
    for (const item of text) {
      expect(item.accelerator).toBeUndefined();
    }
  });

  it('keeps the clipboard + select-all roles working', () => {
    const text = roles(submenuOf(buildAppMenuTemplate({ isDev: false }), 'Text'));
    expect(text).toEqual(expect.arrayContaining(['cut', 'copy', 'paste', 'delete', 'selectAll']));
  });

  it('withholds DevTools, Reload and Force Reload from a packaged build', () => {
    const shipped = roles(buildAppMenuTemplate({ isDev: false }));
    expect(shipped).not.toContain('toggleDevTools');
    expect(shipped).not.toContain('reload');
    expect(shipped).not.toContain('forceReload');
  });

  it('offers DevTools, Reload and Force Reload in development', () => {
    const dev = roles(buildAppMenuTemplate({ isDev: true }));
    expect(dev).toEqual(expect.arrayContaining(['toggleDevTools', 'reload', 'forceReload']));
  });

  it('keeps zoom and full-screen in BOTH builds (they are not dev tools)', () => {
    for (const isDev of [true, false]) {
      expect(roles(buildAppMenuTemplate({ isDev }))).toEqual(
        expect.arrayContaining(['resetZoom', 'zoomIn', 'zoomOut', 'togglefullscreen']),
      );
    }
  });

  it('gives Help ▸ About a real home (main.ts already configures the panel)', () => {
    expect(roles(submenuOf(buildAppMenuTemplate({ isDev: false }), 'Help'))).toContain('about');
  });

  it('has a labelled, non-empty submenu under every top-level entry', () => {
    for (const isDev of [true, false]) {
      const top = buildAppMenuTemplate({ isDev });
      expect(top.length).toBeGreaterThan(0);
      for (const item of top) {
        expect(typeof item.label).toBe('string');
        expect(Array.isArray(item.submenu)).toBe(true);
        expect((item.submenu as MenuItemConstructorOptions[]).length).toBeGreaterThan(0);
      }
    }
  });

  // This repo has shipped ORPHANED modules before (SavePresetsControls and
  // PathsPanel both existed, tested, and unreachable). A menu template nothing
  // installs would leave the stock lying menu in place and the tests above would
  // still pass, so assert the wiring exists.
  it('is actually installed by main.ts (not an orphaned module)', () => {
    const src = readFileSync(join(__dirname, 'main.ts'), 'utf8');
    expect(src).toMatch(/buildAppMenuTemplate/);
    expect(src).toMatch(/Menu\.setApplicationMenu\(/);
    expect(src).toMatch(/Menu\.buildFromTemplate\(/);
  });
});
