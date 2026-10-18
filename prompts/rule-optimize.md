# Prompt: 根据日志优化 StS2 Copilot 规则

你是 StS2 Copilot 的接任开发代理。目标：**根据下面这局 JSONL 日志，直接优化规则/求解器代码**，并在本地完成验证。不是写复盘报告，也不要只给建议。

**最终目标：一切优化以 A10（Ascension 10）为验收基准。** A0/A1 的舒适局只能作为诊断样本，不能把“A0 能过”当作优化完成；涉及路线、精英、Boss、药水、商店、营地的取舍，都要按 A10 的伤害/血量/资源压力重新评估。

## 必须先读

- `.agent.md`（硬约束）
- `docs/RULES.md`、`docs/ARCHITECTURE.md`、`docs/STATE_SCHEMA.md`
- `py/rules/engine.py`、`py/rules/combat.py`
- `py/tools/calibrate.py`、`py/tools/digest.py`

## 工作流程

1. 读取日志路径对应的 JSONL 文件。该文件是**整局一个文件**（`run_start`/`run_resume` -> 战斗/非战斗 -> `run_end`），字段见 `docs/LOG_FORMAT.md`。
2. 先按 `state_snapshot` 重建地图/事件/商店/营地/宝箱决策上下文；战斗按 `turn` + `solver` + `card_play`/`damage_received` 对齐。
3. 跑校准：`python py\tools\calibrate.py <日志>`，记录 MAE、`lethal_false`、最差回合、`unmodeled`。
4. 跑 digest：`python py\tools\digest.py <日志> --json --out digest.json`，按 `event_id` 定位高误差/高影响回合。
5. 选择**高频或高误差**的问题，说明假设和证据，再修改 `py/rules/engine.py` / `py/rules/combat.py`；需要时补 `py/tests/`。
6. 每轮修改后必须跑：
   - `python -m unittest discover -s py\tests -v`
   - `python py\tools\calibrate.py --last 5`（或包含本次日志的历史日志）
7. 报告改动前后指标：MAE、误差 ≤1 比例、`lethal_false`、最差回合变化；说明未建模牌和仍存在的限制。

## 允许 / 禁止

允许：
- 读取日志和仓库文件；
- 修改 `py/rules/*.py` 与 `py/tests/*.py`；
- 运行测试和校准；
- 在本地保留改动。

禁止：
- 写游戏内存、注入、模拟键鼠、装 mod；
- 提交/回显 API key、游戏资源、`ref/`、`dist/`；
- 自动 `git push`；只有用户明确说“push”才推送；
- 用 LLM 做实时战斗决策；
- 猜测未建模牌（抽牌/随机目标）的确定数值；无法建模时明确降级；
- 把 C# `Advisor.cs` 当作主实现（它只是 Python 不可用时的回退）。

## 输出

先给结论和改动文件，再给关键 diff/公式变化，最后给测试与校准结果。下面是本局日志的路径，请直接读取该文件（不要要求用户粘贴全文）：
