import { test, expect } from '@playwright/test';

test('version drawer saves named snapshots and share drawer persists viewer settings', async ({
  page,
  browser,
}) => {
  const headers = { 'X-Arena-Client': 'web' };
  const owner = `drawer_${Date.now()}`;
  await page.request.post('/api/auth/register', {
    headers,
    data: { username: owner, password: 'drawer-password-123' },
  });
  const other = await browser.newContext();
  const viewer = `viewer_${Date.now()}`;
  await other.request.post('http://127.0.0.1:8080/api/auth/register', {
    headers,
    data: { username: viewer, password: 'drawer-password-123' },
  });
  const row = await (
    await page.request.post('/api/notebooks', {
      headers,
      data: { title: 'Drawer workflow', code: 'print(42)' },
    })
  ).json();
  try {
    await page.goto(`/#code/${row.id}/edit`);
    await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeEnabled({
      timeout: 240000,
    });
    const counter = page.getByRole('button', { name: 'Version history', exact: true });
    await expect(counter).toHaveText('1');
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    const panel = page.getByRole('dialog', { name: 'Save version', exact: true });
    await expect(panel).toBeVisible();
    await expect(counter).toHaveText('1');
    await panel.getByRole('button', { name: 'Cancel', exact: true }).click();
    await expect(counter).toHaveText('1');
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await panel.getByLabel('Version name', { exact: true }).fill('Baseline model');
    await panel.getByLabel('Version tags', { exact: true }).fill('baseline, cpu');
    await expect(panel).toHaveCSS('opacity', '1');
    await page.screenshot({ path: '/tmp/arena-save-version-drawer.png', animations: 'disabled' });
    await panel.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(panel).toHaveCount(0);
    await expect(counter).toHaveText('2');
    let versions = await (await page.request.get(`/api/code/${row.id}/versions`)).json();
    expect(versions[0].label).toEqual({ name: 'Baseline model', tags: ['baseline', 'cpu'] });
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await panel.getByLabel('Version', { exact: true }).selectOption(String(versions[0].id));
    await panel.getByLabel('Version name', { exact: true }).fill('Baseline v1');
    await panel.getByRole('button', { name: 'Save labels', exact: true }).click();
    await expect(panel).toHaveCount(0);
    await expect(counter).toHaveText('2');
    await page.getByRole('button', { name: 'Share', exact: true }).click();
    const sharing = page.getByRole('dialog', { name: 'Share notebook' });
    await sharing.getByLabel('Share with people', { exact: true }).fill(viewer);
    await sharing.getByRole('button', { name: 'Add viewer', exact: true }).click();
    await sharing.getByLabel('Allow comments', { exact: true }).uncheck();
    expect((await other.request.get(`http://127.0.0.1:8080/api/code/${row.id}`)).status()).toBe(
      404,
    );
    await expect(sharing).toHaveCSS('opacity', '1');
    await page.screenshot({ path: '/tmp/arena-share-drawer.png', animations: 'disabled' });
    await sharing.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(sharing).toHaveCount(0);
    expect((await other.request.get(`http://127.0.0.1:8080/api/code/${row.id}`)).status()).toBe(
      200,
    );
    expect(
      (
        await other.request.post(`http://127.0.0.1:8080/api/code/${row.id}/comments`, {
          headers,
          data: { body: 'Blocked' },
        })
      ).status(),
    ).toBe(403);
    await page.getByRole('button', { name: 'Share', exact: true }).click();
    await expect(sharing.getByLabel('Allow comments', { exact: true })).not.toBeChecked();
    await sharing.getByRole('radio').nth(1).check();
    await sharing.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(sharing).toHaveCount(0);
    const saved = await (await page.request.get(`/api/code/${row.id}/share-settings`)).json();
    expect(saved.visibility).toBe('public');
  } finally {
    await page.request.delete('/api/notebook-session', { headers });
    await other.close();
  }
});
