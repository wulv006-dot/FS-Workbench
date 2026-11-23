"""Read a single MLB26 offer from a fresh public browser page."""

from urllib.parse import parse_qs, urlsplit

from .quotes import EldoradoOffer, parse_eldorado


_ELDORADO_PATH = "/mlb-the-show-stubs/g/412"
_ELDORADO_DEVICES = {"PS": "PlayStation", "XBOX": "Xbox"}
_ELDORADO_ROW = "eld-currency-other-sellers-list .offer-row"
_ELDORADO_READ = r"""() => {
    const row = document.querySelector("eld-currency-other-sellers-list .offer-row");
    const devices = [...document.querySelectorAll(".offer-trade-environments .font-bold")]
        .map(node => node.innerText.trim()).filter(Boolean);
    return {
        usd: /USD\s*-\s*\$/.test(document.body.innerText),
        devices: [...new Set(devices)],
        seller: row?.querySelector(".profile__username")?.innerText.trim(),
        offer: row?.innerText,
    };
}"""


def is_access_challenge(page):
    return page.evaluate(r"""() =>
        /^(?:just a moment|access denied|verify you are human)/i.test(document.title.trim()) ||
        !!document.querySelector("#challenge-form, #cf-challenge-running, #px-captcha")
    """)


def collect_eldorado(page, platform: str) -> EldoradoOffer:
    device = _ELDORADO_DEVICES[platform]
    url = f"https://www.eldorado.gg{_ELDORADO_PATH}?te_v0={device}"
    response = page.goto(url, wait_until="domcontentloaded", timeout=16000)
    if response is None or response.status != 200:
        status = response.status if response is not None else "no_response"
        raise ValueError(f"eldorado_http_{status}")

    if is_access_challenge(page):
        raise ValueError("eldorado_challenge")
    resolved = urlsplit(page.url)
    if (
        resolved.scheme != "https"
        or resolved.netloc != "www.eldorado.gg"
        or resolved.path != _ELDORADO_PATH
        or parse_qs(resolved.query).get("te_v0") != [device]
    ):
        raise ValueError("eldorado_page_identity_changed")

    page.locator(_ELDORADO_ROW).first.wait_for(state="visible", timeout=7000)
    previous = parse_eldorado(page.evaluate(_ELDORADO_READ), device)
    page.wait_for_timeout(300)
    observed = parse_eldorado(page.evaluate(_ELDORADO_READ), device)
    if observed != previous:
        raise ValueError("eldorado_recommended_offer_changed")
    return observed
