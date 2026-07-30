#!/usr/bin/env node
// @ts-check
/*
 * mutant_kill_targets.mjs — diff-scoped mutation-survivor analyzer + Codex fan-out
 * task generator for Reframe's INCREMENTAL (PR-blocking-capable) mutation gate.
 *
 * WHY THIS EXISTS
 * ---------------
 * The nightly `.github/workflows/mutation.yml` runs Stryker (renderer) + mutmut
 * (sidecar) over the WHOLE high-value surface, NON-blocking. That is a good
 * second-order signal but it cannot gate a PR: a PR that WEAKENS a test only
 * shows up as a lower global score the next night, with no attribution to the
 * change. This tool closes that gap. It consumes the mutation reports produced
 * by the SAME tools (no re-implementation of mutation testing) and answers a
 * single, PR-scoped question:
 *
 *     "Did THIS diff introduce a NEW surviving mutant on a line THIS diff touched?"
 *
 * Only NEW survivors ON CHANGED LINES can gate — pre-existing survivors on
 * untouched code never fail a PR (that is the nightly's job to burn down). This
 * is the "ratchet, don't wall" discipline: block regressions, not the backlog.
 *
 * TWO MODES
 * ---------
 *   gate   : parse reports + diff -> list NEW survivors on changed lines.
 *            Prints a report and (only with --block) exits 1 if any exist.
 *            Default is SHADOW (exit 0 always) so the gate can be trialled on
 *            real PRs before it is allowed to block. Flip to blocking via
 *            --block (CI wires this to a repo variable).
 *
 *   fanout : same survivor selection, but emits a JSON array of Codex "write a
 *            test that kills this mutant" task payloads (Meta ACH style) for the
 *            scheduled agent to fan out. Never exits non-zero.
 *
 * INPUTS (all optional; missing inputs are treated as "no survivors from that
 * tool", so the tool degrades gracefully when only one ecosystem changed):
 *   --stryker <mutation.json>   Stryker JSON report (mutation-report-schema).
 *   --mutmut  <results.txt>     `mutmut results` text output.
 *   --diff    <file|->          Unified `git diff` (base...head). `-` = stdin.
 *   --changed-files <file|->    Newline list (`git diff --name-only`); used for
 *                               mutmut (module-level) scoping and as a fallback
 *                               source of changed files when --diff is absent.
 *   --repo-root <dir>           Prefix stripped from report paths so they align
 *                               with git paths (default: "").
 *
 * OUTPUT:
 *   --out <file>   Write the machine-readable JSON result here (default: stdout
 *                  for fanout; a human summary always goes to stderr).
 *   --mode gate|fanout   (default gate)
 *   --block        gate mode: exit 1 when new survivors exist (else exit 0).
 *
 * Pure functions are exported for unit testing; the CLI only runs when the file
 * is executed directly. Zero runtime deps (Node stdlib only).
 */

import fs from "node:fs";
import process from "node:process";

/* ------------------------------------------------------------------ *
 * Diff parsing — unified diff -> changed (added) lines on the NEW side
 * ------------------------------------------------------------------ */

/**
 * Parse a unified `git diff` into a map of file -> Set of NEW-side line numbers
 * that were added or modified by the diff. Deleted-only lines contribute no new
 * line and are ignored (you cannot mutate a line that no longer exists).
 *
 * @param {string} diffText
 * @returns {Map<string, Set<number>>}
 */
