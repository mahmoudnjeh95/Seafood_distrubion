import datetime as dt
import io
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from apps.catalog import selectors, services
from apps.catalog.models import Product, ProductPrice
from apps.core.models import AuditLog
from apps.core.tests.factories import OrganizationFactory, UserFactory

from .factories import CategoryFactory, ProductFactory, ProductPriceFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def category():
    return CategoryFactory.create(name="Crustacés")


@pytest.fixture
def actor():
    return UserFactory.create()


def new_product(category, actor, **fields):
    values = {"reference": "CR-001", "name": "Crevette Royale", "category": category, "sale_price": "42"}
    values.update(fields)
    return services.create_product(organization=category.organization, actor=actor, **values)


def actions(product):
    return list(AuditLog.objects.filter(target_id=str(product.pk)).order_by("id").values_list("action", flat=True))


# ---- categories ----


def test_category_names_are_unique_per_organization_whatever_the_case(category, actor):
    with pytest.raises(ValidationError, match="déjà"):
        services.create_category(organization=category.organization, actor=actor, name=" crustacés ")

    other = services.create_category(organization=OrganizationFactory.create(), actor=actor, name="Crustacés")
    assert other.name == "Crustacés"


def test_renaming_a_category_is_audited(category, actor):
    services.rename_category(category=category, actor=actor, name="Crustacés frais")

    entry = AuditLog.objects.get(action="category.renamed")
    assert (entry.before, entry.after) == ({"name": "Crustacés"}, {"name": "Crustacés frais"})


# ---- products ----


def test_creating_a_product_stores_kg_and_a_first_price_from_now(category, actor):
    before = timezone.now()

    product = new_product(category, actor, min_stock="20")

    assert product.base_unit.code == "kg"
    assert product.min_stock == Decimal("20.000")
    price = product.prices.get()
    assert price.price == Decimal("42.000")
    assert price.valid_from >= before
    assert price.created_by == actor
    assert actions(product) == ["product.created"]


def test_references_are_unique_per_organization_whatever_the_case(category, actor):
    new_product(category, actor)

    with pytest.raises(ValidationError) as error:
        new_product(category, actor, reference="cr-001 ")
    assert "reference" in error.value.message_dict

    elsewhere = CategoryFactory.create()
    assert new_product(elsewhere, actor).reference == "CR-001"


@pytest.mark.parametrize(
    ("fields", "field"),
    [
        ({"name": "  "}, "name"),
        ({"min_stock": "-1"}, "min_stock"),
        ({"min_stock": "1.0005"}, "min_stock"),
        ({"storage_temp_min": Decimal("4"), "storage_temp_max": Decimal("0")}, "storage_temp_max"),
        ({"illustration": "whale"}, "illustration"),
        ({"sale_price": "0"}, "price"),
    ],
)
def test_invalid_products_are_refused_and_nothing_is_saved(category, actor, fields, field):
    with pytest.raises(ValidationError) as error:
        new_product(category, actor, **fields)

    assert field in error.value.message_dict
    assert not Product.objects.exists()


def test_a_category_of_another_organization_is_refused(actor):
    theirs = CategoryFactory.create()
    with pytest.raises(ValidationError) as error:
        services.create_product(
            organization=OrganizationFactory.create(),
            actor=actor,
            reference="X",
            name="X",
            category=theirs,
            sale_price="1",
        )
    assert "category" in error.value.message_dict


def test_an_open_temperature_range_is_allowed_for_frozen_goods(category, actor):
    product = new_product(category, actor, storage_temp_max=Decimal("-18"))

    assert (product.storage_temp_min, product.storage_temp_max) == (None, Decimal("-18"))


def test_an_update_audits_only_what_changed(category, actor):
    product = new_product(category, actor)

    services.update_product(product=product, actor=actor, name="Crevette royale", min_stock="15")

    entry = AuditLog.objects.get(action="product.updated")
    assert entry.before == {"name": "Crevette Royale", "min_stock": "0.000"}
    assert entry.after == {"name": "Crevette royale", "min_stock": "15.000"}


def test_archiving_and_restoring_are_audited_once(category, actor):
    product = new_product(category, actor)

    services.set_product_active(product=product, actor=actor, is_active=False)
    services.set_product_active(product=product, actor=actor, is_active=False)
    services.set_product_active(product=product, actor=actor, is_active=True)

    assert actions(product) == ["product.created", "product.archived", "product.restored"]


