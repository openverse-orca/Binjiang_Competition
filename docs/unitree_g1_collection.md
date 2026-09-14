# 宇树 G1 · 数据采集与回放

本文说明宇树 G1 在比赛场景中的相机配置、Pico 遥操作、按钮脚本化数据采集、LeRobot 数据回放与数据格式。

---

## 场景与相机

### 加载场景

1. 请在运行本项目的主机上启动 OrcaLab。
2. 请在 OrcaLab 的加载布局对话框中选择任务对应的布局文件：
   - 按钮场景：`src/examples/dataCollection/unitree_g1/g1_pick_buttons.json`
3. 请确认宇树 G1 与场景物体已正确加载。
4. 请确认 `src/examples/dataCollection/unitree_g1/example.yaml` 中的 `level_name` 与 OrcaLab 场景名称一致，默认值为 `"example"`。

按钮布局中保存的机器人名称如下：

| 布局文件 | 布局中的机器人名称 | `--agent_name` |
|----------|--------------------|----------------|
| `g1_pick_buttons.json` | `g1_pick` | `g1_pick` |

本文的示例命令均显式传入：

```text
--agent_name g1_pick
```

当前三个入口脚本的默认 `--agent_name` 也都是 `g1_pick`。示例仍显式传入该参数，便于在使用自定义布局时检查机器人名称是否一致。

### 配置相机

当前 Unitree G1 采集链路使用头部和右腕两路彩色相机：

| 相机位置 | 布局内相机实体 | 代码中的相机名称 | LeRobot 数据键 | Color Port |
|----------|----------------|------------------|------------------|------------|
| 右腕 | `camera_right` | `camera_wrist_r_color` | `cam_wrist_r` | 7080 |
| 头部 | `head_cam` | `camera_head_color` | `cam_head` | 7090 |

以上端口同时由布局与代码确认：

- `g1_pick_buttons.json` 为右腕相机明确设置 `ColorPort: 7080`，为头部相机明确设置 `ColorPort: 7090`，并启用 `ColorCamera`、`UseNvEnc` 和 `Enable`。
- `g1_pick_buttons.json` 还为两路相机显式设置了 `IsRecording: true`。
- `src/dataStorage/lerobot_camera.py` 中的 `DEFAULT_CAMERA_MAP` 使用相同的端口：右腕 `7080`、头部 `7090`。

加载布局后，请在 OrcaLab 中检查两路相机：

1. `Color Camera` 已启用。
2. `UseNvEnc` 已启用。
3. 相机组件处于启用状态。
4. 右腕和头部 `Color Port` 分别为 `7080` 和 `7090`。
5. 启动仿真后没有其它程序占用这两个端口。

共享相机代码还保留左腕 `camera_wrist_l_color:7070`，但当前 Unitree G1 遥操作和脚本化采集入口的 `--cameras` 只支持 `head` 与 `wrist_r`。本文示例不启用左腕相机。

### 启动仿真

完成场景和相机检查后，请点击 OrcaLab 的运行按钮启动仿真，并等待 OrcaGym 服务就绪。默认服务地址为：

```text
localhost:50051
```

---

## 运行准备

请先按仓库根目录 [README](../README.md) 完成环境安装，并确认已在 OrcaLab 资产库中订阅 `Binjiang_Competition_2026` 与 `g1_pick`。

后续命令均在运行 OrcaLab 的主机上执行：

```bash
conda activate orcalab_lerobot
cd src/examples/dataCollection/unitree_g1
```

示例命令中的数据集统一写入 `$HOME/binjiang_datasets`。可以换成其它可写目录，但不要在同一目录中混入不同机器人、不同 state/action schema 或不同相机组合的数据。

---

## Pico 遥操作采集

遥操作脚本为 `g1_pick_osc_collection_tele_lerobot.py`。右臂使用 OSC 跟随 Pico 右手柄位姿，右夹爪使用 Pico 按键或扳机控制，采集结果写为 LeRobot v2.1 数据集。

### Pico 端口转发

