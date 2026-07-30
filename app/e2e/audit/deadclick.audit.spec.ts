// e2e/audit/deadclick.audit.spec.ts — the functional "does every control DO
// something" sweep across every reachable surface of the real app.
//
// WHY THIS EXISTS
// The acceptance bar is "no broken buttons": every interactive control either
// does something observable, or is legitimately inert (disabled / already in the
// requested state). A screenshot cannot prove that and a unit test only proves
// the handler a developer remembered to wire. So this drives the REAL built
// Electron app + live sidecar (e2e/fixtures.ts) and clicks everything.
//
// THE MEASUREMENT PROBLEM (and why a naive version is worthless)
// The obvious detector — "did the DOM mutate after the click?" — reports
// EVERYTHING as alive on any app that changes on its own. Measured directly
// against a page with a 100ms ticker: a bare MutationObserver count found 0 of 2
// planted dead buttons, i.e. a confident false green. Reframe polls job status
// and animates progress, so it is exactly that kind of app.
//
// The fix is a CONTROL WINDOW. For every control we observe the page for the
// same duration WITHOUT clicking, recording a stable signature per mutated node;
// that is the ambient set. Then we click and record again, and only signatures
// absent from the ambient set count as an effect of the click.
//
// ERROR DIRECTION IS DELIBERATE. If a click only touches a node that also churns
// ambiently, it reads as 'none' — a false DEAD. That is the safe direction: a
// false dead is filtered by review, whereas a false ALIVE silently ships a
// broken control, which is the defect this sweep exists to catch.
//
// An uncaught handler throw surfaces as 'pageerror', NOT as a console message
// (measured), and is a DIFFERENT defect from a dead control — wired but broken.
// It is reported as its own flag so it cannot hide inside a "0 dead" headline.
//
// Output: audit-artifacts/deadclick.json + a summary table on stdout.

import { test, expect, type Page } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { launchSeededApp, prepareWindow } from '../visual/_visualSetup';

/** Where the machine-readable report lands (repo-relative, gitignored). */
const OUT_DIR = join(process.cwd(), 'audit-artifacts');

/** Per-control observation window. Must exceed React's commit + a poll tick. */
const WINDOW_MS = 450;

/**
 * Controls we refuse to click, with the reason. Two classes:
 *   - DESTRUCTIVE: would delete library/user data, or uninstall a runtime.
 *   - SPENDING/EGRESS: would start a cloud job or a multi-GB model download.
 * The seeded data root is a throwaway, so destruction is contained — but a
 * cloud-run click could spend real money if a key is present in the inherited
 * environment, and a model download would stall the sweep for tens of minutes.
 * Every skip is REPORTED, never silently dropped: a sweep that quietly avoids
 * the scary half of the UI and then reports "0 dead" is a lie by omission.
 */
const SKIP_PATTERNS: ReadonlyArray<{ re: RegExp; reason: string }> = [
  { re: /\b(delete|remove|clear|reset|wipe|uninstall|forget)\b/i, reason: 'destructive' },
  { re: /\b(install|download|fetch model|provision)\b/i, reason: 'multi-GB download / provisioning' },
  { re: /\b(run in cloud|cloud run|start cloud|purchase|buy|upgrade plan)\b/i, reason: 'spending / egress' },
  { re: /\b(quit|exit|restart app|sign out|log out)\b/i, reason: 'ends the session under test' },
];

interface ControlRecord {
  surface: string;
  index: number;
  identity: string;
  tag: string;
  role: string | null;
  name: string;
  /**
   * 'none'          — clicked, nothing observable happened => a real dead-control candidate
   * 'already-active'— clicked while aria-selected/aria-pressed was already true, so a
   *                   no-op is CORRECT (a segmented control or the current tab). Split
   *                   out from 'none' because otherwise every surface reports its own
   *                   tab as dead and the headline number is meaningless.
   * 'dom' | 'network' | 'dialog' — observable effect
   * 'error'         — could not be actuated / identity drifted => NOT evidence of dead
   * 'skipped' | 'disabled'
   */
  effect: string;
  /** Was the control already in the selected/pressed state before the click? */
  wasActive?: boolean;
  ambientSignatures: number;
  attributedSignatures: number;
  requestsAmbient: number;
  requestsAfterClick: number;
  pageError?: string;
  clickError?: string;
  skipReason?: string;
}

