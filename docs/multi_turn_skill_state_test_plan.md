# Multi-turn Skill State Test Plan

## Learning goal

Observe how explicit routing and Agent runtime state combine:

```text
current user input
-> directly_selected
-> previous_active_skills
-> inherited_skills
-> loaded_skills
-> next_active_skills
-> dynamic Tool Schema
```

The Router still reads only the current input. `SkillStateResolver` is the separate
runtime layer that decides whether to inherit, replace, preserve, or clear state.

## Run

Start the Agent:

```powershell
uv run python main.py
```

In another terminal, start the log viewer:

```powershell
uv run python log_viewer.py
```

For every turn, compare the `skill_routing` and `capability_build` Trace events with
the complete `llm_request.tools` entry in Raw.

## Case 1: Todo follow-up inheritance

Send these messages in the same session:

```text
列出我的待办任务。
完成第一个。
```

Verify on the second turn:

- `directly_selected` is empty.
- `previous_active_skills` contains `todo`.
- `inherited_skills` and `loaded_skills` contain `todo`.
- `state_resolution` is `ambiguous_followup_inherited`.
- Todo tools remain visible.

## Case 2: Finance follow-up inheritance

```text
列出最近的消费记录。
把第一笔改成 35 元。
```

Verify that the second turn inherits Finance capability. The current project does
not yet implement an expense update tool, so the final business action may not be
possible; the learning target is the inherited Skill and visible capability set.

## Case 3: Explicit topic switch

```text
列出我的待办任务。
检查本周餐饮预算。
```

Verify on the second turn:

- `directly_selected` contains `finance`.
- `inherited_skills` is empty.
- `next_active_skills` contains only `finance`.
- Todo tools disappear and Finance tools become visible.

## Case 4: Ordinary chat clears state

```text
列出我的待办任务。
你好，介绍一下自己。
继续。
```

Verify:

- The chat turn has `state_cleared: true`.
- Its `next_active_skills` is empty.
- The final `继续` reports `followup_without_active_skill`.
- Only common tools are visible after the state is cleared.

## Case 5: Context Ref uses minimum capability

After a Finance request produces a referenced result:

```text
把刚才引用的完整结果展开。
```

Verify:

- `state_resolution` is `context_ref_only`.
- `loaded_skills` is empty for this turn.
- Only common tools are visible, including `read_context_ref`.
- `next_active_skills` preserves the previous Finance topic.

Then send:

```text
继续。
```

Verify that Finance is inherited again.

## Case 6: Cross-domain inheritance

```text
检查本周预算，并根据任务安排今天。
继续刚才那个。
```

Verify that the second turn inherits both Todo and Finance and merges both tool
groups without duplicates.

This deliberately exposes a current trade-off: an ambiguous follow-up inherits the
whole active Skill group. Future Trace evidence can justify a narrower policy based
on the last tool or result being referenced.

## Case 7: New session starts clean

Stop and restart `main.py`, then send:

```text
继续。
```

Verify that there is no active Skill to inherit. A `/reset` CLI command remains a
separate deferred feature.

## Automated regression

```powershell
uv run python -m unittest discover -s tests -v
```

The automated tests cover direct selection, inheritance, explicit switching,
cross-domain deduplication, Ref-only minimum capability, chat cleanup, missing active
state, Tool Schema changes, and Trace state fields.
