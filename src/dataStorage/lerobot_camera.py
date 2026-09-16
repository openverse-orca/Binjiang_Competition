"""Camera helpers for LeRobot data collection.

OrcaStudio streams configured cameras over WebSocket. This module provides camera
maps, live-frame capture, and resolution detection. A camera map has the form
``{environment_camera_name: (dataset_key, port), ...}``.
"""
import io
import logging
import socket
import time

import cv2
import numpy as np

_logger = logging.getLogger(__name__)

# 默认相机映射：头部 + 右腕。
DEFAULT_CAMERA_MAP = {
    "camera_head_color": ("cam_head", 7090),
    "camera_wrist_r_color": ("cam_wrist_r", 7080),
}
# Optional left-wrist camera.
WRIST_L_CAMERA = {
    "camera_wrist_l_color": ("cam_wrist_l", 7070),
}
DEFAULT_HW = (480, 640)


def camera_keys(camera_map: dict) -> list[str]:
    """返回 LeRobot 相机键列表（写入数据集 features 时用）。"""
    return [key for (key, _port) in camera_map.values()]


# ---------------------------------------------------------------------------
# 鲁棒相机启动（TCP 端口探测 + WebSocket 连接 + 首帧等待 + 线程重启）
# ---------------------------------------------------------------------------

def _annexb_at(data: bytes, off: int) -> bool:
    """data[off:] 是否以 Annex-B 起始码（00 00 01 / 00 00 00 01）开头。"""
    if off + 3 > len(data):
        return False
    if data[off] == 0 and data[off + 1] == 0 and data[off + 2] == 1:
        return True
    return off + 4 <= len(data) and data[off:off + 4] == b"\x00\x00\x00\x01"


def _strip_ws_header(data: bytes) -> bytes:
    """剥掉 WebSocket 帧头，返回 Annex-B NAL 数据。

    orcagym 26.8+ 帧格式为 [8B 时间戳][4B simulate_index][NAL]（12 字节头），
    旧版为 8 字节头。按 Annex-B 起始码位置自动识别，优先按新版 12 字节处理。
    """
    if _annexb_at(data, 12):
        return data[12:]
    if _annexb_at(data, 8):
        return data[8:]
    return data[12:]


_WS_CAMERA_CLS = None


def _ws_camera_cls():
    """构造适配新版 WebSocket 帧头的 CameraWrapper 子类（懒加载并缓存）。"""
    global _WS_CAMERA_CLS
    if _WS_CAMERA_CLS is None:
        import av
        import websockets
        from orca_gym.sensor.rgbd_camera import CameraWrapper  # type: ignore[import]

        class _WsCameraWrapper(CameraWrapper):
            """按帧头长度自适应的相机拉流（逻辑与父类一致，仅剥头不同）。"""

            async def do_stuff(self):
                uri = f"ws://localhost:{self.port}"
                async with websockets.connect(uri) as websocket:
                    cur_pos = 0
                    rawData = io.BytesIO()
                    container = None
                    while self.running:
                        data = await websocket.recv()
                        data = _strip_ws_header(data)
                        rawData.write(data)
                        rawData.seek(cur_pos)
                        if cur_pos == 0:
                            container = av.open(rawData, mode='r')
                        for packet in container.demux():
                            if packet.size == 0:
                                continue
                            frames = packet.decode()
                            for frame in frames:
                                self.image = frame.to_ndarray(format='bgr24')
                                self.image_index += 1
                                if self.received_first_frame == False:
                                    self.received_first_frame = True
                        cur_pos += len(data)

        _WS_CAMERA_CLS = _WsCameraWrapper
    return _WS_CAMERA_CLS


