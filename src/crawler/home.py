"""The landing page: one HTML template, filled once from settings.

A visitor who opens the bare service URL, or any path that is not an
endpoint, lands here, can run the crawler on any URL, and can try the three
URLs the assignment names with one click.
"""

import json
from html import escape
from importlib import resources
from urllib.parse import quote

from crawler.config import settings
from crawler.model import Reason

# (label, URL, what the recorded run in docs/samples returned)
EXAMPLES = (
    ("Amazon product page",
     "http://www.amazon.com/Cuisinart-CPT-122-Compact-2-Slice-Toaster/dp/B009GQ034C/"
     "ref=sr_1_1?s=kitchen&ie=UTF8&qid=1431620315&sr=1-1&keywords=toaster",
     "success · product"),
    ("REI blog post",
     "http://blog.rei.com/camp/how-to-introduce-your-indoorsy-friend-to-the-outdoors/",
     "blocked · 403"),
    ("CNN article",
     "https://www.cnn.com/2025/09/23/tech/google-study-90-percent-tech-jobs-ai",
     "success · article"),
    ("Wikipedia: Web crawler",
     "https://en.wikipedia.org/wiki/Web_crawler",
     "success · article"),
)


# One sentence per reason, shown under the status badge. Every Reason must be here.
REASON_NOTES: dict[Reason, str] = {
    Reason.ok: "The page was fetched and read.",
    Reason.robots_disallowed: "The site's robots.txt disallows this path; the page was not fetched.",
    Reason.captcha: "The site answered with a CAPTCHA page instead of the content. Reported, not solved.",
    Reason.forbidden: "The site refused the request (401, 403, 451, or a denial page served with 200). Reported, not evaded.",
    Reason.rate_limited: "The site asked us to slow down (429).",
    Reason.bad_url: "Not an http or https URL we can fetch.",
    Reason.private_address: "Loopback, private or link-local target; the crawler refuses these without fetching.",
    Reason.robots_unavailable: "robots.txt answered 5xx, so we cannot know the policy; the site is unwell, not refusing.",
    Reason.dns_error: "The hostname does not resolve.",
    Reason.connect_error: "Could not complete a connection (refused, reset, or a TLS certificate problem).",
    Reason.timeout: "The server did not answer within the time limit, after retries.",
    Reason.server_error: "The server answered 5xx after retries.",
    Reason.not_found: "404 or 410: the page does not exist.",
    Reason.client_error: "A 4xx other than the ones above.",
    Reason.redirect_not_followed: "A redirect was returned while redirect-following is disabled.",
    Reason.not_html: "The response is not an HTML document (PDF, JSON, image…).",
    Reason.too_large: "The body exceeded the size limit and was abandoned.",
    Reason.parse_failed: "The HTML could not be parsed.",
    Reason.no_content: "A 200 with almost no visible text and no metadata for search engines: an error, maintenance or block page in disguise.",
}


def _example_link(label: str, url: str, expected: str) -> str:
    href = f"/extract?url={quote(url, safe='')}"
    return (f'<a class="btn" href="{href}" data-url="{escape(url, quote=True)}">'
            f"{escape(label)}<small>{escape(expected)}</small></a>")


def render_home() -> str:
    template = resources.files("crawler").joinpath("templates/home.html").read_text()
    repo = (
        f'<span><a href="{escape(settings.repo_url, quote=True)}">'
        "source &amp; design docs</a></span>"
        if settings.repo_url
        else ""
    )
    return (
        template.replace("__EXAMPLES__", "".join(_example_link(*e) for e in EXAMPLES))
        .replace("__REASONS_JSON__", json.dumps({r.value: note for r, note in REASON_NOTES.items()}))
        .replace("__AUTHOR__", escape(settings.author_line))
        .replace("__REPO__", repo)
    )