连接 Pico 后，请先确认 ADB 能发现设备，并把主机的 `8001` 端口反向转发到头显：

```bash
adb devices
adb reverse tcp:8001 tcp:8001
```

每次重新连接或重启 Pico 后，建议重新执行端口转发命令。

### 启动命令

请先加载 `g1_pick_buttons.json` 并启动仿真，再执行：

```bash
OMP_NUM_THREADS=1 python g1_pick_osc_collection_tele_lerobot.py \
    --task_config example.yaml \
    --agent_name g1_pick \
    --lerobot_out $HOME/binjiang_datasets/g1_osc \
    --repo_id local/g1_pick_osc \
    --task "按按压式按钮" \
    --fps 20 \
    --clock wall \
    --cameras head,wrist_r \
    --camera_source websocket \
    --dls_lambda 0.2 \
    --joint_strip on \
    --strip_col off \
    --time_step 0.001 \
    --frame_skip 5
```

`OMP_NUM_THREADS=1` 用于限制底层数值库的线程数，减少仿真、相机采集和视频编码之间的 CPU 争用。

当前脚本的默认任务模型配置为 `--joint_strip off`，与上面的采集示例不同。因此示例中的 `--joint_strip on` 不应省略。

| 参数 | 含义 | 脚本默认值 | 示例值或使用建议 |
|------|------|------------|------------------|
| `--task_config` | 场景任务配置文件 | `example.yaml` | 一般无需修改 |
| `--agent_name` | OrcaLab 布局中的机器人名称 | `g1_pick` | 与按钮布局一致 |
| `--lerobot_out` | LeRobot 数据集输出目录 | 无；采集模式必须指定 | 每个数据集使用独立目录 |
| `--repo_id` | 写入数据集元信息的仓库名 | `local/g1_pick_osc` | 可按任务修改 |
| `--task` | 写入数据集的语言指令 | `g1 pick osc teleoperation` | 应与实际任务和训练指令一致 |
| `--fps` | 数据采集帧率 | `20` | 遥操作推荐 20 |
| `--clock` | 采帧时钟：`wall` 或 `sim` | `wall` | 遥操作推荐 `wall` |
| `--resume` | 追加到已有数据集 | 未启用 | 断点续采时追加 |
| `--cameras` | 启用的相机，可选 `head`、`wrist_r` | `head,wrist_r` | 默认使用两路相机 |
| `--cam_resolution` | 数据帧目标分辨率，高×宽 | `480x640` | 需要缩放时修改 |
| `--camera_source` | `websocket` 流式采集或 `mp4` 集末提取 | `websocket` | 推荐 `websocket` |
| `--dls_lambda` | OSC 阻尼最小二乘最大系数 | `0.23` | 示例使用 `0.2` |
| `--joint_strip` | 任务模型配置 | `off` | 采集示例必须显式使用 `on` |
| `--strip_col` | 任务模型的碰撞配置 | `off` | `off` 使用采集碰撞配置，`keep` 保留完整配置 |
| `--time_step` | MuJoCo 物理步长，单位秒 | `0.001` | 与回放保持一致 |
| `--frame_skip` | 每个控制周期的物理子步数 | `5` | 控制周期为 5 ms |
| `--orcagym_addr` | OrcaGym 服务地址 | `localhost:50051` | 服务地址变化时修改 |

### 按键映射

本文示例启用了 `--joint_strip on` 任务模型配置，采集操作集中在右臂和右夹爪；左侧控制不响应 Pico 输入。

| 功能 | 操作 | 说明 |
|------|------|------|
| 右臂末端位姿 | 移动 Pico 右手柄 | 右手柄 6DOF 位姿驱动右臂 OSC |
| 右夹爪张开 | 右手柄 A | 离散张开 |
| 右夹爪闭合 | 右手柄 B | 离散闭合 |
| 右夹爪连续开合 | 右扳机 | 按扳机量连续控制 |
| 开始当前集 | 第一次按左 Grip 侧握键 | 开始后右臂才响应手柄并开始记录 |
| 结束并保存 | 第二次按左 Grip 侧握键 | 无论任务是否成功，均保存当前集 |
| 放弃当前集 | 单按右 Grip 侧握键 | 丢弃当前集并重置场景 |
| 终止全部采集 | 左右 Grip 同时按下 | 丢弃未保存集，等待视频编码完成后退出 |
| 强制中断 | 主机终端按 `Ctrl+C` | 中止采集并执行退出清理 |

