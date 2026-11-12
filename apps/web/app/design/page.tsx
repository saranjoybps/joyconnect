import { notFound } from "next/navigation";
import { MinPreview } from "@/components/min/MinPreview";

export const metadata = { title: "Design preview · Connect" };

// Development only: a visual reference for the minimal design. Not shipped in production builds.
export default function DesignPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return <MinPreview />;
}
