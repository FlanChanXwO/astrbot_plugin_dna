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
  if (typeof value === "string" && value.trim() !== "") {
    return value;
  }
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

  const operationError =
    result && typeof result === "object" ? result.operation_error : null;
  if (operationError && typeof operationError === "object") {
    const error = new Error(errorMessage(operationError));
    if (typeof operationError.code === "string") {
      error.code = operationError.code;
    }
    throw error;
  }
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
  const bridge = await bridgeReady();
  if (typeof bridge.apiDelete === "function") {
    return invoke("apiDelete", endpoint, payload);
  }
  const normalized = validateEndpoint(endpoint);
  const deleteEndpoint = normalized.endsWith("/delete")
    ? normalized
    : `${normalized}/delete`;
  return invoke("apiPost", deleteEndpoint, payload);
}

export async function uploadFile(endpoint, file) {
  const bridge = await bridgeReady();
  if (typeof bridge.upload !== "function") {
    throw new Error("AstrBotPluginPage.upload unavailable");
  }
  const result = await bridge.upload(validateEndpoint(endpoint), file);
  if (result && typeof result === "object" && result.ok === false) {
    throw new Error(errorMessage(result.error));
  }
  return result;
}

function pathSegment(value, label) {
  if (typeof value !== "string" || value.trim() === "") {
    throw new TypeError(`${label} 不能为空`);
  }
  return encodeURIComponent(value.trim());
}

function dataValue(response) {
  return response && typeof response === "object" && response.ok === true
    ? response.data
    : response;
}

export function createDashboardApi() {
  return {
    getBootstrap: () => apiGet("admin/bootstrap"),
    getAccounts,
    getAccount,
    updateAccount,
    getUidDeletePreview,
    deleteUid,
    getUserDeletePreview,
    deleteUser,
    previewOverview,
    previewDetail,
    getAliasCatalog,
    addAlias,
    deleteAlias,
    restoreAliasRole,
    restoreAllAliases,
    getPanelImages,
    getPanelImage,
    uploadPanel,
    deletePanel,
    deleteAllPanels,
    compressPanels,
    getTasks,
    getTargets,
    enableTarget,
    disableTarget,
    deleteTarget,
    updateTask,
    pauseTask,
    resumeTask,
    deleteTask,
    getMembershipCapability,
    scanMembers,
    cleanupMemberGroup,
    getMemberDeletePreview,
    deleteMemberUser,
  };
}

export async function getAliasCatalog() {
  return dataValue(await apiGet("admin/aliases"));
}

export async function addAlias(roleName, alias) {
  const role = pathSegment(roleName, "角色名称");
  return dataValue(await apiPost(`admin/aliases/${role}`, { alias }));
}

export async function deleteAlias(roleName, alias) {
  const role = pathSegment(roleName, "角色名称");
  return dataValue(await apiPost(`admin/aliases/${role}/delete`, { alias }));
}

export async function restoreAliasRole(roleName) {
  const role = pathSegment(roleName, "角色名称");
  return dataValue(await apiPost(`admin/aliases/${role}/restore`, {}));
}

export async function restoreAllAliases() {
  return dataValue(await apiPost("admin/aliases/restore-all", {}));
}

export async function getAccounts({ includeCredentials = false } = {}) {
  return dataValue(
    await apiGet("admin/accounts", {
      include_credentials: includeCredentials ? "true" : "false",
    }),
  );
}

export async function getAccount(userId, uid) {
  const user = pathSegment(userId, "user_id");
  const accountUid = pathSegment(uid, "uid");
  return dataValue(await apiGet(`admin/accounts/${user}/${accountUid}`));
}

export async function updateAccount(userId, uid, payload) {
  const user = pathSegment(userId, "user_id");
  const accountUid = pathSegment(uid, "uid");
  return dataValue(await apiPost(`admin/accounts/${user}/${accountUid}`, payload));
}

export async function getUidDeletePreview(userId, uid) {
  const user = pathSegment(userId, "user_id");
  const accountUid = pathSegment(uid, "uid");
  return dataValue(
    await apiGet(`admin/accounts/${user}/${accountUid}/delete-preview`),
  );
}

export async function deleteUid(userId, uid, plan) {
  const user = pathSegment(userId, "user_id");
  const accountUid = pathSegment(uid, "uid");
  return dataValue(
    await apiPost(`admin/accounts/${user}/${accountUid}/delete`, {
      plan,
      confirmation_payload: plan?.confirmation_payload,
    }),
  );
}

export async function getUserDeletePreview(userId) {
  const user = pathSegment(userId, "user_id");
  return dataValue(await apiGet(`admin/accounts/users/${user}/delete-preview`));
}

