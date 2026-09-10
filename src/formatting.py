"""
Formats expiration dates to match how Webull displays them in its option chain
picker: "DD Mon YY", with a "(W)" suffix for weekly (non-standard-monthly)
expirations — e.g. "2026-09-25" -> "25 Sep 26 (W)", "2026-10-16" -> "16 Oct 26".

"Monthly" here means the standard equity-options monthly cycle: the third Friday of
the month. Anything else listed (most weeks now have their own expiration) gets the
(W) tag, same as Webull's own chain UI.
"""
from datetime import datetime


def _is_weekly(d: datetime) -> bool:
    """
    Webull tags "(W)" only on Friday expirations that aren't the standard monthly
    (third Friday). End-of-month expirations (e.g. a Wednesday EOM listing on SPY/QQQ)
    aren't Fridays at all and aren't tagged either — only non-standard Fridays are.
    """
    if d.weekday() != 4:  # not a Friday at all — e.g. an EOM listing
        return False
    return not (15 <= d.day <= 21)  # Friday, but not the third-Friday standard monthly


def format_expiration_webull(date_str: str) -> str:
    if not date_str:
        return ""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    label = d.strftime("%d %b %y")
    if _is_weekly(d):
        label += " (W)"
    return label
