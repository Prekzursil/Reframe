// static_unwired_scan.mjs — find interactive JSX that has no way to DO anything.
//
// Complements the dynamic sweep (app/e2e/audit/deadclick.audit.spec.ts). The
// sweep can only click what it can REACH; controls behind a modal, an error
// state, a feature flag, or a rarely-hit conditional are never exercised. This
// reads the source instead, so reachability is irrelevant.
//
// Uses the TypeScript compiler API (already a repo dependency) rather than regex:
// a regex over JSX cannot tell an `onClick` on the element from one mentioned in
// a nearby comment or a child, which is the use-vs-mention error class.
//
// HONEST LIMITS — this reports CANDIDATES, not confirmed defects:
//   * a handler can arrive via {...props} spread, which we detect and exempt;
//   * a handler can be injected by a parent through a prop we cannot see here;
//   * a <button type="submit"> inside a form is wired via the form, not onClick;
//   * a label-wrapped input is driven by the input, not the label.
// So a hit means "no LOCAL evidence of wiring" and must be confirmed. The error
// direction is deliberately toward over-reporting.
//
// Usage (from the repo root):
//   node scripts/static_unwired_scan.mjs [--json out.json] [--src <dir>]
//
// DETECTOR IS VALIDATED. Against a fixture of 4 planted defects (empty arrow
// handler, `() => undefined`, a <button> with no wiring, role=button on a div
// with no tabIndex) plus 4 planted GOOD controls (a wired button, a form submit,
// a {...spread} handler, a tabIndex+onKeyDown custom control) it reported
// exactly 4/4 and 0/4 respectively. Re-run that control with --src before
// trusting a zero: an unvalidated zero is not evidence of a clean tree.

import { readFileSync, writeFileSync, readdirSync, statSync, existsSync } from 'node:fs';
import { join, relative } from 'node:path';
import { createRequire } from 'node:module';

const ROOT = process.cwd();
// --src <dir> overrides the scan root. Exists so the scanner can be pointed at a
// fixture directory of PLANTED defects to prove it actually fires: a zero from an
// unvalidated detector is not evidence of a clean tree.
const srcArgIdx = process.argv.indexOf('--src');
const SRC = srcArgIdx !== -1 && process.argv[srcArgIdx + 1]
  ? process.argv[srcArgIdx + 1]
  : existsSync(join(ROOT, 'app', 'renderer', 'src'))
    ? join(ROOT, 'app', 'renderer', 'src')
    : join(ROOT, 'renderer', 'src');
// typescript lives in app/node_modules (the repo root has none), and NODE_PATH is
// ignored for ESM — so resolve it explicitly against the app package instead of
// a bare specifier.
const require = createRequire(join(ROOT, 'app', 'package.json'));
const ts = require('typescript');

/** Attributes that make an element able to do something. */
const ACTION_ATTRS = new Set([
  'onClick', 'onMouseDown', 'onMouseUp', 'onPointerDown', 'onKeyDown', 'onKeyUp',
  'onKeyPress', 'onChange', 'onInput', 'onSubmit', 'onToggle', 'onFocus', 'onBlur',
  'href', 'to', 'form', 'formAction', 'popoverTarget', 'commandFor',
]);

/** Interactive intrinsic tags worth checking. */
const INTERACTIVE_TAGS = new Set(['button', 'a', 'select', 'textarea', 'input']);

function walkFiles(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry);
    const st = statSync(p);
    if (st.isDirectory()) {
      if (entry === 'node_modules' || entry === '__snapshots__') continue;
      walkFiles(p, out);
    } else if (/\.tsx$/.test(entry) && !/\.test\.tsx$/.test(entry)) {
      out.push(p);
    }
  }
  return out;
}

/** Is this JSX attribute list evidence the element can act? */
function classifyAttrs(attributes) {
  let hasAction = false;
  let hasSpread = false;
  let isSubmit = false;
  let isDisabledAlways = false;
  let role = null;
  let tabIndex = false;
  for (const attr of attributes.properties) {
    if (ts.isJsxSpreadAttribute(attr)) {
      hasSpread = true;
      continue;
    }
    if (!ts.isJsxAttribute(attr)) continue;
    const name = attr.name.getText();
    if (ACTION_ATTRS.has(name)) hasAction = true;
    if (name === 'tabIndex') tabIndex = true;
    if (name === 'type' && attr.initializer && ts.isStringLiteral(attr.initializer)) {
      if (attr.initializer.text === 'submit' || attr.initializer.text === 'reset') isSubmit = true;
    }
    if (name === 'role' && attr.initializer && ts.isStringLiteral(attr.initializer)) {
      role = attr.initializer.text;
    }
    // `disabled` with no initializer (bare) is always-disabled; `disabled={x}` is conditional.
    if (name === 'disabled' && !attr.initializer) isDisabledAlways = true;
  }
  return { hasAction, hasSpread, isSubmit, isDisabledAlways, role, tabIndex };
}

