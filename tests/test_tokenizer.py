"""Choosing a named token counter, and refusing to pretend when there is none.

The point of naming the tokenizer is that two of them disagree about the same
text. A count filed under the wrong name, or an estimate filed under any name
at all, is worse than no count: it invites a comparison that does not hold.
"""

from __future__ import annotations

import unittest

from yieldpoint.contextrecording import _counter
from yieldpoint.core.policy import Policy
from yieldpoint.tokenizer import PROVIDERS, Counter, resolve


class ResolveCase(unittest.TestCase):
    def test_a_known_provider_and_encoding_resolves(self):
        counter = resolve("tiktoken:o200k_base")
        if counter is None:
            self.skipTest("tiktoken extra not installed")
        self.assertIsInstance(counter, Counter)
        self.assertEqual(counter.name, "tiktoken:o200k_base")
        self.assertGreater(counter.count("hello world"), 0)

    def test_the_name_is_recorded_exactly_as_written(self):
        counter = resolve("  tiktoken:o200k_base  ")
        if counter is None:
            self.skipTest("tiktoken extra not installed")
        self.assertEqual(counter.name, "tiktoken:o200k_base")

    def test_an_unknown_provider_resolves_to_nothing(self):
        self.assertIsNone(resolve("nosuchlib:base"))

    def test_a_provider_without_an_encoding_resolves_to_nothing(self):
        self.assertIsNone(resolve("tiktoken"))
        self.assertIsNone(resolve(""))

    def test_an_unknown_encoding_resolves_to_nothing(self):
        self.assertIsNone(resolve("tiktoken:not-a-real-encoding"))


class PolicyCase(unittest.TestCase):
    def test_a_misspelt_provider_is_reported_not_ignored(self):
        """Silently estimating would leave a repository believing it measured."""
        policy = Policy.from_dict({"metrics": {"tokenizer": "tiktokne:o200k_base"}})
        self.assertEqual(policy.metrics.tokenizer, "")
        self.assertTrue(any("names no known provider" in w for w in policy.warnings),
                        policy.warnings)

    def test_naming_nothing_is_not_a_warning(self):
        policy = Policy.from_dict({"metrics": {}})
        self.assertEqual(policy.metrics.tokenizer, "")
        self.assertEqual([w for w in policy.warnings if "tokenizer" in w], [])

    def test_every_allowlisted_provider_is_accepted(self):
        for provider in PROVIDERS:
            policy = Policy.from_dict({"metrics": {"tokenizer": f"{provider}:enc"}})
            self.assertEqual(policy.metrics.tokenizer, f"{provider}:enc")


class CounterSelectionCase(unittest.TestCase):
    def test_an_explicit_counter_wins_over_the_policy(self):
        policy = Policy.from_dict({"metrics": {"tokenizer": "tiktoken:o200k_base"}})
        count, name = _counter(policy, len, "caller")
        self.assertEqual((count, name), (len, "caller"))

    def test_no_policy_tokenizer_means_estimating(self):
        count, name = _counter(Policy.from_dict({"metrics": {}}), None, "")
        self.assertIsNone(count)
        self.assertEqual(name, "")

    def test_an_unloadable_tokenizer_estimates_rather_than_mislabels(self):
        """Falling back must never file an estimate under a tokenizer's name."""
        policy = Policy.from_dict({"metrics": {"tokenizer": "tiktoken:not-real"}})
        count, name = _counter(policy, None, "")
        self.assertIsNone(count)
        self.assertEqual(name, "")


if __name__ == "__main__":
    unittest.main()