def wait_ports_open(
    camera_map: dict,
    timeout: float,
    host: str = "127.0.0.1",
) -> dict:
    """等待 OrcaStudio 打开各相机推流端口（TCP 可连），返回 {env_name: port}。

    启动 CameraWrapper 前会轮询各 TCP 端口，直到就绪或达到超时时间。

    Args:
        camera_map: {env_name: (lerobot_key, port)}。
        timeout: 最长等待秒数。
        host: 探测 IP（默认 127.0.0.1）。

    Returns:
        {env_name: port}，仅包含已就绪的相机端口；超时未就绪的被跳过并记 WARNING。
    """
    deadline = time.time() + timeout
    pending = {name: port for name, (_key, port) in camera_map.items()}
    ready: dict = {}
    print(f"[相机] 等待推流端口就绪（最长 {timeout:.0f}s）...", flush=True)
    while pending and time.time() < deadline:
        for name in list(pending):
            port = pending[name]
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.5)
                if sock.connect_ex((host, port)) == 0:
                    ready[name] = port
                    del pending[name]
                    print(f"  ✓ 端口 {port}（{name}）已就绪", flush=True)
        if pending:
            print(f"  等待端口: {sorted(pending.values())}", flush=True)
            time.sleep(1.0)
    if pending:
        _logger.warning(
            "[相机] 以下端口超时未就绪，将跳过：%s\n"
            "        请确认 OrcaStudio 已加载带相机的场景且开始渲染。",
            sorted(pending.values()),
        )
    return ready


def bring_up_cameras(
    camera_map: dict,
    port_timeout: float = 30.0,
    frame_timeout: float = 30.0,
    render_fn=None,
) -> dict:
    """稳健地拉起相机推流：端口就绪探测 → 连接 → 等首帧（线程退出则重启）。

    返回成功收到首帧的 {env_name: CameraWrapper}。任何相机失败都不会抛异常，
    只会被跳过并记 WARNING，保证主流程可控降级。

    Args:
        camera_map: {env_name: (lerobot_key, port)}。
        port_timeout: 等待端口就绪的最长秒数（默认 30s）。
        frame_timeout: 等待首帧到达的最长秒数（默认 30s）。
        render_fn: 等待首帧期间反复调用的回调（无参数）。orcagym 26.8+ 的
            引擎只在 render() 调用时编码推流相机帧，采集循环尚未启动的
            初始化阶段必须主动触发渲染，否则永远收不到首帧。

    Returns:
        {env_name: CameraWrapper}，仅包含已收到首帧的相机。
    """
    CamCls = _ws_camera_cls()

    ready = wait_ports_open(camera_map, timeout=port_timeout)
    if not ready:
        return {}

    cameras: dict = {}
    for name, port in ready.items():
        cam = CamCls(name=name, port=port)
        cam.start()
        cameras[name] = cam
        print(f"  ✓ 相机 {name} 已连接（端口 {port}）", flush=True)

    max_restart = 3
    restarts = {name: 0 for name in cameras}
    print(f"[相机] 等待首帧就绪（最长 {frame_timeout:.0f}s）...", flush=True)
    deadline = time.time() + frame_timeout
    while time.time() < deadline:
        pending = [n for n, c in cameras.items() if not c.is_first_frame_received()]
        if not pending:
            print("[相机] ✓ 所有相机首帧已就绪", flush=True)
            return cameras
        if render_fn is not None:
            try:
                render_fn()
            except Exception:
                pass
        for name in pending:
            thread = getattr(cameras[name], "thread", None)
            if (thread is None or not thread.is_alive()) and restarts[name] < max_restart:
                restarts[name] += 1
                _logger.warning(
                    "相机 %s 后台线程已退出，重启（第 %d/%d 次）",
                    name, restarts[name], max_restart,
                )
                cam = CamCls(name=name, port=ready[name])
                cam.start()
                cameras[name] = cam
        print(f"  等待首帧: {pending}", flush=True)
        time.sleep(1.0)

    alive = {n: c for n, c in cameras.items() if c.is_first_frame_received()}
    dropped = [n for n in cameras if n not in alive]
    if dropped:
        _logger.warning("[相机] 超时仍未收到首帧，丢弃：%s", dropped)
        close_cameras({n: cameras[n] for n in dropped})
    return alive


# ---------------------------------------------------------------------------
# WebSocket 流式取帧（主路径）
# ---------------------------------------------------------------------------

