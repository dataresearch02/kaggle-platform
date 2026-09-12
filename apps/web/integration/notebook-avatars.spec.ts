import { test, expect } from '@playwright/test';

test('notebook authors use photos and team publishers use a photo mosaic', async ({ page }) => {
  await page.route('**/api/code?*', async (route) => {
    await route.fulfill({
      json: {
        items: [
          {
            id: 1,
            title: 'Personal notebook',
            owner_id: 1,
            owner: 'author',
            created_at: '2026-01-01',
            publisher: { kind: 'user', name: 'author', members: ['author'] },
          },
          {
            id: 2,
            title: 'Team notebook',
            owner_id: 2,
            owner: 'author',
            created_at: '2026-01-01',
            publisher: { kind: 'team', name: 'Research team', members: ['author', 'teammate'] },
          },
        ],
        next_cursor: null,
      },
    });
  });
  await page.goto('/#notebooks');
  const rows = page.locator('.code-result-row');
  await expect(rows).toHaveCount(2);
  await expect(rows.first().locator('.notebook-author-avatar img')).toHaveCount(1);
  await expect(rows.last().locator('.notebook-author-avatar img')).toHaveCount(2);
  await expect(rows.last()).toContainText('By Research team');
  await expect(rows.last().locator('.notebook-author-avatar')).toHaveClass(/members-2/);
  for (const photo of await page.locator('.notebook-author-avatar img').all()) {
    await expect
      .poll(() => photo.evaluate((image: HTMLImageElement) => image.naturalWidth))
      .toBeGreaterThan(0);
  }
  await page.screenshot({ path: '/tmp/arena-notebook-avatars.png' });
});
