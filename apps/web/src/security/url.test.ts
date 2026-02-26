import { describe, expect, it } from "vitest";

import { toSafeUrl } from "./url";

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
});