def capture_frame_with_idx(
    cameras: dict,
    camera_map: dict,
    target_hw: tuple,
) -> tuple[dict, dict]:
    """从 CameraWrapper 内存流取最新帧，同时返回各相机 image_index 供对齐诊断。

    Args:
        cameras: {env_name: CameraWrapper}，来自 bring_up_cameras()。
        camera_map: {env_name: (lerobot_key, port)}。
        target_hw: (H, W) 目标分辨率，用 INTER_AREA 缩放。

    Returns:
        (images, indices)
        images:  {lerobot_key: (H,W,3) uint8 ndarray, RGB}
        indices: {env_name: image_index}，连续两次 index 相同表示取到重复帧。
    """
    H, W = target_hw
    images: dict = {}
    indices: dict = {}
    for env_name, (key, _port) in camera_map.items():
        cam = cameras[env_name]
        frame, idx = cam.get_frame(format="rgb24")
        if frame.shape[0] != H or frame.shape[1] != W:
            frame = cv2.resize(frame, (W, H), interpolation=cv2.INTER_AREA)
        images[key] = np.ascontiguousarray(frame, dtype=np.uint8)
        indices[env_name] = idx
    return images, indices


def probe_camera_hw(cameras: dict, camera_map: dict, default_hw: tuple = DEFAULT_HW) -> tuple:
    """返回 WebSocket 首帧分辨率；首帧不可用时返回 ``default_hw``。"""
    first_env_name = next(iter(camera_map.keys()), None)
    if first_env_name is None or first_env_name not in cameras:
        return default_hw
    try:
        cam = cameras[first_env_name]
        frame, _ = cam.get_frame(format="rgb24")
        if frame is not None and frame.ndim == 3 and frame.size > 0:
            return (int(frame.shape[0]), int(frame.shape[1]))
    except Exception as e:
        print(f"[相机] 未能读取首帧分辨率，使用配置值 {default_hw}")
    return default_hw


# 相机角色关键词：逻辑名片段 → 注册名需包含的 token（按优先级降序尝试）。
# orcagym 26.8+ 后端注册名带 uuid 后缀，不能直接使用逻辑名。
_ROLE_TOKENS = {
    "head": ("head_cam", "head"),
    "wrist_r": ("camera_right", "right"),
    "wrist_l": ("camera_left", "left"),
}


def resolve_registered_cameras(env, camera_map: dict) -> tuple[dict, list[str]]:
    """把 camera_map 的逻辑相机名解析为后端注册名（含 uuid 后缀）。

    通过 env.get_camera_names() 枚举后端已注册相机，按角色关键词匹配。
    返回 (resolved, registered)：resolved 是 {逻辑名: 注册名}，
    registered 是后端注册名列表（查询失败时为空）。
    匹配不到的逻辑名保留原名，由后续 start_streaming 给出明确报错。
    """
    try:
        registered = list(env.get_camera_names())
    except Exception:
        registered = []
    resolved: dict[str, str] = {}
    for logical in camera_map:
        if not registered or logical in registered:
            resolved[logical] = logical
            continue
        role = next((r for r in _ROLE_TOKENS if r in logical), None)
        cands: list[str] = []
        if role:
            for tok in _ROLE_TOKENS[role]:
                cands = [r for r in registered if tok in r]
                if cands:
                    break
        else:
            cands = [r for r in registered if logical in r]
        # 多个候选时取最短（主实体名短于派生 body 相机名）
        resolved[logical] = min(cands, key=len) if cands else logical
    return resolved, registered


def setup_cameras(camera_map: dict) -> dict:
    """启动已配置的 WebSocket 相机流。"""
    from orca_gym.sensor.rgbd_camera import CameraWrapper  # type: ignore[import]
    cameras = {}
    for name, (_key, port) in camera_map.items():
        try:
            cam = CameraWrapper(name=name, port=port)
            cam.start()
            cameras[name] = cam
            print(f"✓ 相机 {name} 已启动（端口 {port}）", flush=True)
        except Exception as e:
            print(f"✗ 相机 {name} 启动失败（端口 {port}）: {e}", flush=True)
    return cameras


def wait_for_cameras(cameras: dict, timeout: float = 30.0) -> None:
    """等待 WebSocket 相机首帧就绪。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        pending = [n for n, c in cameras.items() if not c.is_first_frame_received()]
        if not pending:
            return
        time.sleep(1.0)


def close_cameras(cameras: dict) -> None:
    """停止 WebSocket 相机线程。"""
    for cam in cameras.values():
        try:
            cam.running = False
        except Exception:
            pass
    for cam in cameras.values():
        thread = getattr(cam, "thread", None)
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
