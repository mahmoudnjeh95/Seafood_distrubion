from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import QuerySet
from django.http import FileResponse, Http404
from django.urls import reverse
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.core.api.pagination import PagedList
from apps.core.models import Membership, Organization
from apps.core.permissions import ReadOfficeWriteOwnerOrManager, membership_of

from .. import selectors, services
from ..models import WebRequest
from .serializers import (
    OfficeSiteProductSerializer,
    SiteCatalogSerializer,
    SiteProductUpdateSerializer,
    SiteRequestReceivedSerializer,
    SiteRequestSerializer,
    SiteSettingsSerializer,
    WebRequestFilterSerializer,
    WebRequestSerializer,
    WebRequestStatusSerializer,
)


class SiteCatalogThrottle(AnonRateThrottle):
    scope = "site_catalog"


class SiteRequestThrottle(AnonRateThrottle):
    """A visitor sends a few requests an hour at most; more is a robot filling the office's list."""

    scope = "site_request"


# The public site (D-186): nobody is logged in, so no session and no CSRF; a few calls per address only.
# A comment, not a docstring: a docstring would describe every endpoint in the schema.
class SiteView(APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)

    def site_organization(self) -> Organization:
        organization = selectors.site_organization()
        if organization is None:
            raise Http404
        return organization


def _logo_url(organization: Organization) -> str | None:
    if not organization.logo.name:
        return None
    # The file name changes with every upload, so the address can be cached for good.
    version = organization.logo.name.rsplit("/", 1)[-1].split(".", 1)[0]
    return f"{reverse('site-logo')}?v={version}"


class SiteCatalogView(SiteView):
    throttle_classes = (SiteCatalogThrottle,)

    @extend_schema(operation_id="getSiteCatalog", responses=SiteCatalogSerializer)
    def get(self, request: Request) -> Response:
        """What the public site offers: the company's name and contact details, its categories and the products
        the office put on the site, with their web price (or none: "prix sur demande")."""
        organization = self.site_organization()
        answer = {
            "company": organization.name,
            "logo_url": _logo_url(organization),
            "contact": selectors.site_settings_of(organization),
            "categories": selectors.site_categories(organization),
            "products": selectors.site_products(organization),
        }
        return Response(SiteCatalogSerializer(answer).data)


