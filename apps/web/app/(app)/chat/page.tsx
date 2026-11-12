import { Suspense } from "react";
import { ChatWindow } from "@/components/ChatWindow";

export const metadata = { title: "Chat · Connect" };

export default function ChatPage() {
  // ChatWindow reads ?c= (a runtime value), so it renders inside Suspense.
  return (
    <Suspense>
      <ChatWindow />
    </Suspense>
  );
}
