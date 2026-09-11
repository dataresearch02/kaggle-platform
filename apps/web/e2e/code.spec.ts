import { test, expect } from '@playwright/test';

test('code list pages on scroll and filters bookmarks, owned and shared work', async ({
  page,
  browser,
}) => {
  const headers = { 'X-Arena-Client': 'web' };
  const username = `code_author_${Date.now()}`;
  await page.request.post('/api/auth/register', {
    headers,
    data: { username, password: 'browser-code-password' },
  });
  const codeIds: number[] = [];
  for (let n = 0; n < 42; n++) {
    const created = await page.request.post('/api/notebooks', {
      headers,
      data: { title: `Scroll sample ${username} ${n}`, code: 'print(42)' },
    });
    codeIds.push((await created.json()).id);
  }
  const pages: number[] = [];
  page.on('response', async (response) => {
    if (new URL(response.url()).pathname === '/api/code' && response.status() === 200) {
      const data = await response.json();
      pages.push(data.items.length);
      expect(data.items.every((item: object) => !('code' in item) && !('document' in item))).toBe(
        true,
      );
    }
  });
  await page.goto('/#notebooks');
  const searched = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/code' &&
      new URL(response.url()).searchParams.get('q') === username,
  );
  await page.getByLabel('Search codes', { exact: true }).fill(username);
  await searched;
  await expect(page.locator('.code-result-row')).toHaveCount(20);
  await page.locator('.code-load-more').scrollIntoViewIfNeeded();
  await expect(page.locator('.code-result-row')).toHaveCount(40);
  await page.locator('.code-load-more').scrollIntoViewIfNeeded();
  await expect(page.locator('.code-result-row')).toHaveCount(42);
  expect(pages.every((size) => size <= 20)).toBe(true);
  await page.locator('.code-result-row').first().getByRole('button').click();
  await page.getByRole('tab', { name: 'Bookmarks', exact: true }).click();
  await expect(page.locator('.code-result-row')).toHaveCount(1);
  await page.getByRole('tab', { name: 'Your work', exact: true }).click();
  await expect(page.locator('.code-result-row')).toHaveCount(20);
  await page.getByRole('tab', { name: 'Shared with you', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'No codes found' })).toBeVisible();
  const recipient = await browser.newContext();
  const other = await recipient.newPage();
  const recipientName = `code_recipient_${Date.now()}`;
  await other.request.post('/api/auth/register', {
    headers,
    data: { username: recipientName, password: 'browser-code-password' },
  });
  const id = codeIds[codeIds.length - 1];
  await page.goto(`/#code/${id}`);
  await page.getByRole('button', { name: 'Share with user' }).click();
  await page.getByLabel('Recipient username').fill(recipientName);
  await page.getByRole('button', { name: 'Share code', exact: true }).click();
  await expect(page.getByRole('status')).toContainText(`Shared with ${recipientName}`);
  await other.goto('/#notebooks');
  await other.getByRole('tab', { name: 'Shared with you', exact: true }).click();
  await expect(other.locator('.code-result-row')).toHaveCount(1);
  await other.locator('.code-result-row').getByRole('link').click();
  await expect(other.getByRole('link', { name: 'Edit my code' })).toHaveCount(0);
  await expect(other.locator('.cm-content')).toHaveAttribute('contenteditable', 'false');
  await expect(other.getByRole('button', { name: 'Run all', exact: true })).toHaveCount(0);
  await other.reload();
  await expect(other.getByRole('button', { name: 'Fork code', exact: true })).toBeVisible();
  await other.screenshot({ path: 'test-results/code-view-desktop.png', fullPage: true });
  await other.setViewportSize({ width: 390, height: 844 });
  expect(await other.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await other.screenshot({ path: 'test-results/code-view-mobile.png', fullPage: true });
  await recipient.close();
});

