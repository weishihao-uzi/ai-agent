# M1 笔记：手写 tool-calling 循环（react_m1.py）

> 2026-09-05 完成主流程。本笔记是第一份面试素材：协议、踩坑、必答题、面试话术都在这里。
> 标注 ☐ 的空格留给自己的实测观察——实验主义者不做没有亲测的断言。

## 1. M1 做了什么

不依赖 LangChain，用 openai SDK 直连 DeepSeek（OpenAI 兼容接口），完成一次完整往返：
**模型决定调工具 → 我的代码执行工具 → 结果回传 → 模型给出最终文字回答**。
产出 `react_m1.py`（~90 行，2 个 mock 工具），零 langchain 依赖。

## 2. 核心协议（最重要的一张图）

```
system → user → assistant(tool_calls) → tool(tool_call_id) → assistant(最终回答)
```

三条铁律：

1. **assistant 消息原样回传**：`messages.append(msg.model_dump())`，tool_calls 结构一个字段不改
2. **每个工具结果包装成消息**：`{"role": "tool", "tool_call_id": tc.id, "content": json.dumps(结果, ensure_ascii=False)}`
3. **tools 参数每轮请求都要带**：API 无状态，菜单每轮重新端上来

配套要点：

- API 是无状态的，`messages` 数组 = 模型的全部记忆，对话"记忆"是客户端每轮重发全部历史
- `content` 和 `tool_calls` 可以在同一条 assistant 消息里共存（模型可以边说话边调工具）
- `function.arguments` 是 JSON **字符串**，`json.loads` 之后才是 dict
- `func(**args)` 把 dict 展开成关键字参数——分发代码从此不认识任何具体工具，**这就是 AgentExecutor 的核心机制**
- 最终 assistant 发言也要回传记账（不管它带的是 tool_calls 还是纯文本），永远在 `if` 判断之前做，一处覆盖两个分支

## 3. 报错阶梯（每个错 = 一条教训）

| # | 报错 | 教训 |
|---|------|------|
| 1 | `KeyError: DEEPSEEK_API_KEY` | `os.environ` 不读 .env 文件，要 `load_dotenv()`；后端能读到是 pydantic-settings 代劳的 |
| 2 | `NameError: index` | 循环变量先初始化；`index += 1` 放循环体第一行，任何 continue/break 都不漏 |
| 3 | `NameError: messages` | 变量名前后一致（定义 `message`、使用 `messages`） |
| 4 | `400: "[resume_id]" is not of type "array"` | `required` 是数组不是字符串；**schema 在第一次请求就被校验**，模型根本没见到消息 |
| 5 | `400: tool message must follow tool_calls` | 协议配对：assistant 的 tool_calls 宣言必须先回传，tool 消息才有"回复对象" |
| 6 | `AttributeError: 'Function' object has no attribute 'argument'` | 字段是 `arguments`（带 s） |
| 7 | `json.load` 炸 `'str' object has no attribute 'read'` | `load` 读文件（内部调 `.read()`），`loads` 解析字符串（s = string）；配对记：loads/dumps |
| 8 | `msg.model.dump()` 炸 `no attribute 'model'` | pydantic v2 方法名是一个词 `model_dump`；不确定属性时 `print(dir(obj))` 自查 |
| 9 | `msg.assistant` 不存在 | `response.choices[0].message` 拿到的 msg **本身就是** assistant 消息 |

元教训（调试方法论）：

- 报错从**最后一行往上读**：最后行 = 错误类型 + 原因，上面 = 出错位置
- 一次只修一个，修完重跑——修一个会暴露下一个
- 语法错用 `python -m py_compile`（通过了**没有输出就是成功**）；运行时错只能真跑
- API 调用发出之前的错误全是免费的；发出之后每次运行都花 token
- 400 的 `error.message` 会告诉你哪个函数、什么值、期望什么类型——服务器是你最好的调试器

## 4. 四道必答问题（亲测后的答案）

**Q1：为什么 assistant 消息必须原样回传？**
API 无状态，模型只看 messages 数组；server 校验每条 tool 消息前面有带 tool_calls 的 assistant 消息与之配对，结构被改或丢失直接 400。"原样"不是仪式感，是配对校验的硬前提。

