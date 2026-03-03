import { test } from "@playwright/test";
import percySnapshot from "@percy/playwright";
import { NAV_LABELS, navButton, walkPrimarySections } from "./helpers";

test("capture primary sections with Percy", async ({ page }) => {
  await walkPrimarySections(page);

  await page.goto("/");
  for (const label of NAV_LABELS) {
    await navButton(page, label).click();
    await percySnapshot(page, `reframe-${label.toLowerCase()}`, {
      widths: [1280],
      minHeight: 900,
    });
  }
});
