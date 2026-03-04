import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const getBundleTypeMock = vi.fn();
const getIdentifierMock = vi.fn();
const getNameMock = vi.fn();
const getTauriVersionMock = vi.fn();
const getVersionMock = vi.fn();
const invokeMock = vi.fn();
const openUrlMock = vi.fn();
const relaunchMock = vi.fn();
const checkMock = vi.fn();

vi.mock("@tauri-apps/api/app", () => ({
  getBundleType: getBundleTypeMock,
  getIdentifier: getIdentifierMock,
  getName: getNameMock,
  getTauriVersion: getTauriVersionMock,
  getVersion: getVersionMock,
}));

vi.mock("@tauri-apps/api/core", () => ({ invoke: invokeMock }));
vi.mock("@tauri-apps/plugin-opener", () => ({ openUrl: openUrlMock }));
vi.mock("@tauri-apps/plugin-process", () => ({ relaunch: relaunchMock }));
vi.mock("@tauri-apps/plugin-updater", () => ({ check: checkMock }));

const UI_URL = "http://localhost:5173";
const RELEASES_URL = "https://github.com/Prekzursil/Reframe/releases";
const DOCS_URL = "http://localhost:8000/docs";
const LATEST_JSON_URL =
  "https://github.com/Prekzursil/Reframe/releases/latest/download/latest.json";

const htmlFixture = `
  <button id="btn-up">up</button>
  <button id="btn-up-nobuild">up-nobuild</button>
  <button id="btn-down">down</button>
  <button id="btn-refresh">refresh</button>
  <button id="btn-open-ui">open-ui</button>
  <button id="btn-copy-debug">copy-debug</button>
  <button id="btn-updates">updates</button>
  <button id="btn-latest-json">latest-json</button>
  <button id="btn-releases">releases</button>
  <pre id="log">Ready.</pre>
  <pre id="status">Loading…</pre>
  <code id="ui-url"></code>
  <code id="api-url"></code>
  <code id="offline-mode"></code>
  <code id="storage-backend"></code>
  <code id="worker-ping"></code>
  <code id="ffmpeg"></code>
  <pre id="system-status"></pre>
  <code id="compose-path"></code>
  <code id="app-version"></code>
  <code id="updater-manifest"></code>
  <code id="docker-version"></code>
  <code id="step-runtime"></code>
  <code id="step-api"></code>
  <code id="step-worker"></code>
`;

type RuntimeState = {
  appFailures: Set<string>;
  invokeFailures: Set<string>;
  invokeValues: Record<string, string>;
  fetchQueue: Array<Response | Promise<Response>>;
  updateMode: "none" | "available" | "throw";
  updateDownloadFails: boolean;
  confirmQueue: boolean[];
};

const state: RuntimeState = {
  appFailures: new Set<string>(),
  invokeFailures: new Set<string>(),
  invokeValues: {
    compose_file_path: "/tmp/compose.yml",
    docker_version: "Docker 28.3.3",
    compose_ps: "api up\nworker up",
    compose_up: "compose up ok",
    compose_down: "compose down ok",
  },
  fetchQueue: [],
  updateMode: "none",
  updateDownloadFails: false,
  confirmQueue: [],
};

const defaultSystemPayload = {
  offline_mode: true,
  storage_backend: "local",
  worker: {
    ping_ok: true,
    system_info: {
      ffmpeg: {
        present: true,
        version: "6.1",
      },
    },
  },
};

const writeTextMock = vi.fn();
const promptMock = vi.spyOn(window, "prompt").mockImplementation(() => null);
const confirmMock = vi
  .spyOn(window, "confirm")
  .mockImplementation(() => state.confirmQueue.shift() ?? false);

function makeResponse(status: number, body: unknown, statusText = "OK"): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText,
    json: async () => body,
    text: async () => (typeof body === "string" ? body : JSON.stringify(body)),
  } as Response;
}

const fetchMock = vi.fn(async () => {
  const queued = state.fetchQueue.shift();
  if (queued) {
    return queued;
  }
  return makeResponse(200, defaultSystemPayload);
});

let appModule: Awaited<typeof import("./main")>;