/**
 * Is the handler expression an EMPTY function? `onClick={() => {}}` is wired to
 * the type checker and dead to the user — the most deceptive form of unwired,
 * because every "does it have onClick" check passes.
 */
function emptyHandlerName(attributes) {
  for (const attr of attributes.properties) {
    if (!ts.isJsxAttribute(attr) || !attr.initializer) continue;
    const name = attr.name.getText();
    if (!name.startsWith('on')) continue;
    if (!ts.isJsxExpression(attr.initializer) || !attr.initializer.expression) continue;
    const expr = attr.initializer.expression;
    if (ts.isArrowFunction(expr) || ts.isFunctionExpression(expr)) {
      const body = expr.body;
      if (ts.isBlock(body) && body.statements.length === 0) return name;
      if (ts.isBlock(body) && body.statements.every((s) => ts.isEmptyStatement(s))) return name;
      // `() => undefined` / `() => null` / `() => void 0`
      if (!ts.isBlock(body)) {
        const t = body.getText().trim();
        if (t === 'undefined' || t === 'null' || t === 'void 0') return name;
      }
    }
  }
  return null;
}

const findings = [];
const files = walkFiles(SRC);

for (const file of files) {
  const text = readFileSync(file, 'utf8');
  const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const rel = relative(ROOT, file).replace(/\\/g, '/');

  const visit = (node) => {
    let attributes = null;
    let tagName = null;
    if (ts.isJsxSelfClosingElement(node)) {
      attributes = node.attributes;
      tagName = node.tagName.getText();
    } else if (ts.isJsxElement(node)) {
      attributes = node.openingElement.attributes;
      tagName = node.openingElement.tagName.getText();
    }

    if (attributes && tagName) {
      const c = classifyAttrs(attributes);
      const isIntrinsicInteractive = INTERACTIVE_TAGS.has(tagName);
      const isAriaInteractive = c.role === 'button' || c.role === 'tab' || c.role === 'link'
        || c.role === 'menuitem' || c.role === 'switch' || c.role === 'checkbox';
      const line = sf.getLineAndCharacterOfPosition(node.getStart()).line + 1;

      // 1) An EMPTY handler: type-checks, does nothing. Highest-confidence class.
      const empty = emptyHandlerName(attributes);
      if (empty && (isIntrinsicInteractive || isAriaInteractive)) {
        findings.push({
          kind: 'empty-handler',
          confidence: 'high',
          file: rel,
          line,
          tag: tagName,
          role: c.role,
          detail: `${empty} is an empty function — wired to the type checker, dead to the user`,
        });
      }

      // 2) An interactive element with NO local action affordance at all.
      if (
        (isIntrinsicInteractive || isAriaInteractive) &&
        !c.hasAction && !c.hasSpread && !c.isSubmit && !c.isDisabledAlways &&
        // <a> without href is not a control; <input> is often driven by form state.
        tagName !== 'input' && tagName !== 'textarea' && tagName !== 'select'
      ) {
        findings.push({
          kind: 'no-local-handler',
          confidence: 'medium',
          file: rel,
          line,
          tag: tagName,
          role: c.role,
          detail: 'no onClick/href/form and no {...spread} on this element — verify a parent wires it',
        });
      }

      // 3) An ARIA-interactive NON-button with no keyboard path: mouse-only.
      if (isAriaInteractive && !isIntrinsicInteractive && !c.tabIndex && !c.hasSpread) {
        findings.push({
          kind: 'mouse-only-role',
          confidence: 'medium',
          file: rel,
          line,
          tag: tagName,
          role: c.role,
          detail: `role="${c.role}" on <${tagName}> without tabIndex — unreachable by keyboard`,
        });
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
}

const byKind = findings.reduce((m, f) => ({ ...m, [f.kind]: (m[f.kind] ?? 0) + 1 }), {});
console.log(`scanned ${files.length} .tsx files under ${relative(ROOT, SRC)}`);
console.log(`findings by kind: ${JSON.stringify(byKind)}`);
for (const f of findings.filter((x) => x.confidence === 'high')) {
  console.log(`  HIGH  ${f.file}:${f.line}  <${f.tag}${f.role ? ` role=${f.role}` : ''}>  ${f.detail}`);
}
for (const f of findings.filter((x) => x.confidence === 'medium').slice(0, 60)) {
  console.log(`  med   ${f.file}:${f.line}  <${f.tag}${f.role ? ` role=${f.role}` : ''}>  ${f.kind}`);
}
const medTotal = findings.filter((x) => x.confidence === 'medium').length;
if (medTotal > 60) console.log(`  ... ${medTotal - 60} more medium-confidence candidates (see JSON)`);

const jsonIdx = process.argv.indexOf('--json');
if (jsonIdx !== -1 && process.argv[jsonIdx + 1]) {
  writeFileSync(process.argv[jsonIdx + 1], JSON.stringify({ byKind, findings }, null, 2));
  console.log(`\nwrote ${process.argv[jsonIdx + 1]}`);
}
console.log('\nSUCCESS:static-unwired-scan');
