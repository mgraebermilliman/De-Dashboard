"""Certificate of Destruction parsing (fake text only; no real certificate content)."""

import re
import unittest
from unittest import mock

from extract import cod
from extract.fetch import Fetcher
from extract.freshservice import FreshserviceError
from extract.tables import MODEL_LINE_MIN_REQUESTS, REQUESTS_COLUMNS, _fill_models, cod_columns

# KillDisk draws each line twice, so the extracted text repeats every line.
FAKE_TEXT = "\n".join(
    line for pair in [
        "ERASE CERTIFICATE", "Computer", "FAKE1234", "Date:", "January 2, 2026", "Time:", "10:15",
        "Attributes", "Erase Method:", "Fake Method, 1 pass", "Disk Information", "Name:", "PhysicalDrive0",
        "Size:", "477 GB", "Results", "Result:", "Erased", "Errors:", "No Errors",
        "System Information", "OS:", "Windows 11 (10.0)", "Hardware Information", "Processor:",
        "Fake CPU 3000", "Motherboard:", "ACME 1234XYZ", "BIOS:", "ACME BIOS 1.0", "Memory:", "16.0 GB",
        "BIOS Serial:", "FAKE1234",
    ] for line in (pair, pair))


class ParseTests(unittest.TestCase):
    def test_letter_spaced_headings_and_colon_after_computer(self):
        text = re.sub(r"(?m)^Results$", "R e s ult s", FAKE_TEXT)
        text = re.sub(r"(?m)^Computer$", "Computer:", text)
        fields = cod.parse_cod_text(text)
        self.assertEqual(fields["COD Erase Result"], "Erased")
        self.assertEqual(fields["COD Device Serial"], "FAKE1234")
    def test_reads_fields_from_repeated_lines(self):
        fields = cod.parse_cod_text(FAKE_TEXT)
        self.assertEqual(fields["COD Erase Date"], "2026-01-02")
        self.assertEqual(fields["COD Erase Result"], "Erased")
        self.assertEqual(fields["COD Erase Errors"], "No Errors")
        self.assertEqual(fields["COD Motherboard"], "ACME 1234XYZ")
        self.assertEqual(fields["COD Drive Size"], "477 GB")
        self.assertEqual(fields["COD Device Serial"], "FAKE1234")

    def test_unrecognized_layout_is_empty(self):
        self.assertEqual(cod.parse_cod_text("Some other PDF\nNothing useful"), {})


