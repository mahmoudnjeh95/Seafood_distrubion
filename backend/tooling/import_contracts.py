"""Import-linter contract for the boundary rule in docs/ARCHITECTURE.md §3.

An app may call another app's `services` and `selectors`, never its models, API or private helpers.
`core` is the shared kernel: every app may import it, and it imports no other app.
"""

from grimp import ImportGraph
from importlinter import Contract, ContractCheck, output

APPS_PACKAGE = "apps"
SHARED_APP = "core"
PUBLIC_MODULES = frozenset({"services", "selectors"})
# One-time operations command that empties every app's data before go-live (D-146). It reads the models of all apps
# on purpose; nothing else may do so.
RESET_COMMANDS = frozenset(
    {"apps.demo.management.commands.prepare_client_start", "apps.demo.management.commands.prepare_training"}
)


def boundary_violation(importer: str, imported: str) -> str | None:
    """Return why `importer` may not import `imported`, or None when the import is allowed."""
    importer_parts = importer.split(".")
    imported_parts = imported.split(".")
    if len(importer_parts) < 2 or len(imported_parts) < 2:
        return None
    if importer_parts[0] != APPS_PACKAGE or imported_parts[0] != APPS_PACKAGE:
        return None

    importer_app, imported_app = importer_parts[1], imported_parts[1]
    if importer_app == imported_app:
        return None
    # Tests may build data with another app's factories.
    if len(importer_parts) > 2 and importer_parts[2] == "tests":
        return None
    if importer in RESET_COMMANDS:
        return None
    if importer_app == SHARED_APP:
        return f"`{SHARED_APP}` must not depend on another app"
    if imported_app == SHARED_APP:
        return None
    if len(imported_parts) > 2 and imported_parts[2] in PUBLIC_MODULES:
        return None
    return f"only `{imported_app}.services` and `{imported_app}.selectors` are public"


class AppBoundariesContract(Contract):
    def check(self, graph: ImportGraph, verbose: bool) -> ContractCheck:
        violations = []
        for importer in sorted(graph.modules):
            for imported in sorted(graph.find_modules_directly_imported_by(importer)):
                reason = boundary_violation(importer, imported)
                if reason is None:
                    continue
                for detail in graph.get_import_details(importer=importer, imported=imported):
                    violations.append(
                        {
                            "importer": importer,
                            "imported": imported,
                            "line_number": detail["line_number"],
                            "reason": reason,
                        }
                    )
        return ContractCheck(kept=not violations, metadata={"violations": violations})

    def render_broken_contract(self, check: ContractCheck) -> None:
        for violation in check.metadata["violations"]:
            output.print_error(
                f"{violation['importer']}:{violation['line_number']} imports {violation['imported']}: "
                f"{violation['reason']}",
                bold=False,
            )
        output.new_line()
