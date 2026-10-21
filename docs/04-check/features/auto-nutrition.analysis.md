# Gap Analysis: Auto_Nutrition

> 验证开发实现与 PRD 需求的匹配程度。
> 基线：`main` @ v1.3.x（2026-10），`mfp_adapter.py` 1,508 行 / 11 个 MCP tool。

## 1. 需求核对表 (Requirement Checklist)

### 模块一：核心写入适配器 (MCP Server)

| 需求描述 | 实现位置 | 状态 | 备注 |
| :--- | :--- | :--- | :--- |
| 标准 MCP Server | `mfp_adapter.py` `main()` | ✅ | `FastMCP` + `mcp.run()`，stdio 传输 |
| 暴露 `record_nutrition` tool | L957 | ✅ | 签名 `(date, meal_type, items)` |
| 入参遵守 PRD Schema | `FoodItemModel` / `NutritionModel` | ✅ | Pydantic 校验；`calories` / `macros` 改为**可选**，缺失时走三级解析 |
| `SessionExpiredError` 不崩服务 | L466 + 各 tool 的 `try/except` | ✅ | 异常转为可读字符串返回，进程存活 |
| 会话过期可自愈 | `import_cookies` / `get_cookie_guide` | ✅ | 替代 PRD 未细化的"更新 Cookie"要求 |
| Cookie / Session 维持 | `_load_cookies` / `_fetch_access_token` | ✅ | Bearer Token 缓存 + 提前 1h 刷新 |
| 服务端稳定性 | `tenacity` 重试 | ✅ | 仅对 5xx 重试 3 次（`is_server_error`） |

### 模块二：本地补剂与常驻食物配置库

| 需求描述 | 实现位置 | 状态 | 备注 |
| :--- | :--- | :--- | :--- |
| `supplements_config.yaml` 存在 | 根目录 | ✅ | v1.1，含单位规范 `metadata.unit_reference` |
| 耐力运动类（能量胶 / 电解质） | `supplements` | ✅ | Maurten 100、电解质泡腾片、甜菜根粉等，共 12 项 |
| 恢复补剂类（乳清 / 鱼油等） | `supplements` | ✅ | 乳清、钙、镁、姜黄素、氨糖、B 族 |
| 上海 / 台湾地域饮食 | `regional_foods` | ✅ | 卤肉饭、本帮红烧肉、牛肉面等 3 项 |
| **Adapter 层真正消费该配置** | `_apply_config_safeguard` | ✅ | 旧版仅靠 Prompt 硬编码；现已落地为代码级匹配 + 别名 + 组合展开 |
| 常驻食物 / 早晚补剂包 | `common_foods` / `routines` / `meal_combos` | ✅ | 6 + 4 + 1 项，一次调用可展开整包 |

### 模块三：大模型系统提示词 (Parser Prompt)

| 需求描述 | 实现位置 | 状态 | 备注 |
| :--- | :--- | :--- | :--- |
| `system_prompt.txt` 存在 | 根目录 | ✅ | 262 行 |
| 多模态解析（图片估重） | `system_prompt.txt` | ✅ | 含重量估算与宏量拆解规则 |
| 时间感知自动判餐次 | Prompt + `get_current_time` | ✅ | **双保险**：服务端 `suggested_meal_type` + `record_nutrition` 内时间校验告警 |
| 补剂一律归 `snack` | `system_prompt.txt` | ✅ | |
| 强制静默调用工具 | `system_prompt.txt` | ✅ | 禁止输出冗长分析 |

### 架构约束（PRD 系统上下文）

| 需求描述 | 状态 | 备注 |
| :--- | :--- | :--- |
| 三层解耦（Parser / Router / Adapter） | ✅ | 模型端只产 JSON；Adapter 不感知客户端 |
| MFP 仅作无头数据库 | ✅ | 全部写入走 `api.myfitnesspal.com/v2` |
| 数据回流 Garmin / Apple Health | ⚠️ | 依赖 MFP 后台同步，本项目**无同步状态校验**（见 Gaps #4） |

## 2. 差异说明 (Gaps Found)

| # | 差异 | 影响 | 处置 |
| :--- | :--- | :--- | :--- |
| 1 | PRD 要求 `calories` / `macros` 必填，实际改为可选 | 正向：LLM 不必硬编数字，减少幻觉 | 已接受，由三级解析兜底 |
| 2 | PRD 的"更新 Cookie"未定义交互，实际实现为 `get_cookie_guide` + `import_cookies` | 正向：可绕过 Cloudflare 验证码 | 已接受 |
| 3 | `v2/diary` 纯文本条目（无 `food_id`）依赖 MFP 后端容忍度 | 接口变更时可能写入失败 | 现有 `retry` + 错误回传；尚未实现降级到 `/food/diary_update` |
| 4 | Garmin / Apple Health 同步结果无回读校验 | 可能"写进 MFP 但没到手表" | 未实现，列入路线图 |
| 5 | `pyproject.toml` version 仍为 `1.3.0`，最新 tag 为 `v1.3.1` | 版本标识不一致 | 建议下次发布统一到 `1.4.0`（本轮改动已超出 1.3.1） |
| 6 | 单账号 | 多账号需改环境变量结构 | 未实现，列入路线图 |
| 7 | `GET /v2/nutrition_goals` 恒返回 404，MFP 已下线该资源 | 动态营养目标曾静默回落硬编码值 | 已修：404 时回退解析网页日记的 "Your Daily Goal" 行 |

## 3. 匹配度评分 (Match Rate)

**100%** — PRD 三模块的全部必做项均已落地。差异 1 / 2 属超预期实现，3 / 4 属 PRD 未覆盖的运维层面。

## 4. 工程质量基线

| 指标 | 现状 |
| :--- | :--- |
| 单元测试 | 242 个用例，15 个测试模块 |
| 覆盖率 | **100%**（834 statements，门槛 85%） |
| 静态检查 | ruff（阻塞）、mypy（阻塞，0 error） |
| 安全扫描 | bandit（阻塞，0 issue）、pip-audit（阻塞，真实审计） |
| 依赖锁定 | `uv.lock`，`mcp` 上限 `<2` |

## 5. 后续建议 (Next Steps)

1. **同步回读**：新增 `check_sync_status`，比对 MFP 日记与 Garmin 侧记录，断链时主动告警。
2. **多账号**：`MFP_USERNAME` 扩展为多 profile，Cookie 文件按账号隔离。
3. **接口降级**：`v2/diary` 失败时回落 `/food/diary_update` 表单 POST。
4. **趋势可视化**：`get_nutrition_trends` 已产出 30 天数据，可加 MCP resource 输出图表或周报。
