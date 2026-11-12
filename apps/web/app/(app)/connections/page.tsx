import { Suspense } from "react";
import { PageContainer } from "@/components/ui/PageContainer";
import { ConnectionsView } from "@/components/ConnectionsView";

export const metadata = { title: "Connections · Connect" };

export default function ConnectionsPage() {
  return (
    <PageContainer wide>
      <Suspense>
        <ConnectionsView />
      </Suspense>
    </PageContainer>
  );
}
