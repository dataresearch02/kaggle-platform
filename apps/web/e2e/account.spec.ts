import { test, expect } from '@playwright/test';

const headers = { 'X-Arena-Client': 'web' };
test('avatar drawer manages profiles, photos, groups, tokens, settings and notifications', async ({
  page,
}) => {
  const username = `account_${Date.now()}`;
  await page.request.post('/api/auth/register', {
    headers,
    data: { username, password: 'account-password-123' },
  });
  await page.goto('/');
  const trigger = page.getByRole('button', { name: 'Open user menu' });
  await expect(trigger).toBeVisible();
  await expect(trigger).toHaveText('');
  await expect(
    page.locator('.account').getByRole('button', { name: /log out|sign out/i }),
  ).toHaveCount(0);
  await trigger.click();
  const drawer = page.getByRole('dialog', { name: 'Your account', exact: true });
  await expect(drawer).toBeVisible();
  await expect(drawer).toContainText(username);
  await expect(drawer.getByRole('heading', { name: 'Welcome to Arena' })).toBeVisible();
  await drawer.getByRole('button', { name: 'Mark as read' }).click();
  await expect(drawer).toContainText('0 unread');
  const box = (await drawer.boundingBox())!;
  expect(Math.abs(box.x + box.width - 1440)).toBeLessThan(2);
  await drawer.getByRole('button', { name: 'Your profile', exact: true }).click();
  await expect(page).toHaveURL(/#account\/profile$/);
  await page.getByLabel('Display name', { exact: true }).fill('Notebook Researcher');
  await page.getByLabel('Tagline', { exact: true }).fill('Learning from data');
  await page.getByLabel('About you', { exact: true }).fill('My research notebook collection.');
  await page.getByRole('button', { name: 'Save profile', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('Profile saved');
  await page.getByLabel('Upload photo').setInputFiles({
    name: 'photo.png',
    mimeType: 'image/png',
    buffer: Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6p1sAAAAASUVORK5CYII=',
      'base64',
    ),
  });
  await expect(page.getByRole('status')).toContainText('Profile photo updated');
  await expect(trigger.locator('img')).toBeVisible();
  await page.reload();
  await expect(page.getByLabel('Display name', { exact: true })).toHaveValue('Notebook Researcher');
  await page.getByRole('link', { name: 'View your public profile' }).click();
  await expect(page.locator('.public-profile')).toContainText('My research notebook collection.');
  await trigger.click();
  await expect(drawer).toContainText('Notebook Researcher');
  await expect(drawer).toContainText('0 unread');
  await drawer.getByRole('button', { name: 'Your groups', exact: true }).click();
  await page.getByLabel('Group name', { exact: true }).fill('Research circle');
  await page.getByLabel('Description', { exact: true }).fill('A group for experiments');
  await page.getByRole('button', { name: 'Create group', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Research circle' })).toBeVisible();
  await expect(page.locator('.group-invite')).toContainText('Invite code:');
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Research circle' })).toBeVisible();
  await trigger.click();
  await drawer.getByRole('button', { name: 'Your API tokens', exact: true }).click();
  await page.getByLabel('Token name', { exact: true }).fill('CLI read access');
  await page.getByRole('button', { name: 'Create API token', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Copy your token now' })).toBeVisible();
  const token = (await page.locator('.token-secret code').textContent())!;
  expect(
    (
      await page.request.get('/api/work', { headers: { Authorization: `Bearer ${token}` } })
    ).status(),
  ).toBe(200);
  await page.reload();
  await expect(page.locator('.token-secret')).toHaveCount(0);
  await expect(page.locator('.account-row')).toContainText('CLI read access');
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'Revoke', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('Token revoked');
  expect(
    (
      await page.request.get('/api/work', { headers: { Authorization: `Bearer ${token}` } })
    ).status(),
  ).toBe(401);
  await trigger.click();
  await drawer.getByRole('button', { name: 'Settings', exact: true }).click();
  await page.getByLabel('Who can see your profile?').selectOption('private');
  await page.getByRole('button', { name: 'Save settings', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('Settings saved');
  await trigger.click();
  await drawer.getByRole('button', { name: 'Your work', exact: true }).click();
  await expect(page).toHaveURL(/#work$/);
  await trigger.click();
  await drawer.getByRole('button', { name: 'Log out', exact: true }).click();
  await expect(
    page.locator('.account').getByRole('button', { name: 'Sign in', exact: true }),
  ).toBeVisible();
  expect((await page.request.get(`/api/profiles/${username}`)).status()).toBe(404);
});

test('account drawer fits mobile and closes with Escape and backdrop', async ({ page }) => {
  await page.request.post('/api/auth/register', {
    headers,
    data: { username: `drawer_${Date.now()}`, password: 'account-password-123' },
  });
  await page.goto('/');
  const trigger = page.getByRole('button', { name: 'Open user menu' });
  await trigger.click();
  const drawer = page.getByRole('dialog', { name: 'Your account', exact: true });
  await expect(drawer).toBeVisible();
  await page.mouse.click(10, 200);
  await expect(drawer).not.toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await trigger.click();
  await expect(drawer).toBeVisible();
  await expect
    .poll(async () => {
      const box = (await drawer.boundingBox())!;
      return Math.round(box.x + box.width);
    })
    .toBe(390);
  expect(await drawer.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  await page.keyboard.press('Escape');
  await expect(drawer).not.toBeVisible();
  await expect(trigger).toBeFocused();
});
