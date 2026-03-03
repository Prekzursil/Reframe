import { describe, expect, it } from "vitest";

import { toSafeExternalUrl, toSafeMediaUrl, toSafeUrl } from "./url";

describe("toSafeUrl", () => {
  it("allows https and http urls", () => {
    expect(toSafeUrl("https://example.com/file.srt")).toBe("https://example.com/file.srt");
    expect(toSafeUrl("http://localhost:8000/api/v1/jobs")).toBe("http://localhost:8000/api/v1/jobs");
  });

  it("allows blob urls", () => {
    expect(toSafeUrl("blob:http://localhost:5173/abc-123")).toBe("blob:http://localhost:5173/abc-123");
  });

  it("rejects dangerous protocols", () => {
    expect(toSafeUrl("javascript:alert(1)")).toBeNull();
    expect(toSafeUrl("data:text/html,<script>alert(1)</script>")).toBeNull();
    expect(toSafeUrl("file:///etc/passwd")).toBeNull();
  });

  it("rejects urls with credentials", () => {
    expect(toSafeUrl("https://user:pass@example.com/file.srt")).toBeNull();
  });

  it("sanitizes protocol-relative input to https/http safely", () => {
    expect(toSafeUrl("//example.com/path/file.srt")).toBe("http://example.com/path/file.srt");
  });
});

describe("toSafeMediaUrl", () => {
  it("allows blob urls", () => {
    expect(toSafeMediaUrl("blob:http://localhost:5173/abc-123")).toBe("blob:http://localhost:5173/abc-123");
  });

  it("returns null when URL parsing throws", () => {
    expect(toSafeMediaUrl("http://[::1")).toBeNull();
  });

  it("rejects blank media urls", () => {
    expect(toSafeMediaUrl("   ")).toBeNull();
  });
});

describe("toSafeExternalUrl", () => {
  it("rejects blob urls for navigation", () => {
    expect(toSafeExternalUrl("blob:http://localhost:5173/abc-123")).toBeNull();
  });

  it("rejects invalid external URLs and credentials", () => {
    expect(toSafeExternalUrl("http://[::1")).toBeNull();
    expect(toSafeExternalUrl("https://user:pass@example.com")).toBeNull();
  });
});
