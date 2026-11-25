"""Practice lookups and 403 handling (fake data only)."""

import re
import unittest

from extract.fetch import Fetcher
from extract.freshservice import FreshserviceError
from extract.practices import DEPARTMENT_NAMES


class ForbiddenClient:
    def __init__(self):
        self.calls = []

    def get(self, path, params=None):
        self.calls.append(path)
        raise FreshserviceError(f"HTTP 403 for GET /api/v2/{path}")


class PracticeTests(unittest.TestCase):
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


class NameLookupClient:
    """Finds people by first and last name like Freshservice's requester and agent searches."""
    PEOPLE = {
        ("requesters", "Jane", "Example"): [{"id": 2, "first_name": "Jane", "last_name": "Example",
                                             "primary_email": "jane.example@example.com", "department_ids": [14000218908]}],
        ("requesters", "Sam", "Twin"): [{"id": 3, "first_name": "Sam", "last_name": "Twin", "department_ids": []},
                                        {"id": 4, "first_name": "Sam", "last_name": "Twin", "department_ids": []}],
        ("agents", "Alex", "Tech"): [{"id": 1, "first_name": "Alex", "last_name": "Tech",
                                      "primary_email": "alex.tech@example.com", "department_ids": [14000291100]}],
        ("requesters", "Mary Ann", "Example"): [{"id": 5, "first_name": "Mary Ann", "last_name": "Example",
                                                 "primary_email": "mary.example@example.com", "department_ids": []}],
    }

    def __init__(self):
        self.queries = []

    def get(self, path, params=None):
        self.queries.append((path, (params or {}).get("query")))
        query = (params or {}).get("query") or ""
        found = re.search(r"first_name:'(.+?)' AND last_name:'(.+?)'", query)
        items = self.PEOPLE.get((path, found[1], found[2]), []) if found else []
        return {path: items}


class PersonByNameTests(unittest.TestCase):
    def test_one_match_gives_the_person_with_their_own_practice(self):
        fetcher = Fetcher(NameLookupClient())
        jane = fetcher.person_by_name("Jane Example")
        self.assertEqual((jane["name"], jane["email"], jane["department"]), ("Jane Example", "jane.example@example.com", "CMH"))
        technician = fetcher.person_by_name("Alex Tech")  # an agent, found by the second search
        self.assertEqual(technician["department"], "EBC")

    def test_nobody_or_several_matches_give_nothing(self):
        fetcher = Fetcher(NameLookupClient())
        self.assertIsNone(fetcher.person_by_name("Sam Twin"), "two people share the name")
        self.assertIsNone(fetcher.person_by_name("Nobody Known"))
        self.assertIsNone(fetcher.person_by_name("Madonna"), "one word is not a full name")

    def test_a_middle_name_is_tried_both_ways(self):
        self.assertEqual(Fetcher(NameLookupClient()).person_by_name("Mary Ann Example")["id"], 5)

    def test_quotes_are_never_put_into_a_query_and_answers_are_cached(self):
        client = NameLookupClient()
        fetcher = Fetcher(client)
        self.assertIsNone(fetcher.person_by_name("Pat O'Brien"))
        self.assertEqual(client.queries, [])
        fetcher.person_by_name("Jane Example")
        fetcher.person_by_name("jane  example")
        self.assertEqual(len(client.queries), 2, "one requester and one agent search, then the cache")


if __name__ == "__main__":
    unittest.main()
