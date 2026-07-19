# Context Engine 执行计划

本文档用于后续新开 Chat 继续施工。它不是泛泛的设计备忘录，而是一份按阶段推进的实现清单：每一阶段说明要解决什么问题、要改哪些文件、怎么验收，以及本阶段应该学到什么。

当前目标不是给 `context_manager.py` 再补一个小功能，而是把 LifeOps Agent 的上下文系统升级成一个缩减版但完整的 Context 管理框架：

```text
保存完整历史
-> 切分成不可拆的 Context Unit
-> 建立预算、索引和压缩策略
-> 每轮 assemble 出真正发给模型的工作上下文
-> 对被压缩内容保留摘要、来源和恢复路径
```

当前对摘要目标的修正：

```text
Conversation Summary 的目标不是恢复原文，而是让 LLM 对窗口外对话保持足够好的任务认知。
只有工具结果、ID、金额、日期、确认范围等高风险事实，才要求精确保留或通过 Ref/Index 按需恢复。
```

## 0. 当前事实与施工边界

当前仓库的事实基线：

- `app/agents/agent.py` 里 `Agent.messages` 保存跨多轮的完整历史；LLM 请求输入已经改为由 `ContextEngine.assemble()` 生成。
- `instructions` 和 tool schemas 每轮动态生成，不直接累积进 `Agent.messages`。
- `app/context/context_manager.py` 目前做 Tool Observation 压缩：`none / summary / summary_reference / reference`。
- `app/context/context_ref_store.py` 可以保存并读取完整 Tool Result，已有 metadata、payload hash 和 TTL 过期校验；session/run 归属与更严格来源校验仍可继续加强。
- 已有第一版整体对话窗口管理：ContextEngine assemble、Context Unit、近似预算、滑动窗口、Rolling Summary 和 summary message。
- 已有 Context Index、旧 unit 检索、Context Inspect 和主动/被动/手动压缩触发。

本阶段明确不做：

- 不做向量数据库。
- 不做跨会话长期 Memory。
- 不做插件化 Context Engine。
- 不做多 Agent Context 隔离。
- 不做复杂异步后台压缩。
- 不做大型 LLM-as-judge 评测。

保留学习价值但缩小范围：

- 做一个最小可用的 `ContextEngine`。
- 先让所有 LLM 输入都经过 `ContextEngine.assemble()`。
- 先用字符数/近似 token 预算，后续再替换成精确 tokenizer。
- 先做确定性 metadata index，不引入 embedding。
- 先做 structured rolling summary，不做多层 summary DAG。

当前施工进度：

```text
1. Pass-through ContextEngine：已完成第一版。
2. Context Unit + Budget Report：已完成第一版。
3. Sliding Window + ContextStore：已完成第一版。
4. Rolling Summary：已完成第一版。
5. Tool Observation + Context Ref 升级：已完成第一版。
6. Context Index + 按需恢复：已完成第一版。
7. Context Inspector：已完成第一版。
8. 主动/被动/手动压缩触发：已完成第一版。
9. Context Eval：已完成第一版。
```

## 1. 总体架构

最终要形成这几个核心组件：

```text
Agent
  -> ContextEngine
       -> ContextStore
       -> ContextUnit
       -> ContextBudget
       -> ContextIndex
       -> ContextCompactor
       -> ContextAssembler
       -> ContextInspector
```

各组件职责：

| 组件 | 做什么 | 不做什么 |
|---|---|---|
| `ContextEngine` | 对外统一入口：ingest、assemble、compact、after_turn、inspect | 不直接实现每种压缩细节 |
| `ContextStore` | 保存完整原始历史和派生状态 | 不决定本轮哪些内容进模型 |
| `ContextUnit` | 定义不可拆分的上下文块 | 不做摘要生成 |
| `ContextBudget` | 估算输入预算，给 assembler/compactor 决策 | 不保证与供应商 token 100% 一致 |
| `ContextIndex` | 用 metadata 找回旧内容 | 不做语义向量检索 |
| `ContextCompactor` | 把旧内容替换成摘要、ref 或更短表示 | 不删除原始事实 |
| `ContextAssembler` | 编译本轮真正发给模型的 input messages | 不改业务数据 |
| `ContextInspector` | 输出本轮上下文组成、预算、压缩原因 | 不参与决策 |

