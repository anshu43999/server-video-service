import { expect, test } from '@playwright/test'
import { selectElementOption, toggleElementSwitch } from './helpers/navigation'

test.beforeEach(({}, info) => test.skip(info.project.name !== 'production-chromium', 'requires isolated real backend'))

for (const width of [1440, 390]) {
  test(`single-input scene creation stays consistent before and after member selection at ${width}px`, async ({ context, page }) => {
    test.setTimeout(90_000)
    expect((await context.request.post('/aiyoloapi/auth/login', {
      data: { username: `business-owner-scene${width}`, password: 'business-test-password' },
    })).ok()).toBe(true)
    const projectId = (await (await context.request.get('/aiyoloapi/auth/projects')).json()).projects[0].projectId
    const base = `/aiyoloapi/projects/${projectId}`
    const assignmentsBefore = await (await context.request.get(`${base}/model-assignments`)).json()
    await page.setViewportSize({ width, height: 960 })
    await page.goto(`/admin/scenes?project=${projectId}`)
    for (const kind of ['image', 'video'] as const) for (const order of ['before', 'after'] as const) {
      const sceneId = `input-${width}-${kind}-${order}`
      await page.getByRole('button', { name: '创建场景', exact: true }).click()
      const dialog = page.getByRole('dialog', { name: '创建项目场景', exact: true })
      await dialog.getByLabel('场景 ID', { exact: true }).fill(sceneId)
      await dialog.getByLabel('场景名称', { exact: true }).fill(`${kind === 'image' ? '图片' : '视频'}单输入场景`)
      const add = async () => {
        await selectElementOption(page, '项目模型', '安全帽检测 / 1.0.0 · PC 端', false)
        await dialog.getByRole('button', { name: '添加项目模型成员', exact: true }).click()
      }
      if (order === 'after') await add()
      await toggleElementSwitch(page, kind === 'image' ? '适用视频' : '适用图片')
      if (order === 'before') await add()
      const member = dialog.locator('.scene-member-inputs')
      await expect(member.getByRole('switch', { name: kind === 'image' ? '本机相机连续帧' : '图片', exact: true })).toBeDisabled()
      await expect(member.getByRole('switch', { name: kind === 'image' ? '图片' : '本机相机连续帧', exact: true })).toBeChecked()
      expect(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true)
      await page.screenshot({ path: `../evidence/M33/M33-T53/create-${width}-${kind}-${order}.png`, fullPage: true, animations: 'disabled' })
      const response = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === `${base}/scenes`)
      await dialog.getByRole('button', { name: '保存新场景', exact: true }).click()
      const saved = await response
      expect(saved.status(), await saved.text()).toBe(201)
      await expect(dialog).toHaveCount(0)
      const scene = await (await context.request.get(`${base}/scenes/${sceneId}`)).json()
      expect(scene).toMatchObject({ inputTypes: [kind], approved: false, revision: 1 })
      expect(scene.models).toHaveLength(1)
      expect(scene.models[0].inputTypes).toEqual([kind])
      expect(scene.plans[0].inputTypes).toEqual([kind])
    }
    expect(await (await context.request.get(`${base}/model-assignments`)).json()).toEqual(assignmentsBefore)
  })
}
