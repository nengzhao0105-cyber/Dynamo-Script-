"""Rebuild the Dynamo graph after editing the Python source."""
import json
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL

ROOT = Path(__file__).resolve().parent


def uid(label):
    return uuid5(NAMESPACE_URL, 'stratus-package-bill-of-material/' + label).hex


def port(label, name):
    return {'Id': uid(label), 'Name': name, 'Description': name,
            'UsingDefaultValue': False, 'Level': 2, 'UseLevels': False,
            'KeepListStructure': False}


nodes = [
    {'ConcreteType': 'CoreNodeModels.Input.BoolSelector, CoreNodeModels',
     'NodeType': 'BooleanInputNode', 'InputValue': False, 'Id': uid('apply'),
     'Inputs': [], 'Outputs': [port('apply-out', '')], 'Replication': 'Disabled',
     'Description': 'False previews. True opens the package picker, refreshes Revit and exports Excel.'},
    {'ConcreteType': 'CoreNodeModels.Input.StringInput, CoreNodeModels',
     'NodeType': 'StringInputNode', 'InputValue': '', 'Id': uid('folder'),
     'Inputs': [], 'Outputs': [port('folder-out', '')], 'Replication': 'Disabled',
     'Description': 'Excel destination folder. Blank uses Downloads.'},
    {'ConcreteType': 'PythonNodeModels.PythonNode, PythonNodeModels',
     'NodeType': 'PythonScriptNode',
     'Code': (ROOT / 'stratus_package_bill_of_material.py').read_text(),
     'Engine': 'CPython3', 'VariableInputPorts': True, 'Id': uid('python'),
     'Inputs': [port('python-in-0', 'IN[0]'), port('python-in-1', 'IN[1]')],
     'Outputs': [port('python-out', 'OUT')], 'Replication': 'Disabled',
     'Description': 'Package Bill of Material for Fabrication Pipework.'},
    {'ConcreteType': 'CoreNodeModels.Watch, CoreNodeModels',
     'NodeType': 'ExtensionNode', 'Id': uid('watch'),
     'Inputs': [port('watch-in', '')], 'Outputs': [port('watch-out', '')],
     'Replication': 'Disabled', 'Description': 'Preview, output path, skipped counts and errors.'}
]

connectors = [('apply-out', 'python-in-0', 'c1'),
              ('folder-out', 'python-in-1', 'c2'),
              ('python-out', 'watch-in', 'c3')]

graph = {'Uuid': uid('graph'), 'IsCustomNode': False,
         'Description': 'Revit 2025 package BOM schedule with separate fitting and pipe Excel tabs.',
         'Name': 'Stratus Package Bill of Material', 'ElementResolver': {'ResolutionMap': {}},
         'Inputs': [], 'Outputs': [], 'Nodes': nodes,
         'Connectors': [{'Start': uid(a), 'End': uid(b), 'Id': uid(c), 'IsHidden': 'False'}
                        for a, b, c in connectors],
         'Dependencies': [], 'NodeLibraryDependencies': [], 'Bindings': [],
         'View': {'Dynamo': {'ScaleFactor': 1.0, 'HasRunWithoutCrash': False,
                             'IsVisibleInDynamoLibrary': True, 'Version': '3.0.3.7597',
                             'RunType': 'Manual', 'RunPeriod': '1000'},
                  'NodeViews': [
                      {'Id': uid('apply'), 'Name': 'Apply and create BOM (False = preview)',
                       'IsSetAsInput': True, 'IsSetAsOutput': False, 'Excluded': False,
                       'ShowGeometry': False, 'X': 0.0, 'Y': 80.0},
                      {'Id': uid('folder'), 'Name': 'Excel folder (blank = Downloads)',
                       'IsSetAsInput': True, 'IsSetAsOutput': False, 'Excluded': False,
                       'ShowGeometry': False, 'X': 0.0, 'Y': 220.0},
                      {'Id': uid('python'), 'Name': 'Stratus Package Bill of Material',
                       'IsSetAsInput': False, 'IsSetAsOutput': False, 'Excluded': False,
                       'ShowGeometry': False, 'X': 410.0, 'Y': 150.0},
                      {'Id': uid('watch'), 'Name': 'Results / diagnostics',
                       'IsSetAsInput': False, 'IsSetAsOutput': True, 'Excluded': False,
                       'ShowGeometry': False, 'X': 820.0, 'Y': 150.0}],
                  'Annotations': [], 'X': 40.0, 'Y': 80.0, 'Zoom': 0.85}}

(ROOT / 'Stratus Package Bill of Material.dyn').write_text(json.dumps(graph, indent=2))
