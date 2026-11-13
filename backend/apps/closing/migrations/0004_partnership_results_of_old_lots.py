"""Every lot result frozen with a partner gets its partnership result (D-324): one line, the same figures, and the
partner's ledger rows and settlement point to it. The line results keep their partner columns as history."""

from typing import Any

from django.db import migrations


def forwards(apps: Any, schema_editor: Any) -> None:
    LotResult = apps.get_model("closing", "LotResult")
    PartnershipResult = apps.get_model("closing", "PartnershipResult")
    CapitalEntry = apps.get_model("partnerships", "CapitalEntry")
    ProfitShareEntry = apps.get_model("partnerships", "ProfitShareEntry")
    PartnerSettlement = apps.get_model("partnerships", "PartnerSettlement")
    results = (
        LotResult.objects.filter(partnership__isnull=False).select_related("batch__product").order_by("closed_at", "id")
    )
    for line in results:
        data = line.data or {}
        steps = list(data.get("steps", []))
        codes = [step.get("code") for step in steps]
        # The line's share steps come after its net result: they are the partnership's with one line.
        share_steps = steps[codes.index("net_result") + 1 :] if "net_result" in codes else []
        net = str(line.net_result)
        frozen = PartnershipResult.objects.create(
            organization_id=line.organization_id,
            partnership_id=line.partnership_id,
            status=line.status,
            net_result=line.net_result,
            partner_share=line.partner_share,
            owner_share=line.owner_share,
            capital_deducted=line.capital_deducted,
            uncovered_loss=line.uncovered_loss,
            capital_to_return=line.capital_to_return,
            data={
                "lines": [
                    {
                        "lot_result_id": line.pk,
                        "batch_id": line.batch_id,
                        "batch_number": line.batch.number,
                        "product_name": line.batch.product.name,
                        "net_result": net,
                    }
                ],
                "net_result": net,
                "outcome": data.get("outcome", ""),
                "owner_share": str(line.owner_share),
                "partner": data.get("partner"),
                "steps": [
                    {"code": "line", "sign": "+", "amount": net, "kind": line.batch.number, "rate": None},
                    {"code": "net_result", "sign": "=", "amount": net, "kind": "", "rate": None},
                    *share_steps,
                ],
            },
            closed_at=line.closed_at,
            closed_by_id=line.closed_by_id,
            reopened_at=line.reopened_at,
            reopened_by_id=line.reopened_by_id,
            reopen_reason=line.reopen_reason,
        )
        for model in (CapitalEntry, ProfitShareEntry, PartnerSettlement):
            model.objects.filter(partnership_id=line.partnership_id, lot_result_id=line.pk).update(
                partnership_result_id=frozen.pk
            )


def backwards(apps: Any, schema_editor: Any) -> None:
    for name in ("CapitalEntry", "ProfitShareEntry", "PartnerSettlement"):
        apps.get_model("partnerships", name).objects.update(partnership_result_id=None)
    apps.get_model("closing", "PartnershipResult").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("closing", "0003_partnership_result"),
        ("partnerships", "0006_partnership_result"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
