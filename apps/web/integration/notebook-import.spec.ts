import { test, expect } from '@playwright/test';
import { parseNotebook } from '../src/notebookImport';

test('reject malformed notebooks and foreign kernels', () => {
  expect(() => parseNotebook('{')).toThrow('JSON');
  expect(() => parseNotebook(JSON.stringify({ nbformat: 3, cells: [] }))).toThrow('nbformat 4');
  expect(() =>
    parseNotebook(
      JSON.stringify({ nbformat: 4, metadata: { kernelspec: { language: 'julia' } }, cells: [] }),
    ),
  ).toThrow('Python');
  expect(() =>
    parseNotebook(
      JSON.stringify({ nbformat: 4, cells: [{ cell_type: 'code', source: {}, outputs: [] }] }),
    ),
  ).toThrow('Cell 1');
});

test('import is unsaved, preserves Markdown and outputs, and supports history restore', async ({
  page,
}) => {
  const headers = { 'X-Arena-Client': 'web' };
  expect(
    (
      await page.request.post('/api/auth/register', {
        headers,
        data: { username: `import_${Date.now()}`, password: 'notebook-import-password' },
      })
    ).status(),
  ).toBe(201);
  const notebook = await (
    await page.request.post('/api/notebooks', {
      headers,
      data: { title: 'Notebook import check', code: 'print("original")' },
    })
  ).json();
  try {
    await page.goto(`/#code/${notebook.id}/edit`);
    await expect(page.getByRole('button', { name: 'Run all', exact: true })).toBeEnabled({
      timeout: 240000,
    });
    await expect(
      page.locator('.notebook-menubar').getByRole('button', { name: 'Training', exact: true }),
    ).toHaveCount(0);
    await page
      .locator('.notebook-menubar')
      .getByRole('button', { name: 'File', exact: true })
      .click();
    const menuBounds = await page.locator('.notebook-menubar').boundingBox();
    expect((await page.locator('.notebook-topbar').boundingBox())!.height).toBeLessThanOrEqual(78);
    const toolbarBounds = await page.locator('.arena-notebook-toolbar').boundingBox();
    expect(menuBounds!.y + menuBounds!.height).toBeLessThanOrEqual(toolbarBounds!.y);
    const counter = page.getByRole('button', { name: 'Version history', exact: true });
    await expect(counter).toHaveText('1');
    await expect(page.getByRole('button', { name: 'Save', exact: true })).toHaveText(
      'Save Version',
    );
    const chooser = page.waitForEvent('filechooser');
    await page.getByRole('menuitem', { name: 'Import notebook (.ipynb)', exact: true }).click();
    await (
      await chooser
    ).setFiles({ name: 'bad.ipynb', mimeType: 'application/json', buffer: Buffer.from('{') });
    await expect(page.getByText('This file is not valid notebook JSON.')).toBeVisible();
    await expect(page.locator('.arena-cell .cm-content').first()).toContainText('original');
    const document = {
      nbformat: 4,
      nbformat_minor: 5,
      metadata: { arena_inputs: [{ id: 999999 }] },
      cells: [
        {
          cell_type: 'markdown',
          source: '# Imported heading\n\n| Name | Value |\n| --- | --- |\n| Example | 42 |',
          metadata: {},
        },
        {
          cell_type: 'code',
          source: 'raise RuntimeError("must not auto-run")',
          metadata: {},
          execution_count: 1,
          outputs: [{ output_type: 'stream', name: 'stdout', text: 'Saved output preview' }],
        },
      ],
    };
    page.once('dialog', (dialog) => dialog.accept());
    await page.getByLabel('Import notebook file').setInputFiles({
      name: 'sample.ipynb',
      mimeType: 'application/json',
      buffer: Buffer.from(JSON.stringify(document)),
    });
    await expect(
      page.locator('.arena-cell').getByRole('heading', { name: 'Imported heading' }),
    ).toBeVisible();
    await expect(page.getByLabel('Output cell 2')).toContainText('Saved output preview');
    await expect(page.locator('.notebook-save-state')).toHaveText('Unsaved changes');
    const before = await (
      await page.request.get(`/api/notebooks/${notebook.id}/working-copy`)
    ).json();
    expect(JSON.stringify(before)).not.toContain('Imported heading');
    await page
      .locator('.notebook-menubar')
      .getByRole('button', { name: 'File', exact: true })
      .click();
    await page.getByRole('menuitem', { name: 'Save notebook', exact: true }).click();
    await expect(page.locator('.notebook-save-state')).toHaveText('Saved permanently');
    await expect(counter).toHaveText('2');
    await page.screenshot({ path: '/tmp/arena-notebook-header.png' });
    const saved = await (
      await page.request.get(`/api/notebooks/${notebook.id}/working-copy`)
    ).json();
    expect(saved.cells[0].source).toContain('Imported heading');
    expect(saved.metadata.arena_inputs).toBeUndefined();
    await page.getByRole('button', { name: 'Version history', exact: true }).click();
    const history = page.getByRole('dialog', { name: 'Notebook version history' });
    await history.locator('.history-version').first().click();
    await expect(history.getByRole('heading', { name: 'Imported heading' })).toBeVisible();
    expect((await history.locator('.history-version').first().boundingBox())!.height).toBeLessThan(
      100,
    );
    await expect(history.locator('pre').first()).toHaveCSS('color', 'rgb(36, 39, 43)');
    await page.screenshot({ path: '/tmp/arena-notebook-history.png' });
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(history).toBeVisible();
    const bounds = await history.boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);
    await page.setViewportSize({ width: 1440, height: 1000 });
    await history.locator('.history-version').last().click();
    page.once('dialog', (dialog) => dialog.accept());
    await history.getByRole('button', { name: 'Restore into editor' }).click();
    await expect(page.locator('.arena-cell .cm-content').first()).toContainText('original');
    await expect(page.locator('.notebook-save-state')).toHaveText('Unsaved changes');
  } finally {
    await page.request.delete('/api/notebook-session', { headers });
  }
});
