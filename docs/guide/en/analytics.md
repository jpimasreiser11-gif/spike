# Spike Analytics, Verified Reports, and Geo

Language: [Español](../es/analytics.md) | **English** · [Guide Index](README.md)

![Spike Analytics, Verified Reports, and Geo](../images/analytics.png)

## What it does

Analyzes tabular files (`CSV`, `TSV`, `Parquet`, `JSON`, `Excel .xlsx`) locally using **DuckDB**, renders interactive Vega-Lite charts with SVG/PNG export, builds offline **Geo** maps (GeoJSON and point layers without external tile servers), exports reports to Word (`.docx`) and PDF, and turns a table into an editable app with the **Data to app** template, where you review every change before it is written.

## Step-by-step usage

1. Upload a `.csv`, `.xlsx`, or `.parquet` file to a project or workspace and ask the **Data** specialist to query or chart it.
2. In the resulting data card, inspect the exact DuckDB SQL query, returned rows, and Vega-Lite chart (**SVG** / **PNG**).
3. Click **View report** to open the analytical evidence view—where every number is backed by its executed SQL query—or export to **Word** or **PDF**.
4. To edit cells, click **Create** in the sidebar, pick the **Data to app** template and the project file, click **Create local app (writes app.html)**, propose your changes, review them cell by cell, and click **Approve write**.

## Real limits

- The numbers in reports are computed by DuckDB SQL, and each query is shown with its result; very large files are bounded by row and byte limits.
- **Data to app** edits only UTF-8 CSV tables or the first sheet of an XLSX file (at most 2000 rows and 20000 cells; XLSX needs `openpyxl`).
- Geo maps use built-in offline coastline geometry and local GeoJSON/table layers without contacting external map tile servers; see [../../STATUS.md](../../STATUS.md).

## How to verify

- Run `.venv/bin/python -m pytest -q tests/test_analytics.py tests/test_analytics_reliability.py tests/test_geo.py tests/test_data_app.py`.
