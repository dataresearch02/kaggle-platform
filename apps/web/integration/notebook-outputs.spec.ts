import { test, expect } from '@playwright/test';

test('generated notebook file becomes a reusable input and survives a fork', async ({ page }) => {
  const producerTitle = `Reusable prediction producer ${Date.now()}`;
  const headers = { 'X-Arena-Client': 'web' };
  await page.request.post('/api/auth/register', {
    headers,
    data: { username: `outputs_${Date.now()}`, password: 'outputs-test-password' },
  });
  const producer = await (
    await page.request.post('/api/notebooks', {
      headers,
      data: {
        title: producerTitle,
        code: "from pathlib import Path\nPath('outputs').mkdir(exist_ok=True)\nPath('outputs/predictions.csv').write_text('value\\n42\\n')",
      },
    })
  ).json();
  const consumer = await (
    await page.request.post('/api/notebooks', {
      headers,
      data: { title: 'Reusable prediction consumer', code: 'print("Consumer ready")' },
    })
  ).json();
  try {
    await page.goto(`/#code/${producer.id}/edit`);
    await expect(page.getByRole('button', { name: 'Run all', exact: true })).toBeEnabled({
      timeout: 240000,
    });
    await page.getByRole('button', { name: 'Run all', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Run all', exact: true })).toBeEnabled({
      timeout: 130000,
    });
    await expect(page.getByRole('button', { name: 'Run all', exact: true })).toBeEnabled();
    await page
      .locator('.notebook-menubar')
      .getByRole('button', { name: 'File', exact: true })
      .click();
    await page.getByRole('menuitem', { name: 'Save notebook', exact: true }).click();
    await expect(page.locator('.notebook-save-state')).toHaveText('Saved permanently');
    await expect(
      page
        .locator('.notebook-panel')
        .getByRole('link', { name: 'outputs/predictions.csv', exact: true }),
    ).toBeVisible();
    const outputs = await (
      await page.request.get(`/api/notebook-outputs?notebook_id=${producer.id}`)
    ).json();
    const output = outputs.items[0];
    await page.goto(`/#code/${consumer.id}/edit`);
    await expect(page.getByRole('button', { name: 'Run all', exact: true })).toBeEnabled({
      timeout: 240000,
    });
    await page.getByRole('button', { name: 'Add Input', exact: true }).click();
    const picker = page.getByRole('dialog', { name: 'Add notebook input' });
    await picker.getByRole('button', { name: 'Notebooks', exact: true }).click();
    await picker.getByRole('button').filter({ hasText: producerTitle }).click();
    await expect(picker).toHaveCount(0);
    await expect(page.locator('.notebook-inputs')).toContainText(producerTitle);
    await page.getByRole('button', { name: `Remove ${producerTitle}`, exact: true }).click();
    await expect(page.locator('.notebook-inputs')).toHaveCount(0);
    await page.getByRole('button', { name: 'Add Input', exact: true }).click();
    await picker.getByRole('button').filter({ hasText: producerTitle }).click();
    await expect(picker).toHaveCount(0);
    await page.getByRole('button', { name: 'Run all', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Run all', exact: true })).toBeEnabled({
      timeout: 130000,
    });
    await expect(page.getByLabel('Output cell 2')).toContainText('42', { timeout: 130000 });
    await page
      .locator('.notebook-menubar')
      .getByRole('button', { name: 'File', exact: true })
      .click();
    await page.getByRole('menuitem', { name: 'Save notebook', exact: true }).click();
    await expect(page.locator('.notebook-save-state')).toHaveText('Saved permanently');
    const fork = await (
      await page.request.post(`/api/code/${consumer.id}/fork`, { headers })
    ).json();
    await page.goto(`/#code/${fork.id}/edit`);
    await expect(page.getByRole('button', { name: 'Run all', exact: true })).toBeEnabled({
      timeout: 240000,
    });
    await page.getByRole('button', { name: 'Run all', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Run all', exact: true })).toBeEnabled({
      timeout: 130000,
    });
    await expect(page.getByLabel('Output cell 2')).toContainText('42', { timeout: 130000 });
    await page.screenshot({ path: '/tmp/arena-notebook-output-input.png' });
    expect(
      (
        await page.request.put(`/api/code/${producer.id}/share-settings`, {
          headers,
          data: { visibility: 'public', usernames: [], allow_comments: true },
        })
      ).status(),
    ).toBe(200);
    await page.request.post('/api/competitions/1/join', { headers });
    const job = await (
      await page.request.post('/api/notebooks', {
        headers,
        data: { title: 'Isolated output consumer', code: 'print(42)' },
      })
    ).json();
    const grouped = await (
      await page.request.post(
        `/api/editor/notebooks/${job.id}/input-sources/notebook/${producer.id}`,
        { headers },
      )
    ).json();
    const model = await (
      await page.request.post('/api/models', {
        headers,
        data: {
          title: 'Reusable model weights',
          description: 'Test model artifacts',
          framework: 'PyTorch',
          license: 'MIT',
        },
      })
    ).json();
    const weights = await page.request.post(`/api/assets/models/${model.id}`, {
      headers,
      multipart: {
        path: 'weights.bin',
        file: {
          name: 'weights.bin',
          mimeType: 'application/octet-stream',
          buffer: Buffer.from('saved weights'),
        },
      },
    });
    expect(weights.status()).toBe(201);
    const modelInput = await (
      await page.request.post(`/api/editor/notebooks/${job.id}/input-sources/model/${model.id}`, {
        headers,
      })
    ).json();
    const document = {
      nbformat: 4,
      nbformat_minor: 5,
      metadata: { arena_input_sources: [grouped, modelInput] },
      cells: [
        {
          id: 'check-input',
          cell_type: 'code',
          metadata: {},
          execution_count: null,
          outputs: [],
          source: `from pathlib import Path
assert Path(${JSON.stringify(modelInput.files[0].path)}).read_bytes() == b'saved weights'
assert Path(${JSON.stringify(grouped.files[0].path)}).read_text() == 'value\\n42\\n'
Path('submission.csv').write_text('id,prediction\\n7,240\\n8,100\\n9,300\\n')
print('NOTEBOOK_OUTPUT_INPUT_OK')`,
        },
      ],
    };
    expect(
      (
        await page.request.put(`/api/editor/notebooks/${job.id}/document`, {
          headers,
          data: document,
        })
      ).status(),
    ).toBe(200);
    expect(
      (
        await page.request.post(`/api/code/${job.id}/commits`, {
          headers,
          data: { competition_id: 1 },
        })
      ).status(),
    ).toBe(202);
    await expect
      .poll(
        async () =>
          (await (await page.request.get(`/api/code/${job.id}/commits/latest`)).json()).status,
        { timeout: 120000 },
      )
      .toBe('succeeded');
    await expect
      .poll(async () =>
        (
          await (await page.request.get(`/api/notebook-outputs?notebook_id=${job.id}`)).json()
        ).items.map((item: { filename: string }) => item.filename),
      )
      .toEqual(['submission.csv']);
  } finally {
    await page.request.delete('/api/notebook-session', { headers });
  }
});

