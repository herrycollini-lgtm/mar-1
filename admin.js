const loginForm = document.querySelector("#loginForm");
const loginMessage = document.querySelector("#loginMessage");
const adminLogin = document.querySelector("#adminLogin");
const adminDashboard = document.querySelector("#adminDashboard");
const adminDate = document.querySelector("#adminDate");
const reservationList = document.querySelector("#reservationList");
const capacitySummary = document.querySelector("#capacitySummary");
const slotRows = document.querySelector("#slotRows");
let allReservations = [];

function localDateString(date) {
  return date.getFullYear() + "-" + String(date.getMonth() + 1).padStart(2, "0") + "-" + String(date.getDate()).padStart(2, "0");
}

async function apiRequest(path, options) {
  const response = await fetch(path, Object.assign({ headers: { Accept: "application/json" } }, options || {}));
  let result = {};
  try { result = await response.json(); } catch (_) { result = {}; }
  if (!response.ok) {
    const error = new Error(result.error || "La richiesta non è riuscita.");
    error.status = response.status;
    throw error;
  }
  return result;
}

function setMessage(element, message, kind) {
  element.textContent = message || "";
  element.classList.toggle("is-error", kind === "error");
  element.classList.toggle("is-success", kind === "success");
}

function jsonOptions(method, body) {
  return { method: method, headers: { "Content-Type": "application/json", Accept: "application/json" }, body: JSON.stringify(body) };
}

function showDashboard() {
  adminLogin.hidden = true;
  adminDashboard.hidden = false;
  if (!adminDate.value) adminDate.value = localDateString(new Date());
  loadDay();
}

function addSummaryItem(label, value) {
  const item = document.createElement("div");
  item.className = "capacity-summary-item";
  const name = document.createElement("span");
  name.textContent = label;
  const amount = document.createElement("strong");
  amount.textContent = value;
  item.append(name, amount);
  capacitySummary.append(item);
}

function renderSummary(overview) {
  capacitySummary.replaceChildren();
  const activeReservations = overview.reservations.filter(function (reservation) { return reservation.status !== "annullata"; });
  addSummaryItem("Richieste non annullate", String(activeReservations.length));
  addSummaryItem("Coperti prenotati", String(overview.totalBooked));
  addSummaryItem("Capienza giornaliera", overview.dailyCapacity === null ? "Nessun limite" : String(overview.dailyCapacity));
  addSummaryItem("Coperti disponibili", overview.dailyRemaining === null ? "—" : String(overview.dailyRemaining));
  overview.slots.forEach(function (slot) {
    addSummaryItem((slot.service === "pranzo" ? "Pranzo" : "Cena") + " · " + slot.time, slot.booked + " / " + slot.capacity);
  });
}

function renderReservations(reservations) {
  allReservations = reservations;
  applyReservationFilter();
}

function visibleReservations() {
  const filter = document.querySelector("#reservationFilter").value;
  return filter === "tutte" ? allReservations : allReservations.filter(function (reservation) { return reservation.status === filter; });
}