核心心智模型：

```text
完整历史是事实源。
摘要和索引是派生缓存。
模型输入是每轮临时编译产物。
```

## 2. 阶段一：建立 pass-through ContextEngine

### 目标

先不改变模型行为，只改变控制点：让 `Agent` 不再直接把 `self.messages` 发给模型，而是通过 `ContextEngine.assemble()` 获取输入。

这一阶段的意义很大。它像先把铁路岔道铺好，火车暂时还走老路线，但之后所有压缩、窗口、索引都可以接在这个入口上。

### 推荐新增文件

```text
app/context/context_engine.py
app/context/context_types.py
```

### 推荐类型

`context_types.py`：

```python
from dataclasses import dataclass, field
from typing import Any, Literal

ContextUnitKind = Literal["user", "assistant", "tool", "turn", "summary", "system_note"]

@dataclass
class ContextAssembly:
    input_messages: list[Any]
    report: dict[str, Any] = field(default_factory=dict)
```

`context_engine.py`：

```python
class ContextEngine:
    def assemble(self, messages: list[Any], *, instructions: str | None = None, tools: list[Any] | None = None) -> ContextAssembly:
        return ContextAssembly(
            input_messages=list(messages),
            report={
                "mode": "pass_through",
                "message_count": len(messages),
            },
        )

    def after_turn(self, messages: list[Any]) -> dict[str, Any]:
        return {"compacted": False, "reason": "pass_through"}
```

### 修改点

在 `app/agents/agent.py`：

- 初始化 `self.context_engine = ContextEngine()`。
- 原本传给 Responses API 的 `input=self.messages` 改成：

```python
assembly = self.context_engine.assemble(
    self.messages,
    instructions=instructions,
    tools=tools,
)

response = self.client.responses.create(
    ...,
    input=assembly.input_messages,
)
```

- 把 `assembly.report` 写入 event log 或现有 context summary 附近。

### 验收标准

- 所有现有测试通过。
- 一轮普通聊天、一次 tool call、多轮 tool call 行为不变。
- 日志里能看到 `context_engine.mode = pass_through` 或等价信息。
- `Agent.messages` 仍然保留完整历史，本阶段不做裁剪。

### 学习重点

这一步学习的是“控制点迁移”：Context 管理不是某个压缩函数，而是模型输入生成链路的所有权转移。

## 3. 阶段二：定义 Context Unit 和预算报告

### 目标

把原始 `messages` 分析成更高层的单位，并输出预算报告。暂时仍然不裁剪。

为什么要有 Unit：

- Function Call 和 Tool Observation 不能被拆开。
- 一次用户输入到最终回答通常应作为一个 turn 理解。
- 待确认删除、失败结果、用户选择等内容需要被标为 protected，不能被普通摘要吞掉。

### 推荐新增/修改内容

`context_types.py` 增加：

```python
@dataclass
class ContextUnit:
    unit_id: str
    kind: ContextUnitKind
    messages: list[Any]
    protected: bool = False
    token_estimate: int = 0
    char_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
```

`context_engine.py` 增加内部方法：

```python
def _build_units(self, messages: list[Any]) -> list[ContextUnit]:
    ...
```

### Unit 切分规则

第一版可以简单做：

1. 普通 user message 单独成 unit。
2. 普通 assistant message 单独成 unit。
3. function_call + 紧随其后的 function_call_output 合并成一个 `tool` unit。
4. 如果无法识别配对，保守地把相关消息标为 `protected=True`。

后续再升级成完整 Turn Unit。

### Budget 报告

第一版不用精确 tokenizer，先用 JSON 字符数近似：

