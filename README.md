# ng911check

Run documented NG9-1-1 address and centerline checks on a CSV or GeoJSON file. Refuse to let a
settings line switch a routing error off, and refuse to report an MSAG match rate that hides how
well the two sources really agree.

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

This run uses the settings file `tuned.ini`, which holds the two lines above and `ADDR-03 = ERROR`.
The files are synthetic: four address points on one street.

```
$ python -m ng911check --addresses addresses.csv --streets streets.csv --settings tuned.ini --units feet
ng911check report
--------------------------------------------------------------------
addresses: addresses.csv (4 rows)
streets: streets.csv (1 rows)
units: feet

Settings source: tuned.ini
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

NOTICE: ... (three notices: XLAYER-13, XLAYER-15, STREET-11)

Findings: 3 ERROR, 0 WARNING, 2 INFO
  ADDR-05            ERROR    1
  XLAYER-01          ERROR    2
  ADDR-05            INFO     1
  STREET-11          INFO     1

First 5 finding(s), most severe first:
  ERROR   ADDR-05    address row 2: ESN 'ABC' not a valid 1-5 digit ESN
  ERROR   XLAYER-01  address row 2: ESN ABC != covering side ESN(s) ['100'] (SEG 1 Left)
  ERROR   XLAYER-01  address row 4: ESN 200 != covering side ESN(s) ['100'] (SEG 1 Left)
  INFO    ADDR-05    address row 3: STATUS 'RETIRED' not in domain (expected ACTIVE)
  INFO    STREET-11  street row 1: name 'ELM ST' unmatched in degraded fuzzy check (no master list)
                                                              (exit 1)
```

The invalid ESN is still an ERROR and the run exits 1. The retired point became INFO, as asked.
The `XLAYER-14` line is marked as having no effect before the run starts. Without the override file
the same data gives `3 ERROR, 1 WARNING, 1 INFO`.

## What you get

```
$ python -m ng911check --self-test
ng911check self-test: temporary files only, no network, no ArcGIS, no database
--------------------------------------------------------------------
...
PASS  a settings line ADDR-05 = INFO lowers the WARNING and leaves the invalid-ESN ERROR  <-- pinned defect
...
PASS  the held ERROR still makes the run exit 1  <-- pinned defect
...
PASS  an override can never lower an ERROR  <-- pinned defect
...
PASS  xlayer-16 shows a perfect match rate beside a 0 percent exact-tuple rate  <-- pinned defect
...
PASS  xlayer-16 warns that a 100 percent rate over no eligible record compared nothing  <-- pinned defect
...
PASS  reconcile reports 100 percent coverage and 0 percent exact when the GIS run is wider than the MSAG record  <-- pinned defect
...
PASS  a prefix --ap of --apply is REFUSED by the parser and writes nothing  <-- pinned defect
...
PASS  --out onto a polygon file named in the settings is refused and the file is untouched  <-- pinned defect
...
PASS  --out without --apply says what it would write and writes nothing  <-- pinned defect
...
PASS  an unexpected exception exits 70, never the 1 that means a finding  <-- pinned defect
...
PASS  the package folder holds Python files only, so no vendor domain file ships  <-- pinned defect
...
PASS  check() and raises() really do record a failure  <-- pinned defect
...
PASS  ADDR-05 declares exactly the columns it reads
...
PASS  xlayer-10 flags six name pairs that do not agree
...
--------------------------------------------------------------------
676 assertions, 0 failed
```

The full run prints all 676 assertions. Each `...` line above is where the block is cut.
`python -m ng911check --self-test` exits 0 when every assertion passes and 1 when one fails.

| Host | Python | Assertions |
|---|---|---|
| Windows | 3.13.2 | 676 assertions, 0 failed |
| Windows | 3.9.25 | 676 assertions, 0 failed |
| Ubuntu | 3.12.3 | 676 assertions, 0 failed |

The counts are equal on every host because the self-test never branches on the platform. It writes
its files to a temporary folder and removes the folder at the end.

`coverage run --branch -m ng911check --self-test` reports 100 percent of statements and branches
for the whole package, the test modules included. One line carries a `pragma: no branch`. It is the
loop in `Polyline.midpoint` in `geometry.py`. That loop never ends normally, because its last
segment always returns. Branch coverage cannot see that.

## What already exists

Other open tools check NG9-1-1 data. Use them if one fits better.

