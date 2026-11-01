import { type Bank, createBank, updateBank, useListBanks } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  CardTitle,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  Field,
  Input,
  PageHeader,
  Pill,
  Table,
  Td,
  Th,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useId, useState } from "react";
import { useOutletContext } from "react-router";

import { fieldErrors } from "../lib/errors";
import { TresorerieRibbon } from "../treasury/TresorerieRibbon";

const canWrite = (session: Session) => session.role === "owner" || session.role === "manager";

/** The banks a cheque or a traite may be drawn on (D-197): the Tunisian banks come ready; the office adds,
 * renames or takes one off the lists. An effet already written keeps its bank. */
export function BanksPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const banks = useListBanks({ active_only: false });
  const [editing, setEditing] = useState<Bank | "new" | null>(null);
  const queryClient = useQueryClient();
  const refresh = () =>
    queryClient.invalidateQueries({ predicate: (query) => String(query.queryKey[0]).startsWith("/api/v1/treasury") });

  const toggle = useMutation({
    mutationFn: (bank: Bank) => updateBank(bank.id, { code: bank.code, name: bank.name, is_active: !bank.is_active }),
    onSuccess: async (bank) => {
      toast.success(
        bank.is_active
          ? t("admin.treasury.banks.restored", { code: bank.code })
          : t("admin.treasury.banks.hidden", { code: bank.code }),
      );
      await refresh();
    },
    onError: () => toast.error(t("admin.treasury.banks.error")),
  });

  return (
    <>
      <TresorerieRibbon active="banque" />
      <PageHeader eyebrow={t("admin.groups.finance")} title={t("admin.treasury.banks.title")}>
        {canWrite(session) && (
          <Button variant="primary" onClick={() => setEditing("new")}>
            {t("admin.treasury.banks.add")}
          </Button>
        )}
      </PageHeader>
      <p className="text-ink-2">{t("admin.treasury.banks.intro")}</p>
      <Card>
        <CardTitle>{t("admin.treasury.banks.list")}</CardTitle>
        {banks.isPending ? (
          <p className="text-ink-2">{t("common.loading")}</p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.treasury.banks.code")}</Th>
                <Th>{t("admin.treasury.banks.name")}</Th>
                <Th>{t("admin.treasury.banks.state")}</Th>
                {canWrite(session) && <Th />}
              </tr>
            </thead>
            <tbody>
              {(banks.data ?? []).map((bank) => (
                <tr key={bank.id}>
                  <Td className="num font-semibold">{bank.code}</Td>
                  <Td>{bank.name}</Td>
                  <Td>
                    <Pill tone={bank.is_active ? "good" : "neutral"}>
                      {bank.is_active ? t("admin.treasury.banks.active") : t("admin.treasury.banks.inactive")}
                    </Pill>
                  </Td>
                  {canWrite(session) && (
                    <Td className="whitespace-nowrap text-end">
                      <Button
                        variant="ghost"
                        aria-label={t("admin.treasury.banks.renameOne", { code: bank.code })}
                        onClick={() => setEditing(bank)}
                      >
                        {t("admin.treasury.banks.rename")}
                      </Button>
                      <Button variant="ghost" disabled={toggle.isPending} onClick={() => toggle.mutate(bank)}>
                        {bank.is_active ? t("admin.treasury.banks.hide") : t("admin.treasury.banks.restore")}
                      </Button>
                    </Td>
                  )}
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      {editing !== null && (
        <BankDialog
          bank={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={async () => {
            setEditing(null);
            await refresh();
          }}
        />
      )}
    </>
  );
}

function BankDialog({
  bank,
  onClose,
  onSaved,
}: {
  bank: Bank | null;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const formId = useId();
  const [code, setCode] = useState(bank?.code ?? "");
  const [name, setName] = useState(bank?.name ?? "");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: () =>
      bank ? updateBank(bank.id, { code, name, is_active: bank.is_active }) : createBank({ code, name }),
    onSuccess: async (saved) => {
      toast.success(t("admin.treasury.banks.saved", { code: saved.code }));
      await onSaved();
    },
    onError: (failure) => {
      const found = fieldErrors(failure);
      setErrors(Object.keys(found).length > 0 ? found : { detail: t("admin.treasury.banks.error") });
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <form onSubmit={submit} noValidate className="flex flex-col gap-4">
          <DialogTitle>
            {bank ? t("admin.treasury.banks.renameTitle", { code: bank.code }) : t("admin.treasury.banks.add")}
          </DialogTitle>
          <DialogDescription>{t("admin.treasury.banks.dialogBody")}</DialogDescription>
          <div className="grid grid-cols-[1fr_2fr] gap-3 max-[520px]:grid-cols-1">
            <Field label={t("admin.treasury.banks.code")} htmlFor={`${formId}-code`} error={errors.code}>
              <Input
                id={`${formId}-code`}
                value={code}
                maxLength={20}
                onChange={(event) => setCode(event.target.value)}
                autoComplete="off"
              />
            </Field>
            <Field label={t("admin.treasury.banks.name")} htmlFor={`${formId}-name`} error={errors.name}>
              <Input
                id={`${formId}-name`}
                value={name}
                maxLength={100}
                onChange={(event) => setName(event.target.value)}
                autoComplete="off"
              />
            </Field>
          </div>
          {errors.detail && (
            <p role="alert" className="text-[0.85rem] text-bad">
              {errors.detail}
            </p>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={onClose}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" variant="primary" disabled={save.isPending}>
              {t("admin.treasury.banks.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
