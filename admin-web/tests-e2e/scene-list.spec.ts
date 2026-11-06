import { expect, test } from '@playwright/test'

// Layout-only data: real isolated cookie auth, with a read-only scene response.
// No project/catalog mutation or production database is involved.
for(const width of [1366,390]) {
  test(`compact scene list and accessible details at ${width}px`,async({context,page},info)=>{
    test.skip(info.project.name!=='production-chromium','requires isolated local hosting')
    await page.setViewportSize({width,height:768})
    expect((await context.request.post('/aiyoloapi/auth/login',{data:{username:'business-owner-scene1440',password:'business-test-password'}})).ok()).toBe(true)
    const projectId=(await(await context.request.get('/aiyoloapi/auth/projects')).json()).projects[0].projectId
    const longName='安全生产巡检与高风险作业综合识别场景'.repeat(5)
    const scenes=Array.from({length:20},(_,i)=>({projectId,sceneId:`scene-${i+1}`,name:i===1?longName:`${String(i+1).padStart(2,'0')} · ${['安全帽佩戴检查','作业区安全巡检','车辆与人员识别','通道占用检查'][i%4]}`,
      inputTypes:['image','video'],revision:i+1,enabled:i%4!==3,approved:i%3!==2,
      models:Array.from({length:i===0?20:2},(_,m)=>({memberId:`member-${m}`,projectModelId:`pm-${m}`,modelId:'uploaded-06fixture',modelName:`安全检测模型 ${m+1}`,version:'2.0.0',target:m%2?'mobile':'pc',position:m,inputTypes:['image','video'],parameterRevision:0,execution:'single'})),
      plans:Array.from({length:i===0?10:1},(_,p)=>({planId:`plan-${p}`,name:`巡检方案 ${p+1}`,memberIds:['member-0'],inputTypes:['image'],execution:'single',enabled:true})),
    }))
    let writes=0
    await page.route(`**/aiyoloapi/projects/${projectId}/scenes`,async route=>{
      if(route.request().method()!=='GET'){writes++;await route.abort();return}
      await route.fulfill({json:{scenes}})
    })
    await page.goto(`/admin/scenes?project=${projectId}`)
    const region=page.getByRole('region',{name:'项目识别场景列表'})
    const rows=region.locator('.el-table__body-wrapper tr')
    await expect(rows).toHaveCount(20)
    await expect(page.locator('.scene-members')).toHaveCount(0)
    await expect(page.locator('.scene-plan-summary')).toHaveCount(0)
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
    const heights=await rows.evaluateAll(elements=>elements.map(e=>e.getBoundingClientRect().height))
    expect(Math.max(...heights)-Math.min(...heights)).toBeLessThanOrEqual(2)
    const visible=await rows.evaluateAll(elements=>elements.filter(e=>{const r=e.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight}).length)
    console.log(JSON.stringify({viewport:`${width}x768`,completeRows:visible,rowHeight:heights[0],total:scenes.length}))
    await page.screenshot({path:`../evidence/M33/M33-T55/list-${width}.png`,animations:'disabled'})
    if(width===1366)expect(visible).toBeGreaterThanOrEqual(6)

    // The fixed detail action remains reachable without horizontal scrolling.
    const first=page.getByRole('button',{name:`查看详情 ${scenes[0]!.name}`,exact:true})
    await expect(first).toBeInViewport()
    const inlineEdit=page.getByRole('button',{name:`编辑场景 ${scenes[0]!.name}`,exact:true})
    await expect(inlineEdit).toBeVisible();await inlineEdit.focus();await page.keyboard.press('Enter')
    const centered=await inlineEdit.evaluate(button=>{
      const group=button.closest('.scene-row-actions')!,cell=button.closest('.cell')!
      const buttons=[...group.querySelectorAll('button')],first=buttons[0]!.getBoundingClientRect(),last=buttons.at(-1)!.getBoundingClientRect(),cellRect=cell.getBoundingClientRect()
      return Math.abs((first.left+last.right)/2-(cellRect.left+cellRect.right)/2)
    })
    expect(centered).toBeLessThanOrEqual(2)
    await expect(page.getByRole('dialog',{name:'编辑项目场景',exact:true})).toBeVisible()
    await page.keyboard.press('Escape');await expect(page.getByRole('dialog',{name:'编辑项目场景',exact:true})).toHaveCount(0)
    await first.focus();await page.keyboard.press('Enter')
    const detail=page.getByRole('dialog',{name:'场景详情',exact:true})
    await expect(detail).toBeVisible()
    await expect(detail.getByRole('button',{name:/编辑场景|停用场景|撤销批准/})).toHaveCount(0)
    await expect(detail.locator('.scene-members > li')).toHaveCount(20)
    await expect(detail.locator('.scene-plan-summary > ul > li')).toHaveCount(10)
    expect(await detail.evaluate(e=>e.scrollWidth<=e.clientWidth)).toBe(true)
    await page.keyboard.press('Escape');await expect(detail).toHaveCount(0)
    await expect(first).toBeFocused()
    await page.getByRole('button',{name:`查看详情 ${longName}`,exact:true}).click()
    await expect(detail.getByRole('heading',{name:longName,exact:true})).toBeVisible()
    expect(await detail.evaluate(e=>e.scrollWidth<=e.clientWidth)).toBe(true)
    await page.screenshot({path:`../evidence/M33/M33-T55/long-name-${width}.png`,animations:'disabled'})
    expect(writes).toBe(0)
  })
}
