from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from scripts.v2_2cbv_real_paired_corpus_probe import (
    ProbeError,
    _bsv_round_pgn_anchors,
    _content_disposition_filename,
    _expected_suffix_confident,
    parse_anchors,
    read_bounded,
    run_probe,
)


class TwoCbvRealPairedCorpusProbeTests(unittest.TestCase):
    def test_anchor_parser_normalizes_visible_text_without_inventing_targets(self) -> None:
        anchors = parse_anchors(
            '<a href="files/event.pgn"> PGN  Datei <span>alle</span> Runden </a>'
            '<a href="files/event.2cbv">2CBV Datei alle Runden</a>'
        )
        self.assertEqual(len(anchors), 2)
        self.assertEqual(anchors[0].href, "files/event.pgn")
        self.assertEqual(anchors[0].text, "PGN Datei alle Runden")
        self.assertEqual(anchors[1].href, "files/event.2cbv")

    def test_bsv_round_filter_requires_exact_mklasse_round_names(self) -> None:
        html = "".join(
            f'<a href="games/2024-BSV-BEM24-M-Klasse-R{round_no}.pgn">round {round_no}</a>'
            for round_no in range(1, 10)
        ) + '<a href="games/2024-BSV-BEM24-QT-R1.pgn">wrong event</a>'
        anchors = _bsv_round_pgn_anchors(html)
        self.assertEqual(len(anchors), 9)
        self.assertTrue(anchors[0].href.endswith("R1.pgn"))
        self.assertTrue(anchors[-1].href.endswith("R9.pgn"))

    def test_bounded_reader_rejects_payload_larger_than_limit(self) -> None:
        with self.assertRaises(ProbeError):
            read_bounded(io.BytesIO(b"12345"), 4)
        self.assertEqual(read_bounded(io.BytesIO(b"1234"), 4), b"1234")

    def test_download_identity_requires_expected_suffix_in_url_or_content_disposition(self) -> None:
        headers = {"content-disposition": 'attachment; filename="BEM24.2cbv"'}
        self.assertTrue(
            _expected_suffix_confident(
                "https://download.example/object?id=1", headers, ".2cbv"
            )
        )
        self.assertEqual(_content_disposition_filename(headers), "BEM24.2cbv")
        self.assertFalse(
            _expected_suffix_confident(
                "https://download.example/preview", {"content-type": "text/html"}, ".2cbv"
            )
        )

    def test_probe_can_qualify_paired_lead_but_never_acceptance_or_redistribution(self) -> None:
        mattnetz = (
            '<a href="https://files.example/BEM24.pgn">PGN Datei alle Runden</a>'
            '<a href="https://files.example/BEM24.2cbv">2CBV Datei alle Runden</a>'
        )
        bsv = "".join(
            f'<a href="https://bsv.example/2024-BSV-BEM24-M-Klasse-R{round_no}.pgn">R{round_no}</a>'
            for round_no in range(1, 10)
        )

        def fake_html(url: str) -> str:
            return mattnetz if "mattnetz" in url else bsv

        def fake_download(url: str, suffix: str) -> dict[str, object]:
            return {
                "url": url,
                "reachable": True,
                "size_bytes": 10,
                "sha256": "a" * 64,
                "payload_identity_confident": True,
            }

        with patch(
            "scripts.v2_2cbv_real_paired_corpus_probe._fetch_html",
            side_effect=fake_html,
        ), patch(
            "scripts.v2_2cbv_real_paired_corpus_probe._public_download_evidence",
            side_effect=fake_download,
        ):
            report = run_probe()

        self.assertTrue(report["paired_corpus_lead_qualified"])
        self.assertFalse(report["acceptance_ready"])
        self.assertFalse(report["support_promotion_allowed"])
        self.assertFalse(report["repository_ci_redistribution_rights_qualified"])
        self.assertFalse(report["decoder_qualified"])
        self.assertFalse(report["payload_bytes_persisted"])
        self.assertFalse(report["payload_bytes_uploaded_as_artifact"])


if __name__ == "__main__":
    unittest.main()
