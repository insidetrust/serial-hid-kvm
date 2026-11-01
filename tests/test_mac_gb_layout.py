"""Tests for the mac-gb layout, null (unsupported) overrides, and fail-closed typing."""

import string
from unittest.mock import MagicMock, call

import pytest

from serial_hid_kvm import hid_keycodes
from serial_hid_kvm.hid_keyboard import Keyboard
from serial_hid_kvm.hid_keycodes import (
    MOD_LALT,
    MOD_LSHIFT,
    MOD_NONE,
    build_char_map,
    char_to_hid,
    set_layout,
)
from serial_hid_kvm.hid_layouts import SUPPORTED_LAYOUTS


@pytest.fixture(autouse=True)
def _restore_us104():
    """Leave the module-global layout as it was (US104) after each test."""
    yield
    set_layout("us104")


# --- mac-gb mappings -------------------------------------------------------


def test_mac_gb_is_a_builtin_layout():
    assert "mac-gb" in SUPPORTED_LAYOUTS


def test_mac_gb_hash_is_option_3():
    set_layout("mac-gb")
    assert char_to_hid("#") == (MOD_LALT, 0x20)


def test_mac_gb_at_and_quote_stay_on_us_positions():
    """Apple British differs from PC UK here: @ = Shift+2, " = Shift+'."""
    set_layout("mac-gb")
    assert char_to_hid("@") == (MOD_LSHIFT, 0x1F)
    assert char_to_hid('"') == (MOD_LSHIFT, 0x34)


def test_mac_gb_backslash_and_pipe_stay_on_us_positions():
    set_layout("mac-gb")
    assert char_to_hid("\\") == (MOD_NONE, 0x31)
    assert char_to_hid("|") == (MOD_LSHIFT, 0x31)


def test_mac_gb_backtick_and_tilde_are_unsupported():
    set_layout("mac-gb")
    assert char_to_hid("`") is None
    assert char_to_hid("~") is None


def test_mac_gb_letters_digits_unchanged_from_us104():
    us = build_char_map("us104")
    gb = build_char_map("mac-gb")
    for ch in string.ascii_letters + string.digits:
        assert gb[ch] == us[ch], ch


def test_mac_gb_only_intended_differences_from_us104():
    us = build_char_map("us104")
    gb = build_char_map("mac-gb")
    changed = {c for c in us if gb.get(c) != us[c]}
    assert changed == {"#", "`", "~"}


def test_merged_maps_never_contain_none():
    for layout in SUPPORTED_LAYOUTS:
        assert None not in build_char_map(layout).values(), layout


# --- null overrides in custom layouts --------------------------------------


def test_null_override_removes_character(tmp_path):
    (tmp_path / "custom.yaml").write_text("overrides:\n  'x': null\n")
    merged = build_char_map("custom", layouts_dir=str(tmp_path))
    assert "x" not in merged
    assert merged["y"] == build_char_map("us104")["y"]


def test_malformed_mapping_raises(tmp_path):
    (tmp_path / "bad.yaml").write_text("overrides:\n  'x': [none]\n")
    with pytest.raises(ValueError, match="must be \\[modifier, keycode\\] or null"):
        build_char_map("bad", layouts_dir=str(tmp_path))


# --- fail-closed typing: nothing is sent if any character is unsupported ---


def _keyboard() -> tuple[Keyboard, MagicMock]:
    dev = MagicMock()
    return Keyboard(dev, char_delay=0), dev


def test_type_text_rejects_whole_string_before_typing():
    set_layout("mac-gb")
    kb, dev = _keyboard()
    with pytest.raises(ValueError, match="Unsupported character: '~'.*'mac-gb'.*Nothing was typed"):
        kb.type_text("rm -rf ~/x{enter}")
    dev.send_keyboard.assert_not_called()


def test_type_text_raw_rejects_before_typing_earlier_lines():
    """An earlier line must not be typed + entered when a later one is bad."""
    set_layout("mac-gb")
    kb, dev = _keyboard()
    with pytest.raises(ValueError, match="Unsupported character: '`'"):
        kb.type_text("echo ok\nls `pwd`", raw=True)
    dev.send_keyboard.assert_not_called()


def test_type_text_sends_mapped_keys_under_mac_gb():
    set_layout("mac-gb")
    kb, dev = _keyboard()
    kb.type_text("a#")
    assert dev.send_keyboard.call_args_list == [
        call(MOD_NONE, 0x04),
        call(MOD_LALT, 0x20),
    ]


def test_us104_still_types_backtick_and_tilde():
    """The fail-closed entries are layout-specific, not global."""
    assert hid_keycodes.get_layout() == "us104"
    kb, dev = _keyboard()
    kb.type_text("`~")
    assert dev.send_keyboard.call_count == 2
