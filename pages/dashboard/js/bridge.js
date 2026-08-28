const BRIDGE_ERROR = "AstrBotPluginPage bridge not available";
const API_ERROR = "管理 API 请求失败";

function getBridge() {
  return typeof window === "undefined" ? null : window.AstrBotPluginPage || null;
}

export function requireBridge() {
  const bridge = getBridge();
  if (!bridge) {
    throw new Error(BRIDGE_ERROR);
  }
  return bridge;
}

export async function bridgeReady() {
  const bridge = requireBridge();
  if (typeof bridge.ready === "function") {
    await bridge.ready();
  }
  return bridge;
}

function validateEndpoint(endpoint) {
  if (typeof endpoint !== "string" || endpoint.trim() === "") {
    throw new TypeError("管理 API 路径不能为空");
  }
  return endpoint.replace(/^\/+/, "");
}

function errorMessage(value) {
  if (value && typeof value === "object" && typeof value.message === "string") {
    return value.message;
  }
  return API_ERROR;
}

async function invoke(method, endpoint, payload) {
  const bridge = await bridgeReady();
  const call = bridge[method];
  if (typeof call !== "function") {
    throw new Error(`AstrBotPluginPage.${method} unavailable`);
  }

  const path = validateEndpoint(endpoint);
  const result =
    method === "apiGet" || method === "apiDelete"
      ? payload === undefined
        ? await call.call(bridge, path)
        : await call.call(bridge, path, payload)
      : await call.call(bridge, path, payload ?? {});

  if (result && typeof result === "object" && result.ok === false) {
    const error = new Error(errorMessage(result.error));
    if (typeof result.error?.code === "string") {
      error.code = result.error.code;
    }
    throw error;
  }
  return result;
}

export async function apiGet(endpoint, params) {
  return invoke("apiGet", endpoint, params);
}

export async function apiPost(endpoint, payload) {
  return invoke("apiPost", endpoint, payload);
}

export async function apiDelete(endpoint, payload) {
  return invoke("apiDelete", endpoint, payload);
}

export function createDashboardApi() {
  return {
    getBootstrap: () => apiGet("admin/bootstrap"),
  };
}
