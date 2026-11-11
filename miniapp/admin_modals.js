/**
 * Nail Atelier — Telegram Mini App Admin Modals & Booking Actions
 */
(function () {
  const AdminModalsModule = {
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
  };

  if (window.app) {
    Object.assign(window.app, AdminModalsModule);
  } else {
    window.addEventListener("DOMContentLoaded", () => {
      if (window.app) Object.assign(window.app, AdminModalsModule);
    });
  }
})();