```text
estimated_tokens = ceil(json_char_count / 4)
```

输出报告字段建议：

```json
{
  "mode": "pass_through_with_units",
  "message_count": 42,
  "unit_count": 18,
  "estimated_input_tokens": 12345,
  "unit_breakdown": {
    "user": 8,
    "assistant": 6,
    "tool": 4
  },
  "protected_unit_count": 1
}
```

### 验收标准

- 现有行为仍不变。
- 日志能看出每轮有多少 messages、多少 units、多少 tool units。
- Function Call + Tool Observation 配对不会被拆散。
- 遇到未知格式时宁可 protected，也不要错误裁剪。

### 学习重点

这一步学习的是“压缩之前先建模”。如果没有不可拆边界，任何滑动窗口都可能把工具调用历史剪坏。

## 4. 阶段三：实现滑动窗口，但保留完整 Store

### 目标

让模型输入不再无限增长。先实现最简单可靠的工作上下文：

```text
历史摘要占位或空
+ protected units
+ 最近完整 units
+ 当前用户消息
```

本阶段先不生成 LLM 摘要，可以先用“被裁剪历史占位说明”验证 assemble 链路。

### 推荐新增文件

```text
app/context/context_store.py
app/context/context_budget.py
```

### ContextStore 第一版

可以先只在内存中工作，文件持久化放到下一阶段：

```python
class ContextStore:
    def __init__(self) -> None:
        self.full_messages: list[Any] = []
        self.summary_message: dict[str, Any] | None = None
```

但如果施工时精力允许，建议直接落盘：

```text
data/context/
  current_session.jsonl
  state.json
```

注意：不要把 `data/` 里的用户真实数据删掉或重写。

### Sliding Window 策略

配置建议：

```python
@dataclass
class ContextBudgetConfig:
    max_input_tokens: int = 32000
    reserved_output_tokens: int = 4000
    safety_margin_tokens: int = 2000
    recent_window_tokens: int = 12000
```

第一版 assemble：

1. 估算所有 units 的 token。
2. 从最新 unit 往前收集，直到达到 `recent_window_tokens`。
3. 总是保留 `protected=True` units。
4. 被挤出窗口的旧 units 暂时不进入模型。
5. 如果有被挤出的内容，在输入最前面插入一条 summary/system-note 风格消息：

```text
[Context note] Earlier conversation exists but has been compacted. Detailed summary is not available yet.
```

### 修改点

`Agent` 仍然 append 完整消息，但发送给模型的是 `assembly.input_messages`。

这里要特别小心：

- `self.messages` 是完整历史。
- `assembly.input_messages` 是本轮发送给模型的工作上下文。
- 不要用工作上下文覆盖完整历史。

### 验收标准

- 构造 20+ 轮对话后，发给模型的 input messages 数量不再无限增长。
- 完整历史仍然保存在 `Agent.messages` 或 ContextStore。
- Function Call + Observation 不会只保留半边。
- protected unit 即使很旧也会保留。
- 日志能看到：
  - 原始 message 数量
  - assemble 后 message 数量
  - 被窗口排除的 unit 数
  - protected unit 数

### 学习重点

这一步学习的是“完整历史”和“工作上下文”的分离。不要为了省 token 把事实源删掉。

## 5. 阶段四：Rolling Summary 历史摘要

### 目标

把被滑动窗口挤出去的旧内容压缩成结构化摘要。摘要不是不断追加，而是滚动替换：

```text
old_summary + newly_evicted_units -> new_summary
```

### 推荐新增文件

```text
app/context/context_compactor.py
```

### Summary 数据结构

建议 summary 不是一段自然语言，而是结构化 JSON，再包装成一条发给模型的 message：

```json
{
  "summary_version": 1,
  "source_unit_ids": ["u_001", "u_002"],
  "covered_until_unit_id": "u_002",
  "user_goals": [],
  "successful_actions": [],
  "failed_actions": [],
  "pending_confirmations": [],
  "important_entities": [],
  "open_questions": [],
  "notes": []
}
```