脚本连接到 Pico 后并不会立即驱动机器人。场景重置后必须先按一次左 Grip 进入 `RUNNING` 状态，右臂和右夹爪才会响应手柄。

### 仅遥操作、不写数据

需要先检查 Pico、OSC 和场景动作时，可在遥操作命令中加入 `--teleop_only`，并省略 `--lerobot_out`、`--repo_id`、相机和数据集相关参数。该模式不初始化相机，也不会创建 LeRobot 数据集。

### 断点续采

向原数据集追加 episode 时，在原命令末尾加入：

```text
--resume
```

启动后应看到已加载的数据集 episode 数和帧数。续采只允许写入与当前 state/action schema 和相机特征一致的数据集；若元信息不一致，脚本会拒绝续写。

---

## 脚本化数据采集

`g1_pick_osc_collection_scripted_lerobot.py` 读取一个或多个路点 YAML，将各段插值为连续轨迹，自动控制右臂和右夹爪，并把每个 episode 写为 LeRobot v2.1 数据集。

### 按钮任务示例

请先在 OrcaLab 中加载 `g1_pick_buttons.json` 并启动仿真，再执行：

```bash
OMP_NUM_THREADS=1 python g1_pick_osc_collection_scripted_lerobot.py \
    --task_config example.yaml \
    --agent_name g1_pick \
    --waypoint_files my_waypoint_button/marked/my_waypoint_press_01.yaml,my_waypoint_button/marked/my_waypoint_toggle_01.yaml \
    --lerobot_out $HOME/binjiang_datasets/g1_osc_buttons \
    --repo_id local/g1_pick_osc_buttons \
    --num_episodes 1 \
    --fps 20 \
    --clock sim \
    --cameras head,wrist_r \
    --camera_source websocket \
    --joint_strip on \
    --strip_col off \
    --time_step 0.001 \
    --frame_skip 5 \
    --dls_lambda 0.23 \
    --dls_sigma_th 0.12 \
    --null_kp 10 \
    --kp 0 \
    --action_repeat 1 \
    --track_ki 0 \
    --track_clamp 0.08
```

当前 `my_waypoint_button/marked/` 下的路点文件由「路点标注」工具（见下文）在实际场景中标注生成，每个文件都在 YAML 顶层声明自己的 `button_name` 和 `task`：

| 路点文件 | 按钮类型 | 写入的 task prompt |
|----------|----------|--------------------|
| `my_waypoint_press_01.yaml` | 按压式 | `按压停止按钮` |
| `my_waypoint_rotate_01.yaml` | 旋转式 | 留空（标注时未传 `--task`），补填后才能与带 `task` 的文件同用 |
| `my_waypoint_toggle_01.yaml` | 拨杆式 | `拨动拨杆式按钮` |

各按钮任务的运动结构：

- 按压式：接近 → 竖直下压 → 保持 → 撤回（并指夹爪用指尖按压）。
- 旋转式：接近 → 下移 → 闭合夹爪抓住旋钮 → 保持位置、腕部绕竖直轴旋转 → 松开 → 撤回。
- 拨杆式：接近 → 贴住拨杆末端 → 沿竖直方向拨动 → 撤回。

带 `task` 的每个路点文件会单独生成 episode，脚本在该集开始前写入对应 prompt；同一命令中的路点 YAML 必须全部带 `task` 或全部不带，否则脚本会拒绝启动。上面的命令设置 `--num_episodes 1`，因此会依次保存按压、拨杆共 2 个 episode；设置为 `2` 时，每个任务重复 2 集，共保存 4 集。按钮任务不需要再传入 `--task`。相对路径仍以脚本目录为基准，因此必须保留 `my_waypoint_button/marked/` 前缀。

