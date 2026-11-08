#!/usr/bin/env python3
"""Save a validated public stats card without accessing private credentials."""

from pathlib import Path
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET


SOURCE = (
    "https://github-stats-extended-mu-two.vercel.app/api/"
    "?username=rameziophobia&show_icons=true&theme=darcula"
)
DESTINATION = Path(__file__).resolve().parents[1] / "assets/github-stats.svg"
MAX_BYTES = 100 * 1024
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
ALLOWED_TAGS = {
    "svg", "title", "desc", "style", "defs", "g", "rect", "path", "circle", "text",
}
ALLOWED_ATTRIBUTES = {
    "alignment-baseline", "aria-labelledby", "class", "cx", "cy", "d",
    "data-testid", "dominant-baseline", "fill", "fill-rule", "height", "id",
    "r", "role", "rx", "stroke", "stroke-opacity", "style", "text-anchor",
    "transform", "version", "viewBox", "width", "x", "y",
}
METRICS = {"stars", "contributions", "commits", "prs", "reviews", "issues"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Stats source redirected; keeping the saved card")


def validate_card(data):
    """Reject error cards, partial responses, executable SVG and external assets."""
    if not data or len(data) > MAX_BYTES:
        raise ValueError("Stats card is empty or too large")
    source = data.decode("utf-8")
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)", source, re.IGNORECASE):
        raise ValueError("SVG document declarations are not allowed")
    root = ET.fromstring(source)
    if root.tag != f"{{{SVG_NAMESPACE}}}svg":
        raise ValueError("Stats response is not an SVG")
    metrics = {}
    headers = []
    for element in root.iter():
        if element.tag not in {f"{{{SVG_NAMESPACE}}}{tag}" for tag in ALLOWED_TAGS}:
            raise ValueError("Unexpected element in stats card")
        if set(element.attrib) - ALLOWED_ATTRIBUTES:
            raise ValueError("Unexpected attribute in stats card")
        # The renderer needs no links, images, font downloads or CSS imports.
        values = " ".join(element.attrib.values())
        if element.tag == f"{{{SVG_NAMESPACE}}}style":
            values += element.text or ""
        if re.search(r"[\\]|url\s*\(|@import|https?:|//|data:|javascript:|expression\s*\(", values, re.IGNORECASE):
            raise ValueError("External or executable content in stats card")
        field = element.get("data-testid")
        if field == "header":
            headers.append("".join(element.itertext()).strip())
        if field in METRICS:
            value = "".join(element.itertext()).strip()
            if field in metrics or not re.fullmatch(r"[0-9]+", value):
                raise ValueError("Invalid or duplicate stats metric")
            metrics[field] = int(value)
    if headers != ["Ramez Weissa's GitHub Stats"] or set(metrics) != METRICS:
        raise ValueError("Incomplete stats card or upstream error card")
    return metrics


def fetch_card():
    """Fetch only the public aggregate image; no authentication is sent."""
    request = urllib.request.Request(
        SOURCE,
        headers={"Accept": "image/svg+xml", "User-Agent": "rameziophobia-stats-snapshot"},
    )
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=60) as response:
        if response.status != 200 or response.headers.get_content_type() != "image/svg+xml":
            raise ValueError("Stats source did not return a successful SVG")
        return response.read(MAX_BYTES + 1)


def refresh(destination=DESTINATION, download=fetch_card, pause=time.sleep):
    """Replace the snapshot atomically, only after a complete valid download."""
    for attempt in range(3):
        try:
            data = download()
            break
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == 2:
                raise RuntimeError("Stats source unavailable; keeping the saved card") from None
            pause(5 * (attempt + 1))
    metrics = validate_card(data)
    if destination.exists() and destination.read_bytes() == data:
        return False, metrics
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return True, metrics


if __name__ == "__main__":
    try:
        changed, _ = refresh()
    except Exception:
        # Neither response bodies nor request/error objects belong in CI logs.
        raise SystemExit("Stats refresh failed; the last successful SVG is unchanged") from None
    print("Saved a new stats snapshot" if changed else "Stats snapshot is unchanged")
