import { ApiError, reportMyLoss, useListMyStock, useReturnMyStock } from "@frutti/api";
import { useSession } from "@frutti/auth";
import { formatQuantity, parseDecimalInput, useTranslation } from "@frutti/i18n";
import { Button, Card, EmptyState, Input, toast } from "@frutti/ui";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { pendingKilos, useQueue } from "./queue";
import { sendOrKeep } from "./sendOrKeep";
import { sendWaiting } from "./sync";
import { newUuid } from "./uuid";

const REASONS = ["spoiled", "damaged", "expired", "cold_chain", "other"] as const;

// Every text the server put in an error answer, so the driver reads why it was refused.
function messagesOf(body: unknown): string[] {
  if (typeof body === "string") return [body];
  if (Array.isArray(body)) return body.flatMap(messagesOf);
  if (typeof body === "object" && body !== null) return Object.values(body).flatMap(messagesOf);
  return [];
}

// "Perte ou retour": spoiled product with a photo, or bring what is left back to the cold room.
export function LossPage() {
  const { t } = useTranslation();
  const session = useSession();
  const queryClient = useQueryClient();
  const truck = session.data?.truck ?? null;
  const stock = useListMyStock({ query: { enabled: truck !== null, retry: false } });
  const [product, setProduct] = useState<number | null>(null);
  const [kilos, setKilos] = useState("");
  const [reason, setReason] = useState<(typeof REASONS)[number] | null>(null);
  const [photo, setPhoto] = useState<File | undefined>(undefined);
  const [uuid, setUuid] = useState(newUuid);
  const [error, setError] = useState("");
  const [sure, setSure] = useState(false);

  const fail = (failure: unknown, fallback: string) =>
    (failure instanceof ApiError ? messagesOf(failure.body).join(" ") : "") || fallback;
  const [saving, setSaving] = useState(false);
  const queue = useQueue();
  const giveBack = useReturnMyStock({
    mutation: {
      onSuccess: (done) => {
        toast.success(t("truck.loss.returned", { room: done.to_location }));
        setSure(false);
        void queryClient.invalidateQueries();
      },
      onError: (failure) => {
        setSure(false);
        setError(fail(failure, t("truck.loss.returnFailed")));
      },
    },
  });

  if (truck === null) {
    return (
      <EmptyState illustration="truck" title={t("truck.day.noTruck")}>
        {t("truck.sale.needTruck")}
      </EmptyState>
    );
  }
  const items = stock.data ?? [];
  const kilosValue = parseDecimalInput(kilos.trim(), 3);
  const promised = pendingKilos(queue);
  const heldBack = (id: number) => promised[id] ?? 0;
  const tooMuch =
    product !== null &&
    kilosValue !== null &&
    Number(kilosValue) > Number(items.find((item) => item.product_id === product)?.quantity ?? 0) - heldBack(product);
  const ready = product !== null && reason !== null && kilosValue !== null && Number(kilosValue) > 0 && !tooMuch;

  const save = async () => {
    if (product === null || reason === null || kilosValue === null) return;
    setSaving(true);
    setError("");
    const data = { product, quantity: kilosValue, reason, photo, client_uuid: uuid };
    try {
      const outcome = await sendOrKeep(
        {
          kind: "loss",
          uuid,
          createdAt: new Date().toISOString(),
          label: items.find((item) => item.product_id === product)?.product_name ?? "",
          data,
          status: "pending",
          error: "",
        },
        () => reportMyLoss(data),
      );
      toast.success(
        t(
          outcome.kept
            ? "truck.loss.kept"
            : outcome.result?.status === "pending"
              ? "truck.loss.savedWaiting"
              : "truck.loss.saved",
        ),
      );
      setProduct(null);
      setKilos("");
      setReason(null);
      setPhoto(undefined);
      setUuid(newUuid());
      void queryClient.invalidateQueries();
      void sendWaiting(queryClient);
    } catch (failure) {
      setError(fail(failure, t("truck.loss.failed")));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      {items.length === 0 ? (
        <EmptyState illustration="fridge" title={t("truck.sale.emptyTruck")}>
          {t("truck.loss.nothingToDo")}
        </EmptyState>
      ) : (
        <>
          <Card className="space-y-4">
            <h2>{t("truck.loss.which")}</h2>
            <div className="grid grid-cols-2 gap-3">
              {items.map((item) => (
                <Button
                  key={item.product_id}
                  size="lg"
                  variant={product === item.product_id ? "primary" : "secondary"}
                  className="flex-col py-4 text-lg"
                  onClick={() => setProduct(item.product_id)}
                >
                  <span>{item.product_name}</span>
                  <span className="text-sm font-normal">{formatQuantity(item.quantity)}</span>
                </Button>
              ))}
            </div>
            <div className="space-y-1">
              <label htmlFor="loss-kg" className="font-semibold">
                {t("truck.loss.kilos")}
              </label>
              <Input
                id="loss-kg"
                inputMode="decimal"
                placeholder="0"
                className="text-2xl"
                value={kilos}
                onChange={(event) => setKilos(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <p className="font-semibold">{t("truck.loss.why")}</p>
              <div className="grid grid-cols-2 gap-3">
                {REASONS.map((key) => (
                  <Button
                    key={key}
                    size="lg"
                    variant={reason === key ? "primary" : "secondary"}
                    onClick={() => setReason(key)}
                  >
                    {t(`truck.loss.reasons.${key}`)}
                  </Button>
                ))}
              </div>
            </div>
            <div className="space-y-1">
              <label htmlFor="loss-photo" className="font-semibold">
                {t("truck.loss.photo")}
              </label>
              <input
                id="loss-photo"
                type="file"
                accept="image/*"
                capture="environment"
                onChange={(event) => setPhoto(event.target.files?.[0])}
              />
            </div>
            {tooMuch ? <p className="text-bad">{t("truck.sale.notEnough")}</p> : null}
            {error === "" ? null : <p className="text-bad">{error}</p>}
            <Button
              size="lg"
              variant="primary"
              className="py-4 text-lg"
              disabled={!ready || saving}
              onClick={() => void save()}
            >
              {t("truck.loss.save")}
            </Button>
          </Card>
          <Card className="space-y-3">
            <h2>{t("truck.loss.giveBackTitle")}</h2>
            <p className="text-ink-2">{t("truck.loss.giveBackBody")}</p>
            {sure ? (
              <Button
                size="lg"
                variant="primary"
                className="py-4 text-lg"
                disabled={giveBack.isPending}
                onClick={() => giveBack.mutate()}
              >
                {t("truck.loss.giveBackSure")}
              </Button>
            ) : (
              <Button size="lg" className="py-4 text-lg" onClick={() => setSure(true)}>
                {t("truck.loss.giveBack")}
              </Button>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
