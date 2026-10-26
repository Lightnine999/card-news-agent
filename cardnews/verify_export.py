"""내보낸 ZIP을 다시 열어 누락·크기·글자 잘림·출처·날짜를 확인해요.

결과는 통과(pass) / 실패(fail) / 사용자 확인 필요(needs_check) 셋 중 하나예요.
확인하지 못한 것은 통과로 적지 않고, 무엇을 어디서 보면 되는지(whatToCheck)를 남겨요.
"""

import hashlib
import io
import re
import zipfile
from datetime import date
from pathlib import Path

from PIL import Image

from cardnews import config, sources, support
from cardnews.render.layout import CARD_SIZE
from cardnews.util import now

FULL_DATE = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월(?:\s*(\d{1,2})\s*일)?")
MONTH_DAY = re.compile(r"(?<!\d)(\d{1,2})\s*월\s*(\d{1,2})\s*일")
ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
SEP_DATE = re.compile(r"(?<![\d.])(\d{4}|'\d{2})[./-](\d{1,2})[./-](\d{1,2})(?![\d.])")  # 2026.10.24, '26.10.24
SLASH_MD = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?![\d/])")  # 10/24
RANGE_MD = re.compile(r"(?<!\d)(\d{1,2})\s*월\s*(\d{1,2})\s*일?\s*[~∼–-]\s*(\d{1,2})\s*일")  # 10월 23~25일
# 날짜를 가리키지만 정확한 날을 알 수 없는 표현: 통과로 볼 수 없어서 사용자 확인으로 돌려요
RELATIVE = re.compile(r"\d{1,2}\s*월\s*(?:초|중순|말|(?:첫|둘|셋|넷|다섯)째\s*주)|(?:다음|지난|이번)\s*(?:달|주)|올해|내년|작년|\d\s*분기|상반기|하반기|연말|연초")
STATUS_LABEL = {"pass": "통과", "fail": "실패", "needs_check": "사용자 확인 필요"}


def _item(check: str, target: str, status: str, detail: str, what: str | None = None) -> dict:
    return {"check": check, "target": target, "status": status, "detail": detail, "whatToCheck": what}


def _card_file(order: int) -> str:
    return f"cards/card_{order:02d}.png"


def _texts(plan: dict, card: dict) -> str:
    layout = card.get("layout") or {}
    keys = ("title", "keyLine") if plan["role"] == "cover" else ("title", "keyLine", "body")
    return " ".join(str(layout.get(k) if layout.get(k) is not None else plan.get(k) or "") for k in keys)


# --- 누락·크기·잘림 ------------------------------------------------------------------


def _files(zf: zipfile.ZipFile, plans: list[dict]) -> list[dict]:
    names = set(zf.namelist())
    expected = [_card_file(p["order"]) for p in plans] + ["sources.md", "image-credits.md"]
    missing = [n for n in expected if n not in names]
    if missing:
        return [_item("누락", "전체", "fail", f"ZIP에 없는 파일: {', '.join(missing)}",
                      "검수 화면에서 해당 카드를 다시 만들고 다시 승인해 주세요.")]
    return [_item("누락", "전체", "pass", f"카드 PNG {len(plans)}장, sources.md, image-credits.md가 모두 있어요.")]


def _png(zf: zipfile.ZipFile, name: str) -> tuple[bytes, tuple[int, int] | None]:
    data = zf.read(name)
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
        with Image.open(io.BytesIO(data)) as img:
            return data, img.size
    except Exception:
        return data, None


