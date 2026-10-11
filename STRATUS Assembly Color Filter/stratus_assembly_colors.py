"""Dynamo CPython3 / Revit 2025. IN[0]: apply (False previews)."""
import clr
import colorsys
import hashlib
import re
clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
from Autodesk.Revit.DB import (FilteredElementCollector, ParameterFilterElement,
    ParameterFilterUtilities, ParameterFilterRuleFactory, ElementParameterFilter,
    ElementId, StorageType, BuiltInParameter, FillPatternElement,
    FillPatternTarget, OverrideGraphicSettings, Color, SubTransaction,
    TransactionStatus)
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from System.Collections.Generic import List

PARAMETER = 'STRATUS Assembly'
PREFIX = 'DYN STRATUS - '


def filter_name(value, parameter_id, categories):
    # Category signature prevents changing filters already used by other views.
    key = '{}|{}|{}'.format(parameter_id, ','.join(map(str, sorted(categories))), value)
    digest = hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]
    label = re.sub(r'[\\:{}\[\]|;<>?`~\r\n]', '_', value)[:100]
    return PREFIX + label + ' - ' + digest


def choose_color(used):
    candidates = []
    for saturation, brightness in [(0.85, 0.78), (0.65, 0.60), (0.60, 0.92)]:
        for n in range(72):
            candidates.append(tuple(int(round(c * 255)) for c in
                                    colorsys.hsv_to_rgb(n / 72.0, saturation, brightness)))
    def distance(a, b):
        return sum((x - y) ** 2 for x, y in zip(a, b))
    if not used:
        return (30, 110, 200)
    return max(candidates, key=lambda c: min(distance(c, old) for old in used))


def prepare_view(view, keep_ids):
    view.ViewTemplateId = ElementId.InvalidElementId
    for fid in view.GetFilters():
        if fid.Value not in keep_ids:
            view.SetIsFilterEnabled(fid, False)