/** In-page: install a mutation recorder that stores stable per-node signatures. */
async function installRecorder(win: Page): Promise<void> {
  await win.evaluate(() => {
    const w = window as unknown as {
      __rfSigs?: Set<string>;
      __rfMo?: MutationObserver;
    };
    w.__rfSigs = new Set<string>();
    const sig = (m: MutationRecord): string => {
      const el =
        m.target instanceof Element ? m.target : (m.target?.parentElement ?? null);
      if (!el) return `${m.type}|<detached>`;
      let path = '';
      let node: Element | null = el;
      for (let d = 0; d < 4 && node?.parentElement; d += 1) {
        path = `${Array.prototype.indexOf.call(node.parentElement.children, node)}/${path}`;
        node = node.parentElement;
      }
      const cls = Array.from(el.classList).slice(0, 3).join('.');
      return `${m.type}|${el.tagName}#${el.id}.${cls}|${path}`;
    };
    w.__rfMo?.disconnect();
    w.__rfMo = new MutationObserver((recs) => {
      for (const m of recs) w.__rfSigs!.add(sig(m));
    });
    w.__rfMo.observe(document.documentElement, {
      childList: true,
      subtree: true,
      attributes: true,
      characterData: true,
    });
  });
}

async function readSignatures(win: Page): Promise<string[]> {
  try {
    return await win.evaluate(() =>
      Array.from((window as unknown as { __rfSigs?: Set<string> }).__rfSigs ?? []),
    );
  } catch {
    return [];
  }
}

async function clearSignatures(win: Page): Promise<void> {
  try {
    await win.evaluate(() =>
      (window as unknown as { __rfSigs?: Set<string> }).__rfSigs?.clear(),
    );
  } catch {
    /* page busy — a stale set only makes us MORE conservative */
  }
}

/** The interactive set: native controls plus explicit ARIA interaction roles. */
const INTERACTIVE =
  'button, a[href], input:not([type="hidden"]), select, textarea, ' +
  '[role="button"], [role="tab"], [role="link"], [role="menuitem"], [role="switch"], [role="checkbox"]';

/** Enumerate the visible interactive controls on the CURRENT surface. */
async function enumerate(
  win: Page,
): Promise<Array<{ identity: string; tag: string; role: string | null; name: string; disabled: boolean }>> {
  return win.evaluate((sel) => {
    const visible = (el: Element): boolean => {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) return false;
      const cs = getComputedStyle(el);
      return cs.visibility !== 'hidden' && cs.display !== 'none' && cs.opacity !== '0';
    };
    const describe = (el: Element): string => {
      if (el.id) return `#${el.id}`;
      const tid = el.getAttribute('data-testid');
      if (tid) return `[data-testid="${tid}"]`;
      const aria = el.getAttribute('aria-label');
      if (aria?.trim()) return `[aria-label="${aria.trim()}"]`;
      const tag = el.tagName.toLowerCase();
      const text = (el.textContent ?? '').replace(/\s+/g, ' ').trim();
      if (text) return `${tag}:"${text.slice(0, 48)}"`;
      const cls = Array.from(el.classList).slice(0, 3).join('.');
      return cls ? `${tag}.${cls}` : tag;
    };
    return Array.from(document.querySelectorAll(sel))
      .filter(visible)
      .map((el) => ({
        identity: describe(el),
        tag: el.tagName,
        role: el.getAttribute('role'),
        name: (
          el.getAttribute('aria-label') ??
          el.textContent ??
          (el as HTMLInputElement).value ??
          ''
        )
          .replace(/\s+/g, ' ')
          .trim()
          .slice(0, 70),
        // A disabled control doing nothing is CORRECT, not a defect. Recorded
        // separately so it never inflates the dead count.
        disabled:
          (el as HTMLButtonElement).disabled === true ||
          el.getAttribute('aria-disabled') === 'true',
      }));
  }, INTERACTIVE);
}

