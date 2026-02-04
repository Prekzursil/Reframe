import { getVersion } from "@tauri-apps/api/app";
import { invoke } from "@tauri-apps/api/core";
import { openUrl } from "@tauri-apps/plugin-opener";
import { relaunch } from "@tauri-apps/plugin-process";
import { check } from "@tauri-apps/plugin-updater";

const UI_URL = "http://localhost:5173";
const API_URL = "http://localhost:8000/api/v1";
const SYSTEM_STATUS_URL = `${API_URL}/system/status`;
const RELEASES_URL = "https://github.com/Prekzursil/Reframe/releases";

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
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    setText("offline-mode", "unknown");
    setText("storage-backend", "unknown");
    setText("worker-ping", "unknown");
    setText("ffmpeg", "unknown");
    setText("system-status", `Diagnostics unavailable.\n\n${msg}`);
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
      return;
    }

    appendLog(`Update available: ${update.currentVersion} → ${update.version}`);
    const ok = window.confirm(`Update available: ${update.currentVersion} → ${update.version}\n\nDownload and install now?`);
    if (!ok) {
      appendLog("Update cancelled.");
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
    await relaunch();
  } catch (err) {
    appendLog(err instanceof Error ? err.message : String(err));
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
  byId<HTMLButtonElement>("btn-updates").addEventListener("click", () => checkUpdates());
  byId<HTMLButtonElement>("btn-releases").addEventListener("click", () => openUrl(RELEASES_URL));

  void refresh();
});
