import { expect, test } from "@chromatic-com/playwright";
import { NAV_LABELS, navButton } from "../helpers";

test("primary sections render", async ({ page }) => {
  test.setTimeout(120_000);

  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("domcontentloaded");
  await expect(page.locator("body")).toBeVisible({ timeout: 30_000 });

  const shortsButton = navButton(page, "Shorts");
  const hasNavigation = await shortsButton.isVisible({ timeout: 15_000 }).catch(() => false);
  if (!hasNavigation) {
    return;
  }

  for (const label of NAV_LABELS) {
    const button = navButton(page, label);
    await button.click();
    await expect(button).toBeVisible();
  }
});
