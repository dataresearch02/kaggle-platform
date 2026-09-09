import { test, expect } from '@playwright/test';

test('a learner can publish data, save a notebook, complete a lesson and submit predictions', async ({
  page,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('/');
  await expect(
    page.getByRole('heading', { name: 'A little curiosity. Endless possibilities.' }),
  ).toBeVisible();
  await page.screenshot({ path: 'test-results/overview-desktop.png', fullPage: true });
  await page.getByRole('button', { name: 'Join the community' }).click();
  await page.getByLabel('Username', { exact: true }).fill(`learner_${Date.now()}`);
  await page.getByLabel(/^Password/).fill('browser-test-password');
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);

  await page.getByRole('navigation').getByRole('button', { name: 'Datasets', exact: true }).click();
  await page.getByRole('button', { name: 'Upload dataset', exact: true }).click();
  await page.getByLabel('Title', { exact: true }).fill('Browser dataset');
  await page
    .getByLabel('Description', { exact: true })
    .fill('A dataset uploaded through the browser.');
  await page.getByLabel('CSV file').setInputFiles({
    name: 'browser.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('id,value\n1,10\n2,20\n'),
  });
  await page.getByRole('button', { name: 'Publish', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page
    .getByRole('button', { name: /Browser dataset/ })
    .first()
    .click();
  await expect(page.getByRole('cell', { name: '20', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Close dialog' }).click();

  await page.getByRole('navigation').getByRole('button', { name: 'Codes', exact: true }).click();
  // Draft creation uses a live kernel and is covered by the Hub integration suite.
  await page.request.post('/api/notebooks', {
    headers: { 'X-Arena-Client': 'web' },
    data: { title: 'Browser experiment', description: 'A saved experiment.', code: 'print(42)' },
  });
  await page.reload();
  await page
    .getByRole('button', { name: /Browser experiment/ })
    .first()
    .click();
  await page.getByText('Community template source', { exact: true }).click();
  await page.getByLabel('Python source').fill('print(43)');
  await page.getByRole('button', { name: 'Save notebook template', exact: true }).click();
  await expect(page.locator('.toast')).toContainText('Notebook saved');
  await page.getByRole('button', { name: 'Close dialog' }).click();

  await page.getByRole('navigation').getByRole('button', { name: 'Learn', exact: true }).click();
  await page.getByRole('button', { name: /Python foundations/ }).click();
  await page.getByRole('button', { name: 'Mark as complete' }).click();
  await expect(page.getByText('1 of 3 lessons complete')).toBeVisible();
  await page.getByRole('button', { name: 'Close dialog' }).click();

  await page
    .getByRole('navigation')
    .getByRole('button', { name: 'Competitions', exact: true })
    .click();
  await page.getByRole('button', { name: /Predict bike demand/ }).click();
  await page.getByRole('button', { name: 'Join competition', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('You joined');
  await page.getByLabel('Submit predictions').setInputFiles({
    name: 'submission.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('id,prediction\n7,240\n8,100\n9,300\n'),
  });
  await page.getByRole('button', { name: 'Score submission' }).click();
  await expect(page.getByRole('heading', { name: 'Your submissions' })).toBeVisible();
  await expect(page.getByRole('dialog')).toContainText('0.0000');
  expect(errors).toEqual([]);
});

test('mobile navigation and layout work', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(
    page.getByRole('heading', { name: 'A little curiosity. Endless possibilities.' }),
  ).toBeVisible();
  await expect(page.locator('.skeleton')).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/overview-mobile.png', fullPage: true });
  await page.getByRole('button', { name: 'Toggle navigation' }).click();
  await page.getByRole('navigation').getByRole('button', { name: 'Learn', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Make room for a new skill.' })).toBeVisible();
});

test('creators can publish competitions and benchmarks and score predictions', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Join the community' }).click();
  await page.getByLabel('Username', { exact: true }).fill(`creator_${Date.now()}`);
  await page.getByLabel(/^Password/).fill('creator-password-123');
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  for (const kind of ['Competition', 'Benchmark'] as const) {
    await page.getByRole('button', { name: 'Create', exact: true }).click();
    await page.getByRole('menuitem', { name: kind, exact: true }).click();
    const dialog = page.getByRole('dialog');
    const form = page.locator('.publish-page');
    const title = `${kind} browser check ${Date.now()}`;
    await form.getByLabel('Title', { exact: true }).fill(title);
    await form
      .getByLabel('Description', { exact: true })
      .fill('Predict values for this community challenge.');
    if (kind === 'Competition')
      await form.getByLabel('Closing date and time').fill('2099-01-01T12:00');
    await form.getByLabel('Public test CSV').setInputFiles({
      name: 'test.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from('id,feature\na,1\nb,2\n'),
    });
    await form.getByLabel('Private answer CSV').setInputFiles({
      name: 'answers.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from('id,prediction\na,10\nb,20\n'),
    });
    await form.getByRole('button', { name: 'Publish', exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await page.getByRole('button', { name: new RegExp(title) }).click();
    await dialog.getByRole('button', { name: `Join ${kind.toLowerCase()}`, exact: true }).click();
    await dialog.getByLabel('Submit predictions').setInputFiles({
      name: 'predictions.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from('id,prediction\na,10\nb,20\n'),
    });
    await dialog.getByRole('button', { name: 'Score submission' }).click();
    await expect(dialog.getByRole('cell', { name: '#1', exact: true })).toBeVisible();
    await expect(dialog.getByRole('cell', { name: '0.0000', exact: true }).first()).toBeVisible();
    await dialog.getByRole('button', { name: 'Close dialog', exact: true }).click();
  }
});

test('Create dropdown supports keyboard selection and upload page validates dropped files', async ({
  page,
}) => {
  await page.goto('/');
  const create = page.getByRole('button', { name: 'Create', exact: true });
  await create.click();
  await expect(page.getByRole('menu')).toBeVisible();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.screenshot({ path: 'test-results/create-dropdown.png' });
  await page.keyboard.press('Escape');
  await expect(create).toBeFocused();
  await create.click();
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Enter');
  await page.getByLabel('Username', { exact: true }).fill(`upload_${Date.now()}`);
  await page.getByLabel(/^Password/).fill('upload-test-password');
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Share a dataset' })).toBeVisible();
  await page
    .getByLabel('CSV file', { exact: true })
    .setInputFiles({ name: 'wrong.txt', mimeType: 'text/plain', buffer: Buffer.from('bad') });
  await expect(page.getByRole('alert')).toContainText('Choose a CSV file');
  const files = await page.evaluateHandle(() => {
    const transfer = new DataTransfer();
    transfer.items.add(new File(['id,value\n1,10\n'], 'dropped.csv', { type: 'text/csv' }));
    return transfer;
  });
  await page.locator('.upload-drop').dispatchEvent('drop', { dataTransfer: files });
  await expect(page.locator('.upload-file')).toContainText('dropped.csv');
  const drawer = page.locator('.publish-drawer');
  await expect(drawer).toBeVisible();
  await expect(page.locator('main .filters')).toBeVisible();
  await expect.poll(async () => Math.round((await drawer.boundingBox())!.x)).toBe(720);
  expect(Math.round((await drawer.boundingBox())!.width)).toBe(720);
  await page.screenshot({ path: 'test-results/upload-desktop.png', fullPage: true });
  await page.getByRole('button', { name: 'Remove CSV file' }).click();
  await expect(page.locator('.upload-file')).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: 'test-results/upload-mobile.png', fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(page.locator('.publish-page')).toHaveCount(0);
  await page.getByRole('button', { name: 'Upload dataset', exact: true }).click();
  await expect(page.locator('.publish-drawer')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.locator('.publish-drawer')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Upload dataset', exact: true })).toBeFocused();
});

test('Your work appears after creation and manages only the current users content', async ({
  page,
}) => {
  await page.goto('/');
  const navigation = page.getByRole('navigation', { name: 'Main navigation' });
  await expect(navigation.getByRole('button', { name: 'Your work', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Join the community' }).click();
  await page.getByLabel('Username', { exact: true }).fill(`work_${Date.now()}`);
  await page.getByLabel(/^Password/).fill('workspace-test-password');
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await navigation.getByRole('button', { name: 'Datasets', exact: true }).click();
  await page.getByRole('button', { name: 'Your work', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Create something of your own' })).toBeVisible();
  await expect(navigation.getByRole('button', { name: 'Your work', exact: true })).toHaveCount(0);
  await navigation.getByRole('button', { name: 'Datasets', exact: true }).click();
  await page.getByRole('button', { name: 'Upload dataset', exact: true }).click();
  await page.getByLabel('Title', { exact: true }).fill('My managed dataset');
  await page.getByLabel('Description', { exact: true }).fill('Data belonging to this creator.');
  await page.getByLabel('CSV file').setInputFiles({
    name: 'managed.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('x,y\n1,2\n'),
  });
  await page.getByRole('button', { name: 'Publish', exact: true }).click();
  await expect(navigation.getByRole('button', { name: 'Your work', exact: true })).toBeVisible();
  await navigation.getByRole('button', { name: 'Your work', exact: true }).click();
  await expect(page.locator('.work-row')).toHaveCount(1);
  await page
    .getByRole('button', { name: 'Edit details for My managed dataset', exact: true })
    .click();
  await page.getByLabel('Title', { exact: true }).fill('Renamed dataset');
  await page
    .getByLabel('Description', { exact: true })
    .fill('Updated metadata, original data preserved.');
  await page.getByRole('button', { name: 'Save details', exact: true }).click();
  await expect(page.locator('.work-row')).toContainText('Renamed dataset');
  await page.getByRole('button', { name: 'Open Renamed dataset', exact: true }).click();
  await expect(page.getByRole('cell', { name: '2', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Close dialog' }).click();
  await page.getByLabel('Search your work').fill('no match');
  await expect(page.getByRole('heading', { name: 'No matching work' })).toBeVisible();
  await page.getByLabel('Search your work').fill('');
  await page.screenshot({ path: 'test-results/your-work-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/your-work-mobile.png', fullPage: true });
  await page.getByRole('button', { name: 'Delete Renamed dataset', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Delete this item?' })).toContainText(
    'Renamed dataset',
  );
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(page.locator('.work-row')).toHaveCount(1);
  await page.getByRole('button', { name: 'Delete Renamed dataset', exact: true }).click();
  await page.getByRole('button', { name: 'Delete permanently', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.locator('.work-row')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Create something of your own' })).toBeVisible();
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(page.locator('.work-row')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Your work starts here' })).toBeVisible();
});
