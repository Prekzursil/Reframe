import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "./ErrorBoundary";

function Thrower(): never {
  throw new Error("boom");
}

describe("ErrorBoundary", () => {
  it("renders children when no error occurs", () => {
    render(
      <ErrorBoundary>
        <div>healthy child</div>
      </ErrorBoundary>,
    );

    expect(screen.getByText("healthy child")).toBeInTheDocument();
  });

  it("renders fallback when child throws", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});

    render(
      <ErrorBoundary>
        <Thrower />
      </ErrorBoundary>,
    );

    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    expect(screen.getByText("Refresh the page or try again later.")).toBeInTheDocument();

    spy.mockRestore();
  });
});
