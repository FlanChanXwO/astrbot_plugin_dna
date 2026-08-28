const NAV_ITEMS = Object.freeze([
  { id: "panels", label: "面板图" },
  { id: "tasks", label: "任务与探测" },
  { id: "accounts", label: "账号与预览" },
  { id: "aliases", label: "角色别名" },
]);

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

function safeErrorMessage(error) {
  return error instanceof Error && error.message ? error.message : "无法连接管理服务";
}

export function createDashboardStore({ api }) {
  return {
    api,
    navItems: NAV_ITEMS,
    activePage: "panels",
    mobileNavOpen: false,
    pluginVersion: "",
    capabilities: null,
    loading: true,
    errorMessage: "",
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

    async initialize() {
      this.loading = true;
      this.errorMessage = "";
      try {
        const response = await this.api.getBootstrap();
        const payload = response?.data && typeof response.data === "object" ? response.data : response;
        this.pluginVersion = payload?.version || payload?.plugin_version || "";
        this.capabilities = payload?.capabilities || {};
      } catch (error) {
        this.fail(error);
      } finally {
        this.loading = false;
      }
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
  };
}
