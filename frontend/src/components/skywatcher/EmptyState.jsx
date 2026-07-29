import React from "react";
import { Inbox } from "lucide-react";
import { FederationEmptyState } from "@pr-federation/react";

// Delegates to the shared federation empty state (@pr-federation/react) so
// "no records" reads identically across the federation. The dashed-card
// container is kept here because this renders as a self-contained card, not a
// full-height panel. The `icon` prop stays a component so existing call sites
// are unchanged; it's instantiated here and handed to the package as a node.
export default function EmptyState({ icon: Icon = Inbox, title = "No records", message }) {
  return (
    <FederationEmptyState
      className="rounded-lg border border-dashed border-border bg-card/40"
      icon={<Icon className="h-5 w-5" />}
      title={title}
      description={message}
    />
  );
}