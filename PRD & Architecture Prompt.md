**【角色设定】** 你是一个资深的 Python 后端工程师和运动数据生态专家。你需要帮我开发一个名为 `Auto_Nutrition` 的本地微服务项目。该项目基于 MCP (Model Context Protocol) 架构，旨在实现饮食和运动补剂的自动化、无感录入。

**【系统上下文与业务背景】**

- **目标生态:** 用户的终端展示看板是 **Garmin Connect (国际区)** 和 **Apple Health**。
- **数据流向:** 用户在客户端 (OpenClaw) 输入自然语言或食物图片 ->大模型提取结构化数据 -> MCP Server 接收 JSON -> 调用 Python 脚本写入 **MyFitnessPal (MFP)** -> MFP 后台自动同步至 Garmin 和 Apple Health。
- **核心要求:** 高度解耦。大模型端（Parser）、业务逻辑端（Router）和写入端（Adapter）必须通过标准 JSON 通信。MFP 仅作为“无头数据库（Headless DB）”使用。

**【架构设计与开发任务】**

请按照以下三个模块逐步进行代码生成和配置编写：

#### 模块一：核心写入适配器 (MFP Adapter / MCP Server)

这是系统的“手脚”。请使用 Python 编写一个标准的 MCP Server。

- **依赖库:** 使用 `python-myfitnesspal` 或直接封装针对 MFP 网页版的 requests 请求（处理好 Cookie/Session 登录维持，因为官方 API 不开放）。

- **接口规范 (MCP Tool 定义):** 暴露一个名为 `record_nutrition` 的 tool。

- **入参 Schema (严格遵守):**

  JSON

  ```
  {
    "date": "YYYY-MM-DD",
    "meal_type": "breakfast | lunch | dinner | snack",
    "items": [
      {
        "name": "string (食物或补剂名称)",
        "weight_g": "number (可选)",
        "calories": "number",
        "macros": { "protein": "number", "carbs": "number", "fat": "number" }
      }
    ]
  }
  ```

- **错误处理要求:** 如果 MFP 会话过期，抛出明确的 `SessionExpiredError` 并提示用户更新 Cookie，不要让整个 MCP Server 崩溃。

#### 模块二：本地补剂与常驻食物配置库 (Local Config)

为了防止大模型在计算标准工业化补剂时出现“幻觉”，请生成一个 `supplements_config.yaml` 文件。当大模型匹配到这些关键词时，直接使用固定数值计算。

- **请在 YAML 中预设以下数据结构和示例（需符合高强度运动人群需求）：**
  - **耐力运动类:** 能量胶 (如 Maurten 100, 100 kcal, 25g carbs)、电解质泡腾片 (0 kcal, 补充自由潜水或骑行后流失的水分)。
  - **恢复补剂类:** 乳清蛋白粉 (以一勺 30g 计：120 kcal, 24g protein)、鱼油。
  - **高频地域饮食:** 考虑到用户经常在上海和台湾两地活动，预设几个难以准确估算的本地碳水炸弹的基准值，如：台湾卤肉饭 (一碗约 550 kcal, 高脂肪高碳水)、本帮红烧肉 (偏甜，碳水需上调)、牛肉面。

#### 模块三：大模型系统提示词 (Parser Prompt)

请为客户端的 LLM 编写一个 System Prompt (`system_prompt.txt`)，赋予其“高级运动营养师”的设定。

- **Prompt 规则要求:**
  1. **多模态解析:** 当收到食物图片时，需预估重量并拆解热量和三大宏量营养素。
  2. **时间感知:** 根据系统当前时间戳，自动判断归属（早/午/晚）。如果明确识别为运动补剂（如蛋白粉、能量胶），一律归入 `snack`（加餐）。
  3. **强制工具调用:** 解析完成后，禁止输出冗长的分析过程，必须严格按照模块一的 JSON Schema，静默调用 `record_nutrition` 这个 MCP Tool。

**【Agent 执行指令】** 请先输出 **模块一 (MFP Adapter)** 的完整 Python 代码和 `requirements.txt`。并在代码中做好详尽的中文注释。等待我的测试反馈后，我们再推进模块二和模块三。