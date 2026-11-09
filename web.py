#!/usr/bin/env python3
"""Browser form for Secret Santa.

Run:  python3 web.py          then open http://127.0.0.1:8000
It listens only on this computer (127.0.0.1). Nothing is saved to disk.
"""
from __future__ import annotations

import argparse
import json
import os
import smtplib
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import secret_santa as ss


def _participants(data: dict) -> list[ss.Participant]:
    rows = data.get("participants") or []
    out = []
    for r in rows:
        name = str(r.get("name", "")).strip()
        email = str(r.get("email", "")).strip()
        spouse = str(r.get("spouse", "")).strip()
        if name or email or spouse:
            out.append(ss.Participant(name, email, spouse))
    return out


def _mail_config(data: dict) -> ss.MailConfig:
    m = data.get("mail") or {}
    env = os.environ.get

    def pick(key, env_key, default=""):
        return str(m.get(key) or env(env_key) or default).strip()

    host, user = pick("smtp_host", "SMTP_HOST"), pick("smtp_user", "SMTP_USER")
    password = str(m.get("smtp_password") or env("SMTP_PASSWORD") or "")
    if not host or not user or not password:
        raise ss.SecretSantaError("Fill in the email settings (server, username and password) to send.")
    try:
        smtp_port = int(pick("smtp_port", "SMTP_PORT", "587"))
        imap_port = int(pick("imap_port", "IMAP_PORT", "993"))
    except ValueError:
        raise ss.SecretSantaError("Ports must be numbers.")
    return ss.MailConfig(
        smtp_host=host, smtp_port=smtp_port, user=user, password=password,
        sender=pick("smtp_from", "SMTP_FROM", user),
        imap_host=pick("imap_host", "IMAP_HOST"), imap_port=imap_port,
        sent_folder=pick("sent_folder", "IMAP_SENT_FOLDER", "Sent"),
        trash_folder=pick("trash_folder", "IMAP_TRASH_FOLDER", "Trash"),
        subject=pick("subject", "SECRET_SANTA_SUBJECT", ss.MailConfig.subject),
    )


