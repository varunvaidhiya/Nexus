import Link from "next/link";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const pillars = [
  {
    title: "One memory",
    description:
      "Ingests your AI activity from coding agents, web chats, and exports into a single private store.",
  },
  {
    title: "Any provider",
    description:
      "Chat with Anthropic, OpenAI, Gemini, DeepSeek, and more using your own encrypted keys.",
  },
  {
    title: "Context handoff",
    description:
      "Move work to any tool with a portable context package, or serve live memory over MCP.",
  },
  {
    title: "Daily direction",
    description:
      "Ranked recommendations, loose-end detection, goals, and weekly reviews.",
  },
] as const;

export default function Home() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-10 px-6 py-24 font-sans">
      <main className="flex w-full max-w-3xl flex-col items-center gap-10 text-center">
        <div className="flex flex-col gap-4">
          <h1 className="text-4xl font-semibold tracking-tight">Nexus</h1>
          <p className="text-muted-foreground text-lg leading-8">
            Personal AI control tower. Self-hosted, single-user, private by
            default.
          </p>
          <div className="flex justify-center gap-2">
            <Button render={<Link href="/chat" />}>Open chat</Button>
            <Button variant="outline" render={<Link href="/today" />}>
              Today
            </Button>
            <Button variant="outline" render={<Link href="/settings" />}>
              Settings
            </Button>
          </div>
        </div>
        <div className="grid w-full gap-4 sm:grid-cols-2">
          {pillars.map((pillar) => (
            <Card key={pillar.title} className="text-left">
              <CardHeader>
                <CardTitle>{pillar.title}</CardTitle>
                <CardDescription>{pillar.description}</CardDescription>
              </CardHeader>
              <CardContent />
            </Card>
          ))}
        </div>
      </main>
    </div>
  );
}
