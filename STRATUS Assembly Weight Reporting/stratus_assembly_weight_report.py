"""Dynamo CPython3 / Revit 2025.

IN[0]: Apply changes (False = preview)
IN[1]: Create package Excel report (only exports when Apply is True)
IN[2]: Excel folder (blank = Downloads)
IN[3]: Volatile DateTime trigger supplied by the graph; do not edit
"""
import clr
import datetime
import os
import re
import tempfile
import zipfile
from collections import OrderedDict
from System import Guid

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
from Autodesk.Revit.DB import (
    BuiltInCategory, BuiltInParameter, Category, CategorySet, ElementId,
    ExternalDefinitionCreationOptions, FilteredElementCollector, ForgeTypeId,
    InstanceBinding, ScheduleFieldType, ScheduleFilter, ScheduleFilterType,
    ScheduleSortGroupField, SpecTypeId, StorageType, SubTransaction,
    TransactionStatus, UnitTypeId, UnitUtils, ViewSchedule, FabricationPart
)
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

ASSEMBLY = 'STRATUS Assembly'
PACKAGE = 'STRATUS Package Name'
ASSEMBLY_NAME = 'STRATUS Assembly Name'
PIECE_COUNT = 'STRATUS Assembly Piece Count'
TOTAL_WEIGHT = 'STRATUS Assembly Total Weight'
WEIGHT = 'Weight'
SCHEDULE_NAME = 'STRATUS Assembly Weight Report'
PHASE_NAME = 'New Construction'

# Stable GUIDs make reruns and deployment to multiple models predictable.
PARAMETERS = OrderedDict([
    (ASSEMBLY_NAME, (Guid('11aa11aa-2bb2-4cc4-8dd8-111111111111'), SpecTypeId.String.Text)),
    (PIECE_COUNT, (Guid('22bb22bb-3cc3-4dd4-8ee8-222222222222'), SpecTypeId.Int.Integer)),
    (TOTAL_WEIGHT, (Guid('33cc33cc-4dd4-4ee4-8ff8-333333333333'), SpecTypeId.Mass)),
])


def eid_value(eid):
    """Revit 2025 uses Value; this fallback also permits source-level testing."""
    return eid.Value if hasattr(eid, 'Value') else eid.IntegerValue


def clean_number(text):
    if not text:
        return None
    match = re.search(r'[-+]?\d[\d,.]*', text.replace(' ', ''))
    if not match:
        return None
    token = match.group(0)
    if token.count(',') and token.count('.'):
        token = token.replace(',', '')
    else:
        token = token.replace(',', '.')
    try:
        return float(token)
    except ValueError:
        return None


def parameter_text(element, name):
    p = element.LookupParameter(name)
    if p is None:
        return None
    if p.StorageType == StorageType.String:
        return p.AsString()
    return p.AsValueString()


def weight_lbm(element):
    """Return (pounds mass, error). Prefer typed Revit unit conversion."""
    p = element.LookupParameter(WEIGHT)
    if p is None:
        return None, 'missing Weight'
    if p.StorageType == StorageType.Double:
        raw = p.AsDouble()
        try:
            return UnitUtils.ConvertFromInternalUnits(raw, UnitTypeId.PoundsMass), None
        except Exception:
            parsed = clean_number(p.AsValueString())
            return (parsed, None) if parsed is not None else (None, 'unreadable Weight')
    parsed = clean_number(p.AsString() if p.StorageType == StorageType.String else p.AsValueString())
    return (parsed, None) if parsed is not None else (None, 'unreadable Weight')


def coupling_description(element):
    """Return the matching description when a separate part is a coupling."""
    values = []
    for attribute in ('ProductShortDescription', 'Alias', 'Name'):
        try:
            value = getattr(element, attribute)
            if value:
                values.append(str(value))
        except Exception:
            pass
    for parameter_name in ('Item Name', 'Product Name', 'Description', 'STRATUS Item Name'):
        value = parameter_text(element, parameter_name)
        if value:
            values.append(value)
    for value in values:
        if re.search(r'coupl', value, re.IGNORECASE):
            return value
    return None


