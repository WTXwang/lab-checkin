(function () {
  "use strict";

  // ---------- 状态 ----------
  const state = {
    classes: [],
    experiments: [],
    course: null, // {id, name, role}，当前进入的课程；null = 在课程列表
    currentClass: null, // {id, name}，班级管理子界面中进入的班级；null = 班级列表态
    regClass: null, // {id, name}，登记页选择的班级
    regExperiment: null, // {id, name}，登记页选择的实验
    meId: null,
    isSuperAdmin: false,
  };

  // ---------- DOM ----------
  const $ = (id) => document.getElementById(id);
  const views = {
    login: $("view-login"),
    signup: $("view-signup"),
    courses: $("view-courses"),
    register: $("view-register"),
    manage: $("view-manage"),
    overview: $("view-overview"),
    admin: $("view-admin"),
    classManage: $("view-class-manage"),
    globalAdmin: $("view-admin-global"),
  };

  // ---------- API 封装 ----------
  async function req(url, opts = {}) {
    const res = await fetch(url, opts);
    if (res.status === 401) {
      let detail = "未登录";
      try {
        const body = await res.json();
        if (body && body.detail) detail = body.detail;
      } catch (e) {}
      state.course = null;
      showView("login");
      throw new Error(detail);
    }
    if (!res.ok) {
      let detail = "请求失败 (" + res.status + ")";
      try {
        const body = await res.json();
        if (body && body.detail) detail = body.detail;
      } catch (e) {}
      // 课程被删 / 被移出成员时回到课程列表
      if (detail === "课程不存在" || detail === "你不是该课程的成员") {
        state.course = null;
        showView("courses");
      }
      throw new Error(detail);
    }
    return res.json();
  }
  const api = {
    get: (url) => req(url),
    post: (url, data) =>
      req(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data || {}),
      }),
    del: (url) => req(url, { method: "DELETE" }),
    put: (url, data) =>
      req(url, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data || {}),
      }),
  };

  // 当前课程内接口的统一前缀
  const cPath = (p) => "/api/courses/" + state.course.id + p;

  // ---------- 视图切换 ----------
  const COURSE_VIEWS = ["register", "manage", "overview", "admin", "classManage"];

  function showView(name) {
    if (COURSE_VIEWS.includes(name) && !state.course) name = "courses";
    persistView(name);
    clearInputs(name);
    for (const key in views) views[key].classList.toggle("hidden", key !== name);
    if (name === "courses") {
      ["drawer-manage", "drawer-overview", "drawer-admin", "drawer-admin-class"].forEach((id) =>
        $(id).classList.add("hidden")
      );
      loadCourses();
    } else if (name === "globalAdmin") {
      ["drawer-manage", "drawer-overview", "drawer-admin", "drawer-admin-class"].forEach((id) =>
        $(id).classList.add("hidden")
      );
      loadGlobalAdmin();
    } else if (name !== "login" && name !== "signup") {
      updateCourseTitle();
      const isAdmin = state.course.role === "admin";
      $("drawer-manage").classList.toggle("hidden", !isAdmin);
      $("drawer-overview").classList.toggle("hidden", !isAdmin);
      $("drawer-admin").classList.toggle("hidden", !isAdmin);
      $("drawer-admin-class").classList.toggle("hidden", !isAdmin);
      if (name === "register") renderRegisterPage();
      if (name === "overview") loadOverview();
      if (name === "admin") {
        loadAdminData();
        loadMembers();
      }
      if (name === "classManage") renderClassManage();
    }
  }

  // 记住当前视图与课程（按设备存储），刷新页面后恢复现场
  function persistView(name) {
    if (name === "courses" || name === "globalAdmin") {
      localStorage.setItem("checkin_last_view", name);
      localStorage.removeItem("checkin_last_course");
      localStorage.removeItem("checkin_last_class");
    } else if (COURSE_VIEWS.includes(name) && state.course) {
      localStorage.setItem("checkin_last_view", name);
      localStorage.setItem(
        "checkin_last_course",
        JSON.stringify({ id: state.course.id, name: state.course.name, role: state.course.role })
      );
      if (name === "classManage" && state.currentClass) {
        localStorage.setItem("checkin_last_class", JSON.stringify(state.currentClass));
      } else {
        localStorage.removeItem("checkin_last_class");
      }
    }
    // login/signup 不覆盖持久化状态
  }

  // 切视图/切课程时清空该视图的表单与查询状态，避免残留上一个课程或上一个视图的内容
  function clearInputs(name) {
    if (name === "register") {
      $("register-student-no").value = "";
      $("register-result").innerHTML = "";
    } else if (name === "manage") {
      $("manage-student-no").value = "";
      $("manage-result").innerHTML = "";
    } else if (name === "admin") {
      $("new-experiment").value = "";
      $("invite-new-code").innerHTML = "";
    } else if (name === "courses") {
      $("new-course").value = "";
      $("invite-code").value = "";
      $("invite-preview").innerHTML = "";
    } else if (name === "signup") {
      $("signup-username").value = "";
      $("signup-display-name").value = "";
      $("signup-password").value = "";
      $("signup-password2").value = "";
      $("signup-error").textContent = "";
    } else if (name === "classManage") {
      $("cls-new-class").value = "";
      $("cls-import-file").value = "";
      $("cls-import-result").textContent = "";
      $("cls-new-student-no").value = "";
      $("cls-new-student-name").value = "";
    }
  }

  function updateCourseTitle() {
    document.querySelectorAll(".course-title-name").forEach((el) => {
      el.textContent = state.course ? state.course.name : "课程";
    });
  }

  function toggleMenu(open) {
    $("menu-drawer").classList.toggle("open", open);
    $("menu-overlay").classList.toggle("open", open);
  }

  // ---------- 工具 ----------
  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function fmtTime(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d)) return iso;
    const p = (n) => String(n).padStart(2, "0");
    return (
      d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) +
      " " + p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds())
    );
  }

  function fmtShort(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d)) return iso;
    const p = (n) => String(n).padStart(2, "0");
    return p(d.getMonth() + 1) + "-" + p(d.getDate()) + " " + p(d.getHours()) + ":" + p(d.getMinutes());
  }

  function toLocalInput(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d)) return "";
    const p = (n) => String(n).padStart(2, "0");
    return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) +
      "T" + p(d.getHours()) + ":" + p(d.getMinutes());
  }

  // ---------- 登录 / 注册 ----------
  function applyMe(me) {
    state.meId = me.id;
    state.isSuperAdmin = me.is_super_admin === true || me.role === "super_admin";
    $("courses-user").textContent =
      "你好，" + (me.operator || me.display_name || me.username || "");
    $("btn-global-admin").classList.toggle("hidden", !state.isSuperAdmin);
  }

  async function doLogin(e) {
    e.preventDefault();
    const username = $("login-username").value.trim();
    const password = $("login-password").value;
    const err = $("login-error");
    err.textContent = "";
    if (!username || !password) {
      err.textContent = "请输入用户名和密码";
      return;
    }
    try {
      const res = await api.post("/api/login", { username, password });
      $("login-password").value = "";
      applyMe(res);
      showView("courses");
    } catch (ex) {
      err.textContent = ex.message;
    }
  }

  async function doSignup(e) {
    e.preventDefault();
    const username = $("signup-username").value.trim();
    const displayName = $("signup-display-name").value.trim();
    const password = $("signup-password").value;
    const password2 = $("signup-password2").value;
    const err = $("signup-error");
    err.textContent = "";
    if (!username || !password) {
      err.textContent = "请填写用户名和密码";
      return;
    }
    if (password !== password2) {
      err.textContent = "两次输入的密码不一致";
      return;
    }
    try {
      const res = await api.post("/api/register", { username, password, display_name: displayName });
      $("signup-password").value = "";
      $("signup-password2").value = "";
      applyMe(res);
      showView("courses");
    } catch (ex) {
      err.textContent = ex.message;
    }
  }

  function doLogout() {
    api.post("/api/logout").catch(() => {});
    state.course = null;
    state.currentClass = null;
    localStorage.removeItem("checkin_last_view");
    localStorage.removeItem("checkin_last_course");
    localStorage.removeItem("checkin_last_class");
    showView("login");
  }

  // ---------- 课程列表 ----------
  async function loadCourses() {
    try {
      const res = await api.get("/api/courses");
      renderCourses(res.courses || []);
    } catch (ex) {
      // 401 已跳登录
    }
  }

  function renderCourses(courses) {
    const listEl = $("course-list");
    if (!courses.length) {
      listEl.innerHTML =
        '<li class="muted">还没有课程——创建自己的课程，或输入邀请码加入别人的课程</li>';
      return;
    }
    listEl.innerHTML = courses
      .map((c) => {
        const isAdmin = c.role === "admin";
        return (
          '<li class="course-item" data-course-id="' + c.id +
          '" data-course-name="' + escapeHtml(c.name) +
          '" data-course-role="' + c.role + '">' +
          '<div class="course-info"><div class="course-name">' + escapeHtml(c.name) + "</div></div>" +
          '<span class="role-badge ' + c.role + '">' + (isAdmin ? "管理员" : "助教") + "</span>" +
          "</li>"
        );
      })
      .join("");
  }

  function enterCourse(c) {
    state.course = { id: c.id, name: c.name, role: c.role };
    state.currentClass = null;
    state.regClass = null;
    state.regExperiment = null;
    showView("register");
  }

  function backToCourses() {
    state.course = null;
    state.currentClass = null;
    showView("courses");
  }

  async function createCourse() {
    const name = $("new-course").value.trim();
    if (!name) {
      alert("请输入课程名称");
      return;
    }
    try {
      const res = await api.post("/api/courses", { name });
      $("new-course").value = "";
      enterCourse({ id: res.id, name: res.name, role: "admin" });
    } catch (ex) {
      alert(ex.message);
    }
  }

  // ---------- 加入课程（邀请码） ----------
  async function inviteLookup() {
    const code = $("invite-code").value.trim().toUpperCase();
    const el = $("invite-preview");
    if (!code) {
      el.innerHTML = '<p class="hint">请输入邀请码</p>';
      return;
    }
    try {
      const data = await api.get("/api/invites/" + encodeURIComponent(code));
      if (data.already_member) {
        el.innerHTML = '<p class="hint">你已经是课程「' + escapeHtml(data.course_name) + '」的成员</p>';
        return;
      }
      el.innerHTML =
        '<div class="invite-card">' +
        '<h2>课程「' + escapeHtml(data.course_name) + '」邀请你加入</h2>' +
        '<p class="hint">角色：助教 · 课程管理员：' + escapeHtml(data.admin_username) + "</p>" +
        '<button class="btn primary" data-accept-invite="' + escapeHtml(code) + '">接受邀请</button>' +
        "</div>";
    } catch (ex) {
      el.innerHTML = '<p class="hint">' + escapeHtml(ex.message) + "</p>";
    }
  }

  async function acceptInvite(code) {
    try {
      const res = await api.post("/api/invites/accept", { code });
      $("invite-code").value = "";
      $("invite-preview").innerHTML = "";
      await loadCourses();
      alert("已加入课程「" + res.course_name + "」");
    } catch (ex) {
      alert(ex.message);
    }
  }

  // ---------- 成员与邀请管理（课程管理员） ----------
  async function loadMembers() {
    await Promise.all([renderMembers(), renderInvites()]);
  }

  async function renderMembers() {
    try {
      const res = await api.get(cPath("/members"));
      const members = res.members || [];
      $("member-list").innerHTML =
        members
          .map((m) => {
            const isAdmin = m.role === "admin";
            const label = escapeHtml(m.username) +
              (m.display_name && m.display_name !== m.username
                ? ' <span class="muted">' + escapeHtml(m.display_name) + "</span>"
                : "");
            return (
              "<li><span>" + label + "</span>" +
              '<span class="role-badge ' + m.role + '">' + (isAdmin ? "管理员" : "助教") + "</span>" +
              (isAdmin
                ? ""
                : '<button class="btn ghost small" data-remove-member="' + m.user_id + '">移除</button>') +
              "</li>"
            );
          })
          .join("") || '<li class="muted">暂无成员</li>';
    } catch (ex) {
      $("member-list").innerHTML = '<li class="muted">加载失败</li>';
    }
  }

  async function renderInvites() {
    try {
      const res = await api.get(cPath("/invites"));
      const invites = res.invites || [];
      $("invite-list").innerHTML =
        invites
          .map((i) => {
            const status = i.used_at
              ? "已被 " + escapeHtml(i.used_username || "") + " 使用"
              : "待使用";
            return (
              "<li><span class=\"invite-code\">" + escapeHtml(i.code) + "</span>" +
              '<span class="muted">' + status + "</span>" +
              '<button class="btn ghost small" data-revoke-invite="' + i.id + '">撤销</button></li>'
            );
          })
          .join("") || '<li class="muted">暂无邀请码</li>';
    } catch (ex) {
      $("invite-list").innerHTML = '<li class="muted">加载失败</li>';
    }
  }

  async function createInvite() {
    try {
      const res = await api.post(cPath("/invites"), {});
      $("invite-new-code").innerHTML =
        '新邀请码：<span class="invite-code">' + escapeHtml(res.code) + "</span>（7 天有效，一次性）";
      await renderInvites();
    } catch (ex) {
      alert(ex.message);
    }
  }

  async function revokeInvite(id) {
    if (!confirm("撤销该邀请码？")) return;
    try {
      await api.del(cPath("/invites/" + id));
      await renderInvites();
    } catch (ex) {
      alert(ex.message);
    }
  }

  async function removeMember(userId) {
    if (!confirm("移除该助教？移除后对方将无法访问此课程")) return;
    try {
      await api.del(cPath("/members/" + userId));
      await renderMembers();
    } catch (ex) {
      alert(ex.message);
    }
  }

  // ---------- 全局管理（超级管理员） ----------
  async function loadGlobalAdmin() {
    await Promise.all([renderAdminUsers(), renderAdminCourses()]);
  }

  async function renderAdminUsers() {
    try {
      const res = await api.get("/api/admin/users");
      const users = res.users || [];
      $("user-admin-list").innerHTML = users
        .map((u) => {
          const label = escapeHtml(u.username) +
            (u.display_name && u.display_name !== u.username
              ? ' <span class="muted">' + escapeHtml(u.display_name) + "</span>"
              : "");
          const badge = u.role === "super_admin" ? ' <span class="role-badge super_admin">超管</span>' : "";
          const action = u.id === state.meId
            ? '<span class="muted">自己</span>'
            : '<button class="btn ghost small danger-text" data-del-user="' + u.id + '">删除</button>';
          return "<li><span>" + label + badge + "</span>" + action + "</li>";
        })
        .join("");
    } catch (ex) {
      $("user-admin-list").innerHTML = '<li class="muted">加载失败</li>';
    }
  }

  async function renderAdminCourses() {
    try {
      const res = await api.get("/api/admin/courses");
      const courses = res.courses || [];
      $("course-admin-list").innerHTML =
        courses
          .map((c) => {
            return (
              "<li><span>" + escapeHtml(c.name) +
              ' <span class="muted">创建者：' + escapeHtml(c.owner_username) + " · " + c.member_count + " 名成员</span></span>" +
              '<button class="btn ghost small danger-text" data-del-course-admin="' + c.id + '">删除</button></li>'
            );
          })
          .join("") || '<li class="muted">暂无课程</li>';
    } catch (ex) {
      $("course-admin-list").innerHTML = '<li class="muted">加载失败</li>';
    }
  }

  async function deleteUserAdmin(id) {
    if (!confirm("删除该用户？其创建的课程及所有数据都会被删除，且不可恢复！")) return;
    try {
      await api.del("/api/admin/users/" + id);
      await Promise.all([renderAdminUsers(), renderAdminCourses()]);
    } catch (ex) {
      alert(ex.message);
    }
  }

  async function deleteCourseAdmin(id) {
    if (!confirm("删除该课程？课程下所有班级、学生、完成记录都会被删除，且不可恢复！")) return;
    try {
      await api.del("/api/admin/courses/" + id);
      await renderAdminCourses();
    } catch (ex) {
      alert(ex.message);
    }
  }

  // ---------- 管理页 ----------
  async function loadAdminData() {
    await renderAdminExperiments();
  }

  async function renderAdminExperiments() {
    const res = await api.get(cPath("/experiments"));
    state.experiments = res.experiments || [];
    $("experiment-list").innerHTML =
      state.experiments
        .map(
          (e) =>
            "<li><span>" + escapeHtml(e.name) + '</span><button class="btn ghost small" data-del-exp="' + e.id + '">删除</button></li>'
        )
        .join("") || '<li class="muted">暂无实验</li>';
  }

  async function addExperiment() {
    const name = $("new-experiment").value.trim();
    if (!name) {
      alert("请输入实验名称");
      return;
    }
    try {
      await api.post(cPath("/experiments"), { name });
      $("new-experiment").value = "";
      await renderAdminExperiments();
    } catch (ex) {
      alert(ex.message);
    }
  }

  async function handleAdminClick(e) {
    const del = e.target.closest("button[data-del-exp]");
    if (!del) return;
    if (!confirm("删除该实验会同时删除所有班级在该实验下的完成记录，确定？")) return;
    try {
      await api.del(cPath("/experiments/" + del.dataset.delExp));
      await renderAdminExperiments();
    } catch (ex) {
      alert(ex.message);
    }
  }

  // ---------- 班级管理子界面 ----------
  function renderClassManage() {
    const backBtn = $("btn-cls-back");
    if (state.currentClass) {
      // 班级详情态：左上角显示「‹ 返回」，点击回班级列表
      backBtn.textContent = "‹ 返回";
      backBtn.title = "返回班级列表";
      $("cls-list-panel").classList.add("hidden");
      $("cls-detail-panel").classList.remove("hidden");
      $("class-manage-title").textContent = state.currentClass.name + " · 班级管理";
      renderClassStudents();
    } else {
      // 班级列表态：左上角显示 🏠，点击回课程列表首页
      backBtn.textContent = "🏠";
      backBtn.title = "返回课程列表";
      $("cls-list-panel").classList.remove("hidden");
      $("cls-detail-panel").classList.add("hidden");
      $("class-manage-title").textContent = "班级管理";
      loadClassManageList();
    }
  }

  async function loadClassManageList() {
    try {
      const res = await api.get(cPath("/classes"));
      state.classes = res.classes || [];
      $("cls-class-list").innerHTML =
        state.classes
          .map(
            (c) =>
              "<li><span>" + escapeHtml(c.name) + ' <span class="muted">' + c.count + " 人</span></span>" +
              '<span><button class="btn ghost small" data-cls-manage="' + c.id + '" data-cls-name="' + escapeHtml(c.name) + '">管理</button> ' +
              '<button class="btn ghost small" data-cls-del="' + c.id + '">删除</button></span></li>'
          )
          .join("") || '<li class="muted">暂无班级，请先创建</li>';
    } catch (ex) {
      $("cls-class-list").innerHTML = '<li class="muted">加载失败</li>';
    }
  }

  function openClassDetail(classId, className) {
    state.currentClass = { id: classId, name: className };
    localStorage.setItem("checkin_last_class", JSON.stringify(state.currentClass));
    renderClassManage();
  }

  function backClassList() {
    state.currentClass = null;
    localStorage.removeItem("checkin_last_class");
    renderClassManage();
  }

  async function addClassInManage() {
    const name = $("cls-new-class").value.trim();
    if (!name) {
      alert("请输入班级名称");
      return;
    }
    try {
      await api.post(cPath("/classes"), { name });
      $("cls-new-class").value = "";
      await loadClassManageList();
    } catch (ex) {
      alert(ex.message);
    }
  }

  async function deleteClassInManage(id) {
    const cls = state.classes.find((c) => c.id === id);
    const name = cls ? cls.name : "该班级";
    if (!confirm("删除班级「" + name + "」会同时删除其所有学生和完成记录，且不可恢复，确定？")) return;
    try {
      await api.del(cPath("/classes/" + id));
      await loadClassManageList();
    } catch (ex) {
      alert(ex.message);
    }
  }

  async function renderClassStudents() {
    const listEl = $("cls-student-list");
    try {
      const res = await api.get(cPath("/students?class_id=" + state.currentClass.id));
      const students = res.students || [];
      listEl.innerHTML =
        students
          .map(
            (s) =>
              "<li><span>" + escapeHtml(String(s.student_no)) + ' <span class="muted">' + escapeHtml(s.name) + "</span></span>" +
              '<button class="btn ghost small" data-cls-del-student="' + s.id + '">删除</button></li>'
          )
          .join("") || '<li class="muted">该班级暂无学生，可手动添加或导入名单</li>';
    } catch (ex) {
      listEl.innerHTML = '<li class="muted">加载失败</li>';
    }
  }

  async function addClassStudent() {
    const studentNo = $("cls-new-student-no").value.trim();
    const name = $("cls-new-student-name").value.trim();
    if (!studentNo || !name) {
      alert("请填写学号和姓名");
      return;
    }
    try {
      await api.post(cPath("/students"), {
        class_id: state.currentClass.id,
        student_no: studentNo,
        name: name,
      });
      $("cls-new-student-no").value = "";
      $("cls-new-student-name").value = "";
      await renderClassStudents();
    } catch (ex) {
      alert(ex.message);
    }
  }

  async function handleClassStudentDelete(id) {
    if (!confirm("删除该学生会同时删除其所有完成记录，且不可恢复，确定？")) return;
    try {
      await api.del(cPath("/students/" + id));
      await renderClassStudents();
    } catch (ex) {
      alert(ex.message);
    }
  }

  async function importClassStudents() {
    const fileInput = $("cls-import-file");
    const file = fileInput.files[0];
    const result = $("cls-import-result");
    if (!file) {
      result.textContent = "请先选择文件";
      return;
    }
    result.textContent = "正在导入…";
    const fd = new FormData();
    fd.append("file", file);
    try {
      const res = await fetch(cPath("/import?class_id=" + state.currentClass.id), {
        method: "POST",
        body: fd,
      });
      if (!res.ok) {
        let detail = "导入失败";
        try {
          detail = (await res.json()).detail || detail;
        } catch (e) {}
        throw new Error(detail);
      }
      const data = await res.json();
      result.textContent =
        "导入完成：新增学生 " + data.added_students + " 人，跳过/更新 " + data.skipped + " 人" +
        (data.conflicts ? "，学号冲突 " + data.conflicts + " 人" : "");
      fileInput.value = "";
      await renderClassStudents();
    } catch (ex) {
      result.textContent = ex.message;
    }
  }

  // ---------- 总览 / 导出 ----------
  async function loadOverview() {
    try {
      const c = await api.get(cPath("/classes"));
      state.classes = c.classes || [];
    } catch (e) {
      return;
    }
    const sel = $("sel-overview-class");
    const prev = sel.value;
    sel.innerHTML =
      '<option value="">请选择班级</option>' +
      state.classes
        .map((c) => '<option value="' + c.id + '">' + escapeHtml(c.name) + "</option>")
        .join("");
    if (prev && state.classes.some((c) => String(c.id) === prev)) sel.value = prev;
    else if (state.classes.length) sel.value = String(state.classes[0].id);
    await renderOverview();
  }

  async function renderOverview() {
    const classId = $("sel-overview-class").value;
    const tableEl = $("overview-table");
    const hint = $("overview-hint");
    if (!classId) {
      tableEl.innerHTML = "";
      hint.classList.remove("hidden");
      hint.textContent = "请先选择班级";
      return;
    }
    let data;
    try {
      data = await api.get(cPath("/overview?class_id=" + classId));
    } catch (e) {
      return;
    }
    if (!data.experiments.length) {
      tableEl.innerHTML = "";
      hint.classList.remove("hidden");
      hint.textContent = "还没有实验，请先到「管理」页添加实验";
      return;
    }
    if (!data.students.length) {
      tableEl.innerHTML = "";
      hint.classList.remove("hidden");
      hint.textContent = "该班级还没有学生，请先到「管理」页导入名单";
      return;
    }
    hint.classList.add("hidden");
    renderOverviewTable(data);
  }

  function renderOverviewTable(data) {
    const exps = data.experiments;
    let html = "<thead><tr><th>学号</th><th>姓名</th>";
    for (const e of exps) html += "<th>" + escapeHtml(e.name) + "</th>";
    html += "<th>已完成</th></tr></thead><tbody>";
    for (const s of data.students) {
      html +=
        '<tr><td class="no-cell">' + escapeHtml(String(s.student_no)) +
        '</td><td class="name-cell">' + escapeHtml(s.name) + "</td>";
      for (const e of exps) {
        const cell = s.cells[String(e.id)];
        if (cell) {
          const t =
            escapeHtml(e.name) + " · " + fmtTime(cell.completed_at) +
            (cell.operator ? " · " + escapeHtml(cell.operator) : "");
          html += '<td class="cell done" title="' + t + '">' + fmtShort(cell.completed_at) +
            (cell.operator ? '<div class="cell-op">' + escapeHtml(cell.operator) + '</div>' : '') + '</td>';
        } else {
          html += '<td class="cell pending" title="' + escapeHtml(e.name) + ' · 未完成">—</td>';
        }
      }
      html += '<td class="done-count">' + s.done_count + "/" + exps.length + "</td></tr>";
    }
    html += "</tbody>";
    $("overview-table").innerHTML = html;
  }

  async function exportExcel() {
    const classId = $("sel-overview-class").value;
    if (!classId) {
      alert("请先选择班级");
      return;
    }
    try {
      const res = await fetch(cPath("/export?class_id=" + classId));
      if (!res.ok) {
        let detail = "导出失败";
        try {
          detail = (await res.json()).detail || detail;
        } catch (e) {}
        throw new Error(detail);
      }
      const blob = await res.blob();
      const cls = state.classes.find((c) => String(c.id) === classId);
      const filename = (cls ? cls.name : "班级") + "_完成情况.xlsx";
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (ex) {
      alert(ex.message);
    }
  }

  // ---------- 登记 ----------
  function renderRegisterPage() {
    if (state.regClass && state.regExperiment) {
      // 已选择班级与实验 → 显示工作台
      $("reg-select-panel").classList.add("hidden");
      $("reg-work-panel").classList.remove("hidden");
      $("reg-work-title").textContent = state.regClass.name + " · " + state.regExperiment.name;
      $("register-result").innerHTML = "";
      $("register-student-no").value = "";
    } else {
      // 未选择 → 显示选择面板
      $("reg-select-panel").classList.remove("hidden");
      $("reg-work-panel").classList.add("hidden");
      loadRegisterSelect();
    }
  }

  async function loadRegisterSelect() {
    try {
      const [c, e] = await Promise.all([
        api.get(cPath("/classes")),
        api.get(cPath("/experiments")),
      ]);
      state.classes = c.classes || [];
      state.experiments = e.experiments || [];
    } catch (ex) {
      return;
    }
    $("reg-sel-class").innerHTML =
      '<option value="">请选择班级</option>' +
      state.classes
        .map((c) => '<option value="' + c.id + '">' + escapeHtml(c.name) + "</option>")
        .join("");
    $("reg-sel-experiment").innerHTML =
      '<option value="">请选择实验</option>' +
      state.experiments
        .map((e) => '<option value="' + e.id + '">' + escapeHtml(e.name) + "</option>")
        .join("");
  }

  function enterRegWork() {
    const classId = $("reg-sel-class").value;
    const expId = $("reg-sel-experiment").value;
    if (!classId || !expId) {
      alert("请先选择班级和实验");
      return;
    }
    const cls = state.classes.find((c) => String(c.id) === classId);
    const exp = state.experiments.find((e) => String(e.id) === expId);
    state.regClass = { id: Number(classId), name: cls ? cls.name : "" };
    state.regExperiment = { id: Number(expId), name: exp ? exp.name : "" };
    renderRegisterPage();
  }

  function backRegSelect() {
    state.regClass = null;
    state.regExperiment = null;
    renderRegisterPage();
  }

  async function registerLookup() {
    const no = $("register-student-no").value.trim();
    const el = $("register-result");
    if (!no) {
      el.innerHTML = '<p class="hint">请输入学号</p>';
      return;
    }
    try {
      const data = await api.get(cPath("/student_lookup?student_no=" + encodeURIComponent(no)));
      if (!data.found) {
        el.innerHTML = '<p class="hint">未找到该学号的学生</p>';
        return;
      }
      renderRegisterCard(data, el);
    } catch (ex) {
      el.innerHTML = '<p class="hint">查询失败</p>';
    }
  }

  function renderRegisterCard(data, el) {
    const s = data.student;
    const exp = data.experiments.find((e) => e.id === state.regExperiment.id);
    if (!exp) {
      el.innerHTML = '<p class="hint">该实验不存在</p>';
      return;
    }
    let html =
      '<div class="card"><h2>' + escapeHtml(s.name) +
      ' <span class="muted">' + escapeHtml(s.student_no) + ' · ' + escapeHtml(s.class_name) + '</span></h2>';
    if (exp.completed) {
      html +=
        '<div class="manage-item">' +
        '<div class="manage-title"><span>' + escapeHtml(exp.name) + '</span>' +
        '<span><span class="badge ok">已完成</span>' +
        (exp.operator ? ' <span class="done-op">' + escapeHtml(exp.operator) + '</span>' : '') + '</span></div>' +
        '<div class="manage-actions">' +
        '<span class="done-time">' + fmtTime(exp.completed_at) + '</span>' +
        '<button class="btn undo small" data-reg-undo data-student="' + s.id + '" data-exp="' + exp.id + '">撤销</button>' +
        '</div></div>';
    } else {
      html +=
        '<div class="manage-item">' +
        '<div class="manage-title"><span>' + escapeHtml(exp.name) + '</span><span class="badge pending">未完成</span></div>' +
        '<div class="manage-actions">' +
        '<button class="btn primary small" data-register data-student="' + s.id + '" data-exp="' + exp.id + '">登记完成</button>' +
        '</div></div>';
    }
    html += "</div>";
    el.innerHTML = html;
  }

  async function doRegister(e) {
    const btn = e.target.closest("button[data-register]");
    if (!btn) return;
    try {
      await api.post(cPath("/completions"), {
        student_id: Number(btn.dataset.student),
        experiment_id: Number(btn.dataset.exp),
      });
      registerLookup();
    } catch (ex) {
      alert(ex.message);
    }
  }

  async function doUndoRegister(e) {
    const btn = e.target.closest("button[data-reg-undo]");
    if (!btn) return;
    if (!confirm("撤销该实验的完成记录？")) return;
    try {
      await api.del(
        cPath("/completions?student_id=" + btn.dataset.student + "&experiment_id=" + btn.dataset.exp)
      );
      registerLookup();
    } catch (ex) {
      alert(ex.message);
    }
  }

  // ---------- 更正 ----------
  async function manageLookup() {
    const no = $("manage-student-no").value.trim();
    const el = $("manage-result");
    if (!no) {
      el.innerHTML = '<p class="hint">请输入学号</p>';
      return;
    }
    try {
      const data = await api.get(cPath("/student_lookup?student_no=" + encodeURIComponent(no)));
      if (!data.found) {
        el.innerHTML = '<p class="hint">未找到该学号的学生</p>';
        return;
      }
      renderManage(data, el);
    } catch (ex) {
      el.innerHTML = '<p class="hint">查询失败</p>';
    }
  }

  function renderManage(data, el) {
    const s = data.student;
    let html =
      '<div class="card"><h2>' + escapeHtml(s.name) +
      ' <span class="muted">' + escapeHtml(s.student_no) + ' · ' + escapeHtml(s.class_name) + '</span></h2>' +
      '<p class="hint">已完成 <b>' + data.done_count + '</b> / ' + data.experiments.length + ' 个实验</p>';
    for (const e of data.experiments) {
      if (e.completed) {
        html +=
          '<div class="manage-item">' +
          '<div class="manage-title"><span>' + escapeHtml(e.name) + '</span>' +
          '<span><span class="badge ok">已完成</span>' +
          (e.operator ? ' <span class="done-op">' + escapeHtml(e.operator) + '</span>' : '') + '</span></div>' +
          '<div class="manage-actions">' +
          '<input type="datetime-local" class="dt-input" data-time-student="' + s.id + '" data-time-exp="' + e.id + '" value="' + toLocalInput(e.completed_at) + '">' +
          '<button class="btn small" data-save-time data-student="' + s.id + '" data-exp="' + e.id + '">保存</button>' +
          '<button class="btn undo small" data-undo data-student="' + s.id + '" data-exp="' + e.id + '">撤销</button>' +
          '</div></div>';
      } else {
        html +=
          '<div class="manage-item">' +
          '<div class="manage-title"><span>' + escapeHtml(e.name) + '</span><span class="badge pending">未完成</span></div>' +
          '<div class="manage-actions">' +
          '<button class="btn primary small" data-manage-register data-student="' + s.id + '" data-exp="' + e.id + '">登记完成</button>' +
          '</div></div>';
      }
    }
    html += '</div>';
    el.innerHTML = html;
  }

  async function handleManageClick(e) {
    const reg = e.target.closest("button[data-manage-register]");
    const undo = e.target.closest("button[data-undo]");
    const save = e.target.closest("button[data-save-time]");
    try {
      if (reg) {
        await api.post(cPath("/completions"), {
          student_id: Number(reg.dataset.student),
          experiment_id: Number(reg.dataset.exp),
        });
      } else if (undo) {
        if (!confirm("撤销该实验的完成记录？")) return;
        await api.del(
          cPath("/completions?student_id=" + undo.dataset.student + "&experiment_id=" + undo.dataset.exp)
        );
      } else if (save) {
        const input = document.querySelector(
          'input[data-time-student="' + save.dataset.student + '"][data-time-exp="' + save.dataset.exp + '"]'
        );
        const val = input ? input.value : "";
        if (!val) {
          alert("请先选择时间");
          return;
        }
        await api.put(cPath("/completions"), {
          student_id: Number(save.dataset.student),
          experiment_id: Number(save.dataset.exp),
          completed_at: val,
        });
      } else {
        return;
      }
      manageLookup();
    } catch (ex) {
      alert(ex.message);
    }
  }

  // ---------- 事件绑定 ----------
  function bind() {
    $("login-form").addEventListener("submit", doLogin);
    $("signup-form").addEventListener("submit", doSignup);
    $("go-register").addEventListener("click", (e) => {
      e.preventDefault();
      showView("signup");
    });
    $("go-login").addEventListener("click", (e) => {
      e.preventDefault();
      showView("login");
    });

    // 全局菜单
    document.querySelectorAll(".btn-menu").forEach((b) =>
      b.addEventListener("click", () => toggleMenu(true))
    );
    $("menu-overlay").addEventListener("click", () => toggleMenu(false));
    $("drawer-close").addEventListener("click", () => toggleMenu(false));
    $("menu-drawer").addEventListener("click", (e) => {
      const item = e.target.closest(".drawer-item");
      if (!item) return;
      toggleMenu(false);
      if (item.dataset.view === "logout") {
        doLogout();
        return;
      }
      showView(item.dataset.view);
    });

    // 课程列表页
    $("course-list").addEventListener("click", (e) => {
      const item = e.target.closest(".course-item");
      if (!item) return;
      enterCourse({
        id: Number(item.dataset.courseId),
        name: item.dataset.courseName,
        role: item.dataset.courseRole,
      });
    });
    $("btn-create-course").addEventListener("click", createCourse);
    $("new-course").addEventListener("keydown", (e) => {
      if (e.key === "Enter") createCourse();
    });
    $("btn-invite-lookup").addEventListener("click", inviteLookup);
    $("invite-code").addEventListener("keydown", (e) => {
      if (e.key === "Enter") inviteLookup();
    });
    $("invite-preview").addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-accept-invite]");
      if (!btn) return;
      acceptInvite(btn.dataset.acceptInvite);
    });
    $("btn-courses-logout").addEventListener("click", doLogout);
    $("btn-global-admin").addEventListener("click", () => showView("globalAdmin"));
    $("btn-back-from-global").addEventListener("click", () => showView("courses"));

    // 课程内返回
    document.querySelectorAll(".btn-back-courses").forEach((b) =>
      b.addEventListener("click", backToCourses)
    );

    // 成员与邀请管理
    $("btn-new-invite").addEventListener("click", createInvite);
    $("member-list").addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-remove-member]");
      if (!btn) return;
      removeMember(Number(btn.dataset.removeMember));
    });
    $("invite-list").addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-revoke-invite]");
      if (!btn) return;
      revokeInvite(Number(btn.dataset.revokeInvite));
    });

    // 全局管理
    $("user-admin-list").addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-del-user]");
      if (!btn) return;
      deleteUserAdmin(Number(btn.dataset.delUser));
    });
    $("course-admin-list").addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-del-course-admin]");
      if (!btn) return;
      deleteCourseAdmin(Number(btn.dataset.delCourseAdmin));
    });

    $("btn-export").addEventListener("click", exportExcel);
    $("sel-overview-class").addEventListener("change", renderOverview);
    $("btn-do-register").addEventListener("click", registerLookup);
    $("register-student-no").addEventListener("keydown", (e) => {
      if (e.key === "Enter") registerLookup();
    });
    $("register-result").addEventListener("click", (e) => {
      if (e.target.closest("button[data-register]")) doRegister(e);
      else if (e.target.closest("button[data-reg-undo]")) doUndoRegister(e);
    });
    $("btn-reg-enter").addEventListener("click", enterRegWork);
    $("btn-reg-back-select").addEventListener("click", backRegSelect);
    $("btn-do-manage").addEventListener("click", manageLookup);
    $("manage-student-no").addEventListener("keydown", (e) => {
      if (e.key === "Enter") manageLookup();
    });
    $("manage-result").addEventListener("click", handleManageClick);

    $("experiment-list").addEventListener("click", handleAdminClick);
    $("btn-add-experiment").addEventListener("click", addExperiment);

    // 班级管理子界面
    $("btn-cls-back").addEventListener("click", () => {
      if (state.currentClass) backClassList();
      else backToCourses();
    });
    $("btn-cls-import").addEventListener("click", importClassStudents);
    $("btn-cls-add-class").addEventListener("click", addClassInManage);
    $("cls-new-class").addEventListener("keydown", (e) => {
      if (e.key === "Enter") addClassInManage();
    });
    $("cls-class-list").addEventListener("click", (e) => {
      const manage = e.target.closest("button[data-cls-manage]");
      if (manage) {
        openClassDetail(Number(manage.dataset.clsManage), manage.dataset.clsName);
        return;
      }
      const del = e.target.closest("button[data-cls-del]");
      if (del) deleteClassInManage(Number(del.dataset.clsDel));
    });
    $("btn-cls-add-student").addEventListener("click", addClassStudent);
    $("cls-new-student-no").addEventListener("keydown", (e) => {
      if (e.key === "Enter") addClassStudent();
    });
    $("cls-new-student-name").addEventListener("keydown", (e) => {
      if (e.key === "Enter") addClassStudent();
    });
    $("cls-student-list").addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-cls-del-student]");
      if (!btn) return;
      handleClassStudentDelete(Number(btn.dataset.clsDelStudent));
    });
  }

  // ---------- 启动 ----------
  async function init() {
    bind();
    try {
      const me = await api.get("/api/me");
      if (me.authed) {
        applyMe(me);
        // 恢复上次的视图与课程（刷新后回到原页面）
        const lastView = localStorage.getItem("checkin_last_view");
        let lastCourse = null;
        try {
          lastCourse = JSON.parse(localStorage.getItem("checkin_last_course") || "null");
        } catch (e) {
          lastCourse = null;
        }
        if (lastCourse && lastCourse.id && COURSE_VIEWS.includes(lastView)) {
          state.course = lastCourse;
          if (lastView === "classManage") {
            let lastClass = null;
            try {
              lastClass = JSON.parse(localStorage.getItem("checkin_last_class") || "null");
            } catch (e) {
              lastClass = null;
            }
            if (lastClass && lastClass.id) state.currentClass = lastClass;
          }
          showView(lastView);
        } else if (lastView === "globalAdmin" && state.isSuperAdmin) {
          showView("globalAdmin");
        } else {
          showView("courses");
        }
      } else {
        showView("login");
      }
    } catch (e) {
      showView("login");
    }
  }

  init();
})();
