import { test } from "@playwright/test";
import { walkPrimarySections } from "./helpers";

test("browserstack cross-browser primary sections", async ({ page }) => {
  await walkPrimarySections(page);
});