function applyReservationFilter() {
  const reservations = visibleReservations();
  reservationList.replaceChildren();
  const filterCount = reservations.length + (reservations.length === 1 ? " prenotazione" : " prenotazioni");
  document.querySelector("#bookingCount").textContent = reservations.length === allReservations.length ? filterCount : filterCount + " su " + allReservations.length;
  if (!reservations.length) {
    const empty = document.createElement("p");
    empty.className = "reservation-empty";
    empty.textContent = allReservations.length ? "Nessuna prenotazione corrisponde al filtro selezionato." : "Nessuna prenotazione per questa data.";
    reservationList.append(empty);
    return;
  }
  reservations.forEach(function (reservation) {
    const row = document.createElement("article");
    row.className = "reservation-row";
    const time = document.createElement("strong");
    time.className = "reservation-time";
    time.textContent = reservation.time;
    const details = document.createElement("div");
    const service = document.createElement("strong");
    service.textContent = (reservation.service === "pranzo" ? "Pranzo" : "Cena") + " · " + reservation.guests + (reservation.guests === 1 ? " persona" : " persone");
    const code = document.createElement("div");
    code.className = "reservation-code";
    code.textContent = reservation.reference;
    details.append(service, code);
    const note = document.createElement("div");
    note.className = "reservation-notes";
    note.textContent = reservation.notes || "Nessuna nota";
    const extra = document.createElement("div");
    extra.className = "reservation-extra";
    extra.append(note);
    if (reservation.utm_source || reservation.utm_campaign) {
      const attribution = document.createElement("div");
      attribution.className = "reservation-attribution";
      attribution.textContent = "Fonte: " + [reservation.utm_source, reservation.utm_campaign].filter(Boolean).join(" · ");
      extra.append(attribution);
    }
    const status = document.createElement("select");
    status.setAttribute("aria-label", "Stato della prenotazione " + reservation.reference);
    [["ricevuta", "Ricevuta"], ["confermata", "Confermata"], ["annullata", "Annullata"]].forEach(function (optionData) {
      const option = document.createElement("option");
      option.value = optionData[0];
      option.textContent = optionData[1];
      option.selected = reservation.status === optionData[0];
      status.append(option);
    });
    status.addEventListener("change", async function () {
      const previousStatus = reservation.status;
      if (status.value === "annullata" && !window.confirm("Vuoi annullare la prenotazione " + reservation.reference + "? I posti torneranno disponibili.")) {
        status.value = previousStatus;
        return;
      }
      status.disabled = true;
      try {
        await apiRequest("/api/admin/reservations/" + reservation.id, jsonOptions("PATCH", { status: status.value }));
        await loadDay();
      } catch (error) {
        setMessage(document.querySelector("#capacityMessage"), error.message, "error");
        status.value = previousStatus;
        status.disabled = false;
      }
    });
    row.append(time, details, extra, status);
    reservationList.append(row);
  });
}