def _card_files(zf, project_dir: Path, plan: dict, card: dict) -> list[dict]:
    name, target = _card_file(plan["order"]), f"카드 {plan['order']}"
    if name not in zf.namelist():
        return []  # 누락에서 이미 실패로 적었어요
    data, size = _png(zf, name)
    items = []
    if size is None:
        items.append(_item("크기", target, "fail", "ZIP 안 PNG를 열지 못했어요.", "카드를 다시 만들어 주세요."))
    elif list(size) != CARD_SIZE:
        items.append(_item("크기", target, "fail", f"{size[0]}×{size[1]}이에요(기준 1080×1350).", "카드를 다시 만들어 주세요."))
    else:
        items.append(_item("크기", target, "pass", "1080×1350 PNG예요."))
    layout = (card.get("checks") or {}).get("layout") or {}
    rendered = project_dir / card["png"] if card.get("png") else None
    same = rendered is not None and rendered.is_file() and \
        hashlib.sha256(rendered.read_bytes()).hexdigest() == hashlib.sha256(data).hexdigest()
    if layout.get("overflow") is True:
        items.append(_item("글자 잘림", target, "fail", "렌더링 때 글자가 정해진 자리를 넘쳤어요.",
                           "문구를 줄이거나 글자 크기를 줄여 다시 승인해 주세요."))
    elif layout.get("overflow") is False and same:
        items.append(_item("글자 잘림", target, "pass",
                           "렌더링 때 넘침이 없었고, ZIP 안 PNG가 그 렌더링 파일과 같아요."))
    else:
        items.append(_item("글자 잘림", target, "needs_check",
                           "ZIP 안 PNG가 점검한 렌더링 파일과 같은지 확인하지 못했어요.",
                           f"{name}을 열어 글자가 잘리지 않았는지 직접 봐 주세요."))
    return items


# --- 출처 ----------------------------------------------------------------------------


def _sources(plan: dict, index: dict, sources_text: str, allowed: set[str]) -> dict:
    target = f"카드 {plan['order']}"
    urls = plan.get("sourceUrls", [])
    if not urls:
        return _item("출처", target, "needs_check", "이 카드에는 근거 출처가 없어요.",
                     "표지·요약 카드라면 다른 카드의 출처로 충분한지, 아니라면 문구의 근거가 무엇인지 확인해 주세요.")
    unknown = [u for u in urls if sources.normalize(u) not in allowed]
    listed = set(re.findall(r"\]\((https?://[^)\s]+)\)|근거: (https?://\S+)", sources_text))
    listed = {u for pair in listed for u in pair if u}
    unlisted = [u for u in urls if u not in listed]
    if unknown or unlisted:
        return _item("출처", target, "fail",
                     f"조사 기록에 없는 주소 {len(unknown)}개, sources.md에 빠진 주소 {len(unlisted)}개예요.",
                     "카드 문구를 조사 기록의 출처로 다시 고쳐 주세요.")
    unopened = [u for u in urls if not index[sources.normalize(u)]["opened"]]
    if unopened:
        return _item("출처", target, "needs_check", f"엔진이 열어 보지 않은 출처가 {len(unopened)}개 있어요: {', '.join(unopened)}",
                     "링크를 직접 열어 카드 문구와 내용이 맞는지 확인해 주세요.")
    return _item("출처", target, "pass", f"근거 {len(urls)}개 모두 조사 기록에 있고 엔진이 실제로 열어 봤어요.")


# --- 날짜 ----------------------------------------------------------------------------


def _evidence_dates(data: dict) -> tuple[set, set, set]:
    texts = []
    for cand in (data.get("research") or {}).get("candidates", []):
        texts += [cand.get("title", ""), cand.get("summary", ""), cand.get("publishedAt") or "", cand.get("eventDate") or ""]
    for note in data.get("researchNotes") or []:
        texts += [f["text"] for f in note.get("facts", [])] + list(note.get("limits", []))
    full, ym, md = set(), set(), set()
    blob = "\n".join(texts)
    for y, m, d in ISO_DATE.findall(blob):
        full.add((int(y), int(m), int(d))); ym.add((int(y), int(m))); md.add((int(m), int(d)))
    for y, m, d in SEP_DATE.findall(blob):
        full.add((_year(y), int(m), int(d))); ym.add((_year(y), int(m))); md.add((int(m), int(d)))
    for y, m, d in FULL_DATE.findall(blob):
        ym.add((int(y), int(m)))
        if d:
            full.add((int(y), int(m), int(d))); md.add((int(m), int(d)))
    for m, d in MONTH_DAY.findall(blob):
        md.add((int(m), int(d)))
    return full, ym, md


