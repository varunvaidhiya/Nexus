# apps/extension

Nexus Capture — MV3 browser extension (Tier B). Captures conversations from
allowlisted AI chat sites as rendered and pushes them to the Nexus backend's
`/ingest` endpoint with a device token.

**Best-effort by design.** Content-script selectors break when vendors
redesign; each site adapter is isolated so one redesign breaks only that
adapter, and the export importer (Tier C) covers any gaps.

Supported sites (per-site toggle in the options page):

- chatgpt.com
- claude.ai

Planned: gemini.google.com, chat.deepseek.com, MiniMax, Qwen.

## Install (unpacked)

1. `chrome://extensions` → enable Developer mode → **Load unpacked** → select
   this directory.
2. Open the extension's options page; set the backend URL and a device token
   (create one in Nexus Settings → Devices).
3. Grant host access to your backend origin when prompted (localhost is
   requested as an optional host permission).

## How it works

- Content scripts observe the conversation view (MutationObserver, debounced)
  and send the current conversation to the service worker — read-only, no page
  mutation.
- The service worker buffers conversations in `chrome.storage.local` and
  flushes them to `POST /ingest` once a minute; failed pushes stay buffered
  and retry on the next alarm.
- The backend dedupes by conversation/message identity, so re-pushing the same
  conversation never duplicates data.
