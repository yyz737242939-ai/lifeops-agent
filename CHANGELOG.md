# Changelog

本文件记录LifeOps Agent每个学习Milestone交付的主要能力。格式参考
[Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，但版本号表示项目学习阶段，
不等同于PyPI包的语义化版本。

## 当前功能总览

- 基于OpenAI Responses API兼容接口的多轮Function Calling Agent。
- Todo、日计划、Wellbeing、消费预算和活动推荐工具。
- 确定性Skill路由、多轮Skill状态、按需加载Skill正文。
- 动态Tool Schema、最小Capability和Runtime二次授权。
- 单次Chat RunState、结构化Action、预算、重试、超时、取消和停止原因。
- 工具错误归一化、写入幂等重放和确定性循环检测。
- Tool Observation的inline、summary和Context Ref压缩。
- 当前输入写授权、批量删除确认和最终写入声明校验。
- Event、LLM I/O、Application三通道日志及本地Viewer。
- 79项自动化回归测试。

## [Milestone 1.1] - 2026-06-24

### Added

- 增加当前用户输入级别的写工具授权策略，未经明确授权不向模型暴露写能力。
- 增加批量删除确认保护，以及最终回答的写入成功声明校验。
- 日志Viewer支持发现和查看验收测试目录中的Session。
- Events页面增加单次Chat的LLM轮次、API请求数和工具执行尝试摘要。

### Changed

- RunState和ActionRecord字段明确区分单次Chat、LLM API请求和工具执行尝试的作用域。
- LLM Response日志改为诊断字段投影，删除重复的instructions、tools和空字段。
- 更新项目上下文和学习计划，下一阶段聚焦Context压缩与长期消息窗口。
- 清理第一阶段一次性UAT Runner、计划和运行产物，保留自动化回归测试。

### Fixed

- 修复建议类请求可能被模型误当成健康状态写入授权的问题。
- 防止模型在没有成功WRITE Action时声称数据已经保存或修改。
- 修复验收日志在Viewer中出现无效Session ID、无法选择的问题。

## [Milestone 1.0] - 2026-06-23

### Added

- 增加确定性Skill Router，以及Skill继承、切换、清理和Ref-only多轮状态。
- 增加按Skill动态构建Prompt、Tool Schema和授权集合的Capability机制。
- 增加单次请求RunState、ActionRecord、循环预算和结构化StopReason。
- 增加LLM/Tool显式重试、超时、协作式取消和部分成功结果保留。
- 增加工具副作用、幂等性、可重试性和超时元数据。
- 增加稳定调用签名、相同Observation和A-B-A-B循环检测。
- 增加Tool Result的领域摘要、Reference压缩及 `read_context_ref`。
- 增加Event、LLM I/O和Application三通道日志与本地Viewer。

### Changed

- 将Tool Registry、Executor、业务工具和公共JSON/时间工具拆分为清晰职责。
- Skill正文改为选中后按需加载，避免无关正文持续占用Context。
- SDK隐式重试改为Runtime显式管理和计数。

## [Milestone 0.1] - 2026-06-22

### Added

- 建立基础LLM聊天和Responses API调用链路。
- 实现Function Call执行循环，将Tool Observation返回模型继续推理。
- 建立Todo、Wellbeing、Finance和Activity Recommendation四个本地业务领域。
- 使用Pydantic和本地JSON文件保存Todo、日状态、消费及预算数据。
- 建立初版Skill路由、Context摘要和Agent运行日志。