def _year(raw: str) -> int:
    return 2000 + int(raw[1:]) if raw.startswith("'") else int(raw)


def _text_dates(text: str) -> list[tuple[str, tuple]]:
    """카드 문구의 날짜: (원문, (연, 월, 일) | (연, 월) | (월, 일, "md"))."""
    found, rest = [], text
    for match in RANGE_MD.finditer(rest):
        m, d1, d2 = map(int, match.groups())
        found += [(match.group(0), (m, d1, "md")), (match.group(0), (m, d2, "md"))]
    rest = RANGE_MD.sub(" ", rest)
    for match in SEP_DATE.finditer(rest):
        y, m, d = match.groups()
        found.append((match.group(0), (_year(y), int(m), int(d))))
    rest = SEP_DATE.sub(" ", rest)
    for match in FULL_DATE.finditer(rest):
        y, m, d = match.groups()
        found.append((match.group(0), (int(y), int(m), int(d)) if d else (int(y), int(m))))
    rest = FULL_DATE.sub(" ", rest)
    found += [(m.group(0), (int(m.group(1)), int(m.group(2)), "md")) for m in MONTH_DAY.finditer(rest)]
    rest = MONTH_DAY.sub(" ", rest)
    found += [(m.group(0), (int(m.group(1)), int(m.group(2)), "md")) for m in SLASH_MD.finditer(rest)
              if 1 <= int(m.group(1)) <= 12 and 1 <= int(m.group(2)) <= 31]
    return found


def _known(parts: tuple, evidence: tuple, years: set[int]) -> bool:
    """연도 없는 날짜는 조사 기간 연도의 같은 날이 기록에 있을 때만 확인된 것으로 봐요."""
    full, ym, _ = evidence
    if parts[-1] == "md":
        return any((y, parts[0], parts[1]) in full for y in years)
    return parts in full if len(parts) == 3 else parts in ym


def _in_period(published: str, period: dict) -> bool:
    day = date.fromisoformat(published)
    return date.fromisoformat(period["from"][:10]) <= day <= date.fromisoformat(period["to"][:10])


def _dates(plan: dict, card: dict, index: dict, data: dict, evidence: tuple) -> dict:
    target = f"카드 {plan['order']}"
    research = data["research"]
    period = research["period"]
    years = {int(period["from"][:4]), int(period["to"][:4])}
    fails, checks, confirmed = [], [], []
    official = {n.get("candidateId"): n.get("officialDate") for n in data.get("researchNotes") or []}
    seen = set()
    for url in plan.get("sourceUrls", []):
        info = index.get(sources.normalize(url))
        cid = (info or {}).get("candidateId")
        if cid and cid not in seen:  # 기사 게시일과 따로, 1차 자료로 확인한 공식 발표일이 있는지 봐요
            seen.add(cid)
            if not official.get(cid):
                checks.append(f"공식 발표 날짜를 1차 자료로 확인하지 못했어요(기사 게시일 {info['publishedAt'] or '미확인'}만 있어요): {info.get('candidate') or url}")
            elif not _in_period(official[cid], period):
                fails.append(f"공식 발표일 {official[cid]}이 조사 기간 밖이에요: {info.get('candidate') or url}")
            else:
                confirmed.append(f"공식 발표일 {official[cid]}")
        if not info:
            checks.append(f"조사 기록에 없는 근거라 게시일을 확인하지 못했어요: {url}")
        elif not info["publishedAt"]:
            checks.append(f"게시일 미확인 출처: {url}")
        elif not _in_period(info["publishedAt"], period):
            fails.append(f"조사 기간 밖 게시일 {info['publishedAt']}: {url}")
        else:
            confirmed.append(f"근거 게시일 {info['publishedAt']}")
    text = _texts(plan, card)
    for raw, parts in _text_dates(text):
        if _known(parts, evidence, years):
            confirmed.append(f"문구의 '{raw}'")
        else:
            checks.append(f"카드 문구의 날짜 '{raw}'를 조사 기록에서 찾지 못했어요")
    for match in RELATIVE.finditer(text):
        checks.append(f"정확한 날을 알 수 없는 날짜 표현 '{match.group(0)}'이 있어요")
    if "최신" in text and not (research.get("requestedAt") and plan.get("sourceUrls")):
        checks.append("'최신'을 뒷받침할 조사 기준일·게시일이 없어요")
    if fails:
        return _item("날짜", target, "fail", "; ".join(fails), "기간 안의 출처로 바꾸거나 문구에서 '최신' 표현을 빼 주세요.")
    if checks:
        return _item("날짜", target, "needs_check", "; ".join(checks), "원문을 열어 날짜를 직접 확인해 주세요.")
    if not confirmed:  # 비교할 게 하나도 없으면 확인한 것이 아니에요
        return _item("날짜", target, "needs_check", "이 카드에는 확인할 근거 게시일도, 문구 속 날짜도 없어요.",
                     "카드가 시점을 말하지 않아도 괜찮은지 확인해 주세요.")
    return _item("날짜", target, "pass", "확인한 것: " + ", ".join(confirmed) + " (조사 기간·조사 기록과 맞아요).")


