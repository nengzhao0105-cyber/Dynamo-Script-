# Stratus Package Bill of Material — Revit 2025

This Dynamo graph reads all host-model **Fabrication Pipework** created in **New Construction**, refreshes a Revit schedule named **Stratus Package Bill of Material**, and lets the user select multiple `STRATUS Package Name` values, multiple individual `STRATUS Assembly` values, or a mix of both.

## Output

- Revit schedule: grouped by Package, Type, Description and Size, with Count and Total Length.
- Excel `Fittings` tab: Description, Size and Count, sorted by Description and then Size.
- Excel `Pipe` tab: Description, Size, Count and Total Length (ft), sorted by Description and then Size.

The description source uses the first populated parameter in this order: `Family`, `Item Name`, `Product Name`, `Product Entry`, `Family Name`. Size uses `Size`, then `Product Size`. The Watch result reports which source names were actually used so they can be checked against the project content.

## Use

1. Open `Stratus Package Bill of Material.dyn` in Dynamo 3.x for Revit 2025.
2. Keep **Apply and create BOM** set to `False` and run once. Review the packages, source fields and skipped counts in the Watch node.
3. Set the input to `True` and run. Start typing in either autocomplete field, choose an exact suggested value, and click **Add package** or **Add assembly**. Repeat to build the order, review the running summary, then choose **Create BOM**. **Clear selections** starts over. An item included through both routes is counted once.
4. The schedule is recreated and all eligible parts are overwritten with current BOM values. Excel is saved to Downloads unless an existing absolute folder is entered.

Cancelling the picker makes no Revit or Excel changes. Each successful export is timestamped, so previous workbooks remain intact.

Excel files use the compact name `Stratus BOM - YYYY-MM-DD HHMMSS.xlsx`. Selected packages and assemblies are listed inside both worksheets instead of being added to the filename.

The Excel file is created immediately after selection and before the Revit schedule transaction. This keeps the order file available even if a later Revit schedule update reports an error. The Watch output returns the exact saved path under `excel`.

After writing, the graph verifies that the output exists, is non-empty, and is a valid ZIP-based Excel file. It reports an error instead of claiming success when that verification fails.

## Files and assumptions

- No Dynamo packages are required; the Python node uses CPython3.
- The graph creates `Stratus BOM Category`, `Stratus BOM Description`, `Stratus BOM Size`, and `Stratus BOM Total Length` as shared instance parameters. These use stable GUIDs distinct from the earlier test version's `Threads BOM` parameters.
- Fabrication Hangers and linked models are excluded.
- Straight pipe is detected with Revit's `FabricationPart.IsAStraight()` API, with type-text fallbacks.
- Descriptions containing `Shop Weld BW` or `Shop CS` are excluded from the BOM and counted in Watch diagnostics.
- Pipe length uses a numeric `Length` or `Cut Length` parameter, then `CenterlineLength` when available.
- Missing descriptions and sizes are included as visible exception groups; missing pipe lengths are reported and exported as zero so the problem cannot go unnoticed in the Watch diagnostics.
- Revit changes are undoable. The external Excel file is not covered by Revit Undo.

Validate the first Apply run in a copy of the project: check one straight pipe, one fitting, a repeated fitting, and the selected package's total pipe length.
