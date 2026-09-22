"""Diagnostics over LSP, compared against the committed file.

A server that reported "this file is 1,400 lines" every time you opened it
would be the absolute-state checker the review complained about, wearing a
different hat. The before-state comes from git, so an editor shows the same
attribution the hook and CI do.
"""

import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from yieldpoint.core.policy import Policy, Structure
from yieldpoint.core.verdict import Confidence, Finding, Status
from yieldpoint.lsp import ERROR, INFORMATION, WARNING, path_of, serve, severity_for


def _frame(obj):
    body = json.dumps(obj).encode()
    return f"Content-Length: {len(body)}\r\n\r\n".encode() + body


def _messages(raw):
    out = []
    for part in raw.split(b"Content-Length:")[1:]:
        out.append(json.loads(part.split(b"\r\n\r\n", 1)[1]))
    return out


def _finding(status=Status.REPAIR, confidence=Confidence.EXACT, rule="r"):
    return Finding(rule=rule, status=status, file="a.py", line=3, detail="d",
                   prescription="p", confidence=confidence)


class TestSeverity(unittest.TestCase):
    """A red squiggle is a claim the code is wrong."""

    def test_a_blocking_exact_finding_is_an_error(self):
        self.assertEqual(severity_for(_finding(status=Status.BLOCK), False), ERROR)

    def test_a_repair_is_a_warning(self):
        self.assertEqual(severity_for(_finding(), False), WARNING)

    def test_a_lexical_finding_is_only_information(self):
        self.assertEqual(
            severity_for(_finding(confidence=Confidence.LEXICAL), False), INFORMATION)

    def test_an_advisory_rule_is_information_however_severe(self):
        self.assertEqual(severity_for(_finding(status=Status.BLOCK), True), INFORMATION)


class TestUri(unittest.TestCase):
    def test_a_file_uri_becomes_a_path(self):
        self.assertEqual(path_of("file:///tmp/a.py"), "/tmp/a.py")

    def test_percent_escapes_are_undone(self):
        self.assertEqual(path_of("file:///tmp/my%20file.py"), "/tmp/my file.py")


class TestProtocol(unittest.TestCase):
    def _serve(self, *messages, root="."):
        out = io.BytesIO()
        serve(io.BytesIO(b"".join(_frame(m) for m in messages)), out, root=root)
        return _messages(out.getvalue())

    def test_initialize_announces_the_server(self):
        replies = self._serve({"jsonrpc": "2.0", "id": 1, "method": "initialize"},
                              {"jsonrpc": "2.0", "method": "exit"})
        self.assertEqual(replies[0]["result"]["serverInfo"]["name"], "yieldpoint")

    def test_it_asks_for_the_text_on_save(self):
        replies = self._serve({"jsonrpc": "2.0", "id": 1, "method": "initialize"},
                              {"jsonrpc": "2.0", "method": "exit"})
        sync = replies[0]["result"]["capabilities"]["textDocumentSync"]
        self.assertIs(sync["save"]["includeText"], True)

    def test_shutdown_is_answered_before_exit(self):
        replies = self._serve({"jsonrpc": "2.0", "id": 2, "method": "shutdown"},
                              {"jsonrpc": "2.0", "method": "exit"})
        self.assertIsNone(replies[0]["result"])

    def test_end_of_input_ends_the_session(self):
        self.assertEqual(self._serve(), [])

    def test_a_document_with_no_uri_is_ignored_rather_than_crashing(self):
        replies = self._serve(
            {"jsonrpc": "2.0", "method": "textDocument/didSave",
             "params": {"textDocument": {}}},
            {"jsonrpc": "2.0", "method": "exit"})
        self.assertEqual(replies, [])


class TestAgainstTheCommittedFile(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        for args in (["init", "-q", "-b", "main", "."],
                     ["config", "user.email", "t@t"], ["config", "user.name", "T"]):
            subprocess.run(["git", *args], cwd=self.root, capture_output=True)
        (self.root / "a.py").write_text(
            "def f():\n    try:\n        go()\n    except KeyError:\n        return 1\n")
        subprocess.run(["git", "add", "-A"], cwd=self.root, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=self.root,
                       capture_output=True)

    def _diagnostics(self, text=None):
        out = io.BytesIO()
        uri = f"file://{self.root / 'a.py'}"
        params = {"textDocument": {"uri": uri}}
        if text is not None:
            params["text"] = text
        serve(io.BytesIO(
            _frame({"jsonrpc": "2.0", "method": "textDocument/didSave",
                    "params": params})
            + _frame({"jsonrpc": "2.0", "method": "exit"})), out, root=self.root)
        published = [m for m in _messages(out.getvalue())
                     if m.get("method") == "textDocument/publishDiagnostics"]
        return published[0]["params"]["diagnostics"] if published else []

    def test_a_weakened_handler_is_diagnosed(self):
        found = self._diagnostics(
            "def f():\n    try:\n        go()\n    except Exception:\n        pass\n")
        self.assertEqual([d["code"] for d in found], ["swallowed_exception"])

    def test_the_diagnostic_carries_the_fix_as_well_as_the_finding(self):
        found = self._diagnostics(
            "def f():\n    try:\n        go()\n    except Exception:\n        pass\n")
        self.assertIn("\n", found[0]["message"])

    def test_an_unchanged_file_is_clean(self):
        """Reporting inherited shape on every open would be the absolute-state
        checker the review complained about, in an editor."""
        self.assertEqual(self._diagnostics(), [])

    def test_a_diagnostic_is_anchored_zero_based(self):
        found = self._diagnostics(
            "def f():\n    try:\n        go()\n    except Exception:\n        pass\n")
        self.assertEqual(found[0]["range"]["start"]["line"], 3)


if __name__ == "__main__":
    unittest.main()
