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

export function navButton(page: Page, label: (typeof NAV_LABELS)[number]) {
  return page.locator("aside.sidebar nav").getByRole("button", { name: label, exact: true });
}

export async function walkPrimarySections(page: Page): Promise<void> {
  await page.goto("/");
  await expect(navButton(page, "Shorts")).toBeVisible();

  for (const label of NAV_LABELS) {
    const button = navButton(page, label);
    await button.click();
    await expect(button).toHaveClass(/active/);
  }
}
