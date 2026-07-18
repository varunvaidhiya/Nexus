// Shared plumbing for site adapters (Tier B, best-effort by design).
//
// A site adapter calls NexusCapture.register({ site, collect }) where
// `collect()` returns { externalId, title, messages: [{externalId?, role,
// content}] } for the conversation currently on screen, or null. Capture is
// observation-only: adapters must never mutate the page.

"use strict";

const NexusCapture = (() => {
  const DEBOUNCE_MS = 2000;

  function register({ site, collect }) {
    chrome.storage.local.get(["siteToggles"], ({ siteToggles }) => {
      if (siteToggles && siteToggles[site] === false) return;
      let timer = null;

      const capture = () => {
        timer = null;
        let conversation = null;
        try {
          conversation = collect();
        } catch (err) {
          // A vendor redesign broke the adapter; stay silent, the importer covers gaps.
          console.debug("nexus-capture: collect failed", err);
        }
        if (!conversation || !conversation.externalId || !conversation.messages.length) return;
        chrome.runtime.sendMessage({ type: "nexus-capture", site, conversation });
      };

      const observer = new MutationObserver(() => {
        if (timer) clearTimeout(timer);
        timer = setTimeout(capture, DEBOUNCE_MS);
      });
      observer.observe(document.body, { childList: true, subtree: true, characterData: true });
      setTimeout(capture, DEBOUNCE_MS);
    });
  }

  return { register };
})();
