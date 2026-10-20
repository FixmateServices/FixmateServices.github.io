# FixMate booking server

The website in the parent folder is still a static site. This folder adds the
part that cannot be done in the browser: working out what is genuinely free,
saving it in one place, and making it impossible for two people to take the same
slot.

Standard library only. No pip install, no build step, no node_modules.

```
server/
  config.json        every business rule lives here, nothing is hard-coded
  run.py             start the server
  fixmate/
    tz.py            Europe/London <-> UTC, DST-safe
    config.py        reads and validates config.json
    db.py            SQLite schema, the atomic booking guarantee
    availability.py  which slots exist and which are free
    validate.py      field validation for anything a customer sends
    booking.py       the only code path that writes a booking
    notify.py        optional n8n / Google Sheets copy, after the save
    admin.py         scrypt passwords, signed sessions, CSRF
    http_app.py      routes, static files, security headers
    cli.py           serve / init-admin / show-config / self-test
    tests_selftest.py the test suite
  data/              created at runtime: bookings.db and session.key
```

## Requirements

Python 3.11 or newer. Nothing else.

```bash
python3 --version
```

If `zoneinfo` cannot find Europe/London (common on Windows without Python from
python.org), install the tz data:

```bash
pip install tzdata
```

## First run

```bash
cd server

# 1. Check the engine before trusting it
python3 -m fixmate.cli self-test

# 2. Read the settings that are actually in force
python3 -m fixmate.cli show-config

# 3. Create the admin account (you will use this on /admin.html)
python3 -m fixmate.cli init-admin
#    prompts for a password, minimum 12 characters

# 4. Serve
python3 run.py --port 8080
```

Then open <http://127.0.0.1:8080> for the site and
<http://127.0.0.1:8080/admin.html> for the booking list.

## Booking is closed on purpose right now

`config.json` ships with:

```json
"opening_closed_until_YYYY_MM_DD": "2030-01-01"
```

While today's date is earlier than that, the server refuses every booking with a
503 and tells the customer to phone. This is deliberate: the hours, duration and
notice period in that file are placeholders, not FixMate's real rules.

To open for real bookings:

1. Correct the placeholder values in `config.json` (duration, granularity, notice,
   working hours, holidays).
2. Set `opening_closed_until_YYYY_MM_DD` to a date in the past, e.g.
   `"2020-01-01"`.
3. Restart the server.

Nothing else needs changing. `show-config` prints whether booking is open.

## Settings worth knowing

| Key | Meaning |
| --- | --- |
| `appointment_duration_minutes` | how long one visit takes |
| `slot_granularity_minutes` | gap between offered start times |
| `buffer_before_minutes` | held back at the **start** of each working window |
| `buffer_after_minutes` | held back at the **end** of each working window |
| `min_notice_hours` | how far ahead a customer must book |
| `max_advance_days` | furthest date offered in the calendar |
| `booking_horizon_days` | furthest date the server will actually accept |
| `working_hours` | one or more `[start, end]` windows per weekday |
| `holidays` / `closures` | `YYYY-MM-DD` dates with no slots at all |
| `busy_statuses` | statuses that occupy a slot (`Pending`, `Confirmed`) |
| `show_booked_slots` | show taken times greyed out, or hide them entirely |
| `service_types` | allowed service ids; must match `data.js` service group ids |

Several windows per day is how you express a lunch break:

```json
"mon": [["09:00", "12:00"], ["13:00", "17:00"]]
```

A weekday that is absent or `[]` is closed.

## How double booking is prevented

Not by checking, and not by JavaScript. Three layers, in order:

1. `BEGIN IMMEDIATE` in `booking.py` takes SQLite's write lock before the
   availability re-check, so no other writer can interleave between the check and
   the insert.
2. The re-check runs inside that transaction, so a slot that was free when the
   grid was rendered but taken by the time the form was submitted is refused with
   the message `Sorry, this time slot has just been booked. Please choose another
   available time.`
3. `ux_bookings_active_slot`, a partial UNIQUE index on
   `(local_date, local_time)` for non-cancelled rows, is the actual guarantee. If
   the first two layers were ever removed, the database would still refuse the
   second insert.

Cancelling frees the slot because the index only covers `Pending` and
`Confirmed`.

`tests_selftest.py` proves this with 24 threads booking one slot at the same
instant and asserting exactly one winner and 23 conflicts. If that test fails,
do not go live: the suite prints `DOUBLE-BOOKING PROTECTION IS NOT PROVEN`.

## Optional: Google Sheets via n8n

Google Sheets is a report, never the source of availability. The webhook is
called only after SQLite has committed, so a broken webhook can never lose or
duplicate a booking.

```bash
export N8N_BOOKING_WEBHOOK_URL="https://n8n.example.com/webhook/fixmate-booking"
export N8N_WEBHOOK_SECRET="a-long-random-string"
```

Then set `"enabled": true` in the `notify` block of `config.json`.

The payload is signed with HMAC-SHA256 in the `X-FixMate-Signature` header.
In n8n, add a Code node that recomputes it and rejects anything that does not
match. `notified_at_utc` is set only after n8n accepts, so anything still `NULL`
is retried when the server starts.

## Admin page

`/admin.html` lists bookings newest-last, filters by status, and can confirm or
cancel. Passwords are scrypt hashes. The session is a signed HttpOnly,
SameSite=Strict cookie, and every write also needs the `X-FixMate-CSRF` header,
which the page reads from the session response.

Rotating the password:

```bash
python3 -m fixmate.cli init-admin --force
```

Do not link `/admin.html` from the public site. It is unlisted on purpose; the
robots meta tag on the page also asks search engines to skip it.

## Putting it online

The server binds to `127.0.0.1` on purpose. Put a reverse proxy in front of it
and terminate HTTPS there:

- nginx, Caddy or a platform router (Cloudflare Tunnel, Fly, Render, Railway).
- Forward `X-Forwarded-For`, or the rate limiter cannot tell clients apart.
- Start with `--secure-cookies` so the session cookie is never sent in clear.
- `server/data/` must be on persistent disk. It holds `bookings.db`. On most
  platforms a container filesystem is wiped on redeploy, which would silently
  delete every booking. Back it up.

```bash
python3 run.py --host 127.0.0.1 --port 8080 --secure-cookies
```

Environment variable `FIXMATE_SECURE_COOKIES=1` is equivalent to
`--secure-cookies`.

## Tests

```bash
python3 -m fixmate.cli self-test
```

Covers: working hours and slot generation, holidays and closures, notice and
horizon limits, buffers agreeing between grid and re-check, BST/GMT and the
clocks-going-forward gap, duplicate rejection with the exact required message,
cancel-then-rebook, 24-thread single-slot race, 8 parallel distinct slots, the
closed-booking switch, field validation, the honeypot, password hashing, config
validation, and a full HTTP pass covering the public API, static files, path
traversal, login, CSRF and the admin workflow.

## Backups

```bash
cp server/data/bookings.db /somewhere/else/bookings-$(date +%F).db
```

Use `sqlite3 server/data/bookings.db ".backup out.db"` on a live database so the
copy is consistent.