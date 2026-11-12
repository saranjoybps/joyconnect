import {
  siAirtable, siAsana, siGithub, siGmail, siGooglecalendar, siGoogledocs, siGoogledrive, siGoogleforms,
  siGooglemeet, siGooglesheets, siGoogleslides, siGoogletasks, siLinear, siNotion, siStripe, siTrello,
} from "simple-icons";

/**
 * Official brand marks from the Simple Icons package (CC0 data; the marks stay the property of their owners).
 * Used only to identify the app in its own card, dialog or mode chip.
 */
const ICONS: Record<string, { path: string; title: string; hex: string }> = {
  airtable: siAirtable, asana: siAsana, github: siGithub, gmail: siGmail,
  google_calendar: siGooglecalendar, google_docs: siGoogledocs, google_drive: siGoogledrive,
  google_forms: siGoogleforms, google_meet: siGooglemeet, google_sheets: siGooglesheets,
  google_slides: siGoogleslides, google_tasks: siGoogletasks, linear: siLinear, notion: siNotion,
  stripe: siStripe, trello: siTrello,
};

export function hasBrandIcon(id: string): boolean {
  return id in ICONS;
}

/**
 * A small glass tile with the app's mark in its official brand colour (Simple Icons hex). The tile is always a light
 * glass chip, so dark marks (GitHub, Notion) stay visible in the dark theme. Slack and Google Contacts are not in
 * Simple Icons: they get a gradient monogram, never a recreated logo.
 */
export function BrandLogo({ id, name, size = 20, className = "" }: { id: string; name?: string; size?: number; className?: string }) {
  const icon = ICONS[id];
  const box = Math.round(size * 1.7);
  const tile = `inline-flex shrink-0 items-center justify-center rounded-[28%] border border-white/70 bg-white/85 shadow-sm ${className}`;
  if (icon) {
    return (
      <span className={tile} style={{ width: box, height: box }}>
        <svg role="img" aria-label={`${name ?? icon.title} logo`} viewBox="0 0 24 24" width={size} height={size} fill={`#${icon.hex}`}>
          <path d={icon.path} />
        </svg>
      </span>
    );
  }
  const letter = (name ?? id).trim().charAt(0).toUpperCase() || "?";
  return (
    <span aria-hidden data-testid="brand-fallback" style={{ width: box, height: box, fontSize: size * 0.8 }}
      className={`btn-gradient inline-flex shrink-0 items-center justify-center rounded-[28%] font-semibold leading-none ${className}`}>
      {letter}
    </span>
  );
}

/** The bare full-colour mark (no tile), for placing inside a LogoTile. Null when the brand is not in Simple Icons. */
export function BrandMark({ id, name, size = 16 }: { id: string; name?: string; size?: number }) {
  const icon = ICONS[id];
  if (!icon) return null;
  return (
    <svg role="img" aria-label={`${name ?? icon.title} logo`} viewBox="0 0 24 24" width={size} height={size} fill={`#${icon.hex}`}>
      <path d={icon.path} />
    </svg>
  );
}
