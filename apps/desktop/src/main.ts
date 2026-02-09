import {
  getBundleType,
  getIdentifier,
  getName,
  getTauriVersion,
  getVersion,
} from "@tauri-apps/api/app";
import { invoke } from "@tauri-apps/api/core";
import { openUrl } from "@tauri-apps/plugin-opener";
import { relaunch } from "@tauri-apps/plugin-process";
import { check } from "@tauri-apps/plugin-updater";

const UI_URL = "http://localhost:5173";
const API_URL = "http://localhost:8000/api/v1";
const SYSTEM_STATUS_URL = `${API_URL}/system/status`;
const RELEASES_URL = "https://github.com/Prekzursil/Reframe/releases";
const UPDATER_MANIFEST_URL =
  "https://github.com/Prekzursil/Reframe/releases/latest/download/latest.json";

let lastUpdaterError: string | null = null;
let lastDiagnosticsError: string | null = null;

function byId<T extends HTMLElement>(id: string): T {
  const el = document.getElementById(id);
  if (!el) {
    throw new Error(`Missing element #${id}`);
  }
  return el as T;
}

function appendLog(text: string) {
  const log = byId<HTMLPreElement>("log");
  const now = new Date().toISOString().slice(11, 19);
  log.textContent = `${now} ${text}\n${log.textContent ?? ""}`.trimEnd();
}

function setStatus(text: string) {
  byId<HTMLPreElement>("status").textContent = text;
}

function setText(id: string, text: string) {
  byId<HTMLElement>(id).textContent = text;
}

function errToString(err: unknown): string {
  if (err instanceof Error) return err.message;
  if (typeof err === "string") return err;
  try {
    return JSON.stringify(err);
  } catch {
    return String(err);
  }
}

function truncate(text: string, maxChars: number): string {
  if (text.length <= maxChars) return text;
  return `${text.slice(0, maxChars)}\n…(truncated)…`;
}

async function collectDebugInfo(): Promise<string> {
  const lines: string[] = [];

  const push = (label: string, value: string) => {
    lines.push(`${label}: ${value}`);
  };

  push("timestamp", new Date().toISOString());
  push("user_agent", navigator.userAgent);
  push("updater_manifest", UPDATER_MANIFEST_URL);
  push("releases_url", RELEASES_URL);

  try {
    push("app_name", (await getName()).trim() || "unknown");
  } catch (err) {
    push("app_name", `error: ${errToString(err)}`);
  }

  try {
    push("app_version", (await getVersion()).trim() || "unknown");
  } catch (err) {
    push("app_version", `error: ${errToString(err)}`);
  }

  try {
    push("tauri_version", (await getTauriVersion()).trim() || "unknown");
  } catch (err) {
    push("tauri_version", `error: ${errToString(err)}`);
  }

  try {
    push("identifier", (await getIdentifier()).trim() || "unknown");
  } catch (err) {
    push("identifier", `error: ${errToString(err)}`);
  }

  try {
    push("bundle_type", String(await getBundleType()));
  } catch (err) {
    push("bundle_type", `error: ${errToString(err)}`);
  }

  try {
    push("compose_file", await invoke<string>("compose_file_path"));
  } catch (err) {
    push("compose_file", `error: ${errToString(err)}`);
  }

  try {
    push("docker_version", (await invoke<string>("docker_version")).trim());
  } catch (err) {
    push("docker_version", `error: ${errToString(err)}`);
  }

  try {
    push("compose_ps", (await invoke<string>("compose_ps")).trim() || "(empty)");
  } catch (err) {
    push("compose_ps", `error: ${errToString(err)}`);
  }

  try {
    const resp = await fetch(SYSTEM_STATUS_URL, { headers: { Accept: "application/json" } });
    push("system_status_http", `${resp.status} ${resp.statusText}`.trim());
    if (resp.ok) {
      const text = await resp.text();
      push("system_status_body", truncate(text, 4000));
    }
  } catch (err) {
    push("system_status_http", `error: ${errToString(err)}`);
  }

  if (lastUpdaterError) {
    push("last_updater_error", lastUpdaterError);
  }
  if (lastDiagnosticsError) {
    push("last_diagnostics_error", lastDiagnosticsError);
  }

  const statusText = byId<HTMLPreElement>("status").textContent ?? "";
  if (statusText.trim()) {
    push("ui_compose_status", truncate(statusText.trim(), 2000));
  }

  const logText = byId<HTMLPreElement>("log").textContent ?? "";
  if (logText.trim()) {
    push("ui_log", truncate(logText.trim(), 4000));
  }

  return lines.join("\n");
}

async function copyDebugInfo() {
  appendLog("Collecting debug info...");
  const text = await collectDebugInfo();

  try {
    await navigator.clipboard.writeText(text);
    appendLog("Copied debug info to clipboard.");
  } catch (err) {
    const msg = errToString(err);
    appendLog(`Clipboard copy failed: ${msg}`);
    window.prompt("Copy debug info:", text);
  }
}

