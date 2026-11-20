import { expect, test } from '@playwright/test'
import { fixtureProject, fixtureUser, unscopedPath } from './helpers/project-fixture'
import { adminPath, selectElementOption } from './helpers/navigation'

for (const width of [1440, 768, 390, 320]) {
  test(`simple create preserves drafts, defaults and advanced settings at ${width}px`, async ({ context, page }, info) => {
    const project = { ...fixtureProject, capabilities: [...fixtureProject.capabilities, 'project.scenes.manage'] }
    const writes: {path:string;body:any}[] = [], errors:string[] = []
    page.on('pageerror', error => errors.push(error.message))
    await context.routeWebSocket('**/aiyoloapi/**', () => {})
    const models = ['helmet', 'phone'].map(modelId => {
      const assignment = { projectModelId: `simple-${modelId}`, modelId, modelVersion: '2.0.0', target: 'mobile',
        parameterPlatform: 'android', parameterRevision: 2,
        parameterPublished: true, enabled: true, revision: 1 }
      return { modelId, version: '2.0.0', name: modelId === 'helmet' ? '安全帽检测' : '手机检测', inputTypes: ['image','video'],
        assignment, assignments: [assignment], effectiveParametersByTarget: {} }
    })
    await context.route('**/aiyoloapi/**', async route => {
      const path = unscopedPath(new URL(route.request().url()).pathname)
      const reply = (json:unknown,status=200) => route.fulfill({json,status})
      if(route.request().method()!=='GET') {
        writes.push({path,body:route.request().postDataJSON()})
        if(path.endsWith('/scenes')&&route.request().method()==='POST')return reply({...writes.at(-1)!.body,approved:false,revision:1},201)
        return route.abort()
      }
      if(path.endsWith('/auth/status'))return reply({authenticated:true,setupRequired:false,user:fixtureUser()})
      if(path.endsWith('/auth/me'))return reply(fixtureUser())
      if(path.endsWith('/auth/projects'))return reply({contractVersion:'m33-v1',projects:[project]})
      if(path==='/aiyoloapi')return reply(project)
      if(path.endsWith('/scenes'))return reply({scenes:[]})
      if(path.endsWith('/models'))return reply({models})
      return reply({},404)
    })
    await page.setViewportSize({width,height:960})
    await page.goto(adminPath('/scenes'))
    await page.getByRole('button',{name:'创建场景',exact:true}).click()
    const dialog=page.getByRole('dialog',{name:'创建项目场景',exact:true})
    await expect(dialog.getByRole('button',{name:'高级设置（可选）'})).toHaveAttribute('aria-expanded','false')
    await expect(dialog.getByLabel('场景 ID',{exact:true})).toBeHidden()
    await expect(dialog.getByLabel('方案 ID',{exact:true})).toHaveCount(0)
    await dialog.getByLabel('场景名称',{exact:true}).fill('工地安全巡检')
    await selectElementOption(page,'项目模型','安全帽检测 / 2.0.0 · 移动端（Android）',false)
    await expect(dialog.locator('.scene-members.editable>li')).toHaveCount(1)
    await selectElementOption(page,'项目模型','手机检测 / 2.0.0 · 移动端（Android）',false)
    await expect(dialog.locator('.scene-members.editable>li')).toHaveCount(2)
    await expect(dialog.getByText('默认联合识别 · 2 个模型',{exact:true})).toBeVisible()
    await expect(dialog.getByRole('button',{name:'保存新场景',exact:true})).toBeEnabled()
    await expect(dialog.locator('.scene-joint-warning')).toHaveCount(0)
    expect(writes).toHaveLength(0)
    const summary=dialog.getByRole('region',{name:'创建配置摘要',exact:true})
    await expect(summary).toContainText('同一张照片')
    const mode=width===768||width===320?'async':'sync'
    if(mode==='async')await selectElementOption(page,'联合执行方式','异步',true)
    await expect(dialog.getByRole('button',{name:'保存新场景',exact:true})).toBeEnabled()
    await expect(dialog.getByLabel('方案 ID',{exact:true})).toBeHidden()
    await expect(dialog.getByText('创建后为待批准状态',{exact:false})).toBeVisible()
    const autoId=await dialog.getByLabel('场景 ID',{exact:true}).inputValue()
    expect(autoId).toMatch(/^scene-[a-f0-9-]{36}$/)
    await dialog.getByRole('button',{name:'刷新项目模型状态',exact:true}).click()
    await expect(dialog.getByLabel('场景名称',{exact:true})).toHaveValue('工地安全巡检')
    await expect(dialog.locator('.scene-members.editable>li')).toHaveCount(2)
    expect(await dialog.evaluate(node=>node.scrollWidth<=node.clientWidth+1)).toBe(true)
    // Wait for the teleported select's exit transition before measuring the page.
    await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
    await summary.screenshot({path:info.outputPath(`joint-ready-${width}.png`),animations:'disabled'})
    await dialog.getByLabel('场景名称',{exact:true}).scrollIntoViewIfNeeded()
    await page.screenshot({path:info.outputPath(`simple-${width}.png`),animations:'disabled'})
    const advanced=dialog.getByRole('button',{name:'高级设置（可选）',exact:true})
    await advanced.focus();await page.keyboard.press('Enter')
    await expect(dialog.getByLabel('场景 ID',{exact:true})).toBeVisible()
    expect(await dialog.evaluate(node=>node.scrollWidth<=node.clientWidth+1)).toBe(true)
    await expect(dialog.locator('.scene-plan-list>li')).toHaveCount(1)
    await expect(dialog.getByLabel('方案名称',{exact:true})).toHaveValue('全部模型联合识别')
    await expect(dialog.getByLabel('方案 ID',{exact:true})).toHaveValue('plan-joint')
    await expect(dialog.locator('.scene-plan-options').nth(1).getByRole('switch',{checked:true})).toHaveCount(2)
    await expect(dialog.getByRole('button',{name:/编辑方案|更新方案/})).toHaveCount(0)
    await dialog.getByLabel('方案名称',{exact:true}).fill('自定义视频巡检方案')
    await dialog.getByRole('button',{name:'收起高级设置',exact:true}).click()
    await expect(dialog.getByLabel('方案 ID',{exact:true})).toBeHidden()
    await expect(dialog.getByText('保留自定义运行方案',{exact:true})).toBeVisible()
    expect(writes).toHaveLength(0)
    const save=dialog.getByRole('button',{name:'保存新场景',exact:true})
    await save.focus();await page.keyboard.press('Enter')
    await expect(dialog).toHaveCount(0)
    expect(writes).toHaveLength(1)
    const payload=writes[0]!.body
    expect(payload).toMatchObject({sceneId:autoId,name:'工地安全巡检',enabled:true,expectedRevision:0})
    expect(payload.models).toHaveLength(2);expect(payload.plans).toHaveLength(1)
    expect(payload.inputTypes).toEqual(['image','video'])
    expect(payload.plans[0].name).toBe('自定义视频巡检方案')
    for(const plan of payload.plans){expect(plan.execution).toBe(mode);expect(plan.memberIds).toEqual(payload.models.map((member:any)=>member.memberId));expect(plan.inputTypes).toEqual(['image','video']);expect(plan.cameraPolicy.frameInterval).toBe(5)}
    expect(payload).not.toHaveProperty('approved');expect(errors).toEqual([])
    await page.getByRole('button',{name:'创建场景',exact:true}).click()
    await dialog.getByLabel('场景名称',{exact:true}).fill('取消联合草稿')
    await selectElementOption(page,'项目模型','安全帽检测 / 2.0.0 · 移动端（Android）',false)
    await expect(dialog.locator('.scene-members.editable>li')).toHaveCount(1)
    await expect(page.getByRole('listbox')).toBeHidden()
    await selectElementOption(page,'项目模型','手机检测 / 2.0.0 · 移动端（Android）',false)
    await expect(dialog.locator('.scene-members.editable>li')).toHaveCount(2)
    await expect(dialog.getByRole('button',{name:'保存新场景',exact:true})).toBeEnabled()
    await dialog.getByRole('button',{name:'取消',exact:true}).click()
    await expect(dialog).toHaveCount(0)
    expect(writes).toHaveLength(1);expect(errors).toEqual([])
    console.log(JSON.stringify({width,browser:context.browser()!.version(),fixtureWrites:writes.length,plans:payload.plans.length,cancelWrites:0,pageErrors:errors.length}))
  })
}
