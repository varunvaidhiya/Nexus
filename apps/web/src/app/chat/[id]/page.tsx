"use client";

import { use } from "react";

import { ChatView } from "@/components/chat-view";

export default function ConversationPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return <ChatView key={id} conversationId={id} />;
}
