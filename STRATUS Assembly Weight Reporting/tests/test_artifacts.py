import ast
import datetime
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
import zipfile
from collections import OrderedDict
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'stratus_assembly_weight_report.py').read_text()


class ArtifactTests(unittest.TestCase):
    def test_graph_and_source(self):
        graph = json.loads((ROOT / 'STRATUS Assembly Weight Report.dyn').read_text())
        node = next(n for n in graph['Nodes'] if n['NodeType'] == 'PythonScriptNode')
        self.assertEqual(node['Code'], SOURCE)
        self.assertEqual(node['Engine'], 'CPython3')
        self.assertEqual(len(node['Inputs']), 4)
        self.assertEqual(graph['View']['Dynamo']['RunType'], 'Manual')
        bools = [n for n in graph['Nodes'] if n['NodeType'] == 'BooleanInputNode']
        self.assertTrue(all(n['InputValue'] is False for n in bools))
        outputs = {p['Id'] for n in graph['Nodes'] for p in n['Outputs']}
        inputs = {p['Id'] for n in graph['Nodes'] for p in n['Inputs']}
        for connector in graph['Connectors']:
            self.assertIn(connector['Start'], outputs)
            self.assertIn(connector['End'], inputs)
        trigger = next(n for n in graph['Nodes']
                       if n.get('FunctionSignature') == 'DSCore.DateTime.Now')
        self.assertEqual(trigger['NodeType'], 'FunctionNode')
        trigger_output = trigger['Outputs'][0]['Id']
        self.assertTrue(any(c['Start'] == trigger_output and
                            c['End'] == node['Inputs'][3]['Id']
                            for c in graph['Connectors']))
        compile(SOURCE, 'python-node', 'exec')

    def test_clean_number(self):
        helper = next(n for n in ast.parse(SOURCE).body
                      if isinstance(n, ast.FunctionDef) and n.name == 'clean_number')
        env = {'re': __import__('re')}
        exec(compile(ast.Module(body=[helper], type_ignores=[]), 'helper', 'exec'), env)
        clean = env['clean_number']
        self.assertEqual(clean('12.5 lbm'), 12.5)
        self.assertEqual(clean('1,234.5 lbm'), 1234.5)
        self.assertEqual(clean('12,5 kg'), 12.5)
        self.assertIsNone(clean(''))
        self.assertIsNone(clean('not available'))

    def test_required_scope_and_names(self):
        for text in ['OST_FabricationPipework', "PHASE_NAME = 'New Construction'",
                     "ASSEMBLY = 'STRATUS Assembly'", "WEIGHT = 'Weight'",
                     "SCHEDULE_NAME = 'STRATUS Assembly Weight Report'",
                     "PACKAGE = 'STRATUS Package Name'", 'UnitTypeId.PoundsMass']:
            self.assertIn(text, SOURCE)
        self.assertNotIn('OST_FabricationHangers)', SOURCE)

    def test_coupling_identification(self):
        helper = next(n for n in ast.parse(SOURCE).body
                      if isinstance(n, ast.FunctionDef) and n.name == 'coupling_description')
        env = {'re': re, 'parameter_text': lambda element, name: None}
        exec(compile(ast.Module(body=[helper], type_ignores=[]), 'coupling-helper', 'exec'), env)
        class Part:
            ProductShortDescription = 'Victaulic Coupling'
            Alias = ''
            Name = 'Part'
        self.assertEqual(env['coupling_description'](Part()), 'Victaulic Coupling')
        Part.ProductShortDescription = '90 Degree Elbow'
        self.assertIsNone(env['coupling_description'](Part()))

    def test_package_xlsx_is_valid_and_filtered(self):
        wanted = {'excel_path', 'xml_text', 'xlsx_cell', 'export_excel'}
        helpers = [n for n in ast.parse(SOURCE).body
                   if isinstance(n, ast.FunctionDef) and n.name in wanted]
        env = {'datetime': datetime, 'os': os, 're': re, 'zipfile': zipfile}
        exec(compile(ast.Module(body=helpers, type_ignores=[]), 'xlsx-helpers', 'exec'), env)
        groups = OrderedDict([
            ('A', {'assembly_id': 'A&1', 'assembly_name': 'A&1', 'service': 'HWS',
                   'piece_count': 2, 'total_weight_lbm': 40.25, 'packages': {'PK1'},
                   'internal_connections': 1, 'boundary_connections': 1, 'open_ends': 0,
                   'connector_count': 3, 'connection_audit_errors': [],
                   'excluded_couplings': [{'element_id': 12, 'description': 'Pipe Coupling',
                                            'weight_lbm': 2.25}],
                   'coupling_adjustment_lbm': 2.25, 'actual_weight_lbm': 38.0,
                   'connection_details': [{'element_id': 10, 'connector_id': 1,
                       'classification': 'Internal connection', 'connected_element_id': 11,
                       'connected_assembly': 'A&1'}]}),
            ('B', {'assembly_id': 'B2', 'assembly_name': 'B2', 'service': 'HWR',
                   'piece_count': 1, 'total_weight_lbm': 10.0, 'packages': {'PK2'},
                   'internal_connections': 0, 'boundary_connections': 0, 'open_ends': 2,
                   'connector_count': 2, 'connection_audit_errors': [],
                   'excluded_couplings': [], 'coupling_adjustment_lbm': 0.0,
                   'actual_weight_lbm': 10.0,
                   'connection_details': []}),
        ])
        with tempfile.TemporaryDirectory() as folder:
            path, count = env['export_excel'](groups, 'PK1', folder)
            self.assertEqual(count, 1)
            self.assertTrue(path.endswith('.xlsx'))
            with zipfile.ZipFile(path) as book:
                required = {'[Content_Types].xml', '_rels/.rels', 'xl/workbook.xml',
                            'xl/_rels/workbook.xml.rels', 'xl/worksheets/sheet1.xml',
                            'xl/styles.xml'}
                self.assertTrue(required.issubset(book.namelist()))
                for name in required:
                    ElementTree.fromstring(book.read(name))
                sheet = book.read('xl/worksheets/sheet1.xml').decode('utf-8')
                self.assertIn('conditionalFormatting sqref="F10:F10"', sheet)
                self.assertIn('state="frozen"', sheet)
                self.assertIn('A&amp;1', sheet)
                self.assertNotIn('B2', sheet)
                self.assertIn('STRATUS Package Name', sheet)
                self.assertNotIn('Assembly ID', sheet)
                self.assertNotIn('Audit Errors', sheet)
                self.assertNotIn('Coupling Adjustment', sheet)


if __name__ == '__main__':
    unittest.main()
