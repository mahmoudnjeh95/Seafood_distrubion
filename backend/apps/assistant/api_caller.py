"""Call the app's own API in-process, as one user.

The assistant reaches other apps' data through their endpoints, not their code: each view's permission classes,
filters (a driver sees only his truck) and serializers decide what the bot may see, exactly as on the screens.
"""

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from django.http import Http404
from django.urls import Resolver404, resolve
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.core.models import User

API_PREFIX = "/api/v1/"
ALLOWED_METHODS = frozenset({"GET"})
_SAFE_PATH = re.compile(r"^[A-Za-z0-9_\-/]+$")


@dataclass(frozen=True)
class ApiResult:
    status: int
    data: Any


def call_api(
    *,
    user: User,
    method: str,
    path: str,
    query: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
) -> ApiResult:
    """Run one API call as `user` and return its status and data. Only reads in this version (P12-T01)."""
    method = method.upper()
    if method not in ALLOWED_METHODS:
        raise ValueError(f"Méthode refusée : {method}")
    if not _SAFE_PATH.match(path) or ".." in path or "//" in path or path.startswith("/"):
        raise ValueError(f"Chemin refusé : {path!r}")
    full_path = API_PREFIX + path
    try:
        match = resolve(full_path)
    except (Resolver404, Http404):
        return ApiResult(404, None)
    request = APIRequestFactory().generic(method, full_path, data="", QUERY_STRING=_query_string(query))
    force_authenticate(request, user=user)
    response = match.func(request, *match.args, **match.kwargs)
    if hasattr(response, "render"):
        response.render()
    return ApiResult(response.status_code, getattr(response, "data", None))


def _query_string(query: dict[str, str] | None) -> str:
    return urlencode({key: value for key, value in (query or {}).items() if value not in (None, "")})
