import { useListCategories, useListProducts } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  Dialog,
  EmptyState,
  Icon,
  Input,
  PageHeader,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  useUrlState,
} from "@frutti/ui";
import { keepPreviousData } from "@tanstack/react-query";
import { useState } from "react";
import { useOutletContext } from "react-router";

import { type Status, StatusFilter } from "../lib/StatusFilter";
import { useDebounced } from "../lib/useDebounced";
import { ProductCard } from "./ProductCard";
import { ProductDialog } from "./ProductDialog";

const ALL_CATEGORIES = "all";

export function ProductsPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  // The server refuses changes from other roles; this only avoids showing buttons that would fail.
  const canEdit = session.role === "owner" || session.role === "manager";
  const [search, setSearch] = useUrlState("q");
  const [category, setCategory] = useState(ALL_CATEGORIES);
  const [status, setStatus] = useState<Status>("active");
  // "new", the id of the product being edited, or null when the dialog is closed.
  const [open, setOpen] = useState<"new" | number | null>(null);
  const query = useDebounced(search.trim());

  const categories = useListCategories();
  const products = useListProducts(
    {
      status,
      ...(query ? { search: query } : {}),
      ...(category !== ALL_CATEGORIES ? { category: Number(category) } : {}),
    },
    { query: { placeholderData: keepPreviousData } },
  );
  const list = products.data ?? [];
  const filtering = query !== "" || category !== ALL_CATEGORIES || status !== "active";
  // Read from the list, so the dialog shows the new price as soon as it is saved.
  const editing = typeof open === "number" ? list.find((product) => product.id === open) : undefined;

  return (
    <>
      <PageHeader eyebrow={t("admin.groups.goods")} title={t("admin.products.title")}>
        {canEdit && (
          <Button variant="primary" onClick={() => setOpen("new")}>
            <Icon name="plus" />
            {t("admin.products.add")}
          </Button>
        )}
      </PageHeader>

      {!canEdit && <p className="text-ink-2">{t("admin.products.readOnly")}</p>}

      <Card className="filter-bar flex flex-wrap items-center gap-3 p-3">
        <Input
          type="search"
          aria-label={t("admin.products.search")}
          placeholder={t("admin.products.search")}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className="min-w-52 flex-[2_1_14rem]"
        />
        <div className="min-w-48 flex-[1_1_12rem]">
          <Select value={category} onValueChange={setCategory}>
            <SelectTrigger aria-label={t("admin.products.category")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_CATEGORIES}>{t("admin.products.allCategories")}</SelectItem>
              {categories.data?.map((item) => (
                <SelectItem key={item.id} value={String(item.id)}>
                  {item.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <StatusFilter
          value={status}
          onChange={setStatus}
          label={t("admin.products.show")}
          labels={{
            active: t("admin.products.status.active"),
            archived: t("admin.products.status.archived"),
            all: t("admin.products.status.all"),
          }}
        />
        <span className="ms-auto text-[0.85rem] text-ink-2" aria-live="polite">
          {products.data && t("admin.products.count", { count: list.length })}
        </span>
      </Card>

      {products.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : products.isError ? (
        <p role="alert" className="text-bad">
          {t("common.serverUnreachable")}
        </p>
      ) : list.length === 0 ? (
        filtering ? (
          <p className="text-ink-2">{t("admin.products.noMatch")}</p>
        ) : (
          <EmptyState illustration="shrimp" title={t("admin.products.empty")}>
            {t("admin.products.emptyBody")}
          </EmptyState>
        )
      ) : (
        <section className="grid grid-cols-[repeat(auto-fill,minmax(210px,1fr))] gap-4">
          {list.map((product) => (
            <ProductCard key={product.id} product={product} onOpen={canEdit ? () => setOpen(product.id) : undefined} />
          ))}
        </section>
      )}

      <Dialog open={open !== null} onOpenChange={(isOpen) => !isOpen && setOpen(null)}>
        {open === "new" && <ProductDialog onDone={() => setOpen(null)} />}
        {editing && <ProductDialog key={editing.id} product={editing} onDone={() => setOpen(null)} />}
      </Dialog>
    </>
  );
}
