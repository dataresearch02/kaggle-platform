import { test, expect } from '@playwright/test';

test('responsive navigation preserves content width and reduced motion disables effects', async ({
  page,
}) => {
  await page.goto('/');
  await expect(page.locator('h1')).toBeVisible();
  const sidebar = page.locator('.app > .sidebar');
  const shell = page.locator('.app > .main-shell');
  const font = await page
    .locator('body')
    .evaluate((element) => getComputedStyle(element).fontFamily);
  await expect(sidebar.getByRole('button', { name: 'Competitions', exact: true })).toHaveCSS(
    'font-family',
    font,
  );
  await expect(page.locator('h1')).toHaveCSS('font-family', font);
  for (const width of [1440, 900, 651]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const action of ['Collapse navigation', 'Expand navigation']) {
      await sidebar.getByRole('button', { name: action, exact: true }).click();
      await expect
        .poll(async () => {
          const bounds = await shell.boundingBox();
          return Math.abs(bounds!.x + bounds!.width - width);
        })
        .toBeLessThan(1);
    }
  }
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await expect(sidebar).toHaveCSS('transition-duration', '0s');
  await sidebar.getByRole('button', { name: 'Create', exact: true }).click();
  await expect(page.getByRole('menu', { name: 'Create category' })).toHaveCSS(
    'animation-name',
    'none',
  );
  await page.keyboard.press('Escape');
  await expect(sidebar.getByRole('button', { name: 'Create', exact: true })).toBeFocused();
  for (const width of [650, 390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
      .toBeLessThanOrEqual(width);
    const learning = await page
      .getByRole('button', { name: 'Start learning', exact: true })
      .boundingBox();
    expect(learning!.x + learning!.width).toBeLessThanOrEqual(width);
    await page.screenshot({ path: `test-results/design-${width}.png`, fullPage: false });
  }
});
