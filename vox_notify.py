import argparse
import json
import os
import re
import sys

import requests
from bs4 import BeautifulSoup


BASE = "https://egy.voxcinemas.com"

NTFY_HORROR_TOPIC = os.environ.get("NTFY_HORROR_TOPIC")
NTFY_DOOMSDAY_TOPIC = os.environ.get("NTFY_DOOMSDAY_TOPIC")
NTFY_VERITY_TOPIC = os.environ.get("NTFY_VERITY_TOPIC")
NTFY_ERROR_TOPIC = os.environ.get("NTFY_ERROR_TOPIC")

GENRES = {"horror"}
WATCHLIST = {"Avengers: Doomsday"}
VERITY_TITLE = "Verity"

STATE_FILE = "state.json"
STATE_FILES = {
    "horror": "state_horror.json",
    "doomsday": "state_doomsday.json",
    "verity": "state_verity.json",
}

UA = {
    "User-Agent": "curl/8.8.0"
}


def get(url):
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    return r.text


def ld_blobs(html):
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all("script", type="application/ld+json"):
        raw = tag.string or tag.get_text()

        if not raw:
            continue

        try:
            yield json.loads(raw)
        except json.JSONDecodeError:
            continue


def listing(page):
    """
    Return:
    {
        slug: {
            title,
            url,
            booking_open
        }
    }
    """

    html = get(f"{BASE}/movies/{page}")
    out = {}

    for blob in ld_blobs(html):
        for el in blob.get("itemListElement", []):
            item = el.get("item", {})

            if item.get("@type") != "Movie":
                continue

            url = item.get("url", "")
            slug = url.rstrip("/").rsplit("/", 1)[-1]

            if not slug:
                continue

            out[slug] = {
                "title": item.get("name", slug),
                "url": url,
                "booking_open": False,
            }

    for m in re.finditer(r'href="/movies/([^"#]+)#showtimes"', html):
        slug = m.group(1)

        if slug in out:
            out[slug]["booking_open"] = True

    if not out:
        raise RuntimeError("No films parsed")

    return out


def fetch_genre(slug):
    try:
        html = get(f"{BASE}/movies/{slug}")

    except requests.RequestException:
        return None

    for blob in ld_blobs(html):
        g = blob.get("genre")

        if isinstance(g, list):
            g = ", ".join(g)

        if g:
            return g.strip()

    m = re.search(
        r"<strong>Genre:</strong>\s*([^<]+)<",
        html,
        re.I,
    )

    return m.group(1).strip() if m else None


def load_state(path=STATE_FILE):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state, path=STATE_FILE):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def notification_topics(film, channel="all"):
    topics = []

    if channel in ("all", "doomsday") and film["title"] in WATCHLIST:
        topics.append(NTFY_DOOMSDAY_TOPIC)

    genre = film.get("genre")

    if channel in ("all", "horror") and genre and any(
        wanted in genre.lower()
        for wanted in GENRES
    ):
        topics.append(NTFY_HORROR_TOPIC)

    return topics


def notify(film, topic):
    body = (
        f"{film['title']} "
        f"({film.get('genre') or 'genre unknown'}) "
        f"- booking is now open!!"
    )

    response = requests.post(
        f"https://ntfy.sh/{topic}",
        data=body.encode("utf-8"),
        headers={
            "Title": "Time For The Movies",
            "Priority": "high",
            "Click": BASE + film["url"] + "#showtimes",
        },
        timeout=30,
    )

    response.raise_for_status()


def notify_error(channel, message):
    text = f"{channel} checker failed: {message}"
    print(text, file=sys.stderr)

    if not NTFY_ERROR_TOPIC:
        return

    try:
        response = requests.post(
            f"https://ntfy.sh/{NTFY_ERROR_TOPIC}",
            data=text.encode("utf-8"),
            headers={
                "Title": "Movie alerts: checker failed",
                "Priority": "high",
            },
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"Failure alert could not be delivered ({exc})", file=sys.stderr)


def get_all_listings():
    current = {}

    for page in ("whatson", "comingsoon"):
        for slug, film in listing(page).items():
            if slug not in current or film["booking_open"]:
                current[slug] = film

    return current


def _error_message(exc):
    if isinstance(exc, requests.HTTPError):
        status = exc.response.status_code if exc.response is not None else ""
        if status:
            return f"HTTP {status} (403/429 may indicate blocking or rate limiting). Booking state was not advanced."
        return f"HTTP error. Booking state was not advanced."

    message = str(exc).strip()
    if message:
        return f"{message}. Booking state was not advanced."
    return f"{type(exc).__name__}. Booking state was not advanced."


