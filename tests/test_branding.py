"""The mark, and knowing when to be quiet.

The look is a preference. *When it appears* is a correctness question: a banner
on stdout corrupts every pipeline reading it, and escape codes in a CI log are
worse than none. The difference between a tool that feels established and one
that feels noisy is mostly this.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from yieldpoint import branding

ROOT = Path(__file__).resolve().parent.parent


class _Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


class _Pipe(io.StringIO):
    def isatty(self) -> bool:
        return False


class TestWhenItStaysQuiet(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, {"TERM": "xterm-256color"},
                                    clear=False)
        self._env.start()
        for name in ("NO_COLOR", "CI"):
            os.environ.pop(name, None)

    def tearDown(self):
        self._env.stop()

    def test_a_pipe_gets_nothing(self):
        self.assertEqual(branding.banner("review", _Pipe()), "")

    def test_a_terminal_gets_the_mark(self):
        self.assertIn("yieldpoint", branding.banner("review", _Tty()))

    def test_no_color_is_honoured(self):
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}):
            self.assertEqual(branding.banner("review", _Tty()), "")

    def test_ci_is_honoured(self):
        """A build log full of escape codes is worse than a plain one."""
        with mock.patch.dict(os.environ, {"CI": "true"}):
            self.assertEqual(branding.banner("review", _Tty()), "")

    def test_a_dumb_terminal_is_honoured(self):
        with mock.patch.dict(os.environ, {"TERM": "dumb"}):
            self.assertEqual(branding.banner("review", _Tty()), "")

    def test_a_stream_that_cannot_be_asked_is_treated_as_a_pipe(self):
        self.assertFalse(branding.wants_colour(object()))


class TestTheMark(unittest.TestCase):
    def test_the_yield_point_is_coloured_apart_from_the_curve(self):
        """The whole idea is that one moment on the curve is different."""
        curve = branding.mark(branding.COLOUR)
        self.assertIn(branding._AMBER, curve)
        self.assertIn(branding._STEEL, curve)

    def test_it_reads_without_colour_too(self):
        plain = branding.mark(branding.PLAIN)
        self.assertNotIn("\033", plain)
        self.assertIn("●", plain)

    def test_the_palette_is_all_or_nothing(self):
        self.assertTrue(branding.COLOUR.coloured)
        self.assertFalse(branding.PLAIN.coloured)
        self.assertEqual(branding.PLAIN.steel, "")


class TestTheCliStaysParseable(unittest.TestCase):
    """The rules that break pipelines if they regress."""

    def _run(self, args, tty_env=None):
        env = dict(os.environ, TERM="xterm-256color", **(tty_env or {}))
        env.pop("NO_COLOR", None)
        env.pop("CI", None)
        return subprocess.run(
            [sys.executable, "-m", "yieldpoint", *args],
            capture_output=True, text=True, timeout=120, cwd=str(ROOT), env=env,
        )

    def test_json_output_parses(self):
        """--json makes stdout a document, not a report: keys a pipeline reads."""
        import json

        done = self._run(["check", "--path", "t.py",
                          "--before", ".yieldpoint.json",
                          "--after", ".yieldpoint.json", "--json"])
        parsed = json.loads(done.stdout)
        self.assertEqual(parsed["checked"], ["t.py"])
        self.assertEqual(parsed["status"], "pass")
        self.assertIn("schema_version", parsed)
        self.assertEqual(parsed["findings"], [])

    def test_stdout_never_carries_escape_codes_when_piped(self):
        done = self._run(["review"])
        self.assertNotIn("\033", done.stdout)

    def test_the_mcp_server_emits_protocol_only(self):
        done = subprocess.run(
            [sys.executable, "-m", "yieldpoint", "mcp"],
            input='{"jsonrpc":"2.0","id":1,"method":"ping","params":{}}\n',
            capture_output=True, text=True, timeout=120, cwd=str(ROOT),
        )
        import json

        for line in done.stdout.splitlines():
            json.loads(line)
        self.assertEqual(done.stderr.strip(), "")

    def test_the_hook_never_prints_a_banner(self):
        """Its stderr is fed back to an agent; a logo there is noise."""
        done = subprocess.run(
            [sys.executable, "-m", "yieldpoint", "hook"],
            input="{}", capture_output=True, text=True, timeout=120,
            cwd=str(ROOT),
        )
        self.assertNotIn("yieldpoint\n", done.stderr)
        self.assertNotIn("\033", done.stderr)


if __name__ == "__main__":
    unittest.main()
