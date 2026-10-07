import ast
import inspect
import sys
import unittest

from acs import tactile_dotpad_adapter as adapter_mod
from acs import tactile_dotpad_contract as contract
from acs import tactile_dotpad_sdk as sdk_mod


class NeverConnectSdk:
    def __init__(self): self.disconnected = 0
    def connect_serial(self, port_name): pass
    def connect_ble(self, device_name): pass
    def connected_count(self): return 0
    def connected_handle(self, index): raise AssertionError
    def display_info(self, handle): raise AssertionError
    def display_data(self, payload, handle): raise AssertionError
    def reset_display(self, handle): return True
    def disconnect(self, handle): self.disconnected += 1; return True
    def close(self): pass


def frame(width, height, raised=()):
    pins = [False] * (width * height)
    for x, y in raised:
        pins[y * width + x] = True
    return contract.TactilePinFrame(width, height, tuple(pins))


class Section9Tests(unittest.TestCase):
    def test_settings_validate_transport(self):
        s = contract.DotPadSettings(serial_port=" COM7 ", connect_timeout_seconds=0.1)
        self.assertEqual(s.serial_port, "COM7")
        b = contract.DotPadSettings(connection="ble", ble_name=" DotPad320-test ")
        self.assertEqual(b.ble_name, "DotPad320-test")
        with self.assertRaises(contract.TactileAdapterError) as ctx:
            contract.DotPadSettings(connection="serial")
        self.assertEqual(ctx.exception.code, contract.TactileAdapterErrorCode.INVALID_SETTINGS)

    def test_encoder_uses_standard_eight_dot_cell_bits(self):
        expected = [1, 2, 4, 8, 16, 32, 64, 128]
        coords = [(0,0),(0,1),(0,2),(1,0),(1,1),(1,2),(0,3),(1,3)]
        for coord, value in zip(coords, expected):
            self.assertEqual(contract.encode_dotpad_graphics(frame(2,4,[coord]), cell_width=1, cell_height=1), bytes([value]))
        self.assertEqual(contract.encode_dotpad_graphics(frame(2,4,coords), cell_width=1, cell_height=1), b"\xff")

    def test_geometry_mismatch_fails_closed(self):
        with self.assertRaises(contract.TactileAdapterError) as ctx:
            contract.encode_dotpad_graphics(frame(4,4), cell_width=1, cell_height=1)
        self.assertEqual(ctx.exception.code, contract.TactileAdapterErrorCode.GEOMETRY_MISMATCH)

    def test_connect_render_clear_disconnect(self):
        sdk = sdk_mod.DotPadSdkSimulator(cell_width=2, cell_height=1, braille=True)
        adapter = adapter_mod.DotPadTactileAdapter(contract.DotPadSettings(serial_port="COM3", connect_timeout_seconds=0.1), sdk=sdk)
        caps = adapter.connect()
        self.assertEqual(caps.provider, "dotpad")
        self.assertEqual((caps.geometry.width, caps.geometry.height), (4,4))
        self.assertTrue(caps.supports_graphics)
        self.assertTrue(caps.supports_braille)
        adapter.render(frame(4,4,[(0,0),(3,3)]))
        self.assertEqual(adapter.last_payload, bytes([1,128]))
        self.assertEqual(sdk.last_payload, bytes([1,128]))
        self.assertTrue(adapter.status.connected)
        adapter.clear(); self.assertIsNone(sdk.last_payload)
        adapter.disconnect(); self.assertFalse(adapter.status.connected); self.assertFalse(sdk.connected)
        adapter.close()

    def test_ble_path_has_same_simulator_parity(self):
        sdk = sdk_mod.DotPadSdkSimulator(cell_width=1, cell_height=1)
        adapter = adapter_mod.DotPadTactileAdapter(contract.DotPadSettings(connection="ble", ble_name="DotPad320-test", connect_timeout_seconds=0.1), sdk=sdk)
        adapter.connect(); adapter.render(frame(2,4,[(1,3)]))
        self.assertEqual(adapter.last_payload, b"\x80")
        adapter.close()

    def test_render_failure_resets_display(self):
        sdk = sdk_mod.DotPadSdkSimulator(cell_width=1, cell_height=1)
        adapter = adapter_mod.DotPadTactileAdapter(contract.DotPadSettings(serial_port="COM4", connect_timeout_seconds=0.1), sdk=sdk)
        adapter.connect(); sdk.fail_next_render = True
        with self.assertRaises(contract.TactileAdapterError) as ctx:
            adapter.render(frame(2,4,[(0,0)]))
        self.assertEqual(ctx.exception.code, contract.TactileAdapterErrorCode.RENDER_FAILED)
        self.assertEqual(sdk.reset_count, 1)
        self.assertIsNone(adapter.last_payload)
        self.assertEqual(adapter.status.state, "error")
        adapter.close()

    def test_disconnect_clears_pins_by_default(self):
        sdk = sdk_mod.DotPadSdkSimulator(cell_width=1, cell_height=1)
        adapter = adapter_mod.DotPadTactileAdapter(contract.DotPadSettings(serial_port="COM5", connect_timeout_seconds=0.1), sdk=sdk)
        adapter.connect(); adapter.render(frame(2,4,[(0,0)])); adapter.disconnect()
        self.assertEqual(sdk.reset_count, 1); self.assertIsNone(sdk.last_payload)

    def test_timeout_is_stable_and_fail_safe(self):
        sdk = NeverConnectSdk()
        adapter = adapter_mod.DotPadTactileAdapter(contract.DotPadSettings(serial_port="COM6", connect_timeout_seconds=0.05), sdk=sdk)
        with self.assertRaises(contract.TactileAdapterError) as ctx:
            adapter.connect()
        self.assertEqual(ctx.exception.code, contract.TactileAdapterErrorCode.CONNECT_TIMEOUT)
        self.assertGreaterEqual(sdk.disconnected, 1); self.assertFalse(adapter.status.connected)

    def test_disconnected_render_is_rejected(self):
        sdk = sdk_mod.DotPadSdkSimulator(cell_width=1, cell_height=1)
        adapter = adapter_mod.DotPadTactileAdapter(contract.DotPadSettings(serial_port="COM7", connect_timeout_seconds=0.1), sdk=sdk)
        with self.assertRaises(contract.TactileAdapterError) as ctx:
            adapter.render(frame(2,4))
        self.assertEqual(ctx.exception.code, contract.TactileAdapterErrorCode.NOT_CONNECTED)
        self.assertIsNone(sdk.last_payload)

    def test_import_is_safe_without_windows_or_physical_device(self):
        self.assertTrue(hasattr(sdk_mod, "CtypesDotPadSdkApi"))
        if sys.platform != "win32":
            with self.assertRaises(contract.TactileAdapterError) as ctx:
                sdk_mod.CtypesDotPadSdkApi()
            self.assertEqual(ctx.exception.code, contract.TactileAdapterErrorCode.UNSUPPORTED_PLATFORM)

    def test_device_modules_have_no_chess_rule_imports(self):
        forbidden = ("chesscore", "board_service", "game_tree", "position", "pgn", "engine")
        for module in (contract, sdk_mod, adapter_mod):
            tree = ast.parse(inspect.getsource(module))
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import): imports.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom): imports.append(node.module or "")
            self.assertFalse([name for name in imports if any(token in name.lower() for token in forbidden)])

    def test_official_sdk_symbols_are_bound_and_lazy(self):
        source = inspect.getsource(sdk_mod)
        for symbol in (
            "DOT_PAD_CONNECT_SERIAL", "DOT_PAD_CONNECT_BLE",
            "DOT_PAD_GET_CONNECTED_DEVICE_COUNT", "DOT_PAD_GET_CONNECTED_DEVICE_HANDLE",
            "DOT_PAD_GET_DISPLAY_INFO", "DOT_PAD_DISPLAY_DATA",
            "DOT_PAD_RESET_DISPLAY", "DOT_PAD_DISCONNECT",
        ):
            self.assertIn(symbol, source)
        self.assertNotIn("ctypes.WinDLL", inspect.getsource(contract))


if __name__ == "__main__":
    unittest.main()
