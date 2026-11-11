import { Suspense } from "react";
import { ConnectionsView } from "@/components/ConnectionsView";

export const metadata = { title: "Connections · Connect" };

export default function ConnectionsPage() {
  return (
    <Suspense>
      <ConnectionsView />
    </Suspense>
  );
}
