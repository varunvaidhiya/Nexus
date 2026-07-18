// Service worker: buffers captured conversations and pushes them to /ingest.
//
// Content scripts send { type: "nexus-capture", site, conversation }; we merge
// into a chrome.storage.local buffer and flush on an alarm. The backend dedupes
// (external_id / fingerprint), so re-pushing a whole conversation is harmless —
// that keeps this worker stateless-restart-safe.

"use strict";

const FLUSH_ALARM = "nexus-flush";
const SITE_KINDS = { chatgpt: "chatgpt", claude: "claude_web" };

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create(FLUSH_ALARM, { periodInMinutes: 1 });
});

chrome.runtime.onMessage.addListener((message) => {
  if (message && message.type === "nexus-capture") {
    bufferConversation(message.site, message.conversation);
  }
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === FLUSH_ALARM) flush();
});

function bufferConversation(site, conversation) {
  chrome.storage.local.get({ buffer: {} }, ({ buffer }) => {
    buffer[`${site}:${conversation.externalId}`] = { site, conversation, at: Date.now() };
    chrome.storage.local.set({ buffer });
  });
}

async function flush() {
  const { buffer, backendUrl, deviceToken } = await chrome.storage.local.get([
    "buffer",
    "backendUrl",
    "deviceToken",
  ]);
  const entries = Object.entries(buffer || {});
  if (!entries.length || !backendUrl || !deviceToken) return;

  const bySite = {};
  for (const [key, entry] of entries) {
    (bySite[entry.site] = bySite[entry.site] || []).push([key, entry]);
  }

  const flushedKeys = [];
  for (const [site, siteEntries] of Object.entries(bySite)) {
    const batch = {
      schema_version: "nexus.ingest.v1",
      source: { kind: SITE_KINDS[site] || site, name: `${site}-extension`, ingest_tier: "B" },
      conversations: siteEntries.map(([, entry]) => ({
        external_id: entry.conversation.externalId,
        title: entry.conversation.title || null,
        messages: entry.conversation.messages.map((m) => ({
          external_id: m.externalId || null,
          role: m.role,
          content: m.content,
        })),
      })),
    };
    try {
      const response = await fetch(`${backendUrl.replace(/\/$/, "")}/ingest`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${deviceToken}`,
        },
        body: JSON.stringify(batch),
      });
      if (response.ok) {
        flushedKeys.push(...siteEntries.map(([key]) => key));
      }
      // Non-OK (bad token, backend down): keep buffered, retry next alarm.
    } catch (err) {
      console.debug("nexus-capture: flush failed, will retry", err);
    }
  }

  if (flushedKeys.length) {
    const { buffer: current } = await chrome.storage.local.get({ buffer: {} });
    for (const key of flushedKeys) delete current[key];
    await chrome.storage.local.set({ buffer: current, lastFlushAt: Date.now() });
  }
}