test('first draft save captures files and retains its execution folder', async ({ request }) => {
  const headers = { 'X-Arena-Client': 'web' };
  await request.post('/api/auth/register', {
    headers,
    data: { username: `draft_files_${Date.now()}`, password: 'draft-files-password' },
  });
  const draft = await (await request.post('/api/notebook-drafts', { headers })).json();
  try {
    await request.post('/api/notebook-session', { headers });
    await expect
      .poll(async () => (await (await request.get('/api/notebook-session')).json()).state, {
        timeout: 120000,
      })
      .toBe('ready');
    await request.get(`/api/editor/drafts/${draft.id}/document`);
    const code = "from pathlib import Path\nPath('saved.csv').write_text('value\\n17\\n')";
    const document = {
      nbformat: 4,
      nbformat_minor: 5,
      metadata: {},
      cells: [
        {
          id: 'write',
          cell_type: 'code',
          metadata: {},
          source: code,
          outputs: [],
          execution_count: null,
        },
      ],
    };
    expect(
      (
        await request.put(`/api/editor/drafts/${draft.id}/document`, { headers, data: document })
      ).status(),
    ).toBe(200);
    const run = await request.post(`/api/editor/drafts/${draft.id}/execute`, {
      headers,
      data: { code },
      timeout: 150000,
    });
    expect(await run.text()).toContain('"type": "done"');
    const saved = await (
      await request.post(`/api/notebook-drafts/${draft.id}/save`, {
        headers,
        data: { title: 'Permanent draft files' },
      })
    ).json();
    expect(saved.id).toBeTruthy();
    const outputs = await (
      await request.get(`/api/notebook-outputs?notebook_id=${saved.id}`)
    ).json();
    expect(outputs.items[0].filename).toBe('saved.csv');
    await request.delete(`/api/notebook-drafts/${draft.id}`, { headers });
    const rerun = await request.post(`/api/editor/notebooks/${saved.id}/execute`, {
      headers,
      data: { code: "from pathlib import Path\nprint(Path('saved.csv').read_text())" },
      timeout: 150000,
    });
    expect(await rerun.text()).toContain('17');
  } finally {
    await request.delete('/api/notebook-session', { headers });
  }
});
