# StS2 Copilot 项目交接提示词

你是 **StS2 Copilot** 的接任开发代理。工作区：`D:\sts2-ai-copilot`。游戏：**Slay the Spire 2 0.107.1**。

这是一个**只读**的外部陪玩助手：ClrMD 读游戏进程，WPF 第二窗口显示建议，Python 本地规则服务负责规则/数学，JSONL 留下整局日志。用户手动玩，助手不发输入。

## 0. 接手先做

1. 读 `.agent.md`（硬约束）、`docs/ARCHITECTURE.md`、`docs/STATE_SCHEMA.md`、`docs/RULES.md`、`docs/LOG_FORMAT.md`。
2. 跑 `git status` 和 `git log -1`，确认当前 HEAD；不要假设工作区干净。
3. 跑 `python -m unittest discover -s py\tests -v`，确认基线（当前应为 85 个测试通过）。
4. 查看 `logs/runs/` 最新日志；如果用户给了日志路径，只读那一份，不要要求粘贴全文。
5. 先确认本轮是“继续优化”还是“修 bug”；不要重复重写已经实现的功能。

## 1. 目标与硬约束

最终验收目标是 **A10（Ascension 10）**。A0/A1 只能作为诊断样本，不能因为 A0 能过就认为优化完成。路线、精英、Boss、药水、商店、营地的取舍都要按 A10 的压力评估。

硬约束：

- **只读**：禁止写游戏内存、注入、调用游戏方法、模拟键鼠、装 mod。
- **版本锁**：只支持 `release_info.json` 的 `0.107.1`；不匹配必须拒绝连接。
- **失败要响**：HP/能量/手牌/牌堆越界时停止建议与记录，不能静默给错误建议。
- **规则/数学在 Python**：`py/rules/engine.py` 是主实现；`py/rules/combat.py` 是本回合求解器；C# `Advisor.cs` 只是 Python 不可用时的回退。
- **不提交密钥/游戏资源/反编译源码**：`ref/`、`dist/`、`tools/dotnet/`、`logs/` 不提交；`py/rules/data/catalog.json` 是源码生成的模型元数据，已作为唯一例外提交。
- **不要自动 `git push`**：只有用户明确说“push/推送”才推送。

## 2. 当前状态（2026-10-18）

- 分支：`main`；远程：`origin`（`git@github.com:zhangxing-Earthling/sts2-copilot.git`）。
- 当前功能代码提交：`bce49be Add rules service, run logging, model catalog and A10-oriented solver`；其后 `252a849` 增加了本交接文档，均已在 `origin/main`。
- 助手已发布到 `dist/Sts2Copilot/`（2026-10-18 22:30，含第九轮规则与 C# 意图修复）；本次发布后尚未启动助手，实机验证待做。`/health` 正常时应返回 `{"ok":true,"service":"sts2-rules"}`。
- 当前测试：**121 个 Python 单元测试全部通过**。
- 最新分析日志：`logs/runs/run_1792334448_39SXFARPJ0.jsonl`（A0、静默猎手、71 回合、第 17 层死亡）。
- 该日志校准（日志内嵌 solver）：**70 回合，MAE 0.34，误差 ≤1 94.3%，`lethal_false=1`**。
- 该日志 `--replay` 当前规则：**70 回合，MAE 0.31，跟随建议 MAE 0.02，误差 ≤1 94.3%，`lethal_false_followed=0`**。
- 最近 5 局 `--replay`：**210 回合，MAE 0.58，跟随建议 MAE 0.35，误差 ≤1 89.5%，`lethal_false_followed=0`**。
- 全部 64 份日志 replay：**346 回合、MAE 0.53、跟随 MAE 0.23、误差 ≤1 89.9%、`lethal_false_followed=0`**。
- 残余误差来源：① 玩家未按建议出牌（主因）；② `followed` 只比牌名不比目标，同名敌人时会误判“跟随”；③ 抽牌后打出的牌无法预知（后空翻/投掷匕首/肾上腺素居多）；④ 瀑布巨兽压力枪的 C# 意图读取需实机确认（22:30 已发布，尚未重启助手验证）。

注意：`calibrate.py` 读取日志中**当时代码写入的 `solver`**，所以“新代码的改进”不一定让历史日志的 MAE 自动下降。要验证新代码，重放 `turn.state` 或看 `combat.solve()` 的新输出。