export async function deleteUser(userId, plan) {
  const user = pathSegment(userId, "user_id");
  return dataValue(
    await apiPost(`admin/accounts/users/${user}/delete`, {
      plan,
      confirmation_payload: plan?.confirmation_payload,
    }),
  );
}

export async function previewOverview(userId, uid) {
  const user = pathSegment(userId, "user_id");
  const accountUid = pathSegment(uid, "uid");
  return dataValue(
    await apiPost(`admin/accounts/${user}/${accountUid}/preview/overview`, {}),
  );
}

export async function previewDetail(userId, uid, charName, weaponNames = []) {
  const user = pathSegment(userId, "user_id");
  const accountUid = pathSegment(uid, "uid");
  return dataValue(
    await apiPost(`admin/accounts/${user}/${accountUid}/preview/detail`, {
      char_name: charName,
      weapon_names: weaponNames,
    }),
  );
}

export async function getPanelImages(roleName) {
  const role = pathSegment(roleName, "角色名称");
  return dataValue(await apiGet(`admin/panels/${role}`));
}

export async function getPanelImage(roleName, imageId) {
  const role = pathSegment(roleName, "角色名称");
  const image = pathSegment(imageId, "面板图 ID");
  return dataValue(await apiGet(`admin/panels/${role}/${image}`));
}

export async function uploadPanel(roleName, file) {
  const role = pathSegment(roleName, "角色名称");
  return dataValue(await uploadFile(`admin/panels/${role}/upload`, file));
}

export async function deletePanel(roleName, imageId) {
  const role = pathSegment(roleName, "角色名称");
  const image = pathSegment(imageId, "面板图 ID");
  return dataValue(await apiPost(`admin/panels/${role}/${image}/delete`, {}));
}

export async function deleteAllPanels(roleName) {
  const role = pathSegment(roleName, "角色名称");
  return dataValue(await apiPost(`admin/panels/${role}/delete-all`, { confirmed: true }));
}

export async function compressPanels() {
  return dataValue(await apiPost("admin/panels/compress", {}));
}

export async function getTasks() {
  return dataValue(await apiGet("admin/tasks"));
}

export async function getTargets(taskId) {
  const params = taskId ? { task_id: taskId } : undefined;
  return dataValue(await apiGet("admin/targets", params));
}

export async function enableTarget(targetId) {
  const target = pathSegment(targetId, "目标 ID");
  return dataValue(await apiPost(`admin/targets/${target}/enable`, {}));
}

export async function disableTarget(targetId) {
  const target = pathSegment(targetId, "目标 ID");
  return dataValue(await apiPost(`admin/targets/${target}/disable`, {}));
}

export async function deleteTarget(targetId) {
  const target = pathSegment(targetId, "目标 ID");
  return dataValue(await apiPost(`admin/targets/${target}/delete`, {}));
}

export async function updateTask(taskId, schedule) {
  const task = pathSegment(taskId, "任务 ID");
  return dataValue(await apiPost(`admin/tasks/${task}`, { schedule }));
}

export async function pauseTask(taskId) {
  const task = pathSegment(taskId, "任务 ID");
  return dataValue(await apiPost(`admin/tasks/${task}/pause`, {}));
}

export async function resumeTask(taskId) {
  const task = pathSegment(taskId, "任务 ID");
  return dataValue(await apiPost(`admin/tasks/${task}/resume`, {}));
}

export async function deleteTask(taskId) {
  const task = pathSegment(taskId, "任务 ID");
  return dataValue(
    await apiPost(`admin/tasks/${task}/delete`, {
      confirmation_payload: `delete:task:${taskId}`,
    }),
  );
}

export async function getMembershipCapability() {
  return dataValue(await apiGet("admin/members/capability"));
}

export async function scanMembers(userId) {
  const user = pathSegment(userId, "user_id");
  return dataValue(await apiPost(`admin/members/${user}/scan`, {}));
}

export async function cleanupMemberGroup(userId, groupId) {
  const user = pathSegment(userId, "user_id");
  const group = pathSegment(groupId, "group_id");
  return dataValue(await apiPost(`admin/members/${user}/groups/${group}/cleanup`, {}));
}

export async function getMemberDeletePreview(userId) {
  const user = pathSegment(userId, "user_id");
  return dataValue(await apiGet(`admin/accounts/users/${user}/delete-preview`));
}

export async function deleteMemberUser(userId, plan) {
  const user = pathSegment(userId, "user_id");
  return dataValue(
    await apiPost(`admin/members/${user}/delete`, {
      plan,
      confirmation_payload: plan?.confirmation_payload,
    }),
  );
}
