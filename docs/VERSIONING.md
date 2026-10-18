# Versioning

## 当前支持

| 项 | 值 |
|---|---|
| 游戏版本 | `0.107.1` |
| 校验位置 | `MemoryState.cs` 的 `SupportedVersion` |
| 版本来源 | 游戏目录 `release_info.json` 的 `version`（会去掉前缀 `v`） |
| 失败行为 | 拒绝连接，状态栏显示“游戏版本 X 不受支持” |

## 游戏更新后的步骤

1. 读新 `release_info.json`，记录版本号。
2. 改 `SupportedVersion`。
3. `tools/decomp` 重新反编译 `sts2.dll` 到 `ref/sts2`。
4. `clrdprobe fields <pid> <type>` 核对字段。
5. 只改 `MemoryState.cs` 的读取层；`py/rules` 不动。
6. 跑 `run` / `rewards` / `map` 探针 + 启动 app。
7. 更新 `.agent.md`、`docs/STATE_SCHEMA.md`、本文件。

## 为什么 fail closed

读内存依赖私有字段布局。版本不匹配时字段可能改名/改类型，继续读会**静默给出错误建议**；宁可拒绝启动，也不能让玩家按错误数字打。

## 校验兜底

即使版本匹配，也校验：

- `0 <= Hp <= MaxHp`
- `0 <= Energy <= 20`
- 手牌 ≤ 10
- 牌堆数量 ≥ 0
- 敌人 `0 <= Hp <= MaxHp`

任何一项失败：停止建议与记录。
