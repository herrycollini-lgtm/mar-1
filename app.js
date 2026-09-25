const bookingForm = document.querySelector("#bookingForm");
const bookingDate = document.querySelector("#bookingDate");
const timeOptions = document.querySelector("#timeOptions");
const bookingSubmit = document.querySelector("#bookingSubmit");
const bookingMessage = document.querySelector("#bookingMessage");
const bookingGuests = document.querySelector("#bookingGuests");
const bookingNotes = document.querySelector("#bookingNotes");
const confirmationDialog = document.querySelector("#confirmationDialog");
let availabilityRequest = 0;

function localDateString(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return year + "-" + month + "-" + day;
}

function selectedService() {
  return document.querySelector('input[name="service"]:checked').value;
}

function setBookingMessage(message, kind) {
  bookingMessage.textContent = message || "";
  bookingMessage.classList.toggle("is-error", kind === "error");
  bookingMessage.classList.toggle("is-success", kind === "success");
}

function selectedTime() {
  const input = document.querySelector('input[name="time"]:checked');
  return input ? input.value : "";
}

async function loadAvailability(preferredTime) {
  const selectedTimeToKeep = preferredTime || selectedTime();
  const requestId = ++availabilityRequest;
  bookingSubmit.disabled = true;
  setBookingMessage("", "");
  if (!bookingDate.value) {
    timeOptions.innerHTML = '<p class="form-hint">Seleziona una data per vedere gli orari disponibili.</p>';
    return;
  }
  timeOptions.innerHTML = '<p class="form-hint">Carico le disponibilità…</p>';
  const query = new URLSearchParams({
    date: bookingDate.value,
    service: selectedService(),
    guests: bookingGuests.value
  });
  try {
    const response = await fetch("/api/availability?" + query.toString(), { headers: { Accept: "application/json" } });
    const result = await response.json();
    if (requestId !== availabilityRequest) return;
    if (!response.ok) throw new Error(result.error || "Non riesco a caricare gli orari.");
    timeOptions.replaceChildren();
    if (!result.slots.length) {
      const message = document.createElement("p");
      message.className = "form-hint";
      if (result.state === "not_configured") {
        message.textContent = "Non sono ancora stati configurati orari per questo servizio.";
      } else if (result.state === "no_future_slots") {
        message.textContent = "Non restano orari prenotabili in questa data.";
      } else {
        message.textContent = "Non ci sono orari prenotabili per questa data.";
      }
      timeOptions.append(message);
      return;
    }
    result.slots.forEach(function (slot) {
      const label = document.createElement("label");
      label.className = "time-choice";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = "time";
      input.value = slot.time;
      input.disabled = !slot.available;
      if (slot.available && slot.time === selectedTimeToKeep) {
        input.checked = true;
        bookingSubmit.disabled = false;
      }
      input.addEventListener("change", function () { bookingSubmit.disabled = false; });
      const text = document.createElement("span");
      text.textContent = slot.available ? slot.time + " · " + slot.remaining + " posti" : slot.time + " · non disponibile";
      label.append(input, text);
      timeOptions.append(label);
    });
    const hasAvailable = result.slots.some(function (slot) { return slot.available; });
    if (!hasAvailable) {
      const hint = document.createElement("p");
      hint.className = "form-hint";
      hint.textContent = "Non ci sono fasce con posti sufficienti per il numero di persone scelto.";
      timeOptions.append(hint);
    }
  } catch (error) {
    if (requestId !== availabilityRequest) return;
    timeOptions.innerHTML = '<p class="form-hint">Il servizio prenotazioni non è raggiungibile al momento. Riprova più tardi.</p>';
    setBookingMessage(error.message, "error");
  }
}

function readUtmParameters() {
  const keys = ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"];
  const current = new URLSearchParams(window.location.search);
  let saved = {};
  try { saved = JSON.parse(sessionStorage.getItem("mareUtm") || "{}"); } catch (_) { saved = {}; }
  keys.forEach(function (key) {
    const value = current.get(key);
    if (value) saved[key] = value.slice(0, 150);
  });
  try { sessionStorage.setItem("mareUtm", JSON.stringify(saved)); } catch (_) {}
  return saved;
}

bookingDate.min = localDateString(new Date());
bookingDate.value = localDateString(new Date());
bookingDate.addEventListener("change", loadAvailability);
bookingGuests.addEventListener("change", loadAvailability);
bookingGuests.addEventListener("input", loadAvailability);
document.querySelectorAll('input[name="service"]').forEach(function (input) {
  input.addEventListener("change", loadAvailability);
});
loadAvailability();

bookingNotes.addEventListener("input", function () {
  document.querySelector("#characterCount").textContent = bookingNotes.value.length + " / 500";
});

