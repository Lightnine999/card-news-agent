"""Claude CLI가 그린 SVG 거르기 (cardnews/images/svg.py)."""

import pytest

from cardnews.errors import AppError
from cardnews.images import svg

GOOD = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 500">
  <defs><linearGradient id="g"><stop offset="0" stop-color="#102040"/><stop offset="1" stop-color="#187882"/></linearGradient></defs>
  <rect width="400" height="500" fill="url(#g)"/>
  <circle cx="200" cy="380" r="60" fill="#2a9d8f" opacity="0.6"/>
  <path d="M0 450 L400 300 L400 500 Z" fill="#264653"/>
</svg>"""


def test_good_svg_is_kept_and_sized_for_card():
    clean, removed = svg.sanitize(GOOD)
    assert removed == []
    assert 'viewBox="0 0 400 500"' in clean  # 그림 좌표는 그대로
    assert 'width="1080"' in clean and 'height="1350"' in clean  # 보이는 크기는 카드 크기
    assert "<circle" in clean and "url(#g)" in clean


def test_text_script_and_events_are_removed():
    dirty = GOOD.replace("</svg>", """
  <text x="10" y="40">최신 AI 소식</text>
  <script>alert(1)</script>
  <rect x="1" y="1" width="5" height="5" onclick="alert(2)" fill="#fff"/>
  <foreignObject><div>hi</div></foreignObject>
  <image href="https://evil.example.com/x.png"/>
</svg>""")
    clean, removed = svg.sanitize(dirty)
    for bad in ("<text", "script", "onclick", "foreignObject", "<image", "evil.example.com", "alert"):
        assert bad not in clean
    assert {"text", "script", "foreignObject", "image", "onclick"} <= set(removed)


def test_external_references_in_attributes_are_dropped():
    dirty = GOOD.replace('fill="#2a9d8f"', 'fill="url(https://evil.example.com/a.svg#x)"')
    clean, _ = svg.sanitize(dirty)
    assert "evil.example.com" not in clean


@pytest.mark.parametrize("bad", [
    "그림 대신 글만 있어요",
    '<!DOCTYPE svg [<!ENTITY a "aaaa">]><svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="1" height="1"/></svg>',
])
def test_unusable_svg_is_rejected(bad):
    with pytest.raises(AppError) as err:
        svg.sanitize(bad)
    assert err.value.code == "IMAGE_FAILED"
