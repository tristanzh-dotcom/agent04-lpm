from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from functools import lru_cache
from typing import Any


def _placemark_to_display_name(placemark: Any) -> str | None:
    """把 macOS CLPlacemark 压缩成用户能看懂的位置文本。"""

    parts: list[str] = []
    for attr in ("locality", "subLocality", "name"):
        value = getattr(placemark, attr, None)
        if callable(value):
            value = value()
        value = str(value or "").strip()
        if value and value not in parts:
            parts.append(value)
    return " ".join(parts) if parts else None


class MacOSReverseGeocoder:
    """使用 macOS CoreLocation 做反向地理编码，失败时返回 None。

    这是对 Apple Photos 位置显示逻辑的本地优先补强。CoreLocation 可能调用
    Apple 系统服务，并且依赖 `pyobjc-framework-CoreLocation`；缺失依赖或超时
    时调用方应回退到粗粒度城市映射。
    """

    def __init__(self, *, timeout: float = 3.0) -> None:
        self.timeout = timeout

    @lru_cache(maxsize=4096)
    def __call__(self, latitude: float, longitude: float) -> str | None:
        if (
            threading.current_thread() is not threading.main_thread()
            and os.environ.get("LIMB_GEOCODER_SUBPROCESS") != "1"
        ):
            return self._call_in_main_process(latitude, longitude)
        return _corelocation_reverse_geocode(latitude, longitude, self.timeout)

    def _call_in_main_process(self, latitude: float, longitude: float) -> str | None:
        script = (
            "import json;"
            "from backend.geocoding import _corelocation_reverse_geocode;"
            f"print(json.dumps(_corelocation_reverse_geocode({float(latitude)!r}, {float(longitude)!r}, {float(self.timeout)!r})))"
        )
        env = {**os.environ, "LIMB_GEOCODER_SUBPROCESS": "1"}
        try:
            completed = subprocess.run(
                [sys.executable, "-c", script],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout + 1.0,
                env=env,
            )
        except Exception:
            return None
        if completed.returncode != 0:
            return None
        try:
            value = json.loads(completed.stdout.strip() or "null")
        except json.JSONDecodeError:
            return None
        return str(value) if value else None


def _corelocation_reverse_geocode(latitude: float, longitude: float, timeout: float) -> str | None:
    try:
        import CoreLocation
        import Foundation
    except Exception:
        return None

    event = threading.Event()
    result: dict[str, str | None] = {"name": None}

    def handler(placemarks: Any, error: Any) -> None:
        try:
            if not error and placemarks and len(placemarks) > 0:
                result["name"] = _placemark_to_display_name(placemarks[0])
        finally:
            event.set()

    try:
        location = CoreLocation.CLLocation.alloc().initWithLatitude_longitude_(float(latitude), float(longitude))
        geocoder = CoreLocation.CLGeocoder.alloc().init()
        geocoder.reverseGeocodeLocation_completionHandler_(location, handler)
        deadline = time.monotonic() + timeout
        run_loop = Foundation.NSRunLoop.currentRunLoop()
        mode = getattr(Foundation, "NSDefaultRunLoopMode", "kCFRunLoopDefaultMode")
        while not event.is_set() and time.monotonic() < deadline:
            run_loop.runMode_beforeDate_(mode, Foundation.NSDate.dateWithTimeIntervalSinceNow_(0.05))
        return result["name"]
    except Exception:
        return None
