import { useTranslation } from "@frutti/i18n";
import type { ReactNode } from "react";

import { Button } from "../components/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "../components/dialog";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onLogout: () => void;
  /** Said before leaving, e.g. the driver's actions still waiting to be sent. */
  warning?: ReactNode;
}

/** "Se déconnecter ?" with Annuler / Se déconnecter: a tap on the logout icon never logs out at once. */
export function LogoutDialog({ open, onOpenChange, onLogout, warning }: Props) {
  const { t } = useTranslation();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogTitle>{t("common.logoutTitle")}</DialogTitle>
        <DialogDescription>{warning ?? t("common.logoutBody")}</DialogDescription>
        <DialogFooter className="grid grid-cols-2">
          <DialogClose asChild>
            <Button size="lg">{t("common.cancel")}</Button>
          </DialogClose>
          <Button
            size="lg"
            variant="primary"
            onClick={() => {
              onOpenChange(false);
              onLogout();
            }}
          >
            {t("common.logout")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
