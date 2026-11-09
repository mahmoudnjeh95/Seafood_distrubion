import type { AccessSection, LevelsEnum } from "@frutti/api";
import { useTranslation } from "@frutti/i18n";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@frutti/ui";

export type Level = LevelsEnum;
export type Levels = Partial<Record<string, Level>>;

const INHERIT = "inherit";

interface Props {
  sections: AccessSection[];
  /** The levels chosen here. A section left out is "none" for a role, or follows the role for a person. */
  value: Levels;
  onChange: (next: Levels) => void;
  /** A person's role levels: each section then offers "Comme le rôle (…)" (D-306). */
  inherited?: Record<string, Level>;
  disabled?: boolean;
}

/** One row per section of the access matrix, grouped as the menu, with the level of each (D-306). */
export function AccessMatrix({ sections, value, onChange, inherited, disabled }: Props) {
  const { t } = useTranslation();
  const groups = sections.reduce<{ group: string; rows: AccessSection[] }[]>((found, section) => {
    const last = found.at(-1);
    if (last && last.group === section.group) last.rows.push(section);
    else found.push({ group: section.group, rows: [section] });
    return found;
  }, []);
  const levelText = (level: Level) => t(`admin.access.levels.${level}`);
  const sectionText = (section: AccessSection) =>
    t(`admin.access.sections.${section.key}`, { defaultValue: section.title });

  const set = (key: string, next: string) => {
    const copy = { ...value };
    if (next === INHERIT) delete copy[key];
    else copy[key] = next as Level;
    onChange(copy);
  };

  return (
    <div className="flex flex-col gap-4">
      {groups.map(({ group, rows }) => (
        <fieldset key={group} className="flex flex-col gap-1.5">
          <legend className="mb-1 text-[0.75rem] font-bold uppercase tracking-wide text-ink-2">{group}</legend>
          {rows.map((section) => {
            const own = value[section.key];
            const current = inherited ? (own ?? INHERIT) : (own ?? "none");
            return (
              <div
                key={section.key}
                className="grid grid-cols-[1fr_minmax(150px,200px)] items-center gap-3 border-b border-line py-1.5 last:border-b-0 max-[520px]:grid-cols-1 max-[520px]:gap-1"
              >
                <span className={own && inherited ? "font-semibold" : undefined}>{sectionText(section)}</span>
                <Select value={current} onValueChange={(next) => set(section.key, next)} disabled={disabled}>
                  <SelectTrigger aria-label={sectionText(section)}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {inherited && (
                      <SelectItem value={INHERIT}>
                        {t("admin.users.followRole", { level: levelText(inherited[section.key] ?? "none") })}
                      </SelectItem>
                    )}
                    {section.levels.map((level) => (
                      <SelectItem key={level} value={level}>
                        {levelText(level)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            );
          })}
        </fieldset>
      ))}
      <ul className="flex flex-col gap-0.5 text-[0.8rem] text-ink-2">
        {(["read", "write", "full"] as const).map((level) => (
          <li key={level}>
            <strong>{levelText(level)}</strong> : {t(`admin.access.levelHints.${level}`)}
          </li>
        ))}
        <li>{t("admin.access.lookupsNote")}</li>
      </ul>
    </div>
  );
}
