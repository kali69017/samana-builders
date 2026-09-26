import { test, expect } from '@playwright/test';

test('probe: AI chat replies to Hi and does not stick on Thinking', async ({ page }) => {
  test.slow();
  await page.goto('/login/');
  await page.fill('#id_username', 'admin');
  await page.fill('#id_password', 'admin123');
  await Promise.all([
    page.waitForURL(/\/(dashboard|portal)\//, { timeout: 20000 }),
    page.click('button[type="submit"]'),
  ]);

  await page.goto('/ai/');
  await page.waitForSelector('#chatInput', { timeout: 15000 });

  const botBefore = await page.locator('.chat-msg.bot').count();
  await page.fill('#chatInput', 'Hi');
  await page.click('#chatSendBtn');
  await page.waitForSelector('#chatStatus:has-text("Thinking")', { timeout: 10000 }).catch(() => {});

  const status = await page.locator('#chatStatus').textContent();
  const started = Date.now();
  console.log(`probe: status right after send = "${status}"`);

  // Wait up to 90s for a new bot reply.
  await page.waitForFunction(
    ({ before }) => document.querySelectorAll('.chat-msg.bot').length > before,
    { before: botBefore },
    { timeout: 90000 },
  ).catch(() => {});

  const elapsed = Math.round((Date.now() - started) / 1000);
  const botAfter = await page.locator('.chat-msg.bot').count();
  const finalStatus = await page.locator('#chatStatus').textContent();
  const lastBot = botAfter > botBefore
    ? (await page.locator('.chat-msg.bot').last().textContent()).trim()
    : '(none)';
  console.log(`probe: elapsed=${elapsed}s botBefore=${botBefore} botAfter=${botAfter} status="${finalStatus}"`);
  console.log(`probe: last bot msg = ${lastBot.slice(0, 200)}`);

  expect(botAfter).toBeGreaterThan(botBefore);
});