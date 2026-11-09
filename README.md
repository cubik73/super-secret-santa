# secret-santa

Draws Secret Santa pairs and emails each gifter the name of their giftee.
It needs Python 3.9 or later and uses only the standard library, so there's nothing to install.

## Rules
- Each person gives one gift and gets one gift. No one draws themselves.
- **Spouse name is optional.** If you enter one, those two people never draw each other, in either direction.
- In a real draw, nothing prints the pairings. Each email names only that gifter's giftee.
- After the emails go out, the sent copies are deleted from your mailbox (see *Deleting sent emails*).
- **Test mode** (`--test`) prints every pairing on screen and sends no email.

## Input
Use a CSV file with the columns `name,email,spouse`. The `spouse` value can be blank. See `participants.example.csv`.

```csv
name,email,spouse
Alice,alice@example.com,Bob
Bob,bob@example.com,Alice
Erin,erin@example.com,
```

If you don't give a file, the app asks you to type each person in.

## Usage
```bash
# Preview the pairings (no email is sent)
python3 secret_santa.py participants.csv --test

# Real draw: send the emails
export SMTP_HOST=smtp.gmail.com SMTP_PORT=587
export SMTP_USER=you@gmail.com SMTP_PASSWORD='your-app-password'
export IMAP_HOST=imap.gmail.com
export IMAP_SENT_FOLDER='[Gmail]/Sent Mail' IMAP_TRASH_FOLDER='[Gmail]/Trash'
python3 secret_santa.py participants.csv
```
If you don't set `SMTP_PASSWORD`, the app asks for it. For Gmail, use an
[App Password](https://myaccount.google.com/apppasswords).

| Variable | Default | Purpose |
|---|---|---|
| `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD` | — | Required for a real draw |
| `SMTP_PORT` | `587` | `587` uses STARTTLS, `465` uses SSL |
| `SMTP_FROM` | `SMTP_USER` | The From address on the emails |
| `IMAP_HOST`, `IMAP_PORT` | —, `993` | Turns on deleting the sent copies |
| `IMAP_SENT_FOLDER` | `Sent` | The mailbox folder for sent mail |
| `IMAP_TRASH_FOLDER` | `Trash` | Cleared of these messages too |
| `SECRET_SANTA_SUBJECT` | `Your Secret Santa assignment 🎁` | The email subject |

## Deleting sent emails
SMTP itself doesn't keep a copy, but most providers (Gmail, Outlook) save one in your
Sent folder. When `IMAP_HOST` is set, the app finds each message it just sent by its
unique Message-ID. It deletes the message from the Sent folder and then from Trash.
No pairings are stored anywhere. If `IMAP_HOST` isn't set, the app warns you to delete the
sent copies yourself without opening them.

## Tests
```bash
python3 -m unittest discover -s tests
```
