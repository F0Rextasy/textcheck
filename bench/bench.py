#!/usr/bin/env python3
"""Published bench for textcheck: fixture scans plus a synthetic corpus.

Timing rows are in-process medians of 5; the CLI row is one real
subprocess (median of 3). Correctness probes print
``bench: 16/16 probes correct``.
"""

import importlib.machinery
import importlib.util
import os
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "scripts", "textcheck")
FIX = os.path.join(ROOT, "fixtures")

_loader = importlib.machinery.SourceFileLoader("textcheck_mod", CLI)
_spec = importlib.util.spec_from_loader("textcheck_mod", _loader)
textcheck = importlib.util.module_from_spec(_spec)
_loader.exec_module(textcheck)


def fixture(*parts):
    return os.path.join(FIX, *parts)


def scanned(name, policy="lenient"):
    findings, count = textcheck.scan_tree(fixture(name), [], policy)
    return findings, textcheck.summarize(findings, count)


def main():
    probes = []
    rows = []

    def check(name, actual, expected):
        probes.append((name, actual == expected, actual, expected))

    findings, counts = scanned("utf8-clean")
    check("clean findings==[]", findings, [])
    check("clean exit==0", 1 if counts["errors"] else 0, 0)
    findings, counts = scanned("windows-mess")
    check("mess errors==5", counts["errors"], 5)
    check("mess exit==1", 1 if counts["errors"] else 0, 1)
    hit = {(f["rule"], f["severity"]) for f in findings}
    for rule in ("BINARY_AS_TEXT", "BOM_UTF8", "INVALID_UTF8",
                 "LONE_CR", "MIXED_EOL"):
        check("mess rule %s error" % rule, (rule, "error") in hit, True)
    check("mess warnings==6", counts["warnings"], 6)
    check("mess cookie warn",
          ("ENCODING_COOKIE_MISMATCH", "warn") in hit, True)
    findings, counts = scanned("crlf-bom")
    check("crlf-bom lenient exit==0", 1 if counts["errors"] else 0, 0)
    check("crlf-bom lenient infos==1", counts["info"], 1)
    findings, counts = scanned("crlf-bom", "strict")
    check("crlf-bom strict exit==1", 1 if counts["errors"] else 0, 1)
    findings, _ = scanned("windows-mess")
    bom_rows = [f["rule"] for f in findings
                if f["target"].endswith("bom.md")]
    check("bom.md single row", bom_rows, ["BOM_UTF8"])
    rows_utf8 = [f for f in findings if f["rule"] == "INVALID_UTF8"]
    check("invalid offset 8",
          rows_utf8[0]["evidence"] if rows_utf8 else "",
          "byte offset 8 (0xe9)")

    def time_mess():
        start = time.perf_counter()
        scanned("windows-mess")
        return (time.perf_counter() - start) * 1000

    ms = statistics.median(time_mess() for _ in range(5))
    rows.append(("scan windows-mess (9 files)", "5 errors, 6 warns",
                 "5 errors, 6 warns", ms, 80))

    corpus = tempfile.mkdtemp(prefix="textcheck-bench-")
    line = "the quick brown fox jumps over the lazy dog 0123456789\n"
    per_file = 50
    for index in range(2000):
        with open(os.path.join(corpus, "f-%04d.txt" % index), "w",
                  encoding="utf-8") as fh:
            fh.write("file %d\n" % index + line * per_file)
    size_mb = sum(os.path.getsize(os.path.join(corpus, name))
                  for name in os.listdir(corpus)) / 1e6

    def time_corpus():
        start = time.perf_counter()
        textcheck.scan_tree(corpus, [], "lenient")
        return (time.perf_counter() - start) * 1000

    ms = statistics.median(time_corpus() for _ in range(3))
    rows.append(("scan synthetic corpus (2000 files, %.1f MB)" % size_mb,
                 "0 errors", "0 errors", ms, 700))

    def run_cli():
        start = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, CLI, fixture("windows-mess"),
             "--format", "json"],
            capture_output=True, timeout=60)
        return (time.perf_counter() - start) * 1000, proc.returncode

    times, codes = zip(*[run_cli() for _ in range(3)])
    ms = statistics.median(times)
    rows.append(("cli json subprocess (windows-mess)", "exit 1",
                 "exit %d" % codes[0], ms, 1600))

    ok = True
    print("%-42s %-16s %-18s %8s %8s  %s"
          % ("probe", "expected", "detected", "median", "thresh", "verdict"))
    print("-" * 112)
    for name, expected, detected, ms, thresh in rows:
        verdict = "ok" if str(expected) == str(detected) and ms <= thresh \
            else "FAIL"
        print("%-42s %-16s %-18s %8.2f %8d  %s"
              % (name, expected, detected, ms, thresh, verdict))
        ok = ok and verdict == "ok"
    good = sum(1 for _, passed, _, _ in probes if passed)
    print("bench: %d/%d probes correct" % (good, len(probes)))
    for name, passed, actual, expected in probes:
        if not passed:
            print("PROBE FAIL %s: got %r want %r" % (name, actual, expected))
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
