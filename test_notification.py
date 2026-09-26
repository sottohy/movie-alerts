"""Send a real sample alert to one selected notification channel."""
import argparse

from vox_notify import NTFY_DOOMSDAY_TOPIC, NTFY_HORROR_TOPIC, notify, notify_error


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("channel", choices=("horror", "doomsday", "errors"))
    args = parser.parse_args()

    if args.channel == "errors":
        notify_error("test", "This is a test failure notification")
        print("Test notification sent to the errors channel.")
        raise SystemExit(0)

    if args.channel == "horror":
        topic = NTFY_HORROR_TOPIC
        film = {
            "title": "Other Mommy",
            "genre": "Horror",
            "url": "/movies/other-mommy",
        }
    else:
        topic = NTFY_DOOMSDAY_TOPIC
        film = {
            "title": "Avengers: Doomsday",
            "genre": "Action, Adventure",
            "url": "/movies/avengers-doomsday",
        }

    if not topic:
        parser.error(f"Set NTFY_{args.channel.upper()}_TOPIC before sending a test.")
    notify(film, topic)
    print(f"Test notification sent to the {args.channel} channel.")
