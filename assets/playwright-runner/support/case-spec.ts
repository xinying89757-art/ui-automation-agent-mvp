import type { Page } from '@playwright/test';
import { openLlms, openSettings } from '../flows/llms-txt.mjs';

export async function openTarget(page: Page, target: string) {
  if (target === 'settings') return openSettings(page);
  if (target === 'llms') return openLlms(page);
  throw new Error('UIA_EXPLORATION_REQUIRED: unknown open handler');
}
