# Memory State 实现计划

## 目标

本阶段实现 LifeOps Agent 的第一版长期 Memory。它服务于“定制化个人生活助理”这个产品方向，但仍保持小而清晰：

- 让 Agent 能读取用户预先写好的个人画像。
- 让 Agent 能在用户授权后保存长期事实、偏好、目标和约束。
- 让 Agent 在后续建议、计划、复盘和任务拆解时使用相关 Memory。
- 明确区分 Profile、Semantic Memory、Context Summary、业务数据和日志。

本阶段先做可解释、可观察、可删除的基础设施，不做自动推断型复杂记忆系统。

## 两条硬边界

1. Profile Memory 来自预加载 Markdown，程序只读，不允许修改。
2. 其他可写 Semantic Memory 只能在用户授权后写入；工具成功写入才算真正保存。

## Memory 分类

### 1. Read-only Profile Memory

用户画像由用户或开发者在启动前写好，例如：

```text
data/memory/profile.md
```

它用于描述用户长期稳定背景，例如：

- 用户身份和角色
- 长期生活目标
- 沟通偏好
- 学习偏好
- 作息、预算、健康、任务安排等生活约束

规则：

- Runtime 启动或每轮请求前读取。
- 可以注入到本轮模型上下文。
- 程序不能修改、覆盖、合并或自动重写该文件。
- 如果用户想改画像，应由用户直接编辑 Markdown，或后续新增显式“导入/替换 Profile”的人工流程。

### 2. Writable Semantic Memory

Semantic Memory 保存用户授权后的长期事实、偏好、目标和约束。

示例：

- “用户希望解释代码时优先使用中文。”
- “用户不喜欢过度平台化的架构。”
- “用户希望晚上不安排高强度学习任务。”
- “用户当前长期目标是构建 LifeOps Agent。”

规则：

- 用户当前输入必须包含明确授权信号，才允许写入。
- 写入必须通过 Tool 完成，assistant 口头说“我记住了”不算。
- 支持查看和删除。
- 删除后不能再注入上下文。
- 不从 Context Summary、Tool Observation、日志或业务数据中自动生成。

## 明确不做

本阶段不做：

- 自动修改 `profile.md`。
- 后台自动扫描聊天记录并写 Memory。
- LLM 静默判断“这像偏好”后自动保存。
- 向量数据库、embedding 或复杂语义检索。
- Episodic Memory，不把完整对话、日志、工具执行历史升级为长期记忆。
- Procedural Memory，不做动态工作流、策略或规则学习。
- 把 Todo、Expense、Sleep、Daily Log 等业务数据复制进 Memory。
- 重写 `ContextEngine`，Memory 只接入现有上下文组装路径。

## 建议文件结构

```text
app/memory/
  __init__.py
  memory_types.py
  profile_loader.py
  memory_store.py
  memory_retriever.py
  memory_context.py

data/memory/
  profile.md
  semantic_memories.json

tests/
  test_memory_store.py
  test_memory_profile_loader.py
  test_agent_memory_context.py
```

说明：

- `profile_loader.py` 只负责读取 `profile.md`。
- `memory_store.py` 负责 Semantic Memory 的增删查和本地 JSON 持久化。
- `memory_retriever.py` 负责第一版简单检索。
- `memory_context.py` 负责把 Profile 和检索到的 Memory 转成可注入模型的上下文片段。

## 数据模型

第一版 `MemoryItem` 保持简单：

```text
id: str
type: fact | preference | goal | constraint
content: str
source: user_authorized
created_at: str
updated_at: str | None
status: active | deleted
tags: list[str]
```

设计原则：

- `content` 保留用户授权后的简明事实。
- `status=deleted` 的记录可以保留在存储文件中，但默认查询和注入必须排除。
- `tags` 第一版可以由工具参数显式传入，也可以由简单规则生成，不使用 LLM 自动复杂分类。

## Tool 设计

新增 Memory 工具：

1. `save_memory`
   - effect: `WRITE`
   - 保存用户授权后的 Semantic Memory。
   - 参数建议：`type`、`content`、`tags`。
   - 必须经过 `authorized_write_tools(user_input)` 授权。

2. `list_memories`
   - effect: `READ`
   - 查看 active Memory。
   - 可按 `type` 或 `tag` 过滤。

3. `delete_memory`
   - effect: `WRITE`
   - 软删除指定 Memory。
   - 必须经过当前用户输入授权。

Profile 不提供写工具。第一版最多提供只读查看能力，或者直接通过 Memory Context 注入，不暴露单独工具。

## 写入授权策略

扩展 `app/runtime/write_policy.py`：

- 当用户输入包含明确长期记忆授权信号时，才授权 `save_memory`。
- 当用户输入包含明确删除记忆信号时，才授权 `delete_memory`。

授权表达示例：

```text
记住...
长期记住...
以后默认...
把这个偏好保存下来...
忘掉...
删除这条记忆...
不要再记住...
```

注意：

- “我喜欢早上学习”只是陈述，不自动保存。
- “记住我喜欢早上学习”才授权保存。
- “我现在不喜欢早上学习了”不自动覆盖旧 Memory；需要用户表达“修改/删除/更新这条记忆”。

## 读取与注入路径

第一版采用简单检索：

```text
当前用户输入
-> 读取只读 profile.md
-> 从 Semantic Memory 中按 type/tag/关键词选择少量 active items
-> 生成 Memory Context 片段
-> 注入到本轮 LLM input 或 instructions 附加段
```

注入内容应明确来源：