# ---- prices ----


def test_the_price_in_force_is_the_latest_at_or_before_the_moment():
    product = ProductFactory.create()
    morning = timezone.now() - dt.timedelta(hours=6)
    noon = morning + dt.timedelta(hours=3)
    ProductPriceFactory.create(product=product, price=Decimal("40"), valid_from=morning)
    ProductPriceFactory.create(product=product, price=Decimal("38.5"), valid_from=noon)

    def price(at):
        in_force = selectors.price_at(product, at)
        return in_force.price if in_force else None

    assert price(morning - dt.timedelta(seconds=1)) is None
    assert price(morning) == Decimal("40.000")
    assert price(noon - dt.timedelta(seconds=1)) == Decimal("40.000")
    assert price(noon) == Decimal("38.500")


def test_a_planned_price_is_not_in_force_before_its_time(category, actor):
    product = new_product(category, actor)
    tomorrow = timezone.now() + dt.timedelta(days=1)

    services.set_sale_price(product=product, actor=actor, price="45", valid_from=tomorrow)

    # current_price and current_price_from are annotations of the selector.
    now = selectors.product_of(product.organization, product.pk)
    assert getattr(now, "current_price") == Decimal("42.000")  # noqa: B009
    later = selectors.products_of(product.organization, at=tomorrow).get(pk=product.pk)
    assert getattr(later, "current_price") == Decimal("45.000")  # noqa: B009
    assert getattr(later, "current_price_from") == tomorrow  # noqa: B009


def test_a_new_price_never_starts_in_the_past(category, actor):
    product = new_product(category, actor)

    with pytest.raises(ValidationError) as error:
        services.set_sale_price(
            product=product, actor=actor, price="40", valid_from=timezone.now() - dt.timedelta(minutes=5)
        )
    assert "valid_from" in error.value.message_dict


def test_an_archived_product_gets_no_new_price(category, actor):
    product = new_product(category, actor)
    services.set_product_active(product=product, actor=actor, is_active=False)

    with pytest.raises(ValidationError, match="archivé"):
        services.set_sale_price(product=product, actor=actor, price="40")


def test_a_price_change_is_audited_with_the_previous_price(category, actor):
    product = new_product(category, actor)

    services.set_sale_price(product=product, actor=actor, price="39.9")

    entry = AuditLog.objects.get(action="product.price_set")
    assert entry.before == {"price": "42.000"}
    assert entry.after is not None
    assert entry.after["price"] == "39.900"


def test_prices_are_history_and_never_change():
    price = ProductPriceFactory.create()

    price.price = Decimal("1")
    with pytest.raises(TypeError):
        price.save()
    with pytest.raises(TypeError):
        price.delete()
    with pytest.raises(TypeError):
        ProductPrice.objects.filter(pk=price.pk).update(price=Decimal("1"))
    with pytest.raises(TypeError):
        ProductPrice.objects.filter(pk=price.pk).delete()


# ---- search ----


def test_search_matches_reference_french_and_arabic_names(category, actor):
    shrimp = new_product(category, actor, name_ar="قمرون ملكي")
    new_product(category, actor, reference="DO-003", name="Dorade royale", sale_price="24.5")
    organization = category.organization

    assert [p.pk for p in selectors.products_of(organization, search="cr-0")] == [shrimp.pk]
    assert [p.pk for p in selectors.products_of(organization, search="قمرون")] == [shrimp.pk]
    assert len(selectors.products_of(organization, search="royale")) == 2


def test_archived_products_are_listed_only_when_asked(category, actor):
    product = new_product(category, actor)
    services.set_product_active(product=product, actor=actor, is_active=False)
    organization = category.organization

    assert not selectors.products_of(organization).exists()
    assert [p.pk for p in selectors.products_of(organization, status="archived")] == [product.pk]
    assert [p.pk for p in selectors.products_of(organization, status="all")] == [product.pk]


# ---- photos ----


def image_upload(size=(3000, 2000), image_format="JPEG", name="photo.jpg", exif_orientation=None):
    buffer = io.BytesIO()
    image = Image.new("RGB", size, (200, 80, 60))
    options = {}
    if exif_orientation is not None:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        exif[0x8825] = {2: (36.0, 49.0, 0.0)}  # a GPS position, which must not survive
        options["exif"] = exif
    image.save(buffer, format=image_format, **options)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")