document.querySelector("#reservationFilter").addEventListener("change", applyReservationFilter);
document.querySelector("#printReservations").addEventListener("click", function () { window.print(); });
document.querySelector("#exportReservations").addEventListener("click", function () {
  const headers = ["Data", "Ora", "Servizio", "Persone", "Codice", "Stato", "Note"];
  const statusLabels = { ricevuta: "Ricevuta", confermata: "Confermata", annullata: "Annullata" };
  const rows = visibleReservations().map(function (reservation) {
    return [reservation.day, reservation.time, reservation.service, reservation.guests, reservation.reference, statusLabels[reservation.status] || reservation.status, reservation.notes];
  });
  const csvCell = function (value) {
    let text = String(value == null ? "" : value);
    if (/^[=+\-@]/.test(text.trimStart())) text = "'" + text;
    return '"' + text.replace(/"/g, '""') + '"';
  };
  const csv = "\uFEFF" + [headers].concat(rows).map(function (row) { return row.map(csvCell).join(";"); }).join("\r\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "prenotazioni-" + adminDate.value + ".csv";
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
});

function renderCapacityEditor(config) {
  document.querySelector("#dailyCapacity").value = config.dailyCapacity === null ? "" : String(config.dailyCapacity);
  const editor = document.querySelector("#slotCapacityEditor");
  editor.replaceChildren();
  const activeSlots = config.slots.filter(function (slot) { return slot.active; });
  if (!activeSlots.length) {
    const empty = document.createElement("p");
    empty.className = "reservation-empty";
    empty.textContent = "Aggiungi prima gli orari di servizio per impostare le capienze.";
    editor.append(empty);
    return;
  }
  activeSlots.forEach(function (slot) {
    const row = document.createElement("div");
    row.className = "capacity-slot-row";
    const label = document.createElement("label");
    const inputId = "capacity-slot-" + slot.id;
    label.htmlFor = inputId;
    label.textContent = (slot.service === "pranzo" ? "Pranzo" : "Cena") + " · " + slot.time + " · " + slot.booked + " già prenotati";
    const input = document.createElement("input");
    input.type = "number";
    input.min = "1";
    input.max = "500";
    input.id = inputId;
    input.dataset.slotId = String(slot.id);
    input.value = slot.dayCapacity === null ? "" : String(slot.dayCapacity);
    input.placeholder = "Standard " + slot.capacity;
    input.setAttribute("aria-label", "Capienza " + (slot.service === "pranzo" ? "pranzo" : "cena") + " alle " + slot.time + " per la data selezionata");
    row.append(label, input);
    editor.append(row);
  });
}

function createSlotRow(slot) {
  const row = document.createElement("div");
  row.className = "slot-editor-row";
  if (slot && slot.id) row.dataset.slotId = String(slot.id);
  const serviceLabel = document.createElement("label");
  serviceLabel.className = "field";
  const serviceText = document.createElement("span");
  serviceText.textContent = "Servizio";
  const service = document.createElement("select");
  service.innerHTML = '<option value="pranzo">Pranzo</option><option value="cena">Cena</option>';
  service.value = slot ? slot.service : "pranzo";
  serviceLabel.append(serviceText, service);
  const timeLabel = document.createElement("label");
  timeLabel.className = "field";
  const timeText = document.createElement("span");
  timeText.textContent = "Orario";
  const time = document.createElement("input");
  time.type = "time";
  time.required = true;
  time.value = slot ? slot.time : "";
  timeLabel.append(timeText, time);
  const capacityLabel = document.createElement("label");
  capacityLabel.className = "field";
  const capacityText = document.createElement("span");
  capacityText.textContent = "Coperti";
  const capacity = document.createElement("input");
  capacity.type = "number";
  capacity.min = "1";
  capacity.max = "500";
  capacity.required = true;
  capacity.value = slot ? String(slot.capacity) : "";
  capacityLabel.append(capacityText, capacity);
  const activeLabel = document.createElement("label");
  activeLabel.className = "slot-active";
  const active = document.createElement("input");
  active.type = "checkbox";
  active.checked = slot ? slot.active : true;
  const activeText = document.createElement("span");
  activeText.textContent = "Attivo";
  activeLabel.append(active, activeText);
  const remove = document.createElement("button");
  remove.className = "remove-slot";
  remove.type = "button";
  remove.textContent = "Rimuovi";
  remove.setAttribute("aria-label", "Disattiva questo orario");
  remove.addEventListener("click", function () { row.remove(); });
  row.append(serviceLabel, timeLabel, capacityLabel, activeLabel, remove);
  return row;
}

function renderSlots(slots) {
  slotRows.replaceChildren();
  if (!slots.length) {
    const empty = document.createElement("p");
    empty.className = "reservation-empty";
    empty.textContent = "Nessun orario configurato. Aggiungi le fasce comunicate dallo stabilimento.";
    slotRows.append(empty);
    return;
  }
  slots.forEach(function (slot) { slotRows.append(createSlotRow(slot)); });
}

async function loadDay() {
  setMessage(document.querySelector("#capacityMessage"), "", "");
  try {
    const query = "?date=" + encodeURIComponent(adminDate.value);
    const responses = await Promise.all([
      apiRequest("/api/admin/config" + query),
      apiRequest("/api/admin/overview" + query)
    ]);
    const selectedDayLabel = new Intl.DateTimeFormat("it-IT", { dateStyle: "full" }).format(new Date(adminDate.value + "T12:00:00"));
    document.querySelector("#dateTitle").textContent = selectedDayLabel;
    renderCapacityEditor(responses[0]);
    renderSlots(responses[0].slots);
    renderSummary(responses[1]);
    renderReservations(responses[1].reservations);
    document.querySelector("#adminUpdated").textContent = "Ultimo aggiornamento: " + new Intl.DateTimeFormat("it-IT", { dateStyle: "medium", timeStyle: "short" }).format(new Date());
  } catch (error) {
    if (error.status === 401) {
      adminDashboard.hidden = true;
      adminLogin.hidden = false;
      setMessage(loginMessage, "La sessione è terminata. Accedi di nuovo.", "error");
      return;
    }
    setMessage(document.querySelector("#capacityMessage"), error.message, "error");
  }
}

async function checkSession() {
  try {
    const result = await apiRequest("/api/admin/session");
    if (result.authenticated) {
      showDashboard();
    } else if (!result.configured) {
      setMessage(loginMessage, "L’accesso admin deve essere configurato sul server.", "error");
    }
  } catch (_) {
    setMessage(loginMessage, "Non riesco a contattare il servizio. Apri il sito dal server locale.", "error");
  }
}

document.querySelector("#adminDate").value = localDateString(new Date());
checkSession();
adminDate.addEventListener("change", loadDay);

document.querySelector("#passwordVisibility").addEventListener("click", function () {
  const password = document.querySelector("#adminPassword");
  const visible = password.type === "password";
  password.type = visible ? "text" : "password";
  this.textContent = visible ? "Nascondi" : "Mostra";
  this.setAttribute("aria-pressed", String(visible));
});

loginForm.addEventListener("submit", async function (event) {
  event.preventDefault();
  const button = document.querySelector("#loginSubmit");
  button.disabled = true;
  setMessage(loginMessage, "Verifico le credenziali…", "");
  try {
    await apiRequest("/api/admin/login", jsonOptions("POST", {
      username: document.querySelector("#adminUsername").value.trim(),
      password: document.querySelector("#adminPassword").value
    }));
    document.querySelector("#adminPassword").value = "";
    setMessage(loginMessage, "", "");
    showDashboard();
  } catch (error) {
    setMessage(loginMessage, error.message, "error");
  } finally {
    button.disabled = false;
  }
});

document.querySelector("#logoutButton").addEventListener("click", async function () {
  try { await apiRequest("/api/admin/logout", jsonOptions("POST", {})); } catch (_) {}
  adminDashboard.hidden = true;
  adminLogin.hidden = false;
  setMessage(loginMessage, "Hai effettuato la disconnessione.", "success");
});

document.querySelector("#capacityForm").addEventListener("submit", async function (event) {
  event.preventDefault();
  const dailyText = document.querySelector("#dailyCapacity").value.trim();
  const slotCapacities = Array.from(document.querySelectorAll(".capacity-slot-row input")).map(function (input) {
    return { id: Number(input.dataset.slotId), capacity: input.value.trim() ? Number(input.value) : null };
  });
  const payload = { date: adminDate.value, dailyCapacity: dailyText ? Number(dailyText) : null, slotCapacities: slotCapacities };
  try {
    await apiRequest("/api/admin/capacity", jsonOptions("PUT", payload));
    setMessage(document.querySelector("#capacityMessage"), "Capienze salvate.", "success");
    await loadDay();
  } catch (error) {
    setMessage(document.querySelector("#capacityMessage"), error.message, "error");
  }
});

document.querySelector("#addSlotButton").addEventListener("click", function () {
  slotRows.querySelector(".reservation-empty")?.remove();
  slotRows.append(createSlotRow(null));
});

document.querySelector("#slotsForm").addEventListener("submit", async function (event) {
  event.preventDefault();
  const rows = Array.from(slotRows.querySelectorAll(".slot-editor-row"));
  const slots = rows.map(function (row) {
    const controls = row.querySelectorAll("select, input");
    return {
      id: row.dataset.slotId ? Number(row.dataset.slotId) : null,
      service: controls[0].value,
      time: controls[1].value,
      capacity: Number(controls[2].value),
      active: controls[3].checked
    };
  });
  try {
    await apiRequest("/api/admin/slots", jsonOptions("PUT", { slots: slots }));
    setMessage(document.querySelector("#slotsMessage"), "Orari salvati.", "success");
    await loadDay();
  } catch (error) {
    setMessage(document.querySelector("#slotsMessage"), error.message, "error");
  }
});
