import { test, expect } from '@playwright/test';

test('Kaggle practice notebooks run, download CSVs and receive real scores', async ({ page }) => {
  const headers = { 'X-Arena-Client': 'web' };
  const competitions = await (await page.request.get('/api/competitions')).json();
  const samples = competitions.filter((row: { title: string }) => row.title.endsWith('(practice)'));
  test.skip(samples.length !== 2, 'Import the optional sample pack before running this test.');
  const registration = await page.request.post('/api/auth/register', {
    headers,
    data: { username: `sample_test_${Date.now()}`, password: 'sample-workflow-password' },
  });
  expect(registration.status()).toBe(201);
  try {
    for (const competition of samples) {
      await page.goto(`/#competitions/${competition.id}/code`);
      for (const baseline of [false, true]) {
        await page.goto(`/#competitions/${competition.id}/code`);
        await page
          .getByRole('link', {
            name: baseline
              ? /^(Iris|Palmer Penguins) — submission baseline/
              : /^(Iris|Palmer Penguins) — explore the training data/,
          })
          .click();
        await expect(
          page.getByRole('heading', { name: 'Dataset at a glance', exact: true }),
        ).toBeVisible();
        await expect(page.locator('.code-published-cells table')).toHaveCount(3);
        await expect(
          page
            .getByRole('navigation', { name: 'Notebook headings' })
            .getByRole('button', { name: 'Sources and attribution', exact: true }),
        ).toBeVisible();
        await page.getByRole('button', { name: 'Fork code', exact: true }).click();
        await expect(page.getByRole('button', { name: 'Run all', exact: true })).toBeEnabled({
          timeout: 240000,
        });
        await page.getByRole('button', { name: 'Run all', exact: true }).click();
        if (baseline) {
          const link = page.getByRole('link', { name: 'Download CSV', exact: true });
          await expect(link).toBeVisible({ timeout: 60000 });
          const downloadPromise = page.waitForEvent('download');
          await link.click();
          const download = await downloadPromise;
          expect(await download.failure()).toBeNull();
          const path = await download.path();
          expect(path).toBeTruthy();
          await page.getByRole('button', { name: 'Close notebook editor', exact: true }).click();
          await page.getByRole('button', { name: 'Join competition', exact: true }).click();
          await page.getByRole('link', { name: 'Submissions', exact: true }).click();
          await page.getByLabel('Submit predictions').setInputFiles(path!);
          await page.getByRole('button', { name: 'Score submission', exact: true }).click();
          await expect(page.getByText(/Submission scored:/)).toBeVisible();
        } else {
          await expect(
            page.locator('.arena-cell-outputs').filter({ hasText: 'Training rows:' }),
          ).toBeVisible({
            timeout: 60000,
          });
          await expect(page.getByAltText('Python plot output')).toBeVisible();
          await page.getByRole('button', { name: 'Close notebook editor', exact: true }).click();
        }
      }
    }
  } finally {
    await page.request.delete('/api/notebook-session', { headers });
  }
});
