import type { Session } from "@frutti/auth";
import { fieldErrors } from "../lib/errors";
import { removeOrganizationLogo, uploadOrganizationLogo, useGetFinanceSettings } from "@frutti/api";
import { useTranslation } from "@frutti/i18n";
import { Button, Card, CardTitle, Icon, PageHeader, toast } from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";
import { Link, useOutletContext } from "react-router";

function LogoCard({ session }: { session: Session }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const organization = session.organization;
  const refreshSession = () => queryClient.invalidateQueries({ queryKey: ["session"] });

  const upload = useMutation({
    mutationFn: (photo: File) => uploadOrganizationLogo(organization.id, { photo }),
    onSuccess: async () => {
      toast.success(t("admin.settings.logoSaved"));
      await refreshSession();
    },
    onError: (failure) => toast.error(fieldErrors(failure).logo ?? t("admin.settings.logoError")),
  });

  const remove = useMutation({
    mutationFn: () => removeOrganizationLogo(organization.id),
    onSuccess: async () => {
      toast.success(t("admin.settings.logoRemoved"));
      await refreshSession();
    },
    onError: () => toast.error(t("admin.settings.logoError")),
  });

  return (
    <Card>
      <CardTitle>{t("admin.settings.logo")}</CardTitle>
      <div className="flex flex-wrap items-center gap-5">
        <div className="grid size-[120px] flex-none place-items-center overflow-hidden rounded-card border border-line bg-surface-2">
          {organization.logo_url ? (
            <img src={organization.logo_url} alt="" className="size-full object-contain" />
          ) : (
            <span className="px-3 text-center text-[0.85rem] text-ink-2">{t("admin.settings.logoEmpty")}</span>
          )}
        </div>
        <div className="flex flex-col items-start gap-2">
          <p className="text-[0.82rem] text-ink-2">{t("admin.settings.logoHint")}</p>
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" disabled={upload.isPending} onClick={() => fileInput.current?.click()}>
              <Icon name="plus" />
              {t("admin.settings.logoChange")}
            </Button>
            {organization.logo_url && (
              <Button variant="ghost" disabled={remove.isPending} onClick={() => remove.mutate()}>
                {t("admin.settings.logoRemove")}
              </Button>
            )}
          </div>
          <input
            ref={fileInput}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            className="sr-only"
            onChange={(event) => {
              const photo = event.target.files?.[0];
              event.target.value = "";
              if (photo) upload.mutate(photo);
            }}
          />
        </div>
      </div>
    </Card>
  );
}

function LegalCard() {
  const { t } = useTranslation();
  const query = useGetFinanceSettings();
  const seller = query.data?.in_force;
  const rows = seller
    ? [
        [t("admin.financeSettings.legalName"), seller.legal_name],
        [t("admin.financeSettings.address"), seller.address],
        [t("admin.financeSettings.phone"), seller.phone],
        [t("admin.financeSettings.taxId"), seller.tax_id],
        [t("admin.financeSettings.tradeRegister"), seller.trade_register],
      ].filter(([, value]) => value)
    : [];

  return (
    <Card>
      <CardTitle>{t("admin.settings.legal")}</CardTitle>
      <p className="mb-3 text-[0.85rem] text-ink-2">{t("admin.settings.legalHint")}</p>
      {rows.length > 0 ? (
        <dl className="mb-4 grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-[0.92rem]">
          {rows.map(([label, value]) => (
            <div key={label} className="contents">
              <dt className="text-ink-2">{label}</dt>
              <dd className="font-semibold">{value}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="mb-4 text-ink-2">{t("admin.settings.legalEmpty")}</p>
      )}
      <Link to="/factures/parametres" className="text-[0.9rem] font-semibold text-sea hover:underline">
        {t("admin.settings.legalEdit")}
      </Link>
    </Card>
  );
}

function UsersCard() {
  const { t } = useTranslation();
  return (
    <Card>
      <CardTitle>{t("admin.settings.users")}</CardTitle>
      <p className="mb-4 text-[0.85rem] text-ink-2">{t("admin.settings.usersHint")}</p>
      <Link to="/parametres/utilisateurs" className="text-[0.9rem] font-semibold text-sea hover:underline">
        {t("admin.settings.usersOpen")}
      </Link>
    </Card>
  );
}

function BanksCard() {
  const { t } = useTranslation();
  return (
    <Card>
      <CardTitle>{t("admin.treasury.banks.title")}</CardTitle>
      <p className="mb-4 text-[0.85rem] text-ink-2">{t("admin.treasury.banks.settingsHint")}</p>
      <Link to="/tresorerie/banques" className="text-[0.9rem] font-semibold text-sea hover:underline">
        {t("admin.treasury.banks.open")}
      </Link>
    </Card>
  );
}

function NumberingCard() {
  const { t } = useTranslation();
  return (
    <Card>
      <CardTitle>{t("admin.settings.numbering")}</CardTitle>
      <p className="mb-4 text-[0.85rem] text-ink-2">{t("admin.settings.numberingHint")}</p>
      <Link to="/parametres/numerotation" className="text-[0.9rem] font-semibold text-sea hover:underline">
        {t("admin.settings.numberingOpen")}
      </Link>
    </Card>
  );
}

/** "Paramètres": the company's logo and legal identity, and the accounts that log in. Owner only. */
export function SettingsPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  return (
    <>
      <PageHeader eyebrow={t("admin.settings.company")} title={t("admin.settings.title")} />
      <p className="text-ink-2">{t("admin.settings.intro")}</p>
      <div className="grid grid-cols-2 items-start gap-4 max-[900px]:grid-cols-1">
        <LogoCard session={session} />
        <LegalCard />
        <UsersCard />
        <BanksCard />
        <NumberingCard />
      </div>
    </>
  );
}
