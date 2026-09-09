import { bridgeReady, createDashboardApi } from "./js/bridge.js";
import { createDashboardStore } from "./js/store.js";

const root = document.querySelector("#app");
const petiteVue = globalThis.PetiteVue;

if (!root) {
  throw new Error("Dashboard root not found");
}

if (!petiteVue || typeof petiteVue.createApp !== "function") {
  root.removeAttribute("v-cloak");
  root.textContent = "PetiteVue runtime not available";
  throw new Error("PetiteVue runtime not available");
}

const store = createDashboardStore({ api: createDashboardApi() });
globalThis.dnabyDashboard = store;
petiteVue.createApp(store).mount("#app");

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    store.closeOverlay();
  }
});

function syncDocumentMetadata() {
  document.title = `${store.pluginDisplayName} 管理面板`;
  document.documentElement.dataset.pluginDisplayName = store.pluginDisplayName;
}

async function boot() {
  try {
    await bridgeReady();
    await store.initialize();
    syncDocumentMetadata();
  } catch (error) {
    store.fail(error);
    store.loading = false;
  }
}

void boot();
