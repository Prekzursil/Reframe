import { expect, type Page } from "@playwright/test";

export const NAV_LABELS = [
  "Shorts",
  "Captions",
  "Subtitles",
  "Utilities",
  "Jobs",
  "Usage",
  "Projects",
  "Account",
  "Billing",
] as const;

export async function walkPrimarySections(page: Page): Promise<void> {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Reframe" })).toBeVisible();

  for (const label of NAV_LABELS) {
    await page.getByRole("button", { name: label }).click();
    await expect(page.getByRole("button", { name: label })).toHaveClass(/active/);
  }
}