def run_doomsday_check():
    print("Running Doomsday-only check...")

    try:
        current = get_all_listings()

        if not current:
            raise RuntimeError("No films parsed - page structure may have changed.")

        path = STATE_FILES["doomsday"]
        state = load_state(path)

        if not state and os.path.exists(STATE_FILE):
            state = load_state(STATE_FILE)

        doomsday_found = False

        for slug, film in current.items():
            if film["title"] not in WATCHLIST:
                continue

            doomsday_found = True
            prev = state.get(slug)
            was_open = bool(prev and prev.get("booking_open"))
            is_open = film["booking_open"]
            print(f"{film['title']}: previous={was_open}, current={is_open}")
            film["genre"] = prev.get("genre") if prev else None

            if is_open and not was_open:
                notify(film, NTFY_DOOMSDAY_TOPIC)
                print("DOOMSDAY ALERT:", film["title"])

            state[slug] = film

        if not doomsday_found:
            raise RuntimeError("Avengers: Doomsday not found in VOX listings.")

        save_state(state, path)
        return 0

    except Exception as exc:
        notify_error("doomsday", _error_message(exc))
        return 1


def run_verity_check():
    print("Running Verity-only check...")

    try:
        current = get_all_listings()

        if not current:
            raise RuntimeError("No films parsed - page structure may have changed.")

        path = STATE_FILES["verity"]
        state = load_state(path)

        if not state and os.path.exists(STATE_FILE):
            state = load_state(STATE_FILE)

        verity_found = False

        for slug, film in current.items():
            if film["title"] != VERITY_TITLE:
                continue

            verity_found = True
            prev = state.get(slug)
            was_open = bool(prev and prev.get("booking_open"))
            is_open = film["booking_open"]
            print(f"{film['title']}: previous={was_open}, current={is_open}")
            film["genre"] = prev.get("genre") if prev else None

            if is_open and not was_open:
                notify(film, NTFY_VERITY_TOPIC)
                print("VERITY ALERT:", film["title"])

            state[slug] = film

        if not verity_found:
            raise RuntimeError("Verity not found in VOX listings.")

        save_state(state, path)
        return 0

    except Exception as exc:
        notify_error("verity", _error_message(exc))
        return 1


def run_horror_check():
    print("Running full movie check...")

    try:
        current = get_all_listings()

        if not current:
            raise RuntimeError("No films parsed - page structure may have changed.")

        path = STATE_FILES["horror"]
        state = load_state(path)

        if not state and os.path.exists(STATE_FILE):
            state = load_state(STATE_FILE)

        first_run = not state
        alerts = []

        for slug, film in current.items():
            if film["title"] in WATCHLIST:
                continue

            prev = state.get(slug)

            if prev and prev.get("genre"):
                film["genre"] = prev["genre"]
            else:
                film["genre"] = fetch_genre(slug)

            was_open = bool(prev and prev.get("booking_open"))

            if film["booking_open"] and not was_open and notification_topics(film, "horror"):
                alerts.append(film)

        if first_run:
            print(f"First run - baseline of {len(current)} films, no alerts sent.")
            alerts = []

        for film in alerts:
            for topic in notification_topics(film, "horror"):
                notify(film, topic)
            print("ALERT:", film["title"], "-", film.get("genre"))

        for slug, film in current.items():
            if film["title"] in WATCHLIST:
                continue
            state[slug] = film

        save_state(state, path)
        print(f"{len(current)} films tracked, {len(alerts)} alert(s) sent.")
        return 0

    except Exception as exc:
        notify_error("horror", _error_message(exc))
        return 1


def run(channel):
    channel = {"full": "all", "all": "all"}.get(channel, channel)

    if channel == "all":
        status = 0
        status = max(status, run_horror_check())
        status = max(status, run_doomsday_check())
        return status

    if channel == "doomsday":
        return run_doomsday_check()

    if channel == "verity":
        return run_verity_check()

    if channel == "horror":
        return run_horror_check()

    raise ValueError(f"Unknown channel: {channel}")


def main():
    parser = argparse.ArgumentParser(description="Run the VOX booking checker.")
    parser.add_argument("--channel", choices=("all", "horror", "doomsday", "verity"), default="all")
    args = parser.parse_args()

    if args.channel == "verity":
        if not NTFY_VERITY_TOPIC:
            sys.exit("Set NTFY_VERITY_TOPIC.")
        if NTFY_VERITY_TOPIC in {NTFY_HORROR_TOPIC, NTFY_DOOMSDAY_TOPIC}:
            sys.exit("Use different topics for horror, Avengers: Doomsday, and Verity alerts.")
        raise SystemExit(run(args.channel))

    if not NTFY_HORROR_TOPIC or not NTFY_DOOMSDAY_TOPIC:
        sys.exit("Set both NTFY_HORROR_TOPIC and NTFY_DOOMSDAY_TOPIC.")

    if NTFY_HORROR_TOPIC == NTFY_DOOMSDAY_TOPIC:
        sys.exit("Use different topics for horror and Avengers: Doomsday alerts.")

    raise SystemExit(run(args.channel))


if __name__ == "__main__":
    main()