def env_defaults() -> dict:
    """Email settings from environment variables, to prefill the form (never the password)."""
    e = os.environ.get
    return {
        "smtp_host": e("SMTP_HOST", ""), "smtp_port": e("SMTP_PORT", "587"),
        "smtp_user": e("SMTP_USER", ""), "smtp_from": e("SMTP_FROM", ""),
        "imap_host": e("IMAP_HOST", ""), "imap_port": e("IMAP_PORT", "993"),
        "sent_folder": e("IMAP_SENT_FOLDER", "Sent"), "trash_folder": e("IMAP_TRASH_FOLDER", "Trash"),
        "password_from_env": bool(e("SMTP_PASSWORD")),
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # keep the console quiet; never log request bodies
        pass

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, obj: dict) -> None:
        self._send(status, json.dumps(obj).encode(), "application/json")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            page = PAGE.replace("__DEFAULTS__", json.dumps(env_defaults()))
            self._send(200, page.encode(), "text/html; charset=utf-8")
        else:
            self._send(404, b"Not found", "text/plain")

    def do_POST(self):
        if self.path not in ("/api/test", "/api/send"):
            return self._send(404, b"Not found", "text/plain")
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length) or b"{}")
            people = _participants(data)
            if self.path == "/api/test":
                pairs = ss.make_pairings(people)
                return self._json(200, {"pairings": [
                    {"gifter": p.name, "giftee": pairs[p.key].name} for p in people]})
            cfg = _mail_config(data)
            pairs = ss.make_pairings(people)
            log: list[str] = []
            warnings = ss.send_all(cfg, people, pairs, log=log.append)
            # Response says who was emailed, never who they drew.
            return self._json(200, {"log": log, "warnings": warnings})
        except ss.SecretSantaError as exc:
            return self._json(400, {"error": str(exc)})
        except (smtplib.SMTPException, OSError) as exc:
            return self._json(502, {"error": f"Email error: {exc}"})
        except (ValueError, TypeError):
            return self._json(400, {"error": "Bad request."})


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Secret Santa</title>
<style>
  :root { --bg:#faf7f2; --card:#fff; --ink:#1f2a24; --muted:#64706a; --line:#e3ddd3;
          --red:#b3261e; --green:#1d6b45; --greenbg:#e8f3ec; --redbg:#fbeaea; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font:16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
  main { max-width:860px; margin:0 auto; padding:32px 16px 64px; }
  h1 { margin:0 0 4px; font-size:28px; }
  .sub { color:var(--muted); margin:0 0 24px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:20px; margin-bottom:20px; }
  h2 { font-size:18px; margin:0 0 12px; }
  table { width:100%; border-collapse:collapse; }
  th { text-align:left; font-size:13px; color:var(--muted); font-weight:600; padding:0 6px 6px; }
  td { padding:4px 6px; vertical-align:top; }
  input { width:100%; padding:9px 10px; border:1px solid var(--line); border-radius:8px; font:inherit; background:#fff; color:inherit; }
  input:focus { outline:2px solid var(--green); outline-offset:-1px; }
  input.bad { border-color:var(--red); background:var(--redbg); }
  td.num { color:var(--muted); width:28px; padding-top:13px; font-size:14px; }
  td.del { width:40px; }
  button { font:inherit; border-radius:8px; padding:9px 16px; cursor:pointer; border:1px solid var(--line); background:#fff; color:var(--ink); }
  button.primary { background:var(--red); border-color:var(--red); color:#fff; font-weight:600; }
  button.secondary { background:var(--green); border-color:var(--green); color:#fff; font-weight:600; }
  button.icon { padding:8px 11px; color:var(--muted); }
  button:disabled { opacity:.5; cursor:default; }
  .row { display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-top:12px; }
  .grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
  label { display:block; font-size:13px; color:var(--muted); font-weight:600; }
  label input { margin-top:4px; }
  .hint { font-size:13px; color:var(--muted); }
  #msg { display:none; border-radius:10px; padding:14px 16px; margin-bottom:20px; white-space:pre-wrap; }
  #msg.ok { display:block; background:var(--greenbg); color:var(--green); }
  #msg.err { display:block; background:var(--redbg); color:var(--red); }
  #results { display:none; }
  .pair { display:flex; gap:12px; padding:8px 0; border-bottom:1px solid var(--line); }
  .pair:last-child { border-bottom:0; }
  .pair span:first-child { min-width:40%; font-weight:600; }
  details summary { cursor:pointer; font-weight:600; }
  label.check { display:flex; gap:8px; align-items:baseline; margin-top:14px; font-weight:400; color:var(--ink); font-size:14px; }
  label.check input { width:auto; margin:0; }
  @media (max-width:640px) {
    .grid { grid-template-columns:1fr; }
    thead { display:none; }
    tr { display:grid; grid-template-columns:28px 1fr 40px; border-bottom:1px solid var(--line); padding:6px 0; }
    td.num { grid-row:span 3; }
    td.del { grid-column:3; grid-row:1; }
    td:not(.num):not(.del) { grid-column:2; }
  }
</style></head>
<body><main>
  <h1>🎁 Secret Santa</h1>
  <p class="sub">Add everyone below. Each person is emailed only the name they drew.</p>

  <div id="msg" role="status"></div>

  <section class="card">
    <h2>Participants</h2>
    <table>
      <thead><tr><th></th><th>Name</th><th>Email</th><th>Spouse name (optional)</th><th></th></tr></thead>
      <tbody id="rows"></tbody>
    </table>
    <div class="row">
      <button id="add">+ Add person</button>
      <button id="importBtn">Import CSV…</button>
      <input id="csvFile" type="file" accept=".csv,text/csv" hidden>
      <span class="hint">CSV columns: name, email, spouse</span>
    </div>
    <div class="row">
      <span class="hint" id="savedNote">Your entries are saved in this browser only.</span>
      <button class="icon" id="clearBtn">Clear saved data</button>
    </div>
  </section>

  <section class="card">
    <details id="mailBox">
      <summary>Email settings</summary>
      <p class="hint">Needed only for sending. For Gmail, use smtp.gmail.com, imap.gmail.com, folders
        <code>[Gmail]/Sent Mail</code> and <code>[Gmail]/Trash</code>, and an App Password.</p>
      <div class="grid">
        <label>SMTP server <input id="smtp_host" placeholder="smtp.gmail.com"></label>
        <label>SMTP port <input id="smtp_port" inputmode="numeric"></label>
        <label>Username <input id="smtp_user" autocomplete="username"></label>
        <label>Password <input id="smtp_password" type="password" autocomplete="current-password"></label>
        <label>From address (optional) <input id="smtp_from"></label>
        <label>IMAP server (to delete sent copies) <input id="imap_host" placeholder="imap.gmail.com"></label>
        <label>Sent folder <input id="sent_folder"></label>
        <label>Trash folder <input id="trash_folder"></label>
      </div>
      <label class="check"><input type="checkbox" id="rememberPw">
        Remember password on this device <span class="hint">(stored unencrypted in this browser; leave off on shared computers)</span></label>
    </details>
  </section>

  <div class="row">
    <button class="secondary" id="testBtn">Test mode: show pairings</button>
    <button class="primary" id="sendBtn">Draw &amp; send emails</button>
  </div>

  <section class="card" id="results" style="margin-top:20px">
    <h2>Test mode pairings <span class="hint">(no emails sent)</span></h2>
    <div id="pairs"></div>
  </section>
</main>
<script>
const DEFAULTS = __DEFAULTS__;
const rowsEl = document.getElementById('rows');
const msg = document.getElementById('msg');
const MAIL = ['smtp_host','smtp_port','smtp_user','smtp_password','smtp_from','imap_host','sent_folder','trash_folder'];
for (const k of MAIL) if (DEFAULTS[k]) document.getElementById(k).value = DEFAULTS[k];
if (DEFAULTS.password_from_env) document.getElementById('smtp_password').placeholder = '(set on server)';

// ---- memory: everything is kept in this browser's localStorage, never on the server
const STORE = 'secretSanta.v1';
function loadSaved() {
  try { return JSON.parse(localStorage.getItem(STORE)) || null; } catch { return null; }
}
let saveTimer;
function save() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    const mail = {};
    for (const k of MAIL) if (k !== 'smtp_password') mail[k] = document.getElementById(k).value;
    const remember = document.getElementById('rememberPw').checked;
    if (remember) mail.smtp_password = document.getElementById('smtp_password').value;
    const participants = collect().map(({name, email, spouse}) => ({name, email, spouse}));
    try {
      localStorage.setItem(STORE, JSON.stringify({ participants, mail, rememberPw: remember }));
      document.getElementById('savedNote').textContent = 'Saved in this browser only.';
    } catch {
      document.getElementById('savedNote').textContent = "This browser isn't allowing saving, so entries won't be remembered.";
    }
  }, 300);
}

function addRow(p = {}) {
  const tr = document.createElement('tr');
  tr.innerHTML = `<td class="num"></td>
    <td><input class="name" placeholder="Name" aria-label="Name"></td>
    <td><input class="email" type="email" placeholder="name@example.com" aria-label="Email"></td>
    <td><input class="spouse" placeholder="Optional" aria-label="Spouse name" list="nameList"></td>
    <td class="del"><button class="icon" title="Remove" aria-label="Remove">✕</button></td>`;
  tr.querySelector('.name').value = p.name || '';
  tr.querySelector('.email').value = p.email || '';
  tr.querySelector('.spouse').value = p.spouse || '';
  tr.querySelector('button').onclick = () => { tr.remove(); renumber(); save(); };
  tr.querySelectorAll('input').forEach(i => i.addEventListener('input', () => { i.classList.remove('bad'); renumber(); save(); }));
  rowsEl.appendChild(tr);
  renumber();
  return tr;
}
function renumber() {
  [...rowsEl.children].forEach((tr, i) => tr.querySelector('.num').textContent = i + 1);
  let dl = document.getElementById('nameList');
  if (!dl) { dl = document.createElement('datalist'); dl.id = 'nameList'; document.body.appendChild(dl); }
  dl.innerHTML = '';
  for (const p of collect()) if (p.name) { const o = document.createElement('option'); o.value = p.name; dl.appendChild(o); }
}
function collect() {
  return [...rowsEl.children].map(tr => ({
    name: tr.querySelector('.name').value.trim(),
    email: tr.querySelector('.email').value.trim(),
    spouse: tr.querySelector('.spouse').value.trim(),
    tr,
  }));
}
function show(kind, text) { msg.className = kind; msg.textContent = text; msg.scrollIntoView({block:'nearest'}); }

function validate() {
  const people = collect().filter(p => p.name || p.email || p.spouse);
  const errs = []; const seen = new Set();
  for (const p of people) {
    const n = p.tr.querySelector('.name'), e = p.tr.querySelector('.email'), s = p.tr.querySelector('.spouse');
    if (!p.name) { n.classList.add('bad'); errs.push('Every row needs a name.'); }
    else if (seen.has(p.name.toLowerCase())) { n.classList.add('bad'); errs.push(`"${p.name}" is listed twice.`); }
    seen.add(p.name.toLowerCase());
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(p.email)) { e.classList.add('bad'); errs.push(`Check the email for "${p.name || '?'}".`); }
    if (p.spouse && p.spouse.toLowerCase() === p.name.toLowerCase()) { s.classList.add('bad'); errs.push(`"${p.name}" can't be their own spouse.`); }
  }
  if (people.length < 2) errs.push('Add at least 2 people.');
  if (errs.length) { show('err', [...new Set(errs)].join('\n')); return null; }
  return people.map(({name, email, spouse}) => ({name, email, spouse}));
}

async function post(url, body) {
  const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const data = await r.json().catch(() => ({error:'Unexpected server response.'}));
  if (!r.ok) throw new Error(data.error || 'Something went wrong.');
  return data;
}
function busy(on) { document.getElementById('testBtn').disabled = on; document.getElementById('sendBtn').disabled = on; }

document.getElementById('add').onclick = () => addRow().querySelector('.name').focus();

document.getElementById('testBtn').onclick = async () => {
  const participants = validate(); if (!participants) return;
  busy(true);
  try {
    const { pairings } = await post('/api/test', { participants });
    const box = document.getElementById('pairs'); box.innerHTML = '';
    for (const p of pairings) {
      const d = document.createElement('div'); d.className = 'pair';
      const a = document.createElement('span'); a.textContent = p.gifter;
      const b = document.createElement('span'); b.textContent = '→ ' + p.giftee;
      d.append(a, b); box.appendChild(d);
    }
    document.getElementById('results').style.display = 'block';
    show('ok', 'Test draw complete. No emails were sent.');
  } catch (e) { show('err', e.message); } finally { busy(false); }
};

document.getElementById('sendBtn').onclick = async () => {
  const participants = validate(); if (!participants) return;
  if (!confirm(`Draw names and email all ${participants.length} people now?`)) return;
  const mail = {}; for (const k of MAIL) mail[k] = document.getElementById(k).value.trim();
  document.getElementById('results').style.display = 'none';
  document.getElementById('pairs').innerHTML = '';
  busy(true); show('ok', 'Sending…');
  try {
    const { log, warnings } = await post('/api/send', { participants, mail });
    let text = 'Done! Emails sent. Nobody (including you) has seen the pairings.\n' + log.join('\n');
    if (warnings.length) text += '\n\nNote:\n' + warnings.join('\n');
    show('ok', text);
  } catch (e) {
    show('err', e.message);
    if (/settings/.test(e.message)) document.getElementById('mailBox').open = true;
  } finally { busy(false); }
};

document.getElementById('importBtn').onclick = () => document.getElementById('csvFile').click();
document.getElementById('csvFile').onchange = async (ev) => {
  const file = ev.target.files[0]; if (!file) return;
  const lines = (await file.text()).replace(/^﻿/, '').split(/\r?\n/).filter(l => l.trim());
  const split = l => l.split(',').map(c => c.trim().replace(/^"(.*)"$/, '$1'));
  const head = split(lines.shift() || '').map(h => h.toLowerCase());
  const [ni, ei, si] = ['name','email','spouse'].map(h => head.indexOf(h));
  if (ni < 0 || ei < 0) { show('err', 'CSV needs a header row with name and email columns.'); return; }
  rowsEl.innerHTML = '';
  for (const l of lines) { const c = split(l); addRow({name:c[ni], email:c[ei], spouse: si >= 0 ? c[si] : ''}); }
  if (!rowsEl.children.length) addRow();
  save();
  show('ok', `Imported ${rowsEl.children.length} people.`);
  ev.target.value = '';
};

const saved = loadSaved();
if (saved) {
  for (const [k, v] of Object.entries(saved.mail || {})) { const el = document.getElementById(k); if (el && v) el.value = v; }
  document.getElementById('rememberPw').checked = !!saved.rememberPw;
}
const savedPeople = (saved && saved.participants || []).filter(p => p.name || p.email || p.spouse);
if (savedPeople.length) savedPeople.forEach(p => addRow(p)); else for (let i = 0; i < 3; i++) addRow();
if (savedPeople.length) document.getElementById('savedNote').textContent = `Loaded ${savedPeople.length} people saved in this browser.`;

for (const k of MAIL) document.getElementById(k).addEventListener('input', save);
document.getElementById('rememberPw').addEventListener('change', save);
document.getElementById('clearBtn').onclick = () => {
  if (!confirm('Clear all saved participants and email settings from this browser?')) return;
  try { localStorage.removeItem(STORE); } catch {}
  rowsEl.innerHTML = ''; for (let i = 0; i < 3; i++) addRow();
  for (const k of MAIL) document.getElementById(k).value = DEFAULTS[k] || '';
  document.getElementById('rememberPw').checked = false;
  document.getElementById('savedNote').textContent = 'Saved data cleared.';
};
</script>
</body></html>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description="Secret Santa web form.")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true", help="Don't open a browser automatically.")
    args = ap.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"Secret Santa is running at {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