> [!NOTE]
> 新场景按钮位置以标注结果为准。标注后可先用 `--dry_run` 验证轨迹；若某段偏差较大，可重新标注或手动微调该段 `r_target_b` / `r_quat_b`（旋转式还需按旋钮行程调整旋转段角度，拨杆式可按需改为向下拨动）。

| 参数 | 含义 | 默认值 | 使用建议 |
|------|------|--------|----------|
| `--waypoint_files` | 逗号分隔的路点 YAML | `my_waypoint_button/marked/my_waypoint_press_01.yaml` | 带 `task` 的文件分别生成 episode；全部不带 `task` 时按顺序组成同一集；两种文件不能混用 |
| `--lerobot_out` | LeRobot 数据集输出目录 | 无；非 dry-run 必须指定 | 每个数据集使用独立目录 |
| `--repo_id` | 数据集仓库名 | `local/g1_pick_osc_scripted` | 可按任务修改 |
| `--task` | YAML 未声明 `task` 时使用的语言指令 | `按按钮` | 必须与实际轨迹一致；带 `task` 的按钮 YAML 使用自身的 `task` |
| `--num_episodes` | 每条轨迹重复采集的 episode 数 | `1` | 总集数为 `路点文件数 × num_episodes` |
| `--fps` | 数据采集帧率 | `20` | 一般保持 20 |
| `--clock` | `sim` 或 `wall` | `sim` | 脚本化采集推荐 `sim` |
| `--resume` | 追加到已有数据集 | 未启用 | 续采时追加 |
| `--dry_run` | 只验证轨迹，不开相机、不写数据 | 未启用 | 正式采集前建议先验证 |
| `--speed` | 轨迹整体速度倍率 | `1.0` | `2.0` 表示各段步数减半 |
| `--steps` | 覆盖每个路点段的步数 | `0` | `0` 表示使用 YAML 中的 `steps` |
| `--settle_steps` | 夹爪状态变化前的沉降步数 | `200` | 等待 OSC 跟到位后再开合夹爪 |
| `--hold_steps` | 轨迹末尾保持步数 | `100` | 给最后一次夹爪动作留出时间 |
| `--action_repeat` | 每个轨迹采样重复的控制步数 | `1` | 增大会延长任务时间并增加收敛时间 |
| `--track_ki` | 末端位置外环积分增益 | `0.02` | 示例设为 `0`，关闭积分补偿 |
| `--track_clamp` | 积分补偿限幅，单位米 | `0.08` | 仅在 `track_ki > 0` 时生效 |

正式写盘前，可在脚本化命令中加入 `--dry_run`，同时省略 `--lerobot_out` 和 `--repo_id`。该模式只运行轨迹，不连接相机，也不创建数据集。

---

## 路点标注

`g1_pick_waypoint_mark.py` 用于在新场景中采集关键路径点：遥操机器人到目标姿态后按键记录，本轮结束后所有点自动合并为一个任务路点 YAML（记录按钮名），可直接用于脚本化采集。

### 启动命令

请先加载任务布局并启动仿真，再执行：

```bash
OMP_NUM_THREADS=1 python g1_pick_waypoint_mark.py \
    --task_config example.yaml \
    --agent_name g1_pick \
    --button_name 拨杆1 \
    --file_stem toggle \
    --out_dir my_waypoint_button/marked \
    --default_steps 300 \
    --joint_strip on \
    --strip_col off \
    --time_step 0.001 \
    --frame_skip 5
```

| 参数 | 含义 | 默认值 |
|------|------|--------|
| `--button_name` | 本次操作的按钮名称（写入路点 YAML 的 `button_name` 字段） | 必填 |
| `--task` | 任务语言描述（写入路点 YAML 的 `task` 字段） | 留空 |
| `--file_stem` | 输出文件名主干（建议英文，如 `press`/`rotate`/`toggle`） | 未传时使用 `--button_name` |
| `--out_dir` | 标注结果输出目录 | `my_waypoint_button/marked` |
| `--default_steps` | 每段写入的默认 `steps` 数 | `300` |
| `--joint_strip` / `--strip_col` | 任务模型配置 | 与采集脚本保持一致 |