- [kansasgis/NG911](https://github.com/kansasgis/NG911) is a full ArcGIS toolbox from the Kansas
  NG911 project. It validates, converts, adjusts and compares data, and it has MSAG tools and
  submission tools. It needs ArcGIS Desktop 10.3 or later, or ArcGIS Pro. GitHub lists no licence for it. Its domain tables are the model for a state programme. This tool has no such
  tables and does not convert or submit anything.
- [dolin5/NG911-Scripts](https://github.com/dolin5/NG911-Scripts) is a small set of ArcPy scripts
  under the MIT licence. They find overlapping road ranges, list MSAG and centerline differences
  and sync MSAG with structures. Its README says the MSAG script did not yet use the ESN. The
  repository was last pushed in 2017.
- [Nsokol44/ng911-spatial-qa](https://github.com/Nsokol44/ng911-spatial-qa) runs five spatial
  checks on site-address points against centerlines: name agreement, range parity, distance,
  uniqueness and consistency across a county line. It is under the MIT licence. It uses a 45 m
  search window around each point, which this tool does not.
- [A-Charvin/Fishbone-QA-911](https://github.com/A-Charvin/Fishbone-QA-911) is an ArcGIS Pro tool
  that draws a line from each address point to its road segment, so a person sees the mismatches
  on a map. It needs ArcGIS Pro.
- The NENA GIS data model templates at
  [NENA911/NG911GISDataModel](https://github.com/NENA911/NG911GISDataModel) define the schema that
  most of these tools check against.

What this tool adds is small. It runs without ArcGIS. It keeps the severity rule above and prints
the effect of every override. It reports the exact-tuple rate and the file age beside the MSAG
match rate. It generates its own check catalog from the code and fails when the two disagree. It
does not replace a state submission tool, and it does not edit your data.

A search of GitHub with `gh search repos` on the day this was written found these repositories and
others that were not relevant. It found no repository named `ng911check` except this one. That
shows only that the search found nothing more.

## Quick start

```
git clone https://github.com/uhsear/ng911check.git
cd ng911check
python -m ng911check --self-test
python -m ng911check --addresses addresses.csv --streets streets.csv --settings agency.ini --units feet
```

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
| `--streets FILE` | none | Centerlines, `.csv` or `.geojson`. A run needs one of the two layers. |
| `--settings INI` | none | The calibration file. See Settings. |
| `--agency DOMAIN` | none | The agency domain NGUIDs must end in. It replaces the settings file value. |
| `--units` | `degrees` | Units of every coordinate: `degrees`, `feet` or `meters`. |
| `--x-field`, `--y-field` | `X`, `Y` | The coordinate columns of a CSV layer. |
| `--rename LAYER:ACTUAL=CANONICAL` | none | Read column ACTUAL of the layer as CANONICAL. Repeat the flag as needed. |
| `--domains CSV` | none | More street types, directions and modifier values: `domain,full,abbrev`. |
| `--msag CSV` | none | The MSAG as a CSV. It turns on XLAYER-16. |
| `--msag-config JSON` | none | The MSAG column map, header row, floors and a pinned SHA-256. |
| `--msag-exceptions CSV` | none | MSAG records to leave out of the match rate. |
| `--street-names CSV` | none | An authoritative street-name list for STREET-11. |
| `--optional` | off | Also run the checks that are off by default. |
| `--show N` | `20` | How many findings to print. |
| `--format` | `csv` | Format of the `--out` file: `csv` or `json`. |
| `--out FILE` | none | Where to write every finding. Nothing is written without `--apply`. |
| `--apply` | off | Write the `--out` file. It needs `--out`. |
| `--catalog` | off | Print the check catalog and exit. |
| `--catalog-check FILE` | none | Exit 1 when the catalog block in FILE differs from the code. |
| `--self-test` | off | Run the offline assertions and exit. |
| `--version` | off | Print the version and exit. |

Every flag must be spelled in full. The parser sets `allow_abbrev=False`. A prefix such as `--ap`
is refused with exit 64 instead of being read as `--apply`, and the self-test pins that for
`--ap`, `--app`, `--appl` and for `--ou`. Nothing else may write. `--out` is refused when it names
any file the run reads: a file named on the command line, a polygon file named in the settings, or a
file named in the MSAG config. The refused run leaves that file as it was.

Exit codes: 0 no ERROR finding, 1 at least one ERROR after the overrides, 2 an input or settings
file was refused or could not be read, 64 usage error, 70 an unexpected crash. A crash never
reads as a finding.

```
$ python -m ng911check --addresses addresses.csv --streets streets.csv --settings agency.ini --units feet --out found.csv
...
Would write the findings to found.csv. Add --apply to write them.
$ ls found.csv
ls: cannot access 'found.csv': No such file or directory
$ python -m ng911check ... --out found.csv --ap
ng911check: error: unrecognized arguments: --ap                    (exit 64)
$ python -m ng911check ... --out found.csv --apply
...
Wrote found.csv.
$ head -2 found.csv
check_id,check_name,family,severity,layer,row,nguid,description,x,y
ADDR-05,Address domain/bounds violation,address_attr,ERROR,address,2,ADR103@agency.example.org,ESN 'ABC' not a valid 1-5 digit ESN,,
$ python -m ng911check --addresses addresses.csv --settings agency.ini --out addresses.csv --apply
ng911check: error: --out would overwrite an input file             (exit 64)
```

## Inputs

A CSV layer has a header row. The tool reads the columns it knows by name and ignores the rest.
Use `--rename` to map your column names. The column lists are `ADDRESS_COLUMNS` and `STREET_COLUMNS`
in `reader.py`. A column the file lacks is named in a notice at the top of the report. A CSV can
carry address points through two coordinate columns. A CSV street layer has no line geometry.

A GeoJSON layer must be a `FeatureCollection`. Addresses take `Point`. Streets take `LineString` or
`MultiLineString`. Response areas take `Polygon` or `MultiPolygon`. Coordinates are longitude then
latitude. RFC 7946 section 3.1.1 says: "The first two elements are longitude and latitude, or
easting and northing, precisely in that order". Streets with geometry turn on XLAYER-13.
XLAYER-05 also needs `--optional` or `[checks] XLAYER-05 = on`.

Values are not stripped, because ADDR-07 exists to find leading and trailing spaces. A street range
that is not a whole number refuses the file. Reading it as blank would make a broken range look
unused. A row is numbered by its position in the file, and findings quote that row number.

Degrees are converted to planar feet around the centre of the data. Over the few miles a county
spans the result is good to about half a percent against the WGS 84 ellipsoid. The self-test checks
this at 29 degrees north against the series for the length of a degree on the
[Geographic coordinate system](https://en.wikipedia.org/wiki/Geographic_coordinate_system) page. It
is a plausibility measure, not a survey measure. A layer in feet or meters is exact. Coordinates that
cannot be degrees are refused unless you pass `--units`. The meter uses the international foot of
exactly 0.3048 m ([NIST SP 811, appendix B.8](https://www.nist.gov/pml/special-publication-811/nist-guide-si-appendix-b-conversion-factors/nist-guide-si-appendix-b8)).

## Settings

The settings file is an INI file. An unknown section, key or check id is an error, so a typo cannot
weaken a run. A key you leave out takes its built-in default.

| Section | Keys |
|---|---|
| `[thresholds]` | `min_address`, `max_address`, `max_range_gap`, `distance_tolerance_ft`, `sync_threshold` |
| `[agency]` | `expected_agid` (required), `strict_fqdn`, `expected_state`, `counties` |
| `[names]` | `ignored`: street names the name checks skip |
| `[checks]` | `CHECK-ID = on` or `off` |
| `[severity]` | `CHECK-ID = ERROR`, `WARNING` or `INFO` |
| `[areas]` | `RA-xx = file.geojson|key_property[|fields[|sentinel]]` |

The severity rule has three parts. An override may raise a WARNING to ERROR. An override never
lowers an ERROR record. An INFO metric line is left alone. The report prints, before the run, what
each line can do, and after the run, what each line did. The self-test pins this with the line
`ADDR-05 = INFO` over a file that holds an invalid ESN.

`RA-09` has a second class, a blank CITY inside a postal-city polygon. That class is a data-entry
backlog and not a misroute, so it is reported at INFO and answers to its own line, `RA-09-BLANK`.
A wrong CITY stays at ERROR.

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

The report also prints a roll-up by street, so one thousand findings on forty streets read as forty
rows. Three more WARNINGS refuse to let a rate stand alone: no eligible record at all, a record
that fell into no bucket, and a file older than the limit.

```
$ python -m ng911check --addresses addresses.csv --streets streets.csv --settings agency.ini --units feet --msag msag.csv
...
MSAG reconciliation:
  MSAG match rate 66.67% (matched 2/3 eligible); NENA floor 98.00% -> BELOW FLOOR [unmatched: 0 range mismatch, 1 not in GIS, 0 gap-with-no-address]
  MSAG exact-tuple rate 33.33% (1/3 eligible equal one whole GIS run on community, street, parity, extent and ESN); coverage match rate 66.67%; 0 of 3 records excepted
  MSAG source is 0 day(s) old (no limit set)
...
MSAG roll-up by street (top 1 of 1):
  TESTVILLE            OAK AVE                         1  (1 not in GIS, 0 not in MSAG, 0 range, 0 ESN)
```

The floor of 98 percent is the default `min_match_rate`. Secondary sources, a Montana NG9-1-1
assessment and a GeoComm case study, attribute a 98 percent synchronisation rate to NENA 71-501,
*Synchronizing GIS databases with MSAG and ALI*. I did not read the NENA text. The floor is a
setting you can change.

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
| XLAYER-01 | both | ERROR | yes | - | Flag an address ESN that differs from the ESN of the street side that covers it. |
| XLAYER-02 | both | ERROR | yes | - | Flag an address number that lies outside every range of its street. |
| XLAYER-03 | address | WARNING | yes | - | Flag an address whose odd or even number contradicts the declared parity of its covering side. |
| XLAYER-04 | both | ERROR | yes | - | Flag an address whose street name no centerline carries. |
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
| XLAYER-14 | street | INFO | yes | - | Report a street segment that has an address range but no address point inside it. |
| XLAYER-15 | both | WARNING | yes | modifier domains | Flag a modifier or separator value that is not in the supplied domain. |
| XLAYER-16 | both | WARNING, ERROR, INFO | no | msag | Compare the MSAG with the GIS ranges and report coverage, exact-tuple rate, differences and file age. |
<!-- catalog:end -->

## What was verified against documentation

This package relies on no Esri, SQL Server, PROJ, FEMA or Census behaviour. It never imports
`arcpy`. It relies on these published facts, each read on the day it was written.

- USPS Publication 28: section 233 lists the directionals, and Appendix C1 lists the street suffix
  abbreviations. The built-in tables come from those two. No vendor or agency domain file ships.
  The self-test fails when the package folder holds any file that is not Python.
- RFC 7946 section 3.1.1, quoted above, for the coordinate order.
- NIST SP 811, appendix B.8, for the foot.
- The IUGG mean radius R1 of 6371008.7714 m, rounded in the code to 6371008.8 m, from the table on the
  [Earth radius](https://en.wikipedia.org/wiki/Earth_radius) page.

Not verified: the exact grammar of an NGUID. The tool checks the form `localid@authority`, a
localid of letters, digits, `_`, `.` and `-`, and an authority that equals the expected agency. I
could not read NENA-STA-006 or NENA-STA-010. The rule is the one the original toolbox used. Treat
ADDR-06, STREET-08 and XLAYER-08 as local policy until you check them against your standard. The
ESN rule in ADDR-05, one to five digits and not zero, is also a local choice.

## Limits

- The tool has not run on a real county layer. Every number in this file comes from synthetic data.
- The street-name and ESN domains are what the checks need, not a copy of a state schema.
- Points on a polygon edge, and points in two overlapping polygons, take the first polygon in the
  file. Both are topology defects, which this package does not judge.
- STREET-11 without a name list is a heuristic and reports at INFO. A name list or an MSAG turns on
  the real check.
- The checks that need a street geometry (XLAYER-05, XLAYER-13) need a GeoJSON street layer.
- The saint names that XLAYER-10 expands (`ST BENEDICT` to `SAINT BENEDICT`) are a closed list in
  the code. Add a name there for a new saint road.
- A range check for address points against the range of the segment they front is not in this
  release.

## Related

- [safe-republish](https://github.com/uhsear/safe-republish) refuses to truncate a feature class when
  the staged replacement fails a plausibility check. It follows the same rule of a dry run by default.
- [idreuse](https://github.com/uhsear/idreuse) diffs two layers that share an ID and measures how far
  apart each pair is.
- [clonedrift](https://github.com/uhsear/clonedrift) names every script on a share that exists in
  more than one version.

## Licence

MIT. See `LICENSE`.
