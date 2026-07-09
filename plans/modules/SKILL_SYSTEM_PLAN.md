# Skill System 模块计划

## 1. 目标

本模块解决 Runtime 如何选择、加载和约束 skill 的问题。

Skill System 不等同于 Tool System。Skill 负责让 runtime 知道“当前请求应该采用哪组领域说明、参考资料、prompt 片段和 capability 边界”；Tool System 负责真正的 tool definition、execution 和 result。

## 2. 当前 V0 参考

V0 参考只作为历史对照，默认不直接迁入：

- `legacy_v0/app/skills/skill_loader.py`
- `legacy_v0/app/skills/skill_router.py`
- `legacy_v0/app/skills/reference_loader.py`
- `legacy_v0/app/skills/skill_state.py`
- `legacy_v0/app/prompts/prompt_builder.py`
- `legacy_v0/app/tools/capability_builder.py`
- `legacy_v0/tests/test_skill_loader.py`
- `legacy_v0/tests/test_skill_router.py`
- `legacy_v0/tests/test_capability_builder.py`
- `legacy_v0/tests/test_prompt_builder.py`

V0 中值得保留的方向：

- skill discovery 与 skill body 延迟加载分离；
- routing 结果需要可解释；
- capability 暴露应由当前 turn 的 loaded skills 决定；
- progressive reference loading 能避免把所有长参考一次性塞进上下文。

V0 中不应直接带入的风险：

- skill、tool、prompt、state 边界容易互相缠绕；
- helper / source / reference 的白名单规则需要重新放进当前 runtime 的 policy 和 trace 语义里；
- 多轮 skill state 不能绕过当前 turn 的 intent / policy 判断。

## 3. 当前范围

初版做：

- 定义当前 runtime 的 `SkillDefinition` / `LoadedSkill` / `SkillRoute` 等模型。
- 从 `app/skills/*/SKILL.md` 发现 skill metadata。
- 建立 deterministic router，输出 selected skills、score 和 reason。
- 建立 prompt assembly 边界：只加载被选中的 skill body。
- 建立 progressive reference loading 的接口边界，但不急着迁移全部 V0 news source/helper。
- 建立 skill-scoped capability 的输入输出模型，为后续 Tool System 做准备。
- 在 trace 中记录 skill routing 和 reference loading 的关键事件。

初版不做：

- 不实现完整 Tool System。
- 不接 MCP。
- 不迁移所有 V0 domain skills。
- 不把 skill state 当成业务事实源。
- 不让 skill routing 直接授权写入。

## 4. Runtime 边界

输入：

- `RuntimeRequest`
- intent / policy 的当前 turn 结果
- skill registry metadata
- 可选的 request-local history signal

输出：

- 当前 turn 的 selected / loaded skills
- prompt assembly 所需的 skill instructions
- skill-scoped capability hints
- trace events

不负责：

- 执行工具；
- 写入业务数据；
- 决定长期 memory；
- 替代 policy 授权；
- 从旧 V0 skill 自动迁移行为。

依赖方向：

```text
runtime
-> intent / policy
-> orchestration
-> skills
-> tools capability boundary
-> observability / common
```

## 5. 数据模型 / 存储

初版优先使用文件系统中的 skill manifest / `SKILL.md`，不新增 SQLite 表。

后续如果需要持久化 skill usage 或 user preference，应先在模块计划中补充事实来源和隐私边界。

## 6. 对外接口

预期接口：

- `discover_skills(root: Path) -> list[SkillDefinition]`
- `route_skills(request, intent, registry) -> SkillRoute`
- `load_skill_body(skill_id) -> LoadedSkill`
- `read_skill_reference(skill_id, ref_id) -> SkillReference`
- `build_skill_capabilities(loaded_skills) -> SkillCapabilitySet`

接口命名以施工时实际代码为准。

## 7. 失败模式

- skill frontmatter 缺字段或格式错误；
- skill folder name 与 declared name 不一致；
- routing 无匹配时 fallback 过宽；
- reference id 未声明或越界读取；
- capability 暴露和 loaded skills 不一致；
- inherited skill state 污染当前 turn；
- skill prompt 太长导致上下文预算失控。

失败时应记录可解释 trace event，不应静默扩大 capability。

## 8. 测试和 Eval

聚焦测试：

- skill discovery metadata validation；
- deterministic routing reason；
- selected skills 与 loaded skill body 分离；
- reference manifest 白名单；
- skill-scoped capability 暴露；
- prompt assembly 不加载未选中 skill；
- 多轮 skill state 不绕过当前 turn policy。

## 9. 文档更新

- `docs/PROGRESS_LOG.md`：模块完成后记录已实现 skill runtime 边界、有效测试和已知限制。
- `docs/ARCHITECTURE.md`：补充 Skill System 与 Intent / Policy / Orchestration / Tool System 的依赖方向。
- `docs/RUNTIME_CONCEPTS.md`：补充 Skill、Skill Routing、Progressive Reference Loading、Skill-scoped Capability 的本项目解释。
- `docs/AGENT_LEARNING_LINKS.md`：只有在正式施工并确认学习重点后，再补充已经学习的权威链接；不要提前收录未学习主题。

## 10. 实施步骤

1. 定义 Skill System 模型和错误类型。
2. 实现 skill discovery 和 metadata validation。
3. 实现 deterministic routing 和 trace event。
4. 实现 selected skill body 延迟加载。
5. 实现 reference manifest / progressive reference loading 的最小边界。
6. 实现 skill-scoped capability set。
7. 接入 prompt assembly。
8. 补齐聚焦测试。
9. 更新 `docs/PROGRESS_LOG.md`、`docs/ARCHITECTURE.md` 和 `docs/RUNTIME_CONCEPTS.md`。
