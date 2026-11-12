import { PageContainer } from "@/components/ui/PageContainer";
import { SettingsView } from "@/components/SettingsView";

export const metadata = { title: "Settings · Connect" };

export default function SettingsPage() {
  return <PageContainer><SettingsView /></PageContainer>;
}
