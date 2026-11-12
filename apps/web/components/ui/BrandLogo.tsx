import {
  siAirtable, siAsana, siGithub, siGmail, siGooglecalendar, siGoogledocs, siGoogledrive, siGoogleforms,
  siGooglemeet, siGooglesheets, siGoogleslides, siGoogletasks, siLinear, siNotion, siStripe, siTrello,
} from "simple-icons";

/**
 * Official brand marks from the Simple Icons package (CC0 data; the marks stay the property of their owners).
 * Used only to identify the app in a connector's own card or mode chip, rendered monochrome in the text colour.
 * Slack and Google Contacts are not in Simple Icons, so they fall back to a neutral monogram (no recreated logo).
 */
const ICONS: Record<string, { path: string; title: string }> = {
  airtable: siAirtable, asana: siAsana, github: siGithub, gmail: siGmail,
  google_calendar: siGooglecalendar, google_docs: siGoogledocs, google_drive: siGoogledrive,
  google_forms: siGoogleforms, google_meet: siGooglemeet, google_sheets: siGooglesheets,
  google_slides: siGoogleslides, google_tasks: siGoogletasks, linear: siLinear, notion: siNotion,
  stripe: siStripe, trello: siTrello,
};

export function hasBrandIcon(id: string): boolean {
  return id in ICONS;
}

export function BrandLogo({ id, name, size = 20, className = "" }: { id: string; name?: string; size?: number; className?: string }) {
  const icon = ICONS[id];
  if (icon) {
    return (
      <svg role="img" aria-label={`${name ?? icon.title} logo`} viewBox="0 0 24 24" width={size} height={size}
        fill="currentColor" className={`shrink-0 ${className}`}>
        <path d={icon.path} />
      </svg>
    );
  }
  const letter = (name ?? id).trim().charAt(0).toUpperCase() || "?";
  return (
    <span aria-hidden data-testid="brand-fallback" style={{ width: size, height: size, fontSize: size * 0.6 }}
      className={`inline-flex shrink-0 items-center justify-center rounded-md border border-current font-semibold leading-none ${className}`}>
      {letter}
    </span>
  );
}
