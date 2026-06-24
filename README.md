# LifeOps Agent

一个用于学习和实现AI Agent Runtime的本地Python项目，当前重点是Context压缩与长期消息
窗口。业务工具覆盖Todo、Wellbeing、Finance和Activity Recommendation。

## 运行

```powershell
uv run python main.py
uv run python log_viewer.py
uv run python -m unittest discover -s tests -v
```

## 文档

- `PROJECT_CONTEXT.md`：当前架构、实现、状态边界和已知限制。
- `LEARNING_PROGRESS.md`：学习结论和下一阶段Context计划。

项目使用OpenRouter及兼容OpenAI Responses API的模型，本地数据保存在 `data/`，运行日志
保存在 `logs/`。
