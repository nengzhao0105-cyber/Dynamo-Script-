# STRATUS Assembly Colors — Revit 2025

Creates a rule-based Revit view filter for each nonblank **STRATUS Assembly** text value found by the active view's element collector. Each filter uses **equals** and colors projection lines, cut lines, surface solid fill and cut solid fill. These are native Revit filters, editable under **VG → Filters**. No Dynamo packages are required; the Python node uses **CPython3**.

## Use

1. Copy **STRATUS Assembly Colors.dyn** to your Revit computer.
2. Open your Revit 2025 model and activate the plan, section, elevation or 3D view to color. For a drawing sheet, open the view placed on the sheet first.
3. Go to **Manage → Dynamo**, then open the `.dyn` file. Keep run mode **Manual**.
4. Leave **Apply colors** set to **False** and click **Run**. Expand the **Results** Watch node to review assemblies, RGB colors, skipped counts and any error.
5. Set **Apply colors** to **True**, then click **Run** to remove the active view template, disable other filters, and apply the assembly colors.
6. Check the drawing and **VG → Filters**. Save the Revit model when satisfied. Revit Undo can undo the operation.

Run again after new assemblies are added. Existing colors in the current view are preserved; new values receive colors chosen to differ from already assigned colors. Existing filters are reused when their parameter, categories and assembly match. Assembly membership updates automatically through the parameter rule. Creating filters for new values requires another run. Blank values remain uncolored.

## Scope and appearance

- Processes host-model elements returned by the active-view collector, with instance parameters preferred and type parameters used as a fallback. Collector counts are not a guarantee that every counted element is visibly drawn. Linked models are excluded.
- Requires one consistent, filterable text parameter definition across the detected categories. Duplicate names or incompatible category bindings produce an error before changes.
- Revit string equality is case insensitive: `SP-01` and `sp-01` share a filter. Leading/trailing whitespace is preserved; clean inconsistent values in Revit.
- Applies to the current view only. Colors are preserved per view, but separate views can receive different palettes. Filter names include a category signature to avoid rewriting filters used elsewhere.
- Apply sets the active view's **View Template** to **None** and disables every applied filter except the assembly filters used in this run. Disabled filters remain listed in VG and can be re-enabled. The template definition and other views are not edited.
- Preview reports the template and filters that will be affected, without changing the view. No changes are made if no assemblies are found. All changes roll back together if applying fails.
- Assembly discovery uses the view before other filters are disabled. If disabling a hiding filter reveals more assemblies, run again to include them.
- Element overrides may still take precedence. Existing non-filter view settings, transparency and halftone overrides are preserved.
- Use Hidden Line or Shaded and check the resulting view. Wireframe does not show solid surface fills. For printing, select color output.
- Keep assembly tags visible: colors alone cannot reliably distinguish many assemblies or accommodate all color-vision differences. The graph reports a warning above 20 assemblies.
- Reruns enable and show matching tool filters and restore their line/fill settings. Filters for old values are not deleted. Remove unwanted filters from the view through VG. Names starting `DYN STRATUS -` belong to this workflow; do not repurpose their rules.

## Files and validation

- `STRATUS Assembly Colors.dyn`: ready to open in Dynamo for Revit.
- `stratus_assembly_colors.py`: readable Python node source; can also be pasted into a CPython3 node with one Boolean input.
- `build_graph.py`: regenerates the graph after source edits.
- `tests/test_artifacts.py`: checks graph wiring, source synchronization, naming and color allocation without Revit.

The Python syntax and graph structure were checked locally. **Revit/Dynamo execution has not been tested**, because this workspace runs on macOS. First verify in a test model: two assemblies with multiple pieces each, a blank value, a repeated run, a new assembly, a template-controlled view and a cut view. Confirm matching pieces share a color, filters are reused, and cut/projection graphics are correct.

The implementation follows Autodesk's [view filter API guide](https://help.autodesk.com/cloudhelp/2021/ENU/Revit-API/files/Revit_API_Developers_Guide/Basic_Interaction_with_Revit_Elements/Views/Revit_API_Revit_API_Developers_Guide_Basic_Interaction_with_Revit_Elements_Views_View_Filters_html.html). The string equality rule uses the two-argument overload supported by Revit 2025.
