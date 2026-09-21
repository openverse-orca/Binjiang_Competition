# 物理 AI +电力场景智能机器人sim2real挑战赛

本项目为“物理 AI +电力场景智能机器人sim2real挑战赛”竞赛场景提供人形机器人数据采集与数据回放工具。

| 平台 | 交付功能 | 使用说明 |
| --- | --- | --- |
| 宇树 G1 | 按钮任务数据采集 | [数据采集](docs/unitree_g1_collection.md) |

如需基于采集数据训练策略或部署在线推理服务，请阅读 [策略服务部署](docs/openpi_deployment.md)。

## 开始前准备

### 系统与硬件

- 操作系统：Windows 11 / Ubuntu 22.04 / Ubuntu 24.04。
- Python：3.12.13。
- OrcaLab / OrcaGym：26.8.2 及以上。
- Conda：建议使用 Miniconda。
- NVIDIA 驱动：Ubuntu 验证环境要求 570 及以上；Windows 请安装与显卡匹配的最新稳定版 NVIDIA 驱动。
- 采集视频需要支持 AV1 NVENC 的 NVIDIA 40 系及以上 GPU。

### 获取代码

Windows 与 Ubuntu 使用相同命令：

```bash
git clone https://github.com/openverse-orca/Binjiang_Competition
cd Binjiang_Competition
```

## 安装运行环境

> [!IMPORTANT]
> 要求 OrcaLab 版本大于等于 26.8.2。本项目的相机链路已适配 26.8.2 的相机接口，更低版本的相机接口不兼容。

### Ubuntu 22.04 / 24.04

请在新建的 Conda 环境中执行安装：

```bash
conda env create -f environment-unitree.yml
conda activate orcalab_lerobot
bash scripts/install_runtime.sh
```

安装完成后，可使用以下命令检查运行环境：

```bash
python scripts/verify_environment.py
```

### Windows 11

Windows 下建议使用 Anaconda Prompt 或 PowerShell。当前仓库中的 `requirements.txt` 为 Linux x86-64 锁定环境，Windows 请使用 `requirements.in` 与 `constraints.txt` 安装运行依赖。

```powershell
conda create -n orcalab_lerobot python=3.12.13 pip=26.0.1 -y
conda activate orcalab_lerobot
conda install -c conda-forge numpy=2.2.6 scipy=1.16.2 -y

python -m pip install -r requirements.in -c constraints.txt
python -m pip install --no-deps "orca-gym==26.8.2" "orca-lab==26.8.2"
python -m pip install --no-deps --no-build-isolation .\third_party\lerobot .\third_party\televuer .\third_party\openpi-client
```

安装完成后启动 OrcaLab：

```powershell
orcalab
```

