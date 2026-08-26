"""Превращает статью Telegram (Rich Message) в плоский текст."""
from typing import Any

NESTED_BLOCKS = {"block_quotation", "expandable_block_quotation"}
MEDIA_BLOCKS = {
    "photo", "video", "animation", "audio", "document",
    "voice_note", "collage", "slideshow", "map",
}


def inline_text(node: Any) -> str:
    """Собирает текст из вложенных rich-text узлов (bold, italic, link и т.д.)."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(inline_text(n) for n in node)
    if isinstance(node, dict):
        return inline_text(node.get("text"))
    return str(node)


def _walk(blocks: Any, out: list[str]) -> None:
    for b in blocks or []:
        if not isinstance(b, dict):
            continue
        t = b.get("type")

        if t == "divider":
            out.append("")

        elif t == "list":
            for item in b.get("items", []):
                label = str(item.get("label") or "•")
                inner: list[str] = []
                _walk(item.get("blocks", []), inner)
                inner = [x for x in inner if x.strip()]
                if inner:
                    out.append(f"{label} {inner[0]}")
                    out.extend(inner[1:])
                else:
                    out.append(label)

        elif t == "table":
            for row in b.get("cells", []):
                cells = [inline_text(c.get("text")) for c in row if isinstance(c, dict)]
                if any(c.strip() for c in cells):
                    out.append(" | ".join(c.strip() for c in cells))
            cap = inline_text(b.get("caption"))
            if cap:
                out.append(cap)

        elif t == "details":
            summary = inline_text(b.get("summary"))
            if summary:
                out.append(summary)
            _walk(b.get("blocks", []), out)

        elif t in NESTED_BLOCKS:
            _walk(b.get("blocks"), out)

        elif t in MEDIA_BLOCKS:
            cap = inline_text(b.get("caption"))
            if cap:
                out.append(cap)

        else:  # paragraph, section_heading, footer, preformatted, quote...
            txt = inline_text(b.get("text"))
            if txt:
                out.append(txt)


def rich_to_text(rich: Any) -> str:
    data = rich.model_dump(exclude_none=True) if hasattr(rich, "model_dump") else rich
    if not isinstance(data, dict):
        return ""
    out: list[str] = []
    _walk(data.get("blocks", []), out)
    return "\n".join(line.strip() for line in out).strip()


def extract_text(message: Any) -> str:
    """Достаёт текст из обычного сообщения, подписи или статьи."""
    parts: list[str] = []
    rich = getattr(message, "rich_message", None)
    if rich is not None:
        parts.append(rich_to_text(rich))
    if getattr(message, "text", None):
        parts.append(message.text)
    elif getattr(message, "caption", None):
        parts.append(message.caption)
    return "\n".join(p for p in parts if p).strip()