### 操作方式

| 按键 | 功能 |
|------|------|
| 左手柄 Grip | 开始 / 结束当前轮遥操（开始前手臂冻结） |
| 右手柄位姿 | 遥操右臂到目标姿态 |
| 右手柄 A / B / 扳机 | 张开 / 闭合 / 连续控制右夹爪 |
| 左手柄 X | **记录当前点**：保存右臂末端 B 系位姿 + 当前夹爪状态 |
| 左右 Grip 同按 / Ctrl+C | 退出 |

### 旋钮任务采点顺序

以旋转式按钮为例，进入遥操后依次：

1. 靠近旋钮上方 → 按 X（点 1：接近姿态，夹爪张开）
2. 下移夹爪包住旋钮 → 按 X（点 2：套住姿态，夹爪张开）
3. 闭合夹爪 → 按 X（点 3：抓住姿态，夹爪闭合）
4. 旋转到目标角度 → 按 X（点 4：旋转后姿态，夹爪闭合）
5. 张开夹爪 → 按 X（点 5：松开姿态，夹爪张开）
6. 抬离撤回 → 按 X（点 6：离开姿态）

每次按 X 记录一个点（末端 B 系位姿 + 夹爪 open/close 自动判定），本轮按左 Grip 结束后，所有点合并保存为 `my_waypoint_<file_stem>_<轮次>.yaml`（`--file_stem` 未传时使用 `button_name`）：

```yaml
button_name: 旋钮1        # 来自 --button_name
task: 旋转旋转式按钮       # 来自 --task（未传则留空）
gripper_open: -1.0
gripper_close: 2

segments:                 # 本轮按 X 记录的全部点，按记录顺序排列
  - steps: 300
    l_hold: true
    r_target_b: [...]
    r_quat_b: [...]
    gripper_r: open
  - ...
```

### 用于自动化采集

标注文件可直接传给脚本化采集。任务名优先级：命令行 `--task`（提供时覆盖，仅运行时生效、不修改 YAML 文件）> 路点 YAML 的 `task` > 默认值。带 `task` 的多个路点文件分别作为独立 episode：

```bash
# YAML 中 task 为空时，用命令行 --task 指定（不改文件）
python g1_pick_osc_collection_scripted_lerobot.py \
    --waypoint_files my_waypoint_button/marked/my_waypoint_rotate_01.yaml \
    --task "旋转旋转式按钮" ...

# YAML 中已写入 task 后可直接使用
python g1_pick_osc_collection_scripted_lerobot.py \
    --waypoint_files my_waypoint_button/marked/my_waypoint_rotate_01.yaml ...
```

> [!NOTE]
> 每个标注段的 `steps` 默认为 `--default_steps`，请根据该段运动幅度手动调整（如旋转段需要更长时间可增大）。该脚本为独立工具，不影响数据采集主流程。

---

## 数据回放

`g1_pick_osc_replay_lerobot.py` 从 LeRobot 数据集的 parquet 文件中读取 18 维 action，只驱动右臂 OSC 和右夹爪进行回放。回放不读取数据集视频，也不需要连接相机。

请加载与采集时相同的布局并启动仿真，再执行：

```bash
OMP_NUM_THREADS=1 python g1_pick_osc_replay_lerobot.py \
    --dataset_dir $HOME/binjiang_datasets/g1_osc_scripted \
    --task_config example.yaml \
    --agent_name g1_pick \
    --joint_strip on \
    --strip_col off \
    --time_step 0.001 \
    --frame_skip 5 \
    --steps_per_frame 10 \
    --dls_lambda 0.23 \
    --dls_sigma_th 0.12 \
    --null_kp 10 \
    --kp 0 \
    --track_ki 0 \
    --track_clamp 0.08
```