def get_existing_phase(doc):
    matches = [p for p in doc.Phases if p.Name == PHASE_NAME]
    if len(matches) != 1:
        raise ValueError('Expected exactly one phase named "{}"; found {}.'.format(PHASE_NAME, len(matches)))
    return matches[0]


def collect(doc):
    phase = get_existing_phase(doc)
    groups = OrderedDict()
    skipped = {'blank_assembly': 0, 'wrong_phase': 0, 'missing_weight': 0,
               'unreadable_weight': 0}
    packages = set()
    parts = (FilteredElementCollector(doc)
             .OfCategory(BuiltInCategory.OST_FabricationPipework)
             .WhereElementIsNotElementType())
    for part in parts:
        # Fabrication hangers have their own category; retaining this test protects
        # against unusual fabrication content/category mappings.
        if not isinstance(part, FabricationPart):
            continue
        if eid_value(part.CreatedPhaseId) != eid_value(phase.Id):
            skipped['wrong_phase'] += 1
            continue
        if part.DemolishedPhaseId != ElementId.InvalidElementId and eid_value(part.DemolishedPhaseId) == eid_value(phase.Id):
            skipped['wrong_phase'] += 1
            continue
        assembly = parameter_text(part, ASSEMBLY)
        if assembly is None or not assembly.strip():
            skipped['blank_assembly'] += 1
            continue
        pounds, error = weight_lbm(part)
        if error:
            skipped['missing_weight' if error == 'missing Weight' else 'unreadable_weight'] += 1
            continue
        service = ''
        try:
            service = part.ServiceAbbreviation or ''
        except Exception:
            service = parameter_text(part, 'Service Abbreviation') or ''
        package = parameter_text(part, PACKAGE)
        if package is not None and package.strip():
            packages.add(package)
        # Exact text is intentionally the dictionary key: case and whitespace differ.
        group = groups.setdefault(assembly, {'assembly_id': assembly,
            'assembly_name': assembly, 'services': set(), 'elements': [],
            'packages': set(),
            'piece_count': 0, 'total_weight_lbm': 0.0})
        if service:
            group['services'].add(service)
        group['elements'].append(part)
        if package is not None and package.strip():
            group['packages'].add(package)
        group['piece_count'] += 1
        group['total_weight_lbm'] += pounds
    for group in groups.values():
        group['service'] = ', '.join(sorted(group.pop('services')))
        group['excluded_couplings'] = []
        group['coupling_adjustment_lbm'] = 0.0
        for element in group['elements']:
            description = coupling_description(element)
            if description is None:
                continue
            pounds, error = weight_lbm(element)
            if error or pounds is None:
                continue
            group['excluded_couplings'].append({
                'element_id': eid_value(element.Id), 'description': description,
                'weight_lbm': pounds})
            group['coupling_adjustment_lbm'] += pounds
        group['actual_weight_lbm'] = max(
            0.0, group['total_weight_lbm'] - group['coupling_adjustment_lbm'])
    return groups, skipped, phase, sorted(packages)


def ensure_parameters(doc, app):
    """Create stable shared instance parameters bound to fabrication pipework."""
    old_path = app.SharedParametersFilename
    fd, path = tempfile.mkstemp(prefix='stratus_weight_', suffix='.txt')
    os.close(fd)
    try:
        with open(path, 'w') as shared:
            shared.write('# This is a Revit shared parameter file.\n')
            shared.write('# Do not edit manually.\n')
            shared.write('*META\tVERSION\tMINVERSION\nMETA\t2\t1\n')
            shared.write('*GROUP\tID\tNAME\n')
            shared.write('*PARAM\tGUID\tNAME\tDATATYPE\tDATACATEGORY\tGROUP\tVISIBLE\tDESCRIPTION\tUSERMODIFIABLE\tHIDEWHENNOVALUE\n')
        app.SharedParametersFilename = path
        definition_file = app.OpenSharedParameterFile()
        definition_group = definition_file.Groups.Create('Dynamo STRATUS')
        category = Category.GetCategory(doc, BuiltInCategory.OST_FabricationPipework)
        categories = app.Create.NewCategorySet()
        categories.Insert(category)
        binding = app.Create.NewInstanceBinding(categories)
        existing_names = set()
        iterator = doc.ParameterBindings.ForwardIterator()
        iterator.Reset()
        while iterator.MoveNext():
            existing_names.add(iterator.Key.Name)
        for name, (guid, data_type) in PARAMETERS.items():
            if name in existing_names:
                continue
            options = ExternalDefinitionCreationOptions(name, data_type)
            options.GUID = guid
            definition = definition_group.Definitions.Create(options)
            if not doc.ParameterBindings.Insert(definition, binding):
                raise RuntimeError('Could not create project parameter: ' + name)
    finally:
        app.SharedParametersFilename = old_path
        try:
            os.remove(path)
        except Exception:
            pass


