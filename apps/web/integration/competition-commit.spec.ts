import { test, expect } from '@playwright/test';

test('competition forks remain private until a fresh run produces valid predictions', async ({
  page,
}) => {
  const headers = { 'X-Arena-Client': 'web' };
  await page.request.post('/api/auth/register', {
    headers,
    data: { username: `commit_test_${Date.now()}`, password: 'commit-workflow-password' },
  });
  await page.request.post('/api/competitions/1/join', { headers });
  let id = 0;
  try {
    await page.goto('/#code/1?competition=1');
    const forked = page.waitForResponse(
      (response) =>
        response.url().includes('/api/code/1/fork') && response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: 'Fork code', exact: true }).click();
    id = (await (await forked).json()).id;
    await expect(page.getByRole('button', { name: 'Run all', exact: true })).toBeEnabled({
      timeout: 240000,
    });
    const cell = page.locator('.arena-cell .cm-content').first();
    await cell.fill("print('No predictions written')");
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeEnabled();
    const codes = async () =>
      (await (await page.request.get('/api/code?competition_id=1&filter=your-work')).json()).items;
    expect(await codes()).toHaveLength(0);
    expect((await (await page.request.get(`/api/code/${id}`)).json()).private).toBe(true);
    await page.getByRole('button', { name: 'Save & Commit', exact: true }).click();
    await page.getByRole('button', { name: 'Run and evaluate', exact: true }).click();
    await expect(page.locator('.commit-status')).toContainText('Commit failed:', {
      timeout: 90000,
    });
    await expect(page.locator('.commit-status')).toContainText('did not produce submission.csv');
    expect(await codes()).toHaveLength(0);
    const code =
      "import os, csv\nwith open(os.environ['ARENA_TEST_DATA']) as source:\n    rows = list(csv.DictReader(source))\nwith open(os.environ['ARENA_SUBMISSION_FILE'], 'w', newline='') as target:\n    writer = csv.writer(target)\n    writer.writerow(['id', 'prediction'])\n    for row in rows:\n        writer.writerow([row['id'], 0])\nprint('COMMIT_EVALUATION_READY', len(rows))";
    await cell.fill(code);
    await page.getByRole('button', { name: 'Save & Commit', exact: true }).click();
    await page.getByRole('button', { name: 'Run and evaluate', exact: true }).click();
    await expect(page.locator('.commit-status')).toContainText('Evaluated · Score', {
      timeout: 90000,
    });
    expect((await codes()).map((row: { id: number }) => row.id)).toEqual([id]);
    const published = (await (await page.request.get(`/api/code/${id}`)).json()).document;
    expect(published.cells[0].outputs[0].text).toContain('COMMIT_EVALUATION_READY');
    expect(published.cells[0].source).toBe(code);
    await cell.fill("print('NEXT_PRIVATE_EDIT')");
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeEnabled();
    expect(
      (await (await page.request.get(`/api/code/${id}`)).json()).document.cells[0].source,
    ).toBe(code);
    await page.getByRole('button', { name: 'Close notebook editor', exact: true }).click();
    await expect(page).toHaveURL(/#competitions\/1\/code$/);
    await expect(page.locator(`a[href="#code/${id}/edit?competition=1"]`)).toBeVisible();
  } finally {
    // All commits above have finished before stopping the user's runtime.
    await page.request.delete('/api/notebook-session', { headers });
  }
});
