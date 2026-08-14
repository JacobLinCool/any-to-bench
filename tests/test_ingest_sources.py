"""Source preparation: PDFs and photos become ordered page PNGs."""

import pytest
from PIL import Image

from any_to_bench.ingest.sources import prepare_sources


@pytest.fixture
def sample_pdf(tmp_path):
    """A 2-page PDF generated with Pillow."""
    pages = [Image.new("RGB", (400, 560), color) for color in ("white", "lightgray")]
    path = tmp_path / "exam.pdf"
    pages[0].save(path, format="PDF", save_all=True, append_images=pages[1:])
    return path


@pytest.fixture
def sample_photo(tmp_path):
    path = tmp_path / "key.jpg"
    Image.new("RGB", (3000, 2000), "beige").save(path, format="JPEG")
    return path


def test_pdf_renders_to_pages(sample_pdf, tmp_path):
    root = tmp_path / "bundle"
    pages, sources = prepare_sources([sample_pdf], root)
    assert [p.index for p in pages] == [0, 1]
    assert [p.origin_page for p in pages] == [0, 1]
    for page in pages:
        assert page.png_path.exists()
        assert page.png_path.parent == root / "assets" / "pages"
        with Image.open(page.png_path) as image:
            assert image.width > 400  # rendered above source pixel size (~200 dpi)
    assert len(sources) == 1
    assert len(sources[0].sha256) == 64


def test_photo_is_normalized(sample_photo, tmp_path):
    root = tmp_path / "bundle"
    pages, _ = prepare_sources([sample_photo], root)
    assert len(pages) == 1
    with Image.open(pages[0].png_path) as image:
        assert max(image.size) <= 2048
        assert image.format == "PNG"


def test_mixed_inputs_keep_global_order(sample_pdf, sample_photo, tmp_path):
    pages, sources = prepare_sources([sample_pdf, sample_photo], tmp_path / "bundle")
    assert [p.index for p in pages] == [0, 1, 2]
    assert pages[2].origin_file.endswith("key.jpg")
    assert len(sources) == 2


def test_unsupported_input_rejected(tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("hello")
    with pytest.raises(ValueError, match="unsupported input type"):
        prepare_sources([bad], tmp_path / "bundle")
