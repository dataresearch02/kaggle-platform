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

  await page
    .getByRole('navigation')
    .getByRole('button', { name: 'Notebooks', exact: true })
    .click();
  await page.getByRole('button', { name: 'New notebook' }).click();
  await page.getByLabel('Title', { exact: true }).fill('Browser experiment');
  await page.getByLabel('Description', { exact: true }).fill('A saved experiment.');
  await page.getByLabel('Python code').fill('print(42)');
  await page.getByRole('button', { name: 'Publish', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
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
