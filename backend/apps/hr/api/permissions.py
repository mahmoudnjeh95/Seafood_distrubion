from rest_framework.permissions import SAFE_METHODS
from rest_framework.request import Request
from rest_framework.views import APIView

from apps.core.models import Membership, Role
from apps.core.permissions import HasRole


class ReadOwnerOrAccountantWriteOwner(HasRole):
    """Pay is the most private data of the company (D-055): the owner reads and writes, the accountant reads.
    Managers and drivers get 403 on everything: nobody sees another person's pay. Through the access matrix
    (D-306) a person needs "Salaires" in reading, or "full" to change anything."""

    roles = frozenset({Role.OWNER, Role.ACCOUNTANT})
    owner_writes = True

    def role_allows(self, request: Request, view: APIView, membership: Membership) -> bool:
        if not super().role_allows(request, view, membership):
            return False
        return request.method in SAFE_METHODS or membership.role == Role.OWNER
