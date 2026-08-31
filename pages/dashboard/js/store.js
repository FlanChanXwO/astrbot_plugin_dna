const NAV_ITEMS = Object.freeze([
  { id: "tasks", label: "任务与探测" },
  { id: "accounts", label: "账号与预览" },
  { id: "aliases", label: "角色别名" },
]);

const TASK_STATE_LABELS = Object.freeze({
  running: "运行中",
  paused: "已暂停",
  error: "异常",
});

const MEMBERSHIP_STATE_LABELS = Object.freeze({
  present: "仍在群中",
  absent: "已离群",
  unknown: "无法确认",
});

const CREDENTIAL_FIELDS = Object.freeze([
  "app_cookie",
  "app_device_code",
  "app_d_num",
  "app_refresh_token",
  "app_status",
]);

function blankCredentials() {
  return Object.fromEntries(CREDENTIAL_FIELDS.map((field) => [field, ""]));
}

function blankAccountForm() {
  return {
    user_id: "",
    uid: "",
    group_id: "",
    is_active: false,
    credentials: blankCredentials(),
  };
}

function accountKey(account) {
  return `${account?.user_id || ""}:${account?.uid || ""}`;
}

function accountGroups(value) {
  const accounts = asList(value, "accounts");
  const groups = new Map();
  for (const account of accounts) {
    if (!account || typeof account.user_id !== "string" || !account.user_id.trim()) {
      continue;
    }
    const userId = account.user_id.trim();
    if (!groups.has(userId)) {
      groups.set(userId, { user_id: userId, accounts: [] });
    }
    groups.get(userId).accounts.push(account);
  }
  return [...groups.values()];
}

function accountFormValue(account) {
  const credentials = blankCredentials();
  for (const field of CREDENTIAL_FIELDS) {
    if (typeof account?.credentials?.[field] === "string") {
      credentials[field] = account.credentials[field];
    }
  }
  return {
    user_id: typeof account?.user_id === "string" ? account.user_id : "",
    uid: typeof account?.uid === "string" ? account.uid : "",
    group_id: typeof account?.group_id === "string" ? account.group_id : "",
    is_active: account?.is_active === true,
    credentials,
  };
}

