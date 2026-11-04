"""Fresh-frame capture: never return a stale queued frame or a start-up frame.

Uses a fake device instead of a camera. Each read() returns a frame whose
pixel value is its read index, so a test can tell which read it got.
"""

import threading
import time
from unittest.mock import Mock

import numpy as np
import pytest

from serial_hid_kvm import capture
from serial_hid_kvm.config import Config
from serial_hid_kvm.server import ApiDispatcher


class FakeDevice:
    def __init__(self, fail=False, interval=0.005):
        self.reads = 0
        self.fail = fail
        self.interval = interval
        self.lock = threading.Lock()

    def isOpened(self):
        return True

    def read(self):
        time.sleep(self.interval)
        if self.fail:
            return False, None
        with self.lock:
            n = self.reads
            self.reads += 1
        return True, np.full((4, 4, 3), n % 256, dtype=np.uint8)

    def release(self):
        pass


@pytest.fixture
def make_capture():
    made = []

    def _make(**kwargs):
        sc = capture.ScreenCapture(device=0, autocrop=False)
        sc._cap = FakeDevice(**kwargs)
        made.append(sc)
        return sc

    yield _make
    for sc in made:
        sc.stop_capture_thread()


def test_warmup_frames_are_never_published(make_capture):
    sc = make_capture()
    assert sc.wait_for_fresh_frame(timeout=2.0)
    assert int(sc.get_latest_frame()[0, 0, 0]) >= capture.WARMUP_FRAMES


def test_fresh_frame_comes_from_a_read_after_the_request(make_capture):
    sc = make_capture()
    assert sc.wait_for_fresh_frame(timeout=2.0)
    time.sleep(0.1)  # device keeps producing frames while nobody asks
    reads_before = sc._cap.reads
    assert sc.wait_for_fresh_frame(timeout=2.0)
    # At most one read can straddle the request time; nothing older.
    assert int(sc.get_latest_frame()[0, 0, 0]) >= reads_before - 1


def test_wait_times_out_when_device_gives_no_frames(make_capture):
    sc = make_capture(fail=True)
    assert sc.wait_for_fresh_frame(timeout=0.2) is False


def test_capture_starts_thread_and_returns_fresh_image(make_capture):
    sc = make_capture()
    image = sc.capture()
    assert sc._running
    assert image.size == (4, 4)
    assert image.getpixel((0, 0))[0] >= capture.WARMUP_FRAMES


def test_capture_raises_when_no_fresh_frame(make_capture, monkeypatch):
    sc = make_capture()
    monkeypatch.setattr(sc, "wait_for_fresh_frame", lambda timeout=2.0: False)
    with pytest.raises(RuntimeError, match="No fresh frame"):
        sc.capture()


def test_api_capture_frame_waits_for_fresh_frame():
    cap = Mock()
    cap.wait_for_fresh_frame.return_value = True
    cap.get_frame_jpeg.return_value = (b"\xff\xd8jpeg", 1280, 720)
    hw = Mock()
    hw.get_capture.return_value = cap
    dispatcher = ApiDispatcher(hw, Config())

    result = dispatcher._do_capture_frame({})

    cap.wait_for_fresh_frame.assert_called_once_with()
    assert (result["width"], result["height"]) == (1280, 720)


def test_api_capture_frame_errors_instead_of_returning_stale_frame():
    cap = Mock()
    cap.wait_for_fresh_frame.return_value = False
    hw = Mock()
    hw.get_capture.return_value = cap
    dispatcher = ApiDispatcher(hw, Config())

    with pytest.raises(RuntimeError, match="No fresh frame"):
        dispatcher._do_capture_frame({})
    cap.get_frame_jpeg.assert_not_called()
