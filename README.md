# ng911check

Run documented NG9-1-1 address and centerline checks on a CSV or GeoJSON file. Refuse to let a
severity line in a settings file lower a routing error, and refuse to report an MSAG match rate
that hides how well the two sources really agree.

Python 3.9 or newer. Standard library only. No GIS licence, no database, no network.

## The disaster

You inherit a 911 QC toolbox and a settings file that someone tuned to clear a backlog. One line
reads `ADDR-05 = INFO`. You believe the ESN errors are gone because someone fixed them. They are
not fixed. Someone demoted them. A malformed ESN routes a call to the wrong agency, and the report
is clean.

A second line in the same file reads `XLAYER-14 = ERROR`. It looks like a promotion. It does
nothing, because that check only ever reports INFO. Nobody learns that from the report either.

The MSAG hides its own failure in the same way. The tool reports "match rate 100 percent". The
rate counts an MSAG record as matched when a GIS range covers it. A GIS range that is far wider
than the MSAG record covers it. So the rate stays at 100 percent while the two sources disagree
about where the street starts and ends. It also says nothing about how old the MSAG file is.

This tool keeps one rule: a severity override can raise a finding, but it can never lower an
ERROR. The report prints what each override did on this run, including the overrides that did
nothing. For the MSAG it prints three numbers side by side: the coverage rate, the exact-tuple
rate and the age of the file.

The rule covers `[severity]` lines only. A `[checks]` line such as `ADDR-05 = off` switches a whole
check off, on purpose, and the tool does not refuse it. The report names every switched-off check
that can emit an ERROR and says that its findings are not in the report. A run with such a line can
exit 0 on data that holds errors, so read the header of the report.

This run uses the settings file `tuned.ini`, which holds the two lines above and `ADDR-03 = ERROR`.
The files are in the `demo` folder and are synthetic: four address points on one street.

```
$ python -m ng911check --addresses demo/addresses.csv --streets demo/streets.csv --settings demo/tuned.ini --units feet
ng911check report
--------------------------------------------------------------------
addresses: demo/addresses.csv (4 rows)
streets: demo/streets.csv (1 rows)
units: feet

Settings source: demo/tuned.ini
Thresholds/agency overrides:
  expected_agid            = agency.example.org
Severity overrides:
  ADDR-03      ERROR
  ADDR-05      INFO  (ERROR findings stay ERROR; the others become INFO)
  XLAYER-14    ERROR  (no effect: emits only INFO findings; cannot be escalated)
Override effects on this run:
  ADDR-03        ERROR: 0 raised or lowered, 0 held at ERROR, 0 INFO untouched, 0 already ERROR
  ADDR-05        INFO: 1 raised or lowered, 1 held at ERROR, 0 INFO untouched, 0 already INFO
  XLAYER-14      ERROR: 0 raised or lowered, 0 held at ERROR, 0 INFO untouched, 0 already ERROR

NOTICE: XLAYER-13 was skipped: it needs street geometry (a GeoJSON streets file).
NOTICE: XLAYER-15 was skipped: it needs modifier domains (--domains with premod, postmod or pretypesep rows).
NOTICE: XLAYER-18 was skipped: it needs street geometry (a GeoJSON streets file).
NOTICE: XLAYER-19 was skipped: it needs street geometry (a GeoJSON streets file).
NOTICE: XLAYER-17 was skipped: it needs street geometry (a GeoJSON streets file).
NOTICE: STREET-14 was skipped: it needs street geometry (a GeoJSON streets file).
NOTICE: STREET-11 ran in DEGRADED mode: no MSAG was loaded, so there was no authoritative road-name list to check against. Its findings here are a fallback heuristic: it flags a name only because that name shares no significant word with any OTHER name in the street layer, which false-positives on legitimately unique roads, and they are emitted at INFO to say so. A road being in the MSAG cannot help in this mode, because this run never opened the MSAG. For the real check, run with --msag.

Findings: 3 ERROR, 0 WARNING, 2 INFO
  ADDR-05            ERROR    1
  XLAYER-01          ERROR    2
  ADDR-05            INFO     1
  STREET-11          INFO     1
Notices: 7. Read them: a check that was skipped, or that left rows out, did not judge all of the data, and zero findings from it is not a clean result.

First 5 finding(s), most severe first:
  ERROR   ADDR-05    address row 2: ESN 'ABC' not a valid 1-5 digit ESN
  ERROR   XLAYER-01  address row 2: ESN ABC != covering side ESN(s) ['100'] (SEG 1 Left)
  ERROR   XLAYER-01  address row 4: ESN 200 != covering side ESN(s) ['100'] (SEG 1 Left)
  INFO    ADDR-05    address row 3: STATUS 'RETIRED' not in domain (expected ACTIVE)
  INFO    STREET-11  street row 1: name 'ELM ST' unmatched in degraded fuzzy check (no master list)
$ echo $?
1
```

The invalid ESN is still an ERROR and the run exits 1. The retired point became INFO, as asked.
The `XLAYER-14` line is marked as having no effect before the run starts. Pass `--agency agency.example.org`
in place of `--settings demo/tuned.ini` and the same data gives `3 ERROR, 1 WARNING, 1 INFO`. With neither
flag the run exits 2, because no agency is named.

## What you get

```
$ python -m ng911check --self-test
ng911check self-test: temporary files only, no network, no ArcGIS, no database
--------------------------------------------------------------------
...
PASS  xlayer-10 flags six name pairs that do not agree
...
PASS  reconcile reports 100 percent coverage and 0 percent exact when the GIS run is wider than the MSAG record  <-- pinned defect
...
PASS  xlayer-16 shows a perfect match rate beside a 0 percent exact-tuple rate  <-- pinned defect
...
PASS  xlayer-16 warns that a 100 percent rate over no eligible record compared nothing  <-- pinned defect
...
PASS  an override can never lower an ERROR  <-- pinned defect
...
PASS  a settings line ADDR-05 = INFO lowers the WARNING and leaves the invalid-ESN ERROR  <-- pinned defect
...
PASS  the held ERROR still makes the run exit 1  <-- pinned defect
...
PASS  a prefix --ap of --apply is REFUSED by the parser and writes nothing  <-- pinned defect
...
PASS  --out without --apply says what it would write and writes nothing  <-- pinned defect
...
PASS  a clean address file given alone exits 0 and says XLAYER-04 was skipped  <-- pinned defect
...
PASS  a header-only CSV exits 2 instead of passing as clean  <-- pinned defect
...
PASS  a GeoJSON number in a text column is read as text and the run gives a verdict, not exit 70  <-- pinned defect
...
PASS  an unexpected exception exits 70, never the 1 that means a finding  <-- pinned defect
...
PASS  --out onto a polygon file named in the settings is refused and the file is untouched  <-- pinned defect
...
PASS  a four or five digit MSAG ESN is compared with the GIS, not dropped from the rate  <-- pinned defect
...
PASS  an ignored name ELM skips ELM ST and N ELM AVE, never ELMWOOD DR  <-- pinned defect
...
PASS  xlayer-18 needs the gap to be more than the margin, not equal to it  <-- pinned defect
...
PASS  xlayer-19 ignores a nearer centerline that has no address range  <-- pinned defect
...
PASS  xlayer-17 leaves out a point whose nearest spot is the end of the line  <-- pinned defect
...
PASS  street-14 skips a closed loop, which meets its feeder head-to-head whichever way it was drawn  <-- pinned defect
...
PASS  a GeoJSON run reports STREET-14, XLAYER-17, XLAYER-18 and XLAYER-19 on the rows that hold the defects
...
PASS  a correct address on a street whose segments share SEGMENT_ID '' is not flagged  <-- pinned defect
...
PASS  an address file with no X and Y columns beside a street layer exits 2 and prints no report, not a clean pass  <-- pinned defect
...
PASS  an MSAG config error is exit 2 and reads: quoted.json: max_source_age_days must be a whole number of days, or null  <-- pinned defect
...
PASS  a point inside a polygon with a null key is reported as its own finding, not as a mismatch  <-- pinned defect
...
PASS  to_csv_text prefixes one apostrophe to the nguid column when it starts with tab  <-- pinned defect
...
PASS  a CR inside a cell keeps its row whole on every Python version, because the row is written fully quoted  <-- pinned defect
...
PASS  a polygon layer that no address falls inside exits 2, prints no report and writes nothing  <-- pinned defect
...
PASS  a Site_NGUID that starts with = + - @ tab or CR reaches the findings file with one apostrophe in front  <-- pinned defect
...
PASS  a street layer that no address is near exits 2, prints no report and writes nothing  <-- pinned defect
...
PASS  an MSAG with a header-only file and so no eligible record exits 2, prints no report and writes nothing  <-- pinned defect
...
PASS  check() and raises() really do record a failure  <-- pinned defect
...
PASS  ADDR-05 declares exactly the columns it reads
...
PASS  the package folder holds Python files only, so no vendor domain file ships  <-- pinned defect
...
--------------------------------------------------------------------
1015 assertions, 0 failed
```