```text
Long-term profile:
- ...

Relevant saved memories:
- [mem_xxx] ...
```

要求：

- Profile 和 Semantic Memory 不写入 `Agent.messages`。
- Profile 和 Semantic Memory 不进入 Rolling Summary。
- 每轮都从独立 Memory 层读取当前可用内容。
- 删除后的 Memory 不得被注入。

## 与 System Prompt 和 Context 窗口的关系

System Prompt、只读 Profile 和 Semantic Memory 都不应该被当作普通对话历史处理。

分层应保持为：

```text
System Prompt / instructions
Read-only Profile Memory
Relevant Semantic Memory
Conversation ContextAssembly
Tool Schemas
```

规则：

- `instructions` 继续每轮重新生成，并作为独立参数发送给模型。
- `profile.md` 每轮从 Memory/Profile 层读取，作为只读 Profile Context 注入。
- 相关 Semantic Memory 每轮从 Memory Store 检索，作为 Memory Context 注入。
- Profile 和 Semantic Memory 不追加到 `Agent.messages`。
- Profile 和 Semantic Memory 不参与 Rolling Summary。
- Profile 和 Semantic Memory 不被 ContextIndex 当作旧对话 unit 召回。
- Profile 和 Semantic Memory 不通过 Tool Observation 压缩路径处理。
- 如果上下文预算紧张，可以对本轮注入的 Profile/Memory 片段做规则化裁剪，但不能把它们压缩进 Conversation Summary，也不能让 ContextEngine 把它们作为窗口外历史移除。

一句话边界：

> Profile 和 Memory 是每轮重新装配的长期状态输入；ContextEngine 管理的是 conversation working context，不能把长期状态当作可被遗忘的聊天历史。

## 与 ContextEngine 的关系

现有 `ContextEngine` 继续负责：

- 会话历史窗口
- Rolling Summary
- Tool Observation 压缩
- Context Ref 恢复
- Context report 和 inspection

Memory 不重写 ContextEngine。推荐接入点：

1. `Agent._prepare_turn()` 或 `_request_llm()` 前读取 Memory Context。
2. 将 Memory Context 作为受控上下文片段传给 `ContextEngine.assemble()`，或在 `assemble()` 返回前插入。
3. 在 `assembly.report` 或 LLM request context 中记录本轮 Memory 使用情况。

需要避免：

- 把 Memory 当作普通 user/assistant 历史消息追加到 `self.messages`。
- 把 `profile.md` 内容压缩进 Conversation Summary。
- 让 ContextIndex 把 Memory 当作旧对话 unit 召回。

## 可观测性

日志至少记录：

- `profile_loaded`: 是否加载、字符数、路径，不记录过多敏感正文。
- `memory_retrieved`: 本轮注入的 memory ids、type、命中原因。
- `memory_saved`: 写入结果、memory id、type。
- `memory_deleted`: 删除结果、memory id。
- `memory_context_chars`: 本轮 Memory Context 体积。

这些日志用于判断产品行为是否符合预期，避免只看模型回答。

## 测试清单

### Store 与 Profile

- `profile.md` 存在时可以读取。
- `profile.md` 不存在时返回空 Profile，不阻断 Agent。
- Profile loader 不写文件。
- Semantic Memory 可以保存、列出、软删除。
- 删除后的 Memory 默认不出现在 active 查询中。

### 授权边界

- 用户只是陈述偏好时，不授权 `save_memory`。
- 用户明确“记住”时，授权 `save_memory`。
- 用户明确“删除/忘掉记忆”时，授权 `delete_memory`。
- assistant 口头声称保存但没有成功工具结果时，不能算保存成功。

### Agent 集成

- 每轮可加载 Profile Context。
- 授权后保存的 Memory 会在相关请求中注入。
- 删除后的 Memory 不再注入。
- Memory Context 不进入 `Agent.messages`。
- Memory Context 不进入 Context Summary。
- Tool Observation 和业务数据不会自动生成 Memory。

## 分阶段实施

### Step 1: 计划与骨架

- 新增本计划文档。
- 新增 `app/memory/` 模块骨架。
- 新增 `data/memory/profile.md` 示例。

### Step 2: 只读 Profile

- 实现 `ProfileLoader`。
- 在 Agent 请求前加载 Profile。
- 将 Profile 作为只读上下文注入。
- 增加 Profile 只读测试。

### Step 3: Semantic Memory Store

- 实现 `MemoryItem` 和 JSON Store。
- 支持 save/list/delete。
- 增加 Store 单元测试。

### Step 4: Memory Tools 与授权

- 注册 `save_memory`、`list_memories`、`delete_memory`。
- 扩展 `authorized_write_tools()`。
- 将 Memory 工具纳入 capability map。
- 增加授权测试。

### Step 5: 简单 Retrieval 与 Context 注入

- 实现关键词/type/tag 简单检索。
- 每轮注入少量相关 Memory。
- 记录 Memory 使用日志。
- 增加 Agent 集成测试。

### Step 6: 文档同步

- 代码完成后更新 `PROJECT_CONTEXT.md`。
- 若学习阶段状态变化，再更新 `LEARNING_PROGRESS.md`。
- `CHANGELOG.md` 只有在用户明确要求阶段记录时再更新。

## 后续再考虑

Memory v1 稳定后，再考虑：

- Profile 管理界面或显式导入命令。
- Memory 更新/合并策略。
- 冲突检测。
- 过期时间和重要性权重。
- 高级 Memory Retrieval。
- 向量检索。
- Interaction State 和 Task State。