如需在 Windows 下使用 Pico 遥操作，请安装 [Android SDK Platform-Tools](https://developer.android.com/tools/releases/platform-tools?hl=zh-cn)。

## 首次启动与资产订阅

激活运行环境并启动 OrcaLab：

```bash
conda activate orcalab_lerobot
orcalab
```

> [!IMPORTANT]
> 首次运行任务前，必须在 OrcaLab 资产库中订阅以下资产：
>
> - `Binjiang_Competition_2026`
> - `g1_pick`

资产订阅流程：

1. 启动 OrcaLab。OrcaLab 会自动导航到资产库；如果没有自动打开，请点击“打开资产库”。
2. 在资产库网站中依次搜索上述资产名称。
3. 打开资产详情并点击“订阅”。
4. 完成订阅后关闭并重新启动 OrcaLab，等待资产同步完成。

## Pico 遥操作准备

只有使用 Pico 进行遥操作时才需要完成本节。请先按照 Openverse Orca 官方的 [VR 遥操作与数据采集操作指南](https://github.com/openverse-orca/OrcaDocs/blob/main/%E6%93%8D%E4%BD%9C%E6%8C%87%E5%8D%97/%E6%95%B0%E6%8D%AE%E9%87%87%E9%9B%86%E4%B8%8E%E5%90%88%E6%88%90/VR%E9%81%A5%E6%93%8D%E4%BD%9C%E4%B8%8E%E6%95%B0%E6%8D%AE%E9%87%87%E9%9B%86%E6%93%8D%E4%BD%9C%E6%8C%87%E5%8D%97.md) 完成 Pico 应用安装、开发者模式和设备连接。

Pico 遥操作需要 Android Platform Tools（`adb`）。

### Ubuntu

```bash
sudo apt install adb
```

### Windows

安装 Android Platform Tools 后，将其目录加入系统 `Path`，然后检查：

```powershell
adb version
```

连接 Pico 后：

```powershell
adb devices
```

如果设备连接正常，应能在设备列表中看到对应设备序列号。

## 使用流程

完成环境安装和资产订阅后，按以下顺序运行任务：

1. 根据目标平台选择[宇树 G1 数据采集](docs/unitree_g1_collection.md)。
2. 在 OrcaLab 中打开比赛场景 `Binjiang_Competition_2026`。
3. 在 OrcaLab 中加载平台文档指定的任务布局（宇树 G1 按钮任务为 `g1_pick_buttons.json`）。
4. 按平台文档检查相机配置；使用 Pico 遥操作时，同时完成设备连接和端口映射。
5. 在 OrcaLab 中启动仿真。
6. 在终端中运行所选任务的采集、回放或推理命令。

相机连接参数以平台文档和任务代码所列的映射为准。加载布局后，请按平台文档核对并配置所用相机的端口和推流选项；布局中未启用的相机不属于默认采集链路。

不同工作流之间的依赖关系如下：

- 遥操作采集可以直接创建演示数据。
- 脚本化采集需要先准备对应任务的路点或候选位姿。
- 数据回放需要已有采集数据，并使用与采集时相同的任务布局。
- 在线推理需要先部署策略服务，再使用与策略任务对应的布局启动推理客户端。

## Task prompt（任务指令）

Task prompt 是描述当前数据所执行任务的自然语言指令，例如 `按按压式按钮`、`旋转旋转式按钮` 或 `拨动拨杆式按钮`。它与 `--task_config` 不同：`--task_config` 指向场景配置 YAML，task prompt 则用于训练和推理时的语言条件。

采集程序会把 task prompt 写入 LeRobot 数据集：完整文本保存在 `meta/tasks.jsonl`，parquet 中每帧的 `task_index` 指向对应文本。因此 prompt 必须与该帧实际执行的任务一致。

- 宇树 G1 按钮自动化采集从各 `src/examples/dataCollection/unitree_g1/my_waypoint_button/marked/*.yaml` 读取 `task`；每个带 `task` 的路点文件单独生成 episode，并在该集开始前写入对应 prompt。路点文件由 `g1_pick_waypoint_mark.py` 在实际场景中标注生成（如 `my_waypoint_press_01.yaml`、`my_waypoint_rotate_01.yaml`、`my_waypoint_toggle_01.yaml`）；`--num_episodes` 表示每个文件重复采集的集数。
- 不带 `task` 的普通路点 YAML，多个文件仍按顺序组成同一个 episode，并使用命令行 `--task` 作为整集 prompt。
- Pico 遥操作采集使用命令行 `--task`。task prompt 应与本次采集实际执行的任务一致（如 `按按压式按钮`、`旋转旋转式按钮`、`拨动拨杆式按钮`）；同一次脚本启动不要混采不同任务。

示例：

```text
--task "按按压式按钮"
```

## 数据输出

采集结果采用 LeRobot v2.1 数据集格式，包含帧数据、任务信息和视频文件。相机、帧率及数据字段记录在 `meta/info.json`，task prompt 记录在 `meta/tasks.jsonl`；训练或集成时应同时读取相应元信息。

## 目录概览

```text
Binjiang_Competition/
├── docs/                    # 平台使用与部署说明
├── scripts/                 # 环境安装与检查脚本
├── src/examples/
│   ├── dataCollection/      # 数据采集和回放入口
│   └── inference/           # 在线推理入口
└── third_party/             # 随交付环境安装的运行时组件
```