# --- 지원사업·공모전 (SUPPORT_PRD "내보낸 파일 검사") -------------------------------------

DDAY = re.compile(r"D-\d+|오늘 마감|마감 지남")


def _rendered(plan: dict, card: dict) -> str:
    """PNG에 실제로 올린 글자. 렌더링 기록이 없으면 지금 문구로 봐요."""
    texts = (card.get("render") or {}).get("texts") or {}
    layout = card.get("layout") or {}
    return " ".join(str(texts.get(k) or layout.get(k) or plan.get(k) or "") for k in ("title", "keyLine", "body"))


def _norm(urls) -> set[str]:
    return {sources.normalize(u) for u in urls}


def _official_seen(notice: dict, opened: set[str], official: set[str]) -> bool:
    """공식 공고문 주소가 조사에 나온 공식 출처이고, 엔진이 실제로 열어 봤는지."""
    url = notice.get("officialUrl")
    return bool(url) and sources.normalize(url) in _norm(official) and sources.normalize(url) in _norm(opened)


def support_deadline(plan: dict, opened: set[str], today, official: set[str]) -> dict:
    target, notice = f"카드 {plan['order']}", plan["notice"]
    seen = _official_seen(notice, opened, official)
    if notice["dateStatus"] == "rolling":
        if seen:
            return _item("마감일", target, "pass", "상시 모집·소진 시 마감이고, 엔진이 공식 공고문을 열어 봤어요.")
        return _item("마감일", target, "needs_check", "상시 모집이라고 적었지만 공식 공고문을 엔진이 열어 확인한 기록이 없어요.",
                     "공식 공고문을 열어 아직 모집 중인지 확인해 주세요.")
    reason = support.exclusion_reason(notice, today)
    if reason:
        return _item("마감일", target, "fail", reason, "이 공고 카드를 빼거나 공고를 다시 확인해 주세요.")
    if not seen:
        return _item("마감일", target, "needs_check",
                     f"마감일({notice['deadline']})을 적었지만 공식 공고문(조사에 나온 공식 주소)을 엔진이 열어 확인한 기록이 없어요.",
                     "sources.md의 공식 링크를 열어 마감일을 확인해 주세요.")
    return _item("마감일", target, "pass", f"마감일({notice['deadline']})을 공식 공고문(엔진이 열어 봄)에서 확인했고 오늘부터 6개월 안이에요.")


def support_dday(plan: dict, card: dict, today) -> dict:
    target, notice = f"카드 {plan['order']}", plan["notice"]
    base = (card.get("render") or {}).get("ddayBase")
    found = DDAY.findall(_rendered(plan, card))
    if not base or not found:
        return _item("D-day", target, "fail", "카드에 앱이 계산한 D-day가 없어요.", "카드를 다시 렌더링해 주세요.")
    expected = support.dday_text(notice["deadline"], date.fromisoformat(base))
    if found != [expected]:
        return _item("D-day", target, "fail", f"카드의 D-day({', '.join(found)})가 앱 계산({expected}, {base} 기준)과 달라요.",
                     "카드를 다시 렌더링해 주세요.")
    if base != today.isoformat():
        return _item("D-day", target, "needs_check", f"{base} 기준 {expected}로 만들었어요. 오늘({today.isoformat()}) 기준으로 다시 계산해야 해요.",
                     "카드를 다시 렌더링하거나 기준일이 보이는지 확인해 주세요.")
    return _item("D-day", target, "pass", f"{expected}: 앱이 {base} 기준으로 계산한 값과 같아요.")


