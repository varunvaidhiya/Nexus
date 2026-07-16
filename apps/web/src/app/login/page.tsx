"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, apiFetch, setToken } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [token, setTokenInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function connect(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setToken(token.trim());
      await apiFetch("/providers");
      router.push("/settings");
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? "Token rejected — check NEXUS_AUTH_TOKEN on the server."
          : err instanceof Error
            ? err.message
            : "Could not reach the API.",
      );
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-1 items-center justify-center px-6 py-24">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Connect to Nexus</CardTitle>
          <CardDescription>
            Paste the access token you set as{" "}
            <code className="font-mono">NEXUS_AUTH_TOKEN</code> on the server.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={connect} className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="token">Access token</Label>
              <Input
                id="token"
                type="password"
                value={token}
                onChange={(e) => setTokenInput(e.target.value)}
                required
                autoFocus
              />
            </div>
            {error && <p className="text-destructive text-sm">{error}</p>}
            <Button type="submit" disabled={busy || token.trim().length === 0}>
              {busy ? "Connecting…" : "Connect"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
