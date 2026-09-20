import argparse
import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(line_buffering=True)

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import numpy as np
from yaml import Loader, dump, load

import mj_joint_strip

from conf import g1_pick_osc_conf
from controllers import controllers
from controllers.controller_task import TaskStatus
from dataCollectionManager.data_collection_manager import DataCollectionManager
from devices.abstract_device import PicoJoystickDevice
from orca_gym.devices.pico_joytsick import PicoJoystick, PicoJoystickKey
from orca_gym.log.orca_log import OrcaLog, get_orca_logger
from scene.scene_manager import SceneManager
from task.abstract_task import EmptyTask

ENTRY_POINT = "envs.dataCollection.dataCollection_env:DataCollectionEnv"

base_dir = os.path.dirname(os.path.realpath(__file__))
log_dir = os.path.join(base_dir, "logs")

orca_logger = get_orca_logger(
    name="G1PickWaypointMark",
    log_file="g1_pick_waypoint_mark.log",
    max_bytes=10 * 1024 * 1024,
    backup_count=5,
    console_level="INFO",
    file_level="INFO",
    log_dir=log_dir,
    use_colors=True,
    force_reinit=True,
)

# 双臂初始姿态；左臂使用预设停靠位姿，右臂从零位开始。
_L_INIT_JOINT_VALUES = [0.0, 0.127, 0.0, 1.5708, 0.0, 0.0, 0.0]
_R_INIT_JOINT_VALUES = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def pin_floating_base(env, agent_name: str) -> bool:
    """在仿真步进期间保持浮动基座的参考位姿。"""
    import mujoco

    gym = getattr(env, "gym", None) or getattr(
        getattr(env, "unwrapped", env), "gym", None
    )
    if gym is None or not hasattr(gym, "_mjModel") or not hasattr(gym, "_mjData"):
        orca_logger.warning("[CONSTRAINT] 基座姿态约束初始化失败：模型状态不可用")
        return False

    mj, md = gym._mjModel, gym._mjData
    jname = f"{agent_name}_floating_base_joint"
    jid = mujoco.mj_name2id(mj, mujoco.mjtObj.mjOBJ_JOINT, jname)
    if jid < 0:
        orca_logger.warning("[CONSTRAINT] 基座姿态约束初始化失败：模型不兼容")
        return False

    qadr = int(mj.jnt_qposadr[jid])
    dadr = int(mj.jnt_dofadr[jid])
    q0 = np.array(md.qpos[qadr : qadr + 7], dtype=np.float64, copy=True)
    _orig_mj_step = gym.mj_step

    def _mj_step_pinned(nstep=1):
        n = int(nstep) if nstep is not None else 1
        for _ in range(max(n, 1)):
            md.qpos[qadr : qadr + 7] = q0
            md.qvel[dadr : dadr + 6] = 0.0
            _orig_mj_step(1)
            md.qpos[qadr : qadr + 7] = q0
            md.qvel[dadr : dadr + 6] = 0.0
        mujoco.mj_forward(mj, md)

    gym.mj_step = _mj_step_pinned
    return True


def pin_waist_joints(env, agent_name: str) -> bool:
    """在仿真步进期间保持腰部参考姿态。"""
    import mujoco

    gym = getattr(env, "gym", None) or getattr(
        getattr(env, "unwrapped", env), "gym", None
    )
    if gym is None or not hasattr(gym, "_mjModel") or not hasattr(gym, "_mjData"):
        orca_logger.warning("[CONSTRAINT] 腰部姿态约束初始化失败：模型状态不可用")
        return False

    mj, md = gym._mjModel, gym._mjData
    joint_names = g1_pick_osc_conf.locked_waist_joints
    qadrs: list[int] = []
    dadrs: list[int] = []
    q0s: list[float] = []
    for short in joint_names:
        full = f"{agent_name}_{short}"
        jid = mujoco.mj_name2id(mj, mujoco.mjtObj.mjOBJ_JOINT, full)
        if jid < 0:
            orca_logger.warning("[CONSTRAINT] 腰部姿态约束初始化失败：模型不兼容")
            return False
        qadr = int(mj.jnt_qposadr[jid])
        dadr = int(mj.jnt_dofadr[jid])
        qadrs.append(qadr)
        dadrs.append(dadr)
        q0s.append(float(md.qpos[qadr]))

    _orig_mj_step = gym.mj_step

    def _mj_step_waist_pinned(nstep=1):
        n = int(nstep) if nstep is not None else 1
        for _ in range(max(n, 1)):
            for qadr, q0 in zip(qadrs, q0s):
                md.qpos[qadr] = q0
            for dadr in dadrs:
                md.qvel[dadr] = 0.0
            _orig_mj_step(1)
            for qadr, q0 in zip(qadrs, q0s):
                md.qpos[qadr] = q0
            for dadr in dadrs:
                md.qvel[dadr] = 0.0
        mujoco.mj_forward(mj, md)

    gym.mj_step = _mj_step_waist_pinned
    orca_logger.info("[CONSTRAINT] 腰部姿态约束已启用")
    return True


