"""Tests for the search provider fallback chain (Tavily -> Brave)."""

import unittest
from unittest.mock import patch

import requests

from functions.search import _run_search


def _response(json_payload, status=200):
    class _Resp:
        status_code = status

        def json(self):
            return json_payload

        def raise_for_status(self):
            if status >= 400:
                raise requests.HTTPError(f"{status} error")

    return _Resp()


TAVILY_PAYLOAD = {
    "results": [
        {"title": "T1", "url": "https://t.example/1", "content": "tavily snippet"},
    ]
}
BRAVE_PAYLOAD = {
    "web": {
        "results": [
            {
                "title": "B1",
                "url": "https://b.example/1",
                "description": "brave snippet",
                "extra_snippets": ["extra"],
            },
        ]
    }
}


class SearchProviderChainTests(unittest.TestCase):
    @patch.dict("os.environ", {"TAVILY_API_KEY": "tv", "BRAVE_API_KEY": "br"})
    @patch("functions.search.requests.post", return_value=_response(TAVILY_PAYLOAD))
    def test_tavily_preferred_when_configured(self, post_mock):
        provider, results = _run_search("query")
        self.assertEqual(provider, "tavily")
        self.assertEqual(results[0]["title"], "T1")
        self.assertEqual(results[0]["description"], "tavily snippet")
        # Bearer auth header, POST body carries the query
        self.assertIn("Bearer tv", post_mock.call_args.kwargs["headers"]["Authorization"])
        self.assertEqual(post_mock.call_args.kwargs["json"]["query"], "query")

    @patch.dict("os.environ", {"TAVILY_API_KEY": "tv", "BRAVE_API_KEY": "br"})
    @patch("functions.search.requests.get", return_value=_response(BRAVE_PAYLOAD))
    @patch("functions.search.requests.post", return_value=_response({}, status=429))
    def test_falls_back_to_brave_on_tavily_rate_limit(self, _post_mock, _get_mock):
        provider, results = _run_search("query")
        self.assertEqual(provider, "brave")
        self.assertEqual(results[0]["title"], "B1")
        self.assertEqual(results[0]["extra_snippets"], ["extra"])

    @patch.dict("os.environ", {"BRAVE_API_KEY": "br"}, clear=False)
    @patch("functions.search.requests.get", return_value=_response(BRAVE_PAYLOAD))
    def test_brave_used_directly_without_tavily_key(self, _get_mock):
        with patch.dict("os.environ"):
            import os
            os.environ.pop("TAVILY_API_KEY", None)
            provider, _ = _run_search("query")
        self.assertEqual(provider, "brave")

    def test_no_provider_configured_raises(self):
        with patch.dict("os.environ"):
            import os
            os.environ.pop("TAVILY_API_KEY", None)
            os.environ.pop("BRAVE_API_KEY", None)
            with self.assertRaises(RuntimeError) as ctx:
                _run_search("query")
        self.assertIn("no search provider", str(ctx.exception))

    @patch.dict("os.environ", {"TAVILY_API_KEY": "tv", "BRAVE_API_KEY": "br"})
    @patch("functions.search.requests.get", return_value=_response({}, status=429))
    @patch("functions.search.requests.post", return_value=_response({}, status=429))
    def test_all_providers_failing_raises(self, _post_mock, _get_mock):
        with self.assertRaises(RuntimeError) as ctx:
            _run_search("query")
        self.assertIn("all providers", str(ctx.exception))
