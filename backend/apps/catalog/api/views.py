from typing import Any

from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog import selectors, services
from apps.catalog.models import Category, PriceList, Product, VatRate
from apps.core.models import Membership, Organization
from apps.core.permissions import ReadMemberWriteOwnerOrManager, ReadOfficeWriteOwnerOrManager, membership_of

from .serializers import (
    CategorySerializer,
    PhotoUploadSerializer,
    PriceBoardSerializer,
    PriceListFilterSerializer,
    PriceListSerializer,
    PriceListWriteSerializer,
    ProductCreateSerializer,
    ProductFilterSerializer,
    ProductPriceSerializer,
    ProductSerializer,
    ProductUpdateSerializer,
    SetPriceSerializer,
    SetPricesSerializer,
    VatRateSerializer,
    VatRateWriteSerializer,
)


# Base of the catalogue views: every row is read inside the user's organization (D-022).
# A comment, not a docstring: a docstring would become the description of every endpoint in the schema.
class CatalogView(APIView):
    permission_classes = (ReadMemberWriteOwnerOrManager,)

    @property
    def membership(self) -> Membership:
        membership = membership_of(self.request)
        assert membership is not None  # guaranteed by the permission class
        return membership

    @property
    def organization(self) -> Organization:
        return self.membership.organization

    def product(self, product_id: int) -> Product:
        try:
            return selectors.product_of(self.organization, product_id)
        except Product.DoesNotExist:
            raise Http404 from None

    def product_answer(self, product_id: int, status_code: int = status.HTTP_200_OK) -> Response:
        # Read again so the answer carries the price in force, as the list does.
        return Response(ProductSerializer(self.product(product_id)).data, status=status_code)


