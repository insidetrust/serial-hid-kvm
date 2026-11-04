"""Capture settle delay: an API capture waits capture_settle_ms after the last input."""

import asyncio
import time
from unittest.mock import Mock

import pytest

from serial_hid_kvm import config as config_mod
from serial_hid_kvm.config import Config
from serial_hid_kvm.server import INPUT_METHODS, ApiDispatcher


def _dispatcher(settle_ms):
    cap = Mock()
    cap.wait_for_fresh_frame.return_value = True
    cap.get_frame_jpeg.return_value = (b"\xff\xd8jpeg", 1280, 720)
    hw = Mock()
    hw.get_capture.return_value = cap
    cfg = Config()
    cfg.capture_settle_ms = settle_ms
    return ApiDispatcher(hw, cfg), hw


def _timed_capture_after(dispatcher, method, params):
    async def run():
        await dispatcher.dispatch(method, params)
        start = time.monotonic()
        await dispatcher.dispatch("capture_frame", {})
        return time.monotonic() - start
    return asyncio.run(run())


def test_default_settle_is_150_ms():
    assert Config().capture_settle_ms == 150


def test_capture_waits_after_input():
    d, _ = _dispatcher(200)
    elapsed = _timed_capture_after(d, "mouse_click", {"x": 1, "y": 2})
    assert elapsed >= 0.18


def test_capture_does_not_wait_without_recent_input():
    d, _ = _dispatcher(200)
    start = time.monotonic()
    asyncio.run(d.dispatch("capture_frame", {}))
    assert time.monotonic() - start < 0.1


def test_non_input_methods_do_not_reset_timer():
    d, _ = _dispatcher(200)
    elapsed = _timed_capture_after(d, "ping", {})
    assert elapsed < 0.1


def test_zero_disables_settle():
    d, _ = _dispatcher(0)
    elapsed = _timed_capture_after(d, "send_key", {"key": "escape"})
    assert elapsed < 0.1


def test_failed_input_still_resets_timer():
    d, hw = _dispatcher(200)
    hw.get_mouse.return_value.click.side_effect = RuntimeError("serial error")

    async def run():
        with pytest.raises(RuntimeError):
            await d.dispatch("mouse_click", {"x": 1, "y": 2})
        start = time.monotonic()
        await d.dispatch("capture_frame", {})
        return time.monotonic() - start

    assert asyncio.run(run()) >= 0.18


def test_every_input_method_has_a_handler():
    for method in INPUT_METHODS:
        assert hasattr(ApiDispatcher, f"_do_{method}"), method


def test_env_var_sets_settle(monkeypatch):
    monkeypatch.setenv("SHKVM_CAPTURE_SETTLE_MS", "300")
    cfg = Config()
    config_mod._apply_env(cfg)
    assert cfg.capture_settle_ms == 300