function parseWeaponNames(value) {
  return String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function blankDialog() {
  return {
    open: false,
    title: "确认操作",
    description: "",
    confirmLabel: "确认",
    submitting: false,
    onConfirm: null,
  };
}

function blankDrawer() {
  return {
    open: false,
    kind: "generic",
    title: "详情",
    description: "",
  };
}

function responseData(response) {
  return response && typeof response === "object" && response.ok === true
    ? response.data
    : response;
}

function safeErrorMessage(error) {
  return error instanceof Error && error.message ? error.message : "管理服务请求失败";
}

function asList(value, key) {
  const data = responseData(value);
  if (Array.isArray(data)) {
    return data;
  }
  if (data && typeof data === "object" && Array.isArray(data[key])) {
    return data[key];
  }
  return [];
}

function capabilityValue(value) {
  const data = responseData(value);
  return {
    supported: data?.supported === true,
    platform: typeof data?.platform === "string" ? data.platform : null,
    reason: typeof data?.reason === "string" ? data.reason : null,
  };
}

export function createDashboardStore({ api }) {
  return {
    api,
    navItems: NAV_ITEMS,
    activePage: "tasks",
    mobileNavOpen: false,
    pluginVersion: "",
    capabilities: null,
    bootstrapError: "",
    loading: true,
    errorMessage: "",

    tasks: [],
    targets: [],
    tasksLoading: false,
    targetsLoading: false,
    taskError: "",
    targetsError: "",
    selectedTaskId: "",
    taskScheduleDrafts: {},
    taskActionBusy: "",

    membershipCapability: {
      supported: false,
      platform: null,
      reason: "尚未读取平台能力",
    },
    membershipLoading: false,
    membershipError: "",
    memberUserId: "",
    memberScan: null,
    memberScanLoading: false,
    memberActionBusy: false,
    memberDeletePreviewLoading: false,
    memberDeletePlan: null,

    accounts: [],
    accountGroups: [],
    accountSearch: "",
    accountsLoading: false,
    accountsError: "",
    selectedAccount: null,
    accountForm: blankAccountForm(),
    accountEditorOpen: false,
    accountEditorRequestId: 0,
    accountSaving: false,
    accountActionBusy: "",
    accountDeleteLoading: false,
    accountDeletePlan: null,
    accountPreview: null,
    accountPreviewLoading: false,
    accountPreviewError: "",
    previewRequestId: 0,
    previewCharName: "",
    previewWeaponNames: "",

    aliasRoles: [],
    aliasSearch: "",
    aliasesLoading: false,
    aliasesError: "",
    aliasDrafts: {},
    aliasActionBusy: "",

    toast: {
      open: false,
      message: "",
      tone: "info",
    },
    dialog: blankDialog(),
    drawer: blankDrawer(),

    get activePageLabel() {
      return this.navItems.find((item) => item.id === this.activePage)?.label || "任务与探测";
    },

    get filteredAccountGroups() {
      const query = this.accountSearch.trim().toLocaleLowerCase();
      if (!query) {
        return this.accountGroups;
      }
      return this.accountGroups
        .map((group) => ({
          ...group,
          accounts: group.accounts.filter((account) =>
            accountKey(account).toLocaleLowerCase().includes(query),
          ),
        }))
        .filter((group) => group.accounts.length > 0);
    },

    get filteredAliasRoles() {
      const query = this.aliasSearch.trim().toLocaleLowerCase();
      if (!query) {
        return this.aliasRoles;
      }
      return this.aliasRoles.filter((role) => {
        const values = [
          role.canonical_name,
          ...(role.default_aliases || []),
          ...(role.custom_aliases || []),
          ...(role.effective_aliases || []),
        ];
        return values.some((value) => String(value).toLocaleLowerCase().includes(query));
      });
    },

    get selectedTask() {
      return this.tasks.find((task) => task.id === this.selectedTaskId) || null;
    },

    accountKey(account) {
      return accountKey(account);
    },

    get membershipResults() {
      return this.memberScan?.groups || this.memberScan?.results || [];
    },

    get canScanMembers() {
      return (
        this.membershipCapability.supported === true &&
        this.membershipCapability.platform === "aiocqhttp" &&
        this.memberUserId.trim() !== "" &&
        !this.memberScanLoading &&
        !this.memberActionBusy
      );
    },

    async initialize() {
      this.loading = true;
      this.errorMessage = "";
      this.bootstrapError = "";
      try {
        const payload = responseData(await this.api.getBootstrap());
        this.pluginVersion = payload?.version || payload?.plugin_version || "";
        this.capabilities = payload?.capabilities || {};
        if (payload?.capabilities?.membership_probe) {
          this.membershipCapability = capabilityValue(payload.capabilities.membership_probe);
        }
      } catch (error) {
        // capability 不支持时 bootstrap 会按后端契约返回错误；保留页面可用，交给成员区域禁用扫描并说明原因。
        this.bootstrapError = safeErrorMessage(error);
        this.capabilities = {};
        this.membershipCapability = {
          supported: false,
          platform: null,
          reason: "当前平台不支持群成员探测",
        };
        this.showToast("管理服务初始化未完成，部分功能可能不可用", "error");
      }

      await this.loadMembershipCapability();
      await this.reloadTaskState();
      await this.reloadAccountState();
      await this.reloadAliasState();
      this.loading = false;
    },

    fail(error) {
      this.errorMessage = safeErrorMessage(error);
      this.capabilities = null;
      this.showToast(this.errorMessage, "error");
    },

    navigate(page) {
      if (!this.navItems.some((item) => item.id === page)) {
        return;
      }
      this.activePage = page;
      this.mobileNavOpen = false;
    },

    showToast(message, tone = "info") {
      this.toast = {
        open: true,
        message: message || "操作已完成",
        tone,
      };
    },

    closeToast() {
      this.toast.open = false;
    },

    openDialog(options = {}) {
      this.dialog = {
        ...blankDialog(),
        ...options,
        open: true,
      };
    },

    closeDialog() {
      this.dialog = blankDialog();
    },

    async confirmDialog() {
      if (typeof this.dialog.onConfirm !== "function") {
        this.closeDialog();
        return;
      }
      this.dialog.submitting = true;
      try {
        await this.dialog.onConfirm();
        this.closeDialog();
      } catch (error) {
        this.showToast(safeErrorMessage(error), "error");
      } finally {
        this.dialog.submitting = false;
      }
    },

    openDrawer(options = {}) {
      if (this.drawer.kind === "account-edit") {
        this.clearAccountSecrets();
      }
      if (this.drawer.kind === "preview") {
        this.clearPreviewState();
      }
      this.drawer = {
        ...blankDrawer(),
        ...options,
        open: true,
      };
    },

    closeDrawer() {
      if (this.drawer.kind === "account-edit") {
        this.clearAccountSecrets();
        this.accountEditorOpen = false;
        this.selectedAccount = null;
      }
      if (this.drawer.kind === "preview") {
        this.clearPreviewState();
      }
      if (this.drawer.kind === "detail-form") {
        this.clearPreviewState();
      }
      this.drawer = blankDrawer();
    },

    closeOverlay() {
      this.mobileNavOpen = false;
      if (this.dialog.open) {
        this.closeDialog();
      }
      if (this.drawer.open) {
        this.closeDrawer();
      }
    },

    async reloadAccountState() {
      this.accountsLoading = true;
      this.accountsError = "";
      try {
        const payload = await this.api.getAccounts({ includeCredentials: false });
        this.accounts = asList(payload, "accounts");
        this.accountGroups = accountGroups(this.accounts);
      } catch (error) {
        this.accounts = [];
        this.accountGroups = [];
        this.accountsError = safeErrorMessage(error);
      } finally {
        this.accountsLoading = false;
      }
    },

    async openAccountEditor(account) {
      if (!account) {
        return;
      }
      const requestId = ++this.accountEditorRequestId;
      this.clearAccountSecrets();
      this.clearPreviewState();
      this.selectedAccount = account;
      this.accountForm = accountFormValue(account);
      this.accountEditorOpen = true;
      this.openDrawer({
        kind: "account-edit",
        title: `编辑账号 ${account.uid || ""}`,
        description: "身份键只读；来源群、启用状态和全部 App 凭据可编辑。",
      });
      try {
        const payload = responseData(await this.api.getAccount(account.user_id, account.uid));
        if (
          requestId !== this.accountEditorRequestId ||
          !this.drawer.open ||
          this.drawer.kind !== "account-edit"
        ) {
          return;
        }
        if (payload) {
          this.selectedAccount = payload;
          this.accountForm = accountFormValue(payload);
        }
      } catch (error) {
        if (requestId !== this.accountEditorRequestId) {
          return;
        }
        this.accountEditorOpen = false;
        this.closeDrawer();
        this.showToast(safeErrorMessage(error), "error");
      }
    },

    clearAccountSecrets() {
      const credentials = this.accountForm?.credentials;
      if (!credentials) {
        return;
      }
      for (const field of CREDENTIAL_FIELDS) {
        credentials[field] = "";
      }
    },

    closeAccountEditor() {
      this.accountEditorRequestId += 1;
      this.clearAccountSecrets();
      this.accountEditorOpen = false;
      this.accountForm = blankAccountForm();
      this.selectedAccount = null;
      if (this.drawer.open) {
        this.closeDrawer();
      }
    },

    accountFormPayload() {
      const credentials = {};
      for (const field of CREDENTIAL_FIELDS) {
        credentials[field] = String(this.accountForm.credentials?.[field] || "");
      }
      return {
        user_id: this.accountForm.user_id,
        uid: this.accountForm.uid,
        group_id: this.accountForm.group_id.trim() || null,
        is_active: this.accountForm.is_active === true,
        credentials,
      };
    },

    confirmSaveAccount() {
      if (!this.accountForm.user_id || !this.accountForm.uid) {
        this.showToast("账号身份键不完整，无法保存", "error");
        return;
      }
      this.openDialog({
        title: "确认保存账号",
        description: `将更新用户「${this.accountForm.user_id}」的 UID「${this.accountForm.uid}」来源、状态和全部凭据。`,
        confirmLabel: "保存账号",
        onConfirm: () => this.saveAccount(),
      });
    },

    async saveAccount() {
      this.accountSaving = true;
      try {
        await this.api.updateAccount(
          this.accountForm.user_id,
          this.accountForm.uid,
          this.accountFormPayload(),
        );
        await this.reloadAccountState();
        this.showToast("账号已更新");
        this.closeAccountEditor();
      } catch (error) {
        this.showToast(safeErrorMessage(error), "error");
      } finally {
        this.accountSaving = false;
      }
    },

    async confirmDeleteUid(account) {
      if (!account) {
        return;
      }
      this.accountDeleteLoading = true;
      this.accountDeletePlan = null;
      try {
        const plan = responseData(
          await this.api.getUidDeletePreview(account.user_id, account.uid),
        );
        if (
          !plan?.confirmation_payload ||
          plan.user_id !== account.user_id ||
          plan.uid !== account.uid
        ) {
          throw new Error("UID 删除预览无效");
        }
        this.accountDeletePlan = plan;
        this.openDialog({
          title: "确认删除 UID",
          description: `将删除用户「${account.user_id}」的 UID「${account.uid}」及预览列出的数据，此操作不可恢复。`,
          confirmLabel: "永久删除 UID",
          onConfirm: () => this.deleteUid(account, plan),
        });
      } catch (error) {
        this.showToast(safeErrorMessage(error), "error");
      } finally {
        this.accountDeleteLoading = false;
      }
    },

    async deleteUid(account, plan = this.accountDeletePlan) {
      if (!account || !plan) {
        return;
      }
      this.accountActionBusy = accountKey(account);
      try {
        await this.api.deleteUid(account.user_id, account.uid, plan);
        await this.reloadAccountState();
        this.accountDeletePlan = null;
        this.showToast("UID 已永久删除");
        if (this.accountEditorOpen) {
          this.closeAccountEditor();
        }
      } catch (error) {
        this.showToast(safeErrorMessage(error), "error");
      } finally {
        this.accountActionBusy = "";
      }
    },

    async confirmDeleteUser(userId) {
      const normalizedUserId = String(userId || "").trim();
      if (!normalizedUserId) {
        return;
      }
      this.accountDeleteLoading = true;
      this.accountDeletePlan = null;
      try {
        const plan = responseData(await this.api.getUserDeletePreview(normalizedUserId));
        if (!plan?.confirmation_payload || plan.user_id !== normalizedUserId || plan.uid !== null) {
          throw new Error("用户删除预览无效");
        }
        this.accountDeletePlan = plan;
        this.openDialog({
          title: "确认删除用户",
          description: `将删除用户「${normalizedUserId}」及 ${plan.affected_uids?.length || 0} 个 UID 的全部账号数据，此操作不可恢复。`,
          confirmLabel: "永久删除用户",
          onConfirm: () => this.deleteUser(normalizedUserId, plan),
        });
      } catch (error) {
        this.showToast(safeErrorMessage(error), "error");
      } finally {
        this.accountDeleteLoading = false;
      }
    },

    async deleteUser(userId, plan = this.accountDeletePlan) {
      if (!userId || !plan) {
        return;
      }
      this.accountActionBusy = userId;
      try {
        await this.api.deleteUser(userId, plan);
        await this.reloadAccountState();
        this.accountDeletePlan = null;
        this.showToast("用户及其全局数据已永久删除");
        if (this.accountEditorOpen) {
          this.closeAccountEditor();
        }
      } catch (error) {
        this.showToast(safeErrorMessage(error), "error");
      } finally {
        this.accountActionBusy = "";
      }
    },

    clearPreviewState() {
      this.previewRequestId += 1;
      this.accountPreview = null;
      this.accountPreviewLoading = false;
      this.accountPreviewError = "";
      this.previewCharName = "";
      this.previewWeaponNames = "";
    },

    previewImageUrl(preview = this.accountPreview) {
      const data = preview?.data_base64 || preview?.data;
      if (typeof data !== "string" || !data) {
        return "";
      }
      const contentType = typeof preview.content_type === "string" && preview.content_type
        ? preview.content_type
        : "image/png";
      return `data:${contentType};base64,${data}`;
    },

    openDetailForm(account) {
      if (!account) {
        return;
      }
      this.clearPreviewState();
      this.selectedAccount = account;
      this.openDrawer({
        kind: "detail-form",
        title: `生成详情卡 · ${account.uid || ""}`,
        description: "输入总览中的角色名称，可选填至多两件武器名称。",
      });
    },

    async previewOverview(account) {
      if (!account) {
        return;
      }
      this.clearPreviewState();
      this.selectedAccount = account;
      this.openDrawer({
        kind: "preview",
        title: `基本信息卡 · ${account.uid || ""}`,
        description: "管理预览固定显示完整 UID，不受用户隐私设置影响。",
      });
      this.accountPreviewLoading = true;
      const requestId = this.previewRequestId;
      try {
        const payload = responseData(await this.api.previewOverview(account.user_id, account.uid));
        if (
          requestId !== this.previewRequestId ||
          !this.drawer.open ||
          this.drawer.kind !== "preview"
        ) {
          return;
        }
        if (!this.previewImageUrl(payload)) {
          throw new Error("基本信息卡图片无效");
        }
        this.accountPreview = payload;
      } catch (error) {
        if (requestId === this.previewRequestId) {
          this.accountPreviewError = safeErrorMessage(error);
        }
      } finally {
        if (requestId === this.previewRequestId) {
          this.accountPreviewLoading = false;
        }
      }
    },

    async previewDetail(account) {
      if (!account) {
        return;
      }
      const charName = this.previewCharName.trim();
      if (!charName) {
        this.showToast("请输入角色名称", "error");
        return;
      }
      const weaponNames = parseWeaponNames(this.previewWeaponNames);
      this.clearPreviewState();
      this.selectedAccount = account;
      this.previewCharName = charName;
      this.previewWeaponNames = weaponNames.join(", ");
      this.openDrawer({
        kind: "preview",
        title: `详情卡 · ${account.uid || ""}`,
        description: "管理预览固定显示完整 UID，不受用户隐私设置影响。",
      });
      this.accountPreviewLoading = true;
      const requestId = this.previewRequestId;
      try {
        const payload = responseData(
          await this.api.previewDetail(account.user_id, account.uid, charName, weaponNames),
        );
        if (
          requestId !== this.previewRequestId ||
          !this.drawer.open ||
          this.drawer.kind !== "preview"
        ) {
          return;
        }
        if (!this.previewImageUrl(payload)) {
          throw new Error("详情卡图片无效");
        }
        this.accountPreview = payload;
      } catch (error) {
        if (requestId === this.previewRequestId) {
          this.accountPreviewError = safeErrorMessage(error);
        }
      } finally {
        if (requestId === this.previewRequestId) {
          this.accountPreviewLoading = false;
        }
      }
    },

    previewDetailFromDrawer() {
      return this.previewDetail(this.selectedAccount);
    },

    async reloadAliasState() {
      this.aliasesLoading = true;
      this.aliasesError = "";
      try {
        const payload = await this.api.getAliasCatalog();
        this.aliasRoles = asList(payload, "roles");
        const drafts = { ...this.aliasDrafts };
        for (const role of this.aliasRoles) {
          const name = role?.canonical_name;
          if (typeof name === "string" && drafts[name] === undefined) {
            drafts[name] = "";
          }
        }
        this.aliasDrafts = drafts;
      } catch (error) {
        this.aliasRoles = [];
        this.aliasesError = safeErrorMessage(error);
      } finally {
        this.aliasesLoading = false;
      }
    },

    aliasRoleName(role) {
      return typeof role === "string" ? role : role?.canonical_name || "";
    },

    confirmAddAlias(role) {
      const roleName = this.aliasRoleName(role);
      const alias = String(this.aliasDrafts[roleName] || "").trim();
      if (!roleName || !alias) {
        this.showToast("请输入要追加的角色别名", "error");
        return;
      }
      this.openDialog({
        title: "确认添加自定义别名",
        description: `将为角色「${roleName}」追加自定义别名「${alias}」。`,
        confirmLabel: "添加别名",
        onConfirm: () => this.addAlias(roleName, alias),
      });
    },

    async addAlias(role, alias) {
      const roleName = this.aliasRoleName(role);
      const candidate = String(alias || "").trim();
      if (!roleName || !candidate) {
        return;
      }
      this.aliasActionBusy = roleName;
      try {
        await this.api.addAlias(roleName, candidate);
        await this.reloadAliasState();
        this.aliasDrafts[roleName] = "";
        this.showToast("自定义别名已添加");
      } catch (error) {
        this.showToast(safeErrorMessage(error), "error");
      } finally {
        this.aliasActionBusy = "";
      }
    },

    confirmDeleteAlias(role, alias) {
      const roleName = this.aliasRoleName(role);
      if (!roleName || !alias) {
        return;
      }
      this.openDialog({
        title: "确认删除自定义别名",
        description: `将从角色「${roleName}」删除自定义别名「${alias}」。默认别名不会受影响。`,
        confirmLabel: "删除别名",
        onConfirm: () => this.deleteAlias(roleName, alias),
      });
    },

    async deleteAlias(role, alias) {
      const roleName = this.aliasRoleName(role);
      if (!roleName || !alias) {
        return;
      }
      this.aliasActionBusy = roleName;
      try {
        await this.api.deleteAlias(roleName, alias);
        await this.reloadAliasState();
        this.showToast("自定义别名已删除");
      } catch (error) {
        this.showToast(safeErrorMessage(error), "error");
      } finally {
        this.aliasActionBusy = "";
      }
    },

    confirmRestoreAlias(role) {
      const roleName = this.aliasRoleName(role);
      if (!roleName) {
        return;
      }
      this.openDialog({
        title: "确认恢复角色默认别名",
        description: `将删除角色「${roleName}」的全部自定义追加，只保留默认别名。`,
        confirmLabel: "恢复默认",
        onConfirm: () => this.restoreAliasRole(roleName),
      });
    },

    async restoreAliasRole(role) {
      const roleName = this.aliasRoleName(role);
      if (!roleName) {
        return;
      }
      this.aliasActionBusy = roleName;
      try {
        await this.api.restoreAliasRole(roleName);
        await this.reloadAliasState();
        this.showToast("角色默认别名已恢复");
      } catch (error) {
        this.showToast(safeErrorMessage(error), "error");
      } finally {
        this.aliasActionBusy = "";
      }
    },

    confirmRestoreAllAliases() {
      this.openDialog({
        title: "确认恢复全部默认别名",
        description: "将删除所有角色的自定义别名追加，不修改资源仓库中的默认别名。",
        confirmLabel: "恢复全部默认",
        onConfirm: () => this.restoreAllAliases(),
      });
    },

    async restoreAllAliases() {
      this.aliasActionBusy = "all";
      try {
        await this.api.restoreAllAliases();
        await this.reloadAliasState();
        this.showToast("全部角色默认别名已恢复");
      } catch (error) {
        this.showToast(safeErrorMessage(error), "error");
      } finally {
        this.aliasActionBusy = "";
      }
    },

    async reloadTaskState() {
      this.tasksLoading = true;
      this.taskError = "";
      try {
        this.tasks = asList(await this.api.getTasks(), "tasks");
        const currentId = this.selectedTaskId;
        this.selectedTaskId = this.tasks.some((task) => task.id === currentId)
          ? currentId
          : this.tasks[0]?.id || "";
        for (const task of this.tasks) {
          if (this.taskScheduleDrafts[task.id] === undefined) {
            this.taskScheduleDrafts[task.id] = task.schedule || "";
          }
        }
        await this.loadTargets(this.selectedTaskId);
      } catch (error) {
        this.tasks = [];
        this.targets = [];
        this.taskError = safeErrorMessage(error);
      } finally {
        this.tasksLoading = false;
      }
    },

    async loadTargets(taskId) {
      this.selectedTaskId = taskId || "";
      this.targetsLoading = true;
      this.targetsError = "";
      if (!this.selectedTaskId) {
        this.targets = [];
        this.targetsLoading = false;
        return;
      }
      try {
        this.targets = asList(await this.api.getTargets(this.selectedTaskId), "targets");
      } catch (error) {
        this.targets = [];
        this.targetsError = safeErrorMessage(error);
      } finally {
        this.targetsLoading = false;
      }
    },

    taskSchedule(task) {
      return this.taskScheduleDrafts[task.id] ?? task.schedule ?? "";
    },

    formatTaskState(state) {
      return TASK_STATE_LABELS[state] || "未知状态";
    },

    formatNextRun(value) {
      if (!value) {
        return "未排定";
      }
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) {
        return String(value);
      }
      return new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
    },

    confirmTaskSchedule(task) {
      const schedule = String(this.taskSchedule(task)).trim();
      if (!schedule) {
        this.showToast("调度规则不能为空", "error");
        return;
      }
      this.openDialog({
        title: "确认保存调度规则",
        description: `将把「${task.name}」的规则更新为「${schedule}」。`,
        confirmLabel: "保存规则",
        onConfirm: () => this.updateTaskSchedule(task),
      });
    },

    confirmTaskAction(task, actionName) {
      const actions = {
        pauseTask: {
          title: "确认暂停任务",
          description: `将暂停「${task.name}」的当前进程，之后可以恢复。`,
          confirmLabel: "暂停任务",
        },
        resumeTask: {
          title: "确认恢复任务",
          description: `将恢复「${task.name}」的当前进程。`,
          confirmLabel: "恢复任务",
        },
        deleteTask: {
          title: "确认永久删除任务",
          description: `将永久删除「${task.name}」的任务定义并写入不可恢复 tombstone。`,
          confirmLabel: "永久删除",
        },
      };
      const options = actions[actionName];
      if (!options) {
        return;
      }
      this.openDialog({
        ...options,
        onConfirm: () => this[actionName](task),
      });
    },

    async updateTaskSchedule(task) {
      const schedule = String(this.taskSchedule(task)).trim();
      if (!schedule) {
        this.showToast("调度规则不能为空", "error");
        return;
      }
      this.taskActionBusy = task.id;
      try {
        await this.api.updateTask(task.id, schedule);
        await this.reloadTaskState();
        this.showToast("调度规则已更新");
      } catch (error) {
        this.showToast(safeErrorMessage(error), "error");
      } finally {
        this.taskActionBusy = "";
      }
    },

    async pauseTask(task) {
      this.taskActionBusy = task.id;
      try {
        await this.api.pauseTask(task.id);
        await this.reloadTaskState();
        this.showToast("任务已暂停");
      } catch (error) {
        this.showToast(safeErrorMessage(error), "error");
      } finally {
        this.taskActionBusy = "";
      }
    },

    async resumeTask(task) {
      this.taskActionBusy = task.id;
      try {
        await this.api.resumeTask(task.id);
        await this.reloadTaskState();
        this.showToast("任务已恢复");
      } catch (error) {
        this.showToast(safeErrorMessage(error), "error");
      } finally {
        this.taskActionBusy = "";
      }
    },

    async deleteTask(task) {
      this.taskActionBusy = task.id;
      try {
        await this.api.deleteTask(task.id);
        await this.reloadTaskState();
        this.showToast("任务已永久删除");
      } catch (error) {
        this.showToast(safeErrorMessage(error), "error");
      } finally {
        this.taskActionBusy = "";
      }
    },

    targetDestination(target) {
      if (target.group_id) {
        return target.group_id;
      }
      return target.unified_msg_origin || "会话目标";
    },

    async loadMembershipCapability() {
      this.membershipLoading = true;
      this.membershipError = "";
      try {
        this.membershipCapability = capabilityValue(await this.api.getMembershipCapability());
      } catch (_error) {
        this.membershipCapability = {
          supported: false,
          platform: null,
          reason: "当前平台不支持群成员探测",
        };
        this.membershipError = "成员探测仅支持 aiocqhttp（OneBot V11）平台";
      } finally {
        this.membershipLoading = false;
      }
    },

    membershipStatusLabel(status) {
      return MEMBERSHIP_STATE_LABELS[status] || "未知状态";
    },

    async scanMembers(allowBusy = false) {
      const userId = this.memberUserId.trim();
      if ((!this.canScanMembers && !allowBusy) || !userId) {
        this.membershipError = "仅支持 aiocqhttp（OneBot V11）平台，且需要填写 user_id";
        return;
      }
      this.memberScanLoading = true;
      this.membershipError = "";
      try {
        const payload = responseData(await this.api.scanMembers(userId));
        this.memberScan = payload;
        if (payload?.capability) {
          this.membershipCapability = capabilityValue(payload.capability);
        }
        this.showToast("成员探测完成");
      } catch (error) {
        this.memberScan = null;
        this.membershipError = safeErrorMessage(error);
      } finally {
        this.memberScanLoading = false;
      }
    },

    async reloadMembershipState() {
      await this.loadMembershipCapability();
      if (
        this.memberUserId.trim() &&
        this.membershipCapability.supported === true &&
        this.membershipCapability.platform === "aiocqhttp" &&
        !this.memberScanLoading
      ) {
        await this.scanMembers(true);
      }
    },

    confirmCleanup(result) {
      if (!result || result.status !== "absent") {
        this.showToast("只有明确 absent 的群才能清理", "error");
        return;
      }
      this.openDialog({
        title: "确认清理该群个人订阅",
        description: `将清理用户「${result.user_id}」在群「${result.group_id}」中可安全归属的个人密函订阅。`,
        confirmLabel: "确认清理",
        onConfirm: () => this.cleanupMemberGroup(result),
      });
    },

    async cleanupMemberGroup(result) {
      this.memberActionBusy = true;
      try {
        const userId = this.memberUserId.trim();
        await this.api.cleanupMemberGroup(userId, result.group_id);
        await this.reloadMembershipState();
        this.showToast("该群个人订阅已清理");
      } catch (error) {
        this.showToast(safeErrorMessage(error), "error");
      } finally {
        this.memberActionBusy = false;
      }
    },

    async confirmDeleteMemberUser() {
      if (!this.memberScan?.can_delete_user) {
        this.showToast("必须所有关联群均明确 absent 才能全局删除", "error");
        return;
      }
      this.memberDeletePreviewLoading = true;
      try {
        const preview = responseData(
          await this.api.getMemberDeletePreview(this.memberUserId.trim()),
        );
        if (!preview?.confirmation_payload) {
          throw new Error("删除预览无效");
        }
        this.memberDeletePlan = preview;
        this.openDialog({
          title: "确认全局删除用户",
          description: `将删除用户「${preview.user_id}」及 ${preview.affected_uids?.length || 0} 个 UID 的账号、凭据和个人数据，此操作不可恢复。`,
          confirmLabel: "永久删除用户",
          onConfirm: () => this.deleteMemberUser(),
        });
      } catch (error) {
        this.showToast(safeErrorMessage(error), "error");
      } finally {
        this.memberDeletePreviewLoading = false;
      }
    },

    async deleteMemberUser() {
      if (!this.memberDeletePlan) {
        return;
      }
      this.memberActionBusy = true;
      try {
        await this.api.deleteMemberUser(this.memberUserId.trim(), this.memberDeletePlan);
        await this.reloadMembershipState();
        this.memberDeletePlan = null;
        this.memberScan = null;
        this.showToast("用户及其全局数据已删除");
      } catch (error) {
        this.showToast(safeErrorMessage(error), "error");
      } finally {
        this.memberActionBusy = false;
      }
    },
  };
}
