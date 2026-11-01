import {
  getListSiteProductsQueryKey,
  type OfficeSiteProduct,
  type PatchedSiteProductUpdate,
  updateSiteProduct,
  useListSiteProducts,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatMoney, parseDecimalInput, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  EmptyState,
  Illustration,
  ILLUSTRATION_NAMES,
  MoneyInput,
  type IllustrationName,
  Input,
  PageHeader,
  Pill,
  Table,
  Td,
  Th,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useOutletContext } from "react-router";

import { fieldErrors } from "../lib/errors";
import { useDebounced } from "../lib/useDebounced";
import { canRecordReceipts } from "../receipts/shared";
import { SITE_URL } from "./shared";

/** "" → null ("prix sur demande"); "28,5" → "28.5"; anything else → undefined (not a price). */
function parseWebPrice(text: string): string | null | undefined {
  if (text.trim() === "") return null;
  const value = parseDecimalInput(text, 3);
  return value === null || value.startsWith("-") ? undefined : value;
}

function isIllustration(name: string): name is IllustrationName {
  return (ILLUSTRATION_NAMES as readonly string[]).includes(name);
}

function matches(row: OfficeSiteProduct, query: string): boolean {
  const text = `${row.product_name} ${row.product_reference} ${row.category_name}`.toLowerCase();
  return query
    .toLowerCase()
    .split(/\s+/)
    .every((word) => text.includes(word));
}

/** Every active product of the application, with its photo, as the public site shows it (D-186). The office hides
 * some, gives a web price and a text, and sets the order. The day's price is never touched. */
export function SiteProductsPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const canEdit = canRecordReceipts(session);
  const queryClient = useQueryClient();
  const rows = useListSiteProducts();
  const [search, setSearch] = useState("");
  const query = useDebounced(search.trim());

  const refresh = () => queryClient.invalidateQueries({ queryKey: getListSiteProductsQueryKey() });
  const failed = (failure: unknown) => {
    const fromServer = fieldErrors(failure);
    toast.error(Object.values(fromServer)[0] ?? t("admin.siteProducts.actionError"));
  };
  const update = useMutation({
    mutationFn: ({ product, changes }: { product: number; changes: PatchedSiteProductUpdate }) =>
      updateSiteProduct(product, changes),
    onSuccess: async () => {
      toast.success(t("admin.siteProducts.saved"));
      await refresh();
    },
    onError: failed,
  });
  // Moving a row renumbers the whole list 0, 1, 2... and sends only the places that change.
  const move = useMutation({
    mutationFn: async ({ list, from, to }: { list: OfficeSiteProduct[]; from: number; to: number }) => {
      const order = [...list];
      const [moved] = order.splice(from, 1);
      if (!moved) return;
      order.splice(to, 0, moved);
      for (const [position, row] of order.entries()) {
        if (row.position !== position) await updateSiteProduct(row.product, { position });
      }
    },
    onSettled: refresh,
    onError: failed,
  });

  const list = rows.data ?? [];
  const shownCount = list.filter((row) => row.is_published).length;
  const filtered = query ? list.filter((row) => matches(row, query)) : list;
  const busy = update.isPending || move.isPending;

  return (
    <>
      <PageHeader eyebrow={t("admin.groups.site")} title={t("admin.siteProducts.title")}>
        <a
          href={SITE_URL}
          target="_blank"
          rel="noreferrer"
          className="text-[0.9rem] font-semibold text-sea hover:underline"
        >
          {t("admin.siteProducts.openSite")} ↗
        </a>
      </PageHeader>

      <p className="text-ink-2">{canEdit ? t("admin.siteProducts.intro") : t("admin.siteProducts.readOnly")}</p>
      <p className="text-[0.85rem] text-ink-2">{t("admin.siteProducts.photoHint")}</p>

      {rows.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : rows.isError ? (
        <p role="alert" className="text-bad">
          {t("common.serverUnreachable")}
        </p>
      ) : list.length === 0 ? (
        <EmptyState illustration="mix" title={t("admin.siteProducts.empty")}>
          {t("admin.siteProducts.emptyBody")}
        </EmptyState>
      ) : (
        <>
          <Card className="filter-bar flex flex-wrap items-center gap-3 p-3">
            <Input
              type="search"
              aria-label={t("admin.siteProducts.search")}
              placeholder={t("admin.siteProducts.search")}
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              className="min-w-52 flex-[2_1_14rem]"
            />
            <span className="ms-auto text-[0.85rem] text-ink-2" aria-live="polite">
              {t("admin.siteProducts.shownOn", { shown: shownCount, count: list.length })}
            </span>
          </Card>
          {filtered.length === 0 ? (
            <p className="text-ink-2">{t("admin.siteProducts.noMatch")}</p>
          ) : (
            <Card className="p-2">
              <Table>
                <thead>
                  <tr>
                    <Th>{t("admin.siteProducts.columns.photo")}</Th>
                    <Th>{t("admin.siteProducts.columns.product")}</Th>
                    <Th>{t("admin.siteProducts.columns.webPrice")}</Th>
                    <Th className="max-[1000px]:hidden">{t("admin.siteProducts.columns.description")}</Th>
                    <Th>{t("admin.siteProducts.columns.status")}</Th>
                    {canEdit && <Th>{t("admin.siteProducts.columns.actions")}</Th>}
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((row) => {
                    const index = list.indexOf(row);
                    return (
                      <SiteProductRow
                        // A new key once saved, so the fields start again from what the server kept.
                        key={`${row.product}-${row.web_price ?? ""}-${row.description}-${row.is_published}`}
                        row={row}
                        canEdit={canEdit}
                        // Ordering works on the whole list: off while a search narrows it.
                        canMove={!query}
                        busy={busy}
                        first={index === 0}
                        last={index === list.length - 1}
                        onSave={(changes) => update.mutate({ product: row.product, changes })}
                        onMove={(step) => move.mutate({ list, from: index, to: index + step })}
                      />
                    );
                  })}
                </tbody>
              </Table>
            </Card>
          )}
        </>
      )}
    </>
  );
}

