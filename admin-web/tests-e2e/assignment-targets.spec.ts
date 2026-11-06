import { expect, test } from '@playwright/test'
import { selectElementOption, toggleElementSwitch } from './helpers/navigation'

test.beforeEach(({},info)=>test.skip(info.project.name!=='production-chromium','requires isolated real backend'))
for(const width of [1440,390]){
  test(`multiple project models per target and explicit scene membership at ${width}px`,async({context,page,browser})=>{
    test.setTimeout(90_000)
    expect((await context.request.post('/aiyoloapi/auth/login',{data:{username:`business-owner-dual${width}`,password:'business-test-password'}})).ok()).toBe(true)
    const id=(await(await context.request.get('/aiyoloapi/auth/projects')).json()).projects[0].projectId
    const base=`/aiyoloapi/projects/${id}`
    await page.setViewportSize({width,height:960});await page.goto(`/admin/project-models?project=${id}`)

    await page.getByRole('tab',{name:/PC 端/}).click()
    await page.getByRole('button',{name:'添加 PC 模型',exact:true}).click()
    await selectElementOption(page,'模型版本','双端验收模型 / 1.0.0')
    await page.getByRole('dialog',{name:'分配项目模型'}).getByRole('button',{name:'确认分配',exact:true}).click()
    await page.getByRole('alertdialog',{name:'确认加入项目模型池'}).getByRole('button',{name:'确认分配',exact:true}).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await page.getByRole('tab',{name:/移动端/}).click()
    await page.getByRole('button',{name:'添加移动端模型',exact:true}).click()
    await selectElementOption(page,'模型版本','双端验收模型 / 1.0.0')
    await page.getByRole('dialog',{name:'分配项目模型'}).getByRole('button',{name:'确认分配',exact:true}).click()
    await page.getByRole('alertdialog',{name:'确认加入项目模型池'}).getByRole('button',{name:'确认分配',exact:true}).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)

    await expect(page.locator('.target-pool.is-mobile .inventory-row')).toHaveCount(1)
    await page.getByRole('tab',{name:/PC 端/}).click()
    await expect(page.locator('.target-pool .inventory-row')).toHaveCount(1)
    await expect(page.locator('body')).toContainText('不会创建场景，也不会启动运行任务')
    let assignments=(await(await context.request.get(base+'/model-assignments')).json()).assignments
    expect(assignments.map((a:any)=>a.target).sort()).toEqual(['mobile','pc']);expect(assignments.every((a:any)=>a.revision===1)).toBe(true)
    await page.screenshot({path:`../evidence/M33/M33-T38-models-${width}.png`,fullPage:true,animations:'disabled'})
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)

    const userContext=await browser.newContext({baseURL:'http://127.0.0.1:4174',viewport:{width,height:960}})
    try{
      expect((await userContext.request.post('/aiyoloapi/auth/login',{data:{username:`business-user-dual${width}`,password:'business-test-password'}})).ok()).toBe(true)
      const user=await userContext.newPage();await user.goto(`/admin/project-models?project=${id}`)
      await expect(user.locator('.inventory-row')).toHaveCount(1);await expect(user.getByRole('button',{name:'添加 PC 模型',exact:true})).toHaveCount(0);await expect(user.getByRole('button',{name:'添加移动端模型',exact:true})).toHaveCount(0)

      await page.goto(`/admin/scenes?project=${id}`);await page.getByRole('button',{name:'创建场景',exact:true}).click()
      await page.getByLabel('场景 ID',{exact:true}).fill('dual-scene');await page.getByLabel('场景名称',{exact:true}).fill('双端单模型场景')
      await selectElementOption(page,'项目可用模型版本','双端验收模型 / 1.0.0 · PC / 移动双端');await toggleElementSwitch(page,'移动端')
      await page.getByRole('button',{name:'添加模型成员',exact:true}).click();await expect(page.locator('.scene-members.editable li')).toHaveCount(2)
      await page.getByRole('button',{name:'保存新场景',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0)
      const card=page.locator('.scene-card').filter({has:page.getByRole('heading',{name:'双端单模型场景',exact:true})})
      await expect(card).toContainText('1 个模型版本 · 2 条端部署')
      await card.getByRole('button',{name:'批准场景',exact:true}).click();await page.getByLabel('审核原因').fill('隔离环境双端配置验收')
      await page.getByRole('button',{name:'确认批准',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0)
      const scene=await(await context.request.get(base+'/scenes/dual-scene')).json()
      expect(scene.executionSupportByTarget).toEqual({pc:true,mobile:true});expect(scene.executionSupported).toBe(true)
      for(const target of ['pc','mobile']){
        const result=await userContext.request.post(base+'/scenes/dual-scene/resolve',{data:{expectedRevision:scene.revision,target,inputType:'image'}})
        expect(result.ok()).toBe(true);expect((await result.json()).model.target).toBe(target)
      }

      await page.goto(`/admin/project-models?project=${id}`)
      await page.getByRole('tab',{name:/移动端/}).click()
      const mobile=page.locator('.target-pool.is-mobile .inventory-row')
      await mobile.getByRole('button',{name:'停用',exact:true}).click();await page.getByRole('alertdialog').getByRole('button',{name:'确认停用',exact:true}).click()
      await expect(mobile).toContainText('已停用')
      assignments=(await(await context.request.get(base+'/model-assignments')).json()).assignments
      expect(assignments.find((a:any)=>a.target==='pc')).toMatchObject({enabled:true,revision:1})
      expect(assignments.find((a:any)=>a.target==='mobile')).toMatchObject({enabled:false,revision:2})
      await mobile.getByRole('button',{name:'移除',exact:true}).click();await page.getByRole('alertdialog').getByRole('button',{name:'确认移除',exact:true}).click()
      await expect(page.locator('.target-pool.is-mobile .inventory-row')).toHaveCount(0)
      assignments=(await(await context.request.get(base+'/model-assignments')).json()).assignments
      expect(assignments).toHaveLength(1);expect(assignments[0].target).toBe('pc')
      expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
    }finally{await userContext.close()}
  })
}
