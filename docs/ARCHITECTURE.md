# Architecture

## 组件

| 组件 | 语言 | 职责 |
|---|---|---|
| `Sts2Copilot.App` | C# / WPF | 读内存、显示第二窗口、写 JSONL、调用规则服务 |
| `py/rules` | Python | 战斗数学、选牌评分、地图评分、后续 DP/求解器 |
| `tools/clrdprobe` | C# | 调试探针，验证字段/地图/奖励 |
| `tools/decomp` | C# | 游戏更新后反编译 `sts2.dll` |

## 数据流

```
每 250ms:
  1. MemoryReader.Read()
       RunManager.Instance -> RunState
       -> Player / Creature / PlayerCombatState
       -> Hand / Deck / Relics / Potions / Map / Rewards
  2. 校验 HP/能量/手牌/牌堆/敌人 HP
  3. POST /advise (GameState JSON)  -> Python
     超时 500ms；失败则 Advisor.Build() 本地回退
  4. UI 渲染 + RunLogWriter 记录事件
```

## 规则服务

- 地址：`http://127.0.0.1:8765`
- `GET /health` → `{"ok": true}`
- `POST /advise` → `{"advice": [{"ruleId","text","severity"}], "source":"python"}`
- 无状态；每次请求独立计算
- 只监听 `127.0.0.1`，不对外网开放

C# 通过环境变量 `STS2_COPILOT_RULES_URL` 可改地址。

## 日志

`%APPDATA%\Sts2Copilot\runs\run_<时间>_<种子>.jsonl`

| type | 触发 |
|---|---|
| `run_start` | 首次读到该种子 |
| `combat_start` | 进入战斗 |
| `turn` | 进入出牌阶段（`Phase == 3`） |
| `action` | 同一回合内手牌/能量/药水变化；`kind=card_play` 或 `state_change` |
| `reward` | 三选一候选变化 |
| `combat_end` | 离开战斗 |
| `run_end` | 退出对局/关程序/重连 |

## 线程与性能

- UI 线程只做渲染；内存读取和 HTTP 在 `Task.Run`
- 读一次约 0.5–1.5ms；HTTP 本地 <10ms
- 250ms 轮询；`_busy` 防止重入

## 失败模式

| 情况 | 行为 |
|---|---|
| 游戏退出 | 停止轮询，写 `run_end` |
| 版本不匹配 | 拒绝连接，状态栏显示版本错误 |
| 状态校验失败 | 停止建议与记录，不静默继续 |
| Python 未启动 | 自动回退 C# 规则，状态栏 `local` |
| 找不到 DAC | 连接失败并显示错误 |

## 安全/合规

- 只读进程内存，不写、不注入、不模拟输入
- 不修改存档
- 不把游戏资源/反编译代码放进发布物
- API key 只从环境变量读，不落日志
