import { test, expect } from '@playwright/test';

test('CPU worker cancels work and runs without database credentials or external networking', async ({
  page,
}) => {
  const headers = { 'X-Arena-Client': 'web' };
  await page.request.post('/api/auth/register', {
    headers,
    data: { username: `cpu_job_${Date.now()}`, password: 'cpu-evaluation-password' },
  });
  await page.request.post('/api/competitions/1/join', { headers });
  async function create(code: string) {
    const row = await (
      await page.request.post('/api/notebooks', {
        headers,
        data: { title: 'CPU worker acceptance', code },
      })
    ).json();
    const response = await page.request.post(`/api/code/${row.id}/commits`, {
      headers,
      data: { competition_id: 1 },
    });
    expect(response.status()).toBe(202);
    return { notebook: row.id, job: (await response.json()).id };
  }
  const waiting = await create('import time\ntime.sleep(90)');
  const latest = async (id: number) =>
    (await page.request.get(`/api/code/${id}/commits/latest`)).json();
  await expect.poll(async () => (await latest(waiting.notebook)).status).toBe('running');
  const cancel = await page.request.post(
    `/api/code/${waiting.notebook}/commits/${waiting.job}/cancel`,
    { headers },
  );
  expect((await cancel.json()).status).toBe('cancelled');
  const completed = await create(`import os
from pathlib import Path
assert not any(key.startswith('POSTGRES_') or key in ('DATABASE_URL', 'JUPYTERHUB_API_TOKEN') for key in os.environ)
assert not Path('/var/run/docker.sock').exists()
assert set(os.listdir('/sys/class/net')) == {'lo'}
Path(os.environ['ARENA_SUBMISSION_FILE']).write_text('id,prediction\\n7,240\\n8,100\\n9,300\\n')
print('ISOLATED_CPU_OK')`);
  await expect
    .poll(async () => (await latest(completed.notebook)).status, { timeout: 60000 })
    .toBe('succeeded');
  expect((await latest(completed.notebook)).score).toBe(0);
  expect((await latest(waiting.notebook)).status).toBe('cancelled');
  expect((await (await page.request.get(`/api/code/${waiting.notebook}`)).json()).private).toBe(
    true,
  );
});
