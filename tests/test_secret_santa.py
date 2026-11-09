import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import secret_santa as ss  # noqa: E402

P = ss.Participant


def check(test, people, pairs):
    keys = {p.key for p in people}
    test.assertEqual(set(pairs), keys)
    test.assertEqual({g.key for g in pairs.values()}, keys)  # each drawn once
    for p in people:
        r = pairs[p.key]
        test.assertNotEqual(r.key, p.key)
        test.assertNotEqual(r.key, p.spouse_key)
        test.assertNotEqual(r.spouse_key, p.key)  # symmetric spouse rule


class TestPairings(unittest.TestCase):
    def test_no_spouses(self):
        people = [P(n, f"{n}@x.com") for n in "ABCDE"]
        for _ in range(200):
            check(self, people, ss.make_pairings(people))

    def test_couples(self):
        people = [P("Ann", "a@x.com", "Bob"), P("Bob", "b@x.com", "Ann"),
                  P("Cat", "c@x.com", "Dan"), P("Dan", "d@x.com", "Cat"),
                  P("Eve", "e@x.com")]
        for _ in range(200):
            check(self, people, ss.make_pairings(people))

    def test_one_sided_spouse_is_symmetric(self):
        people = [P("Ann", "a@x.com", "bob"), P("Bob", "b@x.com"), P("Cat", "c@x.com"),
                  P("Dan", "d@x.com")]
        for _ in range(200):
            check(self, people, ss.make_pairings(people))

    def test_spouse_not_in_list_ignored(self):
        people = [P("Ann", "a@x.com", "Zed"), P("Bob", "b@x.com")]
        pairs = ss.make_pairings(people)
        self.assertEqual(pairs["ann"].name, "Bob")

    def test_impossible(self):
        people = [P("Ann", "a@x.com", "Bob"), P("Bob", "b@x.com", "Ann")]
        with self.assertRaises(ss.SecretSantaError):
            ss.make_pairings(people)

    def test_validation(self):
        with self.assertRaises(ss.SecretSantaError):
            ss.make_pairings([P("A", "a@x.com")])
        with self.assertRaises(ss.SecretSantaError):
            ss.make_pairings([P("A", "a@x.com"), P("a", "b@x.com")])
        with self.assertRaises(ss.SecretSantaError):
            ss.make_pairings([P("A", "bad"), P("B", "b@x.com")])


class TestCsvAndMessage(unittest.TestCase):
    def test_load_csv(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write("Name,Email,Spouse\nAnn,a@x.com,Bob\nBob,b@x.com,\n\nCat,c@x.com,\n")
        try:
            people = ss.load_csv(f.name)
        finally:
            os.unlink(f.name)
        self.assertEqual([p.name for p in people], ["Ann", "Bob", "Cat"])
        self.assertEqual(people[0].spouse, "Bob")

    def test_message_only_names_own_giftee(self):
        cfg = ss.MailConfig("h", 587, "u", "p", "santa@x.com")
        msg = ss.build_message(cfg, P("Ann", "a@x.com"), P("Cat", "c@x.com"))
        self.assertEqual(msg["To"], "a@x.com")
        body = msg.get_content()
        self.assertIn("Cat", body)
        self.assertTrue(msg["Message-ID"])


class TestPrompt(unittest.TestCase):
    def run_prompt(self, answers):
        from unittest import mock
        it = iter(answers)
        with mock.patch("builtins.input", lambda _="": next(it)), \
             mock.patch("builtins.print"):
            return ss.prompt_participants()

    def test_reprompts_bad_input(self):
        people = self.run_prompt([
            "",                       # too early to stop: re-asked
            "Ann", "bad", "a@x.com", "ann", "Bob",   # bad email, self as spouse
            "ann",                    # duplicate name: skipped
            "Bob", "b@x.com", "",
            "",                       # done
        ])
        self.assertEqual([(p.name, p.email, p.spouse) for p in people],
                         [("Ann", "a@x.com", "Bob"), ("Bob", "b@x.com", "")])


if __name__ == "__main__":
    unittest.main()
