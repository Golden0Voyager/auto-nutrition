# Completion Report: Auto_Nutrition

> 版本：`v1.3.x`（`pyproject` 标 1.3.0，最新 tag `v1.3.1`）
> 代码规模：`mfp_adapter.py` 1,719 行 / 13 个 MCP tool；测试 16 个模块 270 用例

## 1. Executive Summary

`Auto_Nutrition` 是一个基于 MCP (Model Context Protocol) 的自动化饮食与运动录入服务。客户端 LLM 把自然语言或食物图片解析成结构化数据，Adapter 负责校验、补全营养值并写入 MyFitnessPal；MFP 作为无头数据库，再同步到 Garmin Connect 与 Apple Health。

### Value Delivered

| 核心价值 | 问题解决 | 交付成果 | UX 效果 |
| :--- | :--- | :--- | :--- |
| **自动化录入** | 手动"搜、点、输、存"的 30 秒流程 | `record_nutrition` + 10 个配套 tool | 一句话完成记录 |
| **降低幻觉** | LLM 对小众菜品 / 补剂的数值靠猜 | 三级解析：本地配置 → USDA 库 → AI 估值 → 兜底告警 | 补剂与地域菜数值稳定可复现 |
| **离线可查** | 依赖 MFP 接口返回微量元素 | 本地 `usda_core.db`（76,668 条）+ 本地流水账 | 钠钾等微量元素不再缺失 |
| **自愈能力** | Cookie 过期、Cloudflare 验证码阻断 | `get_cookie_guide` + `import_cookies` | 1 分钟恢复，不必改代码 |
| **可维护** | 单文件 1,500 行易腐化 | 270 测试 / 100% 覆盖 / 四道 CI 门禁 | 改动有兜底 |

## 2. 系统组件与交付物

| 组件 | 文件 | 说明 |
| :--- | :--- | :--- |
| MCP Server | `mfp_adapter.py` | FastMCP，13 个 tool，stdio 传输 |
| 营养解析器 | `USDALocalResolver` | SQLite FTS5 全文检索 + 相关性打分，旧 schema 回退 |
| 配置锚点 | `supplements_config.yaml` | 12 补剂 + 3 地域菜 + 6 常驻食物 + 4 补剂包 + 1 套餐 |
| 本地数据 | `usda_core.db` | 76,668 食物 / 477 营养素，57 MB |
| 本地流水账 | `nutrition_journal.json` | 保留 MFP 不接收的微量元素（镁、锌、咖啡因、EPA/DHA 等），上限 200 条 |
| Parser Prompt | `system_prompt.txt` | 262 行，多模态 + 时间感知 + 静默调用 |
| 自动化 | `.github/workflows/ci.yml` | ruff / mypy / bandit / pip-audit / pytest+coverage |

### 2.1 工具清单（13）

| 类别 | 工具 |
| :--- | :--- |
| 写入 | `record_nutrition`、`record_meal`、`record_exercise`、`record_measurement` |
| 读取 | `get_daily_summary`、`get_nutrition_trends`、`lookup_food_nutrition`、`get_food_config`、`get_current_time`、`list_my_meals` |
| 维护 | `delete_last_entry`、`import_cookies`、`get_cookie_guide` |

> `record_meal` / `list_my_meals` 面向 MFP 服务端自定义套餐（My Meals）。v2 API 既不开放 meals 读取（401 scope）也不接受 meal 类型日记条目（400），故读走网页 session 接口 `/api/services/users/meals/mine`，写按套餐数值展开为逐条 `food_entry`。
> `record_meal` 的 `meal_ref` 接受 meal_id 或套餐名称（精确 + difflib 模糊匹配）；命中多个候选时返回候选列表交由调用方选择，不猜测。

### 2.2 营养数据解析优先级

```
1. supplements_config.yaml    用户校准值，最高信任
2. usda_core.db               标准参考数据（FTS5 检索）
3. AI 提供的 calories/macros  估算兜底
4. 0 + 显式告警                最后手段
```

### 2.3 服务端防护层

- **时间校验**：`record_nutrition` 比对当前日期 / 时段与传入的 `date` / `meal_type`，不一致时在返回中附加提醒（不阻断写入）。
- **会话自愈**：Token 提前 1 小时刷新；失效时抛 `SessionExpiredError` 并提示走 Cookie 导入流程，服务不崩。
- **重试**：仅对 5xx 做 3 次指数退避重试，避免把 4xx 业务错误重试成风控。

## 3. 质量现状

| 指标 | 结果 |
| :--- | :--- |
| 测试 | 270 passed |
| 覆盖率 | 100%（936 statements，`fail_under = 85`） |
| ruff | 通过（阻塞） |
| mypy | 0 error（阻塞） |
| bandit | 0 issue（阻塞） |
| pip-audit | 通过（阻塞，真实审计依赖清单） |

## 4. 已知限制

1. **同步不可观测**：无法确认 MFP 的数据是否真的到达 Garmin / Apple Health。
2. **单账号**：Cookie 与环境变量只支持一个 MFP 账号。
3. **接口脆弱性**：纯文本条目依赖 `v2/diary` 的后端容忍度，无 `/food/diary_update` 降级路径。
4. **版本号漂移**：`pyproject.toml` 写 `1.3.0`，最新 tag 为 `v1.3.1`。
5. **趋势无图表**：`get_nutrition_trends` 输出 Markdown 表格，无图形。

## 5. 下一步计划 (Roadmap)

| 优先级 | 事项 | 说明 |
| :--- | :--- | :--- |
| P1 | 同步状态回读 | `check_sync_status`：比对 MFP 日记与 Garmin 记录，断链告警 |
| P1 | 接口降级 | `v2/diary` 失败时回落表单 POST |
| P2 | 多账号 | profile 化配置，Cookie 按账号隔离 |
| P2 | 趋势可视化 | 基于已有 30 天数据输出图表 / 周报 |
| P3 | 版本统一 | 下次发布统一到 `1.4.0` 并打 tag |

## 6. 结论

PRD 三个模块的全部必做项均已交付并通过测试，工程质量基线（测试、覆盖率、静态检查、安全扫描）已建立为阻塞式门禁。系统可用于日常真实录入，剩余风险集中在"写入后不可观测"与"单账号"两项，均已列入路线图。
