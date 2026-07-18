"use strict";

const SITES = ["chatgpt", "claude"];

chrome.storage.local.get(["backendUrl", "deviceToken", "siteToggles"], (stored) => {
  document.getElementById("backendUrl").value = stored.backendUrl || "";
  document.getElementById("deviceToken").value = stored.deviceToken || "";
  for (const site of SITES) {
    const toggles = stored.siteToggles || {};
    document.getElementById(`site-${site}`).checked = toggles[site] !== false;
  }
});

document.getElementById("save").addEventListener("click", () => {
  const siteToggles = {};
  for (const site of SITES) {
    siteToggles[site] = document.getElementById(`site-${site}`).checked;
  }
  chrome.storage.local.set(
    {
      backendUrl: document.getElementById("backendUrl").value.trim(),
      deviceToken: document.getElementById("deviceToken").value.trim(),
      siteToggles,
    },
    () => {
      const status = document.getElementById("status");
      status.textContent = "Saved";
      setTimeout(() => (status.textContent = ""), 2000);
    }
  );
});
