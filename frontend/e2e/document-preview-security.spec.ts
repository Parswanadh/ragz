import { expect, test, type Page } from '@playwright/test';

const FILE_PATH = /\/api\/v1\/documents\/[^/]+\/file$/;

async function mountPreview(
  page: Page,
  { filename, contentType, body }: { filename: string; contentType: string; body: string | Buffer },
): Promise<void> {
  await page.route(FILE_PATH, async (route) => {
    await route.fulfill({ status: 200, contentType, body });
  });
  await page.goto('/e2e/preview-harness.html');
  await page.evaluate((name) => {
    window.__ragzPreviewExecuted = false;
    window.mountDocumentPreview(name);
  }, filename);
  await expect(page.getByRole('heading', { name: filename })).toBeVisible();
}

test('synthetic active HTML and SVG cannot execute or access the parent', async ({ page }) => {
  const payload =
    '<!doctype html><script>parent.__ragzPreviewExecuted=true</script>' +
    '<svg xmlns="http://www.w3.org/2000/svg"><script>parent.__ragzPreviewExecuted=true</script></svg>';
  await mountPreview(page, {
    filename: 'legacy.html',
    contentType: 'text/html',
    body: payload,
  });

  await expect(page.getByText("This file type can't be previewed")).toBeVisible();
  await expect(page.locator('iframe')).toHaveCount(0);
  await expect(page.getByRole('link', { name: /open in new tab/i })).toHaveCount(0);
  expect(await page.evaluate(() => window.__ragzPreviewExecuted)).toBe(false);
});

test('synthetic script markup in plain text is rendered literally', async ({ page }) => {
  const payload = '<script>parent.__ragzPreviewExecuted=true</script>';
  await mountPreview(page, {
    filename: 'notes.txt',
    contentType: 'text/plain; charset=utf-8',
    body: payload,
  });

  await expect(page.locator('pre')).toHaveText(payload);
  await expect(page.locator('iframe')).toHaveCount(0);
  expect(await page.evaluate(() => window.__ragzPreviewExecuted)).toBe(false);
});

test('PDF preview frame is sandboxed without script or same-origin privileges', async ({
  page,
}) => {
  await mountPreview(page, {
    filename: 'manual.pdf',
    contentType: 'application/pdf',
    body: Buffer.from('%PDF-1.7\n%%EOF\n'),
  });

  const frame = page.locator('iframe[title="manual.pdf"]');
  await expect(frame).toHaveAttribute('sandbox', '');
  await expect(frame).not.toHaveAttribute('sandbox', /allow-scripts|allow-same-origin/);
  expect(await page.evaluate(() => window.__ragzPreviewExecuted)).toBe(false);
});
