#!/usr/bin/env python3
"""Secret Santa: randomly pair gifters, email each one their giftee, leave no trace.

Inputs per participant: name, email, spouse name (optional).
Rules:
  * Nobody draws themselves.
  * Nobody draws their spouse (checked both ways: if A lists B, B also can't draw A).
  * Every name is drawn exactly once.
Privacy:
  * Live mode never prints or logs the pairings; each gifter's email only names
    their own giftee.
  * After each email is sent it is deleted from the sender's mailbox over IMAP
    (Sent folder, then Trash) when IMAP is configured.
  * Test mode (--test) prints every pairing to the screen and sends nothing.
"""
from __future__ import annotations

import argparse
import csv
import getpass
import imaplib
import os
import re
import secrets
import smtplib
import ssl
import sys
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import make_msgid

_rng = secrets.SystemRandom()
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_PARTICIPANTS = 100
MAX_NAME_LEN = 60
MAX_EMAIL_LEN = 254


@dataclass(frozen=True)
class Participant:
    name: str
    email: str
    spouse: str = ""

    @property
    def key(self) -> str:
        return self.name.strip().casefold()

    @property
    def spouse_key(self) -> str:
        return self.spouse.strip().casefold()


class SecretSantaError(Exception):
    pass


# --------------------------------------------------------------------------- input

def validate(participants: list[Participant]) -> None:
    if len(participants) < 2:
        raise SecretSantaError("Need at least 2 participants.")
    if len(participants) > MAX_PARTICIPANTS:
        raise SecretSantaError(f"At most {MAX_PARTICIPANTS} participants per draw.")
    seen: set[str] = set()
    for p in participants:
        if not p.name.strip():
            raise SecretSantaError("Every participant needs a name.")
        if p.key in seen:
            raise SecretSantaError(f"Duplicate name: {p.name!r}. Names must be unique.")
        seen.add(p.key)
        if len(p.name) > MAX_NAME_LEN or len(p.spouse) > MAX_NAME_LEN:
            raise SecretSantaError(f"Names must be {MAX_NAME_LEN} characters or fewer.")
        if len(p.email) > MAX_EMAIL_LEN or not EMAIL_RE.match(p.email.strip()):
            raise SecretSantaError(f"Invalid email for {p.name!r}: {p.email!r}")
        if p.spouse_key and p.spouse_key == p.key:
            raise SecretSantaError(f"{p.name!r} lists themselves as their spouse.")


