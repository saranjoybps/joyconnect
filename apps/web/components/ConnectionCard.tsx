"use client";

import { BrandLogo } from "@/components/ui/BrandLogo";
import { Button } from "@/components/ui/Button";
import { CARD_BADGE, cardState, type Connection, type Connector } from "@/lib/connections";

type Props = {
  connector: Connector;
  connections: Connection[];
  /** Opens the step-by-step dialog for this app. */
  onOpen: (connector: Connector) => void;
};

/** A minimal rectangular card: the app's logo and name, and the one button that matches its state. */
export function ConnectionCard({ connector, connections, onOpen }: Props) {
  const state = cardState(connector, connections);
  const headingId = `conn-${connector.id}`;
  const action =
    state === "not_set_up" ? "Set up"
      : state === "ready" ? "Connect"
        : state === "connected" ? "Manage" : "Reconnect";

  return (
    <article aria-labelledby={headingId}
      className="flex h-16 items-center gap-3 rounded-xl border border-m-line bg-m-panel px-3.5 shadow-[var(--m-shadow)] transition-colors duration-150 hover:border-m-line-strong">
      <BrandLogo id={connector.id} name={connector.name} size={18} />
      <h2 id={headingId} className="min-w-0 flex-1 truncate text-[13px] font-medium">{connector.name}</h2>
      {/* The state stays available to screen readers; sighted users get it from the button label. */}
      <span className="sr-only">{CARD_BADGE[state].text}</span>
      <Button size="sm" variant={state === "connected" ? "secondary" : "primary"}
        onClick={() => onOpen(connector)} aria-label={`${action} ${connector.name}`}>
        {action}
      </Button>
    </article>
  );
}
