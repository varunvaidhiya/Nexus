// Claude.ai adapter: reads rendered messages from the conversation view.
// Selectors drift with redesigns — failures here are expected and non-fatal.

"use strict";

NexusCapture.register({
  site: "claude",
  collect() {
    const match = location.pathname.match(/\/chat\/([\w-]+)/);
    if (!match) return null;
    const messages = [];
    for (const el of document.querySelectorAll(
      '[data-testid="user-message"], .font-claude-message'
    )) {
      const role = el.matches('[data-testid="user-message"]') ? "user" : "assistant";
      const content = el.innerText.trim();
      if (!content) continue;
      messages.push({ role, content });
    }
    return {
      externalId: match[1],
      title: document.title.replace(/ [-|] Claude.*$/, "").trim() || null,
      messages,
    };
  },
});
