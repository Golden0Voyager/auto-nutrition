# 🍎 Auto_Nutrition MCP Server
> **AI-Powered Nutrition & Performance Hub for High-Performance Athletes.**

`Auto_Nutrition` 是一套基于 **Model Context Protocol (MCP)** 的智能营养分析与运动中枢。它不仅是 MyFitnessPal 的“语音助手”，更是您的“专业营养记录官”。通过大语言模型的高效理解力，它让记录从繁琐的“搜、点、输、存”缩短为一句话、一张图、甚至一个念头。

---

## ✨ 为什么选择它？ (The Experience)

### 🌿 极致优雅的记录逻辑
**过去**：打开 App -> 点击 "+" -> 搜索 -> 筛选 -> 输入分量 -> 保存。(耗时 30秒)
**现在**：对着 Siri/Claude 说句：“**午饭吃了两百克鸡胸肉和一根香蕉。**” (耗时 2秒)
*   **智能拆解**：自动提取重量、热量及微量元素（钠、钾、钙等）。
*   **锚点校准**：通过本地 `supplements_config.yaml` 锁定常驻补剂数据，杜绝 AI 幻觉。
*   **三级解析**：本地配置 → 本地 USDA 库（7.6 万条） → AI 估值 → 兜底告警。

### 🏃 专业跑者的“马拉松模式”
针对马拉松运动员 (Marathon Training) 深度定制：
*   **运动同步**：支持同步心率、配速、热量消耗。
*   **营养监控**：实时分析“钠钾平衡”防止水肿，追踪蛋白质确保肌肉修复。
*   **缺口补位**：问一句：“**今天跑了20k，晚餐还差多少蛋白质达标？**” AI 结合当日数据给出策略。

### 🪄 主动式补剂管家
*   **时间感知**：记录晚餐后，AI 会主动询问：“**晚餐已录入。需要顺便记录您的‘晚间补剂’包吗？**”
*   **容错自由**：不小心录错了？直接说：“**撤回刚才的记录**” 或者 “**删掉今天的晚餐**”。

---

## 🔥 功能矩阵 (Feature Matrix)

| 功能 | 交互示例 | 价值 |
| :--- | :--- | :--- |
| **精准识食** | “刚才吃了两个肉包子，一碗粥” | 自动换算常见地域食物及分量 |
| **运动打卡** | “跑了 10 公里，配速 5:30” | 自动计算有氧时长与热量消耗 |
| **趋势洞察** | “帮我分析下最近一月的营养趋势” | 抓取 7 天以上数据，监控钠/蛋白偏离度 |
| **点餐补位** | “蛋白还差 40g，推荐个补位晚餐” | 检索本地高频食物库，给出最优配比建议 |
| **底层自愈** | “登录过期了，重置一下” | **内置 Cookie 导入向导**，无需手写代码 |

---

## 🧰 工具清单 (MCP Tools)

| 工具 | 用途 |
| :--- | :--- |
| `record_nutrition` | 录入食物/补剂到指定日期与餐次（支持字符串或结构化对象） |
| `record_meal` | 把 MFP 自定义套餐（My Meals）整体写入某一餐；传 meal_id 或套餐名（支持模糊匹配，歧义时返回候选） |
| `list_my_meals` | 列出 MFP 账号里的自定义套餐（meal_id / 食物数 / 总热量） |
| `get_daily_summary` | 当日热量与三大宏量的预算缺口 |
| `get_nutrition_trends` | 最近 N 天（≤30）趋势，含本地高保真微量元素 |
| `delete_last_entry` | 按日期/餐次撤回最近记录 |
| `record_exercise` | 记录有氧/力量训练及消耗 |
| `record_measurement` | 记录体重 (kg) 或饮水 (ml) |
| `lookup_food_nutrition` | 查询本地 USDA 库的营养成分 |
| `get_food_config` | 查看补剂与常驻食物配置 |
| `import_cookies` | 导入浏览器导出的 Cookie JSON，即时恢复会话 |
| `get_cookie_guide` | 手动导出 Cookie 的分步教程（绕过验证码） |
| `get_current_time` | 当前时间 + 建议餐次（服务端计算，消除推断延迟） |

---

## 🛠️ 快速起步

1.  **安装环境**：推荐使用 [uv](https://astral.sh/uv) 管理。
2.  **配置凭据**：复制 `.env.example` 为 `.env`，填入 `MFP_USERNAME` / `MFP_PASSWORD`；
    若被 Cloudflare 验证码拦截，改在根目录放入浏览器导出的 `cookies.json`（可调用 `get_cookie_guide` 获取教程，再用 `import_cookies` 导入）。
3.  **自定义补剂**：修改 `supplements_config.yaml` 打造您的个人营养包。
4.  **挂载 Claude**：见下节。

### 挂载到 Claude Desktop

**Step 1. 打开配置文件**

macOS：`~/Library/Application Support/Claude/claude_desktop_config.json`
Windows：`%APPDATA%\Claude\claude_desktop_config.json`

**Step 2. 在 `mcpServers` 下添加节点**

远端挂载（免本地克隆）：

```json
{
  "mcpServers": {
    "auto-nutrition": {
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/Golden0Voyager/auto-nutrition.git",
        "auto-nutrition-mcp"
      ]
    }
  }
}
```

本地开发（推荐，便于改代码）：

```json
{
  "mcpServers": {
    "auto-nutrition": {
      "command": "uv",
      "args": ["run", "--python", "3.12", "mfp_adapter.py"],
      "cwd": "/绝对路径/指向/auto-nutrition",
      "env": {
        "PYTHONPATH": "/绝对路径/指向/auto-nutrition/"
      }
    }
  }
}
```

📝 *注意：无论使用哪种方式，请确保 `cookies.json` 位于 `cwd` 下，或与 `mfp_adapter.py` 放在一起。*

**Step 3. 重启 Claude Desktop**

完全退出（Command+Q）并重启。点开 🔨 工具图标，看到 `record_nutrition`、`get_daily_summary`、`get_current_time` 等 13 个工具即连接成功。

---

## 👨‍💻 二次开发与测试

1. 安装 [uv](https://astral.sh/uv)：`curl -LsSf https://astral.sh/uv/install.sh | sh`
2. 安装依赖：`uv sync --extra test`
3. 单元测试（242 个用例，覆盖率 100%）：

   ```bash
   uv run pytest --cov=mfp_adapter --cov-report=term-missing
   ```

4. 真实联通性测试（需有效 Cookie / 账号）：

   ```bash
   uv run pytest tests/test_connection.py -s
   ```

   看到 “✅ 全部测试通过” 即代表本地网络与 Cookie 配置正常。

5. 代码检查：`uv run ruff check mfp_adapter.py tests/`

---

*免责声明：本项目纯属个人自用折腾与自动化探索，与 MyFitnessPal 官方无任何关联。请合理使用 API 频次，避免触发官方风控系统。*