function resetState() {
  state.appFailures.clear();
  state.invokeFailures.clear();
  state.fetchQueue = [];
  state.updateMode = "none";
  state.updateDownloadFails = false;
  state.confirmQueue = [];
  state.invokeValues = {
    compose_file_path: "/tmp/compose.yml",
    docker_version: "Docker 28.3.3",
    compose_ps: "api up\nworker up",
    compose_up: "compose up ok",
    compose_down: "compose down ok",
  };
}

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
}

async function click(id: string) {
  (document.getElementById(id) as HTMLButtonElement).click();
  await flush();
}

function setAppMocks() {
  getNameMock.mockImplementation(async () => {
    if (state.appFailures.has("getName")) throw new Error("getName failed");
    return "Reframe";
  });

  getVersionMock.mockImplementation(async () => {
    if (state.appFailures.has("getVersion")) throw new Error("getVersion failed");
    return "0.1.8";
  });

  getTauriVersionMock.mockImplementation(async () => {
    if (state.appFailures.has("getTauriVersion")) throw new Error("getTauriVersion failed");
    return "2.0.0";
  });

  getIdentifierMock.mockImplementation(async () => {
    if (state.appFailures.has("getIdentifier")) throw new Error("getIdentifier failed");
    return "ai.reframe.desktop";
  });

  getBundleTypeMock.mockImplementation(async () => {
    if (state.appFailures.has("getBundleType")) throw new Error("getBundleType failed");
    return "msi";
  });

  invokeMock.mockImplementation(async (command: string) => {
    if (state.invokeFailures.has(command)) {
      throw new Error(`${command} failed`);
    }
    return state.invokeValues[command] ?? "";
  });

  checkMock.mockImplementation(async () => {
    if (state.updateMode === "throw") {
      throw new Error("update check failed");
    }
    if (state.updateMode === "none") {
      return null;
    }

    return {
      currentVersion: "0.1.8",
      version: "0.1.9",
      downloadAndInstall: async (onEvent: (evt: any) => void) => {
        onEvent({ event: "Started", data: { contentLength: 120 } });
        onEvent({ event: "Progress", data: { chunkLength: 70 } });
        onEvent({ event: "Progress", data: { chunkLength: 50 } });
        onEvent({ event: "Finished", data: {} });
        if (state.updateDownloadFails) {
          throw new Error("download failed");
        }
      },
    };
  });
}