def main(apply):
    doc = DocumentManager.Instance.CurrentDBDocument
    view = doc.ActiveView
    if doc.IsFamilyDocument or view.IsTemplate or not view.AreGraphicsOverridesAllowed():
        raise ValueError('Open a model drawing view (plan, section, elevation, or 3D).')
    template = doc.GetElement(view.ViewTemplateId)
    template_name = template.Name if template else None

    warnings = []
    groups = {}
    category_ids = {}
    parameter_ids = {}
    counts = {'blank': 0, 'no_parameter': 0, 'unsupported': 0}
    eligible = {x.Value for x in ParameterFilterUtilities.GetAllFilterableCategories()}
    for element in FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType():
        if element.Category is None:
            continue
        parameters = list(element.GetParameters(PARAMETER))
        if not parameters:
            element_type = doc.GetElement(element.GetTypeId())
            parameters = list(element_type.GetParameters(PARAMETER)) if element_type else []
        if not parameters:
            counts['no_parameter'] += 1
            continue
        if len(parameters) != 1:
            raise ValueError('Multiple parameters named STRATUS Assembly on element {}. Resolve the duplicate names first.'.format(element.Id.Value))
        p = parameters[0]
        if p.StorageType != StorageType.String or element.Category.Id.Value not in eligible:
            counts['unsupported'] += 1
            continue
        value = p.AsString()
        if not value or not value.strip():
            counts['blank'] += 1
            continue
        # Revit string equality is case insensitive; retain whitespace in the rule.
        key = value.lower()
        group = groups.setdefault(key, {'value': value, 'count': 0})
        group['count'] += 1
        category_ids[element.Category.Id.Value] = element.Category.Id
        parameter_ids[p.Id.Value] = p.Id
    if not groups:
        return {'status': 'No nonblank, filterable text values found.', 'skipped': counts}
    if len(parameter_ids) != 1:
        raise ValueError('Different parameter definitions share the STRATUS Assembly name. Use one shared/project parameter definition across spool categories.')
    pid = next(iter(parameter_ids.values()))
    categories = List[ElementId](list(category_ids.values()))
    common = {x.Value for x in ParameterFilterUtilities.GetFilterableParametersInCommon(doc, categories)}
    if pid.Value not in common:
        raise ValueError('STRATUS Assembly is not filterable across the detected categories. Check its project/shared parameter bindings.')
    solid = next((x for x in FilteredElementCollector(doc).OfClass(FillPatternElement)
                  if x.GetFillPattern().IsSolidFill and
                  x.GetFillPattern().Target == FillPatternTarget.Drafting), None)
    if solid is None:
        raise ValueError('No drafting Solid Fill pattern found.')

    existing = {x.Name: x for x in FilteredElementCollector(doc).OfClass(ParameterFilterElement)}
    applied = {x.Value for x in view.GetFilters()}
    used = []
    # Preserve colors of this tool's filters, including values no longer visible.
    for f in existing.values():
        if f.Name.startswith(PREFIX) and f.Id.Value in applied:
            c = view.GetFilterOverrides(f.Id).ProjectionLineColor
            if c.IsValid:
                used.append((int(c.Red), int(c.Green), int(c.Blue)))
    plan = []
    for key in sorted(groups):
        group = groups[key]
        name = filter_name(key, pid.Value, category_ids)
        f = existing.get(name)
        rgb = None
        if f is not None:
            # Never silently overwrite a manually changed rule.
            rules = f.GetElementFilter()
            # Check the stored single equality rule before reusing it.
            if not isinstance(rules, ElementParameterFilter):
                raise ValueError('Existing tool filter was edited: ' + name)
            old_rules = list(rules.GetRules())
            if (len(old_rules) != 1 or old_rules[0].GetRuleParameter() != pid or
                not hasattr(old_rules[0], 'RuleString') or
                old_rules[0].RuleString.lower() != key or
                old_rules[0].GetEvaluator().GetType().Name != 'FilterStringEquals' or
                {x.Value for x in f.GetCategories()} != set(category_ids)):
                raise ValueError('Existing tool filter was edited: ' + name)
            if f.Id.Value in applied:
                c = view.GetFilterOverrides(f.Id).ProjectionLineColor
                if c.IsValid:
                    rgb = (int(c.Red), int(c.Green), int(c.Blue))
        if rgb is None:
            rgb = choose_color(used)
            used.append(rgb)
        plan.append((group, name, f, rgb))
    if len(groups) > 20:
        warnings.append('More than 20 assemblies: some colors may be hard to distinguish. Keep assembly tags on the drawing.')
    warnings.append('Element overrides, view settings, and linked-model graphics can affect the final appearance. Colors are assigned per view; linked elements are not processed.')

    result = {'status': 'Preview only; set Apply to True to create/apply filters.',
              'template_to_remove': template_name,
              'other_filters_to_disable': [doc.GetElement(fid).Name for fid in view.GetFilters()
                  if fid.Value not in {f.Id.Value for g, n, f, rgb in plan if f is not None}],
              'view': view.Name, 'parameter': PARAMETER, 'skipped': counts,
              'warnings': warnings, 'assemblies': [
                  {'assembly': g['value'], 'elements_in_view_collector': g['count'],
                   'filter': n, 'RGB': list(rgb), 'action': 'reuse' if f else 'create'}
                  for g, n, f, rgb in plan]}
    if not apply:
        return result
    manager = TransactionManager.Instance
    manager.EnsureInTransaction(doc)
    sub = SubTransaction(doc)
    sub.Start()
    try:
        # Keep view preparation and color changes in the same rollback boundary.
        keep_ids = {f.Id.Value for g, n, f, rgb in plan if f is not None}
        prepare_view(view, keep_ids)
        for group, name, f, rgb in plan:
            if f is None:
                rule = ParameterFilterRuleFactory.CreateEqualsRule(pid, group['value'])
                f = ParameterFilterElement.Create(doc, name, categories, ElementParameterFilter(rule))
            ogs = view.GetFilterOverrides(f.Id) if f.Id.Value in applied else OverrideGraphicSettings()
            color = Color(*rgb)
            ogs.SetProjectionLineColor(color)
            ogs.SetCutLineColor(color)
            ogs.SetSurfaceForegroundPatternId(solid.Id)
            ogs.SetSurfaceForegroundPatternColor(color)
            ogs.SetSurfaceForegroundPatternVisible(True)
            ogs.SetCutForegroundPatternId(solid.Id)
            ogs.SetCutForegroundPatternColor(color)
            ogs.SetCutForegroundPatternVisible(True)
            view.SetFilterOverrides(f.Id, ogs)
            view.SetFilterVisibility(f.Id, True)
            view.SetIsFilterEnabled(f.Id, True)
        if sub.Commit() != TransactionStatus.Committed:
            raise RuntimeError('Revit did not commit the filter changes.')
    except Exception:
        if sub.GetStatus() == TransactionStatus.Started:
            sub.RollBack()
        raise
    finally:
        manager.TransactionTaskDone()
    result['removed_template'] = template_name
    result['disabled_other_filters'] = result.pop('other_filters_to_disable')
    result.pop('template_to_remove')
    result['status'] = 'Applied {} assembly filters.'.format(len(plan))
    return result


try:
    OUT = main(bool(IN[0]) if IN and IN[0] is not None else False)
except Exception as error:
    OUT = {'status': 'Stopped', 'error': str(error)}
