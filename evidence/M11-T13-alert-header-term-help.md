# M11-T13 类别告警参数表头术语提示证据

## 浏览器验收

- 页面：`http://127.0.0.1:8080/admin/`
- 入口：模型资产 → 参数设置 → 类别告警初始参数
- 表头帮助按钮数量：9
- 实测标签：启用说明、类别说明、业务名称说明、事件编码说明、告警置信度说明、连续帧说明、停留时间说明、冷却时间说明、级别说明
- 点击“启用”帮助按钮后，提示显示“是否启用该类别对应的告警规则；关闭后仍可识别，但不按该类别生成告警。”
- 按 Esc 后提示关闭，`aria-expanded` 从 `true` 恢复为 `false`

## 自动化验证

- `node --check app/static/app.js`：通过
- `python -m unittest tests.test_admin_model_parameters`：7/7 通过
- `python -m unittest discover -s tests -p "test_admin_*.py"`：24/24 通过
- `python -m unittest discover -s harness/tests -p "test_*.py"`：30/30 通过
- `python harness/harness.py validate`：通过
- `python harness/harness.py render`：通过
