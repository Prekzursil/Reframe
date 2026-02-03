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

