"""The command line: parse arguments, run the checks, print the report.

All the decisions live in the other modules. This one wires the readers to the engine and is
the only place that writes a file, and it writes only behind --apply.

Exit codes: 0 no ERROR finding, 1 at least one ERROR finding after the overrides, 2 an input
or settings file could not be read or was refused, 64 usage error, 70 an unexpected crash,
which is never a finding.
"""
import argparse
import os
import sys
import traceback

from . import __version__, catalog, engine, msag, reader, report, settings as settings_mod
from . import response_area_checks as ra
from .crosswalks import load_crosswalks, load_domain_csv
from .geometry import UNITS, Frame, fits_degrees

EXIT_OK, EXIT_ERRORS, EXIT_INPUT, EXIT_USAGE, EXIT_CRASH = 0, 1, 2, 64, 70
KPI_NAMES = ("MSAG match-rate KPI", "MSAG exact-tuple KPI", "MSAG source age")
ROLLUP_ROWS = 10


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write("%s: error: %s\n" % (self.prog, message))
        raise SystemExit(EXIT_USAGE)


def _count(text):
    """An argparse type: a whole number of zero or more."""
    try:
        value = int(text)
    except ValueError:
        value = -1
    if value < 0:
        raise argparse.ArgumentTypeError("%r is not a number of zero or more" % text)
    return value


def _tolerate_encoding(*streams):
    """Make a console stream print a character its code page lacks as a backslash escape.

    Without this a Windows console on a legacy code page raises on the first such
    character, and the report and any --out file are lost."""
    for stream in streams:
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="backslashreplace")


def build_parser():
    ap = _Parser(
        prog="ng911check",
        description="Run documented NG9-1-1 address and centerline checks from CSV or "
                    "GeoJSON. A severity override can raise a finding but never lowers an "
                    "ERROR.",
        epilog="Nothing is written without --apply.",
        allow_abbrev=False,
    )
    ap.add_argument("--addresses", metavar="FILE", help="address points, .csv or .geojson")
    ap.add_argument("--streets", metavar="FILE", help="centerlines, .csv or .geojson")
    ap.add_argument("--settings", metavar="INI", help="calibration file (see the README)")
    ap.add_argument("--agency", metavar="DOMAIN",
                    help="the agency domain NGUIDs must end in; overrides the settings file")
    ap.add_argument("--units", choices=UNITS, default="degrees",
                    help="units of every coordinate in the inputs (default degrees)")
    ap.add_argument("--x-field", dest="x_field", default="X", metavar="COLUMN",
                    help="the X column of a CSV layer (default X)")
    ap.add_argument("--y-field", dest="y_field", default="Y", metavar="COLUMN",
                    help="the Y column of a CSV layer (default Y)")
    ap.add_argument("--rename", action="append", default=[], metavar="LAYER:ACTUAL=CANONICAL",
                    help="read column ACTUAL of LAYER (addresses or streets) as CANONICAL")
    ap.add_argument("--domains", metavar="CSV",
                    help="extra street-type, direction and modifier values, domain,full,abbrev")
    ap.add_argument("--msag", metavar="CSV", help="the MSAG as a CSV; turns XLAYER-16 on")
    ap.add_argument("--msag-config", dest="msag_config", metavar="JSON",
                    help="MSAG column map, header row, floors and pinned hash")
    ap.add_argument("--msag-exceptions", dest="msag_exceptions", metavar="CSV",
                    help="MSAG records to leave out of the match rate")
    ap.add_argument("--street-names", dest="street_names", metavar="CSV",
                    help="an authoritative street-name list for STREET-11")
    ap.add_argument("--optional", action="store_true", help="also run the opt-in checks")
    ap.add_argument("--show", type=_count, default=20, metavar="N",
                    help="findings to print (default 20)")
    ap.add_argument("--format", choices=("csv", "json"), default="csv",
                    help="format of the --out file (default csv)")
    ap.add_argument("--out", metavar="FILE", help="write every finding here, with --apply")
    ap.add_argument("--apply", action="store_true",
                    help="write the --out file. Without it nothing is written.")
    ap.add_argument("--catalog", action="store_true", help="print the check catalog and exit")
    ap.add_argument("--catalog-check", dest="catalog_check", metavar="FILE",
                    help="exit 1 if the catalog block in FILE is out of date")
    ap.add_argument("--self-test", dest="self_test", action="store_true",
                    help="run the offline assertions and exit")
    ap.add_argument("--version", action="store_true", help="print the version and exit")
    return ap