def pin_left_arm_joints(env, agent_name: str) -> bool:
    """在仿真步进期间保持左臂的预设停靠姿态。"""
    import mujoco

    gym = getattr(env, "gym", None) or getattr(
        getattr(env, "unwrapped", env), "gym", None
    )
    if gym is None or not hasattr(gym, "_mjModel") or not hasattr(gym, "_mjData"):
        orca_logger.warning("[CONSTRAINT] 左臂姿态约束初始化失败：模型状态不可用")
        return False

    mj, md = gym._mjModel, gym._mjData
    joint_names = g1_pick_osc_conf.l_arm["joint_names"]
    motor_names = g1_pick_osc_conf.l_arm["motors_names"]
    target_qpos = list(g1_pick_osc_conf.l_arm["neutral_joint_values"])

    qadrs: list[int] = []
    dadrs: list[int] = []
    for short in joint_names:
        full = f"{agent_name}_{short}"
        jid = mujoco.mj_name2id(mj, mujoco.mjtObj.mjOBJ_JOINT, full)
        if jid < 0:
            orca_logger.warning("[CONSTRAINT] 左臂姿态约束初始化失败：模型不兼容")
            return False
        qadrs.append(int(mj.jnt_qposadr[jid]))
        dadrs.append(int(mj.jnt_dofadr[jid]))

    act_ids: list[int] = []
    for short in motor_names:
        full = f"{agent_name}_{short}"
        aid = mujoco.mj_name2id(mj, mujoco.mjtObj.mjOBJ_ACTUATOR, full)
        if aid < 0:
            orca_logger.warning("[CONSTRAINT] 左臂姿态约束初始化失败：执行器不兼容")
            return False
        act_ids.append(aid)

    # 初始化左臂参考姿态
    for qadr, q0 in zip(qadrs, target_qpos):
        md.qpos[qadr] = float(q0)
    for dadr in dadrs:
        md.qvel[dadr] = 0.0
    for aid in act_ids:
        md.ctrl[aid] = 0.0
    mujoco.mj_forward(mj, md)

    _orig_mj_step = gym.mj_step

    def _mj_step_larm_pinned(nstep=1):
        n = int(nstep) if nstep is not None else 1
        for _ in range(max(n, 1)):
            for qadr, q0 in zip(qadrs, target_qpos):
                md.qpos[qadr] = float(q0)
            for dadr in dadrs:
                md.qvel[dadr] = 0.0
            for aid in act_ids:
                md.ctrl[aid] = 0.0
            _orig_mj_step(1)
            for qadr, q0 in zip(qadrs, target_qpos):
                md.qpos[qadr] = float(q0)
            for dadr in dadrs:
                md.qvel[dadr] = 0.0
            for aid in act_ids:
                md.ctrl[aid] = 0.0
        mujoco.mj_forward(mj, md)

    gym.mj_step = _mj_step_larm_pinned
    orca_logger.info("[CONSTRAINT] 左臂停靠姿态约束已启用")
    return True


