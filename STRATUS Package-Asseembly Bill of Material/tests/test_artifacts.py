import ast
import datetime
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
import zipfile
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'stratus_package_bill_of_material.py').read_text()


class ArtifactTests(unittest.TestCase):
    def test_graph_and_source(self):
        graph = json.loads((ROOT / 'Stratus Package Bill of Material.dyn').read_text())
        node = next(n for n in graph['Nodes'] if n['NodeType'] == 'PythonScriptNode')
        self.assertEqual(node['Code'], SOURCE)
        self.assertEqual(node['Engine'], 'CPython3')
        self.assertEqual(graph['View']['Dynamo']['RunType'], 'Manual')
        compile(SOURCE, 'python-node', 'exec')

    def test_names_and_scope(self):
        for text in ["SCHEDULE_NAME = 'Stratus Package Bill of Material'",
                     "PACKAGE = 'STRATUS Package Name'", 'OST_FabricationPipework',
                     "PHASE_NAME = 'New Construction'", 'UnitTypeId.Feet',
                     'part.IsAStraight()', "'shop weld bw', 'shop cs'",
                     'AutoCompleteMode.SuggestAppend', "BOM_CLASS = 'Stratus BOM Category'",
                     "BOM_LENGTH = 'Stratus BOM Total Length'", 'ComboBox',
                     'DialogResult.Retry', 'DialogResult.Ignore',
                     'zipfile.is_zipfile(path)']:
            self.assertIn(text, SOURCE)
        self.assertNotIn('OST_FabricationHangers)', SOURCE)
        self.assertNotIn('.Click +=', SOURCE)
        self.assertLess(SOURCE.index("result['excel'] = export_excel"),
                        SOURCE.index('manager = TransactionManager.Instance'))
        self.assertIn("result['status'] = 'Excel saved, but the Revit schedule update failed.'", SOURCE)

    def test_aggregate_sorting(self):
        function = next(n for n in ast.parse(SOURCE).body
                        if isinstance(n, ast.FunctionDef) and n.name == 'aggregate')
        env = {'OrderedDict': __import__('collections').OrderedDict}
        exec(compile(ast.Module(body=[function], type_ignores=[]), 'aggregate', 'exec'), env)
        records = [
            {'package': 'P1', 'assembly': 'A1', 'category': 'Fitting', 'description': 'Tee', 'size': '2', 'length_internal': 0},
            {'package': 'P1', 'assembly': 'A1', 'category': 'Fitting', 'description': 'Elbow', 'size': '3', 'length_internal': 0},
            {'package': 'P1', 'assembly': 'A2', 'category': 'Fitting', 'description': 'Elbow', 'size': '3', 'length_internal': 0},
            {'package': 'P1', 'assembly': 'A2', 'category': 'Pipe', 'description': 'Copper', 'size': '2', 'length_internal': 12},
            {'package': None, 'assembly': 'A3', 'category': 'Pipe', 'description': 'Steel', 'size': '4', 'length_internal': 50},
        ]
        fittings, pipe = env['aggregate'](records, ['P1'], ['A1'])
        self.assertEqual([r['description'] for r in fittings], ['Elbow', 'Tee'])
        self.assertEqual(fittings[0]['count'], 2)
        self.assertEqual(pipe[0]['length_internal'], 12)
        fittings, pipe = env['aggregate'](records, [], ['A3'])
        self.assertEqual(fittings, [])
        self.assertEqual(pipe[0]['description'], 'Steel')

    def test_xlsx_has_separate_valid_sheets(self):
        names = {'excel_path', 'xml_text', 'xlsx_cell', 'worksheet_xml', 'export_excel'}
        helpers = [n for n in ast.parse(SOURCE).body
                   if isinstance(n, ast.FunctionDef) and n.name in names]
        class FakeUnitUtils:
            @staticmethod
            def ConvertFromInternalUnits(value, unit):
                return value
        class FakeUnitTypeId:
            Feet = 'feet'
        env = {'datetime': datetime, 'os': os, 're': re, 'zipfile': zipfile,
               'UnitUtils': FakeUnitUtils, 'UnitTypeId': FakeUnitTypeId}
        exec(compile(ast.Module(body=helpers, type_ignores=[]), 'xlsx', 'exec'), env)
        fittings = [{'description': 'Elbow & Tee', 'size': '2 in', 'count': 3, 'length_internal': 0}]
        pipe = [{'description': 'Copper', 'size': '2 in', 'count': 2, 'length_internal': 24.5}]
        with tempfile.TemporaryDirectory() as folder:
            path = env['export_excel'](fittings, pipe, ['PK-01', 'PK-02'], ['ASM-10'], folder)
            self.assertRegex(Path(path).name, r'^Stratus BOM - \d{4}-\d{2}-\d{2} \d{6}\.xlsx$')
            with zipfile.ZipFile(path) as book:
                for name in ('xl/workbook.xml', 'xl/worksheets/sheet1.xml',
                             'xl/worksheets/sheet2.xml', 'xl/styles.xml'):
                    ElementTree.fromstring(book.read(name))
                workbook = book.read('xl/workbook.xml').decode('utf-8')
                self.assertIn('name="Fittings"', workbook)
                self.assertIn('name="Pipe"', workbook)
                self.assertIn('Elbow &amp; Tee', book.read('xl/worksheets/sheet1.xml').decode('utf-8'))
                self.assertIn('Total Length (ft)', book.read('xl/worksheets/sheet2.xml').decode('utf-8'))
                self.assertIn('PK-01, PK-02', book.read('xl/worksheets/sheet1.xml').decode('utf-8'))
                self.assertIn('ASM-10', book.read('xl/worksheets/sheet1.xml').decode('utf-8'))


if __name__ == '__main__':
    unittest.main()
