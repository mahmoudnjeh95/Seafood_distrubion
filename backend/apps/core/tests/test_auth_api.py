import pytest
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core import access
from apps.core.models import Role

from .factories import MembershipFactory, OrganizationFactory, UserFactory

pytestmark = pytest.mark.django_db

PASSWORD = "test-password"


@pytest.fixture(autouse=True)
def _reset_throttles():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api():
    return APIClient()


def member(role, **user_fields):
    return MembershipFactory.create(role=role, user=UserFactory.create(**user_fields))


def log_in(api, username):
    return api.post(reverse("auth-login"), {"username": username, "password": PASSWORD}, format="json")


def test_login_opens_a_session_and_returns_who_is_logged_in(api):
    membership = member(Role.OWNER, username="owner", first_name="Le", last_name="Gérant")

    response = log_in(api, "owner")

    assert response.status_code == 200
    assert response.json() == {
        "user": {
            "id": membership.user.id,
            "username": "owner",
            "first_name": "Le",
            "last_name": "Gérant",
            "email": membership.user.email,
            "language": "fr",
            "avatar_url": None,
        },
        "organization": {"id": membership.organization.id, "name": membership.organization.name, "logo_url": None},
        "role": "owner",
        "role_label": "Propriétaire",
        # The owner has every section in full (D-306).
        "access": dict.fromkeys(access.SECTION_BY_KEY, "full"),
        "can_buy": False,
        "truck": None,
    }
    assert api.get(reverse("me")).json() == response.json()


def test_wrong_password_and_unknown_user_get_the_same_answer(api):
    member(Role.OWNER, username="owner")

    wrong_password = api.post(reverse("auth-login"), {"username": "owner", "password": "nope"}, format="json")
    unknown_user = api.post(reverse("auth-login"), {"username": "ghost", "password": "nope"}, format="json")

    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()
    assert api.get(reverse("me")).status_code == 401


def test_disabled_account_cannot_log_in(api):
    member(Role.DRIVER, username="driver", is_active=False)

    assert log_in(api, "driver").status_code == 401


@pytest.mark.parametrize("broken", ["no_membership", "inactive_membership", "inactive_organization"])
def test_account_without_an_active_role_cannot_log_in(api, broken):
    user = UserFactory.create(username="lost")
    if broken == "inactive_membership":
        MembershipFactory.create(user=user, is_active=False)
    if broken == "inactive_organization":
        MembershipFactory.create(user=user, organization=OrganizationFactory.create(is_active=False))

    response = log_in(api, "lost")

    assert response.status_code == 403
    assert api.get(reverse("me")).status_code == 401


def test_logout_closes_the_session(api):
    member(Role.OWNER, username="owner")
    log_in(api, "owner")

    assert api.post(reverse("auth-logout")).status_code == 204
    assert api.get(reverse("me")).status_code == 401


def test_me_requires_a_login(api):
    assert api.get(reverse("me")).status_code == 401


def test_login_is_refused_without_a_csrf_token():
    member(Role.OWNER, username="owner")
    strict = APIClient(enforce_csrf_checks=True)

    refused = strict.post(reverse("auth-login"), {"username": "owner", "password": PASSWORD}, format="json")

    assert refused.status_code == 403
    assert strict.get(reverse("me")).status_code == 401


def test_login_works_with_the_csrf_token_from_the_csrf_endpoint():
    member(Role.OWNER, username="owner")
    strict = APIClient(enforce_csrf_checks=True)

    assert strict.get(reverse("auth-csrf")).status_code == 204
    token = strict.cookies["csrftoken"].value
    accepted = strict.post(
        reverse("auth-login"),
        {"username": "owner", "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )

    assert accepted.status_code == 200
    # Once logged in, every write needs the token too.
    assert strict.post(reverse("auth-logout")).status_code == 403
    assert strict.post(reverse("auth-logout"), HTTP_X_CSRFTOKEN=strict.cookies["csrftoken"].value).status_code == 204


def test_too_many_attempts_on_one_account_are_blocked(api, settings):
    member(Role.OWNER, username="owner")
    limit = 8  # login_username rate in settings

    answers = [
        api.post(reverse("auth-login"), {"username": "owner", "password": "nope"}, format="json").status_code
        for _ in range(limit + 1)
    ]

    assert answers[:limit] == [401] * limit
    assert answers[limit] == 429
    # Even the right password is refused until the window passes.
    assert log_in(api, "owner").status_code == 429
    # Another account from the same address is not blocked by this account's limit.
    member(Role.DRIVER, username="driver")
    assert log_in(api, "driver").status_code == 200