**Q2：为什么 tool 消息必须带 tool_call_id？**
它是结果与调用之间的**外键**（类比 interview_messages.interview_id）。并行多个工具调用时，N 条结果靠 id 各自找到"主人"；API 靠它校验配对，模型靠它对号入座。

**Q3：第二次请求 tools 传不传？**
要传。无状态 → `tools` 是每轮都要重新端上来的菜单；不传则模型本轮看不到任何工具，无法发起后续调用（多步流程会断）。实测观察：☐（把第二次请求的 tools 注释掉跑一次，把现象写在这里）

**Q4：模型又返回 tool_calls 时脚本会怎样？**
不 break，while 转回开头再发一次请求。若模型永远返回 tool_calls，index 耗尽 max_index 后循环结束且**没有最终文字答案**——这就是 M2 "强制收敛"（到上限补一条"别调工具了，基于现有信息作答"）的由来。
```
抱歉，我多次尝试获取99号简历都遇到了报错，系统提示"resumeid is false"，说明目前系统中无法正确处理这个简历编号的查询请求。

这可能是因为：
- **简历编号99不存在** 或已被删除
- 该系统主要针对**岗位模拟面试**场景设计，需要先选择一个具体的岗位标签后再调用简历信息

---

如果您需要启动一次**岗位匹配模拟面试**，流程通常是：
1. 从**推荐岗位列表**中选定一个岗位
2. 系统会基于您的简历自动完成出题

**您方便告诉我：**
- 您希望匹配的是哪个具体岗位？
- 或者您是否有其他有效的简历编号想查看？

我可以根据您的岗位需求来协助您完成求职匹配与模拟面试~ 😊
----------------------------------------
[
  {
    "role": "system",
    "content": "你是岗位匹配助手，需要简历时调用 get_mock_resume\n"
  },
  {
    "role": "user",
    "content": "帮我看下 99号简历"
  },
  {
    "content": "我来帮你查看99号简历，同时获取一下当前时间以便更好地为你服务。\n\n让我先获取简历信息：",
    "refusal": null,
    "role": "assistant",
    "annotations": null,
    "audio": null,
    "function_call": null,
    "tool_calls": [
      {
        "id": "call_00_9U5cEqNeD15YRoJki0Ez9075",
        "function": {
          "arguments": "{\"resume_id\": 99}",
          "name": "get_mock_resume"
        },
        "type": "function",
        "index": 0
      },
      {
        "id": "call_01_3a5kcYRU7JtBrW01OWRY1363",
        "function": {
          "arguments": "{}",
          "name": "get_mock_time"
        },
        "type": "function",
        "index": 1
      }
    ]
  },
  {
    "role": "tool",
    "tool_call_id": "call_00_9U5cEqNeD15YRoJki0Ez9075",
    "content": "{\"error\": \"resumeid is false\"}"
  },
  {
    "role": "tool",
    "tool_call_id": "call_01_3a5kcYRU7JtBrW01OWRY1363",
    "content": "{\"datetime\": \"2025-09-13T05:18:47\"}"
  },
  {
    "content": "我看到在获取简历时遇到了一些问题。让我重新尝试获取99号简历的信息：",
    "refusal": null,
    "role": "assistant",
    "annotations": null,
    "audio": null,
    "function_call": null,
    "tool_calls": [
      {
        "id": "call_00_sZCE6Ojc5UCGaxTlsm808117",
        "function": {
          "arguments": "{\"resume_id\": 99}",
          "name": "get_mock_resume"
        },
        "type": "function",
        "index": 0
      }
    ]
  },
  {
    "role": "tool",
    "tool_call_id": "call_00_sZCE6Ojc5UCGaxTlsm808117",
    "content": "{\"error\": \"resumeid is false\"}"
  },
  {
    "content": "抱歉，我多次尝试获取99号简历都遇到了报错，系统提示\"resumeid is false\"，说明目前系统中无法正确处理这个简历编号的查询请求。\n\n这可能是因为：\n- **简历编号99不存在** 或已被删除\n- 该系统主要针对**岗位模拟面试**场景设计，需要先选择一个具体的岗位标签后再调用简历信息\n\n---\n\n如果您需要启动一次**岗位匹配模拟面试**，流程通常是：\n1. 从**推荐岗位列表**中选定一个岗位\n2. 系统会基于您的简历自动完成出题\n\n**您方便告诉我：**\n- 您希望匹配的是哪个具体岗位？\n- 或者您是否有其他有效的简历编号想查看？\n\n我可以根据您的岗位需求来协助您完成求职匹配与模拟面试~ 😊",
    "refusal": null,
    "role": "assistant",
    "annotations": null,
    "audio": null,
    "function_call": null,
    "tool_calls": null
  }
]
```
```
当前时间如下：

📅 **日期**：**2025年9月13日**
🕔 **时间**：**05:18（上午）**

需要我帮你查看其他时区的时间吗？😊
----------------------------------------
[
  {
    "role": "system",
    "content": "你是岗位匹配助手，需要简历时调用 get_mock_resume\n"
  },
  {
    "role": "user",
    "content": "帮我看下time"
  },
  {
    "content": "我来帮你查看一下时间。\n\n让我获取一下当前的时间信息。",
    "refusal": null,
    "role": "assistant",
    "annotations": null,
    "audio": null,
    "function_call": null,
    "tool_calls": [
      {
        "id": "call_00_XNhBiWjfrza65b4wAMLd5583",
        "function": {
          "arguments": "{}",
          "name": "get_mock_time"
        },
        "type": "function",
        "index": 0
      }
    ]
  },
  {
    "role": "tool",
    "tool_call_id": "call_00_XNhBiWjfrza65b4wAMLd5583",
    "content": "{\"datetime\": \"2025-09-13T05:18:47\"}"
  },
  {
    "content": "当前时间如下：\n\n📅 **日期**：**2025年9月13日**\n🕔 **时间**：**05:18（上午）**\n\n需要我帮你查看其他时区的时间吗？😊",
    "refusal": null,
    "role": "assistant",
    "annotations": null,
    "audio": null,
    "function_call": null,
    "tool_calls": null
  }
]
```
## 5. 工具说明书原则

