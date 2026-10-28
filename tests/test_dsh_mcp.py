"""The file bridge cannot turn model arguments into arbitrary shell/file access."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    'dsh_mcp', Path(__file__).resolve().parents[1] / 'scripts/dsh_mcp.py')
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
DESIGN = '[parts]\nR1 RES 1k\n[terms]\nGND GROUND\n[nets]\nR1.1,GND\n'


class DshMcpTests(unittest.TestCase):
    def test_path_traversal_extra_arguments_and_reserved_names_are_rejected(self):
        for name in ('../escape', '/absolute', r'C:\escape', 'x/y', 'NUL', 'COM1', ''):
            with self.subTest(name=name), self.assertRaises(ValueError):
                bridge.validate_arguments({'name': name, 'design': DESIGN})
        with self.assertRaises(ValueError):
            bridge.validate_arguments({'name': 'safe', 'design': DESIGN, 'command': 'anything'})
        with self.assertRaises(ValueError):
            bridge.validate_arguments({'name': 'safe', 'design': DESIGN.replace('1k', '1k PROGRAM=x')})

    def test_library_paths_and_oversized_designs_cannot_escape(self):
        for text in (DESIGN.replace('1k', '1k library=../other'), 'x' * 65537,
                     '[parts]\n' + '\n'.join(f'R{i} RES 1k' for i in range(65))):
            with self.subTest(text=text[:60]), self.assertRaises(ValueError):
                bridge.validate_arguments({'name': 'safe', 'design': text})

    def test_existing_project_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            destination = root / 'existing'
            destination.mkdir()
            sentinel = destination / 'design.txt'
            sentinel.write_text('keep me', encoding='utf-8')
            with self.assertRaises(FileExistsError):
                bridge.draw_circuit(root, {'name': 'existing', 'design': DESIGN})
            self.assertEqual(sentinel.read_text(encoding='utf-8'), 'keep me')

    def test_failure_and_interruption_keep_unpassed_evidence_and_propagate(self):
        with tempfile.TemporaryDirectory() as temp:
            interruption = KeyboardInterrupt('controlled')
            with patch('proteus86.design.from_design', side_effect=interruption):
                with self.assertRaises(KeyboardInterrupt) as caught:
                    bridge.draw_circuit(Path(temp), {'name': 'interrupted', 'design': DESIGN})
            self.assertIs(caught.exception, interruption)
            result = json.loads((Path(temp) / 'interrupted/failed.json').read_text(encoding='utf-8'))
            self.assertFalse(result['passed'])
            self.assertEqual(result['error'], 'KeyboardInterrupt')

    def test_protocol_rejects_arbitrary_tools_and_continues_after_bad_json(self):
        lines = ['bad json', json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}),
                 json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize'}),
                 json.dumps({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                             'params': {'name': 'run_shell', 'arguments': {'command': 'bad'}}}),
                 json.dumps({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/list'})]
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as temp:
            bridge.serve(Path(temp), io.StringIO('\n'.join(lines)), output)
        messages = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(messages), 4)
        self.assertEqual(messages[0]['error']['code'], -32700)
        self.assertEqual(messages[1]['result']['serverInfo']['name'], 'proteus86-file-bridge')
        self.assertTrue(messages[2]['result']['isError'])
        self.assertEqual([t['name'] for t in messages[3]['result']['tools']],
                         ['draw_circuit', 'capabilities', 'project_action', 'circuit_edit'])


if __name__ == '__main__':
    unittest.main()