export function parseChangedLines(diffText) {
  /** @type {Map<string, Set<number>>} */
  const byFile = new Map();
  if (!diffText) return byFile;

  const lines = diffText.split(/\r?\n/);
  /** @type {string | null} */
  let currentFile = null;
  let newLineNo = 0;

  for (const line of lines) {
    // New-file header: "+++ b/path/to/file" (or "+++ path"). Prefer this over
    // the "diff --git" header because it already carries the NEW path.
    if (line.startsWith("+++ ")) {
      let p = line.slice(4).trim();
      if (p === "/dev/null") {
        currentFile = null;
        continue;
      }
      if (p.startsWith("b/")) p = p.slice(2);
      // Strip a trailing tab-metadata segment some diff variants append.
      const tab = p.indexOf("\t");
      if (tab !== -1) p = p.slice(0, tab);
      currentFile = normalizePath(p);
      if (!byFile.has(currentFile)) byFile.set(currentFile, new Set());
      continue;
    }
    if (line.startsWith("--- ")) continue; // old-file header: ignore

    // Hunk header: @@ -oldStart,oldLen +newStart,newLen @@
    const hunk = /^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(line);
    if (hunk) {
      newLineNo = Number(hunk[1]);
      continue;
    }
    if (currentFile == null) continue;

    if (line.startsWith("+")) {
      // Added / modified line on the NEW side.
      byFile.get(currentFile)?.add(newLineNo);
      newLineNo += 1;
    } else if (line.startsWith("-")) {
      // Removed from OLD side — new-side counter does not advance.
    } else if (line.startsWith("\\")) {
      // "\ No newline at end of file" — metadata, no line movement.
    } else {
      // Context line — advances the new-side counter.
      newLineNo += 1;
    }
  }
  return byFile;
}

/** Normalize a repo path to forward slashes with no leading "./". */
export function normalizePath(p) {
  let out = String(p).replace(/\\/g, "/");
  while (out.startsWith("./")) out = out.slice(2);
  return out;
}

/**
 * Derive the set of changed files. Prefers an explicit `--changed-files` list;
 * falls back to the files present in the parsed diff.
 * @param {string} changedFilesText
 * @param {Map<string, Set<number>>} changedLines
 * @returns {Set<string>}
 */
export function deriveChangedFiles(changedFilesText, changedLines) {
  const set = new Set();
  if (changedFilesText) {
    for (const raw of changedFilesText.split(/\r?\n/)) {
      const p = raw.trim();
      if (p) set.add(normalizePath(p));
    }
  }
  for (const f of changedLines.keys()) set.add(f);
  return set;
}

/* ------------------------------------------------------------------ *
 * Stryker JSON report -> survivors (line-precise)
 * ------------------------------------------------------------------ */

// Mutant statuses that represent an UNKILLED mutant needing a test.
// (Timeout / Killed = a test caught it; Compile/RuntimeError & Ignored are not
// actionable survivors.)
const UNKILLED = new Set(["Survived", "NoCoverage"]);

/**
 * @param {any} report  Parsed Stryker `mutation.json`.
 * @param {string} [repoRoot]  Prefix to prepend when report paths are repo-root
 *   relative but the diff paths carry a subdir (unused when equal).
 * @returns {Array<{tool:string,file:string,line:number,mutator:string,replacement:string,status:string,id:string}>}
 */
export function parseStrykerSurvivors(report, repoRoot = "") {
  const out = [];
  if (!report || typeof report !== "object" || !report.files) return out;
  for (const [rawFile, entry] of Object.entries(report.files)) {
    const file = joinRepoPath(repoRoot, normalizePath(rawFile));
    const mutants = /** @type {any} */ (entry)?.mutants;
    if (!Array.isArray(mutants)) continue;
    for (const m of mutants) {
      if (!UNKILLED.has(m?.status)) continue;
      const line = m?.location?.start?.line;
      if (typeof line !== "number") continue;
      out.push({
        tool: "stryker",
        file,
        line,
        mutator: String(m.mutatorName ?? "unknown"),
        replacement: typeof m.replacement === "string" ? m.replacement : "",
        status: String(m.status),
        id: String(m.id ?? `${file}:${line}:${m.mutatorName}`),
      });
    }
  }
  return out;
}

/** Join a repo-root prefix to a report-relative path, avoiding double slashes. */
export function joinRepoPath(repoRoot, file) {
  if (!repoRoot) return file;
  const base = normalizePath(repoRoot).replace(/\/+$/, "");
  return `${base}/${file}`;
}