## 3. 已实现的核心能力

- ClrMD 只读、版本锁、状态校验、中文本地化。
- WPF 第二窗口、一键 `start.cmd`、自动拉起/复用 Python 规则服务。
- 一局一个 JSONL（`runStartTime + seed`），`state_snapshot` / `turn` / `heartbeat` / `run_pause` / `run_resume` / `run_end`；应用重连/重启追加同一文件。
- 战斗求解器 DFS：攻击/多段/全体/格挡/毒/力量/敏捷/虚弱/易伤/脆弱/Shrink/荆棘/紧勒/Ravenous/Intangible/回合结束手牌伤害/Survivor 弃牌。
- 已补：StrikeDummy、Fisticuffs 伤害转格挡、纯伤害 X 费牌、Artifact 抵消 debuff、玩家/敌人 Intangible、即时力量/敏捷能力牌、PaperPhrog、PenNib、GremlinHorn、Cruelty、Debilitate。
- 已补（第八轮）：`Blur` 格挡（保留格挡列 partial）、`Flechettes` 按手牌技能数动态分段、`PreciseCut` 按手牌数动态伤害、仅 1 名敌人时随机目标按单体建模、多段牌的毒/debuff 按段数施加、`Orichalcum` 回合末 6 格挡；`calibrate.py --replay` 用当前规则重放历史回合。
- 已补（第九轮）：`ShriekPower` 阈值眩晕（骇鳗）、`VigorPower` 加算伤害、`SteamEruptionPower` 击杀不结束战斗（`combat.eruption` 警告，爆炸≥当前 HP 时 danger）、`DaggerThrow` 弃牌建模（可弃抽到的牌，序列显示弃牌）、`MementoMori` 按本回合弃牌数计算伤害；最优顺序 UI 改为一行一个动作；C# 意图读取跳过 static/const 字段并计入 Vigor。
- 已补（第十轮）：`SlipperyPower`（每次未格挡命中最多 1 血）、回合结束手牌伤害区分可格挡（`Infection`/`Burn`/`Decay`/`Toxic`/`Wither`）与不可格挡（`Beckon`/`BadLuck`/`Regret`）、打死最后一名敌人后不再结算回合结束伤害、`Adrenaline` 回能（抽牌列 partial）；事件选牌升级新增 `event.upgrade_target`（`AromaOfChaos` 等，复用 `score_card` 选牌）。
- 求解序列给升级牌加 `+` / `+2` 标记；`calibrate.py` 比较时会剥离标记。
- 药水：战斗内 `potion.use`（按实际减伤/斩杀/避免死亡给具体药水与预计 HP）；非战斗 `potion.inventory`；奖励药水 `potion.reward` / `potion.discard`，满 3 格时与当前最差比较。
- 地图：`map._map_dp` 从下一步一直算到 Boss，状态包含 HP、前一个节点类型、精英数；精英叠加/连续精英/精英后营地/低血精英有惩罚；Boss 前有安全线；A10 战斗/精英期望掉血 ×1.30、Boss 安全线提高。幕起点不在 `MapNodes` 时用 `MapChoices` 作根。完整图缺失时 `_map_lookahead` 最多 6 步局部前瞻；前两名分差 <0.5 输出 `map.close_call`。
- 事件：`AbyssalBaths` 有精确净损失模型与 `event.lethal`；其他事件是启发式 + 低血保护。
- 全量目录：578 卡 / 298 遗物 / 260 能力 / 64 药水 / 68 事件 / 88 遭遇；当前约 130 张卡 `exact`，其余 `partial`/`catalog_only`。

## 4. 当前优先级

1. **拿真正的 A10 日志**：A0 只能验证机制；优先跑 A10，按日志优化路线/精英/Boss/药水取舍。
2. **继续降低高影响误差**：先看 `calibrate.py --replay` 的最差回合、`digest.py` 的 `event_id`、`solver.unmodeled`；当前高频未建模是 `杂技`/`早有准备`/`急躁`（抽牌，无法只读建模）、`笨拙`/`晕眩`/`黏液`/`受伤`/`藏宝图`（状态/诅咒/任务牌，本回合无效果）、`必备工具`/`刀扇`（能力牌后续 hook）、多敌人时的 `弹跳药瓶`/`连续反弹`（随机目标）。下一件大事：**实机确认瀑布巨兽压力枪意图读到 20/25**（C# 已改并随 22:30 发布进入 dist，尚未实机验证）；若仍读到 5，再查 `IntentParts` 的委托目标。能确定性建模才做，不能就降级，不能猜。
3. **地图评分**：已完成“下一步 = 到 Boss 的整条路径”的 DP；下一步可做的是按实际遭遇/牌组/金币修正期望值，以及 A10 样本校准，不要退回“只看下一层”。
4. **药水**：`potion.use` 目前是求解结果后的启发式比较，不是 DFS 内动作；`RewardPotionIds` 的实机奖励屏路径还没拿到样本，需实机确认。
5. **C# 回退**：只在关键保命规则上补；主实现始终 Python。

