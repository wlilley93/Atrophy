import puppeteer from "puppeteer-core";

async function main() {
  const browser = await puppeteer.connect({
    browserURL: "http://localhost:9222",
  });

  const pages = await browser.pages();
  const page = pages.find(p => p.url().includes("localhost:5173")) || pages[0];
  if (!page) { console.log("No page found"); return; }

  console.log("Connected, waiting for Claude response...");

  const startTime = Date.now();
  let lastText = "";
  let stableCount = 0;

  while (Date.now() - startTime < 120000) {
    await new Promise(r => setTimeout(r, 3000));

    const currentText = await page.evaluate(() => document.body?.innerText || "");

    // Check thinking indicator
    const hasThinking = await page.evaluate(() => {
      const el = document.querySelector(".thinking-indicator, .thinking, [class*='thinking'], .brain-pulse");
      if (!el) return false;
      const style = window.getComputedStyle(el);
      return style.display !== "none" && style.visibility !== "hidden";
    });

    // Check stop button (visible during inference)
    const hasStop = await page.evaluate(() => {
      const btns = document.querySelectorAll("button");
      for (const b of btns) {
        if (b.querySelector("svg") && b.offsetParent !== null) {
          const rect = b.getBoundingClientRect();
          if (rect.right > 700 && rect.bottom > 500) return true;
        }
      }
      return false;
    });

    const elapsed = Math.round((Date.now() - startTime) / 1000);

    if (currentText !== lastText) {
      const diff = currentText.length - lastText.length;
      console.log(`[${elapsed}s] Text changed (+${diff} chars) thinking=${hasThinking}`);
      // Show new content
      if (currentText.length > lastText.length) {
        const newBit = currentText.slice(lastText.length).trim();
        if (newBit.length > 0 && newBit.length < 500) {
          console.log(`  New: ${newBit}`);
        }
      }
      lastText = currentText;
      stableCount = 0;
    } else {
      stableCount++;
      console.log(`[${elapsed}s] Stable (${stableCount}) thinking=${hasThinking}`);
      // Done when stable for 9s AND no thinking indicator
      if (!hasThinking && stableCount >= 3) {
        console.log("Response complete.");
        break;
      }
    }
  }

  // Final screenshot
  await page.screenshot({ path: "/tmp/atrophy-final.png" });
  console.log("Final screenshot: /tmp/atrophy-final.png");

  // Full transcript
  const text = await page.evaluate(() => document.body?.innerText?.slice(0, 3000));
  console.log("\n=== TRANSCRIPT ===");
  console.log(text);

  // Check if TTS played - look for audio elements or mute state
  const audioInfo = await page.evaluate(() => {
    const audioEls = document.querySelectorAll("audio");
    const muteBtn = document.querySelector("[class*='mute'], [title*='mute'], [aria-label*='mute']");
    return {
      audioElements: audioEls.length,
      muteButton: muteBtn ? (muteBtn as HTMLElement).innerText || muteBtn.className : "not found",
    };
  });
  console.log("\nAudio info:", JSON.stringify(audioInfo));

  browser.disconnect();
}

main().catch(console.error);