class SiteLogoView(SiteView):
    throttle_classes = (SiteCatalogThrottle,)

    # Read by an <img> tag, not by the generated client: kept out of the API contract.
    @extend_schema(exclude=True)
    def get(self, request: Request) -> FileResponse:
        """The company logo, for the site's header, footer and browser tab (D-186)."""
        organization = self.site_organization()
        if not organization.logo:
            raise Http404
        response = FileResponse(organization.logo.open("rb"), content_type="image/webp")
        response["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


class SiteProductPhotoView(SiteView):
    throttle_classes = (SiteCatalogThrottle,)

    # Read by an <img> tag, not by the generated client: kept out of the API contract.
    @extend_schema(exclude=True)
    def get(self, request: Request, product_id: int) -> FileResponse:
        try:
            offer = selectors.site_offer_of(self.site_organization(), product_id)
        except ObjectDoesNotExist:
            raise Http404 from None
        if not offer.product.is_active or not offer.is_published or not offer.product.photo:
            raise Http404
        response = FileResponse(offer.product.photo.open("rb"), content_type="image/webp")
        # The address changes with every new photo (see SiteProductSerializer.photo_url).
        response["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


class SiteRequestView(SiteView):
    throttle_classes = (SiteRequestThrottle,)

    @extend_schema(
        operation_id="sendSiteRequest",
        request=SiteRequestSerializer,
        responses={
            201: SiteRequestReceivedSerializer,
            400: OpenApiResponse(description="A field is missing or wrong, e.g. the phone number"),
            429: OpenApiResponse(description="Too many requests from this address"),
        },
    )
    def post(self, request: Request) -> Response:
        """A visitor asks for a quote or orders products. The phone number is required: the office calls back
        to confirm prices and delivery."""
        serializer = SiteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data.pop("website")
        lines = [
            services.RequestedLine(product_id=line["product"], quantity=line["quantity"], note=line["note"])
            for line in data.pop("lines")
        ]
        web_request = services.submit_web_request(organization=self.site_organization(), lines=lines, **data)
        return Response(SiteRequestReceivedSerializer(web_request).data, status=status.HTTP_201_CREATED)


# ---- The office (owners and managers handle them; the accountant reads) ----


class OfficeView(APIView):
    permission_classes = (ReadOfficeWriteOwnerOrManager,)

    @property
    def membership(self) -> Membership:
        membership = membership_of(self.request)
        assert membership is not None  # guaranteed by the permission class
        return membership

    @property
    def organization(self) -> Organization:
        return self.membership.organization

    def web_request(self, request_id: int) -> WebRequest:
        try:
            return selectors.web_request_of(self.organization, request_id)
        except WebRequest.DoesNotExist:
            raise Http404 from None


class WebRequestListView(OfficeView, ListAPIView[WebRequest]):
    serializer_class = WebRequestSerializer
    pagination_class = PagedList
    ordering_columns = {
        "number": ("pk",),
        "date": ("pk",),
        "customer": ("full_name",),
        "phone": ("phone",),
    }

    def get_queryset(self) -> QuerySet[WebRequest]:
        filters = WebRequestFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        return selectors.web_requests_of(
            self.organization,
            status=filters.validated_data.get("status"),
            kind=filters.validated_data.get("kind"),
            search=filters.validated_data["search"],
        )

    @extend_schema(operation_id="listWebRequests", parameters=[WebRequestFilterSerializer])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Quote requests and orders sent from the public site, newest first, paginated (`limit`, `offset`).
        Filter by status, kind or `search` (name, phone, company, number)."""
        return super().get(request, *args, **kwargs)


class WebRequestDetailView(OfficeView):
    @extend_schema(operation_id="getWebRequest", responses=WebRequestSerializer)
    def get(self, request: Request, request_id: int) -> Response:
        return Response(WebRequestSerializer(self.web_request(request_id)).data)


class WebRequestStatusView(OfficeView):
    @extend_schema(
        operation_id="setWebRequestStatus", request=WebRequestStatusSerializer, responses=WebRequestSerializer
    )
    def post(self, request: Request, request_id: int) -> Response:
        """The office called the visitor back: mark the request handled or cancelled with a note, or new again."""
        serializer = WebRequestStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.set_web_request_status(
            request=self.web_request(request_id),
            actor=self.membership.user,
            status=serializer.validated_data["status"],
            note=serializer.validated_data["office_note"],
        )
        return Response(WebRequestSerializer(self.web_request(request_id)).data)


# ---- The office: what the site shows (D-186) ----


class SiteProductListView(OfficeView):
    @extend_schema(operation_id="listSiteProducts", responses=OfficeSiteProductSerializer(many=True))
    def get(self, request: Request) -> Response:
        """Every active product of the application, in the site's order, with its photo, its day's price and what
        the site shows of it. A product the office never changed is shown, without a web price."""
        offers = selectors.site_offers(self.organization, include_hidden=True)
        return Response(OfficeSiteProductSerializer(offers, many=True).data)


class SiteProductDetailView(OfficeView):
    @extend_schema(
        operation_id="updateSiteProduct", request=SiteProductUpdateSerializer, responses=OfficeSiteProductSerializer
    )
    def patch(self, request: Request, product_id: int) -> Response:
        """Hide or show a product on the site, set its web price (null: "prix sur demande"), its text or its
        place. The day's price and the price lists do not change."""
        try:
            selectors.site_offer_of(self.organization, product_id)
        except ObjectDoesNotExist:
            raise Http404 from None
        serializer = SiteProductUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.update_site_product(
            organization=self.organization,
            actor=self.membership.user,
            product_id=product_id,
            changes=serializer.validated_data,
        )
        offer = selectors.site_offer_of(self.organization, product_id)
        return Response(OfficeSiteProductSerializer(offer).data)


class SiteSettingsView(OfficeView):
    @extend_schema(operation_id="getSiteSettings", responses=SiteSettingsSerializer)
    def get(self, request: Request) -> Response:
        """The phone, WhatsApp, e-mail, address and hours the public site shows (empty until saved once)."""
        return Response(SiteSettingsSerializer(selectors.site_settings_of(self.organization)).data)

    @extend_schema(operation_id="saveSiteSettings", request=SiteSettingsSerializer, responses=SiteSettingsSerializer)
    def put(self, request: Request) -> Response:
        """Replace the site's contact details. The numbers are checked and written one way ("+216 74 123 456")."""
        serializer = SiteSettingsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        saved = services.save_site_settings(
            organization=self.organization, actor=self.membership.user, **serializer.validated_data
        )
        return Response(SiteSettingsSerializer(saved).data)
