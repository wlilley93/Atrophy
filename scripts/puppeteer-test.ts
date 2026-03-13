import puppeteer from "puppeteer-core";

async function main() {
  const browser = await puppeteer.connect({
    browserURL: "http://localhost:9222",
  });

  const pages = await browser.pages();
  console.log("Pages found:", pages.length);
  for (const p of pages) {
    console.log(" -", await p.title(), "|", p.url());
  }

  const page = pages.find(p => p.url().includes("localhost:5173")) || pages[0];
  if (!page) {
    console.log("No page found");
    return;
  }

  await page.screenshot({ path: "/tmp/atrophy-puppeteer.png" });
  console.log("Screenshot saved to /tmp/atrophy-puppeteer.png");

  const bodyText = await page.evaluate(() => document.body?.innerText?.slice(0, 500));
  console.log("Body text:", bodyText);

  browser.disconnect();
}

main().catch(console.error);