The full run prints all 1015 assertions. Each `...` line above is where the block is cut.
`python -m ng911check --self-test` exits 0 when every assertion passes and 1 when one fails.

| Host | Python | Assertions |
|---|---|---|
| Windows | 3.13.2 | 1015 assertions, 0 failed |
| Windows | 3.12.10 | 1015 assertions, 0 failed |
| Windows | 3.11.15 | 1015 assertions, 0 failed |
| Windows | 3.10.20 | 1015 assertions, 0 failed |
| Windows | 3.9.25 | 1015 assertions, 0 failed |
| Ubuntu | 3.12.3 | 1015 assertions, 0 failed |

The Windows 3.9, 3.10 and 3.11 rows run on uv-managed builds of CPython. The self-test also parses
every source file with `feature_version=(3, 9)`. A separate assertion walks the syntax tree and
fails on an f-string, because the parse alone accepts one. The Ubuntu row is 3.12.3 only.

The counts are equal on every host because the self-test never branches on the platform. It writes
its files to a temporary folder and removes the folder at the end.

`coverage run --branch -m ng911check --self-test` (coverage 7.16.1) reports 100 percent of 5298
statements and 1550 branches for the whole package, the test modules included. One line carries a
`pragma: no branch`. It is the loop in `Polyline.midpoint` in `geometry.py`. That loop never ends
normally, because its last segment always returns. Branch coverage cannot see that. The reader
refuses a line part with fewer than two positions, so only a `Polyline` built in code with a part of fewer than two vertices
can make `midpoint` return `None`. The production modules alone, without the
`st_*.py` test modules and `selftest.py`, also reach 100 percent of 3121 statements and 1484
branches.

## What already exists

Other open tools check NG9-1-1 data. Use them if one fits better.