核心字段含义：

- `successful_actions`：只记录 runtime 确认成功的写入，不相信模型口头说“已保存”。
- `failed_actions`：保留失败原因，避免之后误以为成功。
- `pending_confirmations`：保留删除确认、批量操作范围等不能丢的信息。
- `important_entities`：Todo ID、Expense ID、日期、金额、ref_id 等。
- `source_unit_ids`：摘要来源，方便调试和失效。

### Summary 生成方式

第一版可以不用再调用 LLM，先用确定性规则摘要：

- 从 tool result / action records 提取成功和失败动作。
- 从 user message 提取粗略文本片段。
- 从 metadata 提取 tool name、entity ids、ref_id。

第二版再考虑调用 LLM 生成自然语言摘要，但要让 LLM 输出结构化 JSON，并保留 fallback。

### Assembly 顺序

建议最终输入顺序：

```text
1. 历史结构化摘要 message
2. protected old units
3. retrieved old units
4. recent full units
5. 当前用户输入
```

注意：`instructions` 仍然通过 Responses API 的独立参数传入，不混入历史消息。

### 验收标准

- 当旧内容被窗口挤出后，summary 会更新。
- 新 summary 替换旧 summary，而不是无限追加。
- summary 记录来源 unit ids。
- summary 中不包含未成功写入的虚假成功记录。
- summary 生成失败时，系统能退回到“扩大窗口/保留旧 summary/占位说明”的安全路径。

### 学习重点

这一步学习的是“摘要是派生状态，不是事实源”。摘要可以错、可以过期、可以重建，所以必须保留来源和恢复策略。

## 6. 阶段五：升级 Tool Observation 压缩和 Context Ref

### 目标

把当前 `context_manager.py` 的工具结果压缩纳入 Context Engine 思路：不只是看体积，还要看用户需求、精确保留和按需恢复。

### 已解决的原始问题

- Todo summary 固定 top 5，用户问 6 条时第 6 条可能丢失。
- `summary` 策略没有 ref，摘要丢掉的字段无法恢复。
- `read_context_ref` 只做简单 `ctx_` 前缀和文件存在校验。
- ref 没有 session/run 归属、来源、TTL。

### 推荐任务

#### 5.1 给查询工具增加 limit/sort/filter

优先从源头减少 observation：

- `list_todos(limit=..., status=..., sort=...)`
- expense 查询支持时间范围、category、limit。

验收：

- 用户要 8 条时，工具尽量只返回 8 条相关数据。
- 如果数据不足，明确返回实际数量。

#### 5.2 动态 summary 数量

`compact_tool_output()` 不再固定 top 5，而是接收需求参数：

```python
compact_tool_output(
    tool_name,
    result_json,
    requested_count=None,
    required_fields=None,
)
```

验收：

- 用户问“最值得先做的 6 项”，summary 至少保留 6 项的 title/id/priority/due_date。

#### 5.3 精确保留与按需恢复规则

只要结果被截断，并且后续可能需要精确字段，就生成 ref。

建议策略：

```text
small result -> inline
medium result + no exact follow-up risk -> summary
medium/large result + exact follow-up risk -> summary + ref
large result -> summary + ref
```

#### 5.4 Ref metadata

`context_ref_store.py` 增加 metadata：

```json
{
  "ref_id": "ctx_xxx",
  "created_at": "...",
  "expires_at": "...",
  "session_id": "...",
  "run_id": "...",
  "tool_name": "list_todos",
  "source_unit_id": "u_123",
  "payload_hash": "..."
}
```

`read_context_ref` 校验：

- ref 必须存在。
- ref 必须属于当前 session 或允许的 scope。
- ref 未过期。
- ref_id 必须来自 runtime 记录，不接受模型编造。

### 验收标准

- 被摘要丢掉的完整结果能通过真实 ref 恢复。
- 编造 ref_id 返回安全错误，不泄露其他文件。
- 过期 ref 返回明确错误。
- summary/ref 策略能从日志中解释。

