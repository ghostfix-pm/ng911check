# ng911check

Run documented NG9-1-1 address and centerline checks from a CSV or GeoJSON. Refuse to let a settings line silently switch a routing error off.

> **Status: started, not built.** The check modules in `ng911check/` were copied from the original ArcGIS toolbox and are partly ported. The package does not run yet. It has no `__main__`, no CSV reader and no self-test.

## The disaster

You inherit a 911 QC toolbox and a settings file that someone tuned to clear a backlog. One line reads `ADDR-05 = INFO`. You believe the ESN errors are gone because someone fixed them. In fact, someone demoted them. A malformed ESN routes a call to the wrong agency, and the report is clean.

## The rule this tool keeps

A severity override can raise a check, but it can never lower an ERROR. The effective settings report prints what each override actually did, including the overrides that had no effect.

## Decisions taken

- **MSAG checks are an optional import.** They run only when MSAG data is supplied as CSV. The tool needs no spreadsheet library, and no vendor-derived domain file ships.
- **A blank community field fails open.** When the city is unknown, the check reports instead of staying quiet.

## Before any public release

- Remove every local name, place and count from the comments and examples.
- Replace the geodatabase loader with a CSV and GeoJSON reader.
- Build one synthetic fixture.
- Write the self-test.

Open NG911 tools already exist, for example [kansasgis/NG911](https://github.com/kansasgis/NG911) and [dolin5/NG911-Scripts](https://github.com/dolin5/NG911-Scripts). The README will say what each one does well.
