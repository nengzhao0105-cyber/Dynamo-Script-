"""Rebuild the Dynamo graph after editing the Python source."""
import json
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL

ROOT = Path(__file__).resolve().parent


def uid(label):
    return uuid5(NAMESPACE_URL, 'stratus-assembly-weight-report/' + label).hex


def port(label, name):
    return {'Id': uid(label), 'Name': name, 'Description': name,
            'UsingDefaultValue': False, 'Level': 2, 'UseLevels': False,
            'KeepListStructure': False}


nodes = [
    {'ConcreteType': 'CoreNodeModels.Input.BoolSelector, CoreNodeModels',
     'NodeType': 'BooleanInputNode', 'InputValue': False, 'Id': uid('apply'),
     'Inputs': [], 'Outputs': [port('apply-out', '')], 'Replication': 'Disabled',
     'Description': 'False previews; True writes parameters and replaces the report schedule.'},
    {'ConcreteType': 'CoreNodeModels.Input.BoolSelector, CoreNodeModels',
     'NodeType': 'BooleanInputNode', 'InputValue': False, 'Id': uid('export'),
     'Inputs': [], 'Outputs': [port('export-out', '')], 'Replication': 'Disabled',
     'Description': 'Show the package picker and create a formatted Excel report after Apply.'},
    {'ConcreteType': 'CoreNodeModels.Input.StringInput, CoreNodeModels',
     'NodeType': 'StringInputNode', 'InputValue': '', 'Id': uid('folder'),
     'Inputs': [], 'Outputs': [port('folder-out', '')], 'Replication': 'Disabled',
     'Description': 'Excel destination folder. Blank uses the current Windows Downloads folder.'},
    {'ConcreteType': 'Dynamo.Graph.Nodes.ZeroTouch.DSFunction, DynamoCore',
     'NodeType': 'FunctionNode', 'FunctionSignature': 'DSCore.DateTime.Now',
     'Id': uid('run-trigger'), 'Inputs': [],
     'Outputs': [port('run-trigger-out', 'dateTime')], 'Replication': 'Auto',
     'Description': 'Changes on every Manual Run so the package picker can be opened repeatedly.'},
    {'ConcreteType': 'PythonNodeModels.PythonNode, PythonNodeModels',
     'NodeType': 'PythonScriptNode',
     'Code': (ROOT / 'stratus_assembly_weight_report.py').read_text(),
     'Engine': 'CPython3', 'VariableInputPorts': True, 'Id': uid('python'),
     'Inputs': [port('python-in-0', 'IN[0]'), port('python-in-1', 'IN[1]'),
                port('python-in-2', 'IN[2]'), port('python-in-3', 'IN[3]')],
     'Outputs': [port('python-out', 'OUT')], 'Replication': 'Disabled',
     'Description': 'Project-wide STRATUS assembly weight reporting.'},
    {'ConcreteType': 'CoreNodeModels.Watch, CoreNodeModels',
     'NodeType': 'ExtensionNode', 'Id': uid('watch'),
     'Inputs': [port('watch-in', '')], 'Outputs': [port('watch-out', '')],
     'Replication': 'Disabled', 'Description': 'Preview, results, skipped counts and errors.'}
]

connectors = [
    ('apply-out', 'python-in-0', 'c1'), ('export-out', 'python-in-1', 'c2'),
    ('folder-out', 'python-in-2', 'c3'), ('run-trigger-out', 'python-in-3', 'c4'),
    ('python-out', 'watch-in', 'c5')]

graph = {'Uuid': uid('graph'), 'IsCustomNode': False,
         'Description': 'Revit 2025 project-wide STRATUS weights, schedule and package Excel heat map.',
         'Name': 'STRATUS Assembly Weight Report',
         'ElementResolver': {'ResolutionMap': {
             'DSCore.DateTime.Now': {'Key': 'DSCore.DateTime', 'Value': 'DSCoreNodes.dll'},
             'DSCore.DateTime': {'Key': 'DSCore.DateTime', 'Value': 'DSCoreNodes.dll'}}},
         'Inputs': [], 'Outputs': [], 'Nodes': nodes,
         'Connectors': [{'Start': uid(a), 'End': uid(b), 'Id': uid(c), 'IsHidden': 'False'}
                        for a, b, c in connectors],
         'Dependencies': [], 'NodeLibraryDependencies': [], 'Bindings': [],
         'View': {'Dynamo': {'ScaleFactor': 1.0, 'HasRunWithoutCrash': False,
                             'IsVisibleInDynamoLibrary': True, 'Version': '3.0.3.7597',
                             'RunType': 'Manual', 'RunPeriod': '1000'},
                  'NodeViews': [
                      {'Id': uid('apply'), 'Name': 'Apply changes (False = preview)', 'IsSetAsInput': True,
                       'IsSetAsOutput': False, 'Excluded': False, 'ShowGeometry': False, 'X': 0.0, 'Y': 50.0},
                      {'Id': uid('export'), 'Name': 'Create package Excel report', 'IsSetAsInput': True,
                       'IsSetAsOutput': False, 'Excluded': False, 'ShowGeometry': False, 'X': 0.0, 'Y': 170.0},
                      {'Id': uid('folder'), 'Name': 'Excel folder (blank = Downloads)', 'IsSetAsInput': True,
                       'IsSetAsOutput': False, 'Excluded': False, 'ShowGeometry': False, 'X': 0.0, 'Y': 290.0},
                      {'Id': uid('run-trigger'), 'Name': 'Run trigger (automatic)', 'IsSetAsInput': False,
                       'IsSetAsOutput': False, 'Excluded': False, 'ShowGeometry': False, 'X': 200.0, 'Y': 410.0},
                      {'Id': uid('python'), 'Name': 'STRATUS Assembly Weight Reporting', 'IsSetAsInput': False,
                       'IsSetAsOutput': False, 'Excluded': False, 'ShowGeometry': False, 'X': 410.0, 'Y': 150.0},
                      {'Id': uid('watch'), 'Name': 'Results / diagnostics', 'IsSetAsInput': False,
                       'IsSetAsOutput': True, 'Excluded': False, 'ShowGeometry': False, 'X': 800.0, 'Y': 150.0}],
                  'Annotations': [], 'X': 40.0, 'Y': 80.0, 'Zoom': 0.85}}

(ROOT / 'STRATUS Assembly Weight Report.dyn').write_text(json.dumps(graph, indent=2))