AMOUNT = re.compile(r"\d[\d,.]*\s*(?:억|천만|백만|만|천)?\s*(?:원|달러)")


def _squash(text: str) -> str:
    return re.sub(r"[\s,]", "", text)


def support_amount(plan: dict, card: dict, opened: set[str], official: set[str], notes: list[dict]) -> dict:
    """금액이 조사 기록 중 공식 주소를 근거로 한 사실(facts)에 있는지 봐요. 엔진이 낸 금액 문구끼리만 비교하지 않아요."""
    target, notice = f"카드 {plan['order']}", plan["notice"]
    if not notice.get("amountText"):
        return _item("금액", target, "needs_check", "공식 공고문에서 금액을 확인하지 못했어요(카드에 '금액 확인 필요').",
                     "공고문을 열어 지원 금액을 확인해 주세요.")
    if notice["amountText"] not in _rendered(plan, card):
        return _item("금액", target, "needs_check", "카드의 금액 문구가 조사 기록과 달라요(고친 문구일 수 있어요).",
                     "카드 금액과 공고문 금액을 비교해 주세요.")
    allowed = _norm(official) & _norm(opened)
    facts = [f["text"] for n in notes if n.get("candidateId") == plan.get("candidateId")
             for f in n.get("facts", []) if _norm(f.get("sourceUrls", [])) & allowed]
    tokens = [_squash(t) for t in AMOUNT.findall(notice["amountText"])]
    blob = _squash(" ".join(facts))
    if not tokens or not all(t in blob for t in tokens):
        return _item("금액", target, "needs_check",
                     f"금액 문구({notice['amountText']})를 엔진이 연 공식 공고문의 확인한 사실에서 찾지 못했어요.",
                     "공식 공고문에서 금액을 확인해 주세요.")
    return _item("금액", target, "pass", f"금액 문구({notice['amountText']})가 엔진이 연 공식 공고문의 확인한 사실에 있어요.")


def support_expected(plan: dict, card: dict, opened: set[str], today, official: set[str]) -> dict:
    target, notice = f"카드 {plan['order']}", plan["notice"]
    text = _rendered(plan, card)
    if DDAY.search(text):
        return _item("예정 공고", target, "fail", "아직 열리지 않은 공고에 D-day가 있어서 확정처럼 보여요.", "D-day를 빼 주세요.")
    if "예정(미확정)" not in text:
        return _item("예정 공고", target, "fail", "'예정(미확정)' 표시가 없어요.", "본문을 되돌리거나 표시를 넣어 주세요.")
    reason = support.exclusion_reason(notice, today)  # 내보내는 날 기준으로 열릴 달이 지났는지 다시 봐요
    if reason:
        return _item("예정 공고", target, "fail", reason, "이 공고 카드를 빼거나 공고가 나왔는지 다시 확인해 주세요.")
    if not _official_seen(notice, opened, official):
        return _item("예정 공고", target, "needs_check", f"근거({notice['basis']})가 있지만 엔진이 공식 근거 페이지를 열어 확인한 기록이 없어요.",
                     "근거 페이지를 열어 열릴 시기를 확인해 주세요.")
    return _item("예정 공고", target, "pass", f"'예정(미확정)' 표시가 있고, 엔진이 연 공식 페이지에 근거가 있어요: {notice['basis']}")


def support_other(plan: dict, card: dict) -> list[dict]:
    """표지·요약·상시 카드: 앱이 계산하지 않은 D-day가 섞이면 실패예요."""
    found = DDAY.findall(_rendered(plan, card))
    if not found:
        return []
    return [_item("D-day", f"카드 {plan['order']}", "fail", f"앱이 D-day를 넣지 않는 카드에 D-day({', '.join(found)})가 있어요.",
                  "이 카드 문구에서 D-day를 빼 주세요.")]


