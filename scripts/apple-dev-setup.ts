#!/usr/bin/env npx tsx
/**
 * Apple Developer certificate setup automation.
 *
 * Opens Chrome, navigates to developer.apple.com, waits for you to sign in,
 * then automates:
 *   1. Creating a Developer ID Application certificate (using pre-generated CSR)
 *   2. Downloading the certificate
 *   3. Installing it in your keychain
 *   4. Creating an App Store Connect API key for notarization
 *
 * Usage: npx tsx scripts/apple-dev-setup.ts
 */

import puppeteer from 'puppeteer-core';
import * as fs from 'fs';
import * as path from 'path';
import { execSync } from 'child_process';

const CHROME_PATH = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const CSR_PATH = path.join(process.env.HOME || '/tmp', '.atrophy/signing/dev_id.csr');
const CERT_DOWNLOAD_DIR = path.join(process.env.HOME || '/tmp', '.atrophy/signing');
const CERTS_URL = 'https://developer.apple.com/account/resources/certificates/list';
const API_KEYS_URL = 'https://appstoreconnect.apple.com/access/integrations/api';

async function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

async function waitForText(page: puppeteer.Page, text: string, timeout = 60_000): Promise<boolean> {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    const content = await page.evaluate(() => document.body?.innerText || '');
    if (content.includes(text)) return true;
    await sleep(1000);
  }
  return false;
}

