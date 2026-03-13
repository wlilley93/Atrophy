import puppeteer from "puppeteer-core";

async function main() {
  const browser = await puppeteer.connect({
    browserURL: "http://localhost:9222",
  });

  const pages = await browser.pages();
  const page = pages.find(p => p.url().includes("localhost:5173")) || pages[0];
  if (!page) { console.log("No page found"); return; }

  // Type in input and press Enter (like a real user)
  const input = await page.$('[placeholder*="essage"]');
  if (!input) {
    console.log("No input found");
    browser.disconnect();
    return;
  }

  await input.click();
  await input.type("hi", { delay: 50 });
  await page.keyboard.press("Enter");
  console.log("Sent 'hi' via UI");

  // Wait and monitor
  const startTime = Date.now();
  for (let i = 0; i < 20; i++) {
    await new Promise(r => setTimeout(r, 3000));
    const elapsed = Math.round((Date.now() - startTime) / 1000);
    const text = await page.evaluate(() => document.body?.innerText || "");
    const lines = text.split("\n").filter(l => l.trim());
    console.log(`[${elapsed}s] Lines: ${lines.length} | Last: ${lines.slice(-3).join(" | ")}`);

    // Check if response appeared (more than just "Xan." + "hi")
    if (lines.length > 4) {
      console.log("Got response!");
      break;
    }
  }

  await page.screenshot({ path: "/tmp/atrophy-send.png" });
  console.log("Screenshot: /tmp/atrophy-send.png");

  const fullText = await page.evaluate(() => document.body?.innerText?.slice(0, 2000));
  console.log("\n=== FULL TEXT ===");
  console.log(fullText);

  browser.disconnect();
}

main().catch(console.error);
