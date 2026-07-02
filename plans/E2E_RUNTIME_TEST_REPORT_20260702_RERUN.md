# E2E Runtime Test Report Rerun: Skill, Context, Memory, MCP

## 总体结论

执行日期：2026-07-02

本轮工作包含三段：

1. 清理第一次 E2E 记录。
2. 修复首轮报告暴露的主要缺口并重跑真实 LLM E2E。
3. 根据第二轮真实 E2E 新暴露的问题继续补丁，并用本地聚焦回归验证。

第一次记录已清理：

- 已删除第一次 raw result：`logs/e2e_runtime_run_20260702_135246`
- 已删除第一次 session：`session_20260702_135246_696040` 到 `session_20260702_140048_098998`
- 已删除第一次报告：`plans/E2E_RUNTIME_TEST_REPORT_20260702.md`
- 已删除第一次相关 context ref。

第二轮真实 E2E 原始结果：

- `logs/e2e_runtime_run_20260702_141549/raw_results.json`

第三轮尝试：

- `logs/e2e_runtime_run_20260702_142614/raw_results.json`
- 这轮不是有效真实 E2E：所有 LLM 请求都快速返回 `llm_request_failed`，原因是当前会话的提权/真实网络执行通道被用量限制挡住。不要把这轮作为测试结论。

## 修复内容

### 1. Todo 写授权修复

修复文件：

- `app/runtime/write_policy.py`
- `tests/test_write_policy.py`

修复点：

- 支持中英混合 Todo 创建表达：
  - `添加一个 todo`
  - `再添加一个 todo`
- 支持完成表达：
  - `把刚才那个“...”的 todo 标记为完成`

验证：

- 新增并通过：
  - `test_mixed_language_todo_add_authorizes_write`
  - `test_repeat_mixed_language_todo_add_authorizes_write`
  - `test_mark_quoted_todo_complete_authorizes_write`

### 2. News helper 参数与空结果保护

修复文件：

- `app/tools/tool.py`
- `app/skills/news/SKILL.md`
- `tests/test_tool_authorization.py`

修复点：

- `run_news_helper` 现在支持受控 `source_ref_id`。
- `source_ref_id` 只接受 Runtime 签发的 `ctx_` ref。
- ref 必须指向 `fetch_news_source` 的结果，不能指向任意 context ref。
- 工具侧从 `full_result.content` 取 HTML，避免模型复制 20 万字符 HTML 造成 JSON 参数损坏。
- parser helper 返回空列表时，返回结构化 `news_helper_empty_result`，防止模型把空解析结果说成具体新闻条目。
- `news/SKILL.md` 明确要求大 source 使用 `source_ref_id`，不要复制巨大 HTML。

验证：

- 新增并通过：
  - `test_news_helper_can_parse_runtime_source_ref`
  - `test_news_helper_rejects_non_source_ref`

### 3. Memory 未授权偏好与学习偏好检索

修复文件：

- `app/prompts/system_prompt.py`
- `app/memory/memory_retriever.py`
- `tests/test_memory_retriever.py`

修复点：

- 核心 prompt 明确：用户只是陈述偏好或事实、没有要求保存时，不要调用 `list_memories` 来确认是否保存。
- `learning` tag 可以被中文“学习 / 学 / 怎么学”命中。
- `runtime` tag 可以被中文“运行时”命中。

验证：

- 新增并通过：
  - `test_retrieves_learning_tag_for_chinese_study_question`

### 4. 写入成功声明误判修复

修复文件：

- `app/runtime/write_policy.py`
- `tests/test_write_policy.py`

修复点：

- `has_write_success_claim()` 排除教学/否定语境，例如：
  - “只有成功的 WRITE action 才能证明真的保存了”
  - “无法保存”
  - “没有写入”

验证：

- 扩展并通过：
  - `test_success_claim_detection_ignores_failure_message`

## 本地聚焦回归

命令：

```powershell
$env:UV_CACHE_DIR='D:\lifeops-agent\.uv-cache'
uv run python -m unittest tests.test_write_policy tests.test_memory_retriever tests.test_tool_authorization tests.test_agent_news_skill -v
```

结果：

- 37 tests passed.

覆盖模块：

- 写授权策略
- Memory retriever
- Tool authorization
- News Skill Agent loop

## 第二轮真实 E2E 结果

第二轮真实 E2E 是在 Todo 创建、News helper `source_ref_id`、Memory no-progress prompt 修复后执行的真实 LLM 验收。