/* ------------------------------------------------------------------ *
 * mutmut results -> survivors (module/file-level; mutmut is not line-precise
 * in the same schema, so we scope it to CHANGED FILES per the spec:
 * "mutmut on git diff --name-only").
 * ------------------------------------------------------------------ */

/**
 * Parse `mutmut results` text. mutmut 3.x prints survivor IDs of the form
 * `media_studio.ffmpeg.func__mutmut_12` (dotted module path). We map the module
 * prefix back to a file path (`media_studio/ffmpeg.py`) so survivors can be
 * scoped to the diff's changed files.
 *
 * The parser is liberal: it collects every token matching a mutmut id pattern
 * anywhere in the text, so it tolerates the "survived"/"timeout" section
 * headers and the "id: status" line format alike. Only survivors are returned.
 *
 * @param {string} text
 * @param {string} [repoRoot]  Prefix prepended to the derived file path so it
 *   aligns with git-diff paths (e.g. "sidecar" -> "sidecar/media_studio/..").
 * @returns {Array<{tool:string,file:string,line:number,mutator:string,replacement:string,status:string,id:string}>}
 */
export function parseMutmutSurvivors(text, repoRoot = "") {
  const out = [];
  if (!text) return out;
  const lines = text.split(/\r?\n/);
  // Track the current section header so a bare list of ids is attributed
  // correctly. mutmut groups as "Survived", "Timeout", etc.
  let section = "";
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;
    const header = /^(survived|timeout|suspicious|killed|no tests|skipped)\b/i.exec(line);
    if (header) {
      section = header[1].toLowerCase();
      // A header line may still carry ids after a colon — fall through.
    }
    // Extract mutmut ids: dotted path ending in `__mutmut_<n>`.
    const ids = line.match(/[A-Za-z_][\w.]*__mutmut_\d+/g);
    if (!ids) continue;
    // Determine status for these ids: an explicit ": survived" wins, else the
    // active section header, else assume survived (conservative — flags it).
    let status = "survived";
    const inline = /:\s*(survived|timeout|suspicious|killed|ok)/i.exec(line);
    if (inline) status = inline[1].toLowerCase();
    else if (section) status = section;
    if (status !== "survived" && status !== "no tests") continue;
    for (const id of ids) {
      out.push({
        tool: "mutmut",
        file: joinRepoPath(repoRoot, mutmutIdToFile(id)),
        line: 0, // mutmut ids are module/function scoped, not line-precise.
        mutator: mutmutIdToFunction(id),
        replacement: "",
        status: status === "no tests" ? "NoCoverage" : "Survived",
        id,
      });
    }
  }
  // De-dup (a header + inline can double-count the same id).
  const seen = new Set();
  return out.filter((s) => (seen.has(s.id) ? false : seen.add(s.id)));
}

/** `media_studio.ffmpeg.func__mutmut_12` -> `media_studio/ffmpeg.py`. */
export function mutmutIdToFile(id) {
  const base = id.split("__mutmut_")[0]; // media_studio.ffmpeg.func
  const parts = base.split(".");
  // Drop the trailing function/attribute segment(s): a module path is the
  // longest prefix; mutmut ids append at least the function name. Heuristic:
  // treat the last segment as the function unless there is only the module.
  if (parts.length >= 2) parts.pop();
  return `${parts.join("/")}.py`;
}

/** Extract the function segment of a mutmut id for a human hint. */
export function mutmutIdToFunction(id) {
  const base = id.split("__mutmut_")[0];
  const parts = base.split(".");
  return parts.length ? parts[parts.length - 1] : base;
}

/* ------------------------------------------------------------------ *
 * Selection: NEW survivors on CHANGED lines (Stryker) / CHANGED files (mutmut)
 * ------------------------------------------------------------------ */