- `description` 是模型眼中工具的**唯一现实**：拼错 → 模型看不见这个字段（API 静默忽略未知字段，不报错）；内容错 → 模型按假现实决策（抄来的"启动面试"说明书会让模型在用户说"开始面试"时调读简历工具）
- error 返回值也是喂给模型的 prompt：写模型能直接转述给用户的话（`"简历 {resume_id} 不存在，请检查 ID"`），不是写给人看的日志
- description 有**两层**（函数级 + 参数级 properties 里），改一层要检查另一层

## 6. 已知限制（M2 / M4 伏笔）

- `excute_tool` 没有 else：模型幻觉出不存在的工具名 → 返回 None → 观察值变成 `"null"`（M4：未知工具错误回传）
- observation 无截断：长工具返回值会让 messages 每轮滚雪球（M4：截断策略）
- max_index 耗尽后静默退出、无输出（M2：强制收敛 + "连续 K 次同工具同参数"死循环检测）
- `deepseek-reasoner` 不支持 function calling（M5 做 A/B 换模型时要显式拦截这个组合）

## 7. 面试话术（30 秒版）

> "我把 LangChain AgentExecutor 的黑盒拆开手写了一遍：模型声明 tool_calls 后，assistant 消息必须原样回传，工具结果包成带 tool_call_id 的 tool 消息，配对不对 API 直接 400；工具参数是 JSON 字符串要自己 loads，再用 `**` 展开传参，让分发逻辑和具体工具完全解耦。体会最深的一点是 LLM API 完全无状态——所谓的对话记忆，是客户端每一轮把全部历史重发一遍。"

## 8. 收尾遗留（本笔记写就时）

- 第 38 行参数级字段名 `descripition` 仍拼错（第 3 次提醒——键名拼错 = 模型看不见参数说明）
- 第 14 行 error 文案少了 f 前缀：`{resume_id}` 会被当字面量原样输出，应改 f-string
- 第 35 行 description 开头混进了一个中文引号 `"`
- 两个实测观察（Q3、999 号简历）跑完填进第 4 节
- 对照 `ai-agent-book/chapter4/execution-tools/execution_tools.py`：他做了什么我没做的 / 我做了什么他没做的，各记一条 → M1 正式关闭
