import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-opener";

const UI_URL = "http://localhost:5173";

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

async function refresh() {
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

window.addEventListener("DOMContentLoaded", () => {
  byId<HTMLButtonElement>("btn-up").addEventListener("click", () => start(true));
  byId<HTMLButtonElement>("btn-up-nobuild").addEventListener("click", () => start(false));
  byId<HTMLButtonElement>("btn-down").addEventListener("click", () => stop());
  byId<HTMLButtonElement>("btn-refresh").addEventListener("click", () => refresh());
  byId<HTMLButtonElement>("btn-open-ui").addEventListener("click", () => open(UI_URL));

  void refresh();
});
