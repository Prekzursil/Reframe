import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "../../..");
const runtimeRoot = path.resolve(scriptDir, "../src-tauri/runtime");
const webDist = path.join(repoRoot, "apps", "web", "dist");

function normalize(p) {
  return p.replace(/\\/g, "/");
}

function ensureDir(p) {
  fs.mkdirSync(p, { recursive: true });
}

function clearDir(dir) {
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
}

function copyFile(src, dst) {
  ensureDir(path.dirname(dst));
  fs.copyFileSync(src, dst);
}

function shouldSkip(relPath) {
  const normalized = normalize(relPath);
  if (normalized.includes("/__pycache__/")) return true;
  if (normalized.endsWith(".pyc")) return true;
  if (/\/test_.*\.py$/i.test(normalized)) return true;
  if (normalized.endsWith("/README.md")) return true;
  return false;
}

function copyTree(srcRoot, dstRoot) {
  const stack = [""];
  while (stack.length > 0) {
    const rel = stack.pop();
    const src = path.join(srcRoot, rel);
    const entries = fs.readdirSync(src, { withFileTypes: true });
    for (const entry of entries) {
      const nextRel = rel ? path.join(rel, entry.name) : entry.name;
      if (shouldSkip(nextRel)) continue;
      const srcPath = path.join(srcRoot, nextRel);
      const dstPath = path.join(dstRoot, nextRel);
      if (entry.isDirectory()) {
        ensureDir(dstPath);
        stack.push(nextRel);
      } else if (entry.isFile()) {
        copyFile(srcPath, dstPath);
      }
    }
  }
}

function requirePath(label, p) {
  if (!fs.existsSync(p)) {
    throw new Error(`${label} missing: ${p}`);
  }
}

function writeManifest(files) {
  const manifest = {
    generated_utc: new Date().toISOString(),
    runtime_root: normalize(path.relative(repoRoot, runtimeRoot)),
    files,
  };
  const outPath = path.join(runtimeRoot, "manifest.json");
  fs.writeFileSync(outPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
}

function main() {
  requirePath("API requirements", path.join(repoRoot, "apps", "api", "requirements.txt"));
  requirePath("Worker requirements", path.join(repoRoot, "services", "worker", "requirements.txt"));
  requirePath("Media core package", path.join(repoRoot, "packages", "media-core", "src", "media_core"));
  requirePath("Web dist", webDist);
  requirePath("Web dist index", path.join(webDist, "index.html"));

  clearDir(runtimeRoot);

  const copies = [
    {
      src: path.join(repoRoot, "apps", "api", "app"),
      dst: path.join(runtimeRoot, "apps", "api", "app"),
      tree: true,
    },
    {
      src: path.join(repoRoot, "apps", "api", "requirements.txt"),
      dst: path.join(runtimeRoot, "apps", "api", "requirements.txt"),
      tree: false,
    },
    {
      src: path.join(repoRoot, "services", "worker"),
      dst: path.join(runtimeRoot, "services", "worker"),
      tree: true,
    },
    {
      src: path.join(repoRoot, "packages", "media-core", "src", "media_core"),
      dst: path.join(runtimeRoot, "packages", "media-core", "src", "media_core"),
      tree: true,
    },
    {
      src: webDist,
      dst: path.join(runtimeRoot, "apps", "web", "dist"),
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
