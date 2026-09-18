# M09 模型市场自动化测试

M09-T07 的回归测试覆盖目录查询、鉴权失败、下载完整性和限流。测试通过
FastAPI `TestClient` 调用真实路由，并临时切换到 `models/registry.test.json`
引用的通用小型下载夹具；生产目录不再为了自动化测试保留占位模型，也不会下载或加载真实的大体积模型权重。

## 覆盖矩阵

| 场景 | 用例 |
| --- | --- |
| 目录查询/场景过滤 | `test_directory_query_and_scenario_filter` |
| 未携带或错误 Token | `test_catalog_authentication_failure` |
| 下载大小与 SHA-256 一致 | `test_download_hash_and_size_match_catalog` |
| 注册表摘要不符 | `test_download_integrity_mismatch_is_rejected_without_bytes` |
| 下载速率限制 | `test_download_rate_limit_returns_retryable_429` |

执行命令：

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_model_marketplace_automation.py' -v
.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_model_marketplace_api.py' -v
.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_model_download.py' -v
```

所有下载响应都使用目录声明的 `sizeBytes` 和 `sha256`，并要求错误时不流式发送不符合契约的字节。
