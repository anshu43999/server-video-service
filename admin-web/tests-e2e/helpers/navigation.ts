import { test, type Page } from '@playwright/test'
import { fixtureProjectId } from './project-fixture'

// Run the same behaviors against Vite preview and FastAPI's formal build.
export function adminPath(path: string) {
  const scoped = !['/models', '/diagnostics', '/projects', '/login'].some(prefix => path.startsWith(prefix))
  return `${test.info().project.name === 'production-chromium' ? '/admin' : '/admin-next'}${path}${scoped ? `${path.includes('?') ? '&' : '?'}project=${fixtureProjectId}` : ''}`
}

function accessibleName(label: string, exact: boolean) {
  if (!exact) return label
  const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp(`^${escaped}(?:\\s|$)`)
}

export async function openElementSelect(page: Page, label: string, exact = true) {
  const control = page.getByRole('combobox', { name: accessibleName(label, exact) })
  await page.locator('.el-select__wrapper').filter({ has: control }).click()
}

export async function selectElementOption(page: Page, label: string, option: string, exact = true) {
  await openElementSelect(page, label, exact)
  await page.getByRole('option', { name: option, exact }).last().click()
}

export async function toggleElementSwitch(page: Page, label: string, exact = true) {
  const control = page.getByRole('switch', { name: accessibleName(label, exact) })
  await page.locator('.el-switch').filter({ has: control }).click()
}