@pytest.fixture
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


def test_a_photo_is_turned_upright_shrunk_and_stored_as_webp_without_metadata(media, category, actor):
    product = new_product(category, actor)

    # Orientation 6: the phone was held upright, so the 3000 × 2000 pixels show a 2000 × 3000 photo.
    services.set_product_photo(product=product, actor=actor, upload=image_upload(exif_orientation=6))

    product.refresh_from_db()
    assert product.photo.name.startswith(f"products/{product.organization_id}/")
    with Image.open(product.photo.path) as stored:
        assert stored.format == "WEBP"
        assert stored.size == (800, 1200)
        assert not stored.getexif()
    assert actions(product)[-1] == "product.photo_set"


def test_replacing_a_photo_deletes_the_old_file_after_commit(
    media, category, actor, django_capture_on_commit_callbacks
):
    product = new_product(category, actor)
    with django_capture_on_commit_callbacks(execute=True):
        services.set_product_photo(product=product, actor=actor, upload=image_upload())
    first = media / Product.objects.get(pk=product.pk).photo.name

    with django_capture_on_commit_callbacks(execute=True):
        services.set_product_photo(product=product, actor=actor, upload=image_upload(image_format="PNG"))

    second = media / Product.objects.get(pk=product.pk).photo.name
    assert second != first
    assert second.exists()
    assert not first.exists()


def test_removing_a_photo_deletes_the_file(media, category, actor, django_capture_on_commit_callbacks):
    product = new_product(category, actor)
    services.set_product_photo(product=product, actor=actor, upload=image_upload())
    stored = media / Product.objects.get(pk=product.pk).photo.name

    with django_capture_on_commit_callbacks(execute=True):
        services.remove_product_photo(product=product, actor=actor)

    assert not Product.objects.get(pk=product.pk).photo
    assert not stored.exists()


@pytest.mark.parametrize(
    "upload",
    [
        SimpleUploadedFile("notes.txt", b"pas une image", content_type="text/plain"),
        SimpleUploadedFile("photo.jpg", b"\xff\xd8\xff\xe0 truncated", content_type="image/jpeg"),
    ],
)
def test_a_file_that_is_not_an_image_is_refused(media, category, actor, upload):
    product = new_product(category, actor)

    with pytest.raises(ValidationError) as error:
        services.set_product_photo(product=product, actor=actor, upload=upload)

    assert "photo" in error.value.message_dict
    assert not list(media.rglob("*.webp"))


def test_an_unsupported_image_format_is_refused(media, category, actor):
    product = new_product(category, actor)

    with pytest.raises(ValidationError, match="JPEG"):
        services.set_product_photo(product=product, actor=actor, upload=image_upload(image_format="GIF", name="a.gif"))


def test_a_product_still_in_stock_cannot_be_archived_until_it_is_gone(category, actor):
    from apps.inventory import services as inventory
    from apps.inventory.tests.factories import BatchFactory, StockLocationFactory

    organization = category.organization
    product = new_product(category, actor)
    batch = BatchFactory.create(organization=organization, product=product)
    room = StockLocationFactory.create(organization=organization)
    inventory.post_movement(
        organization=organization,
        actor=actor,
        kind=inventory.MovementKind.RECEIPT,
        batch=batch,
        quantity="12.500",
        to_location=room,
    )

    with pytest.raises(ValidationError, match="encore en stock"):
        services.set_product_active(product=product, actor=actor, is_active=False)
    product.refresh_from_db()
    assert product.is_active

    inventory.post_movement(
        organization=organization,
        actor=actor,
        kind=inventory.MovementKind.LOSS,
        batch=batch,
        quantity="12.500",
        from_location=room,
        reason="Perdu",
    )
    assert services.set_product_active(product=product, actor=actor, is_active=False).is_active is False


def test_a_product_without_reference_gets_the_next_article_code(category, actor):
    ProductFactory.create(organization=category.organization, reference="ART0060")

    assert new_product(category, actor, reference="").reference == "ART0061"
    assert new_product(category, actor, reference="", name="Crevette tigrée").reference == "ART0062"
