# secret-santa

Draws Secret Santa pairs and emails each gifter the name of their giftee.
It needs Python 3.9 or later and uses only the standard library, so there's nothing to install.

## Rules
- Each person gives one gift and gets one gift. No one draws themselves.
- **Spouse name is optional.** If you enter one, those two people never draw each other, in either direction.
- In a real draw, nothing prints the pairings. Each email names only that gifter's giftee.
- After the emails go out, the sent copies are deleted from your mailbox (see *Deleting sent emails*).
- **Test mode** (`--test`) prints every pairing on screen and sends no email.

## Entering participants
There are three ways to enter names, emails and spouse names.

### 1. In your browser (easiest)
```bash
python3 web.py
```
This opens http://127.0.0.1:8000 in your browser. Type each person's **name**, **email** and **spouse name** (optional).
Use **+ Add person** to add more rows, or **Import CSV…** to fill the table from a file. Then click:
- **Test mode: show pairings**: shows every pairing on the page and sends no email.
- **Draw & send emails**: emails each person their giftee. The page lists who was emailed, but never who they drew.

Enter your mail server details under **Email settings**. Anything set in the environment variables
below fills in automatically, except the password.
**Memory:** the page remembers your participants and email settings in your browser, so they're
still there next time. Nothing is saved on the server. The password is remembered only if you tick
*Remember password on this device*. That stores it unencrypted in the browser, so leave it off on shared computers.
**Clear saved data** erases everything.

The page runs only on your computer (`127.0.0.1`).
Use `--port` to pick a different port, or `--no-browser` to stop it opening a browser.

### 2. Typed in at the command line
Run `python3 secret_santa.py` (or add `--test`) without a file. It asks for each person's name, email
and spouse. It checks each entry as you type it: a bad email, a duplicate name, or a person listed as their
own spouse is asked for again. Leave the name blank when you're done. At the end it offers to save
the list to a CSV file, so next time you can run `python3 secret_santa.py yourfile.csv`.

### 3. From a CSV file
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