| 参数 | 含义 | 默认值 | 使用建议 |
|------|------|--------|----------|
| `--dataset_dir` | 待回放的 LeRobot 数据集根目录 | 无，必须指定 | 目录下应存在 `data/chunk-*` |
| `--episode` | 只回放第 N 集，编号从 1 开始 | 未指定时回放全部 | 仅查看指定回合时使用 |
| `--loop` | 全部播完后从头循环 | 未启用 | 循环展示时追加 |
| `--steps_per_frame` | 每个 parquet 帧重复执行的控制步数 | `10` | 20 FPS、5 ms 控制周期时与原采样周期对应 |
| `--settle_steps` | 开播前保持初始目标的控制步数 | `10` | 初始状态不稳定时增加 |
| `--render_every` | 每隔多少控制步渲染一次 | `5` | `0` 可关闭渲染 |
| `--track_ki` | 回放位置积分补偿增益 | `0.0` | 默认关闭 |
| `--track_log_every` | 每隔多少帧打印跟踪残差 | `20` | 排查轨迹偏差时调整 |

例如，只回放第 1 集时在命令末尾追加 `--episode 1`。需要循环回放时追加 `--loop`，并在主机终端按 `Ctrl+C` 退出。

---

## OSC 与物理参数

遥操作、脚本化采集和回放应使用一致的机器人名称、任务模型配置和物理步长。

| 参数 | 含义 | 推荐或示例值 |
|------|------|--------------|
| `--dls_lambda` | DLS 最大阻尼系数；设为 0 使用原始伪逆 | 遥操作 `0.2`，脚本化/回放 `0.23` |
| `--dls_sigma_th` | 最小奇异值触发阈值；0 表示固定阻尼 | `0.12` |
| `--null_kp` | 零空间关节复原增益 | `10` |
| `--kp` | 脚本化/回放的 OSC 阻抗刚度覆盖值 | `0` 表示沿用控制器配置 |
| `--joint_strip` | 任务模型配置 | `on` |
| `--strip_col` | 任务模型的碰撞配置 | `off` 使用采集配置，`keep` 保留完整配置 |
| `--time_step` | MuJoCo 单个物理步长 | `0.001` 秒 |
| `--frame_skip` | 每个控制周期执行的物理步数 | `5` |

`time_step=0.001` 且 `frame_skip=5` 时，一个控制周期为 5 ms。回放使用 `steps_per_frame=10` 时，每个 20 FPS 数据帧保持约 50 ms。

---

## example.yaml 关键字段

Unitree G1 任务配置位于 `src/examples/dataCollection/unitree_g1/example.yaml`：

```yaml
level_name: "example"
type: "pick_and_place"
data_collection:
  agent_joint_prefix: "g1_pick_"
```

运行时，三个入口脚本都会根据 `--agent_name` 覆盖 `agent_joint_prefix`。因此最重要的是保证命令中的 `--agent_name` 与当前布局中的机器人名称完全一致。

---

## 配置与入口文件

| 文件 | 说明 |
|------|------|
| `src/examples/dataCollection/unitree_g1/example.yaml` | 场景和数据采集配置 |
| `src/examples/dataCollection/unitree_g1/g1_pick_buttons.json` | 按钮场景；显式配置头部 7090、右腕 7080 |
| `src/examples/dataCollection/unitree_g1/g1_pick_osc_collection_tele_lerobot.py` | Pico 遥操作和 LeRobot 数据采集 |
| `src/examples/dataCollection/unitree_g1/g1_pick_osc_collection_scripted_lerobot.py` | 路点插值与脚本化数据采集 |
| `src/examples/dataCollection/unitree_g1/g1_pick_waypoint_mark.py` | 关键路点标注工具 |
| `src/examples/dataCollection/unitree_g1/g1_pick_osc_replay_lerobot.py` | LeRobot parquet 数据回放 |
| `src/examples/dataCollection/unitree_g1/my_waypoint_button/marked/*.yaml` | 路点标注生成的按钮任务路点 |
| `src/dataStorage/lerobot_camera.py` | 相机名称、端口和 WebSocket 连接实现 |
| `src/dataStorage/g1_pick_osc_data_storage.py` | Unitree G1 的 18 维 state/action 定义 |

