from typing import Any

from rest_framework.permissions import SAFE_METHODS
from rest_framework.request import Request
from rest_framework.views import APIView

from apps.core.models import Membership, Role
from apps.core.permissions import IsOwnerOrManager, MatrixFirst, membership_of
from apps.fleet import selectors


class AssignmentsOfficeOrOwnDriver(MatrixFirst):
    """Every member reads the day's assignments (a driver sees their own rows only); owners and managers
    change them, and a driver changes their own. Views narrow a driver to their own rows."""

    def role_allows(self, request: Request, view: APIView, membership: Membership) -> bool:
        if request.method in SAFE_METHODS:
            return True
        return membership.role in IsOwnerOrManager.roles or membership.role == Role.DRIVER


class OwnTruckOrOffice(MatrixFirst):
    """Every member reads trucks, but a driver only their own one; owners and managers change them.

    Views call `check_object_permissions` on the truck they act on, and filter lists the same way.
    """

    def role_allows(self, request: Request, view: APIView, membership: Membership) -> bool:
        return request.method in SAFE_METHODS or membership.role in IsOwnerOrManager.roles

    def has_object_permission(self, request: Request, view: APIView, obj: Any) -> bool:
        membership = membership_of(request)
        return membership is not None and selectors.may_use_truck(membership, obj)