def _same_file(a, b):
    """True when both names reach one file.

    samefile compares file identity, so it sees through a hard link, an 8.3 short name and a
    long-path prefix. A name that does not exist yet falls back to a resolved-path comparison."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        def norm(p):
            return os.path.normcase(os.path.realpath(os.path.abspath(p)))
        return norm(a) == norm(b)


def _write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _msag_config(args):
    if args.msag_config:
        cfg = msag.load_config(args.msag_config)
        if args.msag:
            cfg.source_path = args.msag
        elif not cfg.source_path:
            raise ValueError("%s names no source_path and --msag was not given, so there is no "
                             "MSAG file to read" % args.msag_config)
    elif args.msag:
        cfg = msag.MsagConfig(source_path=args.msag)
    else:
        if args.msag_exceptions or args.street_names:
            raise ValueError("--msag-exceptions and --street-names need --msag or --msag-config")
        return None
    if args.msag_exceptions:
        cfg.exceptions_path = args.msag_exceptions
    if args.street_names:
        cfg.names_path = args.street_names
    return cfg


def _load_settings(args):
    st = settings_mod.load(args.settings) if args.settings else settings_mod.Settings()
    if args.agency:
        st.ctx_overrides["expected_agid"] = args.agency.strip()
    if not st.ctx_overrides.get("expected_agid"):
        raise ValueError("no agency is named. Set expected_agid under [agency] in the "
                         "settings file or pass --agency; the NGUID checks cannot run "
                         "against a default agency.")
    return st


def _kpi_lines(records):
    return ["  " + r.description for r in records
            if r.check_id == "XLAYER-16" and r.check_name in KPI_NAMES]


def _rollup_sections(ctx, records):
    sections = []
    kpis = _kpi_lines(records)
    if kpis:
        sections.append(("MSAG reconciliation:", kpis))
    if ctx.msag_result is not None:
        rows = msag.rollup(ctx.msag_result)
        lines = ["  %-20s %-28s %4d  (%d not in GIS, %d not in MSAG, %d range, %d ESN)" % (
            r["community"], r["name_key"], r["total"], r["msag_not_gis"], r["gis_not_msag"],
            r["range_mismatch"], r["attr_mismatch"]) for r in rows[:ROLLUP_ROWS]]
        if lines:
            sections.append(("MSAG roll-up by street (top %d of %d):"
                             % (len(lines), len(rows)), lines))
    area_rows = ra.rollup(ctx.addresses, [c for c in ra.CHECK_IDS if c in ctx.area_layers],
                          rules=ctx.area_rules)
    if area_rows:
        sections.append(("Response-area roll-up (top %d of %d):"
                         % (min(ROLLUP_ROWS, len(area_rows)), len(area_rows)),
                         ["  %-6s %-10s inside %-12s stored %-12s %5d point(s), e.g. rows %s" % (
                             r["check_id"], r["field"], r["containing"], r["stored"],
                             r["count"], ",".join(str(o) for o in r["sample_oids"]))
                          for r in area_rows[:ROLLUP_ROWS]]))
    return sections


def _read_inputs(args):
    renames = reader.parse_renames(args.rename)
    layers = {}
    for name in reader.LAYERS:
        path = getattr(args, name)
        if path:
            layers[name] = reader.read_layer(path, name, renames[name], args.x_field,
                                             args.y_field)
    if not layers:
        raise ValueError("give --addresses, --streets or both")
    return layers


def _clash(out, paths):
    """True when the --out file, or the OUT.tmp that --apply writes first, is one of the input files."""
    return bool(out) and any(p and _same_file(target, p) for target in (out, out + ".tmp")
                             for p in paths)


def run(args):
    """Run the checks for parsed args.

    Returns (exit code, report text, file text, every input path the run read). The paths
    include the polygon files named in the settings and the files named in the MSAG config, so
    main can refuse an --out that would overwrite any of them."""
    st = _load_settings(args)
    layers = _read_inputs(args)
    # A file given for a check is a request to run it: switch on the opt-in checks it feeds,
    # unless the settings file switched them off on purpose.
    if args.msag or args.msag_config:
        st.checks.setdefault("XLAYER-16", True)
    for cid in st.areas:
        st.checks.setdefault(cid, True)
    areas = {cid: reader.read_areas(spec.path, spec.key_prop) for cid, spec in st.areas.items()}
    coords = [c for layer in layers.values() for c in layer.raw_coords()]
    coords += [p for polys in areas.values() for _k, rings in polys for ring in rings
               for p in ring]
    frame = Frame.fit(args.units, coords)
    geoms = {}
    for name, layer in layers.items():
        geoms[name] = reader.finalize_layer(layer, frame)
    addresses = layers["addresses"].rows if "addresses" in layers else []
    streets = layers["streets"].rows if "streets" in layers else []
    notices = []
    if args.units != "degrees" and fits_degrees(coords):
        notices.append("Every coordinate fits longitude -180..180 and latitude -90..90, yet "
                       "--units is %s. If the files hold longitude and latitude, rerun with "
                       "--units degrees; until then every distance is wrong." % args.units)
    for name, layer in layers.items():
        gone = layer.missing_columns()
        if gone:
            notices.append("The %s file has no column(s) named: %s. Checks that read them see "
                           "blank values or skip the row." % (name, ", ".join(gone)))
    rules = {}
    for cid, spec in st.areas.items():
        if "addresses" not in layers:
            raise ValueError("[areas] %s needs an --addresses file" % cid)
        rules[cid] = ra.resolve_rule(cid, spec)
        absent = [f for f in ra.required_fields(cid, rules[cid])
                  if f not in layers["addresses"].columns]
        if absent:
            raise ValueError("%s compares %s but the addresses file has no such column; "
                             "set the fields in the [areas] line or use --rename"
                             % (cid, ", ".join(absent)))
        reader.annotate_areas(addresses, areas[cid], ra.annotation_key(cid), frame)
        ra.require_hits(cid, addresses, spec.path)
    street_geoms = geoms.get("streets") or {}
    extra = load_domain_csv(args.domains) if args.domains else None
    ctx = engine.build_context(
        addresses, streets, crosswalks=load_crosswalks(extra), settings=st,
        geom_provider=((lambda layer, oid: street_geoms.get(oid) if layer == "street" else None)
                       if street_geoms else None),
        area_layers=frozenset(rules), area_rules=rules)
    mcfg = _msag_config(args)
    engine.build_msag_context(ctx, mcfg)
    result = engine.run_report(addresses, streets, ctx, include_optional=args.optional)
    notices.extend(result.notices)
    inputs = ["%s: %s (%d rows)" % (n, layers[n].path, len(layers[n].rows)) for n in layers]
    inputs.append("units: %s" % args.units)
    text = report.format_text(
        result.records, notices, settings_mod.effective_lines(st),
        settings_mod.override_lines(result.tally), inputs, _rollup_sections(ctx, result.records),
        args.show)
    rows = report.to_rows(result.records, frame)
    summary = dict(report.counts(result.records))
    body = (report.to_json(rows, notices, summary) if args.format == "json"
            else report.to_csv_text(rows))
    used = [args.addresses, args.streets, args.settings, args.domains, args.msag, args.msag_config,
            args.msag_exceptions, args.street_names]
    used.extend(spec.path for spec in st.areas.values())
    if mcfg is not None:
        used.extend((mcfg.source_path, mcfg.exceptions_path, mcfg.names_path))
    return report.exit_status(result.records), text, body, [p for p in used if p]


def main(argv=None):
    _tolerate_encoding(sys.stdout, sys.stderr)
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.version:
        print("ng911check %s" % __version__)
        return EXIT_OK
    if args.self_test:
        from . import selftest
        return selftest.run()
    if args.catalog:
        print(catalog.render_markdown())
        return EXIT_OK
    if args.catalog_check:
        try:
            with open(args.catalog_check, "r", encoding="utf-8") as fh:
                ok, message = catalog.check_document(fh.read())
        except OSError as exc:
            sys.stderr.write("ng911check: %s\n" % exc)
            return EXIT_INPUT
        print(message)
        return EXIT_OK if ok else EXIT_ERRORS
    if args.apply and not args.out:
        ap.error("--apply needs --out FILE")
    inputs = (args.addresses, args.streets, args.settings, args.domains, args.msag,
              args.msag_config, args.msag_exceptions, args.street_names)
    if _clash(args.out, inputs):
        ap.error("--out would overwrite an input file")
    try:
        code, text, body, used = run(args)
        if _clash(args.out, used):
            ap.error("--out would overwrite an input file")
        print(text)
        if args.out and args.apply:
            _write_atomic(args.out, body)
            print("\nWrote %s." % args.out)
        elif args.out:
            print("\nWould write the findings to %s. Add --apply to write them." % args.out)
        return code
    except (ValueError, OSError) as exc:
        sys.stderr.write("ng911check: %s\n" % exc)
        return EXIT_INPUT
    except Exception:  # an unexpected crash must never read as a finding
        traceback.print_exc()
        return EXIT_CRASH