/**
 * @param {Array<any>} survivors  Combined Stryker+mutmut survivors.
 * @param {Map<string, Set<number>>} changedLines
 * @param {Set<string>} changedFiles
 * @returns {Array<any>}  The subset that this diff is accountable for.
 */
export function selectNewSurvivors(survivors, changedLines, changedFiles) {
  const selected = [];
  for (const s of survivors) {
    if (!changedFiles.has(s.file)) continue; // must touch a changed file
    if (s.tool === "stryker") {
      // Line-precise: the survivor's line must be one the diff added/modified.
      const lines = changedLines.get(s.file);
      if (lines && lines.has(s.line)) selected.push(s);
    } else {
      // mutmut: file-level scoping (spec: "mutmut on git diff --name-only").
      selected.push(s);
    }
  }
  return selected;
}

/* ------------------------------------------------------------------ *
 * Codex fan-out task payloads ("write a test that kills this mutant")
 * ------------------------------------------------------------------ */

/**
 * Turn selected survivors into structured Codex task payloads. Each payload is
 * a self-contained "kill this mutant" instruction (Meta ACH pattern). The
 * scheduled agent hands these to the codex mcp-server fan-out.
 *
 * @param {Array<any>} survivors
 * @returns {Array<{id:string,tool:string,file:string,line:number,mutator:string,title:string,prompt:string}>}
 */
export function buildCodexTasks(survivors) {
  return survivors.map((s) => {
    const where = s.line ? `${s.file}:${s.line}` : s.file;
    const repl = s.replacement ? ` The mutation replaces the original code with: \`${s.replacement}\`.` : "";
    const fn = s.mutator && s.tool === "mutmut" ? ` (function \`${s.mutator}\`)` : "";
    const title = `Kill surviving ${s.tool} mutant ${s.mutator} at ${where}`;
    const prompt = [
      `A mutation-testing survivor was found in \`${s.file}\`${s.line ? ` at line ${s.line}` : ""}${fn}.`,
      `Mutator: ${s.mutator} (${s.tool}). Status: ${s.status}.${repl}`,
      ``,
      `Task: write ONE focused, deterministic unit test that FAILS when this`,
      `specific mutation is applied and PASSES on the unmutated code — i.e. a`,
      `test that "kills" the mutant. Do NOT weaken any existing test or assertion.`,
      `Strengthen the real behavioural contract of the code under mutation.`,
      ``,
      `Acceptance: the new test must pass on HEAD, and re-running the mutation`,
      `tool must report this mutant as Killed (not Survived / NoCoverage).`,
    ].join("\n");
    return {
      id: s.id,
      tool: s.tool,
      file: s.file,
      line: s.line,
      mutator: s.mutator,
      title,
      prompt,
    };
  });
}

/* ------------------------------------------------------------------ *
 * Orchestration
 * ------------------------------------------------------------------ */

/**
 * @param {{strykerReport?:any, mutmutText?:string, diffText?:string,
 *   changedFilesText?:string, repoRoot?:string, selectAll?:boolean}} inputs
 */
export function analyze(inputs) {
  const changedLines = parseChangedLines(inputs.diffText ?? "");
  const changedFiles = deriveChangedFiles(inputs.changedFilesText ?? "", changedLines);
  const survivors = [
    ...parseStrykerSurvivors(inputs.strykerReport, inputs.repoRoot ?? ""),
    ...parseMutmutSurvivors(inputs.mutmutText ?? "", inputs.repoRoot ?? ""),
  ];
  // selectAll: the scheduled fan-out agent wants EVERY current survivor turned
  // into a kill-test task, not just the diff-scoped subset. The PR gate never
  // sets this (it is strictly diff-scoped so it can only ratchet, not wall).
  const selected = inputs.selectAll
    ? survivors.slice()
    : selectNewSurvivors(survivors, changedLines, changedFiles);
  return {
    changedFiles: [...changedFiles].sort(),
    totalSurvivors: survivors.length,
    selected,
    tasks: buildCodexTasks(selected),
  };
}