## 5. 日志驱动优化流程

用户给日志路径时：

```powershell
python py\tools\calibrate.py logs\runs\<run>.jsonl
python py\tools\calibrate.py logs\runs\<run>.jsonl --replay   # 用当前规则重放
python py\tools\digest.py logs\runs\<run>.jsonl --json --out logs\digest.json
```

然后：

1. 用 `state_snapshot` 重建地图/事件/商店/营地/宝箱上下文。
2. 用 `turn` + `solver` + `card_play` / `damage_received` 对齐战斗。
3. 选**高频或高误差/高影响**问题，写清证据和假设。
4. 改 `py/rules/engine.py` / `py/rules/combat.py`；需要时改 `py/tools/*` 或 C# 读取字段。
5. 每轮必须跑：
   - `python -m unittest discover -s py\tests -v`
   - `python py\tools\calibrate.py --last 5`（历史 solver 基线）
   - `python py\tools\calibrate.py --last 5 --replay`（当前代码的真实水平）
6. 报告：MAE、误差 ≤1、`lethal_false` / `lethal_false_followed`、最差回合前后变化、未建模牌、仍有限制。

不要只写复盘报告；要直接改代码并在本地验证。

## 6. 常用命令

```powershell
# 测试
python -m unittest discover -s py\tests -v

# 校准 / digest
python py\tools\calibrate.py --last 5
python py\tools\digest.py --last 1 --json --out logs\digest.json

# 单独调试规则服务
python py\rules\server.py

# 构建/发布（先关闭正在运行的助手，避免 DLL 被锁）
$dotnet = "D:\sts2-ai-copilot\tools\dotnet\dotnet.exe"
& $dotnet publish src\Sts2Copilot.App\Sts2Copilot.App.csproj `
  -c Release -r win-x64 --self-contained true -o dist\Sts2Copilot

# 启动
start.cmd
# 或 dist\Sts2Copilot\Sts2Copilot.exe
```

发布后必须检查 `exit=$LASTEXITCODE` 和 `dist` 里 DLL 的修改时间；不要只截取最后几行日志。

## 7. 验收标准

- 机制改动有测试；测试全绿。
- 战斗：已建模牌/遗物/能力范围内，预测掉血与实际误差 ≤1；`lethal_false` 有解释。
- 未建模项必须出现在 `combat.solver_unmodeled` / `partial`，不能静默猜抽牌/随机目标。
- 地图：下一步评分必须包含之后到 Boss 的路径；A10 压力下不能推荐明显送死/低 Boss 血线路线。
- 事件：致死选项必须 `event.lethal`，推荐不能排在危险选项前面。
- 助手仍只读；版本锁、校验、日志一局一文件不破坏。

## 8. 禁止

- 不写内存、不注入、不模拟键鼠、不装 mod。
- 不提交 API key、游戏资源、反编译源码、`ref/`、`dist/`、`logs/`。
- 不用 LLM 做实时战斗决策。
- 不猜测未建模牌（抽牌/随机目标）的确定数值。
- 不把 C# `Advisor.cs` 当主实现。
- 不自动 `git push`；只有用户明确要求才推送。

## 9. 交接时优先读的文件

- `.agent.md`
- `docs/RULES.md`
- `docs/STATE_SCHEMA.md`
- `docs/LOG_FORMAT.md`
- `docs/LOG_HANDOFF.md`
- `py/rules/engine.py`
- `py/rules/combat.py`
- `py/tools/calibrate.py`
- `py/tools/digest.py`
- `prompts/rule-optimize.md`（日志优化提示词）
- `README.md`

如果新会话只能先做一件事：**先读 `.agent.md` 和最新日志，跑测试与 calibrate，再决定改什么。**