### 学习重点

这一步学习的是“压缩不是删除，而是替换成可恢复表示”。尤其在工具结果里，ID、金额、日期、状态这些字段不能随便丢。

当前完成状态：

- `list_todos` 已支持 `limit/status/sort`，可以从源头减少不必要 observation。
- `compact_tool_output()` 已能根据用户请求条数调整摘要数量。
- 被摘要截断但可能继续使用的工具结果会升级为 `summary_reference`，保留摘要和 ref。
- `context_ref_store.py` 已增加 `created_at/expires_at/payload_hash`，并拒绝过期 ref。
- 后续仍可加强 session/run 归属校验和 ref 清理策略。

## 7. 阶段六：Context Index 和简单检索

### 目标

当旧内容被 summary 替代后，仍然可以按当前用户问题找回少量相关旧 unit 或有效 ref。

这一阶段已经完成第一版。它解决的不是“把所有历史重新塞回模型”，而是：

```text
当前问题需要精确信息
-> summary 不足以回答
-> 用 Index 判断应该恢复哪一小块旧上下文
-> 只把相关 unit/ref 放回 working context
```

第一版不做向量，用确定性 metadata index：

```text
unit_id
kind
created_at
tool_names
entity_ids
keywords
action_status
ref_ids
protected
```

### 按需恢复原则

按需恢复不是让摘要可逆，也不是把完整历史再次全量发送给 LLM。它只在当前请求需要精确事实时，把最小必要上下文恢复进本轮工作上下文。

需要触发按需恢复的信号：

- 用户提到明确 ID、ref_id、日期、金额、Todo 标题、Expense 描述等可定位字段。
- 用户要求继续操作旧结果，例如“完成刚才第 6 个”“把那笔 38 元的消费改掉”。
- 当前 summary 只包含概括，但缺少执行工具所需的精确参数。
- pending confirmation、失败重试、批量操作范围等交互状态跨过了窗口边界。

不应该触发按需恢复的情况：

- 用户只是要普通总结、解释或闲聊。
- summary 已经足够回答，并且不涉及写入或精确字段。
- ref 已过期、来源不可信、跨 scope 或无法被 runtime 验证。

### 推荐新增文件

```text
app/context/context_index.py
```

### 检索策略

简单规则：

- 当前用户输入中出现 `todo id / expense id / ref_id`，优先找相关 unit。
- 出现 tool/domain 关键词，如 todo、expense、sleep、activity，找对应 tool units。
- pending confirmation 永远进入 working context。
- 最近已经在窗口里的 unit 不重复检索。
- 如果找到的是 `summary_reference`，优先放入摘要；只有当前请求需要精确字段时才读取完整 ref。
- 如果需要读取 ref，必须经过 `read_context_ref` 的有效性校验，不接受模型编造的 ref_id。

### Assembly 中加入 retrieved units

顺序：

```text
summary
protected units
retrieved old units
recent units
```

其中 `retrieved old units` 应记录恢复原因，例如：

```json
{
  "unit_id": "u_123",
  "reason": "matched_todo_id",
  "matched_fields": ["todo_id"],
  "source": "context_index"
}
```

如果恢复的是 ref，report 中应记录：

```json
{
  "ref_id": "ctx_abc",
  "reason": "current_request_requires_exact_fields",
  "status": "loaded"
}
```

### 验收标准

- 摘要后用户追问某个 Todo ID，能找回相关旧 unit 或有效 ref。
- 检索数量有预算限制。
- retrieved units 出现在 inspect/report 里。
- 没找到时明确不编造。
- summary 足够回答时，不读取完整 ref。
- ref 过期、伪造或不属于允许 scope 时，拒绝恢复并给出安全错误。
- 按需恢复不会破坏 function_call / observation 配对，也不会把无关旧历史重新塞回模型。

### 学习重点

