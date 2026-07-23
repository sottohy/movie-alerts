# movie-alerts

Push notifications when a film's booking opens at [VOX Cinemas Egypt](https://egy.voxcinemas.com).

It scrapes the VOX listings, tracks which films are bookable, and sends a
[ntfy.sh](https://ntfy.sh) notification the moment booking opens for a film you
care about — by genre (horror) or by an exact-title watchlist.

## How it works

`vox_notify.py` runs one pass:

1. Scrapes the `whatson` and `comingsoon` listing pages, reading each film's
   title, URL, and whether booking is open (the page links to its
   `#showtimes` anchor).
2. Compares the current listings against the previous run stored in
   `state.json`.
3. For any film that just flipped from *not bookable* → *bookable* and
   [matches your filters](#configuration), POSTs a notification to ntfy.
4. Writes the new `state.json` for next time.

The **first run** only records a baseline — it never sends alerts, so you don't
get spammed by everything that's already bookable.

## Configuration

Edit the constants at the top of `vox_notify.py`:

| Setting | Purpose |
| --- | --- |
| `GENRES` | Genres to watch, lowercase. Default: `{"horror"}`. |
| `WATCHLIST` | Exact film titles to watch regardless of genre, e.g. `{"Avengers: Doomsday"}`. Marvel films are tagged only "Action", so match them by title here. |

The ntfy topic is read from the `NTFY_TOPIC` environment variable. Pick a hard
-to-guess topic name, then subscribe to it in the ntfy app on your phone
(anyone who knows the topic can read its messages).

## Running locally

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows;  source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt

# set your topic, then run
NTFY_TOPIC=your-topic-name python vox_notify.py
```

On Windows PowerShell: `$env:NTFY_TOPIC = "your-topic-name"; python vox_notify.py`

## Running on a schedule (GitHub Actions)

`.github/workflows/vox.yml` runs the checker every 3 hours and commits the
updated `state.json` back to the repo so state persists between runs.

To enable it:

1. Add your topic as a repo secret: **Settings → Secrets and variables →
   Actions → New repository secret**, named `NTFY_TOPIC`.
2. Push to `main`. The workflow runs on its cron schedule, or manually via the
   **Actions** tab → *VOX booking alerts* → *Run workflow*.

## Notes

- **User-Agent matters.** The site's WAF silently drops requests with custom or
  `Mozilla/...` User-Agents (the connection hangs until timeout). The script
  sends `curl/8.8.0`, which passes. If runs start timing out, check this first.
- `state.json` is committed so the cloud runs have a baseline to diff against.
- `.env` (holding `NTFY_TOPIC`) is gitignored — keep your topic out of the repo.
