# AGENTS.md

本仓库的代理开发说明以 [`.agent.md`](.agent.md) 为准。

最短约束：

- 只读 ClrMD，禁止写内存/注入/模拟键鼠/装 mod。
- 只支持游戏 `0.107.1`，版本不匹配必须拒绝连接。
- 规则与数学在 `py/rules/engine.py`；C# `Advisor.cs` 只是回退。
- 不提交 API key、游戏资源、反编译代码、`dist/`。
- 发布后必须检查 `exit code` 与 `dist` 里 DLL 的修改时间。

常用入口：`README.md`、`docs/ARCHITECTURE.md`、`docs/STATE_SCHEMA.md`、`docs/RULES.md`。
