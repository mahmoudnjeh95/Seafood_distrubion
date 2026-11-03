"""Uploaded pictures are saved again as WebP (D-123); a transparent background stays transparent (D-282)."""

import io

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.core.images import reencoded_photo


def test_a_palette_png_with_a_transparent_colour_keeps_it_transparent():
    """Seen on a logo: the transparent colour of a palette PNG became black, so the receipt printed a black box."""
    image = Image.new("P", (20, 20), 0)
    image.putpalette([0, 0, 0, 200, 30, 30])
    image.paste(1, (5, 5, 15, 15))
    buffer = io.BytesIO()
    image.save(buffer, "PNG", transparency=0)

    saved = reencoded_photo(SimpleUploadedFile("logo.png", buffer.getvalue(), content_type="image/png"))

    with Image.open(io.BytesIO(saved.read())) as result:
        assert result.mode == "RGBA"
        alpha = result.getchannel("A")
        assert alpha.getpixel((0, 0)) == 0  # the corner stays see-through
        assert alpha.getpixel((10, 10)) == 255
