"""Rebuild the Dynamo graph after editing the Python source."""
import json
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL
ROOT = Path(__file__).resolve().parent

def uid(label):
    return uuid5(NAMESPACE_URL, 'stratus-assembly-colors/' + label).hex

def port(label, name):
    return {'Id': uid(label), 'Name': name, 'Description': name,
            'UsingDefaultValue': False, 'Level': 2, 'UseLevels': False,
            'KeepListStructure': False}

nodes = [
    {'ConcreteType': 'CoreNodeModels.Input.BoolSelector, CoreNodeModels',
     'NodeType': 'BooleanInputNode', 'InputValue': False, 'Id': uid('apply'),
     'Inputs': [], 'Outputs': [port('bool-out', '')], 'Replication': 'Disabled',
     'Description': 'False previews; True applies colors to the active view.'},
    {'ConcreteType': 'PythonNodeModels.PythonNode, PythonNodeModels',
     'NodeType': 'PythonScriptNode', 'Code': (ROOT / 'stratus_assembly_colors.py').read_text(),
     'Engine': 'CPython3', 'VariableInputPorts': True, 'Id': uid('python'),
     'Inputs': [port('python-in', 'IN[0]')], 'Outputs': [port('python-out', 'OUT')],
     'Replication': 'Disabled', 'Description': 'Create STRATUS Assembly color filters.'},
    {'ConcreteType': 'CoreNodeModels.Watch, CoreNodeModels',
     'NodeType': 'ExtensionNode', 'Id': uid('watch'),
     'Inputs': [port('watch-in', '')], 'Outputs': [port('watch-out', '')],
     'Replication': 'Disabled', 'Description': 'Preview, results and diagnostics.'}
]
graph = {'Uuid': uid('graph'), 'IsCustomNode': False,
         'Description': 'Revit 2025: preview or apply one color filter per STRATUS Assembly in the active view.',
         'Name': 'STRATUS Assembly Colors', 'ElementResolver': {'ResolutionMap': {}},
         'Inputs': [], 'Outputs': [], 'Nodes': nodes,
         'Connectors': [
             {'Start': uid('bool-out'), 'End': uid('python-in'), 'Id': uid('c1'), 'IsHidden': 'False'},
             {'Start': uid('python-out'), 'End': uid('watch-in'), 'Id': uid('c2'), 'IsHidden': 'False'}],
         'Dependencies': [], 'NodeLibraryDependencies': [], 'Bindings': [],
         'View': {'Dynamo': {'ScaleFactor': 1.0, 'HasRunWithoutCrash': False,
                             'IsVisibleInDynamoLibrary': True, 'Version': '3.0.3.7597',
                             'RunType': 'Manual', 'RunPeriod': '1000'},
                  'NodeViews': [
                      {'Id': uid(label), 'Name': name, 'IsSetAsInput': label == 'apply',
                       'IsSetAsOutput': label == 'watch', 'Excluded': False,
                       'ShowGeometry': False, 'X': x, 'Y': 150.0}
                      for label, name, x in [('apply', 'Apply colors (False = preview)', 0.0),
                                              ('python', 'STRATUS Assembly Colors', 340.0),
                                              ('watch', 'Results / assembly colors', 700.0)]],
                  'Annotations': [], 'X': 40.0, 'Y': 80.0, 'Zoom': 0.85}}
(ROOT / 'STRATUS Assembly Colors.dyn').write_text(json.dumps(graph, indent=2))
