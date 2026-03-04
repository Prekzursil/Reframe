import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "../../..");
const runtimeRoot = path.resolve(scriptDir, "../src-tauri/runtime");
const webDist = path.resolve(repoRoot, "apps/web/dist");

function normalize(p) {
  return p.replace(/\\/g, "/");
}

function assertInside(base, candidate, label) {
  const rel = path.relative(base, candidate);
  if (rel.startsWith("..") || path.isAbsolute(rel)) {
    throw new Error(`${label} path escapes root: ${candidate}`);
  }
}

function resolveInside(base, relPath, label) {
  const safeRel = normalize(String(relPath || ""));
  if (safeRel.includes("..")) {
    throw new Error(`${label} path traversal detected: ${safeRel}`);
  }
  const resolved = path.resolve(base, safeRel);
  assertInside(base, resolved, label);
  return resolved;
}

function resolveRepo(...segments) {
  const resolved = path.resolve(repoRoot, ...segments);
  assertInside(repoRoot, resolved, "repo");
  return resolved;
}

function resolveRuntime(...segments) {
  const resolved = path.resolve(runtimeRoot, ...segments);
  assertInside(runtimeRoot, resolved, "runtime");
  return resolved;
}

function ensureDir(resolvedPath) {
  // nosemgrep: javascript.pathtraversal.rule-non-literal-fs-filename -- validated by resolveInside/assertInside
  fs.mkdirSync(resolvedPath, { recursive: true });
}

function clearRuntimeDir() {
  // nosemgrep: javascript.pathtraversal.rule-non-literal-fs-filename -- runtimeRoot is fixed and trusted
  fs.rmSync(runtimeRoot, { recursive: true, force: true });
  // nosemgrep: javascript.pathtraversal.rule-non-literal-fs-filename -- runtimeRoot is fixed and trusted
  fs.mkdirSync(runtimeRoot, { recursive: true });
}

function copyFile(srcPath, dstPath) {
  ensureDir(path.dirname(dstPath));
  fs.copyFileSync(srcPath, dstPath);
}

function shouldSkip(relPath) {
  const normalized = normalize(relPath);
  if (normalized.includes("/__pycache__/")) {
    return true;
  }
  if (normalized.endsWith(".pyc")) {
    return true;
  }
  if (/\/test_.*\.py$/i.test(normalized)) {
    return true;
  }
  if (normalized.endsWith("/README.md")) {
    return true;
  }
  return false;
}

function copyTree(srcRoot, dstRoot) {
  const stack = [""];
  while (stack.length > 0) {
    const rel = stack.pop();
    const srcDir = resolveInside(srcRoot, rel, "copy-tree-src");
    // nosemgrep: javascript.pathtraversal.rule-non-literal-fs-filename -- srcDir validated by resolveInside
    const entries = fs.readdirSync(srcDir, { withFileTypes: true });

    for (const entry of entries) {
      const nextRel = rel ? `${rel}/${entry.name}` : entry.name;
      if (shouldSkip(nextRel)) {
        continue;
      }

      const srcPath = resolveInside(srcRoot, nextRel, "copy-tree-src");
      const dstPath = resolveInside(dstRoot, nextRel, "copy-tree-dst");
      if (entry.isDirectory()) {
        ensureDir(dstPath);
        stack.push(nextRel);
      } else if (entry.isFile()) {
        copyFile(srcPath, dstPath);
      }
    }
  }
}

function requirePath(label, targetPath) {
  // nosemgrep: javascript.pathtraversal.rule-non-literal-fs-filename -- targetPath pre-resolved from trusted roots
  if (!fs.existsSync(targetPath)) {
    throw new Error(`${label} missing: ${targetPath}`);
  }
}

function writeManifest(files) {
  const manifest = {
    generated_utc: new Date().toISOString(),
    runtime_root: normalize(path.relative(repoRoot, runtimeRoot)),
    files,
  };
  const outPath = resolveRuntime("manifest.json");
  // nosemgrep: javascript.pathtraversal.rule-non-literal-fs-filename -- outPath resolved inside runtime root
  fs.writeFileSync(outPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
}

function main() {
  const apiRequirements = resolveRepo("apps", "api", "requirements.txt");
  const workerRequirements = resolveRepo("services", "worker", "requirements.txt");
  const mediaCorePackage = resolveRepo("packages", "media-core", "src", "media_core");
  const webDistIndex = path.resolve(webDist, "index.html");

  requirePath("API requirements", apiRequirements);
  requirePath("Worker requirements", workerRequirements);
  requirePath("Media core package", mediaCorePackage);
  requirePath("Web dist", webDist);
  requirePath("Web dist index", webDistIndex);

  clearRuntimeDir();

  const copies = [
    {
      src: resolveRepo("apps", "api", "app"),
      dst: resolveRuntime("apps", "api", "app"),
      tree: true,
    },
    {
      src: apiRequirements,
      dst: resolveRuntime("apps", "api", "requirements.txt"),
      tree: false,
    },
    {
      src: resolveRepo("services", "worker"),
      dst: resolveRuntime("services", "worker"),
      tree: true,
    },
    {
      src: mediaCorePackage,
      dst: resolveRuntime("packages", "media-core", "src", "media_core"),
      tree: true,
    },
    {
      src: webDist,
      dst: resolveRuntime("apps", "web", "dist"),
      tree: true,
    },
  ];

  const copied = [];
  for (const item of copies) {
    requirePath("Source", item.src);
    if (item.tree) {
      copyTree(item.src, item.dst);
    } else {
      copyFile(item.src, item.dst);
    }
    copied.push({
      src: normalize(path.relative(repoRoot, item.src)),
      dst: normalize(path.relative(repoRoot, item.dst)),
      mode: item.tree ? "tree" : "file",
    });
  }

  writeManifest(copied);
  console.log(`Prepared desktop runtime resources at ${runtimeRoot}`);
}

main();