describe("desktop main app", () => {
  beforeAll(async () => {
    document.body.innerHTML = htmlFixture;

    Object.defineProperty(globalThis, "fetch", {
      value: fetchMock,
      configurable: true,
      writable: true,
    });

    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: writeTextMock },
      configurable: true,
    });

    setAppMocks();
    appModule = await import("./main");
    window.dispatchEvent(new Event("DOMContentLoaded"));
    await flush();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    resetState();
    setAppMocks();

    writeTextMock.mockResolvedValue(undefined);
    promptMock.mockReturnValue(null);
    confirmMock.mockImplementation(() => state.confirmQueue.shift() ?? false);

    document.getElementById("log")!.textContent = "Ready.";
    document.getElementById("status")!.textContent = "Loading…";
  });

  it("wires click handlers and exposes base app metadata", async () => {
    await appModule.__test.refresh();

    expect(document.getElementById("app-version")?.textContent).toBe("0.1.8");
    expect(document.getElementById("compose-path")?.textContent).toBe("/tmp/compose.yml");
    expect(document.getElementById("updater-manifest")?.textContent).toBe(LATEST_JSON_URL);

    state.invokeValues.compose_ps = "api running (pid 42)\\nqueue mode: local";
    await click("btn-open-ui");
    await click("btn-latest-json");
    await click("btn-releases");

    expect(openUrlMock).toHaveBeenCalledWith(UI_URL);
    expect(openUrlMock).toHaveBeenCalledWith(LATEST_JSON_URL);
    expect(openUrlMock).toHaveBeenCalledWith(RELEASES_URL);
    state.invokeValues.compose_ps = "api up\\nworker up";
    await appModule.__test.openProductExperience();
    expect(invokeMock).toHaveBeenCalledWith("compose_up", { build: true });
    state.invokeValues.compose_ps = "";
    await appModule.__test.openProductExperience();

    state.invokeFailures.add("compose_ps");
    await appModule.__test.openProductExperience();
    expect(openUrlMock).toHaveBeenCalledWith(DOCS_URL);
    expect(document.getElementById("log")?.textContent ?? "").toContain("Unable to prepare Studio launch");
  });

  it("runs start/stop commands and click handlers", async () => {
    await appModule.__test.start(true);
    await appModule.__test.start(false);
    await appModule.__test.stop();

    expect(invokeMock).toHaveBeenCalledWith("compose_up", { build: true });
    expect(invokeMock).toHaveBeenCalledWith("compose_up", { build: false });
    expect(invokeMock).toHaveBeenCalledWith("compose_down");

    await click("btn-up");
    await click("btn-up-nobuild");
    await click("btn-down");
    await click("btn-refresh");
  });

  it("logs start and stop failures", async () => {
    state.invokeFailures.add("compose_up");
    state.invokeFailures.add("compose_down");
    await appModule.__test.start(true);
    await appModule.__test.stop();
    expect(document.getElementById("log")?.textContent ?? "").toContain("compose_up failed");
    expect(document.getElementById("log")?.textContent ?? "").toContain("compose_down failed");
  });


  it("covers non-Error and empty-output runtime branches", async () => {
    const firstHandlers: Record<string, () => string | never> = {
      docker_version: () => {
        throw "docker unavailable";
      },
      compose_ps: () => {
        throw "status unavailable";
      },
      compose_up: () => "   ",
      compose_down: () => "",
    };

    invokeMock.mockImplementation(async (command: string) => {
      const handler = firstHandlers[command];
      if (handler) {
        return handler();
      }
      return state.invokeValues[command] ?? "";
    });

    await appModule.__test.refresh();
    expect(document.getElementById("docker-version")?.textContent).toBe("not available");
    expect(document.getElementById("status")?.textContent).toBe("status unavailable");

    await appModule.__test.start(true);
    await appModule.__test.stop();

    const log = document.getElementById("log")?.textContent ?? "";
    expect(log).toContain("OK");

    const secondHandlers: Record<string, () => string | never> = {
      compose_up: () => {
        throw "runtime failed";
      },
      compose_down: () => {
        throw "runtime failed";
      },
    };

    invokeMock.mockImplementation(async (command: string) => {
      const handler = secondHandlers[command];
      if (handler) {
        return handler();
      }
      return state.invokeValues[command] ?? "";
    });

    await appModule.__test.start(true);
    await appModule.__test.stop();
    expect(document.getElementById("log")?.textContent ?? "").toContain("runtime failed");
  });

  it("handles updater started events with unknown content length", async () => {
    checkMock.mockResolvedValueOnce({
      currentVersion: "0.1.8",
      version: "0.1.9",
      downloadAndInstall: async (onEvent: (evt: any) => void) => {
        onEvent({ event: "Started", data: {} });
        onEvent({ event: "Finished", data: {} });
      },
    });
    state.confirmQueue.push(true);

    await appModule.__test.checkUpdates();

    const log = document.getElementById("log")?.textContent ?? "";
    expect(log).toContain("unknown bytes");
    expect(log).toContain("Download finished.");
  });

  it("falls back when refresh dependencies fail", async () => {
    state.invokeFailures.clear();
    state.appFailures.add("getVersion");
    state.invokeFailures.add("compose_file_path");
    state.invokeFailures.add("docker_version");
    state.invokeFailures.add("compose_ps");
    state.fetchQueue.push(makeResponse(503, { message: "down" }, "Service Unavailable"));

    await appModule.__test.refresh();

    expect(document.getElementById("app-version")?.textContent).toBe("unknown");
    expect(document.getElementById("compose-path")?.textContent).toBe("not found");
    expect(document.getElementById("docker-version")?.textContent).toBe("not available");
    expect(document.getElementById("offline-mode")?.textContent).toBe("unknown");
    expect(document.getElementById("system-status")?.textContent).toContain("Diagnostics unavailable");
  });

  it("handles falsey diagnostics payload branches", async () => {
    state.invokeValues.compose_ps = "   ";
    state.invokeValues.docker_version = "  runtime  ";
    getVersionMock.mockResolvedValueOnce("   ");
    state.fetchQueue.push(
      makeResponse(200, {
        offline_mode: false,
        storage_backend: null,
        worker: {
          ping_ok: false,
          system_info: {
            ffmpeg: {
              present: false,
            },
          },
        },
      }),
    );

    await appModule.__test.refresh();

    expect(document.getElementById("app-version")?.textContent).toBe("unknown");
    expect(document.getElementById("worker-ping")?.textContent).toBe("no response");
    expect(document.getElementById("ffmpeg")?.textContent).toBe("missing");
    expect(document.getElementById("status")?.textContent).toContain("(no output)");
    expect(document.getElementById("step-worker")?.textContent).toBe("no response");
  });

  it("tolerates missing onboarding chips when refreshing diagnostics", async () => {
    document.getElementById("step-runtime")?.remove();
    document.getElementById("step-api")?.remove();
    document.getElementById("step-worker")?.remove();

    await appModule.__test.refreshDiagnostics();

    expect(document.getElementById("offline-mode")?.textContent).toBe("true");
  });

  it("handles updater paths: no-update, cancel, install, and failure", async () => {
    state.updateMode = "none";
    await appModule.__test.checkUpdates();
    expect(document.getElementById("log")?.textContent ?? "").toContain("No updates available.");

    state.updateMode = "available";
    state.confirmQueue.push(false);
    await appModule.__test.checkUpdates();
    expect(document.getElementById("log")?.textContent ?? "").toContain("Update cancelled.");

    state.updateMode = "available";
    state.confirmQueue.push(true);
    await appModule.__test.checkUpdates();
    expect(relaunchMock).toHaveBeenCalled();

    state.updateMode = "throw";
    state.confirmQueue.push(true);
    await appModule.__test.checkUpdates();
    expect(openUrlMock).toHaveBeenCalledWith(RELEASES_URL);

    state.updateMode = "throw";
    state.confirmQueue.push(false);
    await appModule.__test.checkUpdates();

    await click("btn-updates");
  });

  it("collects/copies debug info and handles clipboard fallback", async () => {
    state.updateMode = "throw";
    state.confirmQueue.push(false);
    await appModule.__test.checkUpdates();

    state.appFailures.add("getName");
    state.appFailures.add("getVersion");
    state.appFailures.add("getTauriVersion");
    state.appFailures.add("getIdentifier");
    state.appFailures.add("getBundleType");

    state.invokeFailures.add("compose_file_path");
    state.invokeFailures.add("docker_version");
    state.invokeFailures.add("compose_ps");

    state.fetchQueue.push(makeResponse(500, { message: "diag fail" }, "Server Error"));
    await appModule.__test.refreshDiagnostics();

    state.fetchQueue.push(Promise.reject(new Error("network down")) as unknown as Response);
    const debug = await appModule.__test.collectDebugInfo();

    expect(debug).toContain("app_name: error:");
    expect(debug).toContain("app_version: error:");
    expect(debug).toContain("tauri_version: error:");
    expect(debug).toContain("identifier: error:");
    expect(debug).toContain("bundle_type: error:");
    expect(debug).toContain("compose_file: error:");
    expect(debug).toContain("docker_version: error:");
    expect(debug).toContain("compose_ps: error:");
    expect(debug).toContain("system_status_http: error:");
    expect(debug).toContain("last_updater_error:");
    expect(debug).toContain("last_diagnostics_error:");
    expect(debug).toContain("ui_log:");
    expect(debug).toContain("ui_compose_status:");

    await appModule.__test.copyDebugInfo();
    expect(writeTextMock).toHaveBeenCalled();

    writeTextMock.mockRejectedValueOnce(new Error("clipboard denied"));
    await appModule.__test.copyDebugInfo();
    expect(promptMock).toHaveBeenCalled();

    await click("btn-copy-debug");
  });


  it("covers collectDebugInfo unknown fallbacks and empty-ui branches", async () => {
    state.updateMode = "none";
    await appModule.__test.checkUpdates();
    await appModule.__test.refreshDiagnostics();

    document.getElementById("status")!.textContent = "   ";
    document.getElementById("log")!.textContent = "   ";

    getNameMock.mockResolvedValueOnce("   ");
    getVersionMock.mockResolvedValueOnce("   ");
    getTauriVersionMock.mockResolvedValueOnce("   ");
    getIdentifierMock.mockResolvedValueOnce("   ");
    state.invokeValues.compose_ps = "   ";

    state.fetchQueue.push(makeResponse(503, { message: "not-ok" }, "Service Unavailable"));

    const debug = await appModule.__test.collectDebugInfo();
    expect(debug).toContain("app_name: unknown");
    expect(debug).toContain("app_version: unknown");
    expect(debug).toContain("tauri_version: unknown");
    expect(debug).toContain("identifier: unknown");
    expect(debug).toContain("compose_ps: (empty)");
    expect(debug).toContain("system_status_http: 503 Service Unavailable");
    expect(debug).not.toContain("last_updater_error:");
    expect(debug).not.toContain("last_diagnostics_error:");
    expect(debug).not.toContain("ui_compose_status:");
    expect(debug).not.toContain("ui_log:");
  });

  it("covers refresh diagnostics nullish paths and string throw branches", async () => {
    state.fetchQueue.push(makeResponse(200, { offline_mode: false, storage_backend: "local" }));
    await appModule.__test.refreshDiagnostics();
    expect(document.getElementById("worker-ping")?.textContent).toBe("no response");
    expect(document.getElementById("ffmpeg")?.textContent).toBe("missing");

    state.fetchQueue.push(
      makeResponse(200, {
        offline_mode: true,
        storage_backend: "s3",
        worker: {
          ping_ok: true,
          system_info: {
            ffmpeg: {
              present: true,
            },
          },
        },
      }),
    );
    await appModule.__test.refreshDiagnostics();
    expect(document.getElementById("ffmpeg")?.textContent).toBe("ok");

    getVersionMock.mockImplementationOnce(async () => {
      throw "version string error";
    });
    invokeMock.mockImplementation(async (command: string) => {
      if (command === "compose_file_path") {
        throw "compose path string error";
      }
      return state.invokeValues[command] ?? "";
    });

    document.getElementById("log")!.textContent = null;
    await appModule.__test.refresh();
    const log = document.getElementById("log")?.textContent ?? "";
    expect(log).toContain("version string error");
    expect(log).toContain("compose path string error");
  });

  it("covers updater callback branch for unknown events", async () => {
    checkMock.mockResolvedValueOnce({
      currentVersion: "0.1.8",
      version: "0.1.9",
      downloadAndInstall: async (onEvent: (evt: any) => void) => {
        onEvent({ event: "Started", data: { contentLength: 12 } });
        onEvent({ event: "Progress", data: { chunkLength: 12 } });
        onEvent({ event: "Custom", data: {} });
        onEvent({ event: "Finished", data: {} });
      },
    });
    state.confirmQueue.push(true);

    await appModule.__test.checkUpdates();

    const log = document.getElementById("log")?.textContent ?? "";
    expect(log).toContain("Downloaded 12 bytes");
    expect(log).toContain("Download finished.");
  });


  it("covers null textContent branches in append and debug collectors", async () => {
    const logEl = document.getElementById("log") as HTMLPreElement;
    const statusEl = document.getElementById("status") as HTMLPreElement;

    let logStore: string | null = null;
    let statusStore: string | null = null;

    Object.defineProperty(logEl, "textContent", {
      configurable: true,
      get: () => logStore,
      set: (value: string | null) => {
        logStore = value;
      },
    });

    Object.defineProperty(statusEl, "textContent", {
      configurable: true,
      get: () => statusStore,
      set: (value: string | null) => {
        statusStore = value;
      },
    });

    await appModule.__test.start(true);

    logStore = null;
    statusStore = null;
    const debug = await appModule.__test.collectDebugInfo();
    expect(debug).not.toContain("ui_compose_status:");
    expect(debug).not.toContain("ui_log:");

    delete (logEl as any).textContent;
    delete (statusEl as any).textContent;
    logEl.textContent = "Ready.";
    statusEl.textContent = "Loading…";
  });

  it("throws for missing required DOM elements", () => {
    expect(() => appModule.__test.byId("does-not-exist")).toThrow("Missing element #does-not-exist");
  });
});