这一步学习的是“索引不是记忆，按需恢复也不是可逆摘要”。索引只是帮你从完整历史或 ref 中找回当前请求真正需要的少量上下文；Conversation Summary 负责认知连续性，Index/Ref 负责高风险事实的精确恢复。

当前完成状态：

- 已新增 `app/context/context_index.py`，第一版使用确定性metadata，不使用embedding。
- Index 会从旧 `ContextUnit` 提取 tool name、entity id、ref_id、domain关键词和action状态。
- `ContextEngine.assemble()` 会在滑动窗口裁剪后，对 evicted old units 做按需检索，并把 retrieved unit/ref 插入本轮working context。
- 只有当前用户请求出现精确字段、ref、日期/金额、后续写操作或“刚才第N项”等信号时才触发恢复；普通总结请求不会读取完整ref。
- assembly report 已包含 `retrieved_unit_count`、`retrieved_units`、`retrieved_ref_count`、`retrieved_refs` 和 `retrieval_query`，用于解释恢复原因。
- 伪造、不存在或过期ref不会插入上下文，只会在report中记录 rejected 状态。
- 当前仍是轻量规则：不做语义向量检索，不做跨session scope校验，不保证理解所有自然语言指代。

## 8. 阶段七：Context Inspector 和可观测性

### 目标

每轮都能回答：

```text
这次模型到底看到了什么？
为什么这些内容被保留？
为什么那些内容被压缩？
如果模型答错，是丢了什么上下文？
```

### Inspector 报告建议

每次 assemble 输出：

```json
{
  "mode": "windowed_with_summary",
  "raw_message_count": 80,
  "assembled_message_count": 24,
  "raw_estimated_tokens": 52000,
  "assembled_estimated_tokens": 14500,
  "summary_tokens": 1200,
  "recent_window_tokens": 9800,
  "retrieved_unit_count": 2,
  "protected_unit_count": 1,
  "evicted_unit_count": 34,
  "compaction_trigger": "soft_limit_after_turn"
}
```

### 日志接入点

可以复用当前 events/llm logging：

- LLM request 前记录 `context.assembly`.
- after_turn 后记录 `context.compaction`.
- ref 读取时记录 `context.ref_read`.
- ref 被拒绝时记录 `context.ref_rejected`.

### 可选 CLI/调试命令

后续可以加一个内部命令：

```text
/context
```

输出本轮 context 组成。但如果 CLI 改动成本高，先只写日志。

### 验收标准

- 每轮能看到压缩前后 token/message 估算。
- 能看出 summary、recent、retrieved、protected 的占比。
- 能解释触发压缩的原因。
- 出问题时能定位是 summary 丢失、index 未召回，还是 tool result 本身被截断。

### 学习重点

这一步学习的是“Context 系统必须可解释”。没有 inspector，压缩 bug 会非常隐蔽。

当前完成状态：

- 已新增 `app/context/context_inspector.py`，不改变Context决策，只解释已有 assembly report。
- `ContextEngine.assemble()` 会把 Inspector 输出放在 `assembly.report.inspection`。
- Inspector 当前包含：
  - `overview`：mode、原始/组装后消息数、近似token和节省比例。
  - `composition`：summary、placeholder、protected、retrieved、recent、evicted 的计数。
  - `decisions`：windowing、summary、retrieval 的决策状态和关键参数。
  - `diagnostics`：placeholder summary、精确请求未命中、ref rejected 等调试提示。
- 当前没有新增CLI命令；先复用现有 `llm.requested` event 中的 `context.context_engine` 日志。

## 9. 阶段八：主动、被动、手动压缩触发

### 目标

实现三类压缩触发：

| 类型 | 触发时机 | 用途 |
|---|---|---|
| 主动压缩 | 每轮结束后，超过 soft limit | 提前维护上下文，不等到爆窗 |
| 被动压缩 | 发请求前超过 hard limit，或 provider 返回 context overflow | 保证请求能发出去 |
| 手动压缩 | 用户输入 `/compact` 或内部调试入口 | 学习和排障 |

