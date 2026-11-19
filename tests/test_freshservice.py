import unittest

from extract.freshservice import FreshserviceClient, FreshserviceError, parse_next_link


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


if __name__ == "__main__":
    unittest.main()