def _support_checks(plan: dict, card: dict, opened: set[str], today, official: set[str], notes: list[dict]) -> list[dict]:
    notice = plan.get("notice")
    if not notice:
        return support_other(plan, card)
    amount = support_amount(plan, card, opened, official, notes)
    if notice["dateStatus"] == "expected":
        return [support_expected(plan, card, opened, today, official), amount]
    if notice["dateStatus"] == "rolling":
        return [support_deadline(plan, opened, today, official), *support_other(plan, card), amount]
    return [support_deadline(plan, opened, today, official), support_dday(plan, card, today), amount]


# --- 모으기 --------------------------------------------------------------------------


def verify(project: dict, out_dir: Path, zip_path: Path) -> dict:
    data = project["data"]
    plans = data["storyboard"]["cards"]
    cards = {c["cardId"]: c for c in data["result"]["cards"]}
    project_dir = config.data_dir() / "projects" / project["id"]
    from cardnews.export import source_index  # 순환 import를 피하려고 여기서 불러요
    index = source_index(data)
    evidence = _evidence_dates(data)
    items = []
    with zipfile.ZipFile(zip_path) as zf:
        items += _files(zf, plans)
        sources_text = zf.read("sources.md").decode("utf-8") if "sources.md" in zf.namelist() else ""
        for plan in plans:
            card = cards[plan["id"]]
            items += _card_files(zf, project_dir, plan, card)
            items.append(_sources(plan, index, sources_text, set(index)))
            if (card.get("layout") or {}).get("textEdited"):
                items.append(_item("출처", f"카드 {plan['order']}", "needs_check",
                                   "스토리보드 뒤에 문구를 고쳤어요. 고친 문구가 원문과 맞는지는 확인하지 않았어요.",
                                   f"sources.md의 카드 {plan['order']} 근거 링크를 열어 고친 문구와 비교해 주세요."))
            if data.get("workflow") == "support":  # 게시일 대신 마감·D-day·금액·예정 근거를 봐요
                items += _support_checks(plan, card, set(data.get("openedUrls", [])), now().date(),
                                         support.official_urls(data["research"]["candidates"], data.get("researchNotes") or []),
                                         data.get("researchNotes") or [])
            else:
                items.append(_dates(plan, card, index, data, evidence))
    items.append(_item("출처", "전체", "needs_check",
                       "카드 문구가 원문 내용과 맞는지는 사람이 확인하지 않았어요. 앱은 근거 주소가 조사 기록에 있고 엔진이 열어 봤는지만 봐요.",
                       "카드마다 근거 링크를 열어 숫자·날짜·조건이 원문과 같은지 확인해 주세요."))
    items.append(_item("출처", "전체", "needs_check", "원문 링크가 지금도 열리는지는 확인하지 않았어요(인터넷에 다시 접속하지 않음).",
                       "sources.md의 링크를 몇 개 열어 보고, 바뀌거나 사라진 글이 없는지 확인해 주세요."))
    summary = {s: sum(1 for i in items if i["status"] == s) for s in ("pass", "fail", "needs_check")}
    return {"summary": summary, "items": items, "zip": zip_path.name}


def to_markdown(report: dict) -> str:
    s = report["summary"]
    lines = ["# 내보낸 파일 검사", "", f"- 대상: {report['zip']}",
             f"- 통과 {s['pass']} · 실패 {s['fail']} · 사용자 확인 필요 {s['needs_check']}",
             "- 확인하지 못한 항목은 통과로 적지 않았어요.", "",
             "| 항목 | 대상 | 결과 | 내용 | 확인할 것 |", "|---|---|---|---|---|"]
    for i in report["items"]:
        cells = [i["check"], i["target"], STATUS_LABEL[i["status"]], i["detail"], i["whatToCheck"] or ""]
        lines.append("| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
    return "\n".join(lines) + "\n"
