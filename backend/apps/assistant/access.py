"""Who may use the assistant.

Using the bot is a permission of the roles matrix: section "assistant", level "write" (owner, 2026-11-09).
Until the matrix is merged (branch user-roles-matrix), its default applies: the owner only.
"""

from apps.core.models import Membership, Role


def may_use(membership: Membership) -> bool:
    return membership.is_active and membership.role == Role.OWNER
