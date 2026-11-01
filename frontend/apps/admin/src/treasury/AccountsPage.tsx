import {
  type TreasuryAccount,
  type TreasuryAccountWrite,
  createCashCount,
  createTreasuryAccount,
  updateTreasuryAccount,
  useListBanks,
  useListTreasuryAccounts,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatMoney, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  Field,
  Input,
  PageHeader,
  Pill,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Table,
  Td,
  Th,
  toast,
} from "@frutti/ui";
import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useId, useState } from "react";
import { useOutletContext } from "react-router";

import { fieldErrors } from "../lib/errors";
import { canCollect } from "../payments/shared";
import { TresorerieRibbon } from "./TresorerieRibbon";

type Kind = "bank" | "cash";

/** "Agence bancaire" and "Caisse liquide" (P9-T08): the accounts that hold our money, one list per kind. A bank
 * account has its bank and its RIB; a cash box can be counted (arrêté de caisse). */
export function AccountsPage({ kind }: { kind: Kind }) {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const canWrite = canCollect(session);
  const accounts = useListTreasuryAccounts({ active_only: false });
  const rows = (accounts.data ?? []).filter((one) => one.kind === kind);
  const [editing, setEditing] = useState<TreasuryAccount | "new" | null>(null);
  const [counting, setCounting] = useState<TreasuryAccount | null>(null);

  return (
    <>
      <TresorerieRibbon active={kind === "bank" ? "agences" : "caisses"} />
      <PageHeader eyebrow={t("admin.groups.finance")} title={t(`admin.treasury.accounts.${kind}.title`)}>
        {canWrite && (
          <Button variant="primary" onClick={() => setEditing("new")}>
            {t(`admin.treasury.accounts.${kind}.add`)}
          </Button>
        )}
      </PageHeader>
      <p className="text-ink-2">{t(`admin.treasury.accounts.${kind}.intro`)}</p>

      <Card className="p-2">
        {accounts.isPending ? (
          <p className="p-2 text-ink-2">{t("common.loading")}</p>
        ) : rows.length === 0 ? (
          <p className="p-2 text-ink-2">{t("admin.treasury.accounts.empty")}</p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.treasury.accounts.columns.name")}</Th>
                {kind === "bank" && <Th>{t("admin.treasury.accounts.columns.bank")}</Th>}
                {kind === "bank" && <Th>{t("admin.treasury.accounts.columns.rib")}</Th>}
                <Th numeric>{t("admin.treasury.accounts.columns.opening")}</Th>
                <Th numeric>{t("admin.treasury.accounts.columns.balance")}</Th>
                <Th>{t("admin.treasury.accounts.columns.state")}</Th>
                {canWrite && <Th>{null}</Th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <Td className="font-semibold">{row.name}</Td>
                  {kind === "bank" && <Td>{row.bank ? `${row.bank.code} · ${row.bank.name}` : "—"}</Td>}
                  {kind === "bank" && <Td className="num">{row.rib || "—"}</Td>}
                  <Td numeric className="num">
                    {formatMoney(row.opening_balance)}
                  </Td>
                  <Td numeric className="num font-semibold">
                    {formatMoney(row.balance)}
                  </Td>
                  <Td>
                    <Pill tone={row.is_active ? "good" : "neutral"}>
                      {row.is_active ? t("admin.treasury.accounts.active") : t("admin.treasury.accounts.inactive")}
                    </Pill>
                  </Td>
                  {canWrite && (
                    <Td className="text-end">
                      <div className="flex justify-end gap-1">
                        <Button variant="ghost" onClick={() => setEditing(row)}>
                          {t("admin.treasury.accounts.edit")}
                        </Button>
                        {kind === "cash" && (
                          <Button variant="ghost" onClick={() => setCounting(row)}>
                            {t("admin.treasury.accounts.count")}
                          </Button>
                        )}
                      </div>
                    </Td>
                  )}
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      {editing && (
        <AccountDialog kind={kind} account={editing === "new" ? null : editing} onClose={() => setEditing(null)} />
      )}
      {counting && <CashCountDialog account={counting} onClose={() => setCounting(null)} />}
    </>
  );
}

function AccountDialog({
  kind,
  account,
  onClose,
}: {
  kind: Kind;
  account: TreasuryAccount | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const id = useId();
  const banks = useListBanks();
  const [name, setName] = useState(account?.name ?? "");
  const [bank, setBank] = useState(account?.bank ? String(account.bank.id) : "");
  const [rib, setRib] = useState(account?.rib ?? "");
  const [opening, setOpening] = useState(account?.opening_balance ?? "0.000");
  const [openingOn, setOpeningOn] = useState(account?.opening_on ?? "");
  const [active, setActive] = useState(account ? (account.is_active ? "yes" : "no") : "yes");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setErrors({});
    const body: TreasuryAccountWrite = {
      kind,
      name: name.trim(),
      bank: kind === "bank" && bank ? Number(bank) : null,
      rib: kind === "bank" ? rib.trim() : "",
      opening_balance: opening.trim().replace(",", ".") || "0",
      opening_on: openingOn || null,
      is_active: active === "yes",
    };
    try {
      const saved = account ? await updateTreasuryAccount(account.id, body) : await createTreasuryAccount(body);
      toast.success(t("admin.treasury.accounts.saved", { name: saved.name }));
      await queryClient.invalidateQueries({
        predicate: (query) => String(query.queryKey[0]).startsWith("/api/v1/treasury"),
      });
      onClose();
    } catch (failure) {
      const found = fieldErrors(failure);
      setErrors(Object.keys(found).length > 0 ? found : { detail: t("admin.treasury.accounts.error") });
    } finally {
      setPending(false);
    }
  }

  const title = account
    ? t("admin.treasury.accounts.dialog.edit", { name: account.name })
    : t(`admin.treasury.accounts.${kind}.add`);

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <form onSubmit={submit} noValidate className="flex flex-col gap-3">
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{t("admin.treasury.accounts.dialog.body")}</DialogDescription>
          <Field label={t("admin.treasury.accounts.dialog.name")} htmlFor={`${id}-name`} error={errors.name}>
            <Input id={`${id}-name`} value={name} maxLength={120} onChange={(event) => setName(event.target.value)} />
          </Field>
          {kind === "bank" && (
            <>
              <Field label={t("admin.treasury.accounts.dialog.bank")} htmlFor={`${id}-bank`} error={errors.bank}>
                <Select value={bank} onValueChange={setBank}>
                  <SelectTrigger id={`${id}-bank`}>
                    <SelectValue placeholder={t("admin.treasury.lines.bankPlaceholder")} />
                  </SelectTrigger>
                  <SelectContent>
                    {(banks.data ?? []).map((one) => (
                      <SelectItem key={one.id} value={String(one.id)}>
                        {one.code} · {one.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label={t("admin.treasury.accounts.dialog.rib")} htmlFor={`${id}-rib`} error={errors.rib}>
                <Input
                  id={`${id}-rib`}
                  value={rib}
                  inputMode="numeric"
                  onChange={(event) => setRib(event.target.value)}
                />
              </Field>
            </>
          )}
          <Field
            label={t("admin.treasury.accounts.dialog.opening")}
            htmlFor={`${id}-opening`}
            error={errors.opening_balance}
          >
            <Input
              id={`${id}-opening`}
              value={opening}
              inputMode="decimal"
              onChange={(event) => setOpening(event.target.value)}
            />
          </Field>
          <Field
            label={t("admin.treasury.accounts.dialog.openingOn")}
            htmlFor={`${id}-opening-on`}
            error={errors.opening_on}
          >
            <Input
              id={`${id}-opening-on`}
              type="date"
              value={openingOn}
              onChange={(event) => setOpeningOn(event.target.value)}
            />
          </Field>
          {account && (
            <Field label={t("admin.treasury.accounts.dialog.state")} htmlFor={`${id}-active`} error={errors.is_active}>
              <Select value={active} onValueChange={setActive}>
                <SelectTrigger id={`${id}-active`}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="yes">{t("admin.treasury.accounts.active")}</SelectItem>
                  <SelectItem value="no">{t("admin.treasury.accounts.inactive")}</SelectItem>
                </SelectContent>
              </Select>
            </Field>
          )}
          {errors.detail && <p className="text-[0.85rem] font-semibold text-bad">{errors.detail}</p>}
          <DialogFooter>
            <Button variant="ghost" onClick={onClose}>
              {t("admin.treasury.accounts.cancel")}
            </Button>
            <Button type="submit" variant="primary" disabled={pending}>
              {t("admin.treasury.accounts.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** The arrêté de caisse: the cash counted, against what the books expect; the gap is kept with its reason. */
function CashCountDialog({ account, onClose }: { account: TreasuryAccount; onClose: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const id = useId();
  const [counted, setCounted] = useState(account.balance);
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setErrors({});
    try {
      const count = await createCashCount({
        account: account.id,
        counted: counted.trim().replace(",", "."),
        reason: reason.trim(),
      });
      toast.success(t("admin.treasury.accounts.count_done", { gap: formatMoney(count.gap) }));
      await queryClient.invalidateQueries({
        predicate: (query) => String(query.queryKey[0]).startsWith("/api/v1/treasury"),
      });
      onClose();
    } catch (failure) {
      const found = fieldErrors(failure);
      setErrors(Object.keys(found).length > 0 ? found : { detail: t("admin.treasury.accounts.error") });
    } finally {
      setPending(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <form onSubmit={submit} noValidate className="flex flex-col gap-3">
          <DialogTitle>{t("admin.treasury.accounts.count_title", { name: account.name })}</DialogTitle>
          <DialogDescription>
            {t("admin.treasury.accounts.count_expected", { amount: formatMoney(account.balance) })}
          </DialogDescription>
          <Field label={t("admin.treasury.accounts.count_counted")} htmlFor={`${id}-counted`} error={errors.counted}>
            <Input
              id={`${id}-counted`}
              value={counted}
              inputMode="decimal"
              onChange={(event) => setCounted(event.target.value)}
            />
          </Field>
          <Field label={t("admin.treasury.accounts.count_reason")} htmlFor={`${id}-reason`} error={errors.reason}>
            <Input
              id={`${id}-reason`}
              value={reason}
              maxLength={255}
              onChange={(event) => setReason(event.target.value)}
            />
          </Field>
          {errors.detail && <p className="text-[0.85rem] font-semibold text-bad">{errors.detail}</p>}
          <DialogFooter>
            <Button variant="ghost" onClick={onClose}>
              {t("admin.treasury.accounts.cancel")}
            </Button>
            <Button type="submit" variant="primary" disabled={pending}>
              {t("admin.treasury.accounts.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
