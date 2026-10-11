import ast
import colorsys
import hashlib
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'stratus_assembly_colors.py').read_text()

class ArtifactTests(unittest.TestCase):
    def test_graph(self):
        graph = json.loads((ROOT / 'STRATUS Assembly Colors.dyn').read_text())
        node = next(n for n in graph['Nodes'] if n['NodeType'] == 'PythonScriptNode')
        self.assertEqual(node['Code'], SOURCE)
        self.assertEqual(node['Engine'], 'CPython3')
        self.assertEqual(graph['View']['Dynamo']['RunType'], 'Manual')
        self.assertFalse(graph['Nodes'][0]['InputValue'])
        outputs = {p['Id'] for n in graph['Nodes'] for p in n['Outputs']}
        inputs = {p['Id'] for n in graph['Nodes'] for p in n['Inputs']}
        for c in graph['Connectors']:
            self.assertIn(c['Start'], outputs)
            self.assertIn(c['End'], inputs)
        compile(SOURCE, 'node', 'exec')

    def test_prepare_view(self):
        from types import SimpleNamespace
        helper = next(n for n in ast.parse(SOURCE).body
                      if isinstance(n, ast.FunctionDef) and n.name == 'prepare_view')
        env = {'ElementId': SimpleNamespace(InvalidElementId=-1)}
        exec(compile(ast.Module(body=[helper], type_ignores=[]), 'helper', 'exec'), env)
        calls = []
        view = SimpleNamespace(ViewTemplateId=99,
            GetFilters=lambda: [SimpleNamespace(Value=x) for x in (1, 2, 3)],
            SetIsFilterEnabled=lambda fid, enabled: calls.append((fid.Value, enabled)))
        env['prepare_view'](view, {2})
        self.assertEqual(view.ViewTemplateId, -1)
        self.assertEqual(calls, [(1, False), (3, False)])

    def test_names_and_palette(self):
        module = ast.parse(SOURCE)
        helpers = ast.Module(body=[n for n in module.body if isinstance(n, ast.FunctionDef)
                                  and n.name in ('filter_name', 'choose_color')], type_ignores=[])
        env = dict(colorsys=colorsys, hashlib=hashlib, re=re, PREFIX='DYN STRATUS - ')
        exec(compile(helpers, 'helpers', 'exec'), env)
        name = env['filter_name']
        self.assertEqual(name('a', 1, [3, 2]), name('a', 1, [2, 3]))
        self.assertNotEqual(name('a/b', 1, [2]), name('a_b', 1, [2]))
        self.assertNotEqual(name('a', 1, [2]), name('a', 1, [3]))
        forbidden = set('{}[]|;<>?`~')
        for value in ['SP-001', '{}[]|;<>?`~', 'spool\nname', 'x' * 300]:
            generated = name(value, 1, [2])
            self.assertFalse(forbidden.intersection(generated))
            self.assertNotIn('\n', generated)
            self.assertLess(len(generated), 256)
        used = []
        for _ in range(40):
            c = env['choose_color'](used)
            self.assertNotIn(c, used)
            self.assertTrue(all(0 <= x <= 255 for x in c))
            used.append(c)

if __name__ == '__main__':
    unittest.main()