class ColumnTests(unittest.TestCase):
    @staticmethod
    def model_row(model=None, board=None, pc=None, cert=None):
        return {"Model": model, "PC Make and Model": None, "COD Motherboard": board, "Most Recent PC Name": pc,
                "Certificate File": cert, "Device Type": "Unknown", "Model Line": None, "Model Source": None,
                "Model Group": None}

    def test_model_from_typed_name_pc_name_then_machine_type(self):
        row = self.model_row
        rows = [row("ThinkPad X1 Carbon Gen 11", "LENOVO 21HLS1WQ00"),   # typed on the form
                row(None, "LENOVO 21HLXXXX00"),                          # same machine type as the first
                row(None, "LENOVO 20ABS1MT00", pc="MILWI-T15-JF"),       # the PC name says T15
                row(None, "LENOVO 20ABS1MT01"),                          # 20AB is now known to be a T15
                row(None, "LENOVO 20CDS1MT00"),                          # nothing says what 20CD is
                row(None, None, cert="Certificate-CMH-P14S-JF-PF4H490T-0025-Success-2025-11-20-15-49-37.pdf"),
                row(None, None)]
        _fill_models(rows)
        got = [(r["Model"], r["Model Source"]) for r in rows]
        self.assertEqual(got, [
            ("ThinkPad X1 Carbon Gen 11", "Ticket"), ("ThinkPad X1 Carbon", "Certificate (same machine type)"),
            ("ThinkPad T15", "PC name"), ("ThinkPad T15", "Certificate (same machine type)"),
            ("Lenovo machine type 20CD", "Machine type only"), ("ThinkPad P14s", "PC name"),
            ("Not recorded", "Not recorded")])
        self.assertEqual(rows[1]["Device Type"], "Laptop")
        self.assertEqual(rows[0]["Model Line"], "ThinkPad X1 Carbon")
        self.assertEqual([r["Model Group"] for r in rows[4:]], ["Not identified", "Other ThinkPad", "Not identified"])

    def test_machine_type_with_two_different_models_is_not_guessed(self):
        row = self.model_row
        rows = [row("ThinkPad T14s", "LENOVO 20ABS1"), row("ThinkPad T15", "LENOVO 20ABS2"), row(None, "LENOVO 20ABS3")]
        _fill_models(rows)
        self.assertEqual((rows[2]["Model"], rows[2]["Model Source"]), ("Lenovo machine type 20AB", "Machine type only"))

    def test_chart_groups_name_common_lines_and_join_rare_ones_to_their_family(self):
        row = self.model_row
        common = MODEL_LINE_MIN_REQUESTS
        rows = [row("ThinkPad T14s Gen 2") for _ in range(common)] + [row("ThinkPad T580"), row("ThinkCentre M910q"),
                                                                    row("Dell Latitude 7410"), row("Microsoft Surface Pro 8"),
                                                                    row("HP Elitebook 840 G8"), row("Macbook Pro A2251")]
        _fill_models(rows)
        self.assertEqual([r["Model Group"] for r in rows],
                         ["ThinkPad T14s"] * common + ["Other ThinkPad", "Other ThinkCentre", "Dell", "Surface",
                                                  "HP EliteBook", "Other models"])

    def test_serial_match_ignores_case_and_spaces(self):
        details = cod.parse_cod_text(FAKE_TEXT)
        self.assertEqual(cod_columns(details, "fake 1234")["COD Serial Matches Ticket"], "Yes")
        self.assertEqual(cod_columns(details, "OTHER99")["COD Serial Matches Ticket"], "No")
        self.assertIsNone(cod_columns(details, None)["COD Serial Matches Ticket"])

    def test_no_certificate_gives_blank_columns(self):
        row = cod_columns(None, "FAKE1234")
        self.assertEqual({k for k in row}, {k for k in REQUESTS_COLUMNS if k.startswith("COD ")})
        self.assertTrue(all(v is None for v in row.values()))


class FetcherTests(unittest.TestCase):
    FILES = [{"id": 7, "name": "Certificate-FAKE-FAKE1234-0001-Success-2026-01-02-10-15-00.pdf",
              "url": "https://example.freshservice.com/x"}]

    def test_downloads_once_then_uses_cache(self):
        client = mock.Mock()
        fetcher = Fetcher(client)
        with mock.patch.object(cod, "pdf_text", return_value=FAKE_TEXT):
            self.assertEqual(fetcher.certificate_details(self.FILES)["COD Erase Result"], "Erased")
            self.assertEqual(fetcher.certificate_details(self.FILES)["COD Erase Result"], "Erased")
        self.assertEqual(client.download.call_count, 1)

    def test_missing_pdf_reader_is_noted_not_fatal(self):
        fetcher = Fetcher(mock.Mock())
        with mock.patch.object(cod, "pdf_text", side_effect=cod.CodUnavailable("pypdf is not installed")):
            self.assertIsNone(fetcher.certificate_details(self.FILES))
        self.assertIn("pypdf is not installed", " ".join(fetcher.notes))

    def test_download_failure_is_recorded_and_skipped(self):
        client = mock.Mock()
        client.download.side_effect = FreshserviceError("HTTP 403 downloading an attachment")
        fetcher = Fetcher(client)
        self.assertIsNone(fetcher.certificate_details(self.FILES))
        self.assertIn("Certificate lookups failed", " ".join(fetcher.notes))


if __name__ == "__main__":
    unittest.main()
