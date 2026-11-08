from email.message import Message
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import xml.etree.ElementTree as ET

from scripts import refresh_github_stats as snapshot


CARD = snapshot.DESTINATION.read_bytes()


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.destination = Path(self.directory.name) / "github-stats.svg"
        self.destination.write_bytes(CARD)

    def assert_saved_card_unchanged(self):
        self.assertEqual(self.destination.read_bytes(), CARD)
        self.assertEqual(list(self.destination.parent.iterdir()), [self.destination])

    def test_complete_card_is_saved_and_unchanged_card_is_not_rewritten(self):
        # A formatting-only change preserves all six metrics and exercises storage.
        changed_card = CARD + b"\n"
        changed, metrics = snapshot.refresh(self.destination, lambda: changed_card)
        self.assertTrue(changed)
        self.assertEqual(self.destination.read_bytes(), changed_card)
        self.assertGreater(metrics["commits"], 0)
        with patch.object(snapshot.os, "replace") as replace:
            changed, _ = snapshot.refresh(self.destination, lambda: changed_card)
        self.assertFalse(changed)
        replace.assert_not_called()

    def test_network_timeout_is_retried_then_preserves_previous_card(self):
        with patch.object(snapshot, "fetch_card", side_effect=TimeoutError) as download:
            pauses = []
            with self.assertRaisesRegex(RuntimeError, "keeping the saved card"):
                snapshot.refresh(self.destination, download, pauses.append)
        self.assertEqual(download.call_count, 3)
        self.assertEqual(pauses, [5, 10])
        self.assert_saved_card_unchanged()

    def test_retry_can_recover_without_publishing_partial_response(self):
        with patch.object(
            snapshot, "fetch_card", side_effect=[urllib.error.URLError("offline"), CARD]
        ) as download:
            changed, _ = snapshot.refresh(self.destination, download, lambda _: None)
        self.assertFalse(changed)
        self.assert_saved_card_unchanged()

    def test_error_card_empty_card_and_partial_xml_cannot_replace_saved_card(self):
        for invalid in [
            b"",
            b'<svg xmlns="http://www.w3.org/2000/svg"><text>Try again later</text></svg>',
            CARD[: len(CARD) // 2],
            b"<html>Gateway timeout</html>",
            b"x" * (snapshot.MAX_BYTES + 1),
        ]:
            with self.subTest(invalid=invalid[:30]):
                with self.assertRaises((ValueError, ET.ParseError)):
                    snapshot.refresh(self.destination, lambda: invalid)
                self.assert_saved_card_unchanged()

    def test_executable_and_external_content_is_rejected(self):
        for insertion in [
            b"<script>alert(1)</script>",
            b'<image href="https://example.com/pixel"/>',
            b'<foreignObject><div>hidden</div></foreignObject>',
            b'<style>@import "https://example.com/font.css";</style>',
            b'<style>.stat {fill: url(https://example.com/paint)}</style>',
            b'<style>.stat {fill: u\\72l(https://example.com/paint)}</style>',
            b'<g onclick="alert(1)"/>',
            b'<a href="https://example.com">link</a>',
            b'<g xml:base="https://example.com"/>',
        ]:
            invalid = CARD.replace(b"</svg>", insertion + b"</svg>")
            with self.subTest(insertion=insertion):
                with self.assertRaises(ValueError):
                    snapshot.refresh(self.destination, lambda: invalid)
                self.assert_saved_card_unchanged()

    def test_xml_entities_wrong_profile_and_invalid_counts_are_rejected(self):
        negative_count = ET.fromstring(CARD)
        negative_count.find('.//*[@data-testid="prs"]').text = "-1"
        for invalid in [
            b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]>' + CARD,
            CARD.replace(b"Ramez Weissa", b"Other Profile"),
            CARD.replace(b'data-testid="prs"', b'data-testid="missing"'),
            CARD.replace(b'data-testid="prs"', b'data-testid="commits"'),
            ET.tostring(negative_count),
        ]:
            with self.subTest(invalid=invalid[:30]):
                with self.assertRaises(ValueError):
                    snapshot.refresh(self.destination, lambda: invalid)
                self.assert_saved_card_unchanged()

    def test_failed_atomic_replace_keeps_previous_card_and_cleans_temporary_file(self):
        with patch.object(snapshot.os, "replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                snapshot.refresh(self.destination, lambda: CARD + b"\n")
        self.assert_saved_card_unchanged()

    def test_download_sends_no_credentials_and_bounds_response(self):
        headers = Message()
        headers["Content-Type"] = "image/svg+xml; charset=utf-8"
        with patch.object(snapshot.urllib.request, "build_opener") as build:
            response = build.return_value.open.return_value.__enter__.return_value
            response.status = 200
            response.headers = headers
            response.read.return_value = CARD
            with patch.dict("os.environ", {"GH_TOKEN": "secret", "PROFILE_READ_TOKEN": "private"}):
                self.assertEqual(snapshot.fetch_card(), CARD)
        request = build.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, snapshot.SOURCE)
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(set(request.headers), {"Accept", "User-agent"})
        response.read.assert_called_once_with(snapshot.MAX_BYTES + 1)
        self.assertIsInstance(build.call_args.args[0], snapshot.NoRedirect)

    def test_redirect_is_rejected_instead_of_fetching_another_destination(self):
        with self.assertRaisesRegex(ValueError, "redirected"):
            snapshot.NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.com")

    def test_success_response_with_wrong_content_type_is_rejected(self):
        headers = Message()
        headers["Content-Type"] = "text/html"
        with patch.object(snapshot.urllib.request, "build_opener") as build:
            response = build.return_value.open.return_value.__enter__.return_value
            response.status = 200
            response.headers = headers
            with self.assertRaises(ValueError):
                snapshot.fetch_card()
            response.read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
