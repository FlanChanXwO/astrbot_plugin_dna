const NAV_ITEMS = Object.freeze([
  { id: "panels", label: "面板图" },
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

function roleNames(value) {
  return asList(value, "roles")
    .map((entry) => {
      if (typeof entry === "string") {
        return entry.trim();
      }
      return typeof entry?.canonical_name === "string"
        ? entry.canonical_name.trim()
        : typeof entry?.name === "string"
          ? entry.name.trim()
          : "";
    })
    .filter(Boolean);
}

function capabilityValue(value) {
  const data = responseData(value);
  return {
    supported: data?.supported === true,
    platform: typeof data?.platform === "string" ? data.platform : null,
    reason: typeof data?.reason === "string" ? data.reason : null,
  };
}

function clearPanelPreview(panel) {
  if (panel && typeof panel === "object") {
    panel.previewUrl = "";
    panel.loading = false;
  }
}

export function createDashboardStore({ api }) {
  return {
    api,
    navItems: NAV_ITEMS,
    activePage: "panels",
    mobileNavOpen: false,
    pluginVersion: "",
    capabilities: null,
    bootstrapError: "",
    loading: true,
    errorMessage: "",

    panelSearch: "",
    panelRoles: [],
    selectedPanelRole: "",
    panelRolesLoading: false,
    panelImages: [],
    panelsLoading: false,
    panelError: "",
    panelActionBusy: false,
    pendingPanelFile: null,

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

    toast: {
      open: false,
      message: "",
      tone: "info",
    },
    dialog: blankDialog(),
    drawer: blankDrawer(),

    get activePageLabel() {
      return this.navItems.find((item) => item.id === this.activePage)?.label || "面板图";
    },

    get filteredPanels() {
      const query = this.panelSearch.trim().toLocaleLowerCase();
      if (!query) {
        return this.panelRoles;
      }
      return this.panelRoles.filter((role) => role.toLocaleLowerCase().includes(query));
    },

    get selectedTask() {
      return this.tasks.find((task) => task.id === this.selectedTaskId) || null;
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

      await this.loadRoleCatalog();
      await this.loadMembershipCapability();
      await this.reloadTaskState();
      await this.reloadPanelState();
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
      this.pendingPanelFile = null;
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
      this.drawer = {
        ...blankDrawer(),
        ...options,
        open: true,
      };
    },

    closeDrawer() {
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

    async loadRoleCatalog() {
      this.panelRolesLoading = true;
      try {
        this.panelRoles = roleNames(await this.api.getAliasCatalog());
        if (!this.selectedPanelRole && this.panelRoles.length > 0) {
          this.selectedPanelRole = this.panelRoles[0];
        }
      } catch (_error) {
        this.panelRoles = [];
        this.panelError = "角色目录读取失败，请稍后重试";
      } finally {
        this.panelRolesLoading = false;
      }
    },

    async selectPanelRole(roleName) {
      const normalized = String(roleName || "").trim();
      if (!normalized) {
        this.showToast("请先选择或输入角色名称", "error");
        return;
      }
      this.selectedPanelRole = normalized;
      await this.reloadPanelState();
    },

    async reloadPanelState() {
      this.panelsLoading = true;
      this.panelError = "";
      this.panelImages.forEach(clearPanelPreview);
      if (!this.selectedPanelRole) {
        this.panelImages = [];
        this.panelsLoading = false;
        return;
      }
      try {
        const data = asList(await this.api.getPanelImages(this.selectedPanelRole), "images");
        this.panelImages = data.map((panel) => ({
          ...panel,
          previewUrl: "",
          loading: false,
        }));
      } catch (error) {
        this.panelImages = [];
        this.panelError = safeErrorMessage(error);
      } finally {
        this.panelsLoading = false;
      }
    },

    panelImageUrl(panel) {
      return panel?.previewUrl || "";
    },

    async loadPanelImage(panel) {
      if (!panel || panel.loading || panel.previewUrl || !this.selectedPanelRole) {
        return;
      }
      panel.loading = true;
      try {
        const payload = responseData(
          await this.api.getPanelImage(this.selectedPanelRole, panel.id),
        );
        if (typeof payload?.data !== "string") {
          throw new Error("面板图载荷无效");
        }
        const mediaType = typeof payload.media_type === "string" ? payload.media_type : "image/png";
        panel.previewUrl = `data:${mediaType};base64,${payload.data}`;
      } catch (error) {
        this.showToast(safeErrorMessage(error), "error");
      } finally {
        panel.loading = false;
      }
    },

    prepareUploadPanel(event) {
      const file = event?.target?.files?.[0];
      if (!file || !this.selectedPanelRole) {
        return;
      }
      this.pendingPanelFile = file;
      if (event.target) {
        event.target.value = "";
      }
      this.openDialog({
        title: "确认上传面板图",
        description: `将把「${file.name}」上传到角色「${this.selectedPanelRole}」。`,
        confirmLabel: "上传面板图",
        onConfirm: () => this.uploadPanel(),
      });
    },

    async uploadPanel(event) {
      const file = event?.target?.files?.[0] || this.pendingPanelFile;
      if (!file || !this.selectedPanelRole) {
        return;
      }
      this.panelActionBusy = true;
      try {
        await this.api.uploadPanel(this.selectedPanelRole, file);
        await this.reloadPanelState();
        this.showToast("面板图已上传");
      } catch (error) {
        this.showToast(safeErrorMessage(error), "error");
      } finally {
        this.pendingPanelFile = null;
        this.panelActionBusy = false;
      }
    },

    confirmDeletePanel(panel) {
      if (!panel) {
        return;
      }
      this.openDialog({
        title: "确认删除面板图",
        description: `将删除「${panel.filename || panel.id}」，此操作不可恢复。`,
        confirmLabel: "删除面板图",
        onConfirm: () => this.deletePanel(panel),
      });
    },

    async deletePanel(panel) {
      this.panelActionBusy = true;
      try {
        await this.api.deletePanel(this.selectedPanelRole, panel.id);
        await this.reloadPanelState();
        this.showToast("面板图已删除");
      } catch (error) {
        this.showToast(safeErrorMessage(error), "error");
      } finally {
        this.panelActionBusy = false;
      }
    },

    confirmDeleteAllPanels() {
      if (!this.selectedPanelRole) {
        return;
      }
      this.openDialog({
        title: "确认删除当前角色全部面板图",
        description: `将永久删除「${this.selectedPanelRole}」的全部面板图，此操作不可恢复。`,
        confirmLabel: "删除全部",
        onConfirm: () => this.deleteAllPanels(),
      });
    },

    async deleteAllPanels() {
      this.panelActionBusy = true;
      try {
        await this.api.deleteAllPanels(this.selectedPanelRole);
        await this.reloadPanelState();
        this.showToast("当前角色的面板图已全部删除");
      } catch (error) {
        this.showToast(safeErrorMessage(error), "error");
      } finally {
        this.panelActionBusy = false;
      }
    },

    confirmCompressPanels() {
      this.openDialog({
        title: "确认压缩全部面板图",
        description: "将处理所有角色的自定义面板图，已有文件会按服务端规则压缩。",
        confirmLabel: "开始压缩",
        onConfirm: () => this.compressPanels(),
      });
    },

    async compressPanels() {
      this.panelActionBusy = true;
      try {
        const result = responseData(await this.api.compressPanels());
        await this.reloadPanelState();
        const count = Number(result?.compressed);
        this.showToast(Number.isFinite(count) ? `已压缩 ${count} 张面板图` : "面板图压缩完成");
      } catch (error) {
        this.showToast(safeErrorMessage(error), "error");
      } finally {
        this.panelActionBusy = false;
      }
    },

    formatBytes(value) {
      const bytes = Number(value);
      if (!Number.isFinite(bytes) || bytes < 0) {
        return "大小未知";
      }
      if (bytes < 1024) {
        return `${bytes} B`;
      }
      if (bytes < 1024 * 1024) {
        return `${(bytes / 1024).toFixed(1)} KB`;
      }
      return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
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
