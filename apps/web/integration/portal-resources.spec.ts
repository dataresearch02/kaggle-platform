import { test, expect } from '@playwright/test';

test('resource pages, personal categories and dataset notebook inputs stay connected', async ({
  page,
}) => {
  const headers = { 'X-Arena-Client': 'web' };
  const suffix = Date.now();
  const registered = await page.request.post('/api/auth/register', {
    headers,
    data: { username: `portal_${suffix}`, password: 'portal-test-password' },
  });
  expect(registered.ok()).toBeTruthy();
  const response = await page.request.post('/api/datasets', {
    headers,
    multipart: {
      title: `Portal data ${suffix}`,
      description: '# Experiment input\nA small dataset for reuse.',
      file: {
        name: 'train.csv',
        mimeType: 'text/csv',
        buffer: Buffer.from('feature,target\n1,2\n3,4\n'),
      },
    },
  });
  expect(response.ok()).toBeTruthy();
  const dataset = await response.json();
  try {
    await page.goto('/#datasets');
    await page.getByRole('heading', { name: dataset.title, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`#datasets/${dataset.id}$`));
    await expect(page.locator('.resource-page')).toContainText('Data preview');
    await expect(page.locator('dialog[open]')).toHaveCount(0);
    await page.reload();
    await expect(page.locator('.resource-page-heading h1')).toHaveText(dataset.title);
    await page.getByRole('button', { name: 'Your Work', exact: true }).click();
    await expect(page).toHaveURL(/#work\/datasets$/);
    await page.reload();
    await expect(
      page.locator('.work-tabs').getByRole('button', { name: /^Datasets/ }),
    ).toHaveAttribute('aria-pressed', 'true');
    await page
      .locator('.work-tabs')
      .getByRole('button', { name: /^Models/ })
      .click();
    await expect(page).toHaveURL(/#work\/models$/);
    await page.goBack();
    await expect(
      page.locator('.work-tabs').getByRole('button', { name: /^Datasets/ }),
    ).toHaveAttribute('aria-pressed', 'true');
    await page.getByRole('button', { name: `Open ${dataset.title}`, exact: true }).click();
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.locator('.resource-page-heading h1')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.setViewportSize({ width: 1440, height: 1000 });
    await expect
      .poll(async () => {
        const main = await page.locator('.main-shell').boundingBox();
        const sidebar = await page.locator('.app > .sidebar').boundingBox();
        return Math.round(main!.x - sidebar!.width);
      })
      .toBe(0);
    await page.screenshot({ path: '/tmp/arena-resource-page.png', animations: 'disabled' });
    await page.getByRole('button', { name: 'New notebook', exact: true }).click();
    await expect(
      page.locator('.notebook-input-source-title', { hasText: dataset.title }),
    ).toBeVisible({ timeout: 120000 });
    await expect(page.locator('.notebook-input-files')).toContainText('train.csv');
    await page.getByRole('button', { name: 'Close notebook editor', exact: true }).click();
    await expect(page.getByRole('dialog', { name: 'New notebook', exact: true })).toHaveCount(0);
    await page.goto('/#benchmarks');
    await page.getByRole('button', { name: 'Your Work', exact: true }).click();
    await expect(page).toHaveURL(/#work\/benchmarks$/);
    await page.reload();
    await expect(
      page.locator('.work-tabs').getByRole('button', { name: /^Benchmarks/ }),
    ).toHaveAttribute('aria-pressed', 'true');
  } finally {
    await page.request.delete(`/api/work/datasets/${dataset.id}`, { headers });
    // This test owns the newly registered user's server.
    await page.request.delete('/api/notebook-session', { headers });
  }
});

test('hosted model uploads enable notebook creation on its detail page', async ({ page }) => {
  const headers = { 'X-Arena-Client': 'web' };
  await page.request.post('/api/auth/register', {
    headers,
    data: {
      username: `model_portal_${Date.now()}`,
      password: 'portal-test-password',
    },
  });
  const created = await page.request.post('/api/models', {
    headers,
    data: {
      title: `Model ${Date.now()}`,
      description: 'Hosted weights',
      framework: 'PyTorch',
      license: 'MIT',
    },
  });
  expect(created.ok()).toBeTruthy();
  const model = await created.json();
  try {
    await page.goto('/#models');
    await page.getByRole('heading', { name: model.title, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`#models/${model.id}$`));
    await expect(page.getByRole('button', { name: 'New notebook', exact: true })).toBeDisabled();
    await page.getByLabel('File path', { exact: true }).fill('weights.bin');
    await page.getByLabel('Artifact file', { exact: true }).setInputFiles({
      name: 'weights.bin',
      mimeType: 'application/octet-stream',
      buffer: Buffer.from('test-artifact'),
    });
    await page.getByRole('button', { name: 'Upload file version', exact: true }).click();
    await expect(page.getByRole('link', { name: 'weights.bin', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'New notebook', exact: true })).toBeEnabled();
    await page.reload();
    await expect(page.getByRole('button', { name: 'New notebook', exact: true })).toBeEnabled();
    await page.getByRole('button', { name: 'Your Work', exact: true }).click();
    await expect(page).toHaveURL(/#work\/models$/);
  } finally {
    await page.request.delete(`/api/work/models/${model.id}`, { headers });
  }
});
