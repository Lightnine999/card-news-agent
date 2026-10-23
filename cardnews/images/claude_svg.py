"""agy로 그림을 못 만들 때 Claude CLI로 설명용 배경 그림을 SVG로 그리기 (DECISIONS D16).

Claude CLI는 사진 같은 비트맵 그림을 직접 만들지 못해서, 도형·그라디언트로 된 SVG 코드를 받아요.
- agy에 보내는 것과 같은 그림체(STYLE)·글자 여백 규칙을 써서 카드끼리 색감을 맞춰요.
- 조사 세션과 섞지 않으려고 새 세션으로 부르고 저장하지 않아요(--no-session-persistence).
- 받은 SVG는 svg.sanitize로 글자·스크립트·외부 주소를 지운 뒤에만 저장해요.
"""

from pydantic import BaseModel

from cardnews import config
from cardnews.engines import claude_cli
from cardnews.engines import claude_schema as S
from cardnews.engines.base import RunContext
from cardnews.errors import AppError
from cardnews.images import files, svg
from cardnews.images.agy import STYLE, TEXT_AREA
from cardnews.util import now_iso

BLOCKED = ("Bash", "Edit", "Write", "NotebookEdit", "Task", "WebSearch", "WebFetch")


class SvgImageOutput(BaseModel):
    svg: str


def tool_name() -> str:
    return f"Claude CLI ({config.CLAUDE_MODEL}, SVG)"


def svg_prompt(plan: dict, index: int, total: int) -> str:
    area = TEXT_AREA.get(plan["textArea"], "위쪽")
    return f"""설명용 카드뉴스 배경 그림을 SVG 코드로 그려 주세요 (카드 {index}/{total}).
- 결과의 svg 필드에 <svg>…</svg> 코드 하나만 넣어요.
- viewBox="0 0 1080 1350" (세로 4:5).
- 장면: {plan["prompt"]}
- {STYLE}
- 글자를 올릴 자리: 화면 {area} 약 40%는 비워 두고 단색이나 부드러운 그라디언트만 두세요.
- 도형(rect·circle·ellipse·path·polygon·line)과 그라디언트만 써요. <text>, 글자·숫자 모양, <image>, <script>, 외부 주소는 쓰지 마세요.
- 실제 제품 화면, 실존 인물, 보도 사진처럼 보이지 않게 단순한 설명용 일러스트로 그려 주세요."""


def _args(prompt: str) -> list[str]:
    return [config.claude_bin(), "-p", prompt,
            "--model", config.CLAUDE_MODEL, "--effort", config.CLAUDE_EFFORT,
            "--output-format", "stream-json", "--verbose",
            "--json-schema", S.schema_json(SvgImageOutput),
            "--max-turns", str(claude_cli.LIMITS["svg"][0]),
            "--append-system-prompt", "결과는 지정된 JSON 형식으로만 돌려줘요. 파일을 쓰거나 명령을 실행하지 않아요.",
            "--strict-mcp-config", "--setting-sources", "project", "--no-session-persistence",
            "--disallowedTools", *BLOCKED]


def generate(ctx: RunContext, plan: dict, index: int, total: int, dest_stem, tool: str) -> dict:
    prompt = svg_prompt(plan, index, total)
    result = claude_cli.run_claude(ctx, _args(prompt), "svg")
    out = S.parse(SvgImageOutput, claude_cli.structured(result))
    clean, removed = svg.sanitize(out.svg)
    dest = files.with_extension(dest_stem, "svg")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(clean, encoding="utf-8")
    kind, width, height = files.image_info(dest) or (None, None, None)
    if kind != "svg" or (width, height) != (svg.WIDTH, svg.HEIGHT):
        raise AppError("IMAGE_FAILED", "저장한 SVG 파일을 다시 읽지 못했어요.")
    return {"origin": "generated-svg", "tool": tool, "conversationId": None, "prompt": prompt,
            "createdAt": now_iso(), "originalFormat": "svg", "originalSize": [width, height],
            "sha256": files.sha256(dest), "removedFromSvg": removed,
            "disclosure": "생성 이미지 (Claude CLI가 도형으로 그린 SVG)", "dest": dest}
