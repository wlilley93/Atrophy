import puppeteer from "puppeteer-core";

async function main() {
  const browser = await puppeteer.connect({
    browserURL: "http://localhost:9222",
  });

  const pages = await browser.pages();
  const page = pages.find(p => p.url().includes("localhost:5173")) || pages[0];
  if (!page) {
    console.log("No page found");
    return;
  }

  // Screenshot before
  await page.screenshot({ path: "/tmp/atrophy-before.png" });
  console.log("Before screenshot saved");

  // Get initial transcript
  const beforeText = await page.evaluate(() => document.body?.innerText?.slice(0, 1000));
  console.log("Before:", beforeText?.replace(/\n/g, " | "));

  // Type a message in the input bar
  const input = await page.$('input[type="text"], textarea, [contenteditable], .input-bar input, .input-field');
  if (!input) {
    // Try finding by placeholder
    const inputAlt = await page.$('[placeholder*="essage"]');
    if (!inputAlt) {
      console.log("Could not find input field");
      // Dump all inputs
      const inputs = await page.evaluate(() => {
        const els = document.querySelectorAll("input, textarea");
        return Array.from(els).map(e => ({
          tag: e.tagName,
          type: (e as HTMLInputElement).type,
          placeholder: (e as HTMLInputElement).placeholder,
          className: e.className,
        }));
      });
      console.log("Found inputs:", JSON.stringify(inputs, null, 2));
      browser.disconnect();
      return;
    }
    await inputAlt.click();
    await inputAlt.type("Hey Xan, just testing - say something short", { delay: 30 });
  } else {
    await input.click();
    await input.type("Hey Xan, just testing - say something short", { delay: 30 });
  }

  await page.screenshot({ path: "/tmp/atrophy-typed.png" });
  console.log("Typed message screenshot saved");

  // Press Enter to send
  await page.keyboard.press("Enter");
  console.log("Message sent, waiting for response...");

  // Wait for response - poll for new content
  const startTime = Date.now();
  let lastText = "";
  let stableCount = 0;
  let responseDetected = false;

  while (Date.now() - startTime < 60000) {
    await new Promise(r => setTimeout(r, 2000));

    const currentText = await page.evaluate(() => document.body?.innerText || "");

    // Check for thinking indicator
    const hasThinking = await page.evaluate(() => {
      const el = document.querySelector(".thinking-indicator, .thinking, [class*='thinking']");
      return !!el && (el as HTMLElement).offsetParent !== null;
    });

    if (hasThinking) {
      console.log(`[${Math.round((Date.now() - startTime) / 1000)}s] Thinking...`);
      responseDetected = true;
    }

    if (currentText !== lastText) {
      const newPart = currentText.slice(lastText.length).trim();
      if (newPart) {
        console.log(`[${Math.round((Date.now() - startTime) / 1000)}s] New text: ${newPart.slice(0, 200)}`);
        responseDetected = true;
      }
      lastText = currentText;
      stableCount = 0;
    } else {
      stableCount++;
      if (responseDetected && stableCount >= 3) {
        console.log("Response appears complete (stable for 6s)");
        break;
      }
    }
  }

  // Final screenshot
  await page.screenshot({ path: "/tmp/atrophy-after.png" });
  console.log("After screenshot saved");

  // Get full transcript
  const afterText = await page.evaluate(() => document.body?.innerText?.slice(0, 2000));
  console.log("\n--- Final transcript ---");
  console.log(afterText);

  // Check for errors in console
  const logs = await page.evaluate(() => {
    return (window as any).__puppeteerLogs || [];
  });
  if (logs.length) {
    console.log("\n--- Console logs ---");
    for (const l of logs) console.log(l);
  }

  browser.disconnect();
}

main().catch(console.error);
