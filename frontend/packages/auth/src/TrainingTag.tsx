import { useTranslation } from "@frutti/i18n";

import { useInstance } from "./instance";

/**
 * The small "Formation" tag of the training copy, on every screen and the login screen. Never printed: the papers
 * look exactly like the real ones (owner's choice, D-290).
 */
export function TrainingTag() {
  const { t } = useTranslation();
  const instance = useInstance();
  if (!instance?.training) return null;
  return (
    <div
      role="status"
      className="pointer-events-none fixed top-1 left-1/2 z-50 -translate-x-1/2 rounded-full border border-warn bg-warn-soft px-3 py-0.5 text-[0.72rem] font-bold tracking-wide text-warn uppercase shadow print:hidden"
    >
      {t("auth.trainingTag")}
    </div>
  );
}
