from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


def load_commands_module():
    path = Path(__file__).resolve().parents[1] / "core" / "person_memory" / "commands.py"
    spec = importlib.util.spec_from_file_location("person_memory_commands_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load person memory commands module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PersonMemoryCommandLightweightTests(unittest.TestCase):
    def test_routes_remember_prefixed_self_arrival_with_chinese_single_quotes(self) -> None:
        module = load_commands_module()

        command = module.route_person_memory_command("记住以后见到我说‘are you ok’")

        self.assertIsNotNone(command)
        self.assertEqual(command.action, "arrival_task")
        self.assertEqual(command.content, "are you ok")
        self.assertEqual(command.target_name, "")
        self.assertTrue(command.exact)
        self.assertTrue(command.repeat)


if __name__ == "__main__":
    unittest.main()
