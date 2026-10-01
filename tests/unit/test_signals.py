import pytest

from leadharvest.enrich.signals import detect_tech, has_mobile_viewport
from leadharvest.scoring import score_lead
from tests.unit.test_v1_features import lead


@pytest.mark.parametrize(
    ("html", "headers", "expected"),
    [
        ('<link rel="stylesheet" href="/wp-content/themes/x/style.css">', {}, ["wordpress"]),
        ('<meta name="generator" content="WordPress 6.5">', {}, ["wordpress"]),
        ('<script src="https://cdn.shopify.com/s/files/x.js"></script>', {}, ["shopify"]),
        ("<p>shop</p>", {"X-ShopId": "123"}, ["shopify"]),
        ('<img src="https://static.wixstatic.com/media/a.jpg">', {}, ["wix"]),
        ("<p>x</p>", {"x-wix-request-id": "abc"}, ["wix"]),
        ('<div data-wf-page="123">', {}, ["webflow"]),
        ('<meta name="Generator" content="Drupal 10">', {}, ["drupal"]),
        ('<meta name="generator" content="Joomla! - Open Source">', {}, ["joomla"]),
        ('<link href="https://static1.squarespace.com/x.css">', {}, ["squarespace"]),
        ('<img src="https://img1.wsimg.com/a.png">', {}, ["godaddy"]),
        ("<p>Plain hand-written site</p>", {"server": "nginx"}, []),
        # Plain links to platforms are not platform markers.
        ('<a href="https://ourblog.blogspot.com">Blog</a> <a href="https://x.myshopify.com">Shop</a>',
         {}, []),
    ],
)  # fmt: skip
def test_detect_tech(html: str, headers: dict[str, str], expected: list[str]) -> None:
    assert detect_tech(html, headers) == expected


def test_mobile_viewport() -> None:
    assert has_mobile_viewport(
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
    )
    assert has_mobile_viewport("<META NAME=viewport CONTENT='width=device-width'>")
    assert not has_mobile_viewport('<meta name="viewport" content="width=1024">')
    assert not has_mobile_viewport("<html><head><title>Old site</title></head></html>")


def test_no_mobile_viewport_flag() -> None:
    assert (
        "no_mobile_viewport" in score_lead(lead(website="https://a.ph", mobile_viewport=False))[1]
    )
    assert "no_mobile_viewport" not in score_lead(lead(website="https://a.ph"))[1]  # unknown
