// appMenu.ts — the application menu template (CONTRACTS.md §1: main process).
//
// Reframe previously installed NO menu, so Electron's stock one shipped verbatim.
// Two defects came with it (docs/plans/v1.5/uiux-qol-audit-2026-08.md §4.1, §5):
//
//   C2 — `Edit ▸ Undo (Ctrl+Z)` advertised an undo the app does not have. The
//        role itself is honest (it really does undo TYPING in a focused field);
//        the FRAMING lied twice. "Edit" is a rail destination in this app's IA
//        (views/Edit.tsx = "edit this video"), so an `Edit` menu reads as
//        video-edit undo; and a bare "Undo" claims an app-wide stack that does
//        not exist. editing-surface-audit-2026-08.md row 25 measures the real
//        state: "PARTIAL — two disjoint mechanisms, no app-wide stack" —
//        `director.undo` inverts DIRECTOR ops only, and `timelineOps.ts` keeps a
//        100-entry history for SUBTITLE CUES only. Neither can back a global
//        Ctrl+Z, and this module does not pretend otherwise.
//
//   H1 — DevTools and Force Reload were reachable in a packaged consumer build.
//
// The fix keeps every role that genuinely works and tells the truth about scope:
// the menu is named "Text" and its items are "Undo typing" / "Redo typing". That
// preserves text-field undo everywhere (the Director goal box, caption editors,
// preset names) instead of deleting a working feature to silence a wording bug.
//
// Accelerators are deliberately NOT set on role items: an explicit `accelerator`
// overrides the role's per-platform default, and Windows' native redo is Ctrl+Y,
// not Ctrl+Shift+Z. Only the labels are ours; the bindings stay the platform's.
//
// This is a PURE template builder — it touches no Electron runtime object — so it
// is unit-testable without a live app (appMenu.test.ts). `main.ts` feeds it
// `!app.isPackaged` and installs the result.
import type { MenuItemConstructorOptions } from 'electron';

export interface AppMenuOptions {
  /** `!app.isPackaged`. Gates the developer-only View items (H1). */
  isDev: boolean;
}

/** The View items that must never reach a packaged consumer build (H1). */
function devViewItems(): MenuItemConstructorOptions[] {
  return [
    { role: 'reload' },
    { role: 'forceReload' },
    { role: 'toggleDevTools' },
    { type: 'separator' },
  ];
}

/**
 * Build the application menu template.
 *
 * Top-level: File · Text · View · Window · Help. There is deliberately no "Edit"
 * menu — see the C2 note above.
 */
export function buildAppMenuTemplate({ isDev }: AppMenuOptions): MenuItemConstructorOptions[] {
  return [
    {
      label: 'File',
      submenu: [{ role: 'quit', label: 'Quit Reframe' }],
    },
    {
      // NOT "Edit": that word names a rail destination in this app (views/Edit.tsx).
      // These items act on the FOCUSED TEXT FIELD and say so.
      label: 'Text',
      submenu: [
        { role: 'undo', label: 'Undo typing' },
        { role: 'redo', label: 'Redo typing' },
        { type: 'separator' },
        { role: 'cut' },
        { role: 'copy' },
        { role: 'paste' },
        { role: 'delete' },
        { type: 'separator' },
        { role: 'selectAll' },
      ],
    },
    {
      label: 'View',
      submenu: [
        // Reload / Force Reload / DevTools are development affordances: in a
        // packaged build Force Reload silently discards renderer state mid-job
        // and DevTools is a support-call generator. Zoom and full screen are
        // ordinary user controls and stay in both builds.
        ...(isDev ? devViewItems() : []),
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' },
      ],
    },
    {
      label: 'Window',
      submenu: [{ role: 'minimize' }, { role: 'close' }],
    },
    {
      // main.ts already calls `app.setAboutPanelOptions(...)` and its comment
      // claims a "Help ▸ About" home for it — which did not exist while no menu
      // was installed. This gives that panel the surface it was configured for.
      label: 'Help',
      submenu: [{ role: 'about', label: 'About Reframe' }],
    },
  ];
}

export default buildAppMenuTemplate;
