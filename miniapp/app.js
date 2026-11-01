/**
 * Nail Atelier — Telegram Mini App Client Engine
 */

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function getLocalDateString(d = new Date()) {
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

const tg = window.Telegram?.WebApp;
// The application may be served below a reverse-proxy path.
const miniAppPath = window.location.pathname;
const miniAppIndex = miniAppPath.lastIndexOf("/miniapp/");
const appPrefix = miniAppIndex >= 0 ? miniAppPath.slice(0, miniAppIndex) : "";
try {
  tg?.ready();
  tg?.expand();
} catch (e) {
  console.warn("Telegram WebApp initialization error:", e);
}

const app = {
  state: {
    salonInfo: null,
    currentUser: null,
    isAdmin: false,
    adminDate: getLocalDateString(),
    adminSubtab: "schedule",
    adminStatusFilter: "all",
    adminMasterFilter: "all",
    adminSearchQuery: "",
    adminScheduleRaw: null,
    adminServicesRaw: null,
    services: [],
    masters: [],
    categories: [],
    activeTab: "book",
    currentStep: 1,

    // Active booking selection
    selectedService: null,
    selectedMaster: null,
    selectedDate: null,
    selectedSlot: null,

    // Dev mode
    isDev: false,
    devUserId: "999000101",
  },

  elements: {
    devBanner: document.getElementById("devBanner"),
    devUserSelect: document.getElementById("devUserSelect"),
    themeToggleBtn: document.getElementById("themeToggleBtn"),
    userNameLabel: document.getElementById("userNameLabel"),
    userAvatar: document.getElementById("userAvatar"),
    adminRoleBadge: document.getElementById("adminRoleBadge"),
    loadingView: document.getElementById("loadingView"),
    bookView: document.getElementById("bookView"),
    myBookingsView: document.getElementById("myBookingsView"),
    aboutView: document.getElementById("aboutView"),
    adminView: document.getElementById("adminView"),
    adminNavTab: document.getElementById("adminNavTab"),
    categoryFilters: document.getElementById("categoryFilters"),
    servicesList: document.getElementById("servicesList"),
    mastersList: document.getElementById("mastersList"),
    datesStrip: document.getElementById("datesStrip"),
    slotsContainer: document.getElementById("slotsContainer"),
    serviceSummaryChip: document.getElementById("serviceSummaryChip"),
    myBookingsList: document.getElementById("myBookingsList"),
    adminBookingsList: document.getElementById("adminBookingsList"),
    adminBlocksList: document.getElementById("adminBlocksList"),
    toast: document.getElementById("toast"),
  },

  getInitialTab() {
    const searchParams = new URLSearchParams(window.location.search);
    const tabParam = searchParams.get("tab");
    if (tabParam === "book" || tabParam === "admin" || tabParam === "my_bookings" || tabParam === "about") {
      return tabParam;
    }
    const startAppParam = searchParams.get("startapp") || searchParams.get("tgWebAppStartParam");
    if (startAppParam) return startAppParam;

    if (window.location.hash) {
      const hashStr = window.location.hash.replace(/^#/, "");
      const hashParams = new URLSearchParams(hashStr);
      const hashTab = hashParams.get("tab");
      if (hashTab) return hashTab;
      const hashStart = hashParams.get("tgWebAppStartParam");
      if (hashStart) return hashStart;
    }

    if (window.Telegram?.WebApp?.initDataUnsafe?.start_param) {
      return window.Telegram.WebApp.initDataUnsafe.start_param;
    }

    return "book";
  },

  async init() {
    this.initTheme();
    this.initPhoneMask();
    this.initUserPreview();
    this.checkEnvironment();

    try {
      await this.loadInitialData();
      this.renderCategories();
      this.renderServices();
      this.renderMasters();
      this.initDateStrip();

      // Show initial tab based on parameters or permissions
      const initialTab = this.getInitialTab();
      if (initialTab === "admin" && (this.state.isAdmin || this.state.currentUser?.is_admin)) {
        await this.showTab("admin");
      } else {
        await this.showTab("book");
      }

      // Telegram BackButton integration
      if (tg?.BackButton) {
        tg.BackButton.onClick(() => {
          if (this.state.activeTab === "book" && this.state.currentStep > 1 && this.state.currentStep < 5) {
            this.prevStep();
          } else {
            tg.BackButton.hide();
          }
        });
      }
    } catch (err) {
      console.error("Initialization failed:", err);
      this.showToast("Ошибка загрузки данных: " + err.message);
      this.elements.bookView.innerHTML = `
        <div class="slots-empty" style="margin-top: 30px;">
          Не удалось загрузить данные студии.<br>
          <small>${err.message}</small><br><br>
          <button class="btn-primary" onclick="location.reload()">Повторить попытку</button>
        </div>`;
      this.elements.bookView.classList.remove("hidden");
    } finally {
      this.elements.loadingView.classList.add("hidden");
    }
  },

  initTheme() {
    const isDark = (tg && tg.colorScheme === "dark");
    if (isDark) {
      document.body.classList.add("dark-mode");
    }

    this.elements.themeToggleBtn?.addEventListener("click", () => {
      document.body.classList.toggle("dark-mode");
    });
  },

  initPhoneMask() {
    const bindMask = (phoneInput) => {
      if (!phoneInput) return;
      phoneInput.addEventListener("input", (e) => {
        let val = e.target.value.replace(/\D/g, "");
        if (!val) {
          e.target.value = "";
          return;
        }
        if (val.startsWith("7") || val.startsWith("8")) {
          val = val.substring(1);
        }
        let formatted = "+7 (";
        if (val.length > 0) {
          formatted += val.substring(0, 3);
        }
        if (val.length >= 4) {
          formatted += ") " + val.substring(3, 6);
        }
        if (val.length >= 7) {
          formatted += "-" + val.substring(6, 8);
        }
        if (val.length >= 9) {
          formatted += "-" + val.substring(8, 10);
        }
        e.target.value = formatted;
      });
    };

    bindMask(document.getElementById("clientPhoneInput"));
    bindMask(document.getElementById("manualClientPhone"));
  },

  initUserPreview() {
    // Instant optimistic hydration from Telegram WebApp
    const tgUser = tg?.initDataUnsafe?.user;
    if (tgUser) {
      const first = (tgUser.first_name || "").trim();
      const last = (tgUser.last_name || "").trim();
      const fullName = [first, last].filter(Boolean).join(" ") || first || "Клиент";
      if (this.elements.userNameLabel) {
        this.elements.userNameLabel.textContent = fullName;
      }
      if (this.elements.userAvatar) {
        if (tgUser.photo_url) {
          this.elements.userAvatar.innerHTML = `<img src="${tgUser.photo_url}" alt="${first}" class="avatar-img" onerror="this.parentElement.textContent='${(first || 'К')[0].toUpperCase()}';">`;
        } else {
          this.elements.userAvatar.textContent = (first || "К")[0].toUpperCase();
        }
      }
      const nameInput = document.getElementById("clientNameInput");
      if (nameInput && !nameInput.value) {
        nameInput.value = fullName;
      }
    }
  },

  checkEnvironment() {
    const hasInitData = Boolean(tg?.initData);
    if (!hasInitData) {
      // Browser preview mode
      this.state.isDev = true;
      this.elements.devBanner?.classList.remove("hidden");
      this.elements.devUserSelect?.addEventListener("change", (e) => {
        this.state.devUserId = e.target.value;
        this.loadUserData();
      });
    }
  },

  async apiRequest(path, options = {}) {
    const headers = {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    };

    if (tg?.initData) {
      headers["X-Telegram-Init-Data"] = tg.initData;
    } else if (this.state.isDev) {
      headers["X-Dev-User-Id"] = this.state.devUserId;
    }

    const response = await fetch(`${appPrefix}${path}`, { ...options, headers });
    if (!response.ok) {
      let detail = "Ошибка сервера";
      try {
        const errJson = await response.json();
        detail = errJson.detail || detail;
        if (Array.isArray(detail)) {
          detail = detail.map((e) => e.msg || JSON.stringify(e)).join(", ");
        }
      } catch (_) {}
      throw new Error(detail);
    }
    return response.json();
  },

  async loadInitialData() {
    const [salon, services, masters] = await Promise.all([
      this.apiRequest("/api/salon"),
      this.apiRequest("/api/services"),
      this.apiRequest("/api/masters"),
    ]);

    this.state.salonInfo = salon;
    if (!salon.server?.dev_mode && !tg?.initData) {
      this.state.isDev = false;
      this.elements.devBanner?.classList.add("hidden");
    }

    // Populate salon details into "About" view and header
    if (salon) {
      const salonObj = salon.salon || salon;
      const brandTitleEl = document.getElementById("brandTitle");
      if (brandTitleEl && (salonObj.tagline || salon.tagline)) {
        brandTitleEl.textContent = salonObj.tagline || salon.tagline;
      }
      const addrEl = document.getElementById("aboutAddress");
      const phoneEl = document.getElementById("aboutPhone");
      const hoursEl = document.getElementById("aboutWorkingHours");
      const descEl = document.getElementById("aboutDescription");
      const contactEl = document.getElementById("aboutContact");
      if (addrEl && salonObj.address) addrEl.textContent = salonObj.address;
      if (phoneEl && salonObj.phone) phoneEl.textContent = salonObj.phone;
      if (hoursEl && salonObj.working_hours) hoursEl.textContent = salonObj.working_hours;
      if (descEl && salonObj.description) descEl.textContent = salonObj.description;
      if (contactEl && (salonObj.contact_telegram || salonObj.phone)) {
        contactEl.textContent = salonObj.contact_telegram || salonObj.phone;
      }
    }
    const demoEl = document.getElementById("demoNotice");
    if (demoEl) {
      if (this.state.isDev) {
        demoEl.classList.remove("hidden");
      } else {
        demoEl.classList.add("hidden");
      }
    }
    this.state.services = services;
    this.state.masters = masters;

    // Distinct categories
    const catSet = new Set(services.map((s) => s.category));
    this.state.categories = ["Все", ...Array.from(catSet)];

    await this.loadUserData();
  },

  async loadUserData() {
    try {
      const user = await this.apiRequest("/api/me");
      this.state.currentUser = user;
      if (this.elements.userNameLabel) {
        this.elements.userNameLabel.textContent = user.full_name || "Клиент";
      }
      if (this.elements.userAvatar && !this.elements.userAvatar.querySelector("img")) {
        const cleanName = (user.full_name || "").trim();
        const initial = cleanName ? cleanName[0].toUpperCase() : "К";
        this.elements.userAvatar.textContent = initial;
      }
      if (user.is_admin || user.role === "admin") {
        this.state.isAdmin = true;
        this.elements.adminNavTab?.classList.remove("hidden");
        this.elements.adminRoleBadge?.classList.remove("hidden");
      }
      const phoneInput = document.getElementById("clientPhoneInput");
      if (phoneInput && user.phone) {
        phoneInput.value = user.phone;
      }
      const nameInput = document.getElementById("clientNameInput");
      if (nameInput && user.full_name && !user.full_name.includes("Пользователь")) {
        nameInput.value = user.full_name;
      }
    } catch (e) {
      console.warn("User load failed:", e);
    }
  },

  renderCategories() {
    this.elements.categoryFilters.innerHTML = this.state.categories
      .map(
        (cat, i) => `
        <button class="category-pill ${i === 0 ? "active" : ""}" 
                onclick="app.filterCategory('${cat}', this)">
          ${cat}
        </button>`
      )
      .join("");
  },

  filterCategory(category, pillEl) {
    document.querySelectorAll(".category-pill").forEach((el) => el.classList.remove("active"));
    pillEl.classList.add("active");
    this.renderServices(category);
  },

  renderServices(categoryFilter = "Все") {
    const filtered =
      categoryFilter === "Все"
        ? this.state.services
        : this.state.services.filter((s) => s.category === categoryFilter);

    if (filtered.length === 0) {
      this.elements.servicesList.innerHTML = `<div class="slots-empty">В этой категории нет активных услуг</div>`;
      return;
    }

    this.elements.servicesList.innerHTML = filtered
      .map(
        (s) => `
        <div class="service-card" onclick="app.selectService(${s.id})">
          <div class="service-top">
            <h3 class="service-name">${escapeHtml(s.name)}</h3>
            <span class="service-price">${s.price.toLocaleString("ru-RU")} ₽</span>
          </div>
          ${s.description ? `<p class="service-desc">${escapeHtml(s.description)}</p>` : ""}
          <div class="service-meta">
            <span class="badge-duration">${s.duration_minutes} мин</span>
            <span class="badge-duration" style="background:none; border:1px solid var(--border-color);">${escapeHtml(s.category || "")}</span>
          </div>
        </div>`
      )
      .join("");
  },

  selectService(serviceId) {
    const s = this.state.services.find((x) => x.id === serviceId);
    if (!s) return;
    this.state.selectedService = s;

    // Update summary chip
    this.elements.serviceSummaryChip.innerHTML = `
      <div>
        <strong>${escapeHtml(s.name)}</strong>
        <div style="font-size:11px; color:var(--text-muted);">${s.duration_minutes} мин · ${s.price} ₽</div>
      </div>
      <button class="back-link" style="margin:0;" onclick="app.setStep(1)">Изменить</button>
    `;

    this.setStep(2);
  },

  formatExperience(years) {
    if (!years) return "Опыт от 1 года";
    const mod10 = years % 10;
    const mod100 = years % 100;
    if (mod10 === 1 && mod100 !== 11) return `Стаж: ${years} год`;
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return `Стаж: ${years} года`;
    return `Стаж: ${years} лет`;
  },

  renderMasters() {
    const anyMasterCard = `
      <div class="master-card any-master" onclick="app.selectMaster(0)">
        <div class="master-avatar" style="background:var(--accent-color); color:var(--accent-text); font-weight:700;">✦</div>
        <div class="master-info">
          <div class="master-name">Любой свободный мастер</div>
          <div class="master-spec">Ближайшее свободное окно</div>
          <div class="master-exp">Подходит, если нужно как можно быстрее</div>
        </div>
      </div>
    `;

    this.elements.mastersList.innerHTML = anyMasterCard + this.state.masters
      .map(
        (m) => `
        <div class="master-card" onclick="app.selectMaster(${m.id})">
          <div class="master-avatar">${m.full_name[0]}</div>
          <div class="master-info">
            <div class="master-name">${m.full_name}</div>
            <div class="master-spec">${m.specialization}</div>
            <div class="master-exp">${this.formatExperience(m.experience_years)}</div>
          </div>
        </div>`
      )
      .join("");
  },

  selectMaster(masterId) {
    if (masterId === 0) {
      this.state.selectedMaster = {
        id: 0,
        full_name: "Любой свободный мастер",
        specialization: "Ближайший доступный специалист",
        experience_years: 0,
      };
    } else {
      const m = this.state.masters.find((x) => x.id === masterId);
      if (!m) return;
      this.state.selectedMaster = m;
    }
    this.setStep(3);
    this.loadSlots();
  },

  initDateStrip() {
    const daysCount = 14;
    const now = new Date();
    const dates = [];

    const weekdays = ["Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"];
    const months = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];

    for (let i = 0; i < daysCount; i++) {
      const d = new Date(now);
      d.setDate(now.getDate() + i);
      const year = d.getFullYear();
      const month = String(d.getMonth() + 1).padStart(2, "0");
      const day = String(d.getDate()).padStart(2, "0");
      const iso = `${year}-${month}-${day}`;
      dates.push({
        iso: iso,
        weekday: i === 0 ? "Сег" : i === 1 ? "Зав" : weekdays[d.getDay()],
        day: d.getDate(),
        month: months[d.getMonth()],
      });
    }

    this.state.selectedDate = dates[0].iso;

    this.elements.datesStrip.innerHTML = dates
      .map(
        (d, idx) => `
        <div class="date-item ${idx === 0 ? "active" : ""}" 
             data-date="${d.iso}"
             onclick="app.selectDate('${d.iso}', this)">
          <span class="date-weekday">${d.weekday}</span>
          <span class="date-day">${d.day}</span>
          <span class="date-month">${d.month}</span>
        </div>`
      )
      .join("");
  },

  selectDate(isoDate, el) {
    document.querySelectorAll(".date-item").forEach((item) => item.classList.remove("active"));
    el.classList.add("active");
    this.state.selectedDate = isoDate;
    this.loadSlots();
  },

  async loadSlots() {
    if (!this.state.selectedMaster || !this.state.selectedService || !this.state.selectedDate) {
      return;
    }

    this.elements.slotsContainer.innerHTML = `<div class="slots-loading">Загружаем свободные слоты...</div>`;

    try {
      const url = `/api/slots?master_id=${this.state.selectedMaster.id}&service_id=${this.state.selectedService.id}&date=${this.state.selectedDate}&include_unavailable=true`;
      const slots = await this.apiRequest(url);

      const availableCount = slots.filter((s) => s.available !== false).length;
      if (slots.length === 0 || availableCount === 0) {
        const busyGrid = slots.length > 0 ? `
          <div class="slots-grid" style="margin-top:12px;">
            ${slots.map((slot) => `
              <button class="slot-btn unavailable" disabled>
                <span>${slot.start_time}</span>
                <span class="slot-sub">${slot.reason === "break" ? "перерыв" : "занято"}</span>
              </button>
            `).join("")}
          </div>` : "";
        this.elements.slotsContainer.innerHTML = `
          <div class="slots-empty">
            На выбранную дату нет свободных окон продолжительностью ${this.state.selectedService.duration_minutes} мин.<br>
            Пожалуйста, выберите другой день или мастера.
          </div>${busyGrid}`;
        return;
      }

      this.elements.slotsContainer.innerHTML = `
        <div class="slots-grid">
          ${slots
            .map((slot) => {
              if (slot.available === false) {
                const subLabel = slot.reason === "break" ? "перерыв" : "занято";
                return `
                  <button class="slot-btn unavailable" disabled title="Время недоступно (${subLabel})">
                    <span>${slot.start_time}</span>
                    <span class="slot-sub">${subLabel}</span>
                  </button>`;
              }
              return `
                <button class="slot-btn" onclick="app.selectSlot('${slot.start_time}', '${slot.end_time}')">
                  <span>${slot.start_time}</span>
                </button>`;
            })
            .join("")}
        </div>`;
    } catch (err) {
      this.elements.slotsContainer.innerHTML = `<div class="slots-empty">Ошибка загрузки: ${err.message}</div>`;
    }
  },

  selectSlot(startTime, endTime) {
    this.state.selectedSlot = { startTime, endTime };
    this.setStep(4);
    this.renderReceipt();
  },

  renderReceipt() {
    const s = this.state.selectedService;
    const m = this.state.selectedMaster;
    const slot = this.state.selectedSlot;

    document.getElementById("receiptService").textContent = s.name;
    document.getElementById("receiptDuration").textContent = `${s.duration_minutes} мин`;
    document.getElementById("receiptMaster").textContent = m.full_name;

    const parts = this.state.selectedDate.split("-");
    const dFormatted = `${parts[2]}.${parts[1]}.${parts[0]}`;
    document.getElementById("receiptDateTime").textContent = `${dFormatted} в ${slot.startTime}`;
    document.getElementById("receiptPrice").textContent = `${s.price.toLocaleString("ru-RU")} ₽`;
  },

  async submitBooking() {
    const name = document.getElementById("clientNameInput").value.trim();
    const phone = document.getElementById("clientPhoneInput").value.trim();
    const comment = document.getElementById("clientCommentInput").value.trim();

    if (!name || !phone) {
      this.showToast("Пожалуйста, заполните имя и телефон");
      return;
    }

    const submitBtn = document.getElementById("submitBtn");
    submitBtn.disabled = true;
    submitBtn.textContent = "Бронируем время...";

    try {
      const payload = {
        master_id: this.state.selectedMaster.id,
        service_id: this.state.selectedService.id,
        date: this.state.selectedDate,
        start_time: this.state.selectedSlot.startTime,
        client_name: name,
        client_phone: phone,
        comment: comment || null,
      };

      const result = await this.apiRequest("/api/bookings", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      if (result.master) {
        this.state.selectedMaster = result.master;
      }

      this.renderSuccess(result.booking_id);
      this.setStep(5);
    } catch (err) {
      this.showToast("Не удалось записаться: " + err.message);
      submitBtn.disabled = false;
      submitBtn.textContent = "Записаться на маникюр";
    }
  },

  renderSuccess(bookingId) {
    const s = this.state.selectedService;
    const m = this.state.selectedMaster;
    const slot = this.state.selectedSlot;
    const parts = this.state.selectedDate.split("-");
    const dFormatted = `${parts[2]}.${parts[1]}.${parts[0]}`;

    document.getElementById("successDetails").innerHTML = `
      <div class="booking-receipt card" style="text-align:left; margin-bottom:16px;">
        <div class="receipt-row">
          <span class="receipt-label">Номер заявки:</span>
          <span class="receipt-value highlight">#${bookingId}</span>
        </div>
        <div class="receipt-row">
          <span class="receipt-label">Услуга:</span>
          <span class="receipt-value">${s.name}</span>
        </div>
        <div class="receipt-row">
          <span class="receipt-label">Мастер:</span>
          <span class="receipt-value">${m.full_name}</span>
        </div>
        <div class="receipt-row">
          <span class="receipt-label">Дата и время:</span>
          <span class="receipt-value">${dFormatted} в ${slot.startTime}</span>
        </div>
      </div>
    `;
  },

  setStep(stepNumber) {
    this.state.currentStep = stepNumber;

    // Update dots
    document.querySelectorAll(".step-dot").forEach((dot, idx) => {
      dot.classList.toggle("active", idx + 1 === stepNumber);
    });

    const stepMap = {
      1: "stepService",
      2: "stepMaster",
      3: "stepDateTime",
      4: "stepConfirm",
      5: "stepSuccess",
    };

    Object.values(stepMap).forEach((id) => {
      document.getElementById(id)?.classList.add("hidden");
    });

    document.getElementById(stepMap[stepNumber])?.classList.remove("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });

    // Manage native Telegram BackButton visibility
    if (tg?.BackButton) {
      if (stepNumber > 1 && stepNumber < 5) {
        tg.BackButton.show();
      } else {
        tg.BackButton.hide();
      }
    }
  },

  prevStep() {
    if (this.state.currentStep > 1) {
      this.setStep(this.state.currentStep - 1);
    }
  },

  resetBookingFlow() {
    this.state.selectedService = null;
    this.state.selectedMaster = null;
    this.state.selectedSlot = null;
    const submitBtn = document.getElementById("submitBtn");
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = "Записаться на маникюр";
    }
    this.setStep(1);
    this.showTab("book");
  },

  async showTab(tabName) {
    if (tabName === "book" && this.state.currentStep === 5) {
      this.resetBookingFlow();
    }
    this.state.activeTab = tabName;

    document.querySelectorAll(".nav-item").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tab === tabName);
    });

    this.elements.bookView?.classList.toggle("hidden", tabName !== "book");
    this.elements.myBookingsView?.classList.toggle("hidden", tabName !== "my_bookings");
    this.elements.aboutView?.classList.toggle("hidden", tabName !== "about");
    this.elements.adminView?.classList.toggle("hidden", tabName !== "admin");

    if (tabName === "my_bookings") {
      await this.loadMyBookings();
    } else if (tabName === "admin") {
      await this.loadAdminSchedule();
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  },

  async loadMyBookings() {
    this.elements.myBookingsList.innerHTML = `<div class="slots-loading">Загружаем ваши записи...</div>`;

    try {
      const bookings = await this.apiRequest("/api/bookings");
      if (bookings.length === 0) {
        this.elements.myBookingsList.innerHTML = `
          <div class="slots-empty">
            У вас пока нет оформленных записей.<br><br>
            <button class="btn-primary" onclick="app.showTab('book')">Записаться на маникюр</button>
          </div>`;
        return;
      }

      const statusLabels = {
        pending: "Ожидает подтверждения",
        confirmed: "Подтверждена",
        cancelled_by_client: "Отменена вами",
        cancelled_by_admin: "Отменена мастером",
        completed: "Завершена",
      };

      this.elements.myBookingsList.innerHTML = bookings
        .map((b) => {
          const parts = b.date.split("-");
          const dFormatted = `${parts[2]}.${parts[1]}.${parts[0]}`;
          const isCancelable = ["pending", "confirmed"].includes(b.status);

          return `
          <div class="booking-card">
            <div class="booking-card-top">
              <span class="booking-badge ${escapeHtml(b.status)}">${statusLabels[b.status] || escapeHtml(b.status)}</span>
              <span style="font-size:12px; color:var(--text-muted);">Запись #${b.id}</span>
            </div>
            <div class="booking-card-service">${escapeHtml(b.service_name)}</div>
            <div class="booking-card-details">
              <div>Мастер: <strong>${escapeHtml(b.master_name)}</strong></div>
              <div>Дата и время: <strong>${dFormatted} · ${b.start_time}—${b.end_time}</strong></div>
            </div>
            <div class="booking-card-footer">
              <span class="booking-card-price">${b.service_price.toLocaleString("ru-RU")} ₽</span>
              ${
                isCancelable
                  ? `<button class="btn-danger" onclick="app.cancelBooking(${b.id})">Отменить</button>`
                  : ""
              }
            </div>
          </div>`;
        })
        .join("");
    } catch (err) {
      this.elements.myBookingsList.innerHTML = `<div class="slots-empty">Ошибка загрузки: ${err.message}</div>`;
    }
  },

  async cancelBooking(bookingId) {
    const msg = `Вы действительно хотите отменить запись #${bookingId}?`;
    const doCancel = async () => {
      try {
        await this.apiRequest(`/api/bookings/${bookingId}/cancel`, { method: "POST" });
        this.showToast(`Запись #${bookingId} отменена`);
        await this.loadMyBookings();
      } catch (err) {
        this.showToast("Не удалось отменить запись: " + err.message);
      }
    };

    if (tg?.showConfirm) {
      tg.showConfirm(msg, (ok) => {
        if (ok) doCancel();
      });
    } else if (confirm(msg)) {
      doCancel();
    }
  },

  switchAdminSubtab(subtab) {
    this.state.adminSubtab = subtab;
    tg?.HapticFeedback?.impactOccurred("light");

    document.getElementById("btnSubtabSchedule")?.classList.toggle("active", subtab === "schedule");
    document.getElementById("btnSubtabServices")?.classList.toggle("active", subtab === "services");
    document.getElementById("btnSubtabMasters")?.classList.toggle("active", subtab === "masters");
    document.getElementById("btnSubtabStudio")?.classList.toggle("active", subtab === "studio");
    document.getElementById("btnSubtabAnalytics")?.classList.toggle("active", subtab === "analytics");

    document.getElementById("adminSubtabSchedule")?.classList.toggle("hidden", subtab !== "schedule");
    document.getElementById("adminSubtabServices")?.classList.toggle("hidden", subtab !== "services");
    document.getElementById("adminSubtabMasters")?.classList.toggle("hidden", subtab !== "masters");
    document.getElementById("adminSubtabStudio")?.classList.toggle("hidden", subtab !== "studio");
    document.getElementById("adminSubtabAnalytics")?.classList.toggle("hidden", subtab !== "analytics");

    if (subtab === "services") {
      this.loadAdminServices();
    } else if (subtab === "masters") {
      this.loadAdminMasters();
    } else if (subtab === "studio") {
      this.loadAdminStudioSettings();
    } else if (subtab === "analytics") {
      this.renderAdminAnalytics();
    } else {
      this.renderAdminBookings();
    }
  },

  async refreshAdminView() {
    tg?.HapticFeedback?.impactOccurred("medium");
    if (this.state.adminSubtab === "services") {
      await this.loadAdminServices();
    } else if (this.state.adminSubtab === "masters") {
      await this.loadAdminMasters();
    } else if (this.state.adminSubtab === "studio") {
      await this.loadAdminStudioSettings();
    } else {
      await this.loadAdminSchedule();
    }
  },

  setAdminStatusFilter(status, pillEl) {
    this.state.adminStatusFilter = status;
    tg?.HapticFeedback?.impactOccurred("light");
    document.querySelectorAll(".admin-filter-pill").forEach((el) => el.classList.remove("active"));
    if (pillEl) pillEl.classList.add("active");
    this.renderAdminBookings();
  },

  onAdminSearch(val) {
    this.state.adminSearchQuery = (val || "").trim().toLowerCase();
    this.renderAdminBookings();
  },

  onAdminMasterFilter(val) {
    this.state.adminMasterFilter = val;
    tg?.HapticFeedback?.impactOccurred("light");
    this.renderAdminBookings();
  },

  setAdminDate(modeOrIso) {
    const now = new Date();
    let target = modeOrIso;
    const todayBtn = document.getElementById("adminDateToday");
    const tmrBtn = document.getElementById("adminDateTomorrow");
    const dateInput = document.getElementById("adminDateInput");

    todayBtn?.classList.remove("active");
    tmrBtn?.classList.remove("active");

    if (modeOrIso === "today") {
      target = getLocalDateString(now);
      todayBtn?.classList.add("active");
    } else if (modeOrIso === "tomorrow") {
      const tmr = new Date(now);
      tmr.setDate(now.getDate() + 1);
      target = getLocalDateString(tmr);
      tmrBtn?.classList.add("active");
    }

    if (dateInput && target) {
      dateInput.value = target;
    }

    this.state.adminDate = target;
    const parts = target.split("-");
    const dFormatted = `${parts[2]}.${parts[1]}.${parts[0]}`;
    const dateLabel = document.getElementById("adminSelectedDateLabel");
    if (dateLabel) {
      dateLabel.textContent = (modeOrIso === "today") ? "сегодня" : (modeOrIso === "tomorrow") ? "завтра" : dFormatted;
    }
    const analyticsLabel = document.getElementById("analyticsDateLabel");
    if (analyticsLabel) {
      analyticsLabel.textContent = (modeOrIso === "today") ? "сегодня" : (modeOrIso === "tomorrow") ? "завтра" : dFormatted;
    }

    this.loadAdminSchedule();
  },

  async loadAdminSchedule() {
    const listEl = document.getElementById("adminBookingsList");
    if (listEl) listEl.innerHTML = `<div class="slots-loading">Загружаем расписание...</div>`;

    try {
      const data = await this.apiRequest(`/api/admin/schedule?date=${this.state.adminDate}`);
      this.state.adminScheduleRaw = data;

      // Update KPI cards
      const stats = data.stats || {};
      const revLabelEl = document.getElementById("adminKpiRevenueLabel");
      const revEl = document.getElementById("adminKpiRevenue");
      const totalEl = document.getElementById("adminKpiTotal");
      const pendingEl = document.getElementById("adminKpiPending");

      const todayIso = getLocalDateString(new Date());
      const isFutureDate = this.state.adminDate > todayIso;
      if (revLabelEl) {
        revLabelEl.textContent = isFutureDate ? "Ожидаемая касса" : "Выручка дня";
      }
      if (revEl) {
        const displayRev = isFutureDate
          ? (stats.expected_revenue ?? stats.revenue ?? 0)
          : (stats.revenue || 0);
        revEl.textContent = `${displayRev.toLocaleString("ru-RU")} ₽`;
      }
      if (totalEl) totalEl.textContent = stats.total ?? (data.bookings || []).length;
      if (pendingEl) pendingEl.textContent = stats.pending ?? 0;

      // Populate master filters
      const masterSelect = document.getElementById("blockMasterSelect");
      if (masterSelect && this.state.masters?.length) {
        masterSelect.innerHTML =
          this.state.masters.map((m) => `<option value="${m.id}">${m.full_name}</option>`).join("") +
          `<option value="0">Все мастера студии</option>`;
      }
      const filterSelect = document.getElementById("adminMasterFilterSelect");
      if (filterSelect && this.state.masters?.length && filterSelect.options.length <= 1) {
        filterSelect.innerHTML = `<option value="all">Все мастера</option>` +
          this.state.masters.map((m) => `<option value="${m.id}">${m.full_name}</option>`).join("");
      }

      this.renderAdminBookings();
      this.renderAdminAnalytics();

      // Render blocked intervals
      const blocksList = document.getElementById("adminBlocksList");
      if (blocksList) {
        if (!data.blocked_intervals || data.blocked_intervals.length === 0) {
          blocksList.innerHTML = `
            <div class="slots-empty" style="padding:14px;">
              Нет активных блокировок на этот день
            </div>`;
        } else {
          blocksList.innerHTML = data.blocked_intervals
            .map(
              (blk) => `
            <div class="admin-block-card">
              <div>
                <strong>${blk.start_time} — ${blk.end_time}</strong> · ${escapeHtml(blk.master_name)}<br>
                <small style="color:var(--text-muted);">${escapeHtml(blk.reason || "Технический перерыв")}</small>
              </div>
              <button class="btn-danger-sm" onclick="app.adminDeleteBlock(${blk.id})">Снять</button>
            </div>
          `
            )
            .join("");
        }
      }
    } catch (err) {
      console.error("Admin schedule load failed:", err);
      if (listEl) listEl.innerHTML = `<div class="slots-empty">Ошибка загрузки: ${err.message}</div>`;
    }
  },

  renderAdminBookings() {
    const listEl = document.getElementById("adminBookingsList");
    if (!listEl) return;
    const raw = this.state.adminScheduleRaw;
    if (!raw || !raw.bookings) return;

    const allBookings = raw.bookings;

    // Update filter counts
    const countAll = allBookings.length;
    const countPending = allBookings.filter((b) => b.status === "pending").length;
    const countConfirmed = allBookings.filter((b) => b.status === "confirmed").length;
    const countCompleted = allBookings.filter((b) => b.status === "completed").length;
    const countCancelled = allBookings.filter((b) => b.status.startsWith("cancelled")).length;

    const elAll = document.getElementById("statusCountAll");
    const elPend = document.getElementById("statusCountPending");
    const elConf = document.getElementById("statusCountConfirmed");
    const elComp = document.getElementById("statusCountCompleted");
    const elCanc = document.getElementById("statusCountCancelled");
    if (elAll) elAll.textContent = countAll;
    if (elPend) elPend.textContent = countPending;
    if (elConf) elConf.textContent = countConfirmed;
    if (elComp) elComp.textContent = countCompleted;
    if (elCanc) elCanc.textContent = countCancelled;

    // Filter by status
    let filtered = allBookings;
    if (this.state.adminStatusFilter === "pending") {
      filtered = filtered.filter((b) => b.status === "pending");
    } else if (this.state.adminStatusFilter === "confirmed") {
      filtered = filtered.filter((b) => b.status === "confirmed");
    } else if (this.state.adminStatusFilter === "completed") {
      filtered = filtered.filter((b) => b.status === "completed");
    } else if (this.state.adminStatusFilter === "cancelled") {
      filtered = filtered.filter((b) => b.status.startsWith("cancelled"));
    }

    // Filter by master
    if (this.state.adminMasterFilter !== "all") {
      const mid = parseInt(this.state.adminMasterFilter);
      filtered = filtered.filter((b) => b.master_id === mid);
    }

    // Filter by search query
    if (this.state.adminSearchQuery) {
      const q = this.state.adminSearchQuery;
      filtered = filtered.filter((b) => {
        const nameMatch = (b.client_name || "").toLowerCase().includes(q);
        const phoneMatch = (b.client_phone || "").includes(q);
        const idMatch = `#${b.id}`.includes(q) || String(b.id) === q;
        const srvMatch = (b.service_name || "").toLowerCase().includes(q);
        return nameMatch || phoneMatch || idMatch || srvMatch;
      });
    }

    const filteredCountEl = document.getElementById("adminFilteredCount");
    if (filteredCountEl) {
      filteredCountEl.textContent = (filtered.length !== allBookings.length) ? `Найдено: ${filtered.length}` : "";
    }

    if (filtered.length === 0) {
      listEl.innerHTML = `
        <div class="slots-empty">
          ${allBookings.length === 0 ? "На эту дату записей пока нет.<br><small style='color:var(--text-muted);'>Свободные слоты открыты для записи клиентов.</small>" : "По выбранным фильтрам записей не найдено."}
        </div>`;
      return;
    }

    const statusMap = {
      pending: { label: "Ожидает", cls: "pending" },
      confirmed: { label: "Подтверждена", cls: "confirmed" },
      completed: { label: "Завершена", cls: "completed" },
      cancelled_by_client: { label: "Отменена клиентом", cls: "cancelled_by_client" },
      cancelled_by_admin: { label: "Отменена мастером", cls: "cancelled_by_admin" },
    };

    listEl.innerHTML = filtered
      .map((b) => {
        const st = statusMap[b.status] || { label: b.status, cls: "" };
        let actionsHtml = "";
        if (b.status === "pending") {
          actionsHtml = `
            <div class="admin-booking-actions">
              <button class="btn-action success" onclick="app.adminConfirmBooking(${b.id})">✓ Подтвердить</button>
              <button class="btn-action danger" onclick="app.adminCancelBooking(${b.id})">Отклонить</button>
            </div>`;
        } else if (b.status === "confirmed") {
          actionsHtml = `
            <div class="admin-booking-actions">
              <button class="btn-action complete" onclick="app.adminCompleteBooking(${b.id})">✓ Завершить</button>
              <button class="btn-action danger" onclick="app.adminCancelBooking(${b.id})">Отменить</button>
            </div>`;
        }

        const cleanClient = escapeHtml(b.client_name);
        const cleanPhone = escapeHtml(b.client_phone);
        const cleanService = escapeHtml(b.service_name);
        const cleanMaster = escapeHtml(b.master_name);
        const cleanComment = escapeHtml(b.comment);

        // Fast contact buttons
        const phoneLink = cleanPhone ? `<a href="tel:${cleanPhone}" class="btn-action contact">📞 Позвонить</a>` : "";
        const tgLink = b.client_telegram_id ? `<a href="tg://user?id=${b.client_telegram_id}" class="btn-action contact" target="_blank">✈️ В Telegram</a>` : "";

        return `
          <div class="admin-booking-card">
            <div class="admin-booking-top">
              <span class="booking-badge ${st.cls}">${st.label}</span>
              <span style="font-size:12px; color:var(--text-muted); font-weight:600;">#${b.id}</span>
            </div>
            <div class="admin-booking-service">${cleanService} · ${b.service_price?.toLocaleString("ru-RU")} ₽</div>
            <div class="admin-booking-meta">
              <div>Время: <strong>${b.start_time} — ${b.end_time}</strong></div>
              <div>Мастер: <strong>${cleanMaster}</strong></div>
              <div>Клиент: <strong>${cleanClient}</strong> ${cleanPhone ? `(${cleanPhone})` : ""}</div>
              ${cleanComment ? `<div>Пожелания: <i>«${cleanComment}»</i></div>` : ""}
            </div>
            <div class="admin-booking-actions" style="margin-top:4px;">
              ${phoneLink}
              ${tgLink}
            </div>
            ${actionsHtml}
          </div>`;
      })
      .join("");
  },

  renderAdminAnalytics() {
    const raw = this.state.adminScheduleRaw;
    if (!raw) return;
    const stats = raw.stats || {};
    const rev = stats.revenue || 0;
    const comp = stats.completed || 0;
    const conf = stats.confirmed || 0;
    const avg = stats.avg_check || 0;

    const revEl = document.getElementById("analyticsRevenue");
    const avgEl = document.getElementById("analyticsAvgCheck");
    const compEl = document.getElementById("analyticsCompleted");
    const occEl = document.getElementById("analyticsOccupancy");

    if (revEl) revEl.textContent = `${rev.toLocaleString("ru-RU")} ₽`;
    if (avgEl) avgEl.textContent = `${avg.toLocaleString("ru-RU")} ₽`;
    if (compEl) compEl.textContent = comp;

    const masterCount = (this.state.masters?.length || 2);
    const totalPossibleSlots = masterCount * 11;
    const activeBookings = (comp + conf);
    const occupancy = Math.min(100, Math.round((activeBookings / totalPossibleSlots) * 100));
    if (occEl) occEl.textContent = `${occupancy}%`;

    const masterStatsEl = document.getElementById("adminMasterStatsList");
    if (masterStatsEl && this.state.masters) {
      masterStatsEl.innerHTML = this.state.masters
        .map((m) => {
          const mBookings = (raw.bookings || []).filter((b) => b.master_id === m.id && ["confirmed", "completed"].includes(b.status));
          const mRev = mBookings.reduce((sum, b) => sum + (b.service_price || 0), 0);
          return `
          <div class="master-stat-row">
            <div>
              <strong style="color:var(--text-main); font-size:13px;">${escapeHtml(m.full_name)}</strong><br>
              <small style="color:var(--text-muted);">${escapeHtml(m.specialization || "Мастер студии")}</small>
            </div>
            <div style="text-align:right;">
              <span style="font-weight:700; color:var(--accent-gold); font-size:14px;">${mRev.toLocaleString("ru-RU")} ₽</span><br>
              <small style="color:var(--text-muted);">${mBookings.length} визитов</small>
            </div>
          </div>`;
        })
        .join("");
    }
  },

  async loadAdminServices() {
    const listEl = document.getElementById("adminServicesCatalogList");
    if (!listEl) return;
    listEl.innerHTML = `<div class="slots-loading">Загружаем каталог услуг...</div>`;

    try {
      const services = await this.apiRequest("/api/admin/services");
      this.state.adminServicesRaw = services;

      if (!services || services.length === 0) {
        listEl.innerHTML = `<div class="slots-empty">Услуги не найдены</div>`;
        return;
      }

      listEl.innerHTML = services
        .map((s) => {
          const isActive = s.is_active;
          const cleanName = escapeHtml(s.name);
          const cleanCat = escapeHtml(s.category);
          const cleanDesc = s.description ? escapeHtml(s.description) : "";

          return `
          <div class="admin-service-card" id="srv-card-${s.id}">
            <div class="admin-service-info">
              <div style="display:flex; align-items:center; gap:6px;">
                <span class="service-category-badge">${cleanCat}</span>
                <span class="admin-service-name">${cleanName}</span>
              </div>
              ${cleanDesc ? `<div class="admin-service-desc">${cleanDesc}</div>` : ""}
              <div class="admin-service-meta">${s.duration_minutes} мин · <strong style="color:var(--accent-gold);">${s.price.toLocaleString("ru-RU")} ₽</strong></div>
            </div>
            <div class="admin-service-controls">
              <button class="btn-action-edit" onclick="app.openServiceModalById(${s.id})">✏️ Изменить</button>
              <button class="btn-service-toggle ${isActive ? "active" : "inactive"}" onclick="app.toggleServiceActive(${s.id})">
                ${isActive ? "✓ В каталоге" : "✕ Скрыта"}
              </button>
              <button class="btn-action-delete" onclick="app.deleteService(${s.id})" title="Удалить услугу">🗑️</button>
            </div>
          </div>`;
        })
        .join("");
    } catch (err) {
      console.error("Admin services load failed:", err);
      listEl.innerHTML = `<div class="slots-empty">Ошибка загрузки услуг: ${err.message}</div>`;
    }
  },

  async deleteService(serviceId) {
    const srv = (this.state.adminServicesRaw || []).find((s) => s.id === serviceId);
    const title = srv ? `«${srv.name}»` : `#${serviceId}`;
    const msg = `Удалить услугу ${title} из каталога?`;

    const doDelete = async () => {
      try {
        await this.apiRequest(`/api/admin/services/${serviceId}`, { method: "DELETE" });
        tg?.HapticFeedback?.notificationOccurred("success");
        this.showToast(`Услуга ${title} удалена`);
        await this.loadAdminServices();
        const refreshedServices = await this.apiRequest("/api/services");
        this.state.services = refreshedServices;
        const catSet = new Set(refreshedServices.map((s) => s.category));
        this.state.categories = ["Все", ...Array.from(catSet)];
        this.renderCategories();
        this.renderServices();
      } catch (err) {
        this.showToast("Ошибка удаления: " + err.message);
      }
    };

    if (tg?.showConfirm) {
      tg.showConfirm(msg, (ok) => {
        if (ok) doDelete();
      });
    } else if (confirm(msg)) {
      doDelete();
    }
  },

  openServiceModal(serviceObj = null) {
    tg?.HapticFeedback?.impactOccurred("light");
    const modal = document.getElementById("adminServiceModal");
    const titleEl = document.getElementById("adminServiceModalTitle");
    const idInput = document.getElementById("editServiceId");
    const catInput = document.getElementById("serviceCatInput");
    const nameInput = document.getElementById("serviceNameInput");
    const descInput = document.getElementById("serviceDescInput");
    const durInput = document.getElementById("serviceDurationInput");
    const priceInput = document.getElementById("servicePriceInput");

    if (!modal) return;

    if (serviceObj) {
      if (titleEl) titleEl.textContent = "Редактировать услугу";
      if (idInput) idInput.value = serviceObj.id;
      if (catInput) catInput.value = serviceObj.category || "Маникюр";
      if (nameInput) nameInput.value = serviceObj.name || "";
      if (descInput) descInput.value = serviceObj.description || "";
      if (durInput) durInput.value = serviceObj.duration_minutes || 60;
      if (priceInput) priceInput.value = serviceObj.price || 0;
    } else {
      if (titleEl) titleEl.textContent = "Добавить услугу";
      if (idInput) idInput.value = "";
      if (catInput) catInput.value = "Маникюр";
      if (nameInput) nameInput.value = "";
      if (descInput) descInput.value = "";
      if (durInput) durInput.value = 60;
      if (priceInput) priceInput.value = 2500;
    }

    modal.classList.remove("hidden");
  },

  openServiceModalById(serviceId) {
    const srv = (this.state.adminServicesRaw || []).find((s) => s.id === serviceId);
    this.openServiceModal(srv);
  },

  toggleServiceModal(show) {
    const modal = document.getElementById("adminServiceModal");
    modal?.classList.toggle("hidden", !show);
  },

  async submitServiceForm() {
    const editId = document.getElementById("editServiceId")?.value;
    const category = document.getElementById("serviceCatInput")?.value?.trim();
    const name = document.getElementById("serviceNameInput")?.value?.trim();
    const description = document.getElementById("serviceDescInput")?.value?.trim();
    const duration = parseInt(document.getElementById("serviceDurationInput")?.value || "60");
    const price = parseFloat(document.getElementById("servicePriceInput")?.value || "0");
    const btn = document.getElementById("serviceSaveBtn");

    if (!category || !name) {
      this.showToast("Укажите категорию и название услуги");
      return;
    }
    if (price < 0) {
      this.showToast("Цена не может быть отрицательной");
      return;
    }

    if (btn) btn.disabled = true;

    try {
      if (editId) {
        await this.apiRequest(`/api/admin/services/${editId}`, {
          method: "PUT",
          body: JSON.stringify({
            category,
            name,
            description: description || null,
            duration_minutes: duration,
            price,
          }),
        });
        this.showToast(`Услуга «${name}» обновлена!`);
      } else {
        await this.apiRequest("/api/admin/services", {
          method: "POST",
          body: JSON.stringify({
            category,
            name,
            description: description || null,
            duration_minutes: duration,
            price,
            is_active: true,
          }),
        });
        this.showToast(`Услуга «${name}» создана!`);
      }

      tg?.HapticFeedback?.notificationOccurred("success");
      this.toggleServiceModal(false);
      await this.loadAdminServices();

      // Refresh client data
      const refreshedServices = await this.apiRequest("/api/services");
      this.state.services = refreshedServices;
      const catSet = new Set(refreshedServices.map((s) => s.category));
      this.state.categories = ["Все", ...Array.from(catSet)];
      this.renderCategories();
      this.renderServices();
    } catch (err) {
      this.showToast("Ошибка: " + err.message);
    } finally {
      if (btn) btn.disabled = false;
    }
  },

  /* ==========================================================================
     Admin: Masters Management
     ========================================================================== */
  async loadAdminMasters() {
    const listEl = document.getElementById("adminMastersCatalogList");
    if (!listEl) return;
    listEl.innerHTML = `<div class="slots-loading">Загружаем список мастеров...</div>`;

    try {
      const masters = await this.apiRequest("/api/admin/masters");
      this.state.adminMastersRaw = masters;

      if (!masters || masters.length === 0) {
        listEl.innerHTML = `<div class="slots-empty">Мастера не найдены</div>`;
        return;
      }

      listEl.innerHTML = masters
        .map((m) => {
          const isActive = m.is_active;
          const cleanName = escapeHtml(m.full_name);
          const cleanSpec = escapeHtml(m.specialization || "Мастер ногтевого сервиса");
          const initial = (cleanName ? cleanName[0] : "М").toUpperCase();

          const tgBadge = m.telegram_username
            ? `<span style="color:var(--accent-gold); margin-left:6px;">@${escapeHtml(m.telegram_username)}</span>`
            : "";

          return `
          <div class="admin-master-card" id="m-card-${m.id}">
            <div class="avatar-letter" style="background:var(--accent-gold); color:#1c1917; width:40px; height:40px; font-size:15px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700;">
              ${initial}
            </div>
            <div class="admin-master-info">
              <div class="admin-master-name">${cleanName}</div>
              <div class="admin-master-meta">${cleanSpec}</div>
              <div style="font-size:11px; color:var(--text-muted);">Стаж: ${m.experience_years} лет${tgBadge}</div>
            </div>
            <div class="admin-service-controls">
              <button class="btn-action-edit" onclick="app.openMasterModalById(${m.id})">✏️ Изменить</button>
              <button class="btn-service-toggle ${isActive ? "active" : "inactive"}" onclick="app.toggleMasterActive(${m.id})">
                ${isActive ? "✓ Активен" : "✕ Отключен"}
              </button>
              <button class="btn-action-delete" onclick="app.deleteMaster(${m.id})" title="Удалить мастера">🗑️</button>
            </div>
          </div>`;
        })
        .join("");
    } catch (err) {
      console.error("Admin masters load failed:", err);
      listEl.innerHTML = `<div class="slots-empty">Ошибка загрузки мастеров: ${err.message}</div>`;
    }
  },

  async deleteMaster(masterId) {
    const m = (this.state.adminMastersRaw || []).find((item) => item.id === masterId);
    const title = m ? `«${m.full_name}»` : `#${masterId}`;
    const msg = `Удалить мастера ${title} из команды студии?`;

    const doDelete = async () => {
      try {
        await this.apiRequest(`/api/admin/masters/${masterId}`, { method: "DELETE" });
        tg?.HapticFeedback?.notificationOccurred("success");
        this.showToast(`Мастер ${title} удалён`);
        await this.loadAdminMasters();
        const refreshedMasters = await this.apiRequest("/api/masters");
        this.state.masters = refreshedMasters;
        this.renderMasters();
      } catch (err) {
        this.showToast("Ошибка удаления: " + err.message);
      }
    };

    if (tg?.showConfirm) {
      tg.showConfirm(msg, (ok) => {
        if (ok) doDelete();
      });
    } else if (confirm(msg)) {
      doDelete();
    }
  },

  openMasterModal(masterObj = null) {
    tg?.HapticFeedback?.impactOccurred("light");
    const modal = document.getElementById("adminMasterModal");
    const titleEl = document.getElementById("adminMasterModalTitle");
    const idInput = document.getElementById("editMasterId");
    const nameInput = document.getElementById("masterFullNameInput");
    const specInput = document.getElementById("masterSpecInput");
    const expInput = document.getElementById("masterExpInput");
    const tgInput = document.getElementById("masterTelegramInput");

    if (!modal) return;

    if (masterObj) {
      if (titleEl) titleEl.textContent = "Редактировать мастера";
      if (idInput) idInput.value = masterObj.id;
      if (nameInput) nameInput.value = masterObj.full_name || "";
      if (specInput) specInput.value = masterObj.specialization || "";
      if (expInput) expInput.value = masterObj.experience_years ?? 3;
      if (tgInput) tgInput.value = masterObj.telegram_username ? `@${masterObj.telegram_username}` : "";
    } else {
      if (titleEl) titleEl.textContent = "Добавить мастера";
      if (idInput) idInput.value = "";
      if (nameInput) nameInput.value = "";
      if (specInput) specInput.value = "";
      if (expInput) expInput.value = 3;
      if (tgInput) tgInput.value = "";
    }

    modal.classList.remove("hidden");
  },

  openMasterModalById(masterId) {
    const m = (this.state.adminMastersRaw || []).find((item) => item.id === masterId);
    this.openMasterModal(m);
  },

  toggleMasterModal(show) {
    const modal = document.getElementById("adminMasterModal");
    modal?.classList.toggle("hidden", !show);
  },

  async submitMasterForm() {
    const editId = document.getElementById("editMasterId")?.value;
    const fullName = document.getElementById("masterFullNameInput")?.value?.trim();
    const specialization = document.getElementById("masterSpecInput")?.value?.trim();
    const experienceYears = parseInt(document.getElementById("masterExpInput")?.value || "3");
    const telegramUsername = document.getElementById("masterTelegramInput")?.value?.trim();
    const btn = document.getElementById("masterSaveBtn");

    if (!fullName) {
      this.showToast("Укажите ФИО мастера");
      return;
    }

    if (btn) btn.disabled = true;

    try {
      if (editId) {
        await this.apiRequest(`/api/admin/masters/${editId}`, {
          method: "PUT",
          body: JSON.stringify({
            full_name: fullName,
            specialization: specialization || "",
            experience_years: experienceYears,
            telegram_username: telegramUsername || "",
          }),
        });
        this.showToast(`Мастер «${fullName}» обновлен!`);
      } else {
        await this.apiRequest("/api/admin/masters", {
          method: "POST",
          body: JSON.stringify({
            full_name: fullName,
            specialization: specialization || "",
            experience_years: experienceYears,
            telegram_username: telegramUsername || "",
            is_active: true,
          }),
        });
        this.showToast(`Мастер «${fullName}» добавлен!`);
      }

      tg?.HapticFeedback?.notificationOccurred("success");
      this.toggleMasterModal(false);
      await this.loadAdminMasters();

      // Refresh client masters list
      const refreshedMasters = await this.apiRequest("/api/masters");
      this.state.masters = refreshedMasters;
      this.renderMasters();
    } catch (err) {
      this.showToast("Ошибка: " + err.message);
    } finally {
      if (btn) btn.disabled = false;
    }
  },

  async toggleMasterActive(masterId) {
    tg?.HapticFeedback?.impactOccurred("medium");
    try {
      const res = await this.apiRequest(`/api/admin/masters/${masterId}/toggle`, { method: "POST" });
      this.showToast(`Мастер ${res.is_active ? "активирован" : "отключен"}`);
      await this.loadAdminMasters();

      const refreshedMasters = await this.apiRequest("/api/masters");
      this.state.masters = refreshedMasters;
      this.renderMasters();
    } catch (err) {
      this.showToast("Ошибка: " + err.message);
    }
  },

  /* ==========================================================================
     Admin: Studio Settings Management
     ========================================================================== */
  loadAdminStudioSettings() {
    const salon = this.state.salonInfo?.salon || this.state.salonInfo || {};
    const nameInput = document.getElementById("studioNameInput");
    const tagInput = document.getElementById("studioTaglineInput");
    const addrInput = document.getElementById("studioAddressInput");
    const hoursInput = document.getElementById("studioHoursInput");
    const tzInput = document.getElementById("studioTimezoneInput");
    const phoneInput = document.getElementById("studioPhoneInput");
    const contactInput = document.getElementById("studioContactInput");
    const landInput = document.getElementById("studioLandmarkInput");
    const descInput = document.getElementById("studioDescInput");

    if (nameInput) nameInput.value = salon.name || "";
    if (tagInput) tagInput.value = salon.tagline || "";
    if (addrInput) addrInput.value = salon.address || "";
    if (hoursInput) hoursInput.value = salon.working_hours || "";
    if (tzInput) tzInput.value = salon.timezone || "Europe/Moscow";
    if (phoneInput) phoneInput.value = salon.phone || "";
    if (contactInput) contactInput.value = salon.contact_telegram || salon.admin_contact || "";
    if (landInput) landInput.value = salon.landmark || "";
    if (descInput) descInput.value = salon.description || "";

    const timeoutTodayInput = document.getElementById("studioTimeoutTodayInput");
    const timeoutFutureInput = document.getElementById("studioTimeoutFutureInput");
    const autoAssignInput = document.getElementById("studioAutoAssignInput");

    if (timeoutTodayInput) timeoutTodayInput.value = salon.timeout_today_minutes ?? 10;
    if (timeoutFutureInput) timeoutFutureInput.value = salon.timeout_future_minutes ?? 30;
    if (autoAssignInput) autoAssignInput.checked = (salon.auto_assign_on_timeout !== false);
  },

  async submitStudioSettings() {
    const name = document.getElementById("studioNameInput")?.value?.trim();
    const tagline = document.getElementById("studioTaglineInput")?.value?.trim();
    const address = document.getElementById("studioAddressInput")?.value?.trim();
    const workingHours = document.getElementById("studioHoursInput")?.value?.trim();
    const timezone = document.getElementById("studioTimezoneInput")?.value || "Europe/Moscow";
    const phone = document.getElementById("studioPhoneInput")?.value?.trim();
    const contactTelegram = document.getElementById("studioContactInput")?.value?.trim();
    const landmark = document.getElementById("studioLandmarkInput")?.value?.trim();
    const description = document.getElementById("studioDescInput")?.value?.trim();
    const timeoutToday = parseInt(document.getElementById("studioTimeoutTodayInput")?.value ?? "10", 10) || 10;
    const timeoutFuture = parseInt(document.getElementById("studioTimeoutFutureInput")?.value ?? "30", 10) || 30;
    const autoAssign = document.getElementById("studioAutoAssignInput")?.checked ?? true;
    const btn = document.getElementById("studioSaveBtn");

    if (!name || !address || !workingHours || !phone) {
      this.showToast("Заполните обязательные поля: название, адрес, режим и телефон");
      return;
    }

    if (btn) btn.disabled = true;

    try {
      const res = await this.apiRequest("/api/admin/salon", {
        method: "PUT",
        body: JSON.stringify({
          name,
          tagline: tagline || "",
          address,
          working_hours: workingHours,
          timezone,
          phone,
          contact_telegram: contactTelegram || "",
          landmark: landmark || "",
          description: description || "",
          timeout_today_minutes: timeoutToday,
          timeout_future_minutes: timeoutFuture,
          auto_assign_on_timeout: autoAssign,
        }),
      });

      tg?.HapticFeedback?.notificationOccurred("success");
      this.showToast("Настройки студии сохранены!");

      if (res.salon) {
        if (!this.state.salonInfo) this.state.salonInfo = {};
        this.state.salonInfo.salon = res.salon;

        // Sync About view
        const brandTitleEl = document.getElementById("brandTitle");
        if (brandTitleEl && res.salon.tagline) brandTitleEl.textContent = res.salon.tagline;
        const addrEl = document.getElementById("aboutAddress");
        const phoneEl = document.getElementById("aboutPhone");
        const hoursEl = document.getElementById("aboutWorkingHours");
        const descEl = document.getElementById("aboutDescription");
        const contactEl = document.getElementById("aboutContact");
        if (addrEl) addrEl.textContent = res.salon.address;
        if (phoneEl) phoneEl.textContent = res.salon.phone;
        if (hoursEl) hoursEl.textContent = res.salon.working_hours;
        if (descEl) descEl.textContent = res.salon.description;
        if (contactEl) contactEl.textContent = res.salon.contact_telegram || res.salon.phone;
      }
    } catch (err) {
      this.showToast("Ошибка сохранения: " + err.message);
    } finally {
      if (btn) btn.disabled = false;
    }
  },

  async toggleServiceActive(serviceId) {
    tg?.HapticFeedback?.impactOccurred("medium");
    try {
      const res = await this.apiRequest(`/api/admin/services/${serviceId}/toggle`, { method: "POST" });
      this.showToast(`Услуга ${res.is_active ? "активирована" : "скрыта из каталога"}`);
      await this.loadAdminServices();
      await this.loadInitialData();
      this.renderServices();
    } catch (err) {
      this.showToast("Ошибка: " + err.message);
    }
  },

  openPriceModal(serviceId, name, currentPrice) {
    tg?.HapticFeedback?.impactOccurred("light");
    const modal = document.getElementById("adminPriceModal");
    const nameEl = document.getElementById("priceServiceName");
    const idInput = document.getElementById("priceServiceId");
    const valInput = document.getElementById("priceServiceValue");

    if (modal && idInput && valInput) {
      idInput.value = serviceId;
      valInput.value = currentPrice;
      if (nameEl) nameEl.textContent = name;
      modal.classList.remove("hidden");
    }
  },

  togglePriceModal(show) {
    const modal = document.getElementById("adminPriceModal");
    modal?.classList.toggle("hidden", !show);
  },

  async submitServicePrice() {
    const serviceId = parseInt(document.getElementById("priceServiceId")?.value || "0");
    const newPrice = parseFloat(document.getElementById("priceServiceValue")?.value || "0");

    if (!serviceId || newPrice <= 0) {
      this.showToast("Укажите корректную стоимость");
      return;
    }

    try {
      await this.apiRequest(`/api/admin/services/${serviceId}/price`, {
        method: "POST",
        body: JSON.stringify({ price: newPrice }),
      });
      tg?.HapticFeedback?.notificationOccurred("success");
      this.togglePriceModal(false);
      this.showToast("Стоимость успешно обновлена!");
      await this.loadAdminServices();
      await this.loadInitialData();
      this.renderServices();
    } catch (err) {
      this.showToast("Ошибка обновления: " + err.message);
    }
  },

  toggleManualBookingModal(show) {
    tg?.HapticFeedback?.impactOccurred("light");
    const modal = document.getElementById("adminManualModal");
    if (!modal) return;

    if (show) {
      const srvSelect = document.getElementById("manualServiceSelect");
      const mSelect = document.getElementById("manualMasterSelect");
      const dInput = document.getElementById("manualDateInput");

      if (srvSelect && this.state.services) {
        srvSelect.innerHTML = this.state.services
          .map((s) => `<option value="${s.id}">${s.name} (${s.price} ₽)</option>`)
          .join("");
      }
      if (mSelect && this.state.masters) {
        mSelect.innerHTML = this.state.masters
          .map((m) => `<option value="${m.id}">${m.full_name}</option>`)
          .join("");
      }
      if (dInput) {
        dInput.value = this.state.adminDate;
      }
    }

    modal.classList.toggle("hidden", !show);
  },

  async submitAdminManualBooking() {
    const srvId = parseInt(document.getElementById("manualServiceSelect")?.value || "0");
    const masterId = parseInt(document.getElementById("manualMasterSelect")?.value || "0");
    const bDate = document.getElementById("manualDateInput")?.value;
    const bTime = document.getElementById("manualTimeInput")?.value;
    const cName = document.getElementById("manualClientName")?.value;
    const cPhone = document.getElementById("manualClientPhone")?.value;
    const comment = document.getElementById("manualComment")?.value;

    if (!srvId || !masterId || !bDate || !bTime || !cName || !cPhone) {
      this.showToast("Заполните все обязательные поля");
      return;
    }

    const btn = document.getElementById("manualSubmitBtn");
    if (btn) btn.disabled = true;

    try {
      await this.apiRequest("/api/admin/manual-booking", {
        method: "POST",
        body: JSON.stringify({
          service_id: srvId,
          master_id: masterId,
          date: bDate,
          start_time: bTime,
          client_name: cName,
          client_phone: cPhone,
          comment: comment || "Создано администратором через Mini App",
        }),
      });

      tg?.HapticFeedback?.notificationOccurred("success");
      this.toggleManualBookingModal(false);
      this.showToast(`Клиент ${cName} успешно записан!`);
      await this.loadAdminSchedule();
    } catch (err) {
      this.showToast("Ошибка записи: " + err.message);
    } finally {
      if (btn) btn.disabled = false;
    }
  },

  async adminConfirmBooking(bookingId) {
    try {
      await this.apiRequest(`/api/admin/bookings/${bookingId}/confirm`, { method: "POST" });
      tg?.HapticFeedback?.notificationOccurred("success");
      this.showToast(`Запись #${bookingId} подтверждена!`);
      await this.loadAdminSchedule();
    } catch (err) {
      this.showToast("Ошибка: " + err.message);
    }
  },

  async adminCancelBooking(bookingId) {
    const doCancel = async () => {
      try {
        await this.apiRequest(`/api/admin/bookings/${bookingId}/cancel`, { method: "POST" });
        tg?.HapticFeedback?.notificationOccurred("warning");
        this.showToast(`Запись #${bookingId} отменена`);
        await this.loadAdminSchedule();
      } catch (err) {
        this.showToast("Ошибка: " + err.message);
      }
    };

    const msg = `Отменить запись #${bookingId}?`;
    if (tg?.showConfirm) {
      tg.showConfirm(msg, (ok) => {
        if (ok) doCancel();
      });
    } else if (confirm(msg)) {
      doCancel();
    }
  },

  async adminCompleteBooking(bookingId) {
    try {
      await this.apiRequest(`/api/admin/bookings/${bookingId}/complete`, { method: "POST" });
      tg?.HapticFeedback?.notificationOccurred("success");
      this.showToast(`Запись #${bookingId} завершена и оплачена!`);
      await this.loadAdminSchedule();
    } catch (err) {
      this.showToast("Ошибка: " + err.message);
    }
  },

  toggleBlockModal(show) {
    const modal = document.getElementById("blockModal");
    const errEl = document.getElementById("blockModalError");
    if (errEl) {
      errEl.textContent = "";
      errEl.classList.add("hidden");
    }
    if (show) {
      const dateInput = document.getElementById("blockDateInput");
      if (dateInput) {
        const todayIso = getLocalDateString(new Date());
        dateInput.min = todayIso;
        dateInput.value = this.state.adminDate || todayIso;
      }
      const masterSelect = document.getElementById("blockMasterSelect");
      if (masterSelect && this.state.masters?.length && masterSelect.options.length === 0) {
        masterSelect.innerHTML =
          this.state.masters.map((m) => `<option value="${m.id}">${m.full_name}</option>`).join("") +
          `<option value="0">Все мастера студии</option>`;
      }
    }
    if (modal) {
      modal.classList.toggle("hidden", !show);
    }
  },

  showBlockModalError(msg) {
    const errEl = document.getElementById("blockModalError");
    if (errEl) {
      errEl.textContent = msg;
      errEl.classList.remove("hidden");
    }
    this.showToast(msg);
  },

  async submitBlockInterval() {
    const masterVal = document.getElementById("blockMasterSelect")?.value;
    const masterId = parseInt(masterVal ?? "1", 10);
    const blockDate = document.getElementById("blockDateInput")?.value || this.state.adminDate;
    const startTime = document.getElementById("blockStartTime")?.value;
    const endTime = document.getElementById("blockEndTime")?.value;
    const reason = document.getElementById("blockReasonInput")?.value;

    const errEl = document.getElementById("blockModalError");
    if (errEl) {
      errEl.textContent = "";
      errEl.classList.add("hidden");
    }

    if (Number.isNaN(masterId) || !blockDate || !startTime || !endTime) {
      this.showBlockModalError("Заполните дату, мастера и время перерыва");
      return;
    }

    if (startTime >= endTime) {
      this.showBlockModalError("Время начала перерыва должно быть раньше времени окончания");
      return;
    }

    try {
      await this.apiRequest("/api/admin/block", {
        method: "POST",
        body: JSON.stringify({
          master_id: masterId,
          date: blockDate,
          start_time: startTime,
          end_time: endTime,
          reason: reason || "Технический перерыв",
        }),
      });

      tg?.HapticFeedback?.notificationOccurred("success");
      this.toggleBlockModal(false);
      this.showToast("Перерыв успешно установлен");
      if (blockDate !== this.state.adminDate) {
        this.setAdminDate(blockDate);
      } else {
        await this.loadAdminSchedule();
      }
    } catch (err) {
      this.showBlockModalError("Не удалось заблокировать: " + err.message);
    }
  },

  async adminDeleteBlock(blockId) {
    try {
      await this.apiRequest(`/api/admin/block/${blockId}`, { method: "DELETE" });
      tg?.HapticFeedback?.notificationOccurred("success");
      this.showToast("Блокировка снята");
      await this.loadAdminSchedule();
    } catch (err) {
      this.showToast("Ошибка: " + err.message);
    }
  },

  showToast(message) {
    this.elements.toast.textContent = message;
    this.elements.toast.classList.remove("hidden");
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => {
      this.elements.toast.classList.add("hidden");
    }, 3200);
  },
};

// Start application on DOM content loaded
document.addEventListener("DOMContentLoaded", () => {
  app.init();
});