async function main() {
  console.log('\n  Apple Developer Setup\n');

  // Verify CSR exists
  if (!fs.existsSync(CSR_PATH)) {
    console.error(`  CSR not found at ${CSR_PATH}`);
    console.error('  Run: openssl req -new -newkey rsa:2048 -nodes -keyout ~/.atrophy/signing/dev_id.key -out ~/.atrophy/signing/dev_id.csr');
    process.exit(1);
  }
  console.log('  CSR ready at', CSR_PATH);

  // Launch Chrome (headful - user needs to interact)
  const browser = await puppeteer.launch({
    executablePath: CHROME_PATH,
    headless: false,
    defaultViewport: null,
    args: [
      '--no-first-run',
      '--disable-default-apps',
      '--window-size=1200,900',
    ],
    userDataDir: path.join(process.env.HOME || '/tmp', '.atrophy/chrome-profile'),
  });

  const page = (await browser.pages())[0] || await browser.newPage();

  // ── Step 1: Navigate to Certificates page ──
  console.log('\n  Step 1: Opening developer.apple.com/account...');
  console.log('  -> Sign in with your Apple ID when prompted.');
  console.log('  -> Complete 2FA if asked.\n');

  await page.goto('https://developer.apple.com/account', { waitUntil: 'networkidle2' });

  // Wait for sign-in to complete (look for account page content)
  console.log('  Waiting for sign-in...');
  let signedIn = false;
  const signInTimeout = 300_000; // 5 minutes for sign-in + 2FA
  const t0 = Date.now();

  while (Date.now() - t0 < signInTimeout) {
    const url = page.url();
    const content = await page.evaluate(() => document.body?.innerText || '');

    // Check if we're on the account page (past sign-in)
    if (url.includes('developer.apple.com/account') && !url.includes('signin') &&
        (content.includes('Certificates') || content.includes('Membership') || content.includes('Program'))) {
      signedIn = true;
      break;
    }
    await sleep(2000);
  }

  if (!signedIn) {
    console.error('  Timed out waiting for sign-in. Exiting.');
    await browser.close();
    process.exit(1);
  }

  console.log('  Signed in!\n');

  // Try to get Team ID from the page
  let teamId = '';
  try {
    const membershipLink = await page.$('a[href*="membership"]');
    if (membershipLink) {
      await membershipLink.click();
      await sleep(3000);
      const memberContent = await page.evaluate(() => document.body?.innerText || '');
      const teamMatch = memberContent.match(/Team ID\s*\n?\s*([A-Z0-9]{10})/);
      if (teamMatch) {
        teamId = teamMatch[1];
        console.log(`  Found Team ID: ${teamId}`);
      }
    }
  } catch { /* continue without team ID */ }

  // ── Step 2: Navigate to Certificates ──
  console.log('  Step 2: Navigating to Certificates...');
  await page.goto(CERTS_URL, { waitUntil: 'networkidle2' });
  await sleep(3000);

  // Check if we need to create a Developer ID Application certificate
  const pageContent = await page.evaluate(() => document.body?.innerText || '');
  const hasDeveloperIdCert = pageContent.includes('Developer ID Application');

  if (hasDeveloperIdCert) {
    console.log('  Developer ID Application certificate already exists!');
    console.log('  Checking if it is in your keychain...\n');

    // Check keychain
    const keychainCheck = execSync('security find-identity -v -p codesigning 2>/dev/null').toString();
    if (keychainCheck.includes('Developer ID Application')) {
      console.log('  Certificate is already in keychain. Skipping certificate creation.');
    } else {
      console.log('  Certificate exists in portal but NOT in keychain.');
      console.log('  -> Click on the certificate in the browser to download it.');
      console.log('  -> Then double-click the downloaded .cer file to install it.\n');
      console.log('  Press Enter in this terminal when done...');
      await new Promise<void>((r) => {
        process.stdin.once('data', () => r());
      });
    }
  } else {
    // Create new certificate
    console.log('  Creating new Developer ID Application certificate...');

    // Click the "+" button to create new certificate
    try {
      // Look for create button
      const createBtn = await page.$('a[href*="add"], button[class*="add"], .action-button');
      if (createBtn) {
        await createBtn.click();
        await sleep(3000);
      } else {
        // Try navigating directly
        await page.goto('https://developer.apple.com/account/resources/certificates/add', { waitUntil: 'networkidle2' });
        await sleep(3000);
      }

      // Select "Developer ID Application"
      console.log('  Selecting Developer ID Application...');
      const radioButtons = await page.$$('input[type="radio"]');
      let found = false;
      for (const radio of radioButtons) {
        const label = await page.evaluate((el) => {
          const parent = el.closest('label') || el.parentElement;
          return parent?.textContent || '';
        }, radio);
        if (label.includes('Developer ID Application')) {
          await radio.click();
          found = true;
          break;
        }
      }

      if (!found) {
        // Try clicking by text
        const devIdLink = await page.evaluateHandle(() => {
          const elements = document.querySelectorAll('label, span, div');
          for (const el of elements) {
            if (el.textContent?.includes('Developer ID Application') && el.textContent.length < 200) {
              return el;
            }
          }
          return null;
        });
        if (devIdLink) {
          await (devIdLink as puppeteer.ElementHandle).click();
          found = true;
        }
      }

      if (!found) {
        console.log('  Could not find Developer ID Application option.');
        console.log('  -> Please select it manually in the browser, then press Enter...');
        await new Promise<void>((r) => {
          process.stdin.once('data', () => r());
        });
      }

      // Click Continue
      await sleep(1000);
      const continueBtn = await page.evaluateHandle(() => {
        const buttons = document.querySelectorAll('button, a.button, input[type="submit"]');
        for (const btn of buttons) {
          if (btn.textContent?.trim().toLowerCase() === 'continue') return btn;
        }
        return null;
      });
      if (continueBtn) {
        await (continueBtn as puppeteer.ElementHandle).click();
        await sleep(3000);
      }

      // Upload CSR
      console.log('  Uploading CSR...');
      const fileInput = await page.$('input[type="file"]');
      if (fileInput) {
        await fileInput.uploadFile(CSR_PATH);
        await sleep(2000);

        // Click Continue/Generate
        const genBtn = await page.evaluateHandle(() => {
          const buttons = document.querySelectorAll('button, a.button, input[type="submit"]');
          for (const btn of buttons) {
            const text = btn.textContent?.trim().toLowerCase() || '';
            if (text === 'continue' || text === 'generate') return btn;
          }
          return null;
        });
        if (genBtn) {
          await (genBtn as puppeteer.ElementHandle).click();
          console.log('  Certificate generating...');
          await sleep(5000);
        }
      } else {
        console.log('  Could not find file upload input.');
        console.log('  -> Upload the CSR manually from: ' + CSR_PATH);
        console.log('  -> Press Enter when done...');
        await new Promise<void>((r) => {
          process.stdin.once('data', () => r());
        });
      }

      // Download the certificate
      console.log('  Downloading certificate...');
      const downloadBtn = await page.evaluateHandle(() => {
        const buttons = document.querySelectorAll('button, a.button, a');
        for (const btn of buttons) {
          const text = btn.textContent?.trim().toLowerCase() || '';
          if (text === 'download') return btn;
        }
        return null;
      });

      if (downloadBtn) {
        // Set download path
        const client = await page.createCDPSession();
        await client.send('Page.setDownloadBehavior', {
          behavior: 'allow',
          downloadPath: CERT_DOWNLOAD_DIR,
        });

        await (downloadBtn as puppeteer.ElementHandle).click();
        await sleep(5000);

        // Find the downloaded .cer file
        const cerFiles = fs.readdirSync(CERT_DOWNLOAD_DIR).filter((f) => f.endsWith('.cer'));
        if (cerFiles.length > 0) {
          const cerPath = path.join(CERT_DOWNLOAD_DIR, cerFiles[cerFiles.length - 1]);
          console.log(`  Downloaded: ${cerPath}`);

          // Install in keychain
          console.log('  Installing certificate in keychain...');
          execSync(`security import "${cerPath}" -k ~/Library/Keychains/login.keychain-db -T /usr/bin/codesign -T /usr/bin/security`);
          console.log('  Certificate installed!\n');
        }
      } else {
        console.log('  -> Download the certificate manually and double-click to install.');
        console.log('  -> Press Enter when done...');
        await new Promise<void>((r) => {
          process.stdin.once('data', () => r());
        });
      }
    } catch (e) {
      console.error('  Automation error:', e);
      console.log('  -> Complete certificate creation manually in the browser.');
      console.log('  -> Upload CSR from: ' + CSR_PATH);
      console.log('  -> Press Enter when done...');
      await new Promise<void>((r) => {
        process.stdin.once('data', () => r());
      });
    }
  }

  // ── Step 3: App Store Connect API Key for notarization ──
  console.log('  Step 3: Setting up notarization API key...');
  console.log('  Navigating to App Store Connect...\n');

  await page.goto(API_KEYS_URL, { waitUntil: 'networkidle2' });
  await sleep(5000);

  // Check if we need to agree to terms first
  const connectContent = await page.evaluate(() => document.body?.innerText || '');

  if (connectContent.includes('Generate API Key') || connectContent.includes('Request Access') || connectContent.includes('Keys')) {
    console.log('  App Store Connect API page loaded.');
    console.log('  -> If no keys exist, click "Generate API Key"');
    console.log('  -> Name: "Atrophy Notarization"');
    console.log('  -> Access: "Developer"');
    console.log('  -> Download the .p8 key file and note the Key ID and Issuer ID');
    console.log('  -> Save the .p8 file to: ~/.atrophy/signing/\n');
    console.log('  Press Enter when you have the Key ID, Issuer ID, and .p8 file...');
  } else {
    console.log('  You may need to accept terms or enable API access first.');
    console.log('  -> Complete the setup in the browser.');
    console.log('  -> Create an API key named "Atrophy Notarization" with "Developer" access.');
    console.log('  -> Download the .p8 file to: ~/.atrophy/signing/\n');
    console.log('  Press Enter when done...');
  }

  await new Promise<void>((r) => {
    process.stdin.once('data', () => r());
  });

  // Collect the values
  const readline = await import('readline');
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });

  const ask = (q: string): Promise<string> => new Promise((r) => rl.question(q, r));

  if (!teamId) {
    teamId = await ask('  Team ID: ');
  }
  const keyId = await ask('  API Key ID: ');
  const issuerId = await ask('  Issuer ID: ');

  // Find .p8 file
  let p8Path = '';
  const signingFiles = fs.readdirSync(CERT_DOWNLOAD_DIR).filter((f) => f.endsWith('.p8'));
  if (signingFiles.length > 0) {
    p8Path = path.join(CERT_DOWNLOAD_DIR, signingFiles[signingFiles.length - 1]);
  } else {
    // Check Downloads
    const downloads = path.join(process.env.HOME || '/tmp', 'Downloads');
    const dlFiles = fs.readdirSync(downloads).filter((f) => f.endsWith('.p8'));
    if (dlFiles.length > 0) {
      const src = path.join(downloads, dlFiles[dlFiles.length - 1]);
      p8Path = path.join(CERT_DOWNLOAD_DIR, dlFiles[dlFiles.length - 1]);
      fs.copyFileSync(src, p8Path);
      console.log(`  Copied ${dlFiles[dlFiles.length - 1]} to ${CERT_DOWNLOAD_DIR}`);
    }
  }

  if (!p8Path) {
    p8Path = await ask('  Path to .p8 file: ');
  }

  rl.close();

  // ── Step 4: Verify signing identity ──
  console.log('\n  Verifying signing identity...');
  const identities = execSync('security find-identity -v -p codesigning 2>/dev/null').toString();
  console.log(identities || '  (no identities found)');

  // Extract identity name
  const idMatch = identities.match(/"(Developer ID Application: .+?)"/);
  const signingIdentity = idMatch ? idMatch[1] : 'Developer ID Application';

  // ── Step 5: Write config ──
  console.log('\n  Writing notarization config...');

  // Store API key info for electron-builder
  const notarizeConfig = {
    teamId: teamId.trim(),
    keyId: keyId.trim(),
    issuerId: issuerId.trim(),
    keyPath: p8Path.trim(),
    signingIdentity,
  };

  const configPath = path.join(CERT_DOWNLOAD_DIR, 'notarize-config.json');
  fs.writeFileSync(configPath, JSON.stringify(notarizeConfig, null, 2) + '\n');
  console.log(`  Saved to: ${configPath}`);

  // Write .env for electron-builder
  const envLines = [
    `APPLE_TEAM_ID=${notarizeConfig.teamId}`,
    `APPLE_API_KEY_ID=${notarizeConfig.keyId}`,
    `APPLE_API_ISSUER=${notarizeConfig.issuerId}`,
    `APPLE_API_KEY_PATH=${notarizeConfig.keyPath}`,
    `CSC_NAME=${signingIdentity}`,
  ];

  const envPath = path.join(process.env.HOME || '/tmp', '.atrophy/signing/.env.signing');
  fs.writeFileSync(envPath, envLines.join('\n') + '\n');
  console.log(`  Env file: ${envPath}`);

  console.log('\n  Done! To build a signed + notarized DMG:\n');
  console.log(`    source ~/.atrophy/signing/.env.signing`);
  console.log(`    cd "${path.resolve(__dirname, '..')}"`);
  console.log('    pnpm build && pnpm dist\n');

  await browser.close();
}

main().catch((e) => {
  console.error('Fatal:', e);
  process.exit(1);
});