- [kansasgis/NG911](https://github.com/kansasgis/NG911) is a full ArcGIS toolbox from the Kansas
  NG911 project. It validates, converts, adjusts and compares data, and it has MSAG tools and
  submission tools. It needs ArcGIS Desktop 10.3 or later, or ArcGIS Pro. GitHub lists no licence for it. Its domain tables are the model for a state programme. This tool has no such
  tables and does not convert or submit anything.
- [dolin5/NG911-Scripts](https://github.com/dolin5/NG911-Scripts) is a small set of ArcPy scripts
  under the MIT licence. They find overlapping road ranges, list MSAG and centerline differences
  and sync MSAG with structures. Its README says the MSAG script "currently does not factor in ESN".
  The repository was last pushed in 2017.
- [dolin5/gallatin-ng911-checker](https://github.com/dolin5/gallatin-ng911-checker) is a TypeScript
  web app built on the ArcGIS API for JavaScript 4.11 type definitions, by the same author. It was last
  pushed on 2022-12-11. It has no description and no licence, and its README is the text of a webpack
  sample, so I cannot say which checks it runs. I did not read its source.
- [Nsokol44/ng911-spatial-qa](https://github.com/Nsokol44/ng911-spatial-qa) runs five spatial
  checks on site-address points against centerlines: name agreement, range parity, distance,
  uniqueness and consistency across a county line. It is under the MIT licence. It uses a 45 m
  search window around each point, which this tool does not.
- [A-Charvin/Fishbone-QA-911](https://github.com/A-Charvin/Fishbone-QA-911) is an ArcGIS Pro tool
  that draws a line from each address point to its road segment, so a person sees the mismatches
  on a map. Its description says it validates address points against road segment address ranges.
  It needs ArcGIS Pro, and GitHub lists no licence for it. It is the closest tool to XLAYER-18 that I
  found, and the map view is something this tool does not have.
- [A-Charvin/Parity-QA-911](https://github.com/A-Charvin/Parity-QA-911) derives and validates the
  left and right address parity of a centerline. It is under the MIT licence and needs ArcGIS Pro.
- Four more repositories came up for `ng911`: eneemann/NG911 (scripts to help with and build NG911
  data, no licence listed), geohippie/NG911 (scripts and files for NG911, no licence listed),
  Washington-County-GIS/NG911 (Arcade attribute rules and other scripts, GPL-3.0) and
  northrivergeo/tn_ng911_database (a Tennessee 911 database for QGIS and PostGIS, GPL-2.0). I read
  only their descriptions.
- The NENA GIS data model templates at
  [NENA911/NG911GISDataModel](https://github.com/NENA911/NG911GISDataModel) define the schema that
  most of these tools check against.

What this tool adds is small. It runs without ArcGIS. It keeps the severity rule above and prints
the effect of every override. It reports the exact-tuple rate and the file age beside the MSAG
match rate. It generates its own check catalog from the code and fails when the two disagree. It
does not replace a state submission tool, and it does not edit your data.

A search of GitHub with `gh search repos` on 2026-10-30 found the repositories above. The query
`ng911check` found only this one. The queries `ng911` and `rangefit` returned the NG9-1-1 repositories
named here, other repositories about call handling, a pentest framework and a capstone project, and four
unrelated fitness projects. The queries `ng911 qa`, `ng911 spatial`, `centerline address range`,
`street centerline direction`, `geocode centerline`, `gallatin ng911 checker`, `ng911 address range`
and `ng911 address point qa` returned nothing, although the Nsokol44, Fishbone and Parity repositories
exist (I confirmed each by name). A multi-word search therefore proves little. I read only the
repository descriptions for Fishbone-QA-911 and Parity-QA-911, not their code. I cannot say whether
either one checks the order of numbers along a street, or the direction of a line.

## Quick start

```
git clone https://github.com/uhsear/ng911check.git
cd ng911check
python -m ng911check --self-test
python -m ng911check --addresses demo/addresses.csv --streets demo/streets.csv --settings demo/agency.ini --units feet
```

The `demo` folder holds the synthetic files that every quoted run in this file uses.

It also installs as a package, and it still pulls nothing in: `pip install .` (or `pipx install .`)
puts a `ng911check` command on the path that runs the same command line as `python -m ng911check`,
with the same exit codes. `pyproject.toml` needs setuptools 77 or newer. The self-test runs from
the installed package too, so `ng911check --self-test` is a check of the wheel and not only of the
checkout.

The agency is required. Put `expected_agid = your.agency.domain` under `[agency]` in the settings
file, or pass `--agency`. The tool refuses to run without it, because a default agency would make
every other agency's NGUIDs fail.

## Usage

Nothing is written unless you give `--out FILE` and `--apply` together.

```
python -m ng911check --addresses a.csv --streets s.geojson --settings agency.ini
python -m ng911check --addresses a.csv --settings agency.ini --out found.csv
python -m ng911check --addresses a.csv --settings agency.ini --out found.csv --apply
python -m ng911check --addresses a.geojson --streets s.geojson --settings agency.ini --msag msag.csv
python -m ng911check --catalog
python -m ng911check --catalog-check README.md
```

| Flag | Default | What it does |
|---|---|---|
| `--addresses FILE` | none | Address points, `.csv` or `.geojson`. |
| `--streets FILE` | none | Centerlines, `.csv` or `.geojson`. A run needs one of the two layers. A check that compares the two layers is skipped, with a notice, when one is missing. |
| `--settings INI` | none | The calibration file. See Settings. |
| `--agency DOMAIN` | none | The agency domain NGUIDs must end in. It replaces the settings file value. |
| `--units` | `degrees` | Units of every coordinate: `degrees`, `feet` or `meters`. |
| `--x-field`, `--y-field` | `X`, `Y` | The coordinate columns of a CSV layer. |
| `--rename LAYER:ACTUAL=CANONICAL` | none | Read column ACTUAL of the layer as CANONICAL. Repeat the flag as needed. |
| `--domains CSV` | none | More street types, directions and modifier values: `domain,full,abbrev`. |
| `--msag CSV` | none | The MSAG as a CSV. It turns on XLAYER-16, which also needs `--streets`: without a street file it is skipped with a notice. |
| `--msag-config JSON` | none | The MSAG column map, header row, floors and a pinned SHA-256. |
| `--msag-exceptions CSV` | none | MSAG records to leave out of the match rate. See The MSAG numbers. |
| `--street-names CSV` | none | An authoritative street-name list for STREET-11. It needs `--msag` or `--msag-config`; alone it is refused with exit 2. |
| `--optional` | off | Also run the checks that are off by default. |
| `--show N` | `20` | How many findings to print. A whole number of zero or more; a negative value exits 64. |
| `--format` | `csv` | Format of the `--out` file: `csv` or `json`. |
| `--out FILE` | none | Where to write every finding. Nothing is written without `--apply`. |
| `--apply` | off | Write the `--out` file. It needs `--out`. |
| `--fail-on LEVEL` | `error` | Which finding makes the run exit 1: `error`, `warning` or `any`. It can only widen what fails; no value idles a finding or lowers a severity. A non-default value is printed in the report. |
| `--catalog` | off | Print the check catalog and exit. |
| `--catalog-check FILE` | none | Exit 1 when the catalog block in FILE differs from the code. |
| `--self-test` | off | Run the offline assertions and exit. |
| `--version` | off | Print the version and exit. |

Every flag must be spelled in full. The parser sets `allow_abbrev=False`. A prefix such as `--ap`
is refused with exit 64 instead of being read as `--apply`, and the self-test pins that for
`--ap`, `--app`, `--appl` and for `--ou`. Nothing else may write. `--out` is refused when it names
any file the run reads: a file named on the command line, a polygon file named in the settings, or a
file named in the MSAG config. It is also refused when `OUT.tmp`, the file `--apply` writes first, is
one of those files. The guard compares file identity, so a hard link to an input is caught. The refused
run leaves that file as it was.

Exit codes: 0 no ERROR finding, 1 at least one ERROR after the overrides (or a finding at the level
`--fail-on` names), 2 an input or settings file was refused or could not be read, or a polygon layer
holds no address point, 64 usage error, 70 an unexpected crash. A crash never reads as a finding.

`--fail-on error` is the default and is the rule above. `--fail-on warning` and `--fail-on any` make
the run exit 1 on a WARNING, or on any finding at all, for a batch job that should stop before a
warning becomes a defect. A policy can only widen what exits 1: no value idles a finding or lowers a
severity, so nothing here can turn an ERROR into exit 0. A non-default policy is printed in the
report, under the inputs, as `Exit policy: exit 1 on any WARNING or ERROR (--fail-on warning).`

In the runs below, `ARGS` stands for `--addresses demo/addresses.csv --streets demo/streets.csv --settings demo/agency.ini --units feet`.
A line that holds only `...` is where this file cuts the report.

```
$ python -m ng911check $ARGS --out found.csv
...
Would write the findings to found.csv. Add --apply to write them.
$ ls found.csv
ls: cannot access 'found.csv': No such file or directory
$ python -m ng911check $ARGS --out found.csv --ap
ng911check: error: unrecognized arguments: --ap
$ echo $?
64
$ python -m ng911check $ARGS --out found.csv --apply
...
Wrote found.csv.
$ head -2 found.csv
check_id,check_name,family,severity,layer,row,nguid,description,x,y
ADDR-05,Address domain/bounds violation,address_attr,ERROR,address,2,ADR103@agency.example.org,ESN 'ABC' not a valid 1-5 digit ESN,1010.000,1010.000
$ python -m ng911check --addresses demo/addresses.csv --settings demo/agency.ini --out demo/addresses.csv --apply
ng911check: error: --out would overwrite an input file
$ echo $?
64
```

On a refused run the parser also prints its usage block. This file cuts that block.

A text cell of the `--out` CSV that starts with `=`, `+`, `-`, `@`, a tab or a carriage return gets
one apostrophe in front, so a spreadsheet does not read an input value as a formula. The guard
covers `check_id`, `check_name`, `family`, `severity`, `layer`, `nguid` and `description`. The
`row`, `x` and `y` columns are numbers and are never prefixed, so a western longitude such as
`-30.4995000` stays a number. A row that holds a carriage return is written with every cell
quoted. The `csv` module of Python 3.9 and 3.10 leaves a bare carriage return unquoted when the
line end is LF, and that would split the row in two. The `--format json` file is not guarded, because
a spreadsheet does not open JSON. This package never reads its own findings file back, so it has
no code that strips the apostrophe. The self-test fails if `reader.py`, `msag.py`, `crosswalks.py` or `settings.py` imports the
report module with an `import` or `from ... import` statement. A call to `importlib.import_module` or `__import__` is not checked.

## Inputs

A CSV layer has a header row. The tool reads the columns it knows by name and ignores the rest.
Use `--rename` to map your column names. The column lists are `ADDRESS_COLUMNS` and `STREET_COLUMNS`
in `reader.py`. A column the file lacks is named in a notice at the top of the report. A CSV can
carry address points through two coordinate columns. A CSV street layer has no line geometry.

A GeoJSON layer must be a `FeatureCollection`. Addresses take `Point`. Streets take `LineString` or
`MultiLineString`. Response areas take `Polygon` or `MultiPolygon`. Coordinates are longitude then
latitude. RFC 7946 section 3.1.1 says: "The first two elements are longitude and latitude, or
easting and northing, precisely in that order". Streets with geometry turn on XLAYER-13, XLAYER-17, XLAYER-18, XLAYER-19 and STREET-14.
XLAYER-05 also needs `--optional` or `[checks] XLAYER-05 = on`.

A GeoJSON geometry must carry a string `type`. RFC 7946 makes it a required member, and an object
that held `coordinates` but no `type` used to read as "no geometry": a whole centerline disappeared,
and XLAYER-13/17/18/19 and STREET-14 then said the segment "has no line" while the file carried one.
A `MultiPolygon` must be a list of polygons, each a list of rings, and in a degrees run a polygon
vertex at 0, 0 is refused, as a street vertex is. `frame.forward` would place that vertex millions of
feet from the data, so one null-island vertex stretched the polygon into a wedge and every address in
the wedge counted as inside the area.

A GeoJSON property may be a string, a number or null. A number in a text column is read as the
text a CSV would hold, so `"COUNTY": 99999` reads as `99999`. A number too large for a float, such
as a 400-digit integer, is read as its digits instead of crashing the run. A list, an object or
`true` or `false` refuses the file with exit 2. A header-only CSV, or a `FeatureCollection` with no features, also
refuses the file with exit 2. An empty export would otherwise pass as clean.

Values are not stripped, because ADDR-07 exists to find leading and trailing spaces. A street range
that is not a whole number refuses the file. A house number must be a whole number: a JSON
`"Add_Number": 5.5` is not usable, so ADDR-08 reports it exactly as it reports the CSV text `5.5`,
and no check validates it as house number 5. Reading it as blank would make a broken range look
unused. A row is numbered by its position in the file, and findings quote that row number.

Degrees are converted to planar feet around the centre of the data. Over the few miles a county
spans the result is good to about half a percent against the WGS 84 ellipsoid. The self-test checks
this at 29 degrees north against the series for the length of a degree on the [Geographic coordinate
system](https://en.wikipedia.org/wiki/Geographic_coordinate_system) page. It is a plausibility
measure, not a survey measure. A layer in feet or meters is exact. Coordinates that cannot be
degrees are refused unless you pass `--units`. The reverse is a notice only: when every coordinate
in a feet or meters run fits longitude -180 to 180 and latitude -90 to 90, the report says the files
may be degrees. In a degrees run a position of 0, 0 counts as no position, because it is the usual
stand-in for a missing one, and it does not move the centre of the frame. A street vertex at 0, 0
refuses the file. A GeoJSON `crs` member is ignored. A layer in Web Mercator metres (EPSG:3857)
passed with `--units meters` inflates every distance by 1/cos(latitude), about 14 percent near 29
degrees north, because the scale factor of the [Mercator
projection](https://en.wikipedia.org/wiki/Mercator_projection) is the secant of the latitude. The
meter uses the international foot of exactly 0.3048 m ([NIST SP 811, appendix
B.8](https://www.nist.gov/pml/special-publication-811/nist-guide-si-appendix-b-conversion-factors/nist-guide-si-appendix-b8)).

## Settings

The settings file is an INI file. An unknown section, key or check id is an error, so a typo cannot
weaken a run. A key you leave out takes its built-in default.

| Section | Keys |
|---|---|
| `[thresholds]` | `min_address`, `max_address`, `max_range_gap`, `distance_tolerance_ft`, `sync_threshold`, and the five range fit keys in the Range fit section |
| `[agency]` | `expected_agid` (required), `strict_fqdn`, `expected_state`, `counties` |
| `[names]` | `ignored`: street names the name checks skip. A name matches whole words: `ELM` skips `ELM ST` and `N ELM AVE`, never `ELMWOOD DR`. |
| `[checks]` | `CHECK-ID = on` or `off` |
| `[severity]` | `CHECK-ID = ERROR`, `WARNING` or `INFO` |
| `[areas]` | `RA-xx = file.geojson|key_property[|fields[|sentinel]]` |

A `[checks]` line with `off` removes every finding of that check. The report prints the line, and for
a check that can emit an ERROR it adds `(can emit ERROR: its findings are NOT in this report)`. A line
that provably changes nothing - `on` for a check that is on by default, `off` for one that is off -
is printed with `(no effect: already on by default)`, so the dead lines of a tuned file are as
visible as the no-op `[severity]` ones.

The severity rule has three parts. An override may raise a WARNING to ERROR. An override never
lowers an ERROR record. An INFO metric line is left alone. The report prints, before the run, what
each line can do, and after the run, what each line did. The self-test pins this with the line
`ADDR-05 = INFO` over a file that holds an invalid ESN.

An `[areas]` line can also replace the address column that is compared and the sentinel value, and
both change every verdict. The report therefore prints the RESOLVED rule, not the line as written:
`RA-08        esn.geojson key=ESN fields=ZIP_CODE sentinel=0`. A field named twice in one line
(`RA-08 = esn.geojson|ESN|ESN,ESN`) is refused with exit 2, because the check emits one finding per
field occurrence and every finding, roll-up count and `--out` row would be doubled.

`RA-09` has a second class, a blank CITY inside a postal-city polygon. That class is a data-entry
backlog and not a misroute, so it is reported at INFO and answers to its own line, `RA-09-BLANK`.
A wrong CITY stays at ERROR.

Two rules keep a polygon layer from giving a false clean result.

- A polygon whose key is null, empty or only spaces cannot say what a point inside it should hold.
  A point inside it is reported once, as its own finding, at ERROR. The check name ends with
  `: polygon key is null`, and the description says which fields could not be checked. The stored
  value is not compared, so a blank value is not read as "consistent". The response-area roll-up
  lists these points under `(null key)`. Before this rule, a point inside a polygon with a null
  key was read as "inside no polygon". A filled ESN was reported as `point not inside any ESN
  area`, which names the wrong defect, and a blank ESN was not reported at all. A key that was
  empty or only spaces was reported before as a mismatch with a containing area named `''`.
- A polygon layer that no address point falls inside is refused with exit 2, and the run prints
  no report and writes nothing. With no hit, every point reads as "outside". A blank stored value
  cannot be contradicted there, so a layer in the wrong coordinate system, or the wrong layer, gave
  no response-area finding at all, so a run with no other ERROR exited 0. The refusal counts a point inside a null-keyed polygon, and a polygon
  keyed `0`, as a hit. An empty polygon layer, and an address file with no X and Y, are refused
  the same way. There is no flag to switch the refusal off.
- A street layer that holds geometry, with no address point inside its bounding box widened by one
  mile (5,280 ft), is refused the same way, with exit 2, no report and no file written. Without it
  XLAYER-17, XLAYER-18 and XLAYER-19 judged nothing for a street file in another coordinate
  system, and the run exited 0. The same refusal holds when addresses exist and none has a
  position, for example a CSV with no X and Y columns or a GeoJSON file whose geometries are all
  null, because the three checks then judged no address. A street file in CSV form has no geometry
  and is not tested.
- An MSAG with no eligible record, because the file has no data rows or every record is excepted,
  is refused with exit 2, no report and no file written. Its 100 percent rate compared nothing.

## The MSAG numbers

`--msag` turns on XLAYER-16. It reconciles the MSAG against the GIS ranges in both directions. It
reports three numbers together:

- **Match rate.** The share of eligible MSAG records that GIS ranges cover. Coverage is the union
  of GIS ranges, and each side keeps its own parity.
- **Exact-tuple rate.** The share of eligible MSAG records whose extent equals one whole GIS run for
  the same community, street, parity and ESN. A run merges GIS ranges of one parity that overlap or
  sit one step apart. A B record must equal one even run and one odd run.
- **Source age.** The days since the MSAG file changed. `max_source_age_days` in the config turns an
  old file into a WARNING.

Three kinds of MSAG record are left out of both rates and out of the findings, with or without an
exceptions file: a record on ESN 999, a record whose range is an explicit 0-0, and a record whose
ESN is all digits and longer than five digits. The ESN-999 test compares the VALUE, so the sentinel
is still excepted when `esn_pad_width` pads it to `00999`. The report prints `N of M records excepted`. A four
or five digit ESN is compared, because ADDR-05 accepts one to five digits. The exceptions file
adds more records, through `--msag-exceptions`. Its header is
`kind,community,prefix,street,type,suffix,esn`. A `name` row leaves a street out on one ESN, or on
every ESN when `esn` is blank. A `permanent` row leaves one community, street and ESN out. The
street-name list of `--street-names` has the header `community,street_name`.

A record whose range a GIS side covers but whose ESN is blank is reported like a wrong ESN
(`MSAG ESN blank, GIS 100`), at WARNING. A blank ESN cannot route either, and leaving it quiet kept
the coverage rate at 100 percent while only the exact-tuple rate moved.

The `--msag-config` file is JSON. A key you leave out takes its default. An unknown key refuses the
file. So does a value of the wrong type, a `min_match_rate` outside 0 to 1, and a file that is not a
JSON object: exit 2, and the message names the file and the key.

| Key | Default | Meaning |
|---|---|---|
| `source_path` | none | The MSAG CSV. A relative path starts at the folder of the config file. Without it, pass `--msag`. |
| `header_row` | `0` | The 1-based header row. `0` finds it by its column names. |
| `field_map` | `PREFIX`, `STREET NAME`, `TYPE`, `SUFFIX`, `LOW`, `HIGH`, `COMMUNITY`, `SIDE`, `ESN` | Maps `prefix`, `street_name`, `type`, `suffix`, `low`, `high`, `community`, `parity` and `esn` to your column names. |
| `esn_pad_width` | `3` | ESNs are zero-padded to this width before they are compared. |
| `exceptions_path` | none | The exceptions CSV. |
| `names_path` | none | The street-name CSV. |
| `min_match_rate` | `0.98` | The floor, as a fraction. |
| `max_source_age_days` | none | An older MSAG file is a WARNING. Without it the age is only reported. |
| `source_hash` | none | A SHA-256 in any case. A file that no longer hashes to it refuses the run with exit 2. |

The report also prints a roll-up by street, so one thousand findings on forty streets read as forty
rows. Three more WARNINGS refuse to let a rate stand alone: no eligible record at all, a record
that fell into no bucket, and a file older than the limit.

```
$ python -m ng911check $ARGS --msag demo/msag.csv
...
MSAG reconciliation:
  MSAG match rate 66.67% (matched 2/3 eligible); NENA floor 98.00% -> BELOW FLOOR [unmatched: 0 range mismatch, 1 not in GIS, 0 gap-with-no-address]
  MSAG exact-tuple rate 33.33% (1/3 eligible equal one whole GIS run on community, street, parity, extent and ESN); coverage match rate 66.67%; 0 of 3 records excepted
  MSAG source is 0 day(s) old (no limit set)

MSAG roll-up by street (top 2 of 2):
  TESTVILLE            ELM ST                          1  (0 not in GIS, 1 not in MSAG, 0 range, 0 ESN)
  TESTVILLE            OAK AVE                         1  (1 not in GIS, 0 not in MSAG, 0 range, 0 ESN)
...
```

The floor of 98 percent is the default `min_match_rate`. Secondary sources, including a Montana
NG9-1-1 assessment, attribute a 98 percent synchronisation rate to NENA 71-501,
*Synchronizing GIS databases with MSAG and ALI*. I did not read the NENA text. The floor is a
setting you can change.

## Range fit

A geocoder finds an address by its number and the range of a segment. A map shows where the point
really is. When the two disagree, a responder who follows the number goes to the wrong block, and
no ESN or parity check says so, because the number, the parity and the ESN all agree with each
other. Four checks compare the number with the place. They need a GeoJSON street layer, because
they need the line.

| Check | Question |
|---|---|
| XLAYER-18 | The segment whose range covers the number is far from the point, and another segment of the same street is much nearer. The point fronts a block whose range excludes its number. |
| XLAYER-17 | Along one side of one line, the numbers should rise or fall. Is this number out of order with its neighbours? |
| XLAYER-19 | The point is much nearer a ranged street of another name than its own street. |
| STREET-14 | Two segments of one street name both end, or both start, at one point. One of them is drawn against the street. |

Each of the four reads positions only. None edits a point or a line.

An address with no position, and a street segment that has an address range but no line, drop out of
these checks. The run prints a NOTICE with the counts, for example `XLAYER-17, XLAYER-18 and XLAYER-19 left
out 1 of 2 addresses that have no position`, and a `Notices:` line under the finding counts. When a
street layer holds geometry and no address has a position, the run is refused with exit 2 instead (see
the refusals above). A run without `--addresses` skips
XLAYER-17, XLAYER-18 and XLAYER-19, and a street file in CSV form skips all four. The exit code does not
change when only some addresses lack a position, when `--addresses` is missing, or for a CSV street file,
so read the notices before you trust a zero.

**XLAYER-18.** The covering segment is the same-name segment whose range and parity contain the
number. The nearest other segment is the nearest same-name segment that does not. The check reports
a point when the covering segment is more than `wb_min_margin_ft` farther away and at least
`wb_min_ratio` times as far. A number that no segment covers is XLAYER-02, not this check.

**XLAYER-17.** Each point joins its nearest same-name line and the left or right side of it. A point
whose nearest spot is a line end has no side and is left out, and so is a point within half a foot of the
line, which is on neither side. Points that share a number, a complex,
count as one position, at the mean of their distances along the line. A side needs four positions.
The direction of the numbering comes from the numbers: a Spearman rank correlation of 0.5 or more,
or -0.5 or less, between the order along the line and the order of the numbers. A side without a
clear direction is skipped, so a road numbered against the way it was drawn still works. A position
is out of sequence when its two neighbours agree with the direction and its number lies outside
them. The first and the last position have one neighbour and are never reported. The check keeps a
position that sits at least `oo_min_displacement_ft` from where its number belongs. That place is
half way between the two other positions whose numbers surround it, or the nearest end. Set the key
to `0` to see every swap. In the self-test, two houses that swapped side by side sit 130 and 140 ft
from their places, so they stay under the default.

**XLAYER-19.** The check takes the nearest centerline that has an address range, of any name. A
centerline without a range, such as a private drive, is skipped, and so is a name in `[names]
ignored`. The check reports a point when its own street is more than `nm_min_margin_ft` farther away
and at least `nm_min_ratio` times as far.

**STREET-14.** Every segment has a first and a last vertex. Two segments of one name that share an end
point, within a foot on both axes, are a candidate when both ends are last vertices or both are
first vertices. Three kinds of pair are skipped because nothing in them is wrong. First, a segment
with no address range on either side. Second, a closed loop, whose first and last vertex are one
point, so its feeder is head-to-head or tail-to-tail with it whichever way it was drawn. Third, a
pair whose ranges overlap, which is a divided road. A pair that meets at both ends is reported once.

| Key under `[thresholds]` | Default | Meaning |
|---|---|---|
| `oo_min_displacement_ft` | `150` | XLAYER-17 keeps a point at least this far from where its number belongs. `0` or more. |
| `wb_min_margin_ft` | `150` | XLAYER-18: the covering segment must be more than this much farther. `0` or more. |
| `wb_min_ratio` | `2.0` | XLAYER-18: and at least this many times as far. `1.0` or more. |
| `nm_min_margin_ft` | `5000` | XLAYER-19: the own street must be more than this much farther. `0` or more. |
| `nm_min_ratio` | `2.0` | XLAYER-19: and at least this many times as far. `1.0` or more. |

The defaults are starting values that I chose. No standard defines them, and I did not calibrate
them against a real county layer. Tune them on your data. The tool refuses a value below the
minimum in the table, because a negative margin or a ratio under 1 reports a point that sits on its
own street.

This run uses two synthetic files in the `demo` folder: eight address points and four segments, in
feet. One segment is drawn against its neighbour. One address number is out of order, one point
fronts the wrong block, and one point is far from its street.

```
$ python -m ng911check --addresses demo/fit_addresses.geojson --streets demo/fit_streets.geojson --settings demo/agency.ini --units feet --show 4
...
Findings: 0 ERROR, 4 WARNING, 4 INFO
  STREET-14          WARNING  1
  XLAYER-17          WARNING  1
  XLAYER-18          WARNING  1
  XLAYER-19          WARNING  1
  STREET-11          INFO     1
  XLAYER-14          INFO     3
Notices: 2. Read them: a check that was skipped, or that left rows out, did not judge all of the data, and zero findings from it is not a clean result.

First 4 finding(s), most severe first:
  WARNING STREET-14  street row 1: SEG 1 and SEG 3 of 'ELM ST' meet head-to-head, so one is drawn against the street
  WARNING XLAYER-17  address row 3: house number 121 is out of sequence on the left side of SEG 1: its neighbours are 103 and 107, and it sits 300 ft from where its number belongs
  WARNING XLAYER-18  address row 7: house number 105 is 800 ft from SEG 1, whose range covers it, and 100 ft from SEG 2, whose range does not
  WARNING XLAYER-19  address row 8: house number 115 on 'ELM ST' is 18100 ft from its street (SEG 2) and 1000 ft from 'OAK AVE' (SEG 4)
  ... 4 more. Write them all with --out FILE --apply.
$ echo $?
0
```

All four are WARNING findings, so the run exits 0. A `[severity]` line may raise one to ERROR.

What the self-test exercises. It builds each case as rows and lines in feet. The level lines of the
first cases start at the origin, so a second group uses a due-north line, a sloped line, a bent line and
lines far from the origin, where a sign slip in the line arithmetic changes the verdict. It pins the
boundary of each of the five settings keys: a gap equal to the margin is not reported, a ratio exactly at
the limit is reported, and a displacement exactly at the limit is kept. It also pins the fixed limits in
`rangefit.py`: the one-foot join tolerance of STREET-14 along and across the line, a loop that closes at
exactly a foot, ranges that touch at one number, the rank correlation of 0.5, and the half-foot margin
from a line end and from the line itself. It runs the four checks end to end from two GeoJSON files
through the reader and the command line. It also runs a street file with no geometry, which skips all
four checks with a notice, an address file with no positions (refused with exit 2), and a street with a null geometry. The
checks have no network path, so no local `http.server` stub applies.

No mutation-testing script ships with the package. The evidence for the self-test is its branch coverage
and its labels marked `pinned defect`, not a mutation score.

## The check catalog

The catalog below is generated from the registry. `python -m ng911check --catalog-check README.md`
exits 1 when this block differs from the code. The self-test also runs every check over the
fixtures. It fails when a check reads a column it did not declare, emits a severity it did not
declare, or declares a column or severity that the fixtures never show. The `Needs` column lists
what a check needs from the run. A check that does not get it is skipped, and the report says so.

<!-- catalog:start -->
| Check | Target | Emits | On by default | Needs | What a finding means |
|---|---|---|---|---|---|
| ADDR-01 | address | ERROR | yes | - | Flag an address point that has an empty required field. |
| ADDR-02 | address | ERROR | yes | - | Flag two address points that share one full address in one city. |
| ADDR-03 | address | WARNING | yes | - | Flag an ADDRESS text that is not the number, name, building and unit joined. |
| ADDR-04 | address | WARNING | yes | - | Flag a HOUSE_NU that does not repeat Add_Number. |
| ADDR-05 | address | WARNING, ERROR | yes | - | Flag an address STATUS, ESN, ZIP_CODE, number, PREFIX or TYPE outside its domain or bounds. |
| ADDR-06 | address | ERROR | yes | - | Flag a Site_NGUID that is not localid@authority for the expected agency. |
| ADDR-07 | both | WARNING | yes | - | Flag surrounding spaces, prohibited characters or the text NULL in an address or street field. |
| ADDR-08 | address | WARNING | yes | - | Flag an address point with no usable house number or no street name. |
| RA-01 | address | ERROR | no | area RA-01 | Flag an address whose response-area field disagrees with the area it sits in. |
| RA-02 | address | ERROR | no | area RA-02 | Flag an address whose second response-area field disagrees with its area. |
| RA-03 | address | ERROR | no | area RA-03 | Flag an address whose zone field disagrees with the zone it sits in. |
| RA-08 | address | ERROR | no | area RA-08 | Flag an address whose ESN disagrees with the ESN polygon it sits in. |
| RA-09 | address | ERROR, INFO | no | area RA-09 | Flag an address whose CITY disagrees with the postal city it sits in. |
| RA-10 | address | ERROR | no | area RA-10 | Flag an address whose ZIP_CODE disagrees with the ZIP polygon it sits in. |
| STREET-01 | street | ERROR | yes | - | Flag a street side whose range ends mix parity, or two sides that share one parity. |
| STREET-02 | street | ERROR, WARNING | yes | - | Flag a declared side parity that the range does not support. |
| STREET-03 | street | ERROR, WARNING | yes | - | Flag a negative range end, a half-zero range or two sides that run in opposite directions. |
| STREET-04 | street | ERROR | yes | - | Flag two segments of one street whose address ranges overlap on one parity. |
| STREET-05 | street | ERROR | yes | - | Flag a SEGMENT_ID or RCL_NGUID that appears on more than one segment. |
| STREET-06 | street | WARNING | yes | - | Flag two segments of one street that carry an identical range tuple. |
| STREET-07 | street | ERROR | yes | - | Flag a segment that has an address range and no street name. |
| STREET-08 | street | ERROR, WARNING | yes | - | Flag an RCL_NGUID that is not RCL plus SEGMENT_ID at the expected agency. |
| STREET-09 | street | ERROR, WARNING | yes | - | Flag a parity or ONEWAY value outside its domain. |
| STREET-10 | street | ERROR | yes | - | Flag a street segment that has an empty required field. |
| STREET-11 | street | WARNING, INFO | yes | - | Flag a street name that is not in the authoritative list, or that shares no word with any other name. |
| STREET-12 | street | WARNING | yes | - | Flag a gap in the address numbering between two segments of one street. |
| STREET-13 | street | WARNING | yes | - | Flag an ESN or ZIP change between two range-adjacent segments of one street side. |
| STREET-14 | street | WARNING | yes | geometry | Flag two same-name centerlines that meet head-to-head or tail-to-tail, so one is drawn against the street. |
| XLAYER-01 | both | ERROR | yes | - | Flag an address ESN that differs from the ESN of the street side that covers it. |
| XLAYER-02 | both | ERROR | yes | - | Flag an address number that lies outside every range of its street. |
| XLAYER-03 | address | WARNING | yes | - | Flag an address whose odd or even number contradicts the declared parity of its covering side. |
| XLAYER-04 | both | ERROR | yes | streets | Flag an address whose street name no centerline carries. |
| XLAYER-04b | both | WARNING, INFO | yes | - | Flag a stored COMPARE value that differs from the name rebuilt from its parts. |
| XLAYER-05 | address | WARNING, INFO | no | geometry | Flag an address far from the nearest centerline that carries its street name. |
| XLAYER-06 | address | WARNING | no | - | Flag an address city or ZIP that differs from the covering street side. |
| XLAYER-07 | both | ERROR | yes | - | Flag an NGUID that appears on more than one row of a layer. |
| XLAYER-08 | both | ERROR, WARNING | yes | - | Flag a blank DiscrpAgID, or one that is not the expected agency. |
| XLAYER-09 | both | ERROR, WARNING, INFO | yes | - | Flag a state, country or county that is blank, invalid or outside the configured set. |
| XLAYER-10 | both | WARNING | yes | - | Flag a PREFIX, TYPE or street name that disagrees with its St_ field. |
| XLAYER-11 | both | INFO, WARNING | no | - | Report the share of address points that pass the ESN, range, parity and name checks. |
| XLAYER-12 | both | ERROR | yes | - | Flag an address that two segments of one street both cover. |
| XLAYER-13 | address | WARNING | yes | geometry | Flag an address on the opposite side of the centerline from the side its number implies. |
| XLAYER-14 | street | INFO | yes | addresses | Report a street segment that has an address range but no address point inside it. |
| XLAYER-15 | both | WARNING | yes | modifier domains | Flag a modifier or separator value that is not in the supplied domain. |
| XLAYER-16 | both | WARNING, ERROR, INFO | no | msag, streets | Compare the MSAG with the GIS ranges and report coverage, exact-tuple rate, differences and file age. |
| XLAYER-17 | address | WARNING | yes | addresses, geometry | Flag an address whose house number is out of order with its neighbours along its street. |
| XLAYER-18 | address | WARNING | yes | addresses, geometry | Flag an address that sits clearly nearer a block of its street whose range excludes its number. |
| XLAYER-19 | address | WARNING | yes | addresses, geometry | Flag an address that sits clearly nearer a ranged street of another name than its own street. |
<!-- catalog:end -->

## What was verified against documentation

This package relies on no Esri, SQL Server, PROJ, FEMA or Census behaviour. It never imports
`arcpy`. It relies on these published facts.

- [USPS Publication 28](https://pe.usps.com/text/pub28/welcome.htm):
  [section 233](https://pe.usps.com/text/pub28/28c2_014.htm) lists the directionals, and
  [Appendix C1](https://pe.usps.com/text/pub28/28apc_002.htm) lists the street suffix abbreviations.
  I confirmed on 2026-10-30 that both pages exist with those titles. I did not compare the tables line
  by line. The built-in tables come from those two. No vendor or agency domain file ships.
  The self-test fails when the package folder holds any file that is not Python. The `__pycache__` folder that Python makes is not inspected.
- RFC 7946 section 3.1.1, quoted above, for the coordinate order. Section 3.1.4 says a `LineString` is
  "an array of two or more positions". The RFC attaches no meaning to the direction of a line, so
  "first vertex" in STREET-14 means the first position in the array, which is the order of drawing.
- The Spearman rank correlation formula `1 - 6 * sum(d^2) / (n * (n^2 - 1))`, from the
  [Spearman's rank correlation coefficient](https://en.wikipedia.org/wiki/Spearman%27s_rank_correlation_coefficient)
  page. The page says it holds only when all ranks are distinct. XLAYER-17 merges points that share a
  number before it ranks, so the ranks are distinct. The self-test pins -1, 0, 0.5 and 0.8.
- NIST SP 811, appendix B.8, for the foot.
- The IUGG mean radius R1 of 6371008.7714 m, rounded in the code to 6371008.8 m, from the table on the
  [Earth radius](https://en.wikipedia.org/wiki/Earth_radius) page.

- [OWASP, CSV Injection](https://owasp.org/www-community/attacks/CSV_Injection) lists the
  characters that start a formula: `=`, `+`, `-`, `@`, tab (0x09) and carriage return (0x0D). It
  also lists line feed (0x0A) and the full-width forms of `=`, `+`, `-` and `@`, and it advises a
  single quote in front of the cell. I read that page on 2026-11-11 (the address answers with a
  redirect to community.owasp.org, which returned 200). The tool guards the six characters named
  first and the single quote only. It does not guard the line feed or the full-width forms, and I
  did not run a spreadsheet. The self-test pins the prefix on every text column and on every one
  of the six characters. The older address `/www-community/vulnerabilities/CSV_Injection` returned
  404 on the same day.
- I observed, and did not read in the Python documentation, that the `csv` writer of Python 3.9.25
  and 3.10.20 leaves a carriage return inside a cell unquoted when `lineterminator` is a line feed,
  and that 3.11.15, 3.12 and 3.13 quote it. The self-test pins the result on every host in the table.

Not verified: that an address range runs with the drawing direction of the line, FROM at the first
vertex. STREET-14 assumes it, and I did not read a standard that says so. Where a road is numbered in
opposite directions on purpose, a finding is wrong and `[checks] STREET-14 = off` removes it.

Not verified: the exact grammar of an NGUID. The tool checks the form `localid@authority`, a
localid of letters, digits, `_`, `.` and `-`, and an authority that equals the expected agency. I
could not read NENA-STA-006 or NENA-STA-010. The rule is the one the original toolbox used. Treat
ADDR-06, STREET-08 and XLAYER-08 as local policy until you check them against your standard. The
ESN rule in ADDR-05, one to five digits and not zero, is also a local choice.

## Limits

- The tool has not run on a real county layer. Every number in this file comes from synthetic data.
- The street-name and ESN domains are what the checks need, not a copy of a state schema.
- The range fit thresholds are untested against real data. Their defaults are my starting values.
- XLAYER-17 orders points on one segment at a time. It does not follow a street across segments, so a
  side with fewer than four numbers on one segment is skipped. It does not borrow the numbers of a
  joined segment. It reports every point of a complex that is out of sequence, where one unit of the
  complex might be fine.
- XLAYER-18 and XLAYER-19 judge each point alone. They do not hold back a complex unless every unit
  fails.
- XLAYER-19 scans every ranged segment for each point that is farther than the margin from its own
  street. With the default 5,000 ft margin that is few points. With a margin of 0 on a large layer it
  is slow, and a grid index would fix that. The code carries a `shortcut:` comment.
- The early skip in XLAYER-19 (a point within the margin of its own street) and the `d_own <=
  margin` boundary of that skip cannot change a verdict, so no assertion can pin them.
- STREET-14 compares a segment's first and last vertex only. For a `MultiLineString` those are the
  first vertex of the first part and the last vertex of the last part. It joins ends within a foot on
  each axis, a square and not a circle. It does not tell two roads of one name in different places
  apart. It treats a pair with overlapping ranges as a divided road, which hides a reversed segment
  that also overlaps its neighbour. STREET-04 reports the overlap.
- Points on a polygon edge, and points in two overlapping polygons, take the first polygon in the
  file. Both are topology defects, which this package does not judge.
- STREET-11 without an MSAG is a heuristic and reports at INFO. An MSAG turns on the real check. A
  `--street-names` list is read only beside `--msag` or `--msag-config`; alone it is refused with exit 2.
- The checks that need a street geometry (XLAYER-05, XLAYER-13, XLAYER-17, XLAYER-18, XLAYER-19,
  STREET-14) need a GeoJSON street layer.
- The saint names that XLAYER-10 expands (`ST BENEDICT` to `SAINT BENEDICT`) are a closed list in
  the code. Add a name there for a new saint road.
- A match rate below the floor is only an INFO line (`BELOW FLOOR`), and an INFO metric line cannot be escalated. A run with a 33 percent MSAG match rate and no GIS-side ERROR exits 0. The exit code never reflects `min_match_rate`.
- The refusal for an MSAG with no eligible record applies to a run that loads an MSAG. The `XLAYER-16` check itself, called from code, still reports a 100 percent rate over 0 records with a WARNING.
- The street-layer refusal tests only whether any address lies within a mile of the extent of the street geometry. A street file in the wrong coordinate system that still overlaps that extent passes, and a street layer that covers only part of the county passes.
- The MSAG source age comes from the file modification time. A freshly copied or downloaded MSAG reads as 0 days old.
- A non-numeric MSAG `LOW` or `HIGH` value, for example `1,000` or `1O1`, is read as blank. The record then shows up as `gap-with-no-address`, and the report never names the real cause.
- A CSV that is not UTF-8, for example Windows-1252 or the UTF-16 "Unicode text" format of Excel, is refused with exit 2. The message does not name the file or say to save it as UTF-8.
- The `--out` CSV guard follows the OWASP advice (see "What was verified against documentation"). I did not open a findings file in Excel, LibreOffice or Google Sheets, so I did not observe how each one shows the leading apostrophe. Excel may show it as part of the text. A cell that already starts with an apostrophe is left as it is. A formula character in the middle of the text is not changed, because a spreadsheet does not run it.
- The zero-hit refusal tests only whether any point lands in the layer. A layer that covers only part of the county passes when one address falls inside it. A point outside every polygon of such a layer still counts as `not inside any`, so use a polygon layer that covers the whole address file.
- A point inside a null-keyed polygon and a keyed polygon at once is reported as a null key, whichever polygon comes first in the file. A point inside two keyed polygons takes the first one in the file.
- A polygon feature that lacks the key property, rather than holding null, refuses the whole run with exit 2 and is not reported as a null-key finding.
- A polygon key written as the text `NULL`, `<Null>`, `None` or `nan` counts as a real key. A point inside it gets the ordinary `ESN is blank but point is inside ESN area` finding, not the null-key finding.
- A layer named in `[areas]` is checked for hits even when its check is off in `[checks]`, so remove the `[areas]` line as well.
- The `--out` CSV guard looks at the first character only. A cell that starts with a space or a line feed before `=`, `+`, `-` or `@` is not prefixed, and neither is a cell that starts with a full-width `=`, `+`, `-` or `@`. The OWASP page lists the line feed and the full-width forms as formula starters, and this tool follows the six characters of its specification. The OWASP page also says the single-quote prefix is not reliable in Excel after the CSV is saved and opened again, and it advises a tab character inside the quoted field. This tool uses the quote. The guard applies to the `--out` CSV only. The text report and the JSON file are never guarded.
- An error message for a bad settings or MSAG config value quotes that value. The tool never asks for a credential, but a secret typed into such a field would reach the terminal.
- A polygon layer that holds a feature with null geometry is refused whole, with exit 2 and the message `an area layer takes Polygon or MultiPolygon, got None`. Remove that feature first.
- The reader guard in the self-test checks only `reader.py`, `msag.py`, `crosswalks.py` and `settings.py`. A new reader module outside that list is not checked against importing the report module.
- The message for a SHA-256 mismatch in the MSAG config shows only the first 12 hex characters of the actual and of the pinned digest, so compare the full digest with a hash tool.
- The self-test removes its temporary folder with `ignore_errors=True`. A locked folder on Windows stays behind without a message.
- Column names are matched with their exact case. A file with lowercase headers gets a missing-column notice and many blank-field errors, such as `DiscrpAgID None invalid`, instead of one clear message.
- A CSV row with more cells than the header is read with the extra cells dropped, and no notice is printed. An unquoted comma inside a value hides the shift, so quote values that contain commas.
- Rows without a geometry, a GeoJSON feature with null geometry or a CSV row without X and Y, are left out of the distance and side checks. XLAYER-17, XLAYER-18, XLAYER-19 and STREET-14 count them in a notice. The response-area checks leave such a row out and count it in a notice, for example `RA-08 left out 1 of 2 addresses that have no position`, because a row with no position cannot be placed in a polygon. The other checks do not count them. A run in which no address row has a position is refused for any `[areas]` line.
- In a feet or meters run, a position of 0, 0 is a real position. In a degrees run any other stand-in value that lies inside the degree range, such as -1, -1, is read as a real position.
- Swapped longitude and latitude inside the degree range cannot be detected. The run gives no error and no notice.
- An address far from its street is reported at INFO by XLAYER-05 when its number falls inside a range of a same-name segment. INFO never changes the exit code, even with `--optional`.
- The degraded STREET-11 notice also prints when no street file is given.
- The response-area roll-up still prints when the area check is switched off with `[checks]`. A finding names a column the file lacks as `'None'`, for example `ONEWAY 'None' not a recognized value`.
- ADDR-08 says `missing house number` for an alphanumeric number such as `12A`, and for a fractional one such as `5.5`. The value is present but not a usable number, and the message does not say which of the two it is.
- With `--apply` the tool writes `OUT.tmp` first and then renames it onto `OUT`. An input file named `OUT.tmp` is refused. Any other file under that name is overwritten without warning. A failed rename, for example `--out` naming a folder, leaves `OUT.tmp` behind.
- The `--out` guard compares file identity for names that exist and resolved paths for a name that does not exist yet. A hard link, a symbolic link and a different case on Windows are caught. An 8.3 short name and a long-path prefix (the `?` form) are not exercised: the volume I tested on has no short names, and the prefix works on Windows only.
- The `--out` check compares file identity. A network or copy-on-write file system that reports a different identity for one file would not be caught.
- Branch coverage was measured on Windows with Python 3.13 only. The Linux and the Python 3.9 to 3.12 rows were run for the self-test count only.
- The Earth radius and the length of a degree are cited to Wikipedia pages, not to an official source such as IUGG or NIMA TR8350.2.
- XLAYER-17 does not report two adjacent mis-numbered houses, because each one's neighbour disagrees with the direction. In the numbers 101, 103, 105, 107, 121, 125, 109, 111, 113, 115 it gives no finding, and with 125 removed it reports 121, when the houses are 100 ft apart and the displacement limit is 0.
- XLAYER-17 never reports the first or the last house on a side. A number out of order by less than `oo_min_displacement_ft` (default 150 ft) is also kept quiet.
- XLAYER-17 leaves out a point within half a foot of the centerline, so a layer of points snapped onto the line gets no XLAYER-17 verdict at all.
- XLAYER-19 reports nothing for a point whose street name matches no segment in the street layer, because it has no own street to measure. XLAYER-04 is the check for that case.
- XLAYER-18 and XLAYER-19 test every same-name or ranged segment for every point, so a layer with hundreds of thousands of points and thousands of segments of one street name runs for a long time.
- A street layer is refused for a lack of address positions only when the street file holds geometry and an address file is given. A street file in CSV form has no geometry, so a run with it is never refused for that reason.
- A street file in CSV form skips the four range fit checks and the run can still exit 0. The report says so in NOTICE lines and in the `Notices:` line.
- The `--out` CSV holds findings only. The notices appear in the console report and in a `--format json` file, so a CSV from a run that skipped checks looks the same as a clean one.
- Exit code 1 means an ERROR finding, and it also means the self-test failed or the catalog block is out of date. Do not use the code alone to tell a finding from a tool fault outside a normal run.
- A CSV whose first line is blank is refused with exit 2 and the message `the file has no header row`. The message does not name the blank line.
- The console report prints input values as they are, so a value that holds terminal escape codes can change what a terminal shows. Read untrusted files through `--out` or `--format json`, or filter the output.
- Exit 2 can also come from an internal `ValueError`, so read the message before you blame the input file.
- An unexpected crash (exit 70) prints a Python traceback to stderr. The traceback can quote a value from an input row.
- The synthetic demo files use the state code `FL`. That is a state abbreviation, not a county identifier.
- A path in a settings `[areas]` line or in the MSAG config is opened as written, so a UNC path makes Windows contact that host. Use settings and config files you wrote yourself.
- An `--msag` run with no `--streets` file skips XLAYER-16 with a notice and still exits 0, because there is no GIS side to compare. The XLAYER-04 skip behaves the same way.
- The MSAG source age in the quoted run reads `0 day(s) old` on a fresh checkout. The tool measures the file modification time, so the same demo file reads a larger number once it is days old.
- The XLAYER-07 finding for a repeated NGUID compares values with leading and trailing whitespace stripped. Its `nguid` column can show `x` when the stored text is a tab or a carriage return before `x`.
- A CSV address row with a blank `Add_Number` is not judged by ADDR-01. Only ADDR-08 reports it, at WARNING, so a run with no other ERROR exits 0.
- A CSV row with `X` blank and `Y` present refuses the whole file with exit 2. A row with both `X` and `Y` blank is kept, and it gives no finding and no notice unless a check that needs a position runs.
- A response-area layer with exactly one address inside it passes the zero-hit refusal, so blank stored values on the other addresses stay silent and no coverage notice is printed.
- The Windows points in the `--out` guard sentence (file identity, 8.3 short names, the long-path prefix) and the UNC sentence are observed behaviour. I did not cite Microsoft documentation for them.
- A few one-operator changes to the range fit code cannot be pinned because they change no verdict: the early skip in XLAYER-19, the initial value of the rank list, `<` against `<=` between numbers that all differ, and the sign constants.

## Related

- [safe-republish](https://github.com/uhsear/safe-republish) refuses to truncate a feature class when
  the staged replacement fails a plausibility check. It follows the same rule of a dry run by default.
- [idreuse](https://github.com/uhsear/idreuse) diffs two layers that share an ID and measures how far
  apart each pair is.
- [clonedrift](https://github.com/uhsear/clonedrift) names every script on a share that exists in
  more than one version.

## Licence

MIT. See `LICENSE`.
