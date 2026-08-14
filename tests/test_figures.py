"""Figure cropping: geometry, degenerate-bbox fallback, full-page mode."""

from PIL import Image

from any_to_bench.ingest.figures import FigureResolver
from any_to_bench.ingest.sources import SourcePage
from any_to_bench.schemas.extraction import FigureRef
from tests.conftest import make_png


def _setup(tmp_path, size=(200, 100)):
    root = tmp_path / "bundle"
    page_path = root / "assets" / "pages" / "p0001.png"
    make_png(page_path, size=size, color="white")
    pages = [SourcePage(index=0, origin_file="x.pdf", origin_page=0, png_path=page_path)]
    return root, pages


def test_crop_geometry(tmp_path):
    root, pages = _setup(tmp_path)
    resolver = FigureResolver(root, pages)
    block = resolver.resolve(
        FigureRef(page_index=0, bbox=(0.25, 0.25, 0.75, 0.75), alt="a box", caption=None),
        owner="q1",
    )
    assert block.type == "image"
    path = root / block.asset
    assert path.exists()
    with Image.open(path) as image:
        # Half the page plus 2% padding on each side.
        assert 100 <= image.width <= 110
        assert 50 <= image.height <= 56
    assert resolver.warnings == []


def test_degenerate_small_bbox_falls_back_to_full_page(tmp_path):
    root, pages = _setup(tmp_path)
    resolver = FigureResolver(root, pages)
    block = resolver.resolve(
        FigureRef(page_index=0, bbox=(0.5, 0.5, 0.501, 0.501), alt="dot", caption=None),
        owner="q1",
    )
    assert block.asset == "assets/pages/p0001.png"
    assert any("degenerate" in w for w in resolver.warnings)


def test_degenerate_huge_bbox_falls_back_to_full_page(tmp_path):
    root, pages = _setup(tmp_path)
    resolver = FigureResolver(root, pages)
    block = resolver.resolve(
        FigureRef(page_index=0, bbox=(0.0, 0.0, 1.0, 1.0), alt="everything", caption=None),
        owner="q1",
    )
    assert block.asset == "assets/pages/p0001.png"


def test_full_page_mode_never_crops(tmp_path):
    root, pages = _setup(tmp_path)
    resolver = FigureResolver(root, pages, full_page_figures=True)
    block = resolver.resolve(
        FigureRef(page_index=0, bbox=(0.25, 0.25, 0.75, 0.75), alt="a box", caption=None),
        owner="q1",
    )
    assert block.asset == "assets/pages/p0001.png"
    assert resolver.warnings == []


def test_unknown_page_becomes_text_block(tmp_path):
    root, pages = _setup(tmp_path)
    resolver = FigureResolver(root, pages)
    block = resolver.resolve(
        FigureRef(page_index=99, bbox=(0.1, 0.1, 0.5, 0.5), alt="ghost", caption=None),
        owner="q1",
    )
    assert block.type == "text"
    assert "ghost" in block.markdown
    assert any("unknown page" in w for w in resolver.warnings)


def test_swapped_bbox_coordinates_are_normalized(tmp_path):
    root, pages = _setup(tmp_path)
    resolver = FigureResolver(root, pages)
    block = resolver.resolve(
        FigureRef(page_index=0, bbox=(0.75, 0.75, 0.25, 0.25), alt="swapped", caption=None),
        owner="q1",
    )
    assert block.type == "image"
    assert (root / block.asset).exists()
