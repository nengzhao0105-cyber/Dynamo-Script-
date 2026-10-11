"""Dynamo CPython3 / Revit 2025.

IN[0]: Apply changes (False = preview)
IN[1]: Excel folder (blank = Downloads)
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
    BuiltInCategory, BuiltInParameter, Category, ElementId,
    ExternalDefinitionCreationOptions, FilteredElementCollector,
    ScheduleFieldDisplayType, ScheduleFieldType, ScheduleFilter, ScheduleFilterType,
    ScheduleSortGroupField, SpecTypeId, StorageType, SubTransaction,
    TransactionStatus, UnitTypeId, UnitUtils, ViewSchedule, FabricationPart
)
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

PACKAGE = 'STRATUS Package Name'
ASSEMBLY = 'STRATUS Assembly'
SCHEDULE_NAME = 'Stratus Package Bill of Material'
PHASE_NAME = 'New Construction'
BOM_CLASS = 'Stratus BOM Category'
BOM_DESCRIPTION = 'Stratus BOM Description'
BOM_SIZE = 'Stratus BOM Size'
BOM_LENGTH = 'Stratus BOM Total Length'

PARAMETERS = OrderedDict([
    (BOM_CLASS, (Guid('b215b4cb-4f28-405c-a332-1b72d2ed2201'), SpecTypeId.String.Text)),
    (BOM_DESCRIPTION, (Guid('b215b4cb-4f28-405c-a332-1b72d2ed2202'), SpecTypeId.String.Text)),
    (BOM_SIZE, (Guid('b215b4cb-4f28-405c-a332-1b72d2ed2203'), SpecTypeId.String.Text)),
    (BOM_LENGTH, (Guid('b215b4cb-4f28-405c-a332-1b72d2ed2204'), SpecTypeId.Length)),
])

DESCRIPTION_FIELDS = ('Family', 'Item Name', 'Product Name', 'Product Entry', 'Family Name')
SIZE_FIELDS = ('Size', 'Product Size')
LENGTH_FIELDS = ('Length', 'Cut Length')
EXCLUDED_DESCRIPTION_TEXT = ('shop weld bw', 'shop cs')


def eid_value(eid):
    return eid.Value if hasattr(eid, 'Value') else eid.IntegerValue


def parameter_text(element, name):
    p = element.LookupParameter(name)
    if p is None:
        return None
    value = p.AsString() if p.StorageType == StorageType.String else p.AsValueString()
    return value.strip() if value and value.strip() else None


def first_parameter_text(element, names):
    for name in names:
        value = parameter_text(element, name)
        if value:
            return value, name
    return None, None


def is_straight_pipe(part):
    """Use the FabricationPart type first, with content-text fallbacks."""
    try:
        if part.IsAStraight():
            return True
    except Exception:
        pass
    try:
        if str(part.PartType).lower() == 'straight':
            return True
    except Exception:
        pass
    for name in ('Part Type', 'Item Type'):
        value = parameter_text(part, name)
        if value and value.lower() in ('straight', 'straight pipe', 'pipe', 'tube'):
            return True
    return False


def length_internal(part):
    """Return Revit internal length for straight pipe, or an explanatory error."""
    for name in LENGTH_FIELDS:
        p = part.LookupParameter(name)
        if p is not None and p.StorageType == StorageType.Double:
            return p.AsDouble(), None
    try:
        value = part.CenterlineLength
        if value is not None:
            return float(value), None
    except Exception:
        pass
    return None, 'missing or unreadable Length'


def collect(doc):
    phase_matches = [p for p in doc.Phases if p.Name == PHASE_NAME]
    if len(phase_matches) != 1:
        raise ValueError('Expected exactly one phase named "{}"; found {}.'.format(
            PHASE_NAME, len(phase_matches)))
    phase = phase_matches[0]
    records = []
    packages = set()
    assemblies = set()
    skipped = {'wrong_phase': 0, 'blank_package_and_assembly': 0, 'excluded_shop_item': 0,
               'missing_description': 0,
               'missing_size': 0, 'missing_pipe_length': 0}
    description_sources = set()
    size_sources = set()
    parts = (FilteredElementCollector(doc)
             .OfCategory(BuiltInCategory.OST_FabricationPipework)
             .WhereElementIsNotElementType())
    for part in parts:
        if not isinstance(part, FabricationPart):
            continue
        if eid_value(part.CreatedPhaseId) != eid_value(phase.Id):
            skipped['wrong_phase'] += 1
            continue
        if (part.DemolishedPhaseId != ElementId.InvalidElementId and
                eid_value(part.DemolishedPhaseId) == eid_value(phase.Id)):
            skipped['wrong_phase'] += 1
            continue
        package = parameter_text(part, PACKAGE)
        assembly = parameter_text(part, ASSEMBLY)
        if not package and not assembly:
            skipped['blank_package_and_assembly'] += 1
            continue
        description, description_source = first_parameter_text(part, DESCRIPTION_FIELDS)
        size, size_source = first_parameter_text(part, SIZE_FIELDS)
        if description and any(text in description.lower() for text in EXCLUDED_DESCRIPTION_TEXT):
            skipped['excluded_shop_item'] += 1
            continue
        if not description:
            description = '<Missing description>'
            skipped['missing_description'] += 1
        else:
            description_sources.add(description_source)
        if not size:
            size = '<Missing size>'
            skipped['missing_size'] += 1
        else:
            size_sources.add(size_source)
        category = 'Pipe' if is_straight_pipe(part) else 'Fitting'
        length = 0.0
        if category == 'Pipe':
            length, error = length_internal(part)
            if error:
                skipped['missing_pipe_length'] += 1
                length = 0.0
        if package:
            packages.add(package)
        if assembly:
            assemblies.add(assembly)
        records.append({'element': part, 'package': package, 'assembly': assembly,
                        'category': category, 'description': description, 'size': size,
                        'length_internal': length})
    return (records, sorted(packages), sorted(assemblies), skipped, phase,
            sorted(description_sources), sorted(size_sources))


def aggregate(records, packages, assemblies):
    selected_packages = set(packages)
    selected_assemblies = set(assemblies)
    fittings = OrderedDict()
    pipe = OrderedDict()
    for record in records:
        if (record['package'] not in selected_packages and
                record['assembly'] not in selected_assemblies):
            continue
        key = (record['description'], record['size'])
        target = pipe if record['category'] == 'Pipe' else fittings
        row = target.setdefault(key, {'description': key[0], 'size': key[1],
                                     'count': 0, 'length_internal': 0.0})
        row['count'] += 1
        row['length_internal'] += record['length_internal']
    fitting_rows = sorted(fittings.values(), key=lambda x: (x['description'].lower(), x['size'].lower()))
    pipe_rows = sorted(pipe.values(), key=lambda x: (x['description'].lower(), x['size'].lower()))
    return fitting_rows, pipe_rows


def ensure_parameters(doc, app):
    old_path = app.SharedParametersFilename
    fd, path = tempfile.mkstemp(prefix='stratus_bom_', suffix='.txt')
    os.close(fd)
    try:
        with open(path, 'w') as shared:
            shared.write('# This is a Revit shared parameter file.\n')
            shared.write('*META\tVERSION\tMINVERSION\nMETA\t2\t1\n')
            shared.write('*GROUP\tID\tNAME\n')
            shared.write('*PARAM\tGUID\tNAME\tDATATYPE\tDATACATEGORY\tGROUP\tVISIBLE\tDESCRIPTION\tUSERMODIFIABLE\tHIDEWHENNOVALUE\n')
        app.SharedParametersFilename = path
        definition_file = app.OpenSharedParameterFile()
        group = definition_file.Groups.Create('Dynamo Stratus BOM')
        categories = app.Create.NewCategorySet()
        categories.Insert(Category.GetCategory(doc, BuiltInCategory.OST_FabricationPipework))
        binding = app.Create.NewInstanceBinding(categories)
        existing = set()
        iterator = doc.ParameterBindings.ForwardIterator()
        iterator.Reset()
        while iterator.MoveNext():
            existing.add(iterator.Key.Name)
        for name, (guid, data_type) in PARAMETERS.items():
            if name in existing:
                continue
            options = ExternalDefinitionCreationOptions(name, data_type)
            options.GUID = guid
            definition = group.Definitions.Create(options)
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
        raise ValueError('Parameter "{}" is missing or read-only on element {}.'.format(
            name, eid_value(element.Id)))
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
    existing = [v for v in FilteredElementCollector(doc).OfClass(ViewSchedule)
                if not v.IsTemplate and v.Name == SCHEDULE_NAME]
    for schedule in existing:
        doc.Delete(schedule.Id)
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

    package = add(PACKAGE, 'Package')
    assembly = add(ASSEMBLY, 'Assembly')
    category = add(BOM_CLASS, 'Type')
    description = add(BOM_DESCRIPTION, 'Description')
    size = add(BOM_SIZE, 'Size')
    count_choices = [x for x in definition.GetSchedulableFields()
                     if x.FieldType == ScheduleFieldType.Count]
    if not count_choices:
        raise ValueError('Fabrication Pipework does not expose a schedule Count field.')
    count = definition.AddField(count_choices[0])
    count.ColumnHeading = 'Count'
    length = add(BOM_LENGTH, 'Total Length')
    length.DisplayType = ScheduleFieldDisplayType.Totals
    phase_field = None
    phase_id = ElementId(BuiltInParameter.PHASE_CREATED)
    for schedulable in definition.GetSchedulableFields():
        if schedulable.ParameterId == phase_id:
            phase_field = definition.AddField(schedulable)
            phase_field.IsHidden = True
            break
    if phase_field is None:
        raise ValueError('The schedule does not expose Phase Created.')
    definition.IsItemized = False
    for field in (package, assembly, category, description, size):
        definition.AddSortGroupField(ScheduleSortGroupField(field.FieldId))
    definition.AddFilter(ScheduleFilter(phase_field.FieldId, ScheduleFilterType.Equal, phase.Id))
    definition.AddFilter(ScheduleFilter(category.FieldId, ScheduleFilterType.HasValue))
    return schedule


def select_scope(packages, assemblies):
    clr.AddReference('System.Windows.Forms')
    clr.AddReference('System.Drawing')
    from System.Drawing import Point, Size
    from System.Windows.Forms import (AutoCompleteMode, AutoCompleteSource, Button,
        ComboBox, ComboBoxStyle, DialogResult, Form, FormBorderStyle, Label,
        FormStartPosition)
    selected_packages = set()
    selected_assemblies = set()
    note_text = 'Type to search, choose an exact value, then add it to the order.'

    while True:
        form = Form()
        form.Text = SCHEDULE_NAME
        form.ClientSize = Size(760, 390)
        form.FormBorderStyle = FormBorderStyle.FixedDialog
        form.MaximizeBox = False
        form.MinimizeBox = False
        form.ShowInTaskbar = False
        form.TopMost = True
        form.StartPosition = FormStartPosition.CenterScreen
        label = Label()
        label.Text = note_text
        label.AutoSize = True
        label.Location = Point(20, 15)
        form.Controls.Add(label)

        package_label = Label()
        package_label.Text = 'Search packages'
        package_label.AutoSize = True
        package_label.Location = Point(20, 50)
        form.Controls.Add(package_label)
        package_combo = ComboBox()
        package_combo.Location = Point(20, 75)
        package_combo.Size = Size(345, 28)
        package_combo.DropDownStyle = ComboBoxStyle.DropDown
        package_combo.AutoCompleteMode = AutoCompleteMode.SuggestAppend
        package_combo.AutoCompleteSource = AutoCompleteSource.ListItems
        for value in packages:
            package_combo.Items.Add(value)
        form.Controls.Add(package_combo)
        add_package = Button()
        add_package.Text = 'Add package'
        add_package.Location = Point(255, 112)
        add_package.Size = Size(110, 30)
        add_package.DialogResult = DialogResult.Retry
        form.Controls.Add(add_package)

        assembly_label = Label()
        assembly_label.Text = 'Search individual assemblies'
        assembly_label.AutoSize = True
        assembly_label.Location = Point(395, 50)
        form.Controls.Add(assembly_label)
        assembly_combo = ComboBox()
        assembly_combo.Location = Point(395, 75)
        assembly_combo.Size = Size(345, 28)
        assembly_combo.DropDownStyle = ComboBoxStyle.DropDown
        assembly_combo.AutoCompleteMode = AutoCompleteMode.SuggestAppend
        assembly_combo.AutoCompleteSource = AutoCompleteSource.ListItems
        for value in assemblies:
            assembly_combo.Items.Add(value)
        form.Controls.Add(assembly_combo)
        add_assembly = Button()
        add_assembly.Text = 'Add assembly'
        add_assembly.Location = Point(630, 112)
        add_assembly.Size = Size(110, 30)
        add_assembly.DialogResult = DialogResult.Ignore
        form.Controls.Add(add_assembly)

        summary = Label()
        summary.Text = ('Selected packages ({}): {}\n\nSelected assemblies ({}): {}'
                        .format(len(selected_packages),
                                ', '.join(sorted(selected_packages)) or 'None',
                                len(selected_assemblies),
                                ', '.join(sorted(selected_assemblies)) or 'None'))
        summary.AutoSize = False
        summary.Location = Point(20, 165)
        summary.Size = Size(720, 125)
        form.Controls.Add(summary)

        reset = Button()
        reset.Text = 'Clear selections'
        reset.Location = Point(20, 330)
        reset.Size = Size(120, 30)
        reset.DialogResult = DialogResult.Abort
        form.Controls.Add(reset)
        ok = Button()
        ok.Text = 'Create BOM'
        ok.Location = Point(535, 330)
        ok.Size = Size(110, 30)
        ok.DialogResult = DialogResult.OK
        form.AcceptButton = ok
        form.Controls.Add(ok)
        cancel = Button()
        cancel.Text = 'Cancel'
        cancel.Location = Point(655, 330)
        cancel.Size = Size(85, 30)
        cancel.DialogResult = DialogResult.Cancel
        form.CancelButton = cancel
        form.Controls.Add(cancel)

        choice = form.ShowDialog()
        package_value = package_combo.Text.strip()
        assembly_value = assembly_combo.Text.strip()
        form.Dispose()
        if choice == DialogResult.Cancel:
            return None
        if choice == DialogResult.Retry:
            if package_value in packages:
                selected_packages.add(package_value)
                note_text = 'Package added. Continue searching or create the BOM.'
            else:
                note_text = 'Package not added: choose an exact value from the suggestions.'
            continue
        if choice == DialogResult.Ignore:
            if assembly_value in assemblies:
                selected_assemblies.add(assembly_value)
                note_text = 'Assembly added. Continue searching or create the BOM.'
            else:
                note_text = 'Assembly not added: choose an exact value from the suggestions.'
            continue
        if choice == DialogResult.Abort:
            selected_packages.clear()
            selected_assemblies.clear()
            note_text = 'Selections cleared. Add packages, assemblies, or both.'
            continue
        # Create BOM also accepts a valid value currently shown in either field.
        if package_value in packages:
            selected_packages.add(package_value)
        if assembly_value in assemblies:
            selected_assemblies.add(assembly_value)
        if not selected_packages and not selected_assemblies:
            raise ValueError('Select at least one package or individual assembly.')
        return sorted(selected_packages), sorted(selected_assemblies)


def excel_path(folder, packages):
    base = folder.strip() if folder and folder.strip() else os.path.expanduser('~/Downloads')
    if not os.path.isdir(base):
        raise ValueError('Excel folder does not exist: ' + base)
    stamp = datetime.datetime.now().strftime('%Y-%m-%d %H%M%S')
    candidate = os.path.join(base, 'Stratus BOM - {}.xlsx'.format(stamp))
    if not os.path.exists(candidate):
        return candidate
    number = 2
    while True:
        alternate = os.path.join(base, 'Stratus BOM - {} - {}.xlsx'.format(stamp, number))
        if not os.path.exists(alternate):
            return alternate
        number += 1


def xml_text(value):
    return (str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;').replace("'", '&apos;'))


def xlsx_cell(reference, value, style=0, numeric=False):
    if numeric:
        return '<c r="{}" s="{}"><v>{}</v></c>'.format(reference, style, value)
    return '<c r="{}" s="{}" t="inlineStr"><is><t xml:space="preserve">{}</t></is></c>'.format(
        reference, style, xml_text(value))


def worksheet_xml(title, packages, assemblies, headers, data_rows, pipe_sheet=False):
    package_label = ', '.join(packages) if packages else 'None'
    assembly_label = ', '.join(assemblies) if assemblies else 'None'
    rows = [
        '<row r="2" ht="24" customHeight="1">{}</row>'.format(xlsx_cell('A2', title, 1)),
        '<row r="3">{}{}</row>'.format(xlsx_cell('A3', 'Packages', 2), xlsx_cell('B3', package_label, 3)),
        '<row r="4">{}{}</row>'.format(xlsx_cell('A4', 'Assemblies', 2), xlsx_cell('B4', assembly_label, 3)),
        '<row r="5">{}{}</row>'.format(xlsx_cell('A5', 'Generated', 2), xlsx_cell('B5', datetime.datetime.now().strftime('%Y-%m-%d %H:%M'), 3)),
        '<row r="6" ht="22" customHeight="1">{}</row>'.format(''.join(
            xlsx_cell('{}6'.format(chr(65 + i)), header, 4) for i, header in enumerate(headers)))
    ]
    for index, row in enumerate(data_rows, 7):
        cells = [xlsx_cell('A{}'.format(index), row['description'], 5),
                 xlsx_cell('B{}'.format(index), row['size'], 5),
                 xlsx_cell('C{}'.format(index), row['count'], 6, True)]
        if pipe_sheet:
            feet = UnitUtils.ConvertFromInternalUnits(row['length_internal'], UnitTypeId.Feet)
            cells.append(xlsx_cell('D{}'.format(index), round(feet, 3), 7, True))
        rows.append('<row r="{}">{}</row>'.format(index, ''.join(cells)))
    last = max(6, 6 + len(data_rows))
    last_col = 'D' if pipe_sheet else 'C'
    return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<sheetViews><sheetView showGridLines="0" workbookViewId="0"><pane ySplit="6" topLeftCell="A7" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
<cols><col min="1" max="1" width="38" customWidth="1"/><col min="2" max="2" width="23" customWidth="1"/><col min="3" max="3" width="13" customWidth="1"/><col min="4" max="4" width="21" customWidth="1"/></cols>
<sheetData>{rows}</sheetData><autoFilter ref="A6:{last_col}{last}"/>
<pageMargins left="0.4" right="0.4" top="0.6" bottom="0.6" header="0.2" footer="0.2"/>
</worksheet>'''.format(rows=''.join(rows), last_col=last_col, last=last)


def export_excel(fittings, pipe, packages, assemblies, folder):
    path = excel_path(folder, packages)
    fitting_sheet = worksheet_xml('Stratus Package Bill of Material - Fittings',
                                  packages, assemblies, ['Description', 'Size', 'Count'], fittings, False)
    pipe_sheet = worksheet_xml('Stratus Package Bill of Material - Pipe',
                               packages, assemblies, ['Description', 'Size', 'Count', 'Total Length (ft)'], pipe, True)
    styles = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="4"><font><sz val="10"/><name val="Arial"/></font><font><b/><sz val="14"/><name val="Arial"/></font><font><b/><sz val="10"/><color rgb="FF404040"/><name val="Arial"/></font><font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Arial"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF1F4E78"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border><border><left/><right/><top/><bottom style="thin"><color rgb="FFD9E2F3"/></bottom><diagonal/></border></borders><numFmts count="1"><numFmt numFmtId="164" formatCode="#,##0.000"/></numFmts><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="8"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1"/><xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="3" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf><xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1"/><xf numFmtId="3" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"/><xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'''
    content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>'''
    root_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'''
    workbook = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Fittings" sheetId="1" r:id="rId1"/><sheet name="Pipe" sheetId="2" r:id="rId2"/></sheets><calcPr calcId="191029" fullCalcOnLoad="1"/></workbook>'''
    workbook_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'''
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in [('[Content_Types].xml', content_types), ('_rels/.rels', root_rels),
                           ('xl/workbook.xml', workbook), ('xl/_rels/workbook.xml.rels', workbook_rels),
                           ('xl/worksheets/sheet1.xml', fitting_sheet),
                           ('xl/worksheets/sheet2.xml', pipe_sheet), ('xl/styles.xml', styles)]:
            archive.writestr(name, data.encode('utf-8'))
    if not os.path.isfile(path) or os.path.getsize(path) == 0 or not zipfile.is_zipfile(path):
        raise IOError('Excel validation failed after writing: ' + path)
    return path


def main(apply_changes, folder):
    uiapp = DocumentManager.Instance.CurrentUIApplication
    app = uiapp.Application
    doc = DocumentManager.Instance.CurrentDBDocument
    if doc.IsFamilyDocument:
        raise ValueError('Open a Revit project model, not a family document.')
    (records, packages, assemblies, skipped, phase, description_sources,
     size_sources) = collect(doc)
    result = {'status': 'Preview only; set Apply changes to True.',
              'schedule': SCHEDULE_NAME, 'phase': phase.Name,
              'eligible_parts': len(records), 'packages': packages,
              'assemblies': assemblies, 'skipped': skipped,
              'description_sources_used': description_sources,
              'size_sources_used': size_sources}
    if not records:
        result['status'] = 'No eligible packaged or assembled Fabrication Pipework found.'
        return result
    if not apply_changes:
        return result
    selection = select_scope(packages, assemblies)
    if selection is None:
        result['status'] = 'Cancelled; no Revit or Excel changes were made.'
        return result
    selected_packages, selected_assemblies = selection
    fittings, pipe = aggregate(records, selected_packages, selected_assemblies)
    if not fittings and not pipe:
        raise ValueError('The selected packages and assemblies contain no BOM items after exclusions.')
    result['selected_packages'] = selected_packages
    result['selected_assemblies'] = selected_assemblies
    result['fitting_groups'] = len(fittings)
    result['pipe_groups'] = len(pipe)
    result['excel'] = export_excel(fittings, pipe, selected_packages,
                                   selected_assemblies, folder)
    manager = TransactionManager.Instance
    manager.EnsureInTransaction(doc)
    sub = SubTransaction(doc)
    sub.Start()
    revit_error = None
    try:
        ensure_parameters(doc, app)
        doc.Regenerate()
        for record in records:
            set_value(record['element'], BOM_CLASS, record['category'])
            set_value(record['element'], BOM_DESCRIPTION, record['description'])
            set_value(record['element'], BOM_SIZE, record['size'])
            set_value(record['element'], BOM_LENGTH,
                      record['length_internal'] if record['category'] == 'Pipe' else 0.0)
        schedule = replace_schedule(doc, phase)
        result['schedule_id'] = eid_value(schedule.Id)
        if sub.Commit() != TransactionStatus.Committed:
            raise RuntimeError('Revit did not commit the Bill of Material changes.')
    except Exception as error:
        if sub.GetStatus() == TransactionStatus.Started:
            sub.RollBack()
        revit_error = str(error)
    finally:
        manager.TransactionTaskDone()
    if revit_error:
        result['revit_error'] = revit_error
        result['status'] = 'Excel saved, but the Revit schedule update failed.'
        return result
    result['status'] = ('Saved Excel and updated {} parts; recreated schedule "{}".'
                        .format(len(records), SCHEDULE_NAME))
    return result


try:
    _apply = bool(IN[0]) if IN and len(IN) > 0 and IN[0] is not None else False
    _folder = str(IN[1]) if IN and len(IN) > 1 and IN[1] is not None else ''
    OUT = main(_apply, _folder)
except Exception as error:
    OUT = {'status': 'Stopped', 'error': str(error)}