| Case | 结果 | Session | 结论 |
|---|---|---|---|
| CASE-01 News Skill routing | 通过 | `session_20260702_141549_462730` | News routing / reference / source / helper 均完成 |
| CASE-02 Skill Reference safety | 通过 | `session_20260702_141654_612933` | `ephemeral_reference` 正常，helper 结果非空 |
| CASE-03 Reference 越权拒绝 | 通过 | `session_20260702_141840_952682` | 未读取路径穿越或 missing ref |
| CASE-04 News Source + Helper | 通过 | `session_20260702_141850_448715` | Blog source + helper 闭环完成 |
| CASE-05 ContextEngine old Todo follow-up | 部分通过 | `session_20260702_141951_806786` | Todo 创建成功，但完成操作因授权表达漏匹配失败；已在后续补丁修复 |
| CASE-06 Context Ref 恢复 | 通过 | `session_20260702_142157_354335` | 37 条 Todo 触发 `reference`，`read_context_ref` 恢复成功 |
| CASE-07 Memory 未授权不保存 | 通过 | `session_20260702_142226_440860` | 未保存，且不再 no-progress |
| CASE-08 Memory 授权保存/注入 | 部分通过 | `session_20260702_142237_520648` | 保存成功，但“怎么学”未命中 learning memory；已在后续补丁修复 |
| CASE-09 Memory 删除 | 通过 | `session_20260702_142253_611760` | 删除成功，后续不再注入 |
| CASE-10 MCP 成功/失败 | 通过 | `session_20260702_142318_983044` | PKG-001 成功，PKG-404 `package_not_found` |
| CASE-11 `/compact` 可选 | 条件通过 | `session_20260702_142330_484383` | 历史不足，返回无窗口外上下文 |

第二轮主 case 统计：

- 通过：8
- 部分通过：2
- 失败：0

后续补丁后，部分通过的两个问题均已有本地回归测试覆盖，但由于当前会话真实网络执行被用量限制挡住，还没有完成第三轮有效真实 LLM E2E。

## 关键 Case 细节

### CASE-01

输入：

```text
总结今天 Hugging Face 上的热门论文和博客，给我一个中文 AI 简报。
```

结果：

- `loaded_skills = ["news"]`
- 工具链：
  - `get_current_time`
  - `read_skill_reference` x4
  - `fetch_news_source` x2, `reference`
  - `run_news_helper` x2, `summary`
- 首轮 News helper 参数问题已消失。

### CASE-04

输入：

```text
把 Hugging Face Blog 最近热门文章整理成中文简报，要基于来源内容，不要泛泛而谈。
```

结果：

- `fetch_news_source` 成功读取 `hf_blog`。
- `run_news_helper` 成功解析 Blog source，结果触发 `reference`。
- 最终回答生成了基于列表页可见信息的中文简报。

### CASE-05

输入链：

- 添加 Todo：成功。
- 添加第二个 Todo：成功。
- 长对话拉伸：完成。
- 标记旧 Todo 完成：第二轮真实 E2E 失败。

失败原因：

- 当时 `complete_todo` 未授权。
- 输入“标记为完成”没有被旧正则匹配。

后续修复：

- 已补 `标记为完成` 授权。
- 已补单元测试。

### CASE-06

结果：

- `list_todos` 返回 37 条，触发 `context_compaction.strategy = reference`。
- ref：`ctx_20260702_142201_812153`
- `read_context_ref` 成功恢复完整结果。

### CASE-07

输入：

```text
我学习 Agent Runtime 的时候喜欢先看生命周期，再看代码。你回答时可以注意一下。
```

结果：

- 未暴露 `save_memory`。
- 未调用 `save_memory`。
- 只在显式“列出 memory”时调用一次 `list_memories`。
- 不再出现 no-progress。

### CASE-08

结果：

- `save_memory` 成功。
- 保存 id：`mem_20260702_142240_626382`
- 第二轮真实 E2E 中后续“怎么学”没有注入该 memory。

后续修复：

- `learning` tag 现在能被“怎么学”命中。
- 已补 MemoryRetriever 回归测试。

### CASE-10

结果：

- PKG-001:
  - `track_package_via_mcp` completed
  - `mcp.server_id = mock_package_tracking`
  - `mcp.tool_name = track_package`
- PKG-404:
  - `track_package_via_mcp` failed
  - `error.code = package_not_found`

## 剩余问题

### REMAINING-01: 第三轮有效真实 E2E 未完成

原因：

- 当前会话提权/真实网络执行被用量限制拦截。
- 普通 sandbox 下重跑得到的第三轮结果全是 `llm_request_failed`，不是有效验收。

影响：

- 最后三个补丁已有本地回归测试，但还没有完整真实 LLM E2E 复验。

建议：

- 在用量恢复后重跑 `e2e_runtime_runner_temp.py`。
- 或把 runner 固化为 `scripts/run_e2e_runtime_plan.py`，后续作为人工验收工具使用。

### REMAINING-02: MCP 专门日志仍未补

MCP 功能通过，但仍只有普通 `tool.completed` / `tool.failed` 中的 MCP result 元数据。

后续建议补：

- `mcp.tool.started`
- `mcp.tool.completed`
- `mcp.tool.failed`
- 字段包括 `server_id`、Agent tool name、MCP tool name、`duration_ms`、`is_error`、normalized error code。

## 当前建议

1. 用量恢复后，重跑一次真实 E2E，重点看 CASE-05 和 CASE-08 是否由“部分通过”变为通过。
2. 如果第三轮真实 E2E 通过，再更新 `PROJECT_CONTEXT.md` 记录本次 E2E 修复结论。
3. MCP 专门日志可以作为下一小步，因为它不影响功能，但影响你学习每个 case 里 MCP adapter/server 发生了什么。
