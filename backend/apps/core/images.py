"""Photos sent by people (product pictures, proof of a loss): checked, turned upright, shrunk, saved as WebP."""

import io

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile
from django.utils.translation import gettext as _
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_PHOTO_BYTES = 8 * 1024 * 1024
MAX_PHOTO_PIXELS = 50_000_000  # a 48-megapixel phone photo passes; anything larger is refused
PHOTO_SIDE = 1200  # stored photos fit in 1200 × 1200 px
PHOTO_FORMATS = {"JPEG", "PNG", "WEBP"}


def reencoded_photo(upload: UploadedFile[bytes], *, field: str = "photo", side: int = PHOTO_SIDE) -> ContentFile[bytes]:
    """The photo turned upright, shrunk and saved again as WebP; refused on `field` when it is not one.

    Saving again keeps only the pixels: the GPS position and other metadata of the phone, and anything
    hidden in the file, are dropped. It also keeps the server's disk small.
    """
    if upload.size is not None and upload.size > MAX_PHOTO_BYTES:
        raise ValidationError({field: _("La photo dépasse 8 Mo.")})
    try:
        with Image.open(upload) as image:
            if image.format not in PHOTO_FORMATS:
                raise ValidationError({field: _("Format accepté : JPEG, PNG ou WebP.")})
            if image.width * image.height > MAX_PHOTO_PIXELS:
                raise ValidationError({field: _("La photo est trop grande.")})
            upright = ImageOps.exif_transpose(image)
            # A palette PNG keeps its transparent colour in `info`: without RGBA it turns black (seen on a logo, D-282).
            see_through = "A" in upright.getbands() or "transparency" in upright.info
            upright = upright.convert("RGBA" if see_through else "RGB")
            upright.thumbnail((side, side))
            buffer = io.BytesIO()
            upright.save(buffer, format="WEBP", quality=82, method=4)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValidationError({field: _("Ce fichier n'est pas une image lisible.")}) from None
    return ContentFile(buffer.getvalue())
