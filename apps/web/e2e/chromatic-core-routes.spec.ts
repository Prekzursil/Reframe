import { test } from "@chromatic-com/playwright";
import { NAV_LABELS, navButton } from "./helpers";

for (const label of NAV_LABELS) {
  test(`capture ${label} section`, async ({ page }) => {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const button = navButton(page, label);
    await button.waitFor({ state: "visible", timeout: 30_000 });
    await button.click();
    await page.waitForLoadState("networkidle");
  });
}
