"""Normalize input materials into an ordered list of rendered page images.

PDFs are rasterized per page with pypdfium2 (~200 DPI); photos are normalized
with Pillow (EXIF rotation, bounded size) and re-encoded as PNG. Every model
call downstream sees these page images, so both providers get one input path
and figure bboxes can be cropped from the exact raster the model saw.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageOps

from any_to_bench.bundle import SourceFile
from any_to_bench.util import sha256_file

PDF_RENDER_SCALE = 2.8  # 72 dpi * 2.8 ≈ 200 dpi
MAX_IMAGE_SIDE = 2048

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}


@dataclass
class SourcePage:
    index: int  # global 0-based page index across all inputs
    origin_file: str
    origin_page: int  # 0-based page within the origin file (0 for photos)
    png_path: Path  # rendered page image inside the bundle's assets/pages/


def _save_pil(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    image.save(path, format="PNG")


def _render_pdf(path: Path, pages_dir: Path, start_index: int) -> list[SourcePage]:
    pages: list[SourcePage] = []
    pdf = pdfium.PdfDocument(path)
    try:
        for page_number in range(len(pdf)):
            page = pdf[page_number]
            bitmap = page.render(scale=PDF_RENDER_SCALE)
            image = bitmap.to_pil()
            index = start_index + len(pages)
            png_path = pages_dir / f"p{index + 1:04d}.png"
            _save_pil(image, png_path)
            pages.append(
                SourcePage(
                    index=index,
                    origin_file=str(path),
                    origin_page=page_number,
                    png_path=png_path,
                )
            )
    finally:
        pdf.close()
    return pages


def _render_image(path: Path, pages_dir: Path, index: int) -> SourcePage:
    with Image.open(path) as raw:
        image = ImageOps.exif_transpose(raw)
        assert image is not None
        if max(image.size) > MAX_IMAGE_SIDE:
            image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
        png_path = pages_dir / f"p{index + 1:04d}.png"
        _save_pil(image, png_path)
    return SourcePage(index=index, origin_file=str(path), origin_page=0, png_path=png_path)


def prepare_sources(
    inputs: list[Path], bundle_root: Path
) -> tuple[list[SourcePage], list[SourceFile]]:
    """Render all inputs into bundle_root/assets/pages/ and hash the originals."""
    pages_dir = bundle_root / "assets" / "pages"
    pages: list[SourcePage] = []
    sources: list[SourceFile] = []
    for path in inputs:
        path = Path(path)
        sources.append(SourceFile(path=str(path), sha256=sha256_file(path)))
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            pages.extend(_render_pdf(path, pages_dir, start_index=len(pages)))
        elif suffix in IMAGE_SUFFIXES:
            pages.append(_render_image(path, pages_dir, index=len(pages)))
        else:
            raise ValueError(f"unsupported input type: {path} (expected PDF or image)")
    if not pages:
        raise ValueError("no pages found in the given inputs")
    return pages, sources
