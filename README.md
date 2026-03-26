# Auto_Nutrition MCP Server

Auto_Nutrition 是一个基于 **Model Context Protocol (MCP)** 的智能微服务。它可以让你直接在 Claude Desktop 或其它支持 MCP 的客户端里，通过自然语言或发送食物图片，自动估算热量及三大宏量营养素 (碳水/蛋白质/脂肪)，并**无感静默写入到你的 MyFitnessPal** 账号中。

## 🌟 核心功能

- **自然语言录入饮食**："我今天晚餐吃了一碗米饭和一份西红柿炒鸡蛋" -> 自动拆解并记录为 MyFitnessPal 日常日记。
- **图片识食**：直接发送饭菜照片，大模型会自动估算重量和热量等指标。
- **智能纠偏**：通过本地 `supplements_config.yaml` 锁定常驻补剂（如蛋白粉、能量胶）与地域饮食的营养数值，防止大模型发生幻觉或估算失真。
- **体重跟踪**：支持自然语言直接打卡体重数据。
- **健康查户口**：随时询问当日的热量摄入和营养素结构汇总。

## ⚡ 快速接入指南 (小白友好)

本项目默认支持最新的 `uv` 包管理器调用。请按照以下三个步骤进行配置：

### 第一步：获取 MyFitnessPal 的 Cookie

由于 MyFitnessPal 官方未开放 V2 API 权限，我们需要让 MCP 接管你的网页端登录态：

1. 在电脑浏览器（推荐 Chrome/Edge）中登录 [MyFitnessPal 官网](https://www.myfitnesspal.com/)。
2. 登录成功后，使用任意 Cookie 导出插件（例如 [EditThisCookie](https://chromewebstore.google.com/detail/editthiscookie/fngmhnnpilhplaeedifhccceomclgfbg) 或直接按 F12 抓取）。将所有域下面的 cookie 导出为 JSON 数组格式。
3. 将导出的 Cookie 文本保存为名为 `cookies.json` 的文件。
4. 将 `cookies.json` 放置在与本项目的 `mfp_adapter.py` 同级的根目录下。

*⚠️ 隐私警告：此文件等同于你的账号密码，**绝对不要**将其上传或分享给他人。本项目 `.gitignore` 已默认屏蔽此文件上传。*

### 第二步：(可选) 自定义补剂配置

项目根目录自带了一个 `supplements_config.yaml` 示例。建议使用任何文本编辑器打开它，把你经常吃的“蛋白粉”、“左旋肉碱”或者是带有明确营养标签的“便利店三明治”的热量固定下来。大模型在匹配到这些核心词汇时，会**强制使用你配置的精准热量**，保证长期数据的严谨度。

### 第三步：配置 Claude Desktop

现在，让我们把这个 Server 对接到你的 Claude Desktop 里！

#### 1. 找到 Claude 的配置文件
- **Mac**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

*(如果文件不存在，请手动新建它及其父文件夹)*

#### 2. 添加 Auto_Nutrition 挂载节点
打开那个配置文件，在根目录的 `mcpServers` 节点下增加以下配置：

**如果你选择将本包通过远端 GitHub URL 挂载 (免本地克隆)：**
```json
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
