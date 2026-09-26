# movie-alerts

Push notifications when a film's booking opens at [VOX Cinemas Egypt](https://egy.voxcinemas.com).

It scrapes the VOX listings, tracks which films are bookable, and sends a
[ntfy.sh](https://ntfy.sh) notification when a scheduled check detects booking opening for a film you
care about — by genre (horror) or by an exact-title watchlist.

**Error channel setup:** Set `NTFY_ERROR_TOPIC` to a separate ntfy topic name,
add it as a GitHub Actions repository secret, and subscribe to that topic in
the ntfy app to receive blocking and scraping-failure alerts. For local runs,
export `NTFY_ERROR_TOPIC=your-errors-topic`. See [Error notifications and logs](#error-notifications-and-logs)
for testing and troubleshooting.

## How it works

`vox_notify.py` runs one pass:

1. Scrapes the `whatson` and `comingsoon` listing pages, reading each film's
   title, URL, and whether booking is open (the page links to its
   `#showtimes` anchor).
2. Compares the current listings against the previous run stored in
   `state_horror.json` or `state_doomsday.json`.
3. For any film that just flipped from *not bookable* → *bookable* and
   [matches your filters](#configuration), POSTs a notification to ntfy.
4. Writes the channel’s new state file for next time.

The **first run** only records a baseline — it never sends alerts, so you don't
get spammed by everything that's already bookable.

## Configuration

Edit the constants at the top of `vox_notify.py`:

| Setting | Purpose |
| --- | --- |
| `GENRES` | Genres to watch, lowercase. Default: `{"horror"}`. |
| `WATCHLIST` | Exact film titles to watch regardless of genre, e.g. `{"Avengers: Doomsday"}`. Marvel films are tagged only "Action", so match them by title here. |

Alerts use three separate ntfy channels:

| Environment variable / GitHub secret | Alerts |
| --- | --- |
| `NTFY_HORROR_TOPIC` | Movies matching `GENRES` (horror by default). |
| `NTFY_DOOMSDAY_TOPIC` | Exact titles in `WATCHLIST` (Avengers: Doomsday by default). |
| `NTFY_ERROR_TOPIC` | Blocking, network, scraping, state-processing, or notification-delivery failures. |

Choose three different, hard-to-guess topic names and subscribe to them in the
ntfy app on your phone. Anyone who knows a topic can read its messages.
The selected booking channel and error topic are required. Running both channels
requires all three variables. A movie matching both filters can alert on each channel’s schedule.

When migrating from `NTFY_TOPIC`, you can reuse your existing topic for horror
and choose a new topic for Doomsday. The old variable is no longer used.
Keep `state.json` so previously observed booking openings are not replayed.

## Running locally

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows;  source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt

# set all topics, then run
export NTFY_HORROR_TOPIC=your-horror-topic
export NTFY_DOOMSDAY_TOPIC=your-doomsday-topic
export NTFY_ERROR_TOPIC=your-errors-topic
python vox_notify.py
```

On Windows PowerShell:

```powershell
$env:NTFY_HORROR_TOPIC = "your-horror-topic"
$env:NTFY_DOOMSDAY_TOPIC = "your-doomsday-topic"
$env:NTFY_ERROR_TOPIC = "your-errors-topic"
python vox_notify.py
```

The scripts read environment variables; they do not automatically load `.env`.
If you store these assignments in `.env`, load them in macOS/Linux with
`set -a; source .env; set +a` before running.

To send a real sample notification to any channel without changing state:

```bash
python test_notification.py horror
python test_notification.py doomsday
python test_notification.py errors
```

## Running on a schedule (GitHub Actions)

`.github/workflows/vox.yml` has three schedules (UTC):

- Horror: every three hours at minute 17 (`17 */3 * * *`).
- Doomsday: minutes 2, 7, 12, …, 57 of every hour during November and December
  (`2-59/5 * * 11-12 *`). This repeats annually.
- Verity: minutes 2, 7, 12, …, 57 of every hour, year-round
  (`2-59/5 * * * *`).

Each scheduled run selects only the channel corresponding to the triggering cron
expression. Manual runs offer a `channel` choice: `horror`, `doomsday`, or `verity`
(default: `horror`). Locally, use `python vox_notify.py --channel verity` or select
`horror` or `doomsday`. The local default `all` checks horror and Doomsday only.

Successful runs commit `state_horror.json`, `state_doomsday.json`, and
`state_verity.json` when present. Failed runs do not execute the commit step.

Each checker saves its own state so frequent Doomsday checks cannot consume horror
booking transitions. On migration, each uses the existing `state.json` as its
baseline. The workflow commits updated channel state files and serializes runs.

GitHub Actions schedules can be delayed, so this is not an instant-booking guarantee.

To enable it:

1. Add all three topics as repo secrets: **Settings → Secrets and variables →
   Actions → New repository secret**, named `NTFY_HORROR_TOPIC`,
   `NTFY_DOOMSDAY_TOPIC`, and `NTFY_ERROR_TOPIC`.
2. Push to `main`. The workflow runs on its cron schedule, or manually via the
   **Actions** tab → *VOX booking alerts* → *Run workflow*.

## Error notifications and logs

Errors go to a dedicated ntfy topic, separate from both movie channels.

### Setup and test

1. Choose a different, hard-to-guess topic name for errors and subscribe to it
   in the ntfy app.
2. Add a GitHub Actions repository secret named `NTFY_ERROR_TOPIC` with that
   topic name. The workflow passes it to the checker on all three schedules.
3. For local runs, export the same variable. To send a real test error alert:

   ```bash
   export NTFY_ERROR_TOPIC=your-errors-topic
   .venv/bin/python test_notification.py errors
   ```

The test sends a sample message without scraping VOX or changing booking state.
The scripts do not automatically load `.env`; if using that file, load it as
shown under [Running locally](#running-locally).

### What triggers an error alert

- HTTP request failures, including **403** and **429**, which may indicate
  blocking or rate limiting.
- Network failures and request timeouts.
- A listing page yielding no movies, which may indicate a block page or changed markup.
- Doomsday missing from both listings during a Doomsday check.
- Genre lookup or parsing failures during a horror check.
- State-processing errors or failed booking-notification delivery.

The checker writes a concise error to standard error, attempts a high-priority
notification titled **Movie alerts: checker failed**, and exits with status `1`.
For example, a Doomsday check receiving HTTP 403 sends:

```text
doomsday checker failed: HTTP 403 (403/429 may indicate blocking or rate limiting). Booking state was not advanced.
```

Every failed run attempts an alert; repeated errors are not deduplicated or muted.
Scraping and notification-delivery failures occur before that channel's state is
saved, allowing the next run to retry. A state-file write failure itself may leave
an incomplete file. In an `all` run, an earlier channel may already have completed
before the other channel fails.

### Where to find logs

Locally, errors appear in the terminal. In GitHub, open **Actions → VOX booking
alerts → the failed run → check → Run alerter** to read the checker output.
The application does not maintain a separate log file.

If the error topic is missing or ntfy is unreachable, the checker logs
`Failure alert could not be delivered (...)`; no error push is guaranteed in that
case. These alerts cover failures caught while the Python checker runs. They do
not cover a workflow that never starts, dependency installation failures, or a
later Git commit/push failure; inspect the relevant Actions step for those.

## Notes

- **User-Agent matters.** The site is picky about how requests are shaped —
  some User-Agent values get no response and the request just hangs until it
  times out. The script sends a plain client User-Agent, which works reliably.
  If runs start timing out, check this first.
- `state.json` is the migration baseline; `state_horror.json` and
  `state_doomsday.json` persist each channel’s subsequent checks.
- `.env` (holding your topic names) is gitignored — keep your topic out of the repo.
