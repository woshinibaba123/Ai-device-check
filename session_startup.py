"""Conservative, process-local Android initialization cache."""
import threading
import time

_ready = set()
_lock = threading.Lock()


def create(caps, request, command, adb, log):
    key = None
    if caps.get('platformName') == 'Android':
        device = caps['appium:udid']
        # A boot identifier invalidates the cache after reconnecting a rebooted device.
        try:
            boot = command([adb, '-s', device, 'shell', 'cat', '/proc/sys/kernel/random/boot_id'])
            token = boot.get('output', '').strip()
            if boot.get('ok') and token:
                key = (device, token)
        except Exception:
            pass  # Failure to inspect the device always selects full initialization.
    with _lock:
        warm = key is not None and key in _ready
    options = dict(caps)
    if warm:
        options['appium:skipDeviceInitialization'] = True
        log('设备本次开机已完成初始化，跳过重复初始化（保留驱动版本检查）。')
    started = time.monotonic()
    try:
        result = request('POST', '/session', {'capabilities': {'alwaysMatch': options, 'firstMatch': [{}]}})
        if not isinstance(result, dict) or not result.get('sessionId'):
            raise RuntimeError('Appium 未返回有效测试会话。')
    except BaseException:
        with _lock:
            _ready.discard(key)
        log(f'创建测试会话未完成，已耗时 {time.monotonic()-started:.1f} 秒；下次执行完整初始化。')
        # Never retry a timed-out POST: the server may still be creating its session.
        raise
    with _lock:
        if key is not None:
            _ready.add(key)
    log(f'测试会话已就绪，耗时 {time.monotonic()-started:.1f} 秒。')
    return result
