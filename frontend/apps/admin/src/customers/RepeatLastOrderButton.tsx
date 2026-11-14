import { repeatSale, useListSales } from "@frutti/api";
import { useTranslation } from "@frutti/i18n";
import { Button, toast } from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";

import { fieldErrors } from "../lib/errors";
import { refreshAfterSale } from "../sales/shared";

/** "Refaire la dernière commande" (P13-T02, D-331): the customer's latest confirmed BL again, as a new draft with the
 * same products and kilos at today's prices. Hidden while the customer has no confirmed BL. */
export function RepeatLastOrderButton({ customerId }: { customerId: number }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const last = useListSales({
    customer: customerId,
    status: "confirmed",
    ordering: "-date",
    opening: "exclude",
    limit: 1,
  });
  const latest = last.data?.results[0];
  const repeat = useMutation({
    mutationFn: (saleId: number) => repeatSale(saleId),
    onSuccess: async (saved) => {
      toast.success(t("admin.sales.detail.repeated", { number: saved.number }));
      await refreshAfterSale(queryClient);
      void navigate(`/ventes/${saved.id}`);
    },
    onError: (failure) => toast.error(Object.values(fieldErrors(failure))[0] ?? t("admin.sales.detail.actionError")),
  });
  if (!latest) return null;
  return (
    <Button disabled={repeat.isPending} onClick={() => repeat.mutate(latest.id)}>
      {t("admin.customers.detail.repeatLast", { number: latest.number })}
    </Button>
  );
}