def set_value(element, name, value):
    p = element.LookupParameter(name)
    if p is None or p.IsReadOnly:
        raise ValueError('Parameter "{}" is missing or read-only on element {}.'.format(name, eid_value(element.Id)))
    p.Set(value)


def schedulable_by_name(definition, doc):
    result = {}
    for field in definition.GetSchedulableFields():
        try:
            result.setdefault(field.GetName(doc), []).append(field)
        except Exception:
            pass
    return result


def replace_schedule(doc, phase):
    existing = next((v for v in FilteredElementCollector(doc).OfClass(ViewSchedule)
                     if not v.IsTemplate and v.Name == SCHEDULE_NAME), None)
    if existing is not None:
        doc.Delete(existing.Id)
    schedule = ViewSchedule.CreateSchedule(doc, ElementId(BuiltInCategory.OST_FabricationPipework))
    schedule.Name = SCHEDULE_NAME
    definition = schedule.Definition
    available = schedulable_by_name(definition, doc)

    def add(name, heading=None):
        choices = available.get(name, [])
        if not choices:
            raise ValueError('Schedule field is unavailable: ' + name)
        field = definition.AddField(choices[0])
        if heading:
            field.ColumnHeading = heading
        return field

    assembly = add(ASSEMBLY, 'Assembly ID')
    add(ASSEMBLY_NAME, 'Assembly Name')
    service_choices = available.get('Service Abbreviation', [])
    if service_choices:
        add('Service Abbreviation', 'Service')
    count_choices = [x for x in definition.GetSchedulableFields()
                     if x.FieldType == ScheduleFieldType.Count]
    if not count_choices:
        raise ValueError('The Fabrication Pipework schedule does not expose a Count field.')
    count = definition.AddField(count_choices[0])
    count.ColumnHeading = 'Piece Count'
    add(TOTAL_WEIGHT, 'Total Weight')
    phase_field = None
    phase_parameter = ElementId(BuiltInParameter.PHASE_CREATED)
    for schedulable in definition.GetSchedulableFields():
        if schedulable.ParameterId == phase_parameter:
            phase_field = definition.AddField(schedulable)
            phase_field.IsHidden = True
            break
    if phase_field is None:
        raise ValueError('The schedule does not expose the Phase Created field.')
    definition.IsItemized = False
    definition.AddSortGroupField(ScheduleSortGroupField(assembly.FieldId))
    definition.AddFilter(ScheduleFilter(phase_field.FieldId, ScheduleFilterType.Equal, phase.Id))
    definition.AddFilter(ScheduleFilter(assembly.FieldId, ScheduleFilterType.HasValue))
    return schedule


