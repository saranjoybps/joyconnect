"use client";

import { BrandLogo } from "@/components/ui/BrandLogo";
import { Badge, Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { CARD_BADGE, cardState, type Connection, type Connector } from "@/lib/connections";

type Props = {
  connector: Connector;
  connections: Connection[];
  /** Opens the step-by-step dialog for this app. */
  onOpen: (connector: Connector) => void;
};

/** One app in the integrations grid: logo, status, what it does, and the one button that matches its state. */
export function ConnectionCard({ connector, connections, onOpen }: Props) {
  const state = cardState(connector, connections);
  const badge = CARD_BADGE[state];
  const headingId = `conn-${connector.id}`;
  const action =
    state === "not_set_up" ? "Set up"
      : state === "ready" ? "Connect"
        : state === "connected" ? "Manage" : "Reconnect";
  const accounts = connections.length;

  return (
    <Card className="flex h-full flex-col gap-4 p-5 transition-colors hover:border-line-strong">
      <article aria-labelledby={headingId} className="flex flex-1 flex-col gap-4">
        <div className="flex items-start justify-between gap-3">
          <span className="flex size-11 items-center justify-center rounded-xl border border-line bg-surface">
            <BrandLogo id={connector.id} name={connector.name} size={24} />
          </span>
          <Badge tone={badge.tone}>{badge.text}</Badge>
        </div>
        <div className="min-w-0 flex-1">
          <h2 id={headingId} className="font-medium">{connector.name}</h2>
          <p className="mt-1 line-clamp-3 text-sm text-muted">{connector.description}</p>
          {accounts > 0 && (
            <p className="mt-2 text-xs text-muted">
              {accounts} {accounts === 1 ? "account" : "accounts"}
              {connections[0].account_label ? ` · ${connections[0].account_label}` : ""}
            </p>
          )}
        </div>
        <Button variant={state === "connected" ? "secondary" : "primary"} className="w-full"
          onClick={() => onOpen(connector)} aria-label={`${action} ${connector.name}`}>
          {action}
        </Button>
      </article>
    </Card>
  );
}
