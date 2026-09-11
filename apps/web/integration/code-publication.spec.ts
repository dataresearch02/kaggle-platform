import { test, expect } from '@playwright/test';

test('published code forks with inputs into an isolated editor and retains outputs', async ({
  page,
  browser,
}) => {
  const headers = { 'X-Arena-Client': 'web' };
  const author = `publish_${Date.now()}`;
  expect(
    (
      await page.request.post('/api/auth/register', {
        headers,
        data: { username: author, password: 'publication-password' },
      })
    ).status(),
  ).toBe(201);
  const recipientContext = await browser.newContext();
  const recipient = await recipientContext.newPage();
  try {
    const dataset = await (
      await page.request.post('/api/datasets', {
        headers,
        multipart: {
          title: 'Forkable notebook input',
          description: 'Input used by the publication test',
          file: {
            name: 'values.csv',
            mimeType: 'text/csv',
            buffer: Buffer.from('value\n21\n21\n'),
          },
        },
      })
    ).json();
    const created = await (
      await page.request.post('/api/notebooks', {
        headers,
        data: { title: `Published input experiment ${Date.now()}`, code: 'print(42)' },
      })
    ).json();
    await page.request.put(`/api/datasets/${dataset.id}/access`, {
      headers,
      data: { visibility: 'public' },
    });
    const source = `import pandas as pd\nfrom IPython.display import display\ndf = pd.read_csv('arena-input-${dataset.id}.csv')\nprint('INPUT_SUM', df['value'].sum())\ndisplay(df)`;
    expect(
      (
        await page.request.put(`/api/code/${created.id}/publication`, {
          headers,
          data: {
            nbformat: 4,
            nbformat_minor: 5,
            metadata: { arena_inputs: [{ id: dataset.id }] },
            cells: [
              { id: 'notes', cell_type: 'markdown', source: '# Input experiment', metadata: {} },
              {
                id: 'code',
                cell_type: 'code',
                source,
                metadata: {},
                outputs: [],
                execution_count: null,
              },
            ],
          },
        })
      ).status(),
    ).toBe(200);
    await page.goto(`/#code/${created.id}/edit`);
    await expect(page.getByRole('button', { name: 'Run all', exact: true })).toBeEnabled({
      timeout: 240000,
    });
    await page.getByRole('button', { name: 'Run all', exact: true }).click();
    await expect(page.getByLabel('Output cell 2')).toContainText('INPUT_SUM 42', {
      timeout: 60000,
    });
    await page.getByRole('button', { name: 'Publish code and outputs', exact: true }).click();
    await page.getByRole('button', { name: 'Version history', exact: true }).click();
    const history = page.getByRole('dialog', { name: 'Notebook version history' });
    await expect(history.locator('.history-version').first()).toBeVisible();
    await history.locator('.history-version').last().click();
    page.once('dialog', (dialog) => dialog.accept());
    await history.getByRole('button', { name: 'Restore into editor' }).click();
    await expect(page.locator('.arena-cell .cm-content')).toHaveText('print(42)');
    await page.getByRole('link', { name: 'View published code', exact: true }).click();
    await expect(page.getByLabel('Published output cell 2')).toContainText('INPUT_SUM 42');
    await expect(page.getByRole('button', { name: 'Run all', exact: true })).toHaveCount(0);
    const original = await (await page.request.get(`/api/code/${created.id}`)).json();
    await page.request.delete('/api/notebook-session', { headers });
    expect(
      (
        await recipient.request.post('/api/auth/register', {
          headers,
          data: { username: `fork_${Date.now()}`, password: 'publication-password' },
        })
      ).status(),
    ).toBe(201);
    await recipient.goto(`/#code/${created.id}`);
    await expect(recipient.getByRole('link', { name: 'Edit my code' })).toHaveCount(0);
    await recipient.getByRole('button', { name: 'Fork code', exact: true }).click();
    await expect(recipient).toHaveURL(/#code\/\d+\/edit$/);
    const forkId = Number(recipient.url().match(/#code\/(\d+)/)![1]);
    expect(forkId).not.toBe(created.id);
    await expect(recipient.getByRole('button', { name: 'Run all', exact: true })).toBeEnabled({
      timeout: 240000,
    });
    await recipient.getByRole('button', { name: 'Run all', exact: true }).click();
    await expect(recipient.getByLabel('Output cell 2')).toContainText('INPUT_SUM 42', {
      timeout: 60000,
    });
    await recipient.locator('.arena-cell .cm-content').last().fill("print('MY_FORK_ONLY')");
    await recipient.getByRole('button', { name: 'Run all', exact: true }).click();
    await expect(recipient.getByLabel('Output cell 2')).toContainText('MY_FORK_ONLY');
    await recipient.getByRole('button', { name: 'Publish code and outputs', exact: true }).click();
    await recipient.getByRole('link', { name: 'View published code', exact: true }).click();
    await expect(recipient.getByLabel('Published output cell 2')).toContainText('MY_FORK_ONLY');
    await recipient.reload();
    await expect(recipient.getByLabel('Published output cell 2')).toContainText('MY_FORK_ONLY');
    expect((await (await page.request.get(`/api/code/${created.id}`)).json()).document).toEqual(
      original.document,
    );
    await recipient.screenshot({ path: 'hub-test-results/published-fork.png', fullPage: true });
  } finally {
    await page.request.delete('/api/notebook-session', { headers });
    await recipient.request.delete('/api/notebook-session', { headers });
    await recipientContext.close();
  }
});
