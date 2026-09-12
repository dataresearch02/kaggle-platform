import { test, expect } from '@playwright/test';

test('create reusable task and CPU model, run a real benchmark, inspect and export results', async ({
  page,
}) => {
  const headers = { 'X-Arena-Client': 'web' };
  const suffix = Date.now();
  await page.request.post('/api/auth/register', {
    headers,
    data: { username: `bench_${suffix}`, password: 'benchmark-test-password' },
  });
  await page.goto('/#benchmarks');
  await page.locator('.benchmark-create-menu summary').click();
  await page.getByRole('button', { name: 'Create task', exact: true }).click();
  let drawer = page.getByRole('dialog', { name: 'Create task', exact: true });
  await drawer.getByLabel('Name', { exact: true }).fill(`Identity task ${suffix}`);
  await drawer.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: `Identity task ${suffix}`, exact: true }),
  ).toBeVisible();
  const model = await page.request.post('/api/benchmark-hub/assets/model', {
    headers,
    data: {
      title: `CPU identity ${suffix}`,
      source:
        'import torch\n\ndef predict(prompt):\n    value = torch.tensor([1.0], device="cpu")\n    assert value.sum().item() == 1.0\n    return prompt\n',
      visibility: 'private',
    },
  });
  expect(model.ok()).toBeTruthy();
  await page.goto('/#benchmarks');
  await page.locator('.benchmark-create-menu summary').click();
  await page.getByRole('button', { name: 'Create benchmark', exact: true }).click();
  drawer = page.getByRole('dialog', { name: 'Create benchmark', exact: true });
  await drawer.getByLabel('Name', { exact: true }).fill(`CPU benchmark ${suffix}`);
  await drawer.getByRole('checkbox', { name: new RegExp(`Identity task ${suffix}`) }).check();
  await drawer.getByRole('checkbox', { name: new RegExp(`CPU identity ${suffix}`) }).check();
  await drawer.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: `CPU benchmark ${suffix}`, exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Run evaluation', exact: true }).click();
  await expect(page.locator('.benchmark-run')).toContainText('succeeded', { timeout: 120000 });
  await expect(page.locator('.benchmark-table tbody')).toContainText('100.00%');
  await page.locator('.benchmark-run .text-button').click();
  const details = page.getByRole('region', { name: 'Evaluation details' });
  await expect(details).toBeVisible();
  await details.locator('summary').click();
  await expect(details).toContainText('Hello');
  const csv = await page.getByRole('link', { name: 'CSV', exact: true }).getAttribute('href');
  const download = await page.request.get(csv!);
  expect(download.ok()).toBeTruthy();
  expect(await download.text()).toContain(`CPU identity ${suffix}`);
  await page.reload();
  await expect(page.locator('.benchmark-table tbody')).toContainText('100.00%');
  await page.screenshot({ path: '/tmp/arena-benchmark-results.png' });
  await page.goto('/#benchmarks');
  await page.getByRole('button', { name: 'Private', exact: true }).click();
  const card = page
    .locator('.benchmark-discovery-card')
    .filter({ hasText: `CPU benchmark ${suffix}` });
  await expect(card).toContainText('100.0%');
  await expect(card.locator('progress')).toHaveAttribute('value', '1');
  await page.screenshot({ path: '/tmp/arena-benchmark-landing.png' });
  await page.getByRole('button', { name: 'Public', exact: true }).click();
  await expect(card).toHaveCount(0);
  await page.getByRole('button', { name: 'Private', exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(card).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
  ).toBeTruthy();
  await page.getByRole('button', { name: 'Your Work', exact: true }).click();
  await expect(page).toHaveURL(/#work\/benchmarks$/);
  await expect(
    page.locator('.work-tabs').getByRole('button', { name: /^Benchmarks/ }),
  ).toHaveAttribute('aria-pressed', 'true');
  await page.reload();
  await expect(
    page.locator('.work-tabs').getByRole('button', { name: /^Benchmarks/ }),
  ).toHaveAttribute('aria-pressed', 'true');
  const workRow = page.locator('.work-row').filter({ hasText: `CPU benchmark ${suffix}` });
  await expect(workRow).toBeVisible();
  await workRow.getByRole('button', { name: `Open CPU benchmark ${suffix}`, exact: true }).click();
  await expect(
    page.getByRole('heading', { name: `CPU benchmark ${suffix}`, exact: true }),
  ).toBeVisible();
});
