# Dynamic Tool Schema and Skill Capability Test Plan

## Learning goal

Observe the full capability chain for each user turn:

```text
user input
-> skill_routing.loaded_skills
-> capability_build.visible_tool_names
-> raw llm_request.tools
-> tool_call or tool_denied
```

The current router is intentionally stateless. Ambiguous follow-up requests may lose
their previous domain capability; multi-turn Skill state will address that later.

## Run

```powershell
uv run python main.py
```

Each session creates paired files under `logs/conversations/`:

- `*_trace.json`: structured decisions and runtime behavior.
- `*_raw.json`: complete LLM input/output and tool results.

The local viewer can be started with:

```powershell
uv run python log_viewer.py
```

## Case 1: Single Todo domain

Input:

```text
列出我的待办任务，并安排今天应该先做什么。
```

Verify:

- `skill_routing.directly_selected` and `loaded_skills` contain only `todo`.
- `capability_build.visible_tool_names` contains Todo and common tools.
- Finance, Wellbeing, and Activity tools are absent.
- Raw `llm_request.tools` exactly matches the visible names in Trace.

## Case 2: Single Finance domain

Input:

```text
检查本周餐饮预算还剩多少。
```

Verify that only Finance and common tools are visible.

## Case 3: Cross-domain capability union

Input:

```text
检查本周餐饮预算，并根据未完成任务安排今天。
```

Verify:

- Both `todo` and `finance` are selected.
- Both tool groups are present.
- Common tools appear only once.
- No Wellbeing or Activity tools are visible.

## Case 4: Four-domain request

Input:

```text
我昨晚只睡了 5 小时，今天能量低。这周餐饮预算紧，还有重要任务。
帮我安排现实一点的今天计划，并推荐一个免费的恢复活动。
```

Verify that all four Skills are selected and every registered tool is visible once.

## Case 5: Safe fallback

Input:

```text
你好，介绍一下自己。
```

Verify:

- No domain Skill is loaded.
- `fallback_used` is true.
- Only `get_current_time` and `read_context_ref` remain visible.
- No write tool is exposed.

## Case 6: Context Ref without a domain Skill

After producing a compressed result with a `ref_id`, input:

```text
把刚才引用的完整结果展开。
```

Verify that `read_context_ref` remains visible and can be called even when no domain
Skill is selected.

## Case 7: Runtime authorization

Run the automated authorization test:

```powershell
uv run python -m unittest tests.test_tool_authorization -v
```

It directly attempts a Finance write under Todo-only capability. Verify the result is
`tool_not_allowed` and the underlying expense write function is never called.

## Case 8: Observe multi-turn capability inheritance

First input:

```text
列出最近的消费记录。
```

Then use an ambiguous follow-up:

```text
把第一笔改一下。
```

Verify that the second turn inherits the Finance Skill, records it under
`inherited_skills`, and retains Finance capabilities. Compare `directly_selected`,
`inherited_skills`, and `loaded_skills` to see how runtime state supplements the
stateless Router.

## Automated regression

```powershell
uv run python -m unittest discover -s tests -v
```

The automated tests cover capability mapping, stable Schema order, deduplication,
fallback, Context Ref availability, runtime denial, non-execution of denied writes,
and the Schema actually passed by `Agent` to the LLM client.