def select_package(packages):
    """Modal searchable package picker hosted by Revit's UI thread."""
    clr.AddReference('System.Windows.Forms')
    clr.AddReference('System.Drawing')
    from System.Drawing import Point, Size
    from System.Windows.Forms import (AutoCompleteMode, AutoCompleteSource, Button,
        ComboBox, ComboBoxStyle, DialogResult, Form, FormBorderStyle, Label,
        FormStartPosition)

    form = Form()
    form.Text = 'STRATUS Assembly Weight Report'
    form.ClientSize = Size(500, 155)
    form.FormBorderStyle = FormBorderStyle.FixedDialog
    form.MaximizeBox = False
    form.MinimizeBox = False
    form.ShowInTaskbar = False
    form.TopMost = True
    form.StartPosition = FormStartPosition.CenterScreen

    label = Label()
    label.Text = 'Select the STRATUS package name for the Excel report:'
    label.AutoSize = True
    label.Location = Point(20, 20)
    form.Controls.Add(label)

    combo = ComboBox()
    combo.Location = Point(20, 50)
    combo.Size = Size(460, 28)
    combo.DropDownStyle = ComboBoxStyle.DropDown
    combo.AutoCompleteMode = AutoCompleteMode.SuggestAppend
    combo.AutoCompleteSource = AutoCompleteSource.ListItems
    for value in packages:
        combo.Items.Add(value)
    if packages:
        combo.SelectedIndex = 0
    form.Controls.Add(combo)

    ok = Button()
    ok.Text = 'Create report'
    ok.Location = Point(276, 103)
    ok.Size = Size(110, 30)
    ok.DialogResult = DialogResult.OK
    form.AcceptButton = ok
    form.Controls.Add(ok)

    cancel = Button()
    cancel.Text = 'Cancel'
    cancel.Location = Point(395, 103)
    cancel.Size = Size(85, 30)
    cancel.DialogResult = DialogResult.Cancel
    form.CancelButton = cancel
    form.Controls.Add(cancel)

    accepted = form.ShowDialog() == DialogResult.OK
    selected = combo.Text
    form.Dispose()
    if not accepted:
        return None
    if selected not in packages:
        raise ValueError('Select a package from the available STRATUS Package Name values.')
    return selected


def excel_path(folder, package):
    base = folder.strip() if folder and folder.strip() else os.path.expanduser('~/Downloads')
    if not os.path.isdir(base):
        raise ValueError('Excel folder does not exist: ' + base)
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', package).strip(' .') or 'Package'
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H%M%S')
    candidate = os.path.join(base, 'STRATUS Weight Report - {} - {}.xlsx'.format(safe, timestamp))
    if not os.path.exists(candidate):
        return candidate
    number = 2
    while True:
        alternate = os.path.join(base, 'STRATUS Weight Report - {} - {} - {}.xlsx'.format(
            safe, timestamp, number))
        if not os.path.exists(alternate):
            return alternate
        number += 1


