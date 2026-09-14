# Debug: waypoint-mark-45-22

## Session ID
waypoint-mark-45-22

## Status
[FIXED]

## Symptom
`g1_pick_waypoint_mark.py` 在 `manager.run_episode()` 时报错：
`could not broadcast input array from shape (45,) into shape (22,)`

## Root Cause
日志证据（20:24:40-43）：
1. 采点脚本把 `mj_joint_strip.install(None, ...)` 放在 `DataCollectionManager` 创建**之后**，环境创建时仍是完整模型（nu:45），`manager.ctrl` 初始化为 45 维
2. `finish_install` + `update_scene()` 后模型切换为任务模型（nu:22），但 `manager.ctrl` 仍是 45 维
3. `run_episode()` → `env.set_ctrl(self.ctrl)`：45 维数组写入 22 维 ctrl → 广播错误

遥操脚本正确顺序：`install()`（env=None 仅注册）→ `DataCollectionManager`（env 直接以任务模型创建，nu:22，ctrl 一致）→ `reset` → `finish_install` → `update_scene`。

## Fix
1. `mj_joint_strip.install(None, ...)` 移至 `DataCollectionManager` 创建之前
2. 恢复遥操脚本的 `default_joint_values` 存活关节过滤逻辑
3. 恢复 `env.set_default_joint_values(default_joint_values)` 无条件调用（两处）
4. 移除临时的 `manager.ctrl` 重建补丁

## Verification
待用户运行确认
