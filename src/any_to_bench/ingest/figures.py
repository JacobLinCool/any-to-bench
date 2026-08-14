"""Crop figures referenced by the extraction model out of rendered page images."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from any_to_bench.ingest.sources import SourcePage
from any_to_bench.schemas.content import ImageBlock, TextBlock
from any_to_bench.schemas.extraction import FigureRef

BBOX_PADDING = 0.02
MIN_BBOX_AREA = 0.005  # below this fraction of the page, the bbox is suspect
MAX_BBOX_AREA = 0.95  # above this, cropping adds nothing over the full page


class FigureResolver:
    """Turn FigureRefs into ImageBlocks backed by cropped (or full-page) assets."""

    def __init__(
        self,
        bundle_root: Path,
        pages: list[SourcePage],
        full_page_figures: bool = False,
    ) -> None:
        self.bundle_root = bundle_root
        self.pages_by_index = {p.index: p for p in pages}
        self.full_page_figures = full_page_figures
        self.warnings: list[str] = []
        self._counter = 0

    def resolve(self, ref: FigureRef, owner: str) -> ImageBlock | TextBlock:
        page = self.pages_by_index.get(ref.page_index)
        if page is None:
            self.warnings.append(
                f"{owner}: figure references unknown page {ref.page_index}; "
                "keeping description only"
            )
            return TextBlock(markdown=f"[Missing figure: {ref.alt}]")

        page_asset = str(page.png_path.relative_to(self.bundle_root))
        x0, y0, x1, y1 = ref.bbox
        x0, x1 = sorted((min(max(x0, 0.0), 1.0), min(max(x1, 0.0), 1.0)))
        y0, y1 = sorted((min(max(y0, 0.0), 1.0), min(max(y1, 0.0), 1.0)))
        area = (x1 - x0) * (y1 - y0)

        if self.full_page_figures or area < MIN_BBOX_AREA or area > MAX_BBOX_AREA:
            if not self.full_page_figures:
                self.warnings.append(
                    f"{owner}: figure bbox on page {ref.page_index} looks degenerate "
                    f"(area {area:.3f}); using the full page image"
                )
            return ImageBlock(asset=page_asset, alt=ref.alt, caption=ref.caption)

        self._counter += 1
        asset = f"assets/{owner}-fig{self._counter}.png"
        out_path = self.bundle_root / asset
        with Image.open(page.png_path) as image:
            width, height = image.size
            pad_x = BBOX_PADDING * (x1 - x0) * width
            pad_y = BBOX_PADDING * (y1 - y0) * height
            box = (
                max(0, int(x0 * width - pad_x)),
                max(0, int(y0 * height - pad_y)),
                min(width, int(x1 * width + pad_x)),
                min(height, int(y1 * height + pad_y)),
            )
            out_path.parent.mkdir(parents=True, exist_ok=True)
            image.crop(box).save(out_path, format="PNG")
        return ImageBlock(asset=asset, alt=ref.alt, caption=ref.caption)