入口会根据命令行参数加载相应的任务模型配置，无需单独运行辅助模块。

---

## 数据集格式

### 目录结构

采集结果采用 LeRobot v2.1 格式：

```text
<dataset_root>/
├── meta/
│   ├── info.json
│   ├── episodes.jsonl
│   ├── episodes_stats.jsonl
│   └── tasks.jsonl
├── data/chunk-000/
│   └── episode_XXXXXX.parquet
└── videos/chunk-000/
    ├── observation.images.cam_head/
    └── observation.images.cam_wrist_r/
```

默认采集分辨率为 480×640，默认帧率为 20 FPS。WebSocket 模式下，相机帧由 NVENC 流式编码为 MP4。

### state 与 action

`observation.state` 和 `action` 均为 18 维：

```text
[左末端位置 3,
 左末端四元数 xyzw 4,
 右末端位置 3,
 右末端四元数 xyzw 4,
 左夹爪归一化控制量 2,
 右夹爪归一化控制量 2]
```

默认 `action[i]` 为下一采样时刻的绝对 state，即 `state[i+1]`。回放脚本读取其中的右末端位置、右末端四元数和右夹爪控制量，只驱动右臂与右夹爪。

训练、分析或系统集成时，请以数据集内 `meta/info.json` 的 feature 定义为准。

---

## 启动前检查

- 已安装仓库要求的运行环境，并激活 `orcalab_lerobot`。
- 已订阅 `Binjiang_Competition_2026` 与 `g1_pick` 资产。
- 已加载与任务对应的布局并启动仿真。
- 命令中的 `--agent_name` 与布局机器人名称完全一致。
- `example.yaml` 的 `level_name` 与 OrcaLab 场景名称一致。
- OrcaGym 服务 `localhost:50051` 已就绪。
- 头部相机端口为 `7090`，右腕相机端口为 `7080`。
- 两路相机均已启用 `Color Camera`、`UseNvEnc` 和相机组件。
- Pico 已被 `adb devices` 识别，并已执行 `adb reverse tcp:8001 tcp:8001`。
- GPU、NVIDIA 驱动和 PyAV/FFmpeg 支持 `av1_nvenc`。
- 数据集输出目录可写且磁盘空间充足。
- 按钮路点带有 `my_waypoint_button/` 前缀。

---

## 故障排查

**现象**：脚本找不到机器人或初始化失败。 **处理**：当前按钮布局的机器人名称是 `g1_pick`；使用自定义布局时，请检查 `AgentList` 并将 `--agent_name` 改为实际名称。

**现象**：相机端口 `7080` 或 `7090` 超时。 **处理**：当前布局显式配置了右腕 `7080`、头部 `7090`；请确认仿真已运行，并检查 `Color Camera`、`UseNvEnc` 和相机启用状态。

**现象**：Pico 显示已连接，但机器人不动。 **处理**：连接成功后还要第一次按下左 Grip 才会开始当前集并解除采集前冻结。

**现象**：Pico 没有输入。 **处理**：执行 `adb devices`，确认设备已授权，再重新执行 `adb reverse tcp:8001 tcp:8001`，并确认 Pico 端应用已启动。

**现象**：脚本化采集找不到路点文件。 **处理**：相对路径以 `src/examples/dataCollection/unitree_g1` 为基准，按钮任务使用 `my_waypoint_button/文件名.yaml`，多个文件之间只用逗号分隔。

**现象**：使用 `--resume` 时拒绝续写。 **处理**：检查旧数据集的 state/action feature 和相机键是否与当前命令一致。不要向不同 schema 或不同相机组合的数据集续写。

**现象**：视频编码失败或报找不到 `av1_nvenc`。 **处理**：确认 NVIDIA GPU 和驱动支持 AV1 NVENC，并使用仓库安装脚本配置的 PyAV/FFmpeg 环境。

**现象**：脚本报模块找不到。 **处理**：确认已激活 `orcalab_lerobot`，并在仓库根目录重新执行 `bash scripts/install_runtime.sh`。
