# STRATUS Assembly Weight Reporting — Revit 2025

Processes the full host project without element selection. It groups **Fabrication Pipework** created in the **New Construction** phase by the exact `STRATUS Assembly` instance value, reads each part's `Weight`, writes assembly results, creates a one-row-per-assembly Revit schedule, and can create a package-filtered Excel heat-map report.

## Assumptions

- Revit 2025, Dynamo 3.x, and the built-in CPython3 engine.
- Pipe and fittings are in **Fabrication Pipework**. Fabrication Hangers and linked models are excluded.
- `STRATUS Assembly` and `Weight` exist as instance parameters. Blank assembly values and unreadable weights are skipped and counted in the results.
- `STRATUS Package Name` supplies the searchable package picker. Blank package values remain in the master Revit report but are unavailable in the package picker.
- Assembly identifiers are exact: case and leading/trailing whitespace are not normalized.
- The model has exactly one phase named `New Construction`. Parts must be created in that phase and not demolished in it.
- `Weight` is a mass value displayed in lbm. The report converts Revit's internal mass value to pounds mass.
- Because the supplied Assembly Name source is also `STRATUS Assembly`, ID and Name contain the same text.
- Multiple service abbreviations within an assembly are comma-separated in Excel. The native schedule uses Revit's Service Abbreviation field when available.

## Files

- `STRATUS Assembly Weight Report.dyn` — ready-to-open Dynamo graph.
- `stratus_assembly_weight_report.py` — readable Python-node source.
- `build_graph.py` — regenerates the graph after source edits.
- `tests/test_artifacts.py` — offline syntax, graph, and helper tests.

No Dynamo packages are required.

## Safe use

1. Open a copy of the Revit model and open this graph in Dynamo.
2. Leave **Apply changes** and **Create package Excel report** set to `False`; use Manual run mode and click **Run**.
3. Review the assembly rows and skipped counts in the Watch node. Confirm several totals against the test model.
4. Set **Apply changes** to `True` and run again. This creates or updates:
   - `STRATUS Assembly Name`
   - `STRATUS Assembly Piece Count`
   - `STRATUS Assembly Total Weight`
   - schedule `STRATUS Assembly Weight Report`
5. To create Excel, set **Create package Excel report** to `True`. Choose a package from the searchable pop-up. Leave the folder blank for the Windows Downloads folder, or enter an existing absolute folder path.

Keep Dynamo in **Manual** run mode. The graph includes an automatic `DateTime.Now` trigger, so every click of **Run** re-executes the Python node and reopens the package picker. You can create reports for several packages without closing or reopening the graph. Do not disconnect the Run trigger node.

The Excel workbook contains one concise package report, sorting assemblies from heaviest to lightest, with filters, a frozen header, and a light-to-dark conditional color scale on **Actual Weight (lbm)**. Visible columns are **STRATUS Package Name**, **Assembly Name**, **Service**, **Piece Count**, **Gross Weight (lbm)**, and **Actual Weight (lbm)**. The workflow does not inspect Revit connector status; coupling deductions use separately modeled coupling parts and their weights.

Separately modeled fabrication parts are treated as couplings when `Product Short Description`, `Alias`, element name, `Item Name`, `Product Name`, `Description`, or `STRATUS Item Name` contains `coupl` (case-insensitive). Their individual `Weight` values are deducted from Gross Weight to produce Actual Weight. The adjusted Actual Weight is written to `STRATUS Assembly Total Weight` and drives the Revit schedule and Excel heat map. Each run creates a timestamped `.xlsx` file so earlier reports are retained. Cancelling the picker skips Excel only; an Apply run still updates Revit and the master schedule.

## Rerun behavior

Eligible parts are recalculated and overwritten on every Apply run. The schedule with the exact tool name is deleted and recreated so stale fields and grouping do not survive. Other schedules are untouched.

The three write-back parameters are shared instance parameters with stable GUIDs, bound to Fabrication Pipework. If same-named incompatible or read-only parameters already exist, the run stops rather than silently replacing them.

## Validation limits

The graph and Python syntax can be checked outside Revit, but Revit API behavior must be validated in the supplied Revit 2025 test model. Preview first, then verify a straight pipe, a fitting, an assembly with multiple pieces, a blank assembly, and the resulting schedule totals. Revit Undo can undo the Apply transaction; Excel files are external and are not covered by Revit Undo.
