import { notFound } from "next/navigation";
import { DesignPreview } from "@/components/pro/DesignPreview";

export const metadata = { title: "Design preview · Connect" };

// Development only: a visual reference for the design tokens and components. Not shipped in production builds.
export default function DesignPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return <DesignPreview />;
}