def load_csv(path: str) -> list[Participant]:
    """CSV with header: name,email,spouse  (spouse column/value optional)."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise SecretSantaError("CSV file is empty.")
        cols = {c.strip().casefold(): c for c in reader.fieldnames}
        if "name" not in cols or "email" not in cols:
            raise SecretSantaError("CSV needs at least 'name' and 'email' columns.")
        out = []
        for row in reader:
            name = (row.get(cols["name"]) or "").strip()
            email = (row.get(cols["email"]) or "").strip()
            spouse = (row.get(cols["spouse"]) or "").strip() if "spouse" in cols else ""
            if not (name or email or spouse):
                continue  # skip blank lines
            out.append(Participant(name, email, spouse))
    return out


def prompt_participants() -> list[Participant]:
    """Ask for participants one at a time, checking each entry as it is typed."""
    print("Enter participants. Leave the name blank when finished.\n")
    out: list[Participant] = []
    while True:
        name = input(f"Gifter #{len(out) + 1} name: ").strip()
        if not name:
            if len(out) < 2:
                print("  Please enter at least 2 participants.")
                continue
            break
        if any(p.key == name.casefold() for p in out):
            print(f"  {name!r} is already entered. Names must be unique.")
            continue
        while True:
            email = input("  Email: ").strip()
            if EMAIL_RE.match(email):
                break
            print("  That doesn't look like a valid email. Try again.")
        while True:
            spouse = input("  Spouse name (optional, press Enter to skip): ").strip()
            if spouse.casefold() != name.casefold():
                break
            print("  A person can't be their own spouse.")
        out.append(Participant(name, email, spouse))

    names = {p.key for p in out}
    for p in out:
        if p.spouse_key and p.spouse_key not in names:
            print(f"  Note: {p.name}'s spouse {p.spouse!r} isn't in the list, so it has no effect.")
    print(f"\n{len(out)} participants entered.")
    path = input("Save these to a CSV file for next time? Enter a file name, or press Enter to skip: ").strip()
    if path:
        save_csv(path, out)
        print(f"  Saved. Next time run:  python3 secret_santa.py {path}")
    return out


def save_csv(path: str, participants: list[Participant]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["name", "email", "spouse"])
        for p in participants:
            w.writerow([p.name, p.email, p.spouse])


# ------------------------------------------------------------------------ matching

def _forbidden(participants: list[Participant]) -> dict[str, set[str]]:
    """Map each gifter key to the set of keys they may not draw."""
    keys = {p.key for p in participants}
    forbid = {p.key: {p.key} for p in participants}
    for p in participants:
        if p.spouse_key in keys:  # spouse not in the list is simply irrelevant
            forbid[p.key].add(p.spouse_key)
            forbid[p.spouse_key].add(p.key)  # make it symmetric
    return forbid


def make_pairings(participants: list[Participant]) -> dict[str, Participant]:
    """Return {gifter_key: giftee}. Uniformly random among valid draws is not
    required; we use randomized backtracking, which always finds a valid draw
    if one exists and reports clearly when none does."""
    validate(participants)
    forbid = _forbidden(participants)
    by_key = {p.key: p for p in participants}
    gifters = list(by_key)
    _rng.shuffle(gifters)
    # Most constrained gifters first speeds up the search.
    gifters.sort(key=lambda k: len(forbid[k]), reverse=True)

    assignment: dict[str, str] = {}
    taken: set[str] = set()

    def solve(i: int) -> bool:
        if i == len(gifters):
            return True
        g = gifters[i]
        options = [k for k in by_key if k not in taken and k not in forbid[g]]
        _rng.shuffle(options)
        for o in options:
            assignment[g] = o
            taken.add(o)
            if solve(i + 1):
                return True
            taken.discard(o)
            del assignment[g]
        return False

    if not solve(0):
        raise SecretSantaError(
            "No valid draw is possible with these spouse restrictions "
            "(e.g. only one couple, or too few people). Add more participants."
        )
    return {g: by_key[r] for g, r in assignment.items()}


# --------------------------------------------------------------------------- email

@dataclass
class MailConfig:
    smtp_host: str
    smtp_port: int
    user: str
    password: str
    sender: str
    imap_host: str = ""
    imap_port: int = 993
    sent_folder: str = "Sent"
    trash_folder: str = "Trash"
    subject: str = "Your Secret Santa assignment 🎁"

    @classmethod
    def from_env(cls) -> "MailConfig":
        env = os.environ.get
        host = env("SMTP_HOST")
        user = env("SMTP_USER")
        if not host or not user:
            raise SecretSantaError(
                "Set SMTP_HOST and SMTP_USER (and SMTP_PASSWORD) to send email. "
                "Use --test to preview pairings without sending."
            )
        password = env("SMTP_PASSWORD") or getpass.getpass(f"SMTP password for {user}: ")
        return cls(
            smtp_host=host,
            smtp_port=int(env("SMTP_PORT", "587")),
            user=user,
            password=password,
            sender=env("SMTP_FROM", user),
            imap_host=env("IMAP_HOST", ""),
            imap_port=int(env("IMAP_PORT", "993")),
            sent_folder=env("IMAP_SENT_FOLDER", "Sent"),
            trash_folder=env("IMAP_TRASH_FOLDER", "Trash"),
            subject=env("SECRET_SANTA_SUBJECT", cls.subject),
        )


def build_message(cfg: MailConfig, gifter: Participant, giftee: Participant) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = cfg.sender
    msg["To"] = gifter.email
    msg["Subject"] = cfg.subject
    msg["Message-ID"] = make_msgid(domain="secret-santa.local")
    msg.set_content(
        f"Hi {gifter.name},\n\n"
        f"You are the Secret Santa for: {giftee.name}\n\n"
        "Shh — keep it secret! Nobody else, including the organizer, has seen this.\n"
    )
    return msg


def _imap_purge(cfg: MailConfig, message_ids: list[str]) -> list[str]:
    """Delete our sent messages from the sender's Sent and Trash folders.
    Returns a list of warnings (empty on full success)."""
    warnings: list[str] = []
    try:
        imap = imaplib.IMAP4_SSL(cfg.imap_host, cfg.imap_port, ssl_context=ssl.create_default_context())
    except OSError as exc:
        return [f"Could not connect to IMAP to delete sent copies: {exc}"]
    try:
        imap.login(cfg.user, cfg.password)
        for folder in (cfg.sent_folder, cfg.trash_folder):
            if not folder:
                continue
            typ, _ = imap.select(_quote(folder))
            if typ != "OK":
                warnings.append(f"IMAP folder {folder!r} not found; skipped.")
                continue
            for mid in message_ids:
                typ, data = imap.uid("SEARCH", None, "HEADER", "Message-ID", _quote(mid))
                uids = data[0].split() if typ == "OK" and data and data[0] else []
                for uid in uids:
                    if folder == cfg.sent_folder and cfg.trash_folder:
                        # Gmail only truly deletes from Trash; copying there first
                        # makes the second pass remove it permanently.
                        imap.uid("COPY", uid, _quote(cfg.trash_folder))
                    imap.uid("STORE", uid, "+FLAGS", r"(\Deleted)")
            imap.expunge()
            imap.close()
    except imaplib.IMAP4.error as exc:
        warnings.append(f"IMAP error while deleting sent copies: {exc}")
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    return warnings


def _quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


class SendError(SecretSantaError):
    """Sending failed. `sent` lists who already got their email (empty = nobody)."""

    def __init__(self, message: str, sent: list[str] | None = None):
        super().__init__(message)
        self.sent = sent or []


SECURITY_HELP = ("Use port 587 (STARTTLS) or 465 (SSL). For Gmail: smtp.gmail.com, port 587.")
APP_PASSWORD_HELP = (
    "Gmail, Yahoo and iCloud need an app password, not your normal password "
    "(Gmail: https://myaccount.google.com/apppasswords; it needs 2-Step Verification on). "
    "Outlook.com/Hotmail no longer allow apps to sign in with a password, so use a "
    "different email account to send from."
)


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:  # packaged apps may not find the system certificates (notably on macOS)
        import certifi
        ctx.load_verify_locations(certifi.where())
    except Exception:
        pass
    return ctx


def explain_error(exc: BaseException, cfg: MailConfig, stage: str) -> str:
    """Turn a low-level mail error into something a person can act on."""
    where = f"{cfg.smtp_host}:{cfg.smtp_port}"
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return f"The mail server rejected the username or password. {APP_PASSWORD_HELP}"
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        bad = ", ".join(exc.recipients) or "a recipient"
        return f"The mail server refused to send to {bad}. Check that address."
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return (f"The mail server wouldn't send from {cfg.sender}. The From address usually "
                "has to be the same as the account you sign in with.")
    if isinstance(exc, ssl.SSLCertVerificationError):
        return (f"Couldn't verify {cfg.smtp_host}'s security certificate. Check the server name. "
                "Antivirus that scans email (Avast, AVG, ESET and similar) can also cause this; "
                "try turning its email scanning off for a moment.")
    if isinstance(exc, smtplib.SMTPNotSupportedError):
        return f"{where} doesn't support a secure connection on this port. {SECURITY_HELP}"
    if isinstance(exc, smtplib.SMTPServerDisconnected) or isinstance(exc, ssl.SSLError):
        if stage == "connect":
            return (f"{where} closed the connection straight away. This is usually a wrong "
                    f"server or port. {SECURITY_HELP} Antivirus that scans email (Avast, AVG, "
                    "ESET and similar) can also cause this; try turning its email scanning off "
                    "for a moment.")
        if stage == "login":
            return (f"{where} closed the connection while signing in. That usually means the "
                    f"sign-in was refused. {APP_PASSWORD_HELP}")
        return (f"{where} dropped the connection while sending. The provider may be limiting "
                "how many emails you can send. Wait a few minutes and try again.")
    if isinstance(exc, TimeoutError) or "timed out" in str(exc):
        return (f"Timed out reaching {where}. Check the server name and port. Some networks "
                f"block email ports; try another network or port. {SECURITY_HELP}")
    if isinstance(exc, OSError):  # refused, unknown host, network unreachable...
        return f"Couldn't reach {where} ({exc}). Check the server name and port. {SECURITY_HELP}"
    return f"{exc} ({type(exc).__name__})"


def _connect(cfg: MailConfig, port: int | None = None) -> smtplib.SMTP:
    """Connect and sign in. Raises SendError with a friendly message."""
    port = port or cfg.smtp_port
    ctx = _ssl_context()
    stage = "connect"
    smtp = None
    try:
        if port == 465:
            smtp = smtplib.SMTP_SSL(cfg.smtp_host, port, context=ctx, timeout=30)
        else:
            smtp = smtplib.SMTP(cfg.smtp_host, port, timeout=30)
            smtp.ehlo()
            smtp.starttls(context=ctx)
            smtp.ehlo()
        stage = "login"
        smtp.login(cfg.user, cfg.password)
        return smtp
    except (smtplib.SMTPException, OSError) as exc:
        if smtp is not None:
            try:
                smtp.close()
            except Exception:
                pass
        cfg_for_msg = cfg if port == cfg.smtp_port else MailConfig(**{**cfg.__dict__, "smtp_port": port})
        raise SendError(explain_error(exc, cfg_for_msg, stage)) from exc


def check_connection(cfg: MailConfig) -> str:
    """Try to sign in without sending anything. Returns a success message or raises
    SendError. If the chosen port fails before sign-in, tries the other common port
    and says so if that one works."""
    try:
        _connect(cfg).quit()
        return f"Signed in to {cfg.smtp_host} as {cfg.user}. Email settings look good."
    except SendError as first:
        cause = first.__cause__
        if isinstance(cause, smtplib.SMTPAuthenticationError) or cfg.smtp_port not in (465, 587):
            raise
        other = 465 if cfg.smtp_port == 587 else 587
        try:
            _connect(cfg, other).quit()
        except SendError:
            raise first
        raise SendError(f"Port {cfg.smtp_port} didn't work, but port {other} did. "
                        f"Change the port to {other}.") from None


def send_all(cfg: MailConfig, participants: list[Participant], pairings: dict[str, Participant],
             log=print) -> list[str]:
    """Send one email per gifter, then delete the sent copies. Returns warnings.

    Signs in before sending anything, so a bad setting sends no email. If the
    connection drops part-way, it reconnects and carries on with the same draw.
    """
    message_ids: list[str] = []
    sent: list[str] = []
    smtp = _connect(cfg)  # nothing has been sent if this fails
    try:
        for p in participants:
            msg = build_message(cfg, p, pairings[p.key])
            for attempt in range(3):
                try:
                    smtp.send_message(msg)
                    break
                except (smtplib.SMTPServerDisconnected, OSError) as exc:
                    if attempt == 2:
                        raise SendError(explain_error(exc, cfg, "send"), sent) from exc
                    log(f"  … connection dropped, reconnecting")
                    try:
                        smtp.close()
                    except Exception:
                        pass
                    try:
                        smtp = _connect(cfg)
                    except SendError as err:
                        raise SendError(str(err), sent) from err
                except smtplib.SMTPException as exc:
                    raise SendError(explain_error(exc, cfg, "send"), sent) from exc
            message_ids.append(msg["Message-ID"])
            sent.append(p.name)
            del msg  # don't keep the content around
            log(f"  ✓ sent to {p.name}")
    finally:
        pairings.clear()
        try:
            smtp.quit()
        except Exception:
            pass

    if not cfg.imap_host:
        return ["No IMAP server was set, so the copies your mail provider saved in "
                "'Sent' were not deleted. Delete them yourself without opening them."]
    log("Deleting sent copies from the mailbox...")
    warnings = _imap_purge(cfg, message_ids)
    if not warnings:
        log("  ✓ sent copies deleted")
    return warnings


def partial_send_note(sent: list[str]) -> str:
    if not sent:
        return "No emails were sent, so nothing needs undoing. Fix the problem and try again."
    return (f"{len(sent)} email(s) went out before the error, to: {', '.join(sent)}. "
            "Sending again makes a brand-new draw, so ask those people to ignore their first "
            "email and use the newest one.")


# ----------------------------------------------------------------------------- cli

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Secret Santa draw and emailer.")
    ap.add_argument("csv", nargs="?", help="CSV file with columns name,email,spouse. "
                    "If omitted, you'll be prompted to type participants.")
    ap.add_argument("--test", action="store_true",
                    help="Test mode: print all pairings to the screen and send no email.")
    ap.add_argument("--check-email", action="store_true",
                    help="Check the email settings by signing in, without sending anything.")
    args = ap.parse_args(argv)

    try:
        if args.check_email:
            print(check_connection(MailConfig.from_env()))
            return 0
        participants = load_csv(args.csv) if args.csv else prompt_participants()
        pairings = make_pairings(participants)

        if args.test:
            print("\nTEST MODE — no emails sent. Pairings:\n")
            width = max(len(p.name) for p in participants)
            for p in participants:
                print(f"  {p.name:<{width}}  →  {pairings[p.key].name}")
            return 0

        cfg = MailConfig.from_env()
        print(f"\nDraw complete. Emailing {len(participants)} gifters "
              "(pairings are not shown)...")
        for w in send_all(cfg, participants, pairings):
            print(f"  ! {w}", file=sys.stderr)
        print("Done. Happy holidays! 🎄")
        return 0
    except SendError as exc:
        print(f"Email error: {exc}", file=sys.stderr)
        if not args.check_email:
            print(partial_send_note(exc.sent), file=sys.stderr)
        return 2
    except SecretSantaError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (smtplib.SMTPException, OSError) as exc:
        print(f"Email error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