test('published viewer renders markdown, inputs and safe saved outputs without a kernel', async ({
  page,
}) => {
  const headers = { 'X-Arena-Client': 'web' };
  await page.request.post('/api/auth/register', {
    headers,
    data: { username: `code_view_${Date.now()}`, password: 'browser-code-password' },
  });
  const dataset = await (
    await page.request.post('/api/datasets', {
      headers,
      multipart: {
        title: 'Viewer input',
        description: 'Input for a published notebook',
        file: { name: 'input.csv', mimeType: 'text/csv', buffer: Buffer.from('x\n1\n') },
      },
    })
  ).json();
  await page.request.put(`/api/datasets/${dataset.id}/access`, {
    headers,
    data: { visibility: 'public' },
  });
  const created = await (
    await page.request.post('/api/notebooks', {
      headers,
      data: { title: 'Rendered notebook', code: 'print(42)' },
    })
  ).json();
  expect(
    (
      await page.request.put(`/api/code/${created.id}/publication`, {
        headers,
        data: {
          nbformat: 4,
          nbformat_minor: 5,
          metadata: { arena_inputs: [{ id: dataset.id }] },
          cells: [
            {
              id: 'notes',
              cell_type: 'markdown',
              source:
                '# Experiment result\n\n<h2>sdfsdf</h2>\n\n$x^2$\n\n<script>window.unsafeOutput=true</script><img src=x onerror="window.unsafeOutput=true">',
              metadata: {},
            },
            {
              id: 'code',
              cell_type: 'code',
              source: 'print(42)',
              execution_count: 1,
              metadata: {},
              outputs: [
                { output_type: 'stream', name: 'stdout', text: '42\n' },
                {
                  output_type: 'display_data',
                  data: {
                    'text/html':
                      '<img src=x onerror="window.unsafeOutput=true"><script>window.unsafeOutput=true</script><table><tr><td>Safe table</td></tr></table>',
                  },
                  metadata: {},
                },
              ],
            },
          ],
        },
      })
    ).status(),
  ).toBe(200);
  const runtimeRequests: string[] = [];
  page.on('request', (request) => {
    if (/\/api\/(editor|notebook-session)/.test(request.url())) runtimeRequests.push(request.url());
  });
  await page.goto(`/#code/${created.id}`);
  await expect(page.getByRole('heading', { name: 'Experiment result' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'sdfsdf', level: 2 })).toBeVisible();
  const outline = page.getByRole('navigation', { name: 'Notebook headings' });
  await expect(outline.getByRole('button')).toHaveCount(2);
  await outline.getByRole('button', { name: 'sdfsdf', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'sdfsdf', level: 2 })).toBeFocused();
  await expect(page).toHaveURL(new RegExp(`#code/${created.id}$`));
  await expect(page.locator('.notebook-markdown .katex')).toHaveCount(1);
  await expect(page.locator('.notebook-markdown script, .notebook-markdown [onerror]')).toHaveCount(
    0,
  );
  await expect(page.getByLabel('Published output cell 2')).toContainText('42');
  await expect(page.getByRole('cell', { name: 'Safe table' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Download input' })).toBeVisible();
  expect(
    await page.evaluate(() => (window as Window & { unsafeOutput?: boolean }).unsafeOutput),
  ).toBeUndefined();
  await page.getByRole('tab', { name: 'Input', exact: true }).click();
  await expect(page.getByRole('tabpanel', { name: 'Input', exact: true })).toContainText(
    'Viewer input',
  );
  await page.getByRole('tab', { name: 'Output', exact: true }).click();
  await expect(page.getByRole('tabpanel', { name: 'Output', exact: true })).toContainText('42');
  await page.getByRole('tab', { name: 'Logs', exact: true }).click();
  await expect(page.getByRole('tabpanel', { name: 'Logs', exact: true })).toContainText('42');
  await page.getByRole('tab', { name: 'Comments', exact: true }).click();
  await page.getByLabel('Write a comment').fill('A useful published notebook');
  await page.getByRole('button', { name: 'Post comment', exact: true }).click();
  await expect(page.locator('.code-comments article')).toContainText('A useful published notebook');
  await page.reload();
  await page.getByRole('tab', { name: 'Comments', exact: true }).click();
  await expect(page.locator('.code-comments article')).toContainText('A useful published notebook');
  const comment = page.locator('.code-comments > article').first();
  await comment.getByRole('button', { name: /Like 0/ }).click();
  await expect(comment.getByRole('button', { name: /Like 1/ })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await comment.getByRole('button', { name: 'Reply', exact: true }).click();
  await comment.getByLabel('Write a reply').fill('Thanks for the explanation');
  await comment.getByRole('button', { name: 'Post reply', exact: true }).click();
  await expect(comment.locator('.engagement-reply')).toContainText('Thanks for the explanation');
  await page.reload();
  await page.getByRole('tab', { name: 'Comments', exact: true }).click();
  await expect(comment.getByRole('button', { name: /Like 1/ })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await expect(comment.locator('.engagement-reply')).toContainText('Thanks for the explanation');
  await comment.getByRole('button', { name: /Like 1/ }).click();
  await expect(comment.getByRole('button', { name: /Like 0/ })).toHaveAttribute(
    'aria-pressed',
    'false',
  );
  await comment.getByRole('button', { name: 'Delete reply', exact: true }).click();
  await expect(comment.locator('.engagement-reply')).toHaveCount(0);
  await page.getByRole('button', { name: 'Delete comment', exact: true }).click();
  await expect(page.locator('.code-comments article')).toHaveCount(0);
  await page.getByRole('tab', { name: 'Notebook', exact: true }).click();
  await expect(page.getByRole('navigation', { name: 'Notebook headings' })).toBeVisible();
  expect(runtimeRequests).toEqual([]);
});

test('competition discussion posts support replies and reactions', async ({ page }) => {
  const headers = { 'X-Arena-Client': 'web' };
  await page.request.post('/api/auth/register', {
    headers,
    data: { username: `discussion_replies_${Date.now()}`, password: 'browser-password-123' },
  });
  await page.request.post('/api/competitions/1/join', { headers });
  const title = `Conversation ${Date.now()}`;
  await page.request.post('/api/competitions/1/discussion', {
    headers,
    data: { title, body: 'Share your approach' },
  });
  await page.goto('/#competitions/1/discussion');
  const post = page
    .locator('.competition-post')
    .filter({ has: page.getByRole('heading', { name: title }) });
  await post.getByRole('button', { name: /Helpful 0/ }).click();
  await post.getByRole('button', { name: 'Reply', exact: true }).click();
  await post.getByLabel('Write a reply').fill('Start with a baseline model');
  await post.getByRole('button', { name: 'Post reply', exact: true }).click();
  await expect(post.locator('.engagement-reply')).toContainText('Start with a baseline model');
  await page.reload();
  await expect(post.getByRole('button', { name: /Helpful 1/ })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await expect(post.locator('.engagement-reply')).toContainText('Start with a baseline model');
});
