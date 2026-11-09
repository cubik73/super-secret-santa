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
    seen: set[str] = set()
    for p in participants:
        if not p.name.strip():
            raise SecretSantaError("Every participant needs a name.")
        if p.key in seen:
            raise SecretSantaError(f"Duplicate name: {p.name!r}. Names must be unique.")
        seen.add(p.key)
        if not EMAIL_RE.match(p.email.strip()):
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
    print("Enter participants. Leave the name blank when finished.\n")
    out = []
    while True:
        name = input(f"Gifter #{len(out) + 1} name: ").strip()
        if not name:
            break
        email = input("  Email: ").strip()
        spouse = input("  Spouse name (optional): ").strip()
        out.append(Participant(name, email, spouse))
    return out


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


def send_all(cfg: MailConfig, participants: list[Participant], pairings: dict[str, Participant]) -> None:
    message_ids: list[str] = []
    ctx = ssl.create_default_context()
    if cfg.smtp_port == 465:
        smtp = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, context=ctx)
    else:
        smtp = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port)
        smtp.starttls(context=ctx)
    with smtp:
        smtp.login(cfg.user, cfg.password)
        for p in participants:
            msg = build_message(cfg, p, pairings[p.key])
            smtp.send_message(msg)
            message_ids.append(msg["Message-ID"])
            del msg  # don't keep the content around
            print(f"  ✓ sent to {p.name}")
    pairings.clear()

    if cfg.imap_host:
        print("Deleting sent copies from the mailbox...")
        warnings = _imap_purge(cfg, message_ids)
        for w in warnings:
            print(f"  ! {w}", file=sys.stderr)
        if not warnings:
            print("  ✓ sent copies deleted")
    else:
        print(
            "Note: IMAP_HOST not set, so copies your mail provider saved in "
            "'Sent' were not deleted. Delete them manually without opening them.",
            file=sys.stderr,
        )


# ----------------------------------------------------------------------------- cli

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Secret Santa draw and emailer.")
    ap.add_argument("csv", nargs="?", help="CSV file with columns name,email,spouse. "
                    "If omitted, you'll be prompted to type participants.")
    ap.add_argument("--test", action="store_true",
                    help="Test mode: print all pairings to the screen and send no email.")
    args = ap.parse_args(argv)

    try:
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
        send_all(cfg, participants, pairings)
        print("Done. Happy holidays! 🎄")
        return 0
    except SecretSantaError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (smtplib.SMTPException, OSError) as exc:
        print(f"Email error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
