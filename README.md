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
| **底层自愈** | “登录过期了，重置一下” | **内置浏览器助手**，无需手动导出 Cookie |

---

## 🛠️ 快速起步

1.  **安装环境**：推荐使用 [uv](https://astral.sh/uv) 管理。
2.  **配置 Auth**：在根目录下放入 `cookies.json`。
    *   *Tip*: 可调用 `refresh_login` 工具通过弹窗直接登录抓取。
3.  **自定义补剂**：修改 `supplements_config.yaml` 打造您的个人营养包。
4.  **挂载 Claude**：在 `claude_desktop_config.json` 中配置本项目。

---

## 🌎 国际化标准
本项目所有工具及参数均支持 **中英双语 (Bilingual)** 描述，无论您使用中文还是英文与 Claude 沟通，系统都能提供最精准的工具调用建议。

---
*Designed for performance. Engineered for simplicity.*
父文件夹)*

#### 2. 添加 Auto_Nutrition 挂载节点
打开那个配置文件，在根目录的 `mcpServers` 节点下增加以下配置：

**如果你选择将本包通过远端 GitHub URL 挂载 (免本地克隆)：**
{
  "mcpServers": {
    "auto-nutrition": {
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/你的用户名/Auto_Nutrition.git",
        "auto-nutrition-mcp"
      ]
    }
  }
}
```

**如果你已经将仓库克隆在本地 (针对像你一样正在本地开发的用户)：**
```json
{
  "mcpServers": {
    "auto-nutrition": {
      "command": "uv",
      "args": [
        "run",
        "--python", "python3.10",
        "mfp_adapter.py"
      ],
      "cwd": "/绝对路径/指向/Auto_Nutrition的文件夹",
      "env": {
         "PYTHONPATH": "/绝对路径/指向/Auto_Nutrition的文件夹/"
      }
    }
  }
}
```

📝 *注意：无论使用哪种方式，请确保 `cookies.json` 文件位于工作目录 (`cwd`) 下，或者和 `mfp_adapter.py` 放在一起。*

#### 3. 重启 Claude Desktop
完全退出（Command+Q）并重启 Claude Desktop。观察右下角的 🔨 `插头` / `工具` 图标，点开后如果看到 `record_nutrition`, `get_daily_summary`, `record_weight` 三个工具，说明连接大功告成！

## 👨‍💻 二次开发与底层联通测试

如果你在配置后怀疑没连上，或者你想二次修改代码逻辑：
1. 确保已在系统级安装 [uv](https://astral.sh/uv) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)。
2. 在该项目根目录下通过终端执行自带的综合测试脚本：
   ```bash
   uv run python test_connection.py
   ```
3. 如果看到终端中输出“ ✅ 全部测试通过”，即代表你的本地网络和 Cookie 配置一切正常！

---

*免责声明：本项目纯属个人自用折腾与自动化探索，与 MyFitnessPal 官方无任何关联。请合理使用 API 频次，避免触发官方风控系统。*
