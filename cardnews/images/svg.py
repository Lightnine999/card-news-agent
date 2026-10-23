"""Claude CLI가 그린 SVG를 카드 배경으로 쓰기 전에 거르기.

SVG는 글이라 스크립트·외부 링크·글자를 넣을 수 있어요. 허용한 도형·그라디언트만 남기고 다시 만들어요.
- 글자(<text>)는 지워요. 카드 글자는 렌더러가 따로 올려요.
- 스크립트, 이벤트 속성(on…), 외부 주소, 다른 문서 삽입(foreignObject·image·use 외부)은 지워요.
- 그림 좌표(viewBox)는 그대로 두고, 보이는 크기만 카드 크기(1080×1350, 4:5)로 맞춰요.
"""

import re
import xml.etree.ElementTree as ET

from cardnews.errors import AppError

NS = "http://www.w3.org/2000/svg"
WIDTH, HEIGHT = 1080, 1350
MIN_SHAPES = 3
MAX_BYTES = 400_000

SHAPES = {"rect", "circle", "ellipse", "line", "polyline", "polygon", "path"}
CONTAINERS = {"svg", "g", "defs", "linearGradient", "radialGradient", "stop", "clipPath", "mask",
              "pattern", "filter", "feGaussianBlur", "feOffset", "feBlend", "feColorMatrix",
              "feMerge", "feMergeNode", "feFlood", "feComposite", "feTurbulence", "feDisplacementMap"}
ALLOWED_TAGS = SHAPES | CONTAINERS
ALLOWED_ATTRS = {
    "x", "y", "width", "height", "cx", "cy", "r", "rx", "ry", "x1", "y1", "x2", "y2", "fx", "fy",
    "points", "d", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin",
    "stroke-dasharray", "stroke-opacity", "fill-opacity", "fill-rule", "clip-rule", "opacity",
    "transform", "offset", "stop-color", "stop-opacity", "gradientUnits", "gradientTransform",
    "spreadMethod", "patternUnits", "patternTransform", "id", "clip-path", "mask", "filter",
    "stdDeviation", "dx", "dy", "in", "in2", "mode", "result", "values", "type", "flood-color",
    "flood-opacity", "operator", "k1", "k2", "k3", "k4", "baseFrequency", "numOctaves", "seed",
    "scale", "xChannelSelector", "yChannelSelector", "maskUnits", "filterUnits",
    "viewBox", "preserveAspectRatio",
}
LOCAL_URL = re.compile(r"^url\(#[A-Za-z0-9_-]+\)$")


def _bad(message: str) -> AppError:
    return AppError("IMAGE_FAILED", f"Claude CLI가 그린 SVG를 쓸 수 없어요: {message}")


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _safe_value(value: str) -> bool:
    low = value.strip().lower()
    if "javascript:" in low or "data:" in low or "http:" in low or "https:" in low:
        return False
    return "url(" not in low or bool(LOCAL_URL.match(value.strip()))


def _copy(node: ET.Element, removed: list[str]) -> ET.Element | None:
    name = _local(node.tag)
    if name not in ALLOWED_TAGS:
        removed.append(name)
        return None
    clean = ET.Element(f"{{{NS}}}{name}")
    for key, value in node.attrib.items():
        attr = _local(key)
        if attr in ALLOWED_ATTRS and _safe_value(value):
            clean.set(attr, value)
        else:
            removed.append(attr)
    for child in node:
        copied = _copy(child, removed)
        if copied is not None:
            clean.append(copied)
    return clean


def sanitize(text: str) -> tuple[str, list[str]]:
    """(정리한 SVG 문자열, 지운 요소·속성 이름들). 쓸 수 없으면 IMAGE_FAILED."""
    if len(text.encode()) > MAX_BYTES:
        raise _bad("파일이 너무 커요.")
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise _bad("DOCTYPE·ENTITY 선언은 받지 않아요.")
    try:
        root = ET.fromstring(text.strip())
    except ET.ParseError as err:
        raise _bad("SVG 형식이 아니에요.") from err
    if _local(root.tag) != "svg":
        raise _bad("맨 바깥이 <svg>가 아니에요.")
    removed: list[str] = []
    clean = _copy(root, removed)
    viewbox = root.get("viewBox") or f"0 0 {WIDTH} {HEIGHT}"
    for attr in ("x", "y"):
        clean.attrib.pop(attr, None)
    clean.set("viewBox", viewbox if _safe_value(viewbox) else f"0 0 {WIDTH} {HEIGHT}")
    clean.set("width", str(WIDTH))
    clean.set("height", str(HEIGHT))
    clean.set("preserveAspectRatio", "xMidYMid slice")
    shapes = sum(1 for el in clean.iter() if _local(el.tag) in SHAPES)
    if shapes < MIN_SHAPES:
        raise _bad(f"그린 도형이 {shapes}개뿐이에요.")
    ET.register_namespace("", NS)
    return ET.tostring(clean, encoding="unicode"), sorted(set(removed))
