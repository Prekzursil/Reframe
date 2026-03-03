import { describe, expect, it } from "vitest";
import { errToString, truncate } from "./text";

describe("text helpers", () => {
  it("converts errors and values to string", () => {
    expect(errToString(new Error("boom"))).toBe("boom");
    expect(errToString("plain")).toBe("plain");
    expect(errToString({ code: 7 })).toContain("code");

    const circular: Record<string, unknown> = {};
    circular.self = circular;
    expect(errToString(circular)).toContain("[object Object]");
  });

  it("truncates long strings with marker", () => {
    expect(truncate("short", 10)).toBe("short");
    expect(truncate("abcdef", 3)).toBe("abc\n…(truncated)…");
  });
});