### 推荐配置

```python
soft_limit_tokens = 24000
hard_limit_tokens = 30000
max_input_tokens = 32000
reserved_output_tokens = 4000
safety_margin_tokens = 2000
```

### 行为规则

主动压缩：

```text
after_turn()
  -> 如果 raw_estimated_tokens > soft_limit
  -> compact evicted old units
  -> 更新 summary/index/state
```

被动压缩：

```text
assemble()
  -> 如果 assembled_estimated_tokens > hard_limit
  -> 强制缩小 recent window
  -> 必要时只保留 summary + protected + current user
```

手动压缩：

```text
/compact
  -> 立即把窗口外旧内容滚入 summary
  -> 输出 compact 报告
```

### 验收标准

- 长对话中主动压缩会在请求爆窗前发生。
- 被动压缩能保证请求输入低于预算。
- 手动 compact 后 recent window 变短，summary 更新。
- 压缩不会破坏 function_call / observation 配对。

### 学习重点

这一步学习的是“压缩是生命周期管理，不是单次函数”。真正的系统需要在不同时间点做不同强度的决策。

当前完成状态：

- `ContextBudgetConfig` 已区分 `soft_limit_tokens` 和 `hard_limit_tokens`。
- 主动触发发生在 `ContextEngine.after_turn()`：只有完整历史超过 soft limit 时，才把窗口外旧Unit滚动压缩进 deterministic summary；不调用LLM。
- 被动触发发生在 `ContextEngine.assemble()`：如果组装后的输入超过 hard limit，会缩小 recent window 做预算保护；不生成新summary，不调用LLM。
- 手动触发发生在 CLI `/compact`：命令不进入普通 `Agent.messages`，而是调用 `Agent.compact_context()` 执行内部维护。
- 手动 `/compact` 会先更新 deterministic summary，再用一次无工具LLM请求生成 `natural_language_summary`；该字段只作为软上下文，结构化summary和完整历史仍是事实源。
- `context.compaction` event 会记录主动或手动压缩报告；`llm.request/response` 会记录手动LLM summary边界。

## 10. 阶段九：Context Eval

### 目标

用少量高价值测试证明压缩前后关键行为一致。

不要回到 70 个大 UAT。Context 阶段需要的是针对性强、可解释的回归。

### 推荐测试文件

```text
tests/test_context_engine.py
tests/test_context_windowing.py
tests/test_context_ref_recovery.py
tests/test_context_eval_cases.py
```

### 必测用例

1. Function Call + Observation 配对不能被拆散。
2. 20+ 轮对话后 assembled input 不再无限增长。
3. protected pending confirmation 即使很旧也保留。
4. rolling summary 替换旧 summary，不无限追加。
5. 用户请求 6 条 Todo 时，summary 不能只保留 5 条。
6. 摘要后继续完成指定 Todo，ID 必须正确。
7. 摘要后追问某笔 expense，金额和日期必须正确。
8. 历史 summary 只包含成功 WRITE，不包含失败写入或模型口头成功。
9. 批量删除确认跨压缩后，确认范围不能丢失。
10. 编造/过期/跨 session ref 不能读取。
11. summary 足够回答时不读取完整 ref；summary 不足且涉及精确字段时才按需恢复。
12. 按需恢复只带回相关旧 unit/ref，不把完整历史重新塞回模型。
13. 压缩前后 tool choice 和 tool arguments 保持关键一致。

### 验收标准

- 单元测试覆盖 deterministic 部分。
- 少量真实 LLM case 只用于验证模型行为，不作为所有逻辑的唯一依据。
- 每个失败能定位到：
  - assemble 错误
  - compaction 错误
  - index 未召回
  - ref 恢复失败
  - 模型自身误用

### 学习重点

这一步学习的是“Context Eval 要测不变量”。不要只测回答好不好听，要测压缩前后事实、权限、ID、状态是否一致。

当前完成状态：

