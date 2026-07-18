// ChatGPT adapter: reads rendered messages from the conversation view.
// Selectors drift with redesigns — failures here are expected and non-fatal.

"use strict";

NexusCapture.register({
  site: "chatgpt",
  collect() {
    const match = location.pathname.match(/\/c\/([\w-]+)/);
    if (!match) return null;
    const messages = [];
    for (const el of document.querySelectorAll("[data-message-author-role]")) {
      const role = el.getAttribute("data-message-author-role");
      if (role !== "user" && role !== "assistant") continue;
      const content = el.innerText.trim();
      if (!content) continue;
      messages.push({
        externalId: el.getAttribute("data-message-id") || undefined,
        role,
        content,
      });
    }
    return {
      externalId: match[1],
      title: document.title.replace(/ [-|] ChatGPT.*$/, "").trim() || null,
      messages,
    };
  },
});
