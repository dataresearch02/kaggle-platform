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
  const ownedCode = page.getByRole('link', { name: /Browser experiment/ }).first();
  await expect(ownedCode).toHaveAttribute('href', /\/edit$/);
  // Full-screen owner editing is covered by the live runtime integration test.
  const publishedUrl = (await ownedCode.getAttribute('href'))!.replace('/edit', '');
  await page.goto(`/${publishedUrl}`);
  await expect(page.locator('.code-published-cells')).toContainText('print(42)');
  await expect(page.getByRole('button', { name: 'Run all', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Fork code', exact: true })).toBeVisible();
  await expect(page.getByRole('dialog')).toHaveCount(0);

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
  await expect(page.locator('.competition-page').getByRole('status')).toContainText('You joined');
  const navigation = page.getByRole('navigation', { name: 'Main navigation' });
  await expect(navigation.getByRole('button').last()).toHaveAccessibleName('Your work');
  await navigation.getByRole('button', { name: 'More', exact: true }).click();
  await expect(navigation.getByRole('button', { name: 'Learn', exact: true })).toBeHidden();
  await navigation.getByRole('button', { name: 'More', exact: true }).click();
  await expect(navigation.getByRole('group', { name: 'More' }).getByRole('button')).toHaveCount(2);
  await expect(navigation.getByRole('button', { name: 'Competitions', exact: true })).toHaveCSS(
    'border-right-width',
    '3px',
  );
  await page.getByRole('link', { name: 'Team', exact: true }).click();
  await page.getByLabel('Team name', { exact: true }).fill('Browser team');
  await page.getByRole('button', { name: 'Create team', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Browser team' })).toBeVisible();
  await expect(page.getByLabel('Team invite code')).not.toHaveValue('');
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Browser team' })).toBeVisible();
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'Leave team', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Create team', exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Submissions', exact: true }).click();
  await page.getByLabel('Submit predictions').setInputFiles({
    name: 'submission.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('id,prediction\n7,240\n8,100\n9,300\n'),
  });
  await page.getByRole('button', { name: 'Score submission' }).click();
  await expect(page.getByRole('heading', { name: 'Your submissions' })).toBeVisible();
  await expect(page.locator('.competition-page')).toContainText('0.0000');
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
    const detail = kind === 'Competition' ? page.locator('.competition-page') : dialog;
    await detail.getByRole('button', { name: `Join ${kind.toLowerCase()}`, exact: true }).click();
    if (kind === 'Competition')
      await detail.getByRole('link', { name: 'Submissions', exact: true }).click();
    await detail.getByLabel('Submit predictions').setInputFiles({
      name: 'predictions.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from('id,prediction\na,10\nb,20\n'),
    });
    await detail.getByRole('button', { name: 'Score submission' }).click();
    if (kind === 'Competition')
      await detail.getByRole('link', { name: 'Leaderboard', exact: true }).click();
    await expect(detail.getByRole('cell', { name: '#1', exact: true })).toBeVisible();
    await expect(detail.getByRole('cell', { name: '0.0000', exact: true }).first()).toBeVisible();
    if (kind === 'Competition')
      await detail.getByRole('button', { name: 'All competitions', exact: true }).click();
    else await dialog.getByRole('button', { name: 'Close dialog', exact: true }).click();
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
  await page.getByRole('button', { name: 'Open user menu', exact: true }).click();
  await page.getByRole('button', { name: 'Log out', exact: true }).click();
  await expect(page.locator('.work-row')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Your work starts here' })).toBeVisible();
});

test('competition overview uses a Your work button and combines search and filters', async ({
  page,
}) => {
  await page.goto('/#competitions');
  await expect(page.locator('.collection-tabs')).toHaveCount(0);
  await expect(
    page.locator('.collection-actions').getByRole('button', { name: 'Your work' }),
  ).toBeVisible();
  await page.getByLabel('Search competitions', { exact: true }).fill('bike');
  await page.getByLabel('Competition status', { exact: true }).selectOption('open');
  await page.getByLabel('Competition category', { exact: true }).selectOption('Getting Started');
  await page.getByLabel('Sort competitions', { exact: true }).selectOption('closing');
  await expect(page.getByRole('button', { name: /Predict bike demand/ })).toBeVisible();
  await page.getByLabel('Competition status', { exact: true }).selectOption('closed');
  await expect(page.getByRole('heading', { name: 'No results yet' })).toBeVisible();
  await page.getByRole('button', { name: 'Clear filters', exact: true }).click();
  await expect(page.getByLabel('Search competitions', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('Competition status', { exact: true })).toHaveValue('all');
  await expect(page.getByRole('button', { name: /Predict bike demand/ })).toBeVisible();
  await page.screenshot({ path: 'test-results/competition-filters.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.locator('.collection-actions').getByRole('button', { name: 'Your work' }).click();
  await expect(page.getByRole('heading', { name: 'Your work', exact: true })).toBeVisible();
});

test('competition pages support deep links, all sections and scoped community work', async ({
  page,
}) => {
  await page.goto('/#competitions');
  await page.getByRole('button', { name: /Predict bike demand/ }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page).toHaveURL(/#competitions\/1\/overview$/);
  const sections = page.getByRole('navigation', { name: 'Competition sections' });
  await expect(sections.getByRole('link')).toHaveCount(9);
  await sections.getByRole('link', { name: 'Data', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Join to explore the data' })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: 'temperature', exact: true })).toHaveCount(0);
  await page.reload();
  await expect(sections.getByRole('link', { name: 'Data', exact: true })).toHaveAttribute(
    'aria-current',
    'page',
  );
  await sections.getByRole('link', { name: 'Rules', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Submission rules' })).toBeVisible();
  await sections.getByRole('link', { name: 'Models', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'No models shared yet' })).toBeVisible();
  await page.getByRole('button', { name: 'Join the community' }).click();
  await page.getByLabel('Username', { exact: true }).fill(`comp_page_${Date.now()}`);
  await page.getByLabel(/^Password/).fill('competition-page-password');
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button', { name: 'Join competition', exact: true }).click();
  await sections.getByRole('link', { name: 'Data', exact: true }).click();
  await page.getByRole('button', { name: 'test.csv', exact: true }).click();
  await expect(page.getByRole('columnheader', { name: 'temperature', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Download file' })).toBeVisible();
  const codeTitle = `My competition code ${Date.now()}`;
  const postTitle = `Baseline question ${Date.now()}`;
  const headers = { 'X-Arena-Client': 'web' };
  const code = await (
    await page.request.post('/api/notebooks', {
      headers,
      data: { title: codeTitle, code: 'print(42)' },
    })
  ).json();
  await sections.getByRole('link', { name: 'Code', exact: true }).click();
  await page.getByRole('button', { name: 'Use existing code', exact: true }).click();
  await page.getByLabel('Your saved code').selectOption(String(code.id));
  await expect(page.getByRole('button', { name: 'Open to commit', exact: true })).toBeEnabled();
  // Runtime-backed commit publication is covered by competition-commit.spec.ts.
  expect(
    (
      await (await page.request.get(`/api/code?competition_id=1&filter=your-work`)).json()
    ).items.some((row: { id: number }) => row.id === code.id),
  ).toBe(false);
  await sections.getByRole('link', { name: 'Discussion', exact: true }).click();
  await page.getByLabel('Discussion title').fill(postTitle);
  await page.getByLabel('Message', { exact: true }).fill('I will begin with a simple baseline.');
  await page.getByRole('button', { name: 'Post discussion' }).click();
  await expect(page.getByRole('heading', { name: postTitle, exact: true })).toBeVisible();
  await sections.getByRole('link', { name: 'Overview', exact: true }).click();
  await page.screenshot({ path: 'test-results/competition-page-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/competition-page-mobile.png', fullPage: true });
  await page.getByRole('button', { name: 'All competitions', exact: true }).click();
  await expect(page).toHaveURL(/#competitions$/);
  await page.goBack();
  await expect(
    page.getByRole('heading', { name: 'Predict bike demand', exact: true }),
  ).toBeVisible();
});

test('organizer edits overview and publishes documented competition files', async ({ page }) => {
  await page.goto('/');
  const headers = { 'X-Arena-Client': 'web' };
  const registration = await page.request.post('/api/auth/register', {
    headers,
    data: { username: `metadata_${Date.now()}`, password: 'metadata-test-password' },
  });
  expect(registration.status()).toBe(201);
  const created = await page.request.post('/api/competitions', {
    headers,
    multipart: {
      title: 'Documented competition',
      description: 'Predict measured demand',
      deadline: '2028-12-31T23:59:59Z',
      test_file: {
        name: 'test.csv',
        mimeType: 'text/csv',
        buffer: Buffer.from('id,x\na,2\nb,3\n'),
      },
      solution_file: {
        name: 'solution.csv',
        mimeType: 'text/csv',
        buffer: Buffer.from('id,prediction\na,4\nb,6\n'),
      },
    },
  });
  expect(created.status()).toBe(201);
  const item = await created.json();
  await page.goto(`/#competitions/${item.id}/overview`);
  await page.reload();
  await page.getByRole('button', { name: 'Edit overview', exact: true }).click();
  await page.getByLabel('Prize summary', { exact: true }).fill('Research credits');
  await page.getByLabel('Prize details', { exact: true }).fill('Credits for the top three teams');
  await page
    .getByLabel('How to participate', { exact: true })
    .fill('Train on historical demand and validate before submitting.');
  await page.getByRole('button', { name: 'Save overview', exact: true }).click();
  await expect(page.getByText('Credits for the top three teams')).toBeVisible();
  await page.reload();
  await expect(
    page.getByText('Train on historical demand and validate before submitting.'),
  ).toBeVisible();
  await page.getByRole('link', { name: 'Data', exact: true }).click();
  await page.getByText('Add competition data', { exact: true }).click();
  await page.getByLabel('CSV file', { exact: true }).setInputFiles({
    name: 'train.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('id,x,target\n1,4,8\n2,5,10\n'),
  });
  await page.getByLabel('File path', { exact: true }).fill('train/features.csv');
  await page.getByLabel('Description', { exact: true }).fill('Historical features and labels');
  await page.getByLabel('License', { exact: true }).fill('CC0-1.0');
  await page.getByRole('button', { name: 'Add file', exact: true }).click();
  await expect(page.getByRole('button', { name: 'features.csv', exact: true })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: 'target', exact: true })).toBeVisible();
  await page.getByText('Edit file documentation', { exact: true }).click();
  await page.getByLabel('target', { exact: true }).fill('Demand to predict');
  await page.getByRole('button', { name: 'Save documentation', exact: true }).click();
  await expect(page.getByRole('cell', { name: 'Demand to predict', exact: true })).toBeVisible();
  await page.screenshot({ path: 'test-results/competition-data-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/competition-data-mobile.png', fullPage: true });
});

test('compact navigation keeps groups closed and opens active events', async ({ page }) => {
  await page.goto('/');
  const sidebar = page.locator('.sidebar');
  const header = sidebar.locator('.sidebar-header');
  await expect(header.getByRole('button', { name: 'Arena home' })).toBeVisible();
  await sidebar.getByRole('button', { name: 'Collapse navigation' }).click();
  await expect(sidebar.getByRole('button', { name: 'Arena home' })).toBeHidden();
  await expect(sidebar.getByRole('group', { name: 'Data Hub' })).toBeHidden();
  await sidebar.getByRole('button', { name: 'Data Hub', exact: true }).click();
  await expect(sidebar.getByRole('button', { name: 'Datasets', exact: true })).toBeVisible();
  await sidebar.getByRole('button', { name: 'View Active Events' }).click();
  const dialog = page.getByRole('dialog', { name: 'No Active Events' });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText('0 Active Events', { exact: true })).toBeVisible();
  await page.screenshot({ path: 'test-results/active-events.png' });
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await sidebar.getByRole('button', { name: 'Expand navigation' }).click();
  await expect(header.getByRole('button', { name: 'Arena home' })).toBeVisible();
});
