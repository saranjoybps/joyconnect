import { WorkflowEditor } from "@/components/canvas/WorkflowEditor";

export const metadata = { title: "Workflow · Connect" };

export default async function WorkflowPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <WorkflowEditor id={id} />;
}
