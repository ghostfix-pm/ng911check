"""The offline self-test: `python -m ng911check --self-test`.

No network, no ArcGIS, no database. Every file the tests need is written to a temporary
folder that is removed at the end. The sections live in the st_*.py modules next to this one.
They share one rule: a test never branches. Each case is a straight line of check() calls,
so the coverage report measures the package and not the tests.

Every label is lowercase. A label that ends in "<-- pinned defect" guards a defect that was
found and fixed, or a rule the package exists to keep, so it cannot come back.
"""
import contextlib
import io
import shutil
import tempfile

from . import st_fix


class Harness(object):
    """The check()/raises() recorder, a class so the self-test can test it."""

    def __init__(self):
        self.passed = 0
        self.failed = []

    def check(self, cond, label):
        if cond:
            self.passed += 1
            print("PASS  %s" % label)
        else:
            self.failed.append(label)
            print("FAIL  %s" % label)

    def raises(self, fn, label, exc=ValueError):
        """Pass when fn() raises exc (default ValueError). Any other outcome fails."""
        try:
            fn()
        except exc:
            self.check(True, label)
        except Exception as err:
            self.check(False, "%s (wrong exception %r)" % (label, err))
        else:
            self.check(False, "%s (no error raised)" % label)

    def footer(self):
        """Print the closing line and return the process exit status."""
        print("-" * 68)
        total = self.passed + len(self.failed)
        if self.failed:
            print("%d assertions, %d failed" % (total, len(self.failed)))
            for label in self.failed:
                print("  FAILED: %s" % label)
            return 1
        print("%d assertions, 0 failed" % total)
        return 0


class Quiet(object):
    """Capture stdout and stderr for the length of a with block."""

    def __enter__(self):
        self.out, self.err = io.StringIO(), io.StringIO()
        self._o = contextlib.redirect_stdout(self.out)
        self._e = contextlib.redirect_stderr(self.err)
        self._o.__enter__()
        self._e.__enter__()
        return self

    def __exit__(self, *exc):
        self._e.__exit__(*exc)
        self._o.__exit__(*exc)
        return False


class Tmp(object):
    """A temporary folder with a helper that writes a text file into it."""

    def __enter__(self):
        self.root = tempfile.mkdtemp(prefix="ng911check-st-")
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self.root, ignore_errors=True)
        return False

    def path(self, name):
        return self.root + "/" + name

    def write(self, name, text):
        with open(self.path(name), "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        return self.path(name)


def sections():
    """The test sections in run order. Imported late so --version never pays for them."""
    from . import (st_addr, st_area, st_cli, st_cross, st_edge, st_geom, st_io, st_meta, st_msag,
                   st_street)
    return (st_addr.section, st_street.section, st_cross.section, st_area.section,
            st_msag.section, st_geom.section, st_io.section, st_cli.section, st_edge.section,
            st_meta.section)


def run():
    """Run every section. Returns the process exit status: 0 green, 1 at least one failure."""
    print("ng911check self-test: temporary files only, no network, no ArcGIS, no database")
    print("-" * 68)
    h = Harness()
    st_fix.reset()
    for section in sections():
        section(h)
    return h.footer()
