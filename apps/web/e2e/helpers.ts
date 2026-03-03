import { expect, type Locator, type Page } from "@playwright/test";

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

export function navButton(page: Page, label: (typeof NAV_LABELS)[number]): Locator {
  return page
    .locator("aside.sidebar nav")
    .getByRole("button", { name: label, exact: true })
    .or(page.getByRole("button", { name: label, exact: true }))
    .or(page.getByRole("link", { name: label, exact: true }));
}

export async function walkPrimarySections(page: Page): Promise<void> {
  await page.goto("/");
  await page.waitForLoadState("domcontentloaded");
  await expect(page.locator("#root")).toBeVisible();
  await expect(navButton(page, "Shorts")).toBeVisible({ timeout: 30000 });

  for (const label of NAV_LABELS) {
    const button = navButton(page, label);
    await button.click();
    await expect(button).toBeVisible();
  }
}
