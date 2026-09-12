import { test, expect } from '@playwright/test';

test('home and notebook share navigation and Create menus stay anchored above panels', async ({
  page,
}) => {
  const headers = { 'X-Arena-Client': 'web' };
  await page.request.post('/api/auth/register', {
    headers,
    data: {
      username: `sidebar_${Date.now()}`,
      password: 'sidebar-test-password',
    },
  });
  try {
    await page.goto('/');
    const home = page.locator('.app > .sidebar');
    const labels = await home
      .locator('nav button')
      .evaluateAll((buttons) => buttons.map((button) => button.getAttribute('aria-label')));
    const homeWidth = (await home.boundingBox())!.width;
    const metrics = await home
      .getByRole('button', { name: 'Competitions', exact: true })
      .evaluate((button) => {
        const style = getComputedStyle(button);
        return [style.paddingLeft, style.fontSize, button.getBoundingClientRect().height];
      });
    async function checkMenu(sidebar: typeof home) {
      const trigger = sidebar.getByRole('button', { name: 'Create', exact: true });
      await trigger.click();
      const menu = page.getByRole('menu', { name: 'Create category' });
      await expect(menu).toBeVisible();
      const triggerBox = (await trigger.boundingBox())!;
      const menuBox = (await menu.boundingBox())!;
      expect(Math.abs(menuBox.y - triggerBox.y - triggerBox.height - 6)).toBeLessThan(2);
      expect(
        await menu.evaluate((element) => {
          const box = element.getBoundingClientRect();
          return (
            element.matches(':popover-open') &&
            element.contains(document.elementFromPoint(box.right - 15, box.top + 35))
          );
        }),
      ).toBe(true);
      return menu;
    }
    let menu = await checkMenu(home);
    await menu.getByRole('menuitem', { name: 'Notebook', exact: true }).click();
    const notebook = page.locator('.notebook-sidebar');
    await expect(notebook).toBeVisible();
    await notebook.getByRole('button', { name: 'Expand navigation', exact: true }).click();
    await expect.poll(async () => (await notebook.boundingBox())!.width).toBe(homeWidth);
    expect(
      await notebook
        .locator('nav button')
        .evaluateAll((buttons) => buttons.map((button) => button.getAttribute('aria-label'))),
    ).toEqual(labels);
    expect(
      await notebook
        .getByRole('button', { name: 'Competitions', exact: true })
        .evaluate((button) => {
          const style = getComputedStyle(button);
          return [style.paddingLeft, style.fontSize, button.getBoundingClientRect().height];
        }),
    ).toEqual(metrics);
    menu = await checkMenu(notebook);
    await page.keyboard.press('Escape');
    await expect(notebook.getByRole('button', { name: 'Create', exact: true })).toBeFocused();
    await notebook.getByRole('button', { name: 'Collapse navigation', exact: true }).click();
    await page.setViewportSize({ width: 390, height: 844 });
    menu = await checkMenu(notebook);
    expect((await menu.boundingBox())!.x + (await menu.boundingBox())!.width).toBeLessThanOrEqual(
      390,
    );
    await menu.getByRole('menuitem', { name: 'Dataset', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Share a dataset' })).toBeVisible();
    await expect(notebook).toHaveCount(0);
  } finally {
    await page.request.delete('/api/notebook-session', { headers });
  }
});
