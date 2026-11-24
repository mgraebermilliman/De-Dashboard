"""Practice lookups and 403 handling (fake data only)."""

import unittest

from extract.fetch import Fetcher
from extract.freshservice import FreshserviceError
from extract.practices import DEPARTMENT_NAMES, practice_from_dn


class ForbiddenClient:
    def __init__(self):
        self.calls = []

    def get(self, path, params=None):
        self.calls.append(path)
        raise FreshserviceError(f"HTTP 403 for GET /api/v2/{path}")


class PracticeTests(unittest.TestCase):
    def test_practice_from_dn_picks_practice_ou(self):
        self.assertEqual(practice_from_dn("CN=A,OU=Users,OU=Milwaukee,OU=CMH,DC=milliman,DC=com"), "CMH")
        self.assertEqual(practice_from_dn("CN=A,OU=Users,DC=milliman,DC=com"), None)
        self.assertIsNone(practice_from_dn(None))

    def test_local_department_table_avoids_api(self):
        client = ForbiddenClient()
        fetcher = Fetcher(client)
        self.assertEqual(fetcher.department_name(14000218908), DEPARTMENT_NAMES[14000218908])
        self.assertEqual(client.calls, [])

    def test_lookups_stop_after_first_403(self):
        client = ForbiddenClient()
        fetcher = Fetcher(client)
        for user_id in (1, 2, 3):
            self.assertIsNone(fetcher.user_by_id(user_id))
        for department_id in (7, 8):
            self.assertIsNone(fetcher.department_name(department_id))
        self.assertEqual(client.calls, ["requesters/1", "agents/1", "departments/7"])
        self.assertTrue(any("HTTP 403" in n for n in fetcher.notes))

    def test_recipient_id_resolved_from_ticket_people(self):
        fetcher = Fetcher(ForbiddenClient())
        jane = {"id": 2, "name": "Jane Example", "email": "jane.example@example.com", "department": None}
        self.assertEqual(fetcher.resolve_person(2, {2: jane}), jane)
        self.assertEqual(fetcher.resolve_person(9, {2: jane})["name"], "Unknown user (ID 9)")


if __name__ == "__main__":
    unittest.main()
