import puppeteer from "puppeteer-core";

async function main() {
  const browser = await puppeteer.connect({
    browserURL: "http://localhost:9222",
  });

  const pages = await browser.pages();
  const page = pages.find(p => p.url().includes("localhost:5173")) || pages[0];
  if (!page) { console.log("No page found"); return; }

  // Capture renderer console logs
  page.on("console", msg => {
    const text = msg.text();
    if (text.includes("inference") || text.includes("error") || text.includes("Error") || text.includes("claude") || text.includes("Claude")) {
      console.log(`[RENDERER ${msg.type()}] ${text}`);
    }
  });

  // Check if there's an active inference (stop button visible)
  const hasStop = await page.evaluate(() => {
    const stopBtn = document.querySelector('.stop-btn, [class*="stop"]');
    return stopBtn ? { found: true, visible: (stopBtn as HTMLElement).offsetParent !== null } : { found: false };
  });
  console.log("Stop button:", JSON.stringify(hasStop));

  // First stop any pending inference
  if (hasStop.found) {
    console.log("Stopping current inference...");
    await page.evaluate(() => {
      const stopBtn = document.querySelector('.stop-btn, [class*="stop"]') as HTMLElement;
      if (stopBtn) stopBtn.click();
    });
    await new Promise(r => setTimeout(r, 2000));
  }

  // Check the preload API
  const apiCheck = await page.evaluate(() => {
    const api = (window as any).atrophy;
    if (!api) return "atrophy API not found on window";
    return {
      hasAPI: true,
      methods: Object.keys(api),
      hasSendMessage: typeof api.sendMessage === "function",
      hasOnTextDelta: typeof api.onTextDelta === "function",
    };
  });
  console.log("Preload API:", JSON.stringify(apiCheck, null, 2));

  // Listen for inference events before sending
  await page.evaluate(() => {
    const api = (window as any).atrophy;
    if (!api) return;

    // Hook into IPC events
    (window as any).__inferenceLog = [];
    const origOnTextDelta = api.onTextDelta;
    const origOnError = api.onError;
    const origOnDone = api.onDone;

    if (typeof origOnTextDelta === "function") {
      // These are likely ipcRenderer.on wrappers, so just log
    }
  });

  // Try calling inference directly
  console.log("\nSending message via API...");
  const sendResult = await page.evaluate(async () => {
    const api = (window as any).atrophy;
    if (!api?.sendMessage) return "no sendMessage method";
    try {
      const result = await api.sendMessage("test - say hi in one word");
      return { result };
    } catch (e: any) {
      return { error: e.message || String(e) };
    }
  });
  console.log("Send result:", JSON.stringify(sendResult));

  // Wait and collect events
  console.log("Waiting 15s for response...");
  for (let i = 0; i < 5; i++) {
    await new Promise(r => setTimeout(r, 3000));

    const transcript = await page.evaluate(() => document.body?.innerText?.slice(0, 1500));
    const elapsed = (i + 1) * 3;
    console.log(`[${elapsed}s] Text: ${transcript?.replace(/\n/g, " | ").slice(0, 200)}`);
  }

  await page.screenshot({ path: "/tmp/atrophy-debug.png" });
  console.log("Screenshot saved to /tmp/atrophy-debug.png");

  browser.disconnect();
}

main().catch(console.error);