def _fmt_vec(v: list[float], nd: int = 4) -> str:
    return "[" + ", ".join(f"{x:.{nd}f}" for x in v) + "]"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="G1 路点标注：遥操到关键姿态后按 X 记录，每轮合并保存为一个任务路点 YAML"
    )
    parser.add_argument(
        "--button_name", required=True, help="本次操作的按钮名称（写入路点 YAML）"
    )
    parser.add_argument(
        "--task",
        default="",
        help="任务语言描述（写入路点 YAML 的 task 字段，未传则留空）",
    )
    parser.add_argument(
        "--file_stem",
        default="",
        help="输出文件名主干（建议英文，如 press/rotate/toggle）；未传时使用 --button_name",
    )
    parser.add_argument(
        "--level", type=str, default="default", help="场景的名称（默认 default）"
    )
    parser.add_argument(
        "--task_config", default="example.yaml", help="场景配置 YAML 文件名"
    )
    parser.add_argument("--orcagym_addr", default="localhost:50051")
    parser.add_argument(
        "--agent_name",
        default="g1_pick",
        help="OrcaStudio 场景中的 agent 名称",
    )
    parser.add_argument(
        "--out_dir",
        default=os.path.join(base_dir, "my_waypoint_button", "marked"),
        help="标注结果输出目录（默认 my_waypoint_button/marked）",
    )
    parser.add_argument(
        "--default_steps",
        type=int,
        default=300,
        help="每个标注段写入的默认 steps 数（默认 300）",
    )
    parser.add_argument(
        "--joint_strip",
        choices=["off", "on"],
        default="off",
        help="选择任务模型配置：on 使用采集任务配置，off 使用完整模型配置。",
    )
    parser.add_argument(
        "--strip_col",
        choices=["off", "keep"],
        default="off",
        help="任务模型的碰撞配置：off 使用采集碰撞配置，keep 保留完整碰撞配置。",
    )
    parser.add_argument(
        "--time_step", type=float, default=0.001, help="MuJoCo 物理步长（秒）。"
    )
    parser.add_argument(
        "--frame_skip", type=int, default=5, help="每控制周期的物理子步数。"
    )
    args = parser.parse_args()

    out_dir = os.path.abspath(os.path.expanduser(args.out_dir))
    os.makedirs(out_dir, exist_ok=True)

    # ── 关节初值（任务模型已含约束时仅用于文档，不实际下发）─────────────────────
    default_joint_values: dict = {}
    for jn, v in zip(g1_pick_osc_conf.l_arm["joint_names"], _L_INIT_JOINT_VALUES):
        default_joint_values[jn] = v
    for jn, v in zip(g1_pick_osc_conf.r_arm["joint_names"], _R_INIT_JOINT_VALUES):
        default_joint_values[jn] = v

    # ── VR 设备 ───────────────────────────────────────────────────────────
    print("=" * 60, flush=True)
    print("  G1 路点标注启动中...", flush=True)
    print(f"  场景: {args.level}  agent: {args.agent_name}", flush=True)
    print(f"  输出目录: {out_dir}", flush=True)
    print("  等待 Pico 连接...", flush=True)
    print("=" * 60, flush=True)
    pico_device = PicoJoystickDevice(PicoJoystick())

    # ── 场景管理 ──────────────────────────────────────────────────────────
    orca_logger.info("Creating scene manager")
    with open(
        os.path.abspath(os.path.join(base_dir, args.task_config)), "r", encoding="utf-8"
    ) as f:
        scene_config = load(f, Loader=Loader)
    if "data_collection" in scene_config:
        scene_config["data_collection"]["agent_joint_prefix"] = f"{args.agent_name}_"
    else:
        scene_config["data_collection"] = {"agent_joint_prefix": f"{args.agent_name}_"}
    scene_manager = SceneManager(args.orcagym_addr, config=scene_config)

    script_name = os.path.basename(sys.argv[0]) if sys.argv else os.path.basename(__file__)
    scene_manager.show_ui_message(
        1, "开始路点标注，请按左手柄 Grip 开始遥操", "0xffff00", showtime=10
    )
    scene_manager.get_scene_data(script_name, "beginscene")

    # ── 任务模型配置（必须在环境创建前注册）───────────────────────────────
    strip = None
    if args.joint_strip == "on":
        keep = mj_joint_strip.KEEP_DEFAULT + tuple(g1_pick_osc_conf.l_arm["joint_names"])
        strip = mj_joint_strip.install(
            None,
            args.agent_name,
            keep=keep,
            kill_collision=(args.strip_col == "off"),
            required_cameras=(),
            log=lambda m: (orca_logger.info(m), print(m, flush=True)),
        )

    # ── DataCollectionManager ─────────────────────────────────────────────
    orca_logger.info("Creating DataCollectionManager")
    manager = DataCollectionManager(
        agent_name=args.agent_name,
        env_name="DataCollection",
        entry_point=ENTRY_POINT,
        default_joint_values={},
        obs_callback=lambda _env: {
            "dummy": np.zeros(1, dtype=np.float32),
        },
        env_index=0,
        device=pico_device,
        scene_manager=scene_manager,
        data_storage=None,
        frame_skip=args.frame_skip,
        time_step=args.time_step,
        orcagym_addr=args.orcagym_addr,
    )
    env = manager.env
    manager.save_video = False

    # 按当前模型过滤初始关节状态
    stripped = bool(strip is not None and strip.applied)
    if stripped:
        alive = set(env.model.get_joint_dict() or {})
        dropped = [j for j in default_joint_values if env.joint(j) not in alive]
        for j in dropped:
            default_joint_values.pop(j)
        orca_logger.info(f"[MODEL] 初始状态配置完成（{len(default_joint_values)} 个关节）")

    # ── 场景就绪后初始化控制器 ────────────────────────────────────────────
    r_ee_site = env.site(g1_pick_osc_conf.r_arm["ee_site_name"])
    r_grip_act_names = g1_pick_osc_conf.gripper_r["actuator_names"]
    r_grip_ranges = g1_pick_osc_conf.gripper_r["actuator_ranges"]
    r_grip_act_ids = [env.model.actuator_name2id(env.actuator(n)) for n in r_grip_act_names]

    # 夹爪控制值 → open/close 的映射（2F85 反向：低值为 open，高值为 close）
    _grip_open_v = min(r_grip_ranges[0])
    _grip_close_v = max(r_grip_ranges[0])
    _grip_mid_v = (_grip_open_v + _grip_close_v) / 2.0

    marked_points: list = []
    _last_mark_t = {"t": 0.0}
    _MARK_DEBOUNCE = 0.5  # X 键防抖（秒）

    def _grip_state_from_ctrl() -> str:
        try:
            vals = [float(env.ctrl[aid]) for aid in r_grip_act_ids if aid < len(env.ctrl)]
            if not vals:
                return "close"
            return "open" if float(np.mean(vals)) < _grip_mid_v else "close"
        except Exception:
            return "close"

    def _mark_current():
        now = time.perf_counter()
        if now - _last_mark_t["t"] < _MARK_DEBOUNCE:
            return
        _last_mark_t["t"] = now

        # 仅允许在遥操运行状态下标注，避免采集前冻结位姿被误记录
        tsc = manager.task_status_controller
        if tsc is None or tsc.current_status != TaskStatus.RUNNING:
            orca_logger.warning("[标注] 请先按左手柄 Grip 进入遥操状态，再按 X 标注")
            print("[标注] 未在遥操状态，本次忽略（先按左手柄 Grip 开始）", flush=True)
            return

        try:
            ee = env.query_site_pos_and_quat_B(
                [r_ee_site], [env.body(g1_pick_osc_conf.base_body)]
            )
            pos_b = [float(x) for x in np.asarray(ee[r_ee_site]["xpos"]).reshape(-1)]
            _q_wxyz = np.asarray(ee[r_ee_site]["xquat"]).reshape(-1)  # wxyz（MuJoCo 约定）
            quat_b = [float(x) for x in _q_wxyz[[1, 2, 3, 0]]]  # 转为 xyzw（B 系）
        except Exception as e:
            orca_logger.error(f"[标注] 读取末端位姿失败: {e}")
            return

        grip_state = _grip_state_from_ctrl()
        idx = len(marked_points) + 1

        seg = {
            "steps": int(args.default_steps),
            "l_hold": True,
            "r_target_b": [round(p, 4) for p in pos_b],
            "r_quat_b": [round(q, 4) for q in quat_b],
            "gripper_r": grip_state,
        }
        marked_points.append(seg)

        msg = (
            f"[标注 #{idx}] pos={_fmt_vec(pos_b)} quat={_fmt_vec(quat_b)} "
            f"gripper={grip_state}"
        )
        orca_logger.info(msg)
        print(msg, flush=True)
        try:
            scene_manager.show_ui_message(
                1, f"已记录点 {idx}（{grip_state}）", "0x00ff00", showtime=2
            )
        except Exception:
            pass

    def _dump_marked(ep_idx: int) -> str | None:
        """本轮结束：把已记录的点合并为一个任务路点 YAML。"""
        if not marked_points:
            return None
        safe_name = (args.file_stem.strip() or args.button_name).strip().replace(" ", "_") or "button"
        doc = {
            "button_name": args.button_name,
            "task": str(args.task).strip(),
            "gripper_open": float(_grip_open_v),
            "gripper_close": float(_grip_close_v),
            "segments": marked_points,
        }
        fname = os.path.join(out_dir, f"my_waypoint_{safe_name}_{ep_idx:02d}.yaml")
        try:
            with open(fname, "w", encoding="utf-8") as f:
                dump(doc, f, allow_unicode=True, sort_keys=False)
        except Exception as e:
            orca_logger.error(f"[标注] 写入失败: {e}")
            return None
        return fname

    try:
        env.reset()
        time.sleep(0.1)
        if strip is not None:
            mj_joint_strip.finish_install(
                env, strip, args.agent_name,
                log=lambda m: (orca_logger.info(m), print(m, flush=True)),
            )
        if manager.update_scene():
            env.set_default_joint_values(default_joint_values)

            # 右夹爪：用 A/B/扳机控制（采点时需要手动开合夹爪）
            orca_logger.info("Adding right gripper controller")
            controllers.add_gripper_2f85_reverse_pico_controller(
                manager,
                env,
                g1_pick_osc_conf.gripper_r,
                g1_pick_osc_conf.base_body,
                pico_device,
                [PicoJoystickKey.A, PicoJoystickKey.B, PicoJoystickKey.R_TRIGGER],
            )

            # 右臂 OSC 遥操
            orca_logger.info("Adding right arm OSC controller")
            controllers.add_arm_osc_pico_controller(
                manager,
                env,
                g1_pick_osc_conf.r_arm,
                g1_pick_osc_conf.base_body,
                pico_device,
                PicoJoystickKey.R_TRANSFORM,
            )

            # 姿态约束（任务模型已含基座/腰部/左臂约束则跳过）
            if not stripped:
                pin_floating_base(env, args.agent_name)
                pin_waist_joints(env, args.agent_name)
                pin_left_arm_joints(env, args.agent_name)

            # 任务状态（左 Grip 开始/结束遥操）
            manager.set_task(EmptyTask(env))
            controllers.add_task_status_pico_controller(
                manager, env, pico_device, g1_pick_osc_conf.base_body
            )

            # X 键绑定标注事件（X 为左手柄主键，采点脚本专用，不影响其他脚本）
            pico_device.bind_primary_button_event(
                PicoJoystickKey.X, lambda pressed: pressed and _mark_current()
            )

            print("[场景] 机器人已就绪，相机未启用", flush=True)
    except KeyboardInterrupt:
        orca_logger.info("初始化阶段收到 Ctrl+C")
    except Exception as e:
        orca_logger.error(f"初始化失败: {e}")
        try:
            env.close()
        except Exception:
            pass
        return

    # ── 输入门控：开始遥操前冻结手臂，仅放行左 Grip 与 X（X 在 RUNNING 校验）──
    _LOCKED_KEYS: set = {PicoJoystickKey.L_TRANSFORM}
    _all_pico_keys = [k for k in pico_device.keys if k not in _LOCKED_KEYS]
    _pre_start_keys = [k for k in _all_pico_keys if k == PicoJoystickKey.L_GRIPBUTTON]

    def _gated_pico_update():
        tsc = manager.task_status_controller
        if tsc is not None and tsc.current_status == TaskStatus.RUNNING:
            pico_device.pico_joystick.update(_all_pico_keys)
        else:
            pico_device.pico_joystick.update(_pre_start_keys)

    pico_device.update = _gated_pico_update

    print("", flush=True)
    print("=" * 60, flush=True)
    print("  ✓ 进入路点标注主循环", flush=True)
    print("-" * 60, flush=True)
    print("  【操作按键】", flush=True)
    print("  右臂移动    右手柄位姿 (持握激活)", flush=True)
    print("  右夹爪      A 张开 / B 闭合 / 右扳机连续", flush=True)
    print("  标注路点    左手柄 X 键（记录当前末端位姿+夹爪状态）", flush=True)
    print("-" * 60, flush=True)
    print("  【流程】", flush=True)
    print("  开始遥操  →  轻按【左手柄 Grip】", flush=True)
    print("  标注路点  →  遥操到关键姿态后按【左手柄 X】", flush=True)
    print(f"  结束本轮  →  再按【左手柄 Grip】（本轮点合并保存，按钮名: {args.button_name}）", flush=True)
    print("  退出      →  【左右 Grip 同时按下】或 Ctrl+C", flush=True)
    print("=" * 60, flush=True)
    print("", flush=True)
    try:
        scene_manager.show_ui_message(
            1, "左Grip=开始 左手X=记录点 左Grip=结束 左右Grip=退出", "0x00ff00", showtime=0
        )
    except Exception:
        pass

    # ── 主循环 ────────────────────────────────────────────────────────────
    orca_logger.info(f"开始路点标注，输出目录: {out_dir}")
    _ep_idx = 0
    try:
        while not manager._shutdown_requested:  # noqa: SLF001
            _ep_idx += 1
            env.reset()
            time.sleep(0.1)
            if not manager.update_scene():
                orca_logger.info("update_scene 失败，停止标注")
                break
            env.set_default_joint_values(default_joint_values)
            marked_points.clear()

            orca_logger.info(f"========== 标注第 {_ep_idx} 轮 ==========")
            print(
                f"\n>>> 标注第 {_ep_idx} 轮（按左Grip开始，遥操中按左手X记录点）",
                flush=True,
            )

            manager.run_episode()

            # 本轮结束（含退出前的最后一轮）：合并写出本轮全部标注点
            out_file = _dump_marked(_ep_idx)
            n_pts = len(marked_points)
            if out_file is not None:
                orca_logger.info(
                    f"[EP {_ep_idx}] 本轮结束，共 {n_pts} 个点 → {os.path.basename(out_file)}"
                )
                print(
                    f">>> 本轮结束，共 {n_pts} 个点，已合并保存: {os.path.basename(out_file)}",
                    flush=True,
                )
            else:
                orca_logger.info(f"[EP {_ep_idx}] 本轮结束，未记录任何点")
                print(">>> 本轮结束，未记录任何点", flush=True)

            if manager._shutdown_requested:  # noqa: SLF001
                orca_logger.info("结束标注（左右Grip/Ctrl+C）")
                print("\n[结束] 已停止标注", flush=True)
                break

    except KeyboardInterrupt:
        orca_logger.info("KeyboardInterrupt，停止标注")
        print("\n[停止] 标注已中断", flush=True)
    except Exception as e:
        orca_logger.error(f"标注异常: {e}")
    finally:
        try:
            scene_manager.show_ui_message(1, "", showtime=0)
            env.render()
        except Exception:
            pass
        try:
            env.close()
        except Exception:
            pass
        summary = f"标注结束，输出目录: {out_dir}"
        orca_logger.info(summary)
        print(f"\n{'=' * 60}", flush=True)
        print(f"  {summary}", flush=True)
        print(f"{'=' * 60}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        orca_logger.info("已收到中断请求")
    except Exception as e:
        OrcaLog.get_instance().error(f"程序异常: {e}")
    finally:
        orca_logger.info("程序已退出")
        os._exit(0)
