import { test, expect } from '@playwright/test';
test.use({ actionTimeout: 30_000 });
const headers = { 'X-Arena-Client': 'web' };
test.afterEach(async ({ page }) => {
  await page.request.delete('/api/notebook-session', { headers }).catch(() => {});
});
async function register(page: import('@playwright/test').Page) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Join the community' }).click();
  await page.getByLabel('Username', { exact: true }).fill(`native_${Date.now()}`);
  await page.getByLabel(/^Password/).fill('native-notebook-password');
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
}

test('Arena editor runs Python and renders safe outputs without a Jupyter UI', async ({ page }) => {
  await register(page);
  const created = await page.request.post('/api/notebooks', {
    headers,
    data: {
      title: `Native editor ${Date.now()}`,
      code: 'import pandas as pd\nfrom IPython.display import display, HTML\nprint("ARENA_NATIVE_OK")\ndisplay(pd.DataFrame({"feature": ["temperature", "demand"], "value": [21, 280]}))\ndisplay(HTML("<img src=x onerror=window.arenaUnsafe=true><script>window.arenaUnsafe=true</script><b>Safe rich output</b>"))\nimport matplotlib.pyplot as plt\nplt.plot([1,2], [3,4])\nplt.show()',
    },
  });
  const notebook = await created.json();
  await page.getByRole('navigation').getByRole('button', { name: 'Codes', exact: true }).click();
  await page.getByRole('link', { name: new RegExp(notebook.title) }).click();
  await expect(page.getByRole('button', { name: 'Run all', exact: true })).toBeEnabled({
    timeout: 240000,
  });
  await expect(page.locator('iframe')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Files', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Run all', exact: true }).click();
  await expect(page.getByLabel('Output cell 1')).toContainText('ARENA_NATIVE_OK', {
    timeout: 60000,
  });
  await expect(page.getByLabel('Output cell 1').locator('table')).toContainText('temperature');
  await expect(page.getByAltText('Python plot output')).toBeVisible();
  expect(
    await page.evaluate(() => (window as Window & { arenaUnsafe?: boolean }).arenaUnsafe),
  ).toBeUndefined();
  await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Markdown', exact: true }).click();
  await page
    .locator('.arena-cell')
    .nth(1)
    .locator('.cm-content')
    .fill('# Experiment notes\n\n**Result:** complete.');
  await page.getByRole('button', { name: 'Preview', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Experiment notes' })).toBeVisible();
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.locator('.arena-notebook-subbar')).toContainText('Saved');
  const saved = await (await page.request.get(`/api/notebooks/${notebook.id}/working-copy`)).json();
  expect(saved.cells[1].cell_type).toBe('markdown');
  expect(JSON.stringify(saved.cells[0].outputs)).toContain('ARENA_NATIVE_OK');
  await page.screenshot({ path: 'hub-test-results/native-notebook.png' });
  await page.getByRole('button', { name: 'Close notebook editor', exact: true }).click();
  await page.request.delete('/api/notebook-session', { headers });
  await page.goto(`/#code/${notebook.id}/edit`);
  await expect(page.getByLabel('Output cell 1')).toContainText('ARENA_NATIVE_OK', {
    timeout: 240000,
  });
  await page.getByRole('button', { name: 'Code', exact: true }).click();
  await page
    .locator('.arena-cell .cm-content')
    .last()
    .fill('import time\nprint("LONG_CELL_STARTED", flush=True)\ntime.sleep(30)');
  await page.getByRole('button', { name: 'Run cell', exact: true }).click();
  await expect(page.getByLabel('Output cell 2')).toContainText('LONG_CELL_STARTED');
  await page.getByRole('button', { name: 'Interrupt', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Run all', exact: true })).toBeEnabled();
  await expect(page.getByLabel('Output cell 2')).toContainText('KeyboardInterrupt');
  await page.getByRole('button', { name: 'Restart kernel', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Run all', exact: true })).toBeEnabled();
  await page.locator('.arena-cell .cm-content').last().fill('print(pd)');
  await page.getByRole('button', { name: 'Run cell', exact: true }).click();
  await expect(page.getByLabel('Output cell 2')).toContainText('NameError');
  expect((await page.request.get('/jupyter/hub/')).status()).toBe(404);
  const user = await (await page.request.get('/api/auth/me')).json();
  expect((await page.request.get(`/jupyter/user/arena-${user.id}/lab`)).status()).toBe(404);
  expect((await page.request.get(`/jupyter/user/arena-${user.id}/api/contents`)).status()).toBe(
    404,
  );
});

test('native drafts discard unsaved files and explicitly save full notebooks', async ({ page }) => {
  await register(page);
  const before = await (await page.request.get('/api/notebooks')).json();
  async function draft() {
    await page.getByRole('button', { name: 'Create', exact: true }).click();
    const result = page.waitForResponse(
      (r) => r.url().endsWith('/api/notebook-drafts') && r.request().method() === 'POST',
    );
    await page.getByRole('menuitem', { name: 'Notebook', exact: true }).click();
    const { id } = await (await result).json();
    await expect(page.getByRole('button', { name: 'Run all', exact: true })).toBeEnabled({
      timeout: 240000,
    });
    return id;
  }
  const discarded = await draft();
  await page.locator('.arena-cell .cm-content').first().fill('print("discard me")');
  await page.getByRole('button', { name: 'Close notebook editor' }).click();
  await expect(page.locator('.new-notebook-dialog')).toHaveCount(0);
  expect((await page.request.get(`/api/editor/drafts/${discarded}/document`)).status()).toBe(404);
  expect((await (await page.request.get('/api/notebooks')).json()).length).toBe(before.length);
  const kept = await draft();
  const title = `Saved native draft ${Date.now()}`;
  await page.getByLabel('Notebook title').fill(title);
  await page.locator('.arena-cell .cm-content').first().fill('print("DRAFT_NATIVE_SAVED")');
  await page.getByRole('button', { name: 'Run all', exact: true }).click();
  await expect(page.getByLabel('Output cell 1')).toContainText('DRAFT_NATIVE_SAVED', {
    timeout: 60000,
  });
  await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.locator('.new-notebook-header')).toContainText('Saved permanently');
  const items = await (await page.request.get('/api/notebooks')).json();
  const notebook = items.find((item: { title: string }) => item.title === title);
  expect(items.length).toBe(before.length + 1);
  await page.getByLabel('Notebook title').fill(title + ' renamed');
  await page.keyboard.press('Control+s');
  await expect
    .poll(
      async () =>
        (await (await page.request.get('/api/notebooks')).json()).find(
          (item: { id: number }) => item.id === notebook.id,
        )?.title,
    )
    .toBe(title + ' renamed');
  await page.getByRole('button', { name: 'Close notebook editor' }).click();
  await expect(page.locator('.new-notebook-dialog')).toHaveCount(0);
  expect((await page.request.get(`/api/editor/drafts/${kept}/document`)).status()).toBe(404);
  const output = await (
    await page.request.get(`/api/notebooks/${notebook.id}/working-copy`)
  ).json();
  expect(JSON.stringify(output.cells[0].outputs)).toContain('DRAFT_NATIVE_SAVED');
});

test('reference notebook layout has working menus, shared console and dataset inputs', async ({
  page,
}) => {
  await register(page);
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.getByRole('button', { name: 'Create', exact: true }).click();
  await page.getByRole('menuitem', { name: 'Notebook', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Run all', exact: true })).toBeEnabled({
    timeout: 240000,
  });
  await page.getByLabel('Notebook title').fill('Exploring the data');
  await expect(page.getByLabel('Notebook panel', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Python console', { exact: true })).toBeVisible();
  const editor = await page.locator('.new-notebook-dialog').boundingBox();
  expect(editor?.width).toBe(1920);
  expect(editor?.height).toBe(1080);
  await page
    .locator('.arena-cell .cm-content')
    .first()
    .fill(
      'import numpy as np  # linear algebra\nimport pandas as pd  # data processing\n\nanswer = 42\n\n# Add a dataset using the Input panel on the right.\n# Saved notebooks include code, Markdown, and outputs.',
    );
  await page.getByRole('button', { name: 'Run all', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Run all', exact: true })).toBeEnabled();
  await page.getByLabel('Console command', { exact: true }).fill('print(answer + 1)');
  await page.getByLabel('Console command', { exact: true }).press('Enter');
  await expect(page.locator('.notebook-console-output')).toContainText('43');
  await expect(page.getByRole('button', { name: 'Run all', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Markdown', exact: true }).click();
  await page
    .locator('.arena-cell .cm-content')
    .last()
    .fill('# Exploring the data\n\nStart with a question, add a dataset, and run an experiment.');
  await page.getByRole('button', { name: 'Preview', exact: true }).click();
  await expect(page.locator('.notebook-outline')).toContainText('Exploring the data');
  await page.screenshot({ path: 'hub-test-results/notebook-reference-layout.png' });
  await page.getByRole('button', { name: 'Copy cell', exact: true }).click();
  await page.getByRole('button', { name: 'Paste cell', exact: true }).click();
  await expect(page.locator('.arena-cell')).toHaveCount(3);
  await page.getByRole('button', { name: 'Cut cell', exact: true }).click();
  await expect(page.locator('.arena-cell')).toHaveCount(2);
  await page.getByRole('button', { name: 'View', exact: true }).click();
  await page.getByRole('menuitem', { name: 'Hide console', exact: true }).click();
  await expect(page.getByLabel('Python console', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Toggle Python console', exact: true }).click();
  await expect(page.getByLabel('Python console', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Add Input', exact: true }).click();
  const option = page.locator('.notebook-dataset-option').first();
  await expect(option).toBeVisible();
  await option.click();
  await expect(page.locator('.notebook-inputs li')).toHaveCount(1);
  await page.getByRole('button', { name: 'Run cell', exact: true }).click();
  await expect(page.locator('.arena-cell-outputs table')).toBeVisible({ timeout: 60000 });
  await page.getByRole('button', { name: 'Upload', exact: true }).click();
  await page.getByLabel('Dataset title').fill(`Notebook upload ${Date.now()}`);
  await page
    .getByLabel('Description', { exact: true })
    .fill('Published from the notebook input panel.');
  await page.getByLabel('CSV file', { exact: true }).setInputFiles({
    name: 'experiment.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('feature,value\na,42\nb,43\n'),
  });
  await page.getByRole('button', { name: 'Publish and attach', exact: true }).click();
  await expect(page.locator('.notebook-inputs li')).toHaveCount(2);
  await page.getByRole('button', { name: 'Run cell', exact: true }).click();
  await expect(page.locator('.arena-cell-outputs').last()).toContainText('43');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Close notebook panel', exact: true }).click();
  await expect(page.getByLabel('Notebook panel', { exact: true })).toHaveCount(0);
  expect(
    await page.locator('.new-notebook-dialog').evaluate((el) => el.scrollWidth <= el.clientWidth),
  ).toBe(true);
  await page.screenshot({ path: 'hub-test-results/notebook-reference-mobile.png' });
  await page.getByRole('button', { name: 'Close notebook editor', exact: true }).click();
});