test('functional sweep: every interactive control on every surface', async () => {
  mkdirSync(OUT_DIR, { recursive: true });
  const { app } = await launchSeededApp();
  const win = await prepareWindow(app);

  const records: ControlRecord[] = [];
  const pageErrors: string[] = [];
  win.on('pageerror', (e) => pageErrors.push(e.message.split('\n')[0]));
  let requests = 0;
  win.on('request', () => {
    requests += 1;
  });
  let dialogSeen = false;
  win.on('dialog', (d) => {
    dialogSeen = true;
    void d.dismiss().catch(() => {});
  });

  // ---- Surface discovery: read the real nav rather than hardcoding a list, so
  // a surface added later is swept automatically instead of silently missed.
  const topTabs = await win.locator('.toptab').allTextContents();
  const tops = topTabs.map((t) => t.replace(/\s+/g, ' ').trim()).filter(Boolean);
  // eslint-disable-next-line no-console
  console.log(`[sweep] discovered ${tops.length} top-level surfaces: ${tops.join(' | ')}`);
  expect(tops.length, 'at least one top-level surface must be discoverable').toBeGreaterThan(0);

  const goTop = async (label: string): Promise<boolean> => {
    try {
      await win.locator('.toptab', { hasText: label }).first().click({ timeout: 5000 });
      await win.waitForTimeout(350);
      return true;
    } catch {
      return false;
    }
  };

  /**
   * A sweep CONTEXT is a (top tab, optional sub tab) pair. Sweeping only top
   * tabs was a real coverage hole: Settings enumerated 40 controls but only ~24
   * exist under any single sub-tab, so every control past that index reported
   * "absent after surface restore" and was NEVER CLICKED — 15 controls silently
   * unswept, in exactly the panel where an unwired control is most likely.
   */
  const contexts: Array<{ label: string; top: string; sub?: string }> = [];
  for (const top of tops) {
    if (!(await goTop(top))) {
      contexts.push({ label: top, top });
      continue;
    }
    const subs = (await win.locator('.tabbar [role="tab"]').allTextContents())
      .map((t) => t.replace(/\s+/g, ' ').trim())
      .filter(Boolean);
    if (subs.length === 0) contexts.push({ label: top, top });
    else for (const sub of subs) contexts.push({ label: `${top} > ${sub}`, top, sub });
  }
  // eslint-disable-next-line no-console
  console.log(`[sweep] ${contexts.length} sweep contexts:\n  ${contexts.map((c) => c.label).join('\n  ')}`);

  /** Restore a context so every control is clicked from the same known state. */
  const goSurface = async (label: string): Promise<boolean> => {
    const ctx = contexts.find((c) => c.label === label);
    if (!ctx) return false;
    if (!(await goTop(ctx.top))) return false;
    if (ctx.sub) {
      try {
        await win.locator('.tabbar [role="tab"]', { hasText: ctx.sub }).first().click({ timeout: 5000 });
        await win.waitForTimeout(300);
      } catch {
        return false;
      }
    }
    return true;
  };

  for (const { label: surface } of contexts) {
    if (!(await goSurface(surface))) {
      // eslint-disable-next-line no-console
      console.log(`[sweep] FAILED to reach surface "${surface}" — recorded, not skipped silently`);
      records.push({
        surface,
        index: -1,
        identity: '<surface>',
        tag: 'SURFACE',
        role: null,
        name: surface,
        effect: 'error',
        ambientSignatures: 0,
        attributedSignatures: 0,
        requestsAmbient: 0,
        requestsAfterClick: 0,
        clickError: 'surface unreachable from top nav',
      });
      continue;
    }

    const controls = await enumerate(win);
    // eslint-disable-next-line no-console
    console.log(`[sweep] ${surface}: ${controls.length} visible interactive control(s)`);

    for (let i = 0; i < controls.length; i += 1) {
      const c = controls[i];
      const base: Omit<ControlRecord, 'effect'> = {
        surface,
        index: i,
        identity: c.identity,
        tag: c.tag,
        role: c.role,
        name: c.name,
        ambientSignatures: 0,
        attributedSignatures: 0,
        requestsAmbient: 0,
        requestsAfterClick: 0,
      };

      if (c.disabled) {
        records.push({ ...base, effect: 'disabled' });
        continue;
      }
      const skip = SKIP_PATTERNS.find((p) => p.re.test(c.name));
      if (skip) {
        records.push({ ...base, effect: 'skipped', skipReason: skip.reason });
        continue;
      }

      // Re-establish the surface: a previous click may have navigated away or
      // opened a panel, and every control must be judged from the same state.
      await win.keyboard.press('Escape').catch(() => {});
      if (!(await goSurface(surface))) break;

      // Re-resolve by position on the freshly-restored surface.
      const handles = await win.locator(INTERACTIVE).all();
      const live = handles[i];
      if (!live) {
        records.push({
          ...base,
          effect: 'error',
          clickError: `control index ${i} absent after surface restore (found ${handles.length})`,
        });
        continue;
      }

      // IDENTITY GUARD. Index-based re-resolution is only valid if the restored
      // surface presents the SAME control at the same position. A prior click can
      // leave sticky state (an expanded panel, a flipped toggle) that shifts the
      // set, and then index i would silently point at a different element —
      // producing a verdict attributed to the wrong control. Compare identities
      // and record a drift instead of trusting a mislabelled reading.
      const liveIdentity = await live
        .evaluate((el) => {
          if (el.id) return `#${el.id}`;
          const tid = el.getAttribute('data-testid');
          if (tid) return `[data-testid="${tid}"]`;
          const aria = el.getAttribute('aria-label');
          if (aria?.trim()) return `[aria-label="${aria.trim()}"]`;
          const tag = el.tagName.toLowerCase();
          const text = (el.textContent ?? '').replace(/\s+/g, ' ').trim();
          if (text) return `${tag}:"${text.slice(0, 48)}"`;
          const cls = Array.from(el.classList).slice(0, 3).join('.');
          return cls ? `${tag}.${cls}` : tag;
        })
        .catch(() => '<unreadable>');
      if (liveIdentity !== c.identity) {
        records.push({
          ...base,
          effect: 'error',
          clickError: `identity drift at index ${i}: enumerated ${c.identity}, found ${liveIdentity}`,
        });
        continue;
      }

      // Read the control's OWN state before clicking. A tab already selected, or
      // a segmented-control button already pressed, is SUPPOSED to do nothing —
      // e.g. RoutingToggle.tsx documents `value !== mode && onChange(mode)` so the
      // active segment never re-writes the same value. Deciding this from the
      // element's own aria state is deterministic; deciding it by reading the
      // label and judging is not.
      const wasActive = await live
        .evaluate(
          (el) =>
            el.getAttribute('aria-selected') === 'true' ||
            el.getAttribute('aria-pressed') === 'true' ||
            el.getAttribute('aria-current') === 'page' ||
            el.classList.contains('is-active'),
        )
        .catch(() => false);

      await installRecorder(win);

      // --- ambient control window: observe WITHOUT clicking ---
      requests = 0;
      await win.waitForTimeout(WINDOW_MS);
      const ambient = new Set(await readSignatures(win));
      const requestsAmbient = requests;

      // --- the click ---
      await clearSignatures(win);
      requests = 0;
      pageErrors.length = 0;
      dialogSeen = false;
      let clickError: string | undefined;
      try {
        await live.click({ timeout: 2500 });
      } catch (e) {
        clickError = (e as Error).message.split('\n')[0];
      }
      await win.waitForTimeout(WINDOW_MS);

      const post = await readSignatures(win);
      const attributed = post.filter((s) => !ambient.has(s));

      let effect: string;
      if (dialogSeen) effect = 'dialog';
      else if (attributed.length > 0) effect = 'dom';
      else if (requests > requestsAmbient) effect = 'network';
      else if (clickError) effect = 'error';
      else if (wasActive) effect = 'already-active';
      else effect = 'none';

      records.push({
        ...base,
        effect,
        wasActive,
        ambientSignatures: ambient.size,
        attributedSignatures: attributed.length,
        requestsAmbient,
        requestsAfterClick: requests,
        ...(pageErrors.length ? { pageError: pageErrors[0] } : {}),
        ...(clickError ? { clickError } : {}),
      });
    }
  }

  await app.close().catch(() => {});

  // ---- Report -------------------------------------------------------------
  const dead = records.filter((r) => r.effect === 'none');
  const throwing = records.filter((r) => r.pageError);
  const errored = records.filter((r) => r.effect === 'error');
  const skipped = records.filter((r) => r.effect === 'skipped');
  const disabled = records.filter((r) => r.effect === 'disabled');
  const alreadyActive = records.filter((r) => r.effect === 'already-active');
  const acted = records.filter((r) => ['dom', 'network', 'dialog'].includes(r.effect));
  const maxAmbient = records.reduce((m, r) => Math.max(m, r.ambientSignatures), 0);

  writeFileSync(
    join(OUT_DIR, 'deadclick.json'),
    JSON.stringify(
      {
        generatedFor: 'functional sweep — every interactive control, every surface',
        windowMs: WINDOW_MS,
        totals: {
          controls: records.length,
          acted: acted.length,
          dead: dead.length,
          alreadyActive: alreadyActive.length,
          throwing: throwing.length,
          errored: errored.length,
          skipped: skipped.length,
          disabled: disabled.length,
        },
        maxAmbientSignatures: maxAmbient,
        records,
      },
      null,
      2,
    ),
  );

  /* eslint-disable no-console */
  console.log(`\n=== functional sweep ===`);
  console.log(`  controls enumerated : ${records.length}`);
  console.log(`  acted (dom/network/dialog) : ${acted.length}`);
  console.log(`  DEAD (clicked, nothing happened) : ${dead.length}`);
  console.log(`  already-active (no-op is correct) : ${alreadyActive.length}`);
  console.log(`  THROWS (uncaught page error) : ${throwing.length}`);
  console.log(`  not actionable / drifted : ${errored.length}`);
  console.log(`  skipped (listed below) : ${skipped.length}`);
  console.log(`  disabled (correctly inert) : ${disabled.length}`);
  console.log(`  max ambient signatures in a no-click window: ${maxAmbient}`);
  // State the denominator plainly: "0 dead" is only meaningful against how many
  // were actually actuated, and errored/skipped/disabled were NOT actuated.
  console.log(
    `  ACTUATED ${acted.length + dead.length + alreadyActive.length}/${records.length} ` +
      `(unactuated: ${errored.length} errored + ${skipped.length} skipped + ${disabled.length} disabled)`,
  );
  for (const r of dead) console.log(`  DEAD    [${r.surface}] ${r.identity} "${r.name}"`);
  for (const r of throwing) console.log(`  THROWS  [${r.surface}] ${r.identity} -> ${r.pageError}`);
  for (const r of errored) console.log(`  ERROR   [${r.surface}] ${r.identity} -> ${r.clickError}`);
  for (const r of skipped) console.log(`  SKIP    [${r.surface}] "${r.name}" (${r.skipReason})`);
  console.log(`\nreport: ${join(OUT_DIR, 'deadclick.json')}`);
  /* eslint-enable no-console */

  // This spec is an INSTRUMENT, not the gate: it must always produce its report
  // rather than abort partway on the first defect. The gate is applied by the
  // caller reading deadclick.json, so the only hard assertion is that the sweep
  // actually observed something (a zero-control run means the harness broke).
  expect(records.length, 'sweep must observe at least one control').toBeGreaterThan(0);
});
