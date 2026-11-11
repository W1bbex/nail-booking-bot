/**
 * Nail Atelier — Telegram Mini App Admin Engine
 */
(function () {
  const AdminModule = {
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

      if (this.state.adminMasterFilter !== "all") {
        const mid = parseInt(this.state.adminMasterFilter);
        filtered = filtered.filter((b) => b.master_id === mid);
      }

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
  };

  if (window.app) {
    Object.assign(window.app, AdminModule);
  } else {
    window.addEventListener("DOMContentLoaded", () => {
      if (window.app) Object.assign(window.app, AdminModule);
    });
  }
})();
