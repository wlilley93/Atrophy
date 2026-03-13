import puppeteer from "puppeteer-core";

async function main() {
  const browser = await puppeteer.connect({
    browserURL: "http://localhost:9222",
  });

  const pages = await browser.pages();
  const page = pages.find(p => p.url().includes("localhost:5173")) || pages[0];
  if (!page) { console.log("No page found"); return; }

  await page.screenshot({ path: "/tmp/atrophy-now.png" });

  const text = await page.evaluate(() => document.body?.innerText?.slice(0, 2000));
  console.log("=== TRANSCRIPT ===");
  console.log(text);

  browser.disconnect();
}

main().catch(console.error);