/* ------------------------------------------------------------------ *
 * CLI
 * ------------------------------------------------------------------ */

/** Tiny arg parser: --key value / --flag. */
export function parseArgs(argv) {
  const out = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith("--")) {
      const key = a.slice(2);
      const next = argv[i + 1];
      if (next === undefined || next.startsWith("--")) {
        out[key] = true;
      } else {
        out[key] = next;
        i++;
      }
    } else {
      out._.push(a);
    }
  }
  return out;
}

function readMaybe(path) {
  if (!path) return "";
  if (path === "-") return fs.readFileSync(0, "utf8");
  if (!fs.existsSync(path)) return "";
  return fs.readFileSync(path, "utf8");
}

function readJsonMaybe(path) {
  const txt = readMaybe(path);
  if (!txt.trim()) return undefined;
  try {
    return JSON.parse(txt);
  } catch (err) {
    process.stderr.write(`WARN: could not parse JSON from ${path}: ${err}\n`);
    return undefined;
  }
}

export function main(argv) {
  const args = parseArgs(argv);
  const mode = args.mode === "fanout" ? "fanout" : "gate";
  const diffText = readMaybe(args.diff);
  const changedFilesText = readMaybe(args["changed-files"]);
  // In fanout mode with NO diff scoping supplied (or an explicit --all), fan out
  // every current survivor. In gate mode we NEVER select-all: an absent diff
  // means "this PR changed nothing relevant" -> zero gated survivors.
  const selectAll =
    Boolean(args.all) || (mode === "fanout" && !diffText.trim() && !changedFilesText.trim());
  const result = analyze({
    strykerReport: readJsonMaybe(args.stryker),
    mutmutText: readMaybe(args.mutmut),
    diffText,
    changedFilesText,
    repoRoot: typeof args["repo-root"] === "string" ? args["repo-root"] : "",
    selectAll,
  });

  const payload =
    mode === "fanout"
      ? { mode, count: result.tasks.length, tasks: result.tasks }
      : {
          mode,
          blocking: Boolean(args.block),
          newSurvivors: result.selected.length,
          changedFiles: result.changedFiles,
          survivors: result.selected,
        };

  const json = JSON.stringify(payload, null, 2);
  if (typeof args.out === "string") fs.writeFileSync(args.out, json + "\n");
  else if (mode === "fanout") process.stdout.write(json + "\n");

  // Human summary -> stderr (keeps stdout clean for piping in fanout mode).
  const n = result.selected.length;
  if (mode === "gate") {
    if (n === 0) {
      process.stderr.write(
        `SUCCESS: no new surviving mutants on changed lines ` +
          `(${result.totalSurvivors} survivor(s) total, all on untouched code).\n`,
      );
    } else {
      process.stderr.write(
        `${args.block ? "FAILED" : "SHADOW"}: ${n} new surviving mutant(s) on changed lines:\n`,
      );
      for (const s of result.selected) {
        const where = s.line ? `${s.file}:${s.line}` : s.file;
        process.stderr.write(`  - [${s.tool}] ${s.mutator} @ ${where} (${s.status})\n`);
      }
      process.stderr.write(
        args.block
          ? `\nThese mutations survived on lines this PR changed. Add/strengthen a ` +
              `test that KILLS each (never weaken an assertion), then re-run.\n`
          : `\n(SHADOW mode: not blocking. Set --block to make this gate PR-blocking.)\n`,
      );
    }
    // Only exit non-zero when explicitly asked to block AND survivors exist.
    return args.block && n > 0 ? 1 : 0;
  }

  process.stderr.write(`SUCCESS: emitted ${result.tasks.length} Codex kill-test task(s).\n`);
  return 0;
}

// Run only when executed directly (not when imported by a test).
const invokedPath = process.argv[1] ? normalizePath(process.argv[1]) : "";
if (invokedPath.endsWith("mutant_kill_targets.mjs")) {
  process.exit(main(process.argv.slice(2)));
}
