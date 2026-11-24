import ssl
import unittest

from extract.freshservice import FreshserviceClient, FreshserviceError, parse_next_link, tls_context


class LinkHeaderTests(unittest.TestCase):
    def test_parses_next(self):
        header = '<https://example.freshservice.com/api/v2/tickets?page=2>; rel="next"'
        self.assertEqual(parse_next_link(header), "https://example.freshservice.com/api/v2/tickets?page=2")

    def test_no_next(self):
        self.assertIsNone(parse_next_link(None))
        self.assertIsNone(parse_next_link(""))


class ClientSafetyTests(unittest.TestCase):
    def test_requires_https(self):
        with self.assertRaises(ValueError):
            FreshserviceClient("http://example.freshservice.com", "fake-key")

    def test_refuses_other_hosts(self):
        client = FreshserviceClient("https://example.freshservice.com", "fake-key")
        with self.assertRaises(FreshserviceError):
            client._check_host("https://evil.example.org/api/v2/tickets")

    def test_has_no_write_methods(self):
        for name in ("post", "put", "patch", "delete"):
            self.assertFalse(hasattr(FreshserviceClient, name))

    def test_tls_still_verifies_certificates_and_hostname(self):
        context = tls_context()
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertFalse(context.verify_flags & ssl.VERIFY_X509_STRICT)


if __name__ == "__main__":
    unittest.main()
