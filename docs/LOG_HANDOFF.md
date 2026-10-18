# 日志交接与规则优化

助手不再内置 AI 复盘/DeepSeek 调用。它只负责把**日志路径 + 规则优化提示词**交给外部 DSH。

## 日志目录

所有日志在项目 `logs\` 下：

| 目录 | 内容 |
|---|---|
| `logs\runs\` | 对局 JSONL：`run_<runStartTime>_<种子>.jsonl`，**一局一个文件** |
| `logs\app\` | 助手自身日志 `app.log` |
| `logs\archive\reviews\` | 历史 AI 复盘产物（旧功能，已停用，仅存档） |

`STS2_COPILOT_LOG_DIR` 可覆盖根目录；`logs/` 已在 `.gitignore` 中。

一局从选完角色到死亡/换局都写同一个文件；应用重启/重连会按 `runStartTime + seed` 继续追加 `run_resume`。日志结构见 [LOG_FORMAT.md](LOG_FORMAT.md)。

## 复制日志地址 + 提示词

助手窗口底部只有 **日志交接** 面板：

- 按钮「复制日志地址+提示词」；
- 复制 `prompts/rule-optimize.md` 和**当前这一局** JSONL 的绝对路径（不复制全文，不再用“最新文件”兜底）；
- 明确要求 DSH 直接读取该文件。

粘贴给 DSH 后，提示词要求它：

1. 读 `.agent.md` / `docs/RULES.md` / `docs/STATE_SCHEMA.md` / `docs/LOG_FORMAT.md` / `py/rules/engine.py` / `combat.py`；
2. 坚持**一切优化以 A10 为最终目标**：A0/A1 只作诊断样本，路线/精英/Boss/资源取舍按 A10 压力评估；
3. 按 `state_snapshot` 重建 P4 上下文，按 `turn`/`solver`/因果事件校准战斗；
4. 跑 `calibrate.py` 和 `digest.py` 定位高误差回合；
5. 直接修改 `py/rules/*.py`（必要时补测试）；
6. 跑 `python -m unittest discover -s py\tests -v` 和校准；
7. 报告改动前后 MAE / `lethal_false` / 最差回合；
8. 不写内存、不注入、不模拟键鼠、不提交 key、不自动 push。

## 安全边界

- 助手本身不调用 DeepSeek，不需要 `DEEPSEEK_API_KEY`。
- 规则代码的修改由 DSH/人完成，助手不自动改代码、不自动 push。
- 历史 `review_*` 文件保留在 `logs\archive\reviews`，不参与新流程。