def xml_text(value):
    value = str(value)
    return (value.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;').replace("'", '&apos;'))


def xlsx_cell(reference, value, style=0, numeric=False):
    if numeric:
        return '<c r="{}" s="{}"><v>{}</v></c>'.format(reference, style, value)
    return '<c r="{}" s="{}" t="inlineStr"><is><t xml:space="preserve">{}</t></is></c>'.format(
        reference, style, xml_text(value))


def export_excel(groups, package, folder):
    """Create a two-sheet XLSX with weight summary and connector audit."""
    selected = [g for g in groups.values() if package in g['packages']]
    selected.sort(key=lambda g: (-g['actual_weight_lbm'], g['assembly_id']))
    if not selected:
        raise ValueError('No eligible assemblies were found for package: ' + package)
    path = excel_path(folder, package)
    generated = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    total_pieces = sum(g['piece_count'] for g in selected)
    total_weight = sum(g['total_weight_lbm'] for g in selected)
    total_actual_weight = sum(g['actual_weight_lbm'] for g in selected)
    rows = [
        '<row r="2" ht="24" customHeight="1">{}</row>'.format(
            xlsx_cell('A2', 'STRATUS Assembly Weight Report', 1)),
        '<row r="3">{}{}</row>'.format(xlsx_cell('A3', 'Generated', 2), xlsx_cell('B3', generated, 3)),
        '<row r="4">{}{}</row>'.format(xlsx_cell('A4', 'Package', 2), xlsx_cell('B4', package, 3)),
        '<row r="5">{}{}{}{}</row>'.format(
            xlsx_cell('A5', 'Assembly Count', 2), xlsx_cell('B5', len(selected), 3, True),
            xlsx_cell('D5', 'Total Piece Count', 2), xlsx_cell('E5', total_pieces, 3, True)),
        '<row r="6">{}{}</row>'.format(
            xlsx_cell('A6', 'Combined Gross Weight (lbm)', 2),
            xlsx_cell('B6', round(total_weight, 3), 6, True)),
        '<row r="7">{}{}</row>'.format(
            xlsx_cell('A7', 'Combined Actual Weight (lbm)', 2),
            xlsx_cell('B7', round(total_actual_weight, 3), 6, True)),
        '<row r="9" ht="30" customHeight="1">{}</row>'.format(''.join([
            xlsx_cell('A9', 'STRATUS Package Name', 4), xlsx_cell('B9', 'Assembly Name', 4),
            xlsx_cell('C9', 'Service', 4), xlsx_cell('D9', 'Piece Count', 4),
            xlsx_cell('E9', 'Gross Weight (lbm)', 4),
            xlsx_cell('F9', 'Actual Weight (lbm)', 4)]))]
    for index, group in enumerate(selected, 10):
        rows.append('<row r="{}">{}</row>'.format(index, ''.join([
            xlsx_cell('A{}'.format(index), package, 5),
            xlsx_cell('B{}'.format(index), group['assembly_name'], 5),
            xlsx_cell('C{}'.format(index), group['service'], 5),
            xlsx_cell('D{}'.format(index), group['piece_count'], 7, True),
            xlsx_cell('E{}'.format(index), round(group['total_weight_lbm'], 3), 6, True),
            xlsx_cell('F{}'.format(index), round(group['actual_weight_lbm'], 3), 6, True)])))
    last = 9 + len(selected)
    sheet = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<sheetViews><sheetView showGridLines="0" workbookViewId="0"><pane ySplit="9" topLeftCell="A10" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
<cols><col min="1" max="2" width="27" customWidth="1"/><col min="3" max="3" width="16" customWidth="1"/><col min="4" max="4" width="14" customWidth="1"/><col min="5" max="6" width="22" customWidth="1"/></cols>
<sheetData>{rows}</sheetData>
<autoFilter ref="A9:F{last}"/>
<conditionalFormatting sqref="F10:F{last}"><cfRule type="colorScale" priority="1"><colorScale><cfvo type="min"/><cfvo type="percentile" val="50"/><cfvo type="max"/><color rgb="FFFFF2CC"/><color rgb="FFF4B183"/><color rgb="FF9C0006"/></colorScale></cfRule></conditionalFormatting>
<pageMargins left="0.4" right="0.4" top="0.6" bottom="0.6" header="0.2" footer="0.2"/>
</worksheet>'''.format(rows=''.join(rows), last=last)
    styles = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="4"><font><sz val="10"/><name val="Arial"/></font><font><b/><sz val="14"/><color rgb="FF1F1F1F"/><name val="Arial"/></font><font><b/><sz val="10"/><color rgb="FF404040"/><name val="Arial"/></font><font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Arial"/></font></fonts>
<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF1F4E78"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border><border><left/><right/><top/><bottom style="thin"><color rgb="FFD9E2F3"/></bottom><diagonal/></border></borders>
<numFmts count="1"><numFmt numFmtId="164" formatCode="#,##0.000"/></numFmts>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="9"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1"/><xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="3" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf><xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1"/><xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"/><xf numFmtId="3" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"/><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyFont="1"><alignment wrapText="0"/></xf></cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>'''
    content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/><Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/><Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/></Types>'''
    root_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/></Relationships>'''
    workbook = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Package Weight Report" sheetId="1" r:id="rId1"/></sheets><calcPr calcId="191029" fullCalcOnLoad="1"/></workbook>'''
    workbook_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'''
    core = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>STRATUS Assembly Weight Report</dc:title><dc:creator>Dynamo</dc:creator><dcterms:created xsi:type="dcterms:W3CDTF">{}</dcterms:created></cp:coreProperties>'''.format(datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
    app_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><Application>Microsoft Excel</Application></Properties>'''
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in [('[Content_Types].xml', content_types), ('_rels/.rels', root_rels),
                           ('xl/workbook.xml', workbook), ('xl/_rels/workbook.xml.rels', workbook_rels),
                           ('xl/worksheets/sheet1.xml', sheet), ('xl/styles.xml', styles),
                           ('docProps/core.xml', core), ('docProps/app.xml', app_xml)]:
            archive.writestr(name, data.encode('utf-8'))
    return path, len(selected)


def summary(groups):
    return [{'Assembly ID': g['assembly_id'], 'Assembly Name': g['assembly_name'],
             'Service': g['service'], 'Piece Count': g['piece_count'],
             'Gross Weight (lbm)': round(g['total_weight_lbm'], 3),
             'Excluded Coupling Count': len(g['excluded_couplings']),
             'Coupling Adjustment (lbm)': round(g['coupling_adjustment_lbm'], 3),
             'Actual Weight (lbm)': round(g['actual_weight_lbm'], 3)}
            for g in groups.values()]


def main(apply_changes, do_export, folder):
    uiapp = DocumentManager.Instance.CurrentUIApplication
    app = uiapp.Application
    doc = DocumentManager.Instance.CurrentDBDocument
    if doc.IsFamilyDocument:
        raise ValueError('Open a Revit project model, not a family document.')
    groups, skipped, phase, packages = collect(doc)
    selected_package = None
    export_cancelled = False
    if do_export:
        if not packages:
            raise ValueError('No nonblank STRATUS Package Name values were found on eligible parts.')
        selected_package = select_package(packages)
        export_cancelled = selected_package is None
    result = {'status': 'Preview only; set Apply changes to True.',
              'phase': phase.Name, 'schedule': SCHEDULE_NAME,
              'assemblies': summary(groups), 'skipped': skipped,
              'notes': ['Assembly IDs are matched exactly, including case and whitespace.',
                        'Assembly Name currently copies STRATUS Assembly.',
                        'Only Fabrication Pipework created in New Construction is included; hangers are excluded.',
                        'Separately modeled parts whose description contains "coupl" are deducted from Gross Weight to calculate Actual Weight.']}
    if selected_package:
        result['selected_package'] = selected_package
        result['package_assemblies'] = summary(OrderedDict(
            (key, value) for key, value in groups.items() if selected_package in value['packages']))
    elif export_cancelled:
        result['excel'] = 'Cancelled; Revit processing will continue if Apply changes is True.'
    if not groups:
        result['status'] = 'No eligible Fabrication Pipework found.'
        return result
    if not apply_changes:
        return result

    manager = TransactionManager.Instance
    manager.EnsureInTransaction(doc)
    sub = SubTransaction(doc)
    sub.Start()
    try:
        ensure_parameters(doc, app)
        doc.Regenerate()
        for group in groups.values():
            total_internal = UnitUtils.ConvertToInternalUnits(group['actual_weight_lbm'], UnitTypeId.PoundsMass)
            for element in group['elements']:
                set_value(element, ASSEMBLY_NAME, group['assembly_name'])
                set_value(element, PIECE_COUNT, group['piece_count'])
                set_value(element, TOTAL_WEIGHT, total_internal)
        schedule = replace_schedule(doc, phase)
        result['schedule_id'] = eid_value(schedule.Id)
        if sub.Commit() != TransactionStatus.Committed:
            raise RuntimeError('Revit did not commit the STRATUS report changes.')
    except Exception:
        if sub.GetStatus() == TransactionStatus.Started:
            sub.RollBack()
        raise
    finally:
        manager.TransactionTaskDone()

    result['status'] = 'Updated {} assemblies and created schedule "{}".'.format(len(groups), SCHEDULE_NAME)
    if selected_package:
        try:
            path, row_count = export_excel(groups, selected_package, folder)
            result['excel'] = path
            result['excel_assembly_count'] = row_count
        except Exception as excel_error:
            result['excel_error'] = str(excel_error)
            result['status'] += ' Revit succeeded, but Excel creation failed.'
    return result


try:
    _apply = bool(IN[0]) if IN and len(IN) > 0 and IN[0] is not None else False
    _export = bool(IN[1]) if IN and len(IN) > 1 and IN[1] is not None else False
    _folder = str(IN[2]) if IN and len(IN) > 2 and IN[2] is not None else ''
    _run_trigger = IN[3] if IN and len(IN) > 3 else None
    OUT = main(_apply, _export, _folder)
except Exception as error:
    OUT = {'status': 'Stopped', 'error': str(error)}