function Photo({ row }: { row: OfficeSiteProduct }) {
  const { t } = useTranslation();
  if (row.photo_url) {
    return <img src={row.photo_url} alt="" className="size-14 rounded-control object-cover" loading="lazy" />;
  }
  return (
    <div
      className="grid size-14 place-items-center rounded-control bg-gradient-to-br from-tile-a to-tile-b"
      title={t("admin.siteProducts.noPhoto")}
    >
      {isIllustration(row.illustration) && <Illustration name={row.illustration} className="w-12" />}
    </div>
  );
}

function SiteProductRow({
  row,
  canEdit,
  canMove,
  busy,
  first,
  last,
  onSave,
  onMove,
}: {
  row: OfficeSiteProduct;
  canEdit: boolean;
  canMove: boolean;
  busy: boolean;
  first: boolean;
  last: boolean;
  onSave: (changes: PatchedSiteProductUpdate) => void;
  onMove: (step: -1 | 1) => void;
}) {
  const { t } = useTranslation();
  const [price, setPrice] = useState(row.web_price ?? "");
  const [description, setDescription] = useState(row.description);
  const parsed = parseWebPrice(price);
  const priceChanged = parsed !== undefined && parsed !== row.web_price;
  const descriptionChanged = description.trim() !== row.description;
  const dirty = priceChanged || descriptionChanged;
  const save = () => {
    if (!dirty || parsed === undefined) return;
    onSave({
      ...(priceChanged ? { web_price: parsed } : {}),
      ...(descriptionChanged ? { description: description.trim() } : {}),
    });
  };

  return (
    <tr className={row.is_published ? undefined : "opacity-60"}>
      <Td className="w-16">
        <Photo row={row} />
      </Td>
      <Td>
        <div className="font-semibold">{row.product_name}</div>
        <div className="text-[0.8rem] text-ink-2">
          <span className="num">{row.product_reference}</span> · {row.category_name}
        </div>
      </Td>
      <Td className="min-w-40">
        {canEdit ? (
          <MoneyInput
            inputMode="decimal"
            aria-label={`${t("admin.siteProducts.webPrice")} · ${row.product_name}`}
            placeholder={t("admin.siteProducts.onRequest")}
            aria-invalid={parsed === undefined ? true : undefined}
            value={price}
            onChange={(event) => setPrice(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") save();
            }}
            className="num w-32"
          />
        ) : (
          <span className="num">{row.web_price ? formatMoney(row.web_price) : t("admin.siteProducts.onRequest")}</span>
        )}
        {row.day_price && (
          <div className="mt-1 text-[0.75rem] text-ink-2">
            {t("admin.siteProducts.dayPrice", { price: formatMoney(row.day_price) })}
          </div>
        )}
      </Td>
      <Td className="max-[1000px]:hidden">
        {canEdit ? (
          <Input
            aria-label={`${t("admin.siteProducts.description")} · ${row.product_name}`}
            placeholder={t("admin.siteProducts.descriptionHint")}
            maxLength={300}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") save();
            }}
            className="min-w-56"
          />
        ) : (
          row.description || "—"
        )}
      </Td>
      <Td>
        <Pill tone={row.is_published ? "good" : "neutral"}>
          {row.is_published ? t("admin.siteProducts.published") : t("admin.siteProducts.hidden")}
        </Pill>
      </Td>
      {canEdit && (
        <Td>
          <div className="flex flex-wrap items-center gap-1.5">
            <Button variant="primary" disabled={!dirty || parsed === undefined || busy} onClick={save}>
              {t("admin.siteProducts.save")}
            </Button>
            <Button disabled={busy} onClick={() => onSave({ is_published: !row.is_published })}>
              {row.is_published ? t("admin.siteProducts.hide") : t("admin.siteProducts.show")}
            </Button>
            {canMove && (
              <>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={t("admin.siteProducts.up")}
                  title={t("admin.siteProducts.up")}
                  disabled={first || busy}
                  onClick={() => onMove(-1)}
                >
                  ↑
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={t("admin.siteProducts.down")}
                  title={t("admin.siteProducts.down")}
                  disabled={last || busy}
                  onClick={() => onMove(1)}
                >
                  ↓
                </Button>
              </>
            )}
          </div>
        </Td>
      )}
    </tr>
  );
}