class CategoryListView(CatalogView):
    @extend_schema(operation_id="listCategories", responses=CategorySerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(CategorySerializer(selectors.categories_of(self.organization), many=True).data)

    @extend_schema(operation_id="createCategory", request=CategorySerializer, responses={201: CategorySerializer})
    def post(self, request: Request) -> Response:
        serializer = CategorySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        category = services.create_category(
            organization=self.organization, actor=self.membership.user, name=serializer.validated_data["name"]
        )
        return Response(CategorySerializer(category).data, status=status.HTTP_201_CREATED)


class CategoryDetailView(CatalogView):
    @extend_schema(operation_id="renameCategory", request=CategorySerializer, responses=CategorySerializer)
    def patch(self, request: Request, category_id: int) -> Response:
        try:
            category = selectors.categories_of(self.organization).get(pk=category_id)
        except Category.DoesNotExist:
            raise Http404 from None
        serializer = CategorySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        category = services.rename_category(
            category=category, actor=self.membership.user, name=serializer.validated_data["name"]
        )
        return Response(CategorySerializer(category).data)


class ProductListView(CatalogView):
    @extend_schema(
        operation_id="listProducts", parameters=[ProductFilterSerializer], responses=ProductSerializer(many=True)
    )
    def get(self, request: Request) -> Response:
        """Products sorted by name. Archived ones only when asked (`status`). Not paginated: a catalogue
        holds tens of products, not thousands (D-030)."""
        filters = ProductFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        products = selectors.products_of(
            self.organization,
            search=filters.validated_data["search"],
            category_id=filters.validated_data.get("category"),
            status=filters.validated_data["status"],
        )
        return Response(ProductSerializer(products, many=True).data)

    @extend_schema(operation_id="createProduct", request=ProductCreateSerializer, responses={201: ProductSerializer})
    def post(self, request: Request) -> Response:
        serializer = ProductCreateSerializer(data=request.data, context={"organization": self.organization})
        serializer.is_valid(raise_exception=True)
        product = services.create_product(
            organization=self.organization, actor=self.membership.user, **serializer.validated_data
        )
        return self.product_answer(product.pk, status.HTTP_201_CREATED)


class ProductDetailView(CatalogView):
    @extend_schema(operation_id="getProduct", responses=ProductSerializer)
    def get(self, request: Request, product_id: int) -> Response:
        return self.product_answer(product_id)

    @extend_schema(operation_id="updateProduct", request=ProductUpdateSerializer, responses=ProductSerializer)
    def patch(self, request: Request, product_id: int) -> Response:
        """Change the description of a product. The price changes through `setProductPrice`."""
        product = self.product(product_id)
        serializer = ProductUpdateSerializer(
            data=request.data, partial=True, context={"organization": self.organization}
        )
        serializer.is_valid(raise_exception=True)
        services.update_product(product=product, actor=self.membership.user, **serializer.validated_data)
        return self.product_answer(product_id)


class ProductArchiveView(CatalogView):
    @extend_schema(operation_id="archiveProduct", request=None, responses=ProductSerializer)
    def post(self, request: Request, product_id: int) -> Response:
        """Archived products keep their history but can no longer be bought or sold."""
        services.set_product_active(product=self.product(product_id), actor=self.membership.user, is_active=False)
        return self.product_answer(product_id)


class ProductRestoreView(CatalogView):
    @extend_schema(operation_id="restoreProduct", request=None, responses=ProductSerializer)
    def post(self, request: Request, product_id: int) -> Response:
        services.set_product_active(product=self.product(product_id), actor=self.membership.user, is_active=True)
        return self.product_answer(product_id)


class ProductPriceListView(CatalogView):
    @extend_schema(operation_id="listProductPrices", responses=ProductPriceSerializer(many=True))
    def get(self, request: Request, product_id: int) -> Response:
        """Every sale price of the product, newest first, including prices planned for later."""
        prices = selectors.prices_of(self.product(product_id))
        return Response(ProductPriceSerializer(prices, many=True).data)

    @extend_schema(operation_id="setProductPrice", request=SetPriceSerializer, responses={201: ProductSerializer})
    def post(self, request: Request, product_id: int) -> Response:
        """A new sale price from now, or from a later moment. Earlier prices are never changed (D-020)."""
        serializer = SetPriceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.set_sale_price(
            product=self.product(product_id), actor=self.membership.user, **serializer.validated_data
        )
        return self.product_answer(product_id, status.HTTP_201_CREATED)


class ProductPhotoView(CatalogView):
    parser_classes = (MultiPartParser,)

    # Read by an <img> tag, not by the generated client: kept out of the API contract.
    @extend_schema(exclude=True)
    def get(self, request: Request, product_id: int) -> FileResponse:
        product = self.product(product_id)
        if not product.photo:
            raise Http404
        response = FileResponse(product.photo.open("rb"), content_type="image/webp")
        # The address changes with every new photo (see ProductSerializer.photo_url).
        response["Cache-Control"] = "private, max-age=31536000, immutable"
        return response

    @extend_schema(
        operation_id="uploadProductPhoto",
        request={"multipart/form-data": PhotoUploadSerializer},
        responses={200: ProductSerializer, 400: OpenApiResponse(description="Not a readable JPEG, PNG or WebP")},
    )
    def put(self, request: Request, product_id: int) -> Response:
        """Replace the photo. It is turned upright, shrunk to 1200 px and stored as WebP without metadata."""
        serializer = PhotoUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.set_product_photo(
            product=self.product(product_id), actor=self.membership.user, upload=serializer.validated_data["photo"]
        )
        return self.product_answer(product_id)

    @extend_schema(operation_id="removeProductPhoto", request=None, responses={200: ProductSerializer})
    def delete(self, request: Request, product_id: int) -> Response:
        services.remove_product_photo(product=self.product(product_id), actor=self.membership.user)
        return self.product_answer(product_id)


def _products_by_id(organization: Organization, ids: list[int]) -> dict[int, Product]:
    return {p.pk: p for p in Product.objects.for_organization(organization).filter(pk__in=ids)}


def _unknown_product() -> ValidationError:
    return ValidationError({"items": _("Produit inconnu.")})


class PriceBoardView(CatalogView):
    # Costs are office data: drivers get 403 (D-049).
    permission_classes = (ReadOfficeWriteOwnerOrManager,)  # type: ignore[assignment]

    def board(self) -> dict[str, Any]:
        rows = selectors.price_board(self.organization)
        return {"rows": rows, "below_minimum": [row.product.pk for row in rows if row.below_minimum]}

    @extend_schema(operation_id="getPriceBoard", responses=PriceBoardSerializer)
    def get(self, request: Request) -> Response:
        """The "Prix du jour" screen: each active product with its price, the cost of what is in stock
        (last and weighted average), the margin, and the prices already set today with who and when."""
        return Response(PriceBoardSerializer(self.board()).data)

    @extend_schema(operation_id="setPriceBoard", request=SetPricesSerializer, responses=PriceBoardSerializer)
    def post(self, request: Request) -> Response:
        """Save many prices in one transaction. Each changed price applies from this moment; a product
        whose price did not change is left alone. A price below the minimum is accepted and listed in
        `below_minimum`; it is also logged in the audit."""
        serializer = SetPricesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        items = serializer.validated_data["items"]
        products = _products_by_id(self.organization, [item["product"] for item in items])
        changes: list[services.PriceChange] = []
        for item in items:
            if item["product"] not in products:
                raise _unknown_product()
            change: services.PriceChange = {"product": products[item["product"]]}
            if "price" in item:
                change["price"] = item["price"]
            if "min_price" in item:
                change["min_price"] = item["min_price"]
            changes.append(change)
        services.set_sale_prices(organization=self.organization, actor=self.membership.user, changes=changes)
        return Response(PriceBoardSerializer(self.board()).data)


class PriceListBaseView(CatalogView):
    def validated(self, request: Request) -> dict[str, Any]:
        serializer = PriceListWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data: dict[str, Any] = dict(serializer.validated_data)
        products = _products_by_id(self.organization, [item["product"] for item in data["items"]])
        items: list[services.PriceListItemInput] = []
        for item in data["items"]:
            if item["product"] not in products:
                raise _unknown_product()
            items.append({"product": products[item["product"]], "price": item["price"]})
        data["items"] = items
        return data


class PriceListListView(PriceListBaseView):
    @extend_schema(
        operation_id="listPriceLists", parameters=[PriceListFilterSerializer], responses=PriceListSerializer(many=True)
    )
    def get(self, request: Request) -> Response:
        filters = PriceListFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        lists = selectors.price_lists_of(
            self.organization,
            customer_id=filters.validated_data.get("customer"),
            status=filters.validated_data["status"],
        )
        return Response(PriceListSerializer(lists, many=True).data)

    @extend_schema(
        operation_id="createPriceList", request=PriceListWriteSerializer, responses={201: PriceListSerializer}
    )
    def post(self, request: Request) -> Response:
        data = self.validated(request)
        price_list = services.create_price_list(
            organization=self.organization,
            actor=self.membership.user,
            name=data["name"],
            customer_id=data["customer"],
            items=data["items"],
        )
        answer = selectors.price_list_of(self.organization, price_list.pk)
        return Response(PriceListSerializer(answer).data, status=status.HTTP_201_CREATED)


class PriceListDetailView(PriceListBaseView):
    def price_list(self, price_list_id: int) -> PriceList:
        try:
            return selectors.price_list_of(self.organization, price_list_id)
        except PriceList.DoesNotExist:
            raise Http404 from None

    @extend_schema(operation_id="getPriceList", responses=PriceListSerializer)
    def get(self, request: Request, price_list_id: int) -> Response:
        return Response(PriceListSerializer(self.price_list(price_list_id)).data)

    @extend_schema(operation_id="updatePriceList", request=PriceListWriteSerializer, responses=PriceListSerializer)
    def put(self, request: Request, price_list_id: int) -> Response:
        """Replace the name, customer, state and items of a list. Items not sent are removed."""
        price_list = self.price_list(price_list_id)
        data = self.validated(request)
        services.update_price_list(
            price_list=price_list,
            actor=self.membership.user,
            name=data["name"],
            customer_id=data["customer"],
            is_active=data["is_active"],
            items=data["items"],
        )
        return Response(PriceListSerializer(self.price_list(price_list_id)).data)


def _vat_rows(organization: Organization, rates: list[VatRate]) -> list[dict[str, Any]]:
    return [
        {
            "id": row.pk,
            "rate": row.rate,
            "label": row.label,
            "is_active": row.is_active,
            "in_use": services.vat_rate_in_use(organization, row.rate),
        }
        for row in rates
    ]


class VatRateView(CatalogView):
    # The office reads the VAT rates; owners and managers change them. Drivers have no use for them.
    permission_classes = (ReadOfficeWriteOwnerOrManager,)  # type: ignore[assignment]


class VatRateListView(VatRateView):
    @extend_schema(operation_id="listVatRates", responses=VatRateSerializer(many=True))
    def get(self, request: Request) -> Response:
        """The VAT rates (Paramètres › TVA, D-283), lowest first, active and deactivated. The product form offers
        the active ones."""
        return Response(
            VatRateSerializer(_vat_rows(self.organization, services.vat_rates_of(self.organization)), many=True).data
        )

    @extend_schema(operation_id="createVatRate", request=VatRateWriteSerializer, responses={201: VatRateSerializer})
    def post(self, request: Request) -> Response:
        """A new VAT rate (owner or manager), active at once."""
        serializer = VatRateWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if "rate" not in serializer.validated_data:
            raise ValidationError({"rate": _("Indiquez le taux en %.")})
        created = services.create_vat_rate(
            organization=self.organization,
            actor=self.membership.user,
            rate=serializer.validated_data["rate"],
            label=serializer.validated_data.get("label", ""),
        )
        return Response(
            VatRateSerializer(_vat_rows(self.organization, [created])[0]).data, status=status.HTTP_201_CREATED
        )


class VatRateDetailView(VatRateView):
    def vat_rate(self, rate_id: int) -> VatRate:
        try:
            return VatRate.objects.for_organization(self.organization).get(pk=rate_id)
        except VatRate.DoesNotExist:
            raise Http404 from None

    @extend_schema(operation_id="updateVatRate", request=VatRateWriteSerializer, responses=VatRateSerializer)
    def patch(self, request: Request, rate_id: int) -> Response:
        """Change a VAT rate's label, deactivate it or bring it back; its percent only while nothing uses it."""
        serializer = VatRateWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = services.update_vat_rate(
            vat_rate=self.vat_rate(rate_id), actor=self.membership.user, **serializer.validated_data
        )
        return Response(VatRateSerializer(_vat_rows(self.organization, [updated])[0]).data)

    @extend_schema(operation_id="deleteVatRate", request=None, responses={204: None})
    def delete(self, request: Request, rate_id: int) -> Response:
        """Delete a VAT rate never used; one in use is refused (deactivate it instead)."""
        services.delete_vat_rate(vat_rate=self.vat_rate(rate_id), actor=self.membership.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
