import { test, expect } from '@playwright/test';

test('joined member creates temporary competition code and saves it into Your work', async ({
  page,
}) => {
  const headers = { 'X-Arena-Client': 'web' };
  await page.request.post('/api/auth/register', {
    headers,
    data: { username: `competition_code_${Date.now()}`, password: 'competition-code-password' },
  });
  try {
    await page.goto('/#competitions/1/code');
    await expect(page.getByRole('button', { name: 'New notebook', exact: true })).toBeDisabled();
    await page.getByRole('button', { name: 'Join competition', exact: true }).click();
    await expect(page.getByRole('button', { name: 'New notebook', exact: true })).toBeEnabled();
    await page.getByRole('button', { name: 'New notebook', exact: true }).click();
    const title = `Competition entry ${Date.now()}`;
    await page.getByLabel('Notebook title', { exact: true }).fill(title);
    await expect(page.getByRole('button', { name: 'Run all', exact: true })).toBeEnabled({
      timeout: 240000,
    });
    await page
      .locator('.arena-cell .cm-content')
      .first()
      .fill("print('COMPETITION_NOTEBOOK_READY')");
    await page.getByRole('button', { name: 'Run all', exact: true }).click();
    await expect(page.getByLabel('Output cell 1')).toContainText('COMPETITION_NOTEBOOK_READY');
    const navigation = page.getByRole('navigation', { name: 'Platform navigation' });
    await navigation.getByRole('button', { name: 'Expand navigation', exact: true }).click();
    await expect(navigation.getByRole('button', { name: 'Collapse navigation' })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
    await navigation.getByRole('button', { name: 'Collapse navigation' }).click();
    await page
      .locator('.arena-add-cell')
      .getByRole('button', { name: 'Markdown', exact: true })
      .click();
    await page
      .locator('.arena-cell .cm-content')
      .last()
      .fill(
        '# Competition notes\n\n**Important result**\n\n| Model | Score |\n| --- | --- |\n| Baseline | 0.9 |\n\n$x^2$\n\n<h2>HTML section</h2>\n\nSubsection\n---\n\n## Repeated\n\n## Repeated\n\n```python\n# Not a heading\n```',
      );
    const outline = page.getByRole('navigation', { name: 'Notebook headings' });
    await expect(outline.getByRole('button')).toHaveCount(5);
    await outline.getByRole('button', { name: 'HTML section', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'HTML section', exact: true })).toBeFocused();
    await outline.getByRole('button', { name: 'Repeated', exact: true }).last().click();
    await expect(page.getByRole('heading', { name: 'Repeated', exact: true }).last()).toBeFocused();
    await expect(outline.getByRole('button', { name: 'Not a heading' })).toHaveCount(0);
    await expect(page.getByRole('heading', { name: 'Competition notes' })).toBeVisible();
    await expect(page.locator('.arena-markdown .katex')).toHaveCount(1);
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page.locator('.new-notebook-header')).toContainText('Saved permanently');
    expect(
      (await (await page.request.get('/api/code?competition_id=1&filter=your-work')).json()).items,
    ).toHaveLength(0);
    await page.locator('.arena-cell .cm-content').first().click();
    await page.locator('.arena-cell .cm-content').first().press('ControlOrMeta+a');
    await page.locator('.arena-cell .cm-content').first().press('Backspace');
    await page
      .locator('.arena-cell .cm-content')
      .first()
      .fill(
        "import os, csv\nwith open(os.environ['ARENA_TEST_DATA']) as source:\n    rows = list(csv.DictReader(source))\nwith open(os.environ['ARENA_SUBMISSION_FILE'], 'w', newline='') as target:\n    writer = csv.writer(target)\n    writer.writerow(['id', 'prediction'])\n    writer.writerows((row['id'], 0) for row in rows)",
      );
    await page.getByRole('button', { name: 'Save & Commit', exact: true }).click();
    await page.getByRole('button', { name: 'Run and evaluate', exact: true }).click();
    await expect(page.locator('.commit-status')).toContainText('Evaluated · RMSE', {
      timeout: 90000,
    });
    await page.getByRole('button', { name: 'Close notebook editor', exact: true }).click();
    await expect(page.getByRole('tab', { name: 'Your work', exact: true })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await expect(page.getByRole('link', { name: title, exact: true })).toBeVisible();
    const codes = await (
      await page.request.get('/api/code?competition_id=1&filter=your-work')
    ).json();
    expect(codes.items).toHaveLength(1);
    await page.getByRole('link', { name: title, exact: true }).click();
    await expect(page).toHaveURL(/\/edit\?competition=1$/);
    await expect(page.locator('.code-editor-fullscreen')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Run all', exact: true })).toBeEnabled();
    expect(
      await page
        .locator('.code-editor-fullscreen')
        .evaluate((el) => el.getBoundingClientRect().height === innerHeight),
    ).toBe(true);
    await page.getByRole('button', { name: 'Close notebook editor', exact: true }).click();
    await page.goto(`/#code/${codes.items[0].id}?competition=1`);
    await expect(page.getByRole('heading', { name: 'Competition notes' })).toBeVisible();
    await expect(page.locator('.code-published-cells .katex')).toHaveCount(1);
    await expect(page.getByRole('cell', { name: 'Baseline', exact: true })).toBeVisible();
    await page.goto('/#competitions/1/code');
    await page.reload();
    await expect(page.getByRole('link', { name: title, exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'New notebook', exact: true }).click();
    await expect(
      page.getByRole('button', { name: 'Close notebook editor', exact: true }),
    ).toBeVisible();
    const rail = page.getByRole('navigation', { name: 'Platform navigation', exact: true });
    await expect(rail.getByRole('group', { name: 'Data Hub' })).toBeHidden();
    await rail.getByRole('button', { name: 'Data Hub', exact: true }).click();
    await expect(rail.getByRole('button', { name: 'Codes', exact: true })).toHaveAttribute(
      'aria-current',
      'page',
    );
    await expect(rail.getByRole('group', { name: 'Data Hub' })).toBeVisible();
    await expect(rail.getByRole('button', { name: 'Your work', exact: true })).toBeVisible();
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(rail.getByRole('button', { name: 'Datasets', exact: true })).toBeVisible();
    const discarded = page.waitForResponse(
      (response) =>
        response.url().includes('/api/notebook-drafts/') &&
        response.request().method() === 'DELETE',
    );
    await rail.getByRole('button', { name: 'Datasets', exact: true }).click();
    expect((await discarded).ok()).toBe(true);
    await expect(page).toHaveURL(/#datasets$/);

    await expect(page.getByRole('dialog', { name: 'New notebook', exact: true })).toHaveCount(0);
    expect(
      (await (await page.request.get('/api/code?competition_id=1&filter=your-work')).json()).items,
    ).toHaveLength(1);
  } finally {
    await page.request.delete('/api/notebook-session', { headers });
  }
});
