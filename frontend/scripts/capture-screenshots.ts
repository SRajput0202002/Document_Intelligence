import { chromium } from "playwright";
import * as path from "path";
import * as fs from "fs";

const PAGES = [
  { path: "/extract", name: "extract" },
  { path: "/jobs", name: "jobs" },
  { path: "/schemas", name: "schemas" },
  { path: "/providers", name: "providers" },
  { path: "/settings", name: "settings" },
];

const screenshotDir = path.join(__dirname, "../design-screenshots");

async function captureScreenshots() {
  // Ensure directory exists
  if (!fs.existsSync(screenshotDir)) {
    fs.mkdirSync(screenshotDir, { recursive: true });
  }

  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });
  const page = await context.newPage();

  console.log("Capturing screenshots...\n");

  for (const pageInfo of PAGES) {
    const url = `http://localhost:3000${pageInfo.path}`;
    console.log(`Capturing: ${pageInfo.name} (${url})`);

    try {
      await page.goto(url, { waitUntil: "networkidle", timeout: 30000 });
      await page.waitForTimeout(500); // Wait for animations

      const screenshotPath = path.join(screenshotDir, `${pageInfo.name}.png`);
      await page.screenshot({ path: screenshotPath, fullPage: true });
      console.log(`  Saved: ${screenshotPath}`);
    } catch (error) {
      console.error(`  Error: ${error}`);
    }
  }

  // Capture dark mode
  console.log("\nCapturing dark mode...");
  await page.goto("http://localhost:3000", { waitUntil: "networkidle" });

  // Toggle theme
  const themeButton = page.locator("button").filter({ has: page.locator("svg") }).last();
  if (await themeButton.isVisible()) {
    await themeButton.click();
    await page.waitForTimeout(300);

    // Click dark mode option
    const darkOption = page.locator("text=Dark").first();
    if (await darkOption.isVisible()) {
      await darkOption.click();
      await page.waitForTimeout(500);
      await page.screenshot({
        path: path.join(screenshotDir, "home-dark.png"),
        fullPage: true
      });
      console.log("  Saved: home-dark.png");
    }
  }

  // Capture collapsed sidebar
  console.log("\nCapturing collapsed sidebar...");
  await page.goto("http://localhost:3000", { waitUntil: "networkidle" });
  const collapseBtn = page.locator('[class*="PanelLeftClose"]').first();
  if (await collapseBtn.isVisible()) {
    await collapseBtn.click();
    await page.waitForTimeout(300);
    await page.screenshot({
      path: path.join(screenshotDir, "home-collapsed.png"),
      fullPage: true
    });
    console.log("  Saved: home-collapsed.png");
  }

  await browser.close();
  console.log("\nDone! Screenshots saved to:", screenshotDir);
}

captureScreenshots().catch(console.error);
