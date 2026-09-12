import { test, expect } from '@playwright/test';

test('official Titanic files, pages, archived outputs and forked code work without local scoring', async ({
  page,
}) => {
  test.setTimeout(180000);
  const headers = { 'X-Arena-Client': 'web' };
  const competitions = await (await page.request.get('/api/competitions')).json();
  const competition = competitions.find(
    (row: { source_url?: string }) =>
      row.source_url === 'https://www.kaggle.com/competitions/titanic',
  );
  test.skip(!competition, 'Import the official Titanic bundle first');
  await page.request.post('/api/auth/register', {
    headers,
    data: { username: `titanic_check_${Date.now()}`, password: 'titanic-browser-test-password' },
  });
  const base = `/api/competitions/${competition.id}`;
  try {
    await page.goto(`/#competitions/${competition.id}/overview`);
    await expect(
      page.getByRole('heading', { name: 'Titanic - Machine Learning from Disaster', exact: true }),
    ).toBeVisible();
    await expect(page.getByText('Ongoing', { exact: true }).first()).toBeVisible();
    await page.getByRole('button', { name: 'Join competition', exact: true }).click();
    await page.goto(`/#competitions/${competition.id}/rules`);
    await expect(
      page.getByRole('heading', { name: 'One account per participant', exact: true }),
    ).toBeVisible();
    await page.goto(`/#competitions/${competition.id}/data`);
    await expect(page.getByText('train.csv', { exact: true }).first()).toBeVisible();
    const testFile = await page.request.get(base + '/test');
    expect((await testFile.text()).split('\n')[0]).toContain('PassengerId,Pclass');
    expect((await (await page.request.get(base + '/sample')).text()).split('\n')[0]).toContain(
      'PassengerId,Survived',
    );
    await page.goto(`/#competitions/${competition.id}/submissions`);
    await expect(
      page.getByRole('status').filter({ hasText: 'Local scoring is unavailable' }),
    ).toBeVisible();
    const notebooks = await (await page.request.get(base + '/resources/notebooks')).json();
    const adapted = notebooks.find((row: { title: string }) =>
      row.title.includes('Arena adaptation'),
    );
    await page.goto(`/#code/${adapted.id}`);
    await expect(page.locator('.code-published-cells')).toContainText('Titanic Tutorial');
    const data = await (await page.request.get(`/api/code/${adapted.id}`)).json();
    expect(data.inputs).toHaveLength(3);
    expect(JSON.stringify(data.document)).toContain('text/csv');
    expect(JSON.stringify(data.document)).toContain('Archived Kaggle execution log');
    const fork = await (
      await page.request.post(`/api/code/${adapted.id}/fork?competition_id=${competition.id}`, {
        headers,
      })
    ).json();
    await page.goto(`/#code/${fork.id}/edit`);
    await expect(page.getByRole('button', { name: 'Run all', exact: true })).toBeVisible({
      timeout: 120000,
    });
    await expect(page.getByRole('button', { name: 'Local scoring unavailable' })).toBeDisabled();
    await page.getByRole('button', { name: 'Run all', exact: true }).click();
    await expect(
      page
        .getByLabel(/^Output cell /)
        .filter({ hasText: 'Your submission was successfully saved!' }),
    ).toBeVisible({ timeout: 60000 });
    await expect(page.getByRole('button', { name: 'Run all', exact: true })).toBeEnabled({
      timeout: 60000,
    });
    await page.screenshot({ path: 'hub-test-results/titanic-notebook.png' });
    expect(
      (
        await page.request.post(`/api/code/${fork.id}/commits`, {
          headers,
          data: { competition_id: competition.id },
        })
      ).status(),
    ).toBe(409);
  } finally {
    await page.request.delete('/api/notebook-session', { headers });
  }
});