bookingForm.addEventListener("submit", async function (event) {
  event.preventDefault();
  if (!bookingDate.value || !selectedTime()) {
    setBookingMessage("Scegli una data e un orario disponibile per continuare.", "error");
    return;
  }
  const guestCount = Number(bookingGuests.value);
  if (!Number.isInteger(guestCount) || guestCount < 1 || guestCount > 500) {
    setBookingMessage("Inserisci un numero di persone valido.", "error");
    return;
  }
  bookingSubmit.disabled = true;
  bookingSubmit.classList.add("is-loading");
  bookingSubmit.setAttribute("aria-busy", "true");
  setBookingMessage("Registro la prenotazione…", "");
  const payload = {
    date: bookingDate.value,
    service: selectedService(),
    time: selectedTime(),
    guests: guestCount,
    notes: bookingNotes.value.trim(),
    utm: readUtmParameters()
  };
  try {
    const response = await fetch("/api/reservations", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload)
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "La prenotazione non è stata registrata.");
    const dateLabel = new Intl.DateTimeFormat("it-IT", { weekday: "long", day: "numeric", month: "long" }).format(new Date(payload.date + "T12:00:00"));
    const summary = document.querySelector("#confirmationSummary");
    summary.textContent = "";
    const serviceName = payload.service === "pranzo" ? "pranzo" : "cena";
    summary.append(document.createTextNode("Tavolo per " + payload.guests + (payload.guests === 1 ? " persona" : " persone") + ", " + serviceName + " di " + dateLabel + " alle " + payload.time + "."));
    document.querySelector("#bookingReference").textContent = result.reference;
    confirmationDialog.showModal();
    bookingForm.reset();
    bookingDate.value = localDateString(new Date());
    document.querySelector("#characterCount").textContent = "0 / 500";
    bookingSubmit.disabled = true;
    loadAvailability();
    setBookingMessage("Richiesta inviata. È in attesa della verifica del gestore.", "success");
  } catch (error) {
    await loadAvailability(payload.time);
    setBookingMessage(error.message, "error");
  } finally {
    bookingSubmit.classList.remove("is-loading");
    bookingSubmit.removeAttribute("aria-busy");
  }
});

document.querySelector("#closeConfirmation").addEventListener("click", function () { confirmationDialog.close(); });
document.querySelector("#finishConfirmation").addEventListener("click", function () { confirmationDialog.close(); });
document.querySelector("#printConfirmation").addEventListener("click", function () { window.print(); });
document.querySelector("#copyReference").addEventListener("click", async function () {
  const reference = document.querySelector("#bookingReference").textContent;
  try {
    await navigator.clipboard.writeText(reference);
    document.querySelector("#copyFeedback").textContent = "Codice copiato.";
  } catch (_) {
    document.querySelector("#copyFeedback").textContent = "Seleziona e copia il codice: " + reference;
  }
});
confirmationDialog.addEventListener("click", function (event) {
  if (event.target === confirmationDialog) confirmationDialog.close();
});

const mobileMenuToggle = document.querySelector("#mobileMenuToggle");
const primaryNav = document.querySelector("#primaryNav");
mobileMenuToggle.addEventListener("click", function () {
  const expanded = mobileMenuToggle.getAttribute("aria-expanded") === "true";
  mobileMenuToggle.setAttribute("aria-expanded", String(!expanded));
  primaryNav.classList.toggle("is-open", !expanded);
});
primaryNav.querySelectorAll("a").forEach(function (link) {
  link.addEventListener("click", function () {
    primaryNav.classList.remove("is-open");
    mobileMenuToggle.setAttribute("aria-expanded", "false");
  });
});

const themeToggle = document.querySelector("#themeToggle");
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  document.body.dataset.theme = theme;
  const dark = theme === "dark";
  document.querySelector('meta[name="theme-color"]').setAttribute("content", dark ? "#202331" : "#edf2f4");
  themeToggle.setAttribute("aria-pressed", String(dark));
  themeToggle.setAttribute("aria-label", dark ? "Attiva tema chiaro" : "Attiva tema scuro");
  try { localStorage.setItem("mareTheme", theme); } catch (_) {}
}
let savedTheme = "light";
try { savedTheme = localStorage.getItem("mareTheme") || "light"; } catch (_) {}
applyTheme(savedTheme);
themeToggle.addEventListener("click", function () { applyTheme(document.body.dataset.theme === "dark" ? "light" : "dark"); });

const searchToggle = document.querySelector("#searchToggle");
const siteSearch = document.querySelector("#siteSearch");
const searchInput = document.querySelector("#searchInput");
const searchResults = document.querySelector("#searchResults");
searchToggle.addEventListener("click", function () {
  const opening = siteSearch.hidden;
  siteSearch.hidden = !opening;
  searchToggle.setAttribute("aria-expanded", String(opening));
  if (opening) searchInput.focus();
});
siteSearch.addEventListener("submit", function (event) {
  event.preventDefault();
  const query = searchInput.value.trim().toLocaleLowerCase("it");
  searchResults.replaceChildren();
  if (!query) return;
  const matches = Array.from(document.querySelectorAll("main section[id]" )).filter(function (section) {
    return section.innerText.toLocaleLowerCase("it").includes(query);
  });
  if (!matches.length) {
    const message = document.createElement("p");
    message.textContent = "Nessun risultato trovato.";
    searchResults.append(message);
    return;
  }
  matches.slice(0, 5).forEach(function (section) {
    const heading = section.querySelector("h1, h2");
    const link = document.createElement("a");
    link.href = "#" + section.id;
    link.textContent = heading ? heading.textContent.replace(/\s+/g, " ").trim() : section.id;
    link.addEventListener("click", function () { siteSearch.hidden = true; searchToggle.setAttribute("aria-expanded", "false"); });
    searchResults.append(link);
  });
});

const backToTop = document.querySelector("#backToTop");
const readingProgress = document.querySelector("#readingProgress");
function updateScrollControls() {
  const maxScroll = document.documentElement.scrollHeight - window.innerHeight;
  const progress = maxScroll > 0 ? Math.min(100, window.scrollY / maxScroll * 100) : 0;
  readingProgress.style.width = progress + "%";
  backToTop.classList.toggle("is-visible", window.scrollY > 650);
}
window.addEventListener("scroll", updateScrollControls, { passive: true });
updateScrollControls();
backToTop.addEventListener("click", function () { window.scrollTo({ top: 0, behavior: "smooth" }); });
document.querySelector("#currentYear").textContent = String(new Date().getFullYear());
