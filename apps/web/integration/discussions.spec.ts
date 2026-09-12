import { test, expect } from '@playwright/test';

test('topics use a shared list, creation sidebar and rich comments inside competitions', async ({
  page,
}) => {
  const headers = { 'X-Arena-Client': 'web' };
  const title = `Discussion panel ${Date.now()}`;
  await page.request.post('/api/auth/register', {
    headers,
    data: { username: `discussion_${Date.now()}`, password: 'discussion-test-password' },
  });
  const photo = await page.request.put('/api/account/avatar', {
    headers,
    multipart: {
      file: {
        name: 'avatar.png',
        mimeType: 'image/png',
        buffer: Buffer.from(
          'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=',
          'base64',
        ),
      },
    },
  });
  expect(photo.ok()).toBeTruthy();
  const competition = await (
    await page.request.post('/api/competitions', {
      headers,
      multipart: {
        title: 'Discussion interface test',
        description: 'Test discussion ownership and navigation',
        deadline: '2099-01-01T00:00:00Z',
        test_file: {
          name: 'test.csv',
          mimeType: 'text/csv',
          buffer: Buffer.from('id,value\na,1\n'),
        },
        solution_file: {
          name: 'answers.csv',
          mimeType: 'text/csv',
          buffer: Buffer.from('id,prediction\na,2\n'),
        },
      },
    })
  ).json();
  expect(competition.id).toBeTruthy();
  await page.goto(`/#competitions/${competition.id}/discussion`);
  await page.getByRole('button', { name: 'New discussion', exact: true }).click();
  const drawer = page.getByRole('dialog', { name: 'Create discussion' });
  await expect(drawer).toBeVisible();
  const box = await drawer.boundingBox();
  expect(box!.x).toBeGreaterThan(0);
  await drawer.getByLabel('Title', { exact: true }).fill(title);
  await drawer
    .getByLabel('Discussion message', { exact: true })
    .fill('## Shared thread\n\n**A formatted topic**');
  await drawer.getByRole('button', { name: 'Insert table', exact: true }).click();
  await drawer.getByRole('button', { name: 'Post discussion', exact: true }).click();
  await expect(drawer).toHaveCount(0);
  const detail = page.getByRole('region', { name: 'Discussion details' });
  await expect(detail.getByRole('heading', { name: title, exact: true })).toBeVisible();
  await expect(detail.getByRole('table')).toBeVisible();
  await expect(page.getByRole('button', { name: 'New discussion', exact: true })).toHaveCount(0);
  await detail.getByRole('button', { name: 'Pin discussion', exact: true }).click();
  await expect(detail.getByRole('button', { name: 'Unpin discussion', exact: true })).toBeVisible();
  await detail.getByRole('button', { name: 'Bookmark discussion', exact: true }).click();
  await expect(
    detail.getByRole('button', { name: 'Bookmark discussion', exact: true }),
  ).toHaveAttribute('aria-pressed', 'true');
  const body = detail.getByLabel('Comment message', { exact: true });
  await body.fill('**First comment** with a [link](https://example.com).');
  await detail.getByLabel('Comment message image', { exact: true }).setInputFiles({
    name: 'plot.png',
    mimeType: 'image/png',
    buffer: Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=',
      'base64',
    ),
  });
  await expect(body).toHaveValue(/\/api\/competition-discussions\/images\//);
  await detail.getByRole('button', { name: 'Post comment', exact: true }).click();
  await expect(detail.locator('.discussion-comment')).toHaveCount(1);
  await expect(detail.locator('.discussion-comment .notebook-markdown img')).toHaveJSProperty(
    'naturalWidth',
    1,
  );
  await expect(
    detail.locator('.discussion-comment strong').filter({ hasText: 'First comment' }),
  ).toBeVisible();
  await body.fill('Second comment');
  await detail.getByRole('button', { name: 'Post comment', exact: true }).click();
  await expect(detail.locator('.discussion-comment')).toHaveCount(2);
  const avatars = detail.locator('.discussion-comment .discussion-avatar img');
  await expect(avatars).toHaveCount(2);
  await expect(avatars.first()).toHaveJSProperty('naturalWidth', 1);
  const composerBox = await detail.locator('.discussion-comments form').boundingBox();
  const commentBox = await detail.locator('.discussion-comment').first().boundingBox();
  expect(composerBox!.y + composerBox!.height).toBeLessThanOrEqual(commentBox!.y);
  const parent = detail.locator('.discussion-comment').first();
  await parent.getByRole('button', { name: 'Reply', exact: true }).click();
  await parent.getByLabel('Write a reply', { exact: true }).fill('**A nested reply**');
  await parent.getByRole('button', { name: 'Post reply', exact: true }).click();
  await expect(parent.locator('.engagement-reply')).toContainText('A nested reply');
  const canonical = page.url();
  await page.reload();
  await expect(page.locator('.discussion-comment')).toHaveCount(2);
  await expect(
    page.locator('.discussion-comment').first().locator('.engagement-reply'),
  ).toContainText('A nested reply');
  await page.goto('/#discussions');
  await page.getByRole('button', { name: 'Bookmarks', exact: true }).click();
  const pinned = page.getByRole('region', { name: 'Pinned topics', exact: true });
  await expect(pinned).toContainText(title);
  await expect(page.locator('.discussion-list')).not.toContainText('Discussion interface test');
  await expect(pinned.locator('.discussion-avatar img')).toHaveJSProperty('naturalWidth', 1);
  await expect(pinned).toContainText('2 comments');
  await page.getByRole('combobox', { name: 'Sort discussions' }).selectOption('comments');
  await page
    .getByRole('link')
    .filter({ has: page.getByRole('heading', { name: title, exact: true }) })
    .click();
  await expect(page).toHaveURL(canonical);
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.locator('.discussion-comment')).toHaveCount(2);
  await page.goto(`/#competitions/${competition.id}/discussion`);
  await expect(page.getByRole('region', { name: 'Pinned topics' })).toContainText(title);
  await page.request.put('/api/account/profile', { headers, data: { pronouns: 'she/her' } });
  await page.request.delete('/api/account/avatar', { headers });
  await page.reload();
  const defaultPhoto = page.locator('.discussion-topic-row .discussion-avatar img').first();
  await expect(defaultPhoto).toBeVisible();
  await expect
    .poll(() => defaultPhoto.evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBeGreaterThan(0);
  const fallbackResponse = await page.request.get((await defaultPhoto.getAttribute('src'))!);
  expect(await fallbackResponse.text()).toContain('Default woman avatar');
  await page.screenshot({ path: '/tmp/arena-discussion-topics.png' });
});
