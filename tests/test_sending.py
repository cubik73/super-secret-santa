import os
import smtplib
import socket
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import secret_santa as ss  # noqa: E402

P = ss.Participant
PEOPLE = [P("Ann", "a@x.com"), P("Bob", "b@x.com"), P("Cat", "c@x.com")]


def cfg(port=587):
    return ss.MailConfig("127.0.0.1", port, "me@x.com", "pw", "me@x.com")


class FakeSMTP:
    """Stand-in for smtplib.SMTP. Class attributes script its behaviour."""
    instances = []
    fail_login = False
    drop_on_send = []      # 1-based send counts (across all connections) that drop
    sends = 0
    delivered = []

    def __init__(self, *a, **k):
        FakeSMTP.instances.append(self)

    def ehlo(self): pass
    def starttls(self, **k): pass
    def close(self): pass
    def quit(self): pass

    def login(self, *a):
        if FakeSMTP.fail_login:
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    def send_message(self, msg):
        FakeSMTP.sends += 1
        if FakeSMTP.sends in FakeSMTP.drop_on_send:
            raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
        FakeSMTP.delivered.append((msg["To"], msg.get_content().splitlines()[2]))


class TestSending(unittest.TestCase):
    def setUp(self):
        FakeSMTP.instances, FakeSMTP.delivered = [], []
        FakeSMTP.fail_login, FakeSMTP.drop_on_send, FakeSMTP.sends = False, [], 0
        p = mock.patch.object(smtplib, "SMTP", FakeSMTP)
        p.start()
        self.addCleanup(p.stop)

    def test_bad_password_sends_nothing(self):
        FakeSMTP.fail_login = True
        with self.assertRaises(ss.SendError) as cm:
            ss.send_all(cfg(), PEOPLE, ss.make_pairings(PEOPLE), log=lambda *_: None)
        self.assertEqual(cm.exception.sent, [])
        self.assertIn("app password", str(cm.exception))
        self.assertEqual(FakeSMTP.delivered, [])

    def test_reconnects_and_keeps_same_draw(self):
        FakeSMTP.drop_on_send = [2]           # drop while sending the 2nd email
        pairs = ss.make_pairings(PEOPLE)
        expected = {p.email: f"You are the Secret Santa for: {pairs[p.key].name}" for p in PEOPLE}
        ss.send_all(cfg(), PEOPLE, pairs, log=lambda *_: None)
        self.assertEqual(dict(FakeSMTP.delivered), expected)
        self.assertEqual(len(FakeSMTP.delivered), 3)
        self.assertEqual(len(FakeSMTP.instances), 2)  # one reconnect

    def test_gives_up_and_reports_who_was_sent(self):
        FakeSMTP.drop_on_send = [2, 3, 4]     # 2nd email fails 3 times in a row
        with self.assertRaises(ss.SendError) as cm:
            ss.send_all(cfg(), PEOPLE, ss.make_pairings(PEOPLE), log=lambda *_: None)
        self.assertEqual(cm.exception.sent, ["Ann"])
        self.assertIn("Ann", ss.partial_send_note(cm.exception.sent))


class TestRealSocket(unittest.TestCase):
    def test_server_that_hangs_up_gives_a_helpful_message(self):
        """Reproduces 'Connection unexpectedly closed' from a server that closes at once."""
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen()
        port = srv.getsockname()[1]

        def hang_up():
            for _ in range(2):
                conn, _ = srv.accept()
                conn.close()
        threading.Thread(target=hang_up, daemon=True).start()
        with self.assertRaises(ss.SendError) as cm:
            ss.check_connection(cfg(port))
        srv.close()
        msg = str(cm.exception)
        self.assertIn("closed the connection straight away", msg)
        self.assertIn("587", msg)

    def test_nothing_listening(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        with self.assertRaises(ss.SendError) as cm:
            ss.check_connection(cfg(port))
        self.assertIn("Couldn't reach", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
