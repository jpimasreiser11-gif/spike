# Analytics A3

Analytics works on workspace files locally. No service, network request, new package or model inference is required.
DuckDB remains the existing optional `data` extra; JSON Schema and YAML use dependencies already declared by SPIKE.

## Loading and rescue

`Session(workspace, files, locale="es", contracts={"sales.csv": "sales.contract.json"})` rescues CSV/TSV/TXT before
creating the DuckDB table. Source files are never modified. `locale="es"` interprets slash dates day-first;
`locale="en"` uses month-first. Both accept ISO dates and Spanish/English month names. The default is explicit and
deterministic; ambiguous dates are not inferred from the host locale.

Rescue handles UTF-8 (with or without BOM), cp1252, comma/semicolon/tab/pipe separators, leading narrow preamble
records, header detection, empty/duplicate header names, decimal commas, dates, duplicate rows and empty columns.
Numbers and dates convert only when every nonempty value in that column parses. A first record containing text
is treated as a header; numeric/date-only records receive generated column names. Ragged records fail with an
error rather than losing cells. Mixed-format dates/numbers stay text if the whole column cannot be converted.
Duplicate removal applies to full normalized rows, including the time column when present; it can change counts.

The rescue report includes before/after dimensions, each repair's code/count or detection settings, the original
SHA-256 and the normalized-data SHA-256. Reports omit cell values. Header-only/empty-column-only CSVs are refused.
Encoding detection is limited to UTF-8/cp1252; this is not a general encoding detector. Large-file memory/speed
have not been measured. Parquet, JSON, Excel and SQLite retain their existing loaders; CSV rescue does not rewrite
those binary/structured formats.

## Data contracts

A contract is a UTF-8 JSON or safely loaded YAML file inside the workspace. Example:

```json
{
  "columns": {
    "day": {"type": "date", "nullable": false},
    "amount": {"type": "number", "nullable": false},
    "region": {"type": "string"}
  },
  "rules": [
    {"column": "day", "unique": true},
    {"column": "amount", "min": 0, "max": 1000000},
    {"column": "region", "enum": ["north", "south"]}
  ]
}
```

Supported logical types: `string`, `integer`, `number`, `boolean`, `date`, `datetime`. Declared columns are required;
extra data columns are allowed; `nullable` defaults to true. Rules skip nulls (use `nullable: false` to reject them).
Definitions reject unknown fields/types, undeclared rule columns, nonnumeric bounds and inverted ranges.
Validation runs on rescued/loaded values, before any user SQL. Violations identify table, column, 1-based data row
and code, without exposing the value. `ContractViolation.violations` contains the report; tools return an error
with the report. A failed load cannot be queried. A misspelled filename in `contracts` fails rather than bypassing
validation. One contract for a multi-sheet file applies to every loaded sheet.

The `contracts` and `locale` arguments are available in `data_describe`, `data_sql`, `data_chart`, `data_forecast`.

## SQL Guardian

The in-memory connection must be writable during trusted loading. Each user query then runs in a DuckDB
`BEGIN TRANSACTION READ ONLY` transaction, in addition to the existing external-access/configuration lockdown.
DuckDB parses and classifies the statement: one SELECT only by default. Multi-statements, EXPLAIN ANALYZE writes,
COPY, ATTACH, INSTALL, LOAD and settings are refused. Side effects within SELECT (for example `nextval`) are blocked
by the read-only transaction. The existing query timeout still applies to execution.

`Session.explain(sql, limit)` and `data_sql` with `explain_only: true` return an EXPLAIN JSON plan and a deterministic
Spanish/English explanation without executing the query. Normal `run_query`/`data_sql` also explain before running.
Previews wrap the SQL with `LIMIT limit + 1`; the extra row is only a truncation sentinel. Limits are 1–10000.

Only a trusted Python caller can use `session.query(sql, limit, approved=True)` for an explicitly approved
INSERT/UPDATE/DELETE/CREATE/ALTER/DROP on disposable in-memory tables. The flag must be the literal Boolean true;
it is not exposed in any model tool schema and model-supplied `approved` arguments cannot grant permission.
The chat SQL tool stays read-only; no new chat write/export workflow is introduced. Approved writes are not saved
to the source files and still cannot use external access. The Python caller is responsible for obtaining the
human approval before supplying the flag.

## Baseline forecasts

`data_forecast` accepts `files`, a one-column numeric SQL query ordered by time, `horizon` (1–100) and `season`
(default 1). The caller must supply equally spaced observations, aggregate to a regular frequency and resolve
missing periods first. Forecast output is step numbers, not inferred calendar dates. Null/nonfinite/nonnumeric
values, fewer than `max(2, season) + horizon` observations or over 10000 values are refused.

Candidates:

- `naive`: repeat the last observation.
- `seasonal_naive`: repeat the last complete season.
- `drift`: extend the line between first and last observations.
- `ses`: simple exponential smoothing, alpha=0.5, initialized at the first observation.
- `holt`: additive level/trend, alpha=beta=0.5, initial level=first value and trend=second minus first.

All methods use the same expanding rolling origins, beginning at `max(2, season)`, with complete horizon-sized
held-out windows. At most the last 100 origins are evaluated. MAE averages all held-out absolute errors, including
overlapping windows. The lowest MAE wins; ties use the candidate order above. The output includes every method's
MAE, fold count, individual absolute errors, origins and fixed smoothing parameters. Parameters are not tuned.
Backtest scores and the chosen method appear beside the forecast in the existing result card. No prediction
intervals or future accuracy claims are made; these mathematical baselines have not been measured on real business
data or with real model weights (the implementation does not use model weights).

## Lineage and proof

Results snapshot an ordered list of rescue, source load/checksum, contract checks, EXPLAIN, query, chart and forecast
steps. Rescue substeps and full backtest evidence are nested within their steps. The new evidence component shows
them in Spanish or English. Tool UI payloads are already persisted with conversation messages; the existing proof
package's `chat.json` therefore contains the complete successful analysis lineage without changing the proof format.
The integration test runs a scripted Data chat and checks the actual exported ZIP. As before, exports are not signed.
