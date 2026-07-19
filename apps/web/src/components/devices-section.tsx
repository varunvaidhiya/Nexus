"use client";

import { useCallback, useEffect, useState } from "react";

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
import { apiFetch } from "@/lib/api";

interface Device {
  id: string;
  name: string;
  created_at: string;
  last_used_at: string | null;
  revoked: boolean;
}

interface DeviceCreated extends Device {
  token: string;
}

export function DevicesSection() {
  const [devices, setDevices] = useState<Device[] | null>(null);
  const [name, setName] = useState("");
  const [created, setCreated] = useState<DeviceCreated | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setDevices(await apiFetch<Device[]>("/devices"));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load devices.");
    }
  }, []);

  useEffect(() => {
    const load = setTimeout(() => void refresh(), 0);
    return () => clearTimeout(load);
  }, [refresh]);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setCreated(
        await apiFetch<DeviceCreated>("/devices", {
          method: "POST",
          body: JSON.stringify({ name: name.trim() }),
        }),
      );
      setName("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create device.");
    } finally {
      setBusy(false);
    }
  }

  async function revoke(id: string) {
    await apiFetch(`/devices/${id}`, { method: "DELETE" });
    await refresh();
  }

  return (
    <section className="flex flex-col gap-4" data-testid="devices-section">
      <div>
        <h2 className="text-lg font-medium">Devices</h2>
        <p className="text-muted-foreground text-sm">
          Tokens for companion tools: the agent and extension push to /ingest,
          and MCP clients (Claude Code, Cursor) read memory via /mcp. They never
          unlock the main app or your provider keys.
        </p>
      </div>

      {error && <p className="text-destructive text-sm">{error}</p>}

      <Card>
        <CardHeader>
          <CardTitle>Create a device token</CardTitle>
          <CardDescription>
            The token is shown once, right here — copy it into nexus-agent.toml
            or the extension options.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <form onSubmit={create} className="flex items-end gap-4">
            <div className="flex flex-1 flex-col gap-2">
              <Label htmlFor="deviceName">Name</Label>
              <Input
                id="deviceName"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="work-laptop"
                required
              />
            </div>
            <Button type="submit" disabled={busy} data-testid="create-device">
              {busy ? "Creating…" : "Create"}
            </Button>
          </form>
          {created && (
            <p className="text-sm" data-testid="device-token">
              Token for <strong>{created.name}</strong>:{" "}
              <code className="bg-muted rounded px-1 py-0.5 break-all">
                {created.token}
              </code>
            </p>
          )}
        </CardContent>
      </Card>

      {devices !== null && devices.length > 0 && (
        <div className="flex flex-col gap-1 font-mono text-xs">
          {devices.map((device) => (
            <div key={device.id} className="flex items-center gap-2">
              <span className="w-44 truncate">{device.name}</span>
              <span className="text-muted-foreground flex-1">
                {device.revoked
                  ? "revoked"
                  : device.last_used_at
                    ? `last used ${new Date(device.last_used_at).toLocaleString()}`
                    : "never used"}
              </span>
              {!device.revoked && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => revoke(device.id)}
                >
                  Revoke
                </Button>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
