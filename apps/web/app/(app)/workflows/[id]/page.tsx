import { Suspense } from "react";
import { WorkflowEditor } from "@/components/canvas/WorkflowEditor";

export const metadata = { title: "Workflow · Connect" };

// `params` is runtime data, so it is read inside a Suspense boundary (Next 16 blocks routes that read it outside one).
async function Editor({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <WorkflowEditor id={id} />;
}

export default function WorkflowPage({ params }: { params: Promise<{ id: string }> }) {
  return (
    <Suspense fallback={<p className="text-sm text-neutral-600">Loading…</p>}>
      <Editor params={params} />
    </Suspense>
  );
}
