import fs from "node:fs";
import { BatchInfo, Configuration, Eyes, Target } from "@applitools/eyes-playwright";
import { test } from "@playwright/test";
import { NAV_LABELS, navButton } from "./helpers";

function numberOrZero(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "" && !Number.isNaN(Number(value))) return Number(value);
  return 0;
}

test("capture primary sections with Applitools", async ({ page }) => {
  test.skip(!process.env.APPLITOOLS_API_KEY, "APPLITOOLS_API_KEY is required");

  const resultsPath = process.env.APPLITOOLS_RESULTS_PATH || "applitools/results.json";
  const eyes = new Eyes();
  const configuration = new Configuration();
  configuration.setApiKey(process.env.APPLITOOLS_API_KEY || "");
  configuration.setBatch(
    new BatchInfo(process.env.APPLITOOLS_BATCH_NAME || `Reframe-${process.env.GITHUB_SHA || "local"}`),
  );
  eyes.setConfiguration(configuration);

  await page.goto("/");
  await eyes.open(page, "Reframe", "primary-sections", { width: 1280, height: 900 });
  await navButton(page, "Shorts").waitFor({ state: "visible" });

  for (const label of NAV_LABELS) {
    await navButton(page, label).click();
    await eyes.check(label, Target.window().fully());
  }

  const closeResult = await eyes.close();
  await eyes.abortIfNotClosed();

  const payload = {
    unresolved: numberOrZero((closeResult as any)?.getUnresolved?.() ?? (closeResult as any)?.unresolved),
    mismatches: numberOrZero((closeResult as any)?.getMismatches?.() ?? (closeResult as any)?.mismatches),
    missing: numberOrZero((closeResult as any)?.getMissing?.() ?? (closeResult as any)?.missing),
  };

  fs.mkdirSync("applitools", { recursive: true });
  fs.writeFileSync(resultsPath, JSON.stringify(payload, null, 2));
});
