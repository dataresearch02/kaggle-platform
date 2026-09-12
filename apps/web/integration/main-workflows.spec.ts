import { test, expect } from '@playwright/test';

const headers = { 'X-Arena-Client': 'web' };

test('personal notebook attaches input, executes, saves outputs and reopens for editing', async ({
  page,
}) => {
  const suffix = Date.now();
  await page.request.post('/api/auth/register', {
    headers,
    data: { username: `personal_core_${suffix}`, password: 'core-workflow-password' },
  });
  const response = await page.request.post('/api/datasets', {
    headers,
    multipart: {
      title: `Core input ${suffix}`,
      description: 'Personal training input',
      file: {
        name: 'train.csv',
        mimeType: 'text/csv',
        buffer: Buffer.from('x,y\n1,2\n2,4\n3,6\n'),
      },
    },
  });
  expect(response.ok()).toBeTruthy();
  const dataset = await response.json();
  let notebookId = 0;
  try {
    await page.goto('/');
    await page
      .locator('.app > .sidebar')
      .getByRole('button', { name: 'Create', exact: true })
      .click();
    await page.getByRole('menuitem', { name: 'Notebook', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Run all', exact: true })).toBeEnabled({
      timeout: 120000,
    });
    await page.getByLabel('Notebook title', { exact: true }).fill(`Personal run ${suffix}`);
    await page.getByRole('button', { name: 'Add Input', exact: true }).click();
    await page
      .locator('.notebook-input-source-tabs')
      .getByRole('button', { name: 'Datasets', exact: true })
      .click();
    await page.getByLabel('Search input sources').fill(dataset.title);
    await page.getByRole('button', { name: 'Search', exact: true }).click();
    await page.locator('.notebook-dataset-option').filter({ hasText: dataset.title }).click();
    await expect(page.locator('.notebook-input-source-title')).toContainText(dataset.title);
    const code = `from pathlib import Path
import pandas as pd
import torch
source = next(Path('input').rglob('train.csv'))
data = pd.read_csv(source)
x = torch.tensor(data['x'].to_numpy(), dtype=torch.float32)
y = torch.tensor(data['y'].to_numpy(), dtype=torch.float32)
weight = (x @ y) / (x @ x)
assert weight.item() == 2.0
Path('model.txt').write_text(str(weight.item()))
print('PERSONAL_TRAINING_OK', len(data), weight.item())`;
    await page.locator('.arena-cell .cm-content').first().fill(code);
    await page.getByRole('button', { name: 'Run all', exact: true }).click();
    await expect(
      page.getByLabel(/^Output cell /).filter({ hasText: 'PERSONAL_TRAINING_OK' }),
    ).toBeVisible({ timeout: 60000 });
    const saved = page.waitForResponse(
      (r) => /\/notebook-drafts\/[^/]+\/save$/.test(r.url()) && r.request().method() === 'POST',
    );
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    const drawer = page.getByRole('dialog', { name: 'Save version', exact: true });
    await drawer.getByRole('button', { name: 'Save', exact: true }).click();
    notebookId = (await (await saved).json()).id;
    await expect(drawer).toBeHidden();
    page.once('dialog', (dialog) => dialog.accept());
    await page
      .locator('.notebook-menubar')
      .getByRole('button', { name: 'Run', exact: true })
      .click();
    await page
      .getByRole('menuitem', { name: 'Save and stop notebook server', exact: true })
      .click();
    await expect(page.getByRole('button', { name: 'Start session', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Close notebook editor', exact: true }).click();
    await page.goto(`/#code/${notebookId}/edit`);
    await expect(page.getByRole('button', { name: 'Run all', exact: true })).toBeEnabled({
      timeout: 120000,
    });
    await expect(page.locator('.arena-cell .cm-content').first()).toContainText(
      'PERSONAL_TRAINING_OK',
    );
    await expect(page.locator('.notebook-input-source-title')).toContainText(dataset.title);
    await page.getByRole('button', { name: 'Add code cell', exact: true }).click();
    await page
      .locator('.arena-cell .cm-content')
      .last()
      .fill(
        "from pathlib import Path\nassert Path('model.txt').read_text() == '2.0'\nprint('MODEL_SURVIVED_SERVER_STOP')",
      );
    await page.getByRole('button', { name: 'Run cell', exact: true }).click();
    await expect(
      page.getByLabel(/^Output cell /).filter({ hasText: 'MODEL_SURVIVED_SERVER_STOP' }),
    ).toBeVisible();
    const outputs = await (
      await page.request.get(`/api/notebook-outputs?notebook_id=${notebookId}`)
    ).json();
    expect(outputs.items.some((row: { filename: string }) => row.filename === 'model.txt')).toBe(
      true,
    );
  } finally {
    await page.request.delete('/api/notebook-session', { headers });
    if (notebookId) await page.request.delete(`/api/work/notebooks/${notebookId}`, { headers });
    await page.request.delete(`/api/work/datasets/${dataset.id}`, { headers });
  }
});

test('joined competition draft commits on first save and only evaluated code is published', async ({
  page,
}) => {
  await page.request.post('/api/auth/register', {
    headers,
    data: { username: `competition_core_${Date.now()}`, password: 'core-workflow-password' },
  });
  let notebookId = 0;
  try {
    await page.goto('/#competitions/1/code');
    await expect(page.getByRole('button', { name: 'New notebook', exact: true })).toBeDisabled();
    await page.getByRole('button', { name: 'Join competition', exact: true }).click();
    await page.getByRole('button', { name: 'New notebook', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Run all', exact: true })).toBeEnabled({
      timeout: 120000,
    });
    await expect(page.locator('.notebook-input-source')).not.toHaveCount(0);
    await page.locator('.arena-cell .cm-content').first().fill("print('NO_SUBMISSION_YET')");
    async function commit() {
      await page.getByRole('button', { name: 'Save', exact: true }).click();
      const drawer = page.getByRole('dialog', { name: 'Save version', exact: true });
      await drawer.getByLabel('Version type', { exact: true }).selectOption('commit');
      const response = page.waitForResponse(
        (r) => /\/code\/\d+\/commits$/.test(r.url()) && r.request().method() === 'POST',
      );
      await drawer.getByRole('button', { name: 'Save', exact: true }).click();
      const queued = await response;
      expect(queued.status()).toBe(202);
      notebookId = Number(queued.url().match(/\/code\/(\d+)\//)![1]);
      await expect(drawer).toBeHidden();
    }
    await commit();
    await expect(page.locator('.commit-status')).toContainText('Commit failed:', {
      timeout: 90000,
    });
    expect(
      (await (await page.request.get('/api/code?competition_id=1&filter=your-work')).json()).items,
    ).toHaveLength(0);
    expect((await (await page.request.get(`/api/code/${notebookId}`)).json()).private).toBe(true);
    const code = `import os
from pathlib import Path
import pandas as pd
assert list(Path('input').rglob('*.csv'))
data = pd.read_csv(os.environ['ARENA_TEST_DATA'])
pd.DataFrame({'id': data['id'], 'prediction': 0}).to_csv(os.environ['ARENA_SUBMISSION_FILE'], index=False)
Path('model.txt').write_text('baseline')
print('FRESH_COMPETITION_RUN_OK', len(data))`;
    await page.locator('.arena-cell .cm-content').first().fill(code);
    await commit();
    await expect(page.locator('.commit-status')).toContainText('Evaluated · Score', {
      timeout: 90000,
    });
    const codes = (
      await (await page.request.get('/api/code?competition_id=1&filter=your-work')).json()
    ).items;
    expect(codes.map((row: { id: number }) => row.id)).toContain(notebookId);
    const publication = await (await page.request.get(`/api/code/${notebookId}`)).json();
    expect(JSON.stringify(publication.document.cells[0].outputs)).toContain(
      'FRESH_COMPETITION_RUN_OK',
    );
    expect(publication.document.cells[0].source).toBe(code);
    await page.locator('.arena-cell .cm-content').first().fill("print('PRIVATE_NEXT_EDIT')");
    await page
      .locator('.notebook-menubar')
      .getByRole('button', { name: 'File', exact: true })
      .click();
    await page.getByRole('menuitem', { name: 'Save notebook', exact: true }).click();
    await expect(page.locator('.arena-notebook-subbar')).toContainText('Saved');
    expect(
      (await (await page.request.get(`/api/code/${notebookId}`)).json()).document.cells[0].source,
    ).toBe(code);
  } finally {
    await page.request.delete('/api/notebook-session', { headers });
    if (notebookId) await page.request.delete(`/api/work/notebooks/${notebookId}`, { headers });
  }
});
