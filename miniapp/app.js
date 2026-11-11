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
