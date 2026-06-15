import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

if (!("createObjectURL" in URL)) {
  Object.defineProperty(URL, "createObjectURL", {
    value: vi.fn(() => "blob:http://localhost/mock"),
    writable: true,
  });
}

if (!("clipboard" in navigator)) {
  Object.defineProperty(navigator, "clipboard", {
    value: {
      writeText: vi.fn(),
    },
    configurable: true,
  });
}

// jsdom under vitest 4 exposes an incomplete Storage (missing removeItem), which
// breaks tests that reset auth state in beforeEach. Install a complete in-memory
// localStorage/sessionStorage when the runtime one lacks the full API.
function createStorageMock(): Storage {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => (key in store ? store[key] : null),
    setItem: (key: string, value: string) => {
      store[key] = String(value);
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
    key: (index: number) => Object.keys(store)[index] ?? null,
    get length() {
      return Object.keys(store).length;
    },
  } as Storage;
}

for (const name of ["localStorage", "sessionStorage"] as const) {
  const current = (globalThis as Record<string, unknown>)[name] as Storage | undefined;
  if (!current || typeof current.removeItem !== "function") {
    Object.defineProperty(globalThis, name, {
      value: createStorageMock(),
      writable: true,
      configurable: true,
    });
  }
}

