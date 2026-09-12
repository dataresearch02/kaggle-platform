import { test, expect } from '@playwright/test';

test('competition New notebook automatically links inputs and keeps context after saving', async ({
  page,
}) => {
  const headers = { 'X-Arena-Client': 'web' };
  await page.request.post('/api/auth/register', {
    headers,
    data: {
      username: `competition_inputs_${Date.now()}`,
      password: 'competition-input-test-password',
    },
  });
  await page.request.post('/api/competitions/1/join', { headers });
  try {
    await page.goto('/#competitions/1/code');
    await page.getByRole('button', { name: 'New notebook', exact: true }).click();
    const editor = page.getByRole('dialog', { name: 'New notebook', exact: true });
    await expect(editor.getByRole('button', { name: 'Run all', exact: true })).toBeEnabled({
      timeout: 240000,
    });
    await expect(editor.locator('.notebook-inputs')).toContainText('Predict bike demand');
    await editor.getByRole('button', { name: 'Cell type: Code', exact: true }).click();
    const typeMenu = editor.getByRole('menu', { name: 'Cell type', exact: true });
    await expect(typeMenu.getByRole('menuitemradio', { name: /Code Run Python/ })).toHaveAttribute(
      'aria-checked',
      'true',
    );
    await typeMenu.screenshot({ path: '/tmp/arena-cell-type-menu.png' });
    await typeMenu.getByRole('menuitemradio', { name: /Markdown Headings/ }).click();
    await editor.getByRole('button', { name: 'Cell type: Markdown', exact: true }).click();
    await page.keyboard.press('Home');
    await page.keyboard.press('Enter');
    await expect(
      editor.getByRole('button', { name: 'Cell type: Code', exact: true }),
    ).toBeFocused();
    await expect(typeMenu).toHaveCount(0);

    const source = editor.getByRole('button', { name: 'Predict bike demand', exact: true });
    await expect(source).toHaveAttribute('aria-expanded', 'true');
    await source.click();
    await expect(editor.locator('.notebook-input-files')).toBeHidden();
    await source.click();
    await expect(editor.locator('.notebook-input-files')).toBeVisible();
    await expect(editor.locator('.notebook-input-file-button').first()).toHaveCSS(
      'justify-content',
      'flex-start',
    );
    await expect(editor.getByRole('button', { name: 'Add Input', exact: true })).toHaveCSS(
      'border-top-width',
      '1px',
    );
    const fileIcons = editor.locator('.notebook-input-file-button > svg');
    const firstIcon = await fileIcons.nth(0).boundingBox();
    const secondIcon = await fileIcons.nth(1).boundingBox();
    expect(Math.abs(firstIcon!.x - secondIcon!.x)).toBeLessThan(1);
    expect(secondIcon!.y - firstIcon!.y).toBeLessThan(40);

    await expect(editor.getByRole('region', { name: 'Python console' })).toHaveCount(0);
    await editor.locator('.notebook-input-file-button').first().click();
    const preview = editor.getByRole('region', { name: 'Input data preview' });
    await expect(preview.getByRole('table')).toBeVisible();
    await expect(preview.getByRole('columnheader').first()).toBeVisible();
    await editor.getByRole('button', { name: 'Toggle Python console' }).click();
    const consolePanel = editor.getByRole('region', { name: 'Python console' });
    await expect(consolePanel).toBeVisible();
    await expect(preview.getByRole('table')).toBeVisible();
    const previewBounds = await preview.boundingBox();
    const consoleBounds = await consolePanel.boundingBox();
    expect(previewBounds!.y + previewBounds!.height).toBeLessThanOrEqual(consoleBounds!.y + 1);
    await editor.locator('.notebook-input-file-button').first().click();
    await expect(consolePanel).toBeVisible();
    await preview.getByRole('button', { name: 'Close input data preview' }).click();
    await expect(consolePanel).toBeVisible();
    await editor.getByRole('button', { name: 'Toggle Python console' }).click();
    await expect(preview).toHaveCount(0);

    await editor
      .locator('.notebook-input-section')
      .screenshot({ path: '/tmp/arena-input-panel.png' });

    await editor.getByRole('button', { name: 'Run all', exact: true }).click();
    await expect(editor.getByRole('button', { name: 'Run all', exact: true })).toBeEnabled({
      timeout: 130000,
    });
    await expect(editor.getByLabel('Output cell 2')).toContainText(
      'input/predict-bike-demand-competition-1/',
    );
    await editor
      .locator('.notebook-menubar')
      .getByRole('button', { name: 'File', exact: true })
      .click();
    await editor.getByRole('menuitem', { name: 'Save notebook', exact: true }).click();
    await expect(editor.locator('.notebook-save-state')).toHaveText('Saved permanently');
    const library = await (await page.request.get('/api/code?filter=your-work')).json();
    const saved = await (await page.request.get(`/api/code/${library.items[0].id}`)).json();
    expect(saved.working_competition_id).toBe(1);
    expect(saved.document.metadata.arena_input_sources[0].id).toBe(1);
    await editor.getByRole('button', { name: 'Close notebook editor', exact: true }).click();
    await page.goto(`/#code/${library.items[0].id}/edit`);
    await expect(page.getByRole('button', { name: 'Run all', exact: true })).toBeEnabled({
      timeout: 240000,
    });
    await expect(page.locator('.notebook-inputs')).toContainText('Predict bike demand');
  } finally {
    await page.request.delete('/api/notebook-session', { headers });
  }
});
