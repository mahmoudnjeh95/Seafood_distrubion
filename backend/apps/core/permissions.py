"""Role checks for the API layer (ARCHITECTURE §4.8). Hiding a button is not security: every view sets one.

Every class first asks the access matrix (D-306, `apps.core.access`): a custom role, or a person the owner gave
their own level in a section, is decided there; everyone else by the rule of the class, as before.
"""

from typing import ClassVar

from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from . import access
from .models import Membership, Role, User
from .selectors import active_membership

_CACHE_ATTRIBUTE = "_frutti_membership"


def membership_of(request: Request) -> Membership | None:
    """The logged-in user's active membership, looked up once per request."""
    if not isinstance(request.user, User):
        return None
    if not hasattr(request, _CACHE_ATTRIBUTE):
        setattr(request, _CACHE_ATTRIBUTE, active_membership(request.user))
    membership: Membership | None = getattr(request, _CACHE_ATTRIBUTE)
    return membership


def _owner_writes(view: APIView) -> bool:
    return any(getattr(permission, "owner_writes", False) for permission in getattr(view, "permission_classes", ()))


def matrix_decision(
    request: Request, view: APIView, membership: Membership, *, owner_writes: bool = False
) -> bool | None:
    """The access matrix's answer for this call, or None when the class's own rule decides (D-306).
    `owner_writes`: the class checking the call leaves its writes to the owner."""
    match = getattr(request, "resolver_match", None)
    if match is None or not match.route:
        return None
    return access.decide(
        membership,
        route=match.route,
        kwargs=match.kwargs,
        method=request.method or "GET",
        owner_writes=owner_writes or _owner_writes(view),
    )


class MatrixFirst(BasePermission):
    """Base of every role check: the matrix first (D-306), then `role_allows`."""

    # The writes behind this class are the owner's alone: through the matrix they need the level `full`.
    owner_writes: ClassVar[bool] = False

    def has_permission(self, request: Request, view: APIView) -> bool:
        membership = membership_of(request)
        if membership is None:
            return False
        decided = matrix_decision(request, view, membership, owner_writes=self.owner_writes)
        if decided is not None:
            return decided
        return self.role_allows(request, view, membership)

    def role_allows(self, request: Request, view: APIView, membership: Membership) -> bool:
        raise NotImplementedError


class HasRole(MatrixFirst):
    """Allowed when the user's role in their organization is one of `roles`."""

    roles: ClassVar[frozenset[Role]] = frozenset(Role)

    def role_allows(self, request: Request, view: APIView, membership: Membership) -> bool:
        return membership.role in self.roles


class IsMember(HasRole):
    """Any role, as long as the user belongs to an active organization."""


class IsOwner(HasRole):
    """The owner only: used for the data import (D-112) and for managing other users and roles (D-123, D-306)."""

    roles = frozenset({Role.OWNER})
    owner_writes = True


class IsOwnerOrManager(HasRole):
    roles = frozenset({Role.OWNER, Role.MANAGER})


class IsDriver(HasRole):
    roles = frozenset({Role.DRIVER})


class ReadMemberWriteOwnerOrManager(HasRole):
    """Every member may read (drivers need the catalogue to sell); only owners and managers may change."""

    def role_allows(self, request: Request, view: APIView, membership: Membership) -> bool:
        if request.method in SAFE_METHODS:
            return True
        return membership.role in IsOwnerOrManager.roles


class ReadOwnerOrAccountantWriteOwner(HasRole):
    """The owner's own money (lot results, partners' shares and capital, D-060, D-061): the owner reads and
    changes, the accountant reads; managers and drivers get 403."""

    roles = frozenset({Role.OWNER, Role.ACCOUNTANT})
    owner_writes = True

    def role_allows(self, request: Request, view: APIView, membership: Membership) -> bool:
        if not super().role_allows(request, view, membership):
            return False
        return request.method in SAFE_METHODS or membership.role == Role.OWNER


class ReadOfficeWriteOwnerOrManager(HasRole):
    """Office data drivers have no use for (suppliers, purchases): owners, managers and the accountant read;
    only owners and managers change."""

    roles = frozenset({Role.OWNER, Role.MANAGER, Role.ACCOUNTANT})

    def role_allows(self, request: Request, view: APIView, membership: Membership) -> bool:
        if not super().role_allows(request, view, membership):
            return False
        return request.method in SAFE_METHODS or membership.role in IsOwnerOrManager.roles