async function refreshDiagnostics() {
  setText("ui-url", UI_URL);
  setText("api-url", API_URL);

  try {
    const resp = await fetch(SYSTEM_STATUS_URL, { headers: { Accept: "application/json" } });
    if (!resp.ok) {
      throw new Error(`API returned ${resp.status}`);
    }
    const data = (await resp.json()) as any;
    const worker = data?.worker ?? {};
    const systemInfo = worker?.system_info ?? {};
    const ffmpeg = systemInfo?.ffmpeg ?? {};

    setText("offline-mode", data?.offline_mode ? "true" : "false");
    setText("storage-backend", String(data?.storage_backend ?? "unknown"));
    setText("worker-ping", worker?.ping_ok ? "ok" : "no response");
    setText(
      "ffmpeg",
      ffmpeg?.present ? `ok${ffmpeg?.version ? ` (${ffmpeg.version})` : ""}` : "missing",
    );
    setText("system-status", JSON.stringify(data, null, 2));
    lastDiagnosticsError = null;
  } catch (err) {
    const msg = errToString(err);
    setText("offline-mode", "unknown");
    setText("storage-backend", "unknown");
    setText("worker-ping", "unknown");
    setText("ffmpeg", "unknown");
    setText("system-status", `Diagnostics unavailable.\n\n${msg}`);
    lastDiagnosticsError = msg;
  }
}

async function refresh() {
  try {
    const appVersion = await getVersion();
    setText("app-version", appVersion.trim() || "unknown");
  } catch (err) {
    setText("app-version", "unknown");
    appendLog(err instanceof Error ? err.message : String(err));
  }

  setText("updater-manifest", UPDATER_MANIFEST_URL);

  try {
    const composePath = await invoke<string>("compose_file_path");
    byId<HTMLElement>("compose-path").textContent = composePath;
  } catch (err) {
    byId<HTMLElement>("compose-path").textContent = "not found";
    appendLog(err instanceof Error ? err.message : String(err));
  }

  try {
    const version = await invoke<string>("docker_version");
    byId<HTMLElement>("docker-version").textContent = version.trim();
  } catch (err) {
    byId<HTMLElement>("docker-version").textContent = "not available";
    appendLog(err instanceof Error ? err.message : String(err));
  }

  try {
    const ps = await invoke<string>("compose_ps");
    setStatus(ps.trim() || "(no output)");
  } catch (err) {
    setStatus(err instanceof Error ? err.message : String(err));
  }

  await refreshDiagnostics();
}

async function start(build: boolean) {
  appendLog(build ? "Starting stack (build)..." : "Starting stack (no build)...");
  try {
    const out = await invoke<string>("compose_up", { build });
    appendLog(out.trim() || "OK");
  } catch (err) {
    appendLog(err instanceof Error ? err.message : String(err));
  } finally {
    await refresh();
  }
}

async function stop() {
  appendLog("Stopping stack...");
  try {
    const out = await invoke<string>("compose_down");
    appendLog(out.trim() || "OK");
  } catch (err) {
    appendLog(err instanceof Error ? err.message : String(err));
  } finally {
    await refresh();
  }
}

async function checkUpdates() {
  appendLog("Checking for updates...");
  try {
    const update = await check();
    if (!update) {
      appendLog("No updates available.");
      lastUpdaterError = null;
      return;
    }

    appendLog(`Update available: ${update.currentVersion} → ${update.version}`);
    const ok = window.confirm(`Update available: ${update.currentVersion} → ${update.version}\n\nDownload and install now?`);
    if (!ok) {
      appendLog("Update cancelled.");
      lastUpdaterError = null;
      return;
    }

    let downloaded = 0;
    await update.downloadAndInstall((event) => {
      if (event.event === "Started") {
        downloaded = 0;
        appendLog(`Downloading update… (${event.data.contentLength ?? "unknown"} bytes)`);
      } else if (event.event === "Progress") {
        downloaded += event.data.chunkLength;
        appendLog(`Downloaded ${downloaded} bytes…`);
      } else if (event.event === "Finished") {
        appendLog("Download finished.");
      }
    });

    appendLog("Update installed; restarting…");
    lastUpdaterError = null;
    await relaunch();
  } catch (err) {
    const msg = errToString(err);
    lastUpdaterError = msg;
    appendLog(msg);
    const openReleases = window.confirm("Update check failed. Open GitHub Releases page?");
    if (openReleases) {
      await openUrl(RELEASES_URL);
    }
  }
}

window.addEventListener("DOMContentLoaded", () => {
  byId<HTMLButtonElement>("btn-up").addEventListener("click", () => start(true));
  byId<HTMLButtonElement>("btn-up-nobuild").addEventListener("click", () => start(false));
  byId<HTMLButtonElement>("btn-down").addEventListener("click", () => stop());
  byId<HTMLButtonElement>("btn-refresh").addEventListener("click", () => refresh());
  byId<HTMLButtonElement>("btn-open-ui").addEventListener("click", () => openUrl(UI_URL));
  byId<HTMLButtonElement>("btn-copy-debug").addEventListener("click", () => copyDebugInfo());
  byId<HTMLButtonElement>("btn-updates").addEventListener("click", () => checkUpdates());
  byId<HTMLButtonElement>("btn-latest-json").addEventListener("click", () =>
    openUrl(UPDATER_MANIFEST_URL),
  );
  byId<HTMLButtonElement>("btn-releases").addEventListener("click", () => openUrl(RELEASES_URL));

  void refresh();
});
