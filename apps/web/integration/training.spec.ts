import { test, expect } from '@playwright/test';

test('CPU frameworks train from the editor, preserve checkpoints and run in isolated commits', async ({
  page,
}) => {
  test.setTimeout(240000);
  const headers = { 'X-Arena-Client': 'web' };
  await page.request.post('/api/auth/register', {
    headers,
    data: { username: `training_${Date.now()}`, password: 'training-browser-password' },
  });
  const created = await page.request.post('/api/notebooks', {
    headers,
    data: { title: 'CPU framework training check', code: '# Training examples' },
  });
  const notebook = await created.json();
  try {
    await page.goto(`/#code/${notebook.id}/edit`);
    await expect(page.getByRole('button', { name: 'Run all', exact: true })).toBeEnabled({
      timeout: 120000,
    });
    await page
      .locator('.arena-cell .cm-content')
      .first()
      .fill(
        '%run /opt/arena/examples/pytorch_training.py --output-dir models/pytorch\n%run /opt/arena/examples/xgboost_training.py --output-dir models/xgboost',
      );
    await page.getByRole('button', { name: 'Run all', exact: true }).click();
    for (const framework of ['PyTorch', 'XGBoost']) {
      await expect(
        page.getByLabel(/^Output cell /).filter({ hasText: `${framework} validation accuracy:` }),
      ).toBeVisible({ timeout: 60000 });
    }
    await expect(page.getByRole('button', { name: 'Run all', exact: true })).toBeEnabled();
    await page
      .locator('.notebook-menubar')
      .getByRole('button', { name: 'File', exact: true })
      .click();
    await page.getByRole('menuitem', { name: 'Save notebook', exact: true }).click();
    await expect(page.locator('.arena-notebook-subbar')).toContainText('Saved');
    page.once('dialog', (dialog) => dialog.accept());
    await page
      .locator('.notebook-menubar')
      .getByRole('button', { name: 'Run', exact: true })
      .click();
    await page
      .getByRole('menuitem', { name: 'Save and restart notebook server', exact: true })
      .click();
    await expect(page.getByRole('button', { name: 'Run all', exact: true })).toBeEnabled({
      timeout: 120000,
    });
    await expect(page.getByRole('button', { name: 'Run all', exact: true })).toBeVisible({
      timeout: 120000,
    });
    await page.getByRole('button', { name: 'Code', exact: true }).click();
    await page.locator('.arena-cell .cm-content').last().fill(`import json
from pathlib import Path
import torch
import xgboost as xgb
checkpoint = torch.load('models/pytorch/model.pt', map_location='cpu', weights_only=True)
assert checkpoint['epochs'] == 100
model = xgb.XGBClassifier(n_jobs=2)
model.load_model('models/xgboost/model.ubj')
for framework in ('pytorch', 'xgboost'):
    metrics = json.loads(Path(f'models/{framework}/metrics.json').read_text())
    assert metrics['reload_verified'] and metrics['validation_accuracy'] > 0.75
print('CHECKPOINTS_SURVIVED_SERVER_RECREATION')`);
    await page.getByRole('button', { name: 'Run cell', exact: true }).click();
    await expect(
      page
        .getByLabel(/^Output cell /)
        .filter({ hasText: 'CHECKPOINTS_SURVIVED_SERVER_RECREATION' }),
    ).toBeVisible({ timeout: 60000 });
    await page.request.post('/api/competitions/1/join', { headers });
    const jobNotebook = await (
      await page.request.post('/api/notebooks', {
        headers,
        data: {
          title: 'Isolated framework acceptance',
          code: `import os, runpy
from pathlib import Path
for name in ('pytorch', 'xgboost'):
    metrics = runpy.run_path('/opt/arena/examples/' + name + '_training.py')['train']()
    assert metrics['reload_verified'] and metrics['validation_accuracy'] > 0.75
assert set(os.listdir('/sys/class/net')) == {'lo'}
Path(os.environ['ARENA_SUBMISSION_FILE']).write_text('id,prediction\\n7,240\\n8,100\\n9,300\\n')
print('ISOLATED_FRAMEWORK_TRAINING_OK')`,
        },
      })
    ).json();
    const commit = await page.request.post(`/api/code/${jobNotebook.id}/commits`, {
      headers,
      data: { competition_id: 1 },
    });
    expect(commit.status()).toBe(202);
    await expect
      .poll(
        async () =>
          (await (await page.request.get(`/api/code/${jobNotebook.id}/commits/latest`)).json())
            .status,
        { timeout: 120000 },
      )
      .toBe('succeeded');
    const publication = await (await page.request.get(`/api/code/${jobNotebook.id}`)).json();
    expect(
      JSON.stringify(
        publication.document.cells.flatMap((cell: { outputs?: unknown[] }) => cell.outputs || []),
      ),
    ).toContain('ISOLATED_FRAMEWORK_TRAINING_OK');
  } finally {
    await page.request.delete('/api/notebook-session', { headers });
  }
});
