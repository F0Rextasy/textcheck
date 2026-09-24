import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "scripts", "textcheck")
FIX = os.path.join(ROOT, "fixtures")

_loader = importlib.machinery.SourceFileLoader("textcheck_mod", CLI)
_spec = importlib.util.spec_from_loader("textcheck_mod", _loader)
textcheck = importlib.util.module_from_spec(_spec)
_loader.exec_module(textcheck)


def fixture(*parts):
    return os.path.join(FIX, *parts)


def scan(name, policy="lenient"):
    findings, count = textcheck.scan_tree(fixture(name), [], policy)
    return findings, textcheck.summarize(findings, count)


class FixtureTests(unittest.TestCase):
    def test_clean_is_silent(self):
        findings, counts = scan("utf8-clean")
        self.assertEqual(findings, [])
        self.assertEqual(
            counts, {"files": 3, "errors": 0, "warnings": 0, "info": 0})

    def test_mess_error_count_and_exit(self):
        findings, counts = scan("windows-mess")
        self.assertEqual(counts["errors"], 5)
        proc = subprocess.run(
            [sys.executable, CLI, fixture("windows-mess")],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 1)

    def test_mess_hits_every_error_rule(self):
        findings, _ = scan("windows-mess")
        hit = {(f["rule"], f["severity"]) for f in findings}
        for rule in ("BINARY_AS_TEXT", "BOM_UTF8", "INVALID_UTF8",
                     "LONE_CR", "MIXED_EOL"):
            self.assertIn((rule, "error"), hit)

    def test_mess_warn_rules(self):
        findings, counts = scan("windows-mess")
        hit = {(f["rule"], f["severity"]) for f in findings}
        self.assertIn(("ENCODING_COOKIE_MISMATCH", "warn"), hit)
        self.assertIn(("CRLF_NO_GITATTRIBUTES", "warn"), hit)
        self.assertIn(("NONASCII_NO_POLICY", "warn"), hit)
        self.assertEqual(counts["warnings"], 6)

    def test_bom_does_not_double_fire_nonascii(self):
        findings, _ = scan("windows-mess")
        bom_rows = [f for f in findings
                    if f["target"].endswith("bom.md")]
        self.assertEqual([f["rule"] for f in bom_rows], ["BOM_UTF8"])

    def test_lenient_tolerates_ps1_bom(self):
        findings, counts = scan("crlf-bom")
        self.assertEqual(counts["errors"], 0)
        self.assertEqual(counts["info"], 1)
        self.assertEqual(findings[0]["rule"], "BOM_UTF8")
        self.assertEqual(findings[0]["severity"], "info")

    def test_strict_flags_ps1_bom(self):
        findings, counts = scan("crlf-bom", "strict")
        self.assertEqual(counts["errors"], 1)
        proc = subprocess.run(
            [sys.executable, CLI, fixture("crlf-bom"),
             "--bom-policy", "strict"],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 1)

    def test_invalid_utf8_reports_byte_offset(self):
        findings, _ = scan("windows-mess")
        rows = [f for f in findings if f["rule"] == "INVALID_UTF8"]
        self.assertEqual(len(rows), 1)
        self.assertIn("offset 8", rows[0]["evidence"])

    def test_lone_cr_reports_byte_offset(self):
        findings, _ = scan("windows-mess")
        rows = [f for f in findings if f["rule"] == "LONE_CR"]
        self.assertEqual(len(rows), 1)
        self.assertIn("offset 8", rows[0]["evidence"])


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, CLI, *args],
                              capture_output=True, text=True, timeout=30)

    def test_clean_exits_zero(self):
        self.assertEqual(
            self.run_cli(fixture("utf8-clean")).returncode, 0)

    def test_missing_dir_exits_two(self):
        proc = self.run_cli(fixture("does-not-exist"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no such directory", proc.stderr)

    def test_exclude_drops_files(self):
        proc = self.run_cli(fixture("windows-mess"),
                            "--exclude", "latin1.py",
                            "--exclude", "bom.md",
                            "--exclude", "mixed.sh",
                            "--exclude", "lone.txt",
                            "--exclude", "binary.py")
        self.assertEqual(proc.returncode, 0)

    def test_json_mirror_matches_counts(self):
        proc = self.run_cli(fixture("windows-mess"), "--format", "json")
        report = json.loads(proc.stdout)
        self.assertEqual(report["exit"], proc.returncode)
        for key in ("tool", "version", "root", "findings", "counts",
                    "exit"):
            self.assertIn(key, report)
        self.assertEqual(report["counts"]["errors"], 5)


class UnitTests(unittest.TestCase):
    def test_gitattributes_covered(self):
        self.assertTrue(
            textcheck.gitattributes_covered(fixture("utf8-clean")))
        self.assertFalse(
            textcheck.gitattributes_covered(fixture("windows-mess")))

    def test_is_excluded(self):
        self.assertTrue(textcheck.is_excluded("a/b.pyc", ["*.pyc"]))
        self.assertTrue(textcheck.is_excluded("dist/x.js", ["dist/"]))
        self.assertFalse(textcheck.is_excluded("src/a.py", ["*.pyc"]))


if __name__ == "__main__":
    unittest.main()
