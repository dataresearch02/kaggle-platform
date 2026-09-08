import { test, expect } from '@playwright/test';

const headers = { 'X-Arena-Client': 'web' };

test.afterEach(async ({ page }) => {
  await page.request.delete('/api/notebook-session', { headers }).catch(() => {});
});

test('embedded JupyterLab executes Python, saves outputs, and restores a stopped workspace', async ({
  page,
  browser,
}) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Join the community' }).click();
  await page.getByLabel('Username', { exact: true }).fill(`runtime_${Date.now()}`);
  await page.getByLabel(/^Password/).fill('real-notebook-test-password');
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  const identity = await (await page.request.get('/api/auth/me')).json();
  const created = await page.request.post('/api/notebooks', {
    headers,
    data: {
      title: `Runtime test ${Date.now()}`,
      description: 'Integration test of a real Python kernel.',
      code: 'import pandas as pd\nprint("ARENA_KERNEL_OK")\ndisplay(pd.DataFrame({"feature": ["temperature", "demand"], "value": [21, 280]}))',
    },
  });
  expect(created.status()).toBe(201);
  const notebook = await created.json();
  await page
    .getByRole('navigation')
    .getByRole('button', { name: 'Notebooks', exact: true })
    .click();
  await page.getByRole('button', { name: new RegExp(notebook.title) }).click();
  await page.getByRole('button', { name: 'Open in JupyterLab', exact: true }).click();
  await expect(page.locator('iframe')).toBeVisible({ timeout: 240_000 });
  const frame = page.frameLocator('iframe');
  await expect(frame.locator('.jp-NotebookPanel')).toBeVisible({ timeout: 60_000 });
  // First-run JupyterLab announcements can cover the editor.
  const dismiss = frame.getByRole('button', { name: /Dismiss|No, thanks|Maybe later/i });
  if (await dismiss.count()) await dismiss.first().click();
  await frame.locator('.jp-CodeCell .cm-content').first().click();
  await expect(page.getByRole('button', { name: 'Run cell', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Run cell', exact: true }).click();
  await expect(frame.locator('.jp-OutputArea-output').first()).toContainText('ARENA_KERNEL_OK');
  await expect(frame.locator('.jp-OutputArea-output table')).toContainText('temperature');
  await page.getByRole('button', { name: 'Markdown', exact: true }).click();
  await frame
    .locator('.jp-mod-active .cm-content')
    .fill('# Experiment notes\n\n**Result:** the model is ready.');
  await page.getByRole('button', { name: 'Run cell', exact: true }).click();
  await expect(frame.getByRole('heading', { name: 'Experiment notes' })).toBeVisible();
  await page.getByRole('button', { name: 'Outline', exact: true }).click();
  await expect(frame.locator('.jp-TableOfContents')).toBeVisible();
  await page.getByRole('button', { name: 'Files', exact: true }).click();
  await expect(frame.locator('.jp-FileBrowser')).toBeVisible();
  await page.getByRole('button', { name: 'Files', exact: true }).click();
  await page.getByRole('button', { name: 'Full IDE', exact: true }).click();
  await expect(frame.locator('#jp-top-panel')).toBeVisible();
  await page.getByRole('button', { name: 'Focus view', exact: true }).click();
  await page.getByRole('button', { name: 'Use dark theme' }).click();
  await expect(frame.locator('body')).toHaveAttribute('data-jp-theme-name', 'JupyterLab Dark');
  await page.getByRole('button', { name: 'Use light theme' }).click();
  await page.getByRole('button', { name: 'Run all', exact: true }).click();
  await expect(page.locator('.studio-session')).toContainText('idle');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect
    .poll(async () => {
      const response = await page.request.get(`/api/notebooks/${notebook.id}/working-copy`);
      return response.status() === 200
        ? JSON.stringify((await response.json()).cells[0].outputs)
        : '';
    })
    .toContain('ARENA_KERNEL_OK');
  await page.screenshot({ path: 'hub-test-results/jupyterhub-running.png', fullPage: false });
  await page.getByRole('button', { name: 'Stop server', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Open in JupyterLab', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Open in JupyterLab', exact: true }).click();
  await expect(page.locator('iframe')).toBeVisible({ timeout: 240_000 });
  await expect(frame.locator('.jp-OutputArea-output').first()).toContainText('ARENA_KERNEL_OK', {
    timeout: 60_000,
  });

  const other = await browser.newContext({ baseURL: 'http://127.0.0.1:8080' });
  expect((await other.request.get(`/jupyter/user/arena-${identity.id}/lab`)).status()).toBe(401);
  expect(
    (
      await other.request.post('/api/auth/register', {
        headers,
        data: { username: `other_${Date.now()}`, password: 'another-notebook-password' },
      })
    ).status(),
  ).toBe(201);
  expect((await other.request.get(`/jupyter/user/arena-${identity.id}/lab`)).status()).toBe(403);
  await other.close();
  await page.getByRole('button', { name: 'Stop server', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Open in JupyterLab', exact: true })).toBeVisible();
});
