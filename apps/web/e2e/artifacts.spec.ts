import { test, expect } from '@playwright/test';

test('owner uploads model file versions and visitors download immutable files', async ({
  page,
}) => {
  const headers = { 'X-Arena-Client': 'web' };
  await page.request.post('/api/auth/register', {
    headers,
    data: { username: `artifacts_${Date.now()}`, password: 'browser-password-123' },
  });
  const title = `Hosted artifact ${Date.now()}`;
  const response = await page.request.post('/api/models', {
    headers,
    data: {
      title,
      description: 'Model weights with immutable history',
      framework: 'PyTorch',
      license: 'MIT',
    },
  });
  expect(response.status()).toBe(201);
  const model = await response.json();
  await page.goto('/#models');
  await page.getByText(title, { exact: true }).click();
  for (const content of ['first weights', 'second weights']) {
    await page.getByLabel('File path', { exact: true }).fill('weights/model.bin');
    await page.getByLabel('Artifact file', { exact: true }).setInputFiles({
      name: 'model.bin',
      mimeType: 'application/octet-stream',
      buffer: Buffer.from(content),
    });
    await page.getByRole('button', { name: 'Upload file version', exact: true }).click();
    await expect(page.getByLabel('File path', { exact: true })).toHaveValue('');
  }
  await expect(page.locator('.artifact-list li')).toHaveCount(2);
  const versions = await (await page.request.get(`/api/assets/models/${model.id}`)).json();
  await page.request.post('/api/auth/logout', { headers });
  for (const [index, content] of ['second weights', 'first weights'].entries()) {
    const downloaded = await page.request.get(
      `/api/assets/models/${model.id}/${versions[index].id}/download`,
    );
    expect(await downloaded.text()).toBe(content);
  }
});