- 已新增 `tests/test_context_eval_cases.py` 作为Context阶段九Eval测试层，不调用真实LLM，重点验证确定性压缩不变量。
- Eval覆盖精确Todo后续操作只召回相关旧Unit、Expense金额/日期恢复、失败WRITE只进入失败摘要、protected确认状态跨窗口和被动压缩保留，以及Ref恢复不重新插入完整历史。
- 与既有 `tests/test_context_engine.py`、`tests/test_context_manager.py`、`tests/test_context_ref_store.py` 一起形成Context回归套件。

## 11. 推荐施工顺序总表

按这个顺序施工，风险最低：

| 顺序 | 阶段 | 主要产物 | 行为是否改变 |
|---|---|---|---|
| 1 | Pass-through Engine | `context_engine.py`, `context_types.py` | 已完成第一版 |
| 2 | Unit + Budget Report | unit breakdown, token estimate | 已完成第一版 |
| 3 | Sliding Window | assemble 后 input 变短 | 已完成第一版 |
| 4 | Rolling Summary | summary state/message | 已完成第一版 |
| 5 | Tool Observation + Ref 升级 | dynamic summary, `summary_reference`, metadata ref | 已完成第一版 |
| 6 | Index + 按需恢复 | deterministic index, retrieved units/ref loading | 已完成第一版 |
| 7 | Inspector | context report/logs | 已完成第一版 |
| 8 | Triggers | active/passive/manual compact | 已完成第一版 |
| 9 | Eval | context regression tests | 已完成第一版 |

已经完成的第一刀：

```text
先让 Agent 的 LLM input 只从 ContextEngine.assemble() 出来。
即使第一版 assemble 只是原样返回 messages，也要先完成这一步。
```

## 12. 后续新 Chat 的建议开场指令

Context阶段已经完成第一轮收口。后续如果要回看Context问题，可以这样开新 Chat：

```text
请阅读 AGENTS.md、PROJECT_CONTEXT.md、LEARNING_PROGRESS.md、CONTEXT_ENGINE_IMPLEMENTATION_PLAN.md。
然后检查Context Eval测试与当前Context实现是否仍一致。
要求：
1. 不重复重写已有 ContextEngine / ContextStore / Rolling Summary / summary_reference / ContextIndex / ContextInspector / Triggers。
2. 聚焦压缩前后关键行为回归，不引入向量数据库或长期Memory。
3. 优先复用现有预算、summary、index、inspector report 和 `/compact` 触发。
4. Eval 重点验证 tool choice、tool arguments、写入安全、ID/金额/日期、pending confirmation 和 ref 恢复是否一致。
5. 跑相关 Context 测试和全量回归。
```

如果继续下一阶段：

```text
请阅读 AGENTS.md、PROJECT_CONTEXT.md、LEARNING_PROGRESS.md。
先制定 MEMORY_STATE_IMPLEMENTATION_PLAN.md。
重点是最小Memory State：明确授权保存、查看、删除、后续读取，以及和Context Summary/业务数据的边界。
```

## 13. 完成标准

这一整轮 Context Engine 阶段完成时，应满足：

- `Agent.messages` 或 ContextStore 保存完整历史，但不会再被无脑全量发送给模型。
- 每轮发给模型的 input 都由 ContextEngine 编译出来。
- Function Call + Observation 配对不会被破坏。
- 长对话有滑动窗口和历史摘要。
- 被压缩的工具结果有真实、受控、可过期的恢复路径。
- 当前请求需要精确字段时，可以通过 Index/Ref 按需恢复少量相关旧上下文。
- 普通对话摘要不要求可逆恢复原文，但要维持用户目标、偏好、决定、开放问题和当前任务的认知连续性。
- 摘要有来源、版本和可解释的更新规则。
- 当前用户问题可以从旧历史中召回少量相关 unit。
- 每轮日志能解释 context 的组成、预算和压缩原因。
- 压缩前后关键工具选择、写入安全、事实字段和确认状态有回归测试保护。
