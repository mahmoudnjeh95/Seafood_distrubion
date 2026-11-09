import factory
from factory.django import DjangoModelFactory

from apps.assistant.models import WhatsAppLink
from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory


class WhatsAppLinkFactory(DjangoModelFactory[WhatsAppLink]):
    class Meta:
        model = WhatsAppLink

    membership = factory.SubFactory(MembershipFactory, role=Role.OWNER)
    organization = factory.SelfAttribute("membership.organization")
    phone = factory.Sequence(lambda n: f"2162{n:07d}")
