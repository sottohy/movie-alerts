import json, os, re, sys
import requests
from bs4 import BeautifulSoup

BASE = "https://egy.voxcinemas.com"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC")
# NTFY_TOPIC = "testing"
GENRES = {"horror"}
WATCHLIST = {"Avengers: Doomsday"}   # exact titles to watch regardless of genre
STATE_FILE = "state.json"
UA = {"User-Agent": "curl/8.8.0"}  # site's WAF blackholes custom/Mozilla UAs; a plain client UA passes


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
    """Return {slug: {title, url, booking_open}} for one listing page."""
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

    # A film is bookable if the page links to its #showtimes anchor.
    for m in re.finditer(r'href="/movies/([^"#]+)#showtimes"', html):
        slug = m.group(1)
        if slug in out:
            out[slug]["booking_open"] = True

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
    m = re.search(r"<strong>Genre:</strong>\s*([^<]+)<", html, re.I)
    return m.group(1).strip() if m else None


def matches(film):
    if film["title"] in WATCHLIST:
        return True
    g = film.get("genre")
    if not g:
        return False
    return any(want in g.lower() for want in GENRES)


def notify(film):
    body = f"{film['title']} ({film.get('genre') or 'genre unknown'}) - booking is now open!!"
    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=body.encode("utf-8"),
        headers={
            "Title": "VOX: tickets on sale",
            "Priority": "high",
            "Tags": "clapper",
            "Click": BASE + film["url"] + "#showtimes",
        },
        timeout=30,
    )


def main():
    current = {}
    for page in ("whatson", "comingsoon"):
        for slug, film in listing(page).items():
            # whatson wins: if a film is on both pages, keep the bookable state
            if slug not in current or film["booking_open"]:
                current[slug] = film

    if not current:
        sys.exit("No films parsed - page structure may have changed")

    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}

    first_run = not state
    alerts = []

    for slug, film in current.items():
        prev = state.get(slug)
        film["genre"] = prev["genre"] if prev and prev.get("genre") else fetch_genre(slug)

        was_open = bool(prev and prev.get("booking_open"))
        if film["booking_open"] and not was_open and matches(film):
            alerts.append(film)

    if first_run:
        print(f"First run - baseline of {len(current)} films, no alerts sent.")
        alerts = []

    for film in alerts:
        notify(film)
        print("ALERT:", film["title"], "-", film.get("genre"))

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)

    print(f"{len(current)} films tracked, {len(alerts)} alert(s) sent.")


if __name__ == "__main__":
    main()