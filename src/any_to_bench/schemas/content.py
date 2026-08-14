"""Rich content blocks used in question prompts, options, and instructions."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class TextBlock(BaseModel):
    """Markdown text. Inline math as $...$, display math as $$...$$."""

    type: Literal["text"] = "text"
    markdown: str


class ImageBlock(BaseModel):
    """An image stored in the bundle's assets directory."""

    type: Literal["image"] = "image"
    asset: str = Field(description="Path relative to the bundle root, e.g. 'assets/q03-fig1.png'")
    alt: str = Field(description="Model-written description; also used as a text fallback")
    caption: str | None = None


class TableBlock(BaseModel):
    """A table; cell contents are Markdown."""

    type: Literal["table"] = "table"
    header: list[str] | None = None
    rows: list[list[str]]
    caption: str | None = None


ContentBlock = Annotated[TextBlock | ImageBlock | TableBlock, Field(discriminator="type")]


def content_to_markdown(blocks: list[ContentBlock]) -> str:
    """Render content blocks to Markdown (images become '[Figure: alt]' markers)."""
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, TextBlock):
            parts.append(block.markdown)
        elif isinstance(block, ImageBlock):
            marker = f"[Figure: {block.alt}]"
            if block.caption:
                marker += f" ({block.caption})"
            parts.append(marker)
        elif isinstance(block, TableBlock):
            parts.append(table_to_markdown(block))
    return "\n\n".join(p for p in parts if p)


def table_to_markdown(table: TableBlock) -> str:
    width = max(
        [len(r) for r in table.rows] + ([len(table.header)] if table.header else [0]),
        default=0,
    )
    if width == 0:
        return ""
    header = table.header or [""] * width
    lines = [
        "| " + " | ".join(header + [""] * (width - len(header))) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    for row in table.rows:
        lines.append("| " + " | ".join(row + [""] * (width - len(row))) + " |")
    if table.caption:
        lines.append(f"\n*{table.caption}*")
    return "\n".join(lines)
