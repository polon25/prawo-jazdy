"use strict";
// The app's page: logging in, the dashboard with statistics, the exam
// simulation and its result. Talks to the JSON API in web_server.py.

const YES_NO = { pl: ["TAK", "NIE"], en: ["YES", "NO"], de: ["JA", "NEIN"], uk: ["ТАК", "НІ"] };
const CATEGORY_NAMES = {
  AM: "motorower", A1: "motocykl do 125 cm³", A2: "motocykl do 35 kW",
  A: "motocykl", B1: "czterokołowiec", B: "samochód osobowy",
  C1: "ciężarowy do 7,5 t", C: "samochód ciężarowy", D1: "autobus do 16 miejsc",
  D: "autobus", T: "ciągnik rolniczy", PT: "tramwaj",
};
const CATEGORY_ORDER = ["AM", "A1", "A2", "A", "B1", "B", "C1", "C", "D1", "D", "T", "PT"];

const app = document.getElementById("app");
const account = document.getElementById("account");
let meta = null;
let me = null;
let runner = null;

// --- helpers ------------------------------------------------------------

async function api(method, path, body) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch("api/" + path, options);
  } catch (e) {
    throw Object.assign(new Error("Brak połączenia z serwerem."), { status: 0 });
  }
  let data = {};
  try { data = await response.json(); } catch (e) { /* not JSON */ }
  if (!response.ok) {
    throw Object.assign(new Error(data.error || "Błąd " + response.status),
                        { status: response.status });
  }
  return data;
}

// el("p", {class: "x", onclick: f}, "text", child, [more, children])
function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key === "class") node.className = value;
    else if (key in node && typeof value !== "string") node[key] = value;
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : String(child));
  }
  return node;
}

function show(...nodes) {
  app.replaceChildren(...nodes);
  window.scrollTo(0, 0);
}

function remember(key, value) {
  try {
    if (value === undefined) return localStorage.getItem("pj." + key);
    localStorage.setItem("pj." + key, value);
  } catch (e) { /* storage unavailable: nothing to remember */ }
  return null;
}

const fmtNumber = (n) => String(n).replace(".", ",");
const fmtClock = (seconds) => {
  const s = Math.max(0, Math.ceil(seconds));
  return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
};
const fmtDate = (epoch) => new Date(epoch * 1000).toLocaleString("pl-PL", {
  day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
});
const langName = (code) => (meta.languages.find((l) => l.code === code) || {}).name || code;
const categoryLabel = (c) => "kat. " + c + (CATEGORY_NAMES[c] ? " – " + CATEGORY_NAMES[c] : "");
const sortCategories = (list) => list.slice().sort(
  (a, b) => (CATEGORY_ORDER.indexOf(a) + 1 || 99) - (CATEGORY_ORDER.indexOf(b) + 1 || 99));

function partMax(scope) {
  return Object.entries(meta.rules.composition[scope])
    .reduce((sum, [points, n]) => sum + Number(points) * n, 0);
}

// --- start and account --------------------------------------------------

async function start() {
  try {
    meta = await api("GET", "meta");
    await loadMe();
  } catch (e) {
    show(el("p", { class: "loading" }, e.message));
  }
}

async function loadMe() {
  try {
    me = await api("GET", "me");
  } catch (e) {
    if (e.status !== 401) throw e;
    me = null;
  }
  renderAccount();
  if (me) showDashboard(); else showLogin("login");
}

function renderAccount() {
  if (!me) return account.replaceChildren();
  account.replaceChildren(
    el("span", {}, me.user.username),
    el("button", { type: "button", onclick: logout }, "Wyloguj"));
}

async function logout() {
  if (runner && !confirm("Egzamin trwa dalej, możesz do niego wrócić po zalogowaniu. Wylogować?")) return;
  stopRunner();
  try { await api("POST", "logout"); } catch (e) { /* logged out anyway */ }
  me = null;
  renderAccount();
  showLogin("login");
}

function showLogin(mode) {
  const register = mode === "register";
  const error = el("p", { class: "error", role: "alert" });
  const username = el("input", {
    type: "text", id: "username", autocomplete: "username", maxlength: "32",
    autocapitalize: "none", spellcheck: "false", required: true,
  });
  const password = el("input", {
    type: "password", id: "password", required: true,
    autocomplete: register ? "new-password" : "current-password",
  });
  const password2 = register && el("input", {
    type: "password", id: "password2", autocomplete: "new-password", required: true,
  });
  const submit = el("button", { class: "btn primary big", type: "submit" },
                    register ? "Załóż konto" : "Zaloguj się");

  async function onSubmit(event) {
    event.preventDefault();
    error.textContent = "";
    if (register && password.value !== password2.value) {
      error.textContent = "Hasła się różnią.";
      return;
    }
    submit.disabled = true;
    try {
      await api("POST", register ? "register" : "login",
                { username: username.value, password: password.value });
      await loadMe();
    } catch (e) {
      error.textContent = e.message;
      submit.disabled = false;
    }
  }

  const tab = (name, label) => el("button", {
    type: "button", class: mode === name ? "active" : "",
    onclick: () => showLogin(name),
  }, label);

  show(el("section", { class: "panel auth" },
    el("div", { class: "tabs" }, tab("login", "Logowanie"), tab("register", "Nowe konto")),
    el("p", { class: "muted" }, register
      ? "Wystarczy nazwa użytkownika i hasło."
      : "Zaloguj się, aby rozwiązywać testy i śledzić swoje wyniki."),
    el("form", { onsubmit: onSubmit },
      el("label", { for: "username" }, "Nazwa użytkownika"), username,
      register && el("p", { class: "hint" }, "3–32 znaki: litery, cyfry, kropka, myślnik, podkreślnik."),
      el("label", { for: "password" }, "Hasło"), password,
      register && el("label", { for: "password2" }, "Powtórz hasło"), password2,
      register && el("p", { class: "hint" }, "Co najmniej 6 znaków."),
      submit, error)));
  username.focus();
}

// --- dashboard ----------------------------------------------------------

function showDashboard() {
  const s = me.stats;
  const stat = (value, label, cls) => el("div", { class: "panel stat " + (cls || "") },
    el("div", { class: "value" }, value), el("div", { class: "label" }, label));

  let lang = remember("lang") || "pl";
  if (!meta.available[lang]) lang = "pl";
  let category = remember("category") || "B";

  const cats = el("div", { class: "cats" });
  const startButton = el("button", { class: "btn primary big", type: "button" }, "Rozpocznij test");
  const langSelect = el("select", { id: "lang" },
    meta.languages.map((l) => el("option", { value: l.code, selected: l.code === lang }, l.name)));

  function renderCategories() {
    const available = meta.available[lang] || [];
    if (!available.includes(category)) category = available.includes("B") ? "B" : available[0];
    cats.replaceChildren(...sortCategories(meta.categories).map((c) => el("button", {
      type: "button", class: "cat" + (c === category ? " active" : ""),
      disabled: !available.includes(c),
      title: available.includes(c) ? null : "Za mało pytań w tym języku",
      onclick: () => { category = c; remember("category", c); renderCategories(); },
    }, el("b", {}, c), el("span", {}, CATEGORY_NAMES[c] || ""))));
    startButton.disabled = !category;
  }
  langSelect.addEventListener("change", () => {
    lang = langSelect.value;
    remember("lang", lang);
    renderCategories();
  });
  startButton.addEventListener("click", () => showIntro(category, lang));
  renderCategories();

  const current = me.current && el("section", { class: "panel notice" },
    el("div", {},
      el("b", {}, "Masz niedokończony egzamin"),
      el("div", { class: "muted" }, categoryLabel(me.current.category) + ", " +
        langName(me.current.lang) + " · zostało " + fmtClock(me.current.remaining))),
    el("div", { class: "row" },
      el("button", { class: "btn primary", type: "button", onclick: resumeExam }, "Kontynuuj"),
      el("button", {
        class: "btn danger", type: "button", onclick: async () => {
          if (!confirm("Zakończyć egzamin? Pytania bez odpowiedzi liczą się jako błędne.")) return;
          await api("POST", "exams/" + me.current.id + "/finish");
          await loadMe();
        },
      }, "Zakończ")));

  const history = me.history.length ? el("div", { class: "table-wrap" }, el("table", { class: "history" },
    el("thead", {}, el("tr", {},
      el("th", {}, "Data"), el("th", {}, "Kategoria"), el("th", { class: "lang" }, "Język"),
      el("th", {}, "Wynik"), el("th", {}, ""), el("th", { class: "open" }, ""))),
    el("tbody", {}, me.history.map((h) => el("tr", { onclick: () => openResult(h.id) },
      el("td", {}, fmtDate(h.started_at)),
      el("td", {}, h.category),
      el("td", { class: "lang" }, langName(h.lang)),
      el("td", { class: "nowrap" }, h.score + " / " + meta.rules.max_points),
      el("td", {}, el("span", { class: "tag " + (h.passed ? "good" : "bad") },
                     el("span", { class: "long" }, h.passed ? "zaliczony" : "niezaliczony"),
                     el("span", { class: "short" }, h.passed ? "✓" : "✗"))),
      el("td", { class: "open" }, el("button", { class: "btn", type: "button" }, "Przegląd")))))))
    : el("p", { class: "muted" }, "Nie masz jeszcze rozwiązanych testów.");

  show(el("div", { class: "stack" },
    el("h1", {}, "Cześć, " + me.user.username + "!"),
    current,
    el("div", { class: "stats" },
      stat(s.taken, "rozwiązane testy"),
      stat(s.passed, "zaliczone", "good"),
      stat(s.failed, "niezaliczone", "bad"),
      stat(s.average === null ? "–" : fmtNumber(s.average),
           "średnio punktów (na " + meta.rules.max_points + ")")),
    el("section", { class: "panel" },
      el("h2", {}, "Nowy test"),
      el("div", { class: "row" },
        el("div", { class: "grow" }, el("label", { for: "lang" }, "Język pytań"), langSelect)),
      el("label", {}, "Kategoria"),
      cats,
      el("div", { class: "exam-actions" }, startButton)),
    el("section", { class: "panel" }, el("h2", {}, "Ostatnie testy"), history)));
}

function showIntro(category, lang) {
  const c = meta.rules.composition;
  const t = meta.rules.time_limits;
  const error = el("p", { class: "error", role: "alert" });
  const go = el("button", { class: "btn primary big", type: "button" }, "Rozpocznij egzamin");
  go.addEventListener("click", async () => {
    if (me.current && !confirm("Nowy egzamin zakończy ten niedokończony. Kontynuować?")) return;
    go.disabled = true;
    try {
      startRunner(await api("POST", "exams", { category, lang }));
    } catch (e) {
      error.textContent = e.message;
      go.disabled = false;
    }
  });
  const count = (scope) => Object.values(c[scope]).reduce((a, b) => a + b, 0);
  show(el("section", { class: "panel stack" },
    el("h1", {}, "Egzamin teoretyczny – " + categoryLabel(category)),
    el("p", { class: "muted" }, "Język pytań: " + langName(lang)),
    el("ul", { class: "rules" },
      el("li", {}, (count("basic") + count("specialist")) + " pytania: " + count("basic") +
        " z wiedzy podstawowej (odpowiedź TAK lub NIE) i " + count("specialist") +
        " z wiedzy specjalistycznej (jedna z odpowiedzi A, B, C)."),
      el("li", {}, "Pytanie podstawowe: " + t.basic.read + " s na zapoznanie się z treścią, " +
        "potem film odtwarza się jeden raz, a na odpowiedź masz " + t.basic.answer +
        " s. Przycisk START skraca czas na zapoznanie się."),
      el("li", {}, "Pytanie specjalistyczne: " + t.specialist.answer + " s na przeczytanie i odpowiedź."),
      el("li", {}, "Odpowiedź możesz zmieniać do przejścia dalej. Do poprzednich pytań nie można wrócić; " +
        "pytanie bez odpowiedzi to 0 punktów."),
      el("li", {}, "Pytania są warte 1, 2 lub 3 punkty. Czas egzaminu: " + meta.rules.duration_minutes +
        " minut. Do zdobycia " + meta.rules.max_points + " pkt, zaliczenie od " +
        meta.rules.pass_points + " pkt.")),
    el("div", { class: "exam-actions" },
      el("button", { class: "btn", type: "button", onclick: showDashboard }, "Wróć"), go),
    error));
  go.focus();
}

async function resumeExam() {
  try {
    const data = await api("GET", "exams/current");
    if (data.exam) startRunner(data.exam); else await loadMe();
  } catch (e) {
    alert(e.message);
  }
}

// --- the exam -----------------------------------------------------------

function startRunner(exam) {
  stopRunner();
  runner = new ExamRunner(exam);
  runner.start();
}

function stopRunner() {
  if (runner) runner.stop();
  runner = null;
}

class ExamRunner {
  constructor(exam) {
    this.exam = exam;
    this.pos = exam.next_position;
    this.deadline = performance.now() + exam.remaining * 1000;
    this.yesNo = YES_NO[exam.lang] || YES_NO.pl;
    this.media = new Map();  // url -> element, for this question and the next
    this.token = 0;          // changes with every question, to drop stale callbacks
    this.busy = false;
  }

  start() {
    this.build();
    this.interval = setInterval(() => this.tick(), 200);
    this.onKey = (e) => this.key(e);
    this.onUnload = (e) => { e.preventDefault(); e.returnValue = ""; };
    document.addEventListener("keydown", this.onKey);
    window.addEventListener("beforeunload", this.onUnload);
    this.showQuestion();
  }

  stop() {
    clearInterval(this.interval);
    document.removeEventListener("keydown", this.onKey);
    window.removeEventListener("beforeunload", this.onUnload);
    this.token++;
    for (const m of this.media.values()) if (m.pause) m.pause();
  }

  build() {
    const item = (label, short) => {
      const value = el("div", { class: "value" });
      return [el("div", { class: "status-item" }, el("div", { class: "label" },
        el("span", { class: "long" }, label), el("span", { class: "short" }, short)), value), value];
    };
    let basicBox, specialistBox, pointsBox, clockBox;
    [pointsBox, this.pointsValue] = item("Wartość punktowa", "Wartość");
    [basicBox, this.basicValue] = item("Pytania podstawowe", "Podst.");
    [specialistBox, this.specialistValue] = item("Pytania specjalistyczne", "Spec.");
    [clockBox, this.clockValue] = item("Czas do końca egzaminu", "Egzamin");

    this.phaseLabel = el("div", { class: "label" });
    this.phaseValue = el("div", { class: "value" });
    this.phaseFill = el("div", { class: "fill" });
    this.startButton = el("button", { class: "btn primary", type: "button", onclick: () => this.skipReading() }, "START");
    this.timerBox = el("div", { class: "timer" }, this.phaseLabel, this.phaseValue,
      el("div", { class: "track" }, this.phaseFill), this.startButton);

    this.mediaBox = el("div", {
      class: "media",
      onclick: () => { if (this.mediaBox.classList.contains("waiting")) this.skipReading(); },
    });
    this.questionText = el("p", { class: "question-text" });
    this.answersBox = el("div", { class: "answers" });
    this.error = el("p", { class: "error", role: "alert" });
    this.nextButton = el("button", { class: "btn primary big", type: "button", onclick: () => this.next() }, "Następne pytanie");

    show(el("div", { class: "exam" },
      el("section", { class: "panel" },
        this.mediaBox, this.questionText, this.answersBox,
        el("div", { class: "exam-actions" }, this.nextButton), this.error,
        el("p", { class: "hint" }, "Klawisze: T / N lub A / B / C – odpowiedź, spacja – START, Enter – następne pytanie.")),
      el("aside", { class: "panel exam-status" },
        el("div", { class: "status-list" },
          el("div", { class: "status-item category" }, el("div", { class: "label" }, "Kategoria"),
             el("div", { class: "value" }, this.exam.category)),
          pointsBox, basicBox, specialistBox, clockBox, this.timerBox),
        el("button", { class: "btn danger", type: "button", onclick: () => this.quit() }, "Zakończ egzamin"))));
  }

  mediaFor(q) {
    if (!q || !q.media_url) return null;
    let m = this.media.get(q.media_url);
    if (!m) {
      if (q.media_type === "video") {
        m = el("video", { preload: "auto", playsinline: true, disablePictureInPicture: true });
        m.src = q.media_url;
      } else {
        m = el("img", { alt: "Ilustracja do pytania" });
        m.src = q.media_url;
      }
      this.media.set(q.media_url, m);
    }
    return m;
  }

  showQuestion() {
    const token = ++this.token;
    const questions = this.exam.questions;
    const q = this.q = questions[this.pos];
    this.selected = null;
    this.busy = false;
    this.error.textContent = "";
    this.nextButton.disabled = false;

    // Keep only this question's and the next one's media (loading it now).
    const current = this.mediaFor(q);
    const upcoming = this.mediaFor(questions[this.pos + 1]);
    for (const [url, m] of this.media) {
      if (m !== current && m !== upcoming) { if (m.pause) m.pause(); this.media.delete(url); }
    }

    const basicCount = questions.filter((x) => x.scope === "basic").length;
    const specialistCount = questions.length - basicCount;
    const basic = q.scope === "basic";
    this.basicValue.textContent = (basic ? this.pos + 1 : basicCount) + " / " + basicCount;
    this.specialistValue.textContent = (basic ? 0 : this.pos + 1 - basicCount) + " / " + specialistCount;
    this.pointsValue.textContent = q.points + " pkt";
    this.questionText.textContent = q.question || "(pytania nie ma już w bazie)";

    this.answerButtons = {};
    const button = (key, content) => {
      const b = el("button", { class: "answer", type: "button", onclick: () => this.select(key) }, content);
      this.answerButtons[key] = b;
      return b;
    };
    this.answersBox.className = "answers" + (basic ? " yesno" : "");
    this.answersBox.replaceChildren(...(basic
      ? [button("T", this.yesNo[0]), button("N", this.yesNo[1])]
      : ["A", "B", "C"].map((k) => button(k, [el("span", { class: "key" }, k), el("span", {}, q.answers[k])]))));

    if (!current) {
      this.mediaBox.className = "media none";
      this.mediaBox.replaceChildren("Pytanie bez ilustracji");
    } else if (q.media_type === "video" && basic) {
      this.mediaBox.className = "media waiting";
      current.hidden = true;
      this.mediaBox.replaceChildren(current, el("div", { class: "placeholder" },
        el("b", {}, "Film"), "Odtworzy się po kliknięciu START lub po upływie czasu na zapoznanie się z pytaniem."));
    } else {
      this.mediaBox.className = "media";
      current.hidden = false;
      this.mediaBox.replaceChildren(current);
    }

    if (basic) {
      this.setPhase("read");
    } else {
      this.setPhase("answer");
      if (q.media_type === "video") this.playVideo(token, () => {});
    }
  }

  setPhase(phase) {
    const limits = meta.rules.time_limits;
    const basic = this.q.scope === "basic";
    this.phase = phase;
    this.startButton.hidden = phase !== "read";
    if (phase === "read") {
      this.phaseSeconds = limits.basic.read;
      this.phaseLabel.textContent = "Czas na zapoznanie się z pytaniem";
    } else if (phase === "play") {
      this.phaseSeconds = null;
      this.phaseLabel.textContent = "Trwa odtwarzanie filmu";
      this.phaseValue.textContent = "▶";
      this.phaseFill.style.width = "100%";
      this.timerBox.classList.remove("urgent");
      const token = this.token;
      this.playVideo(token, () => { if (token === this.token) this.setPhase("answer"); });
    } else {
      this.phaseSeconds = basic ? limits.basic.answer : limits.specialist.answer;
      this.phaseLabel.textContent = "Czas na udzielenie odpowiedzi";
    }
    this.phaseEnd = this.phaseSeconds === null ? null : performance.now() + this.phaseSeconds * 1000;
    this.tick();
  }

  playVideo(token, done) {
    const video = this.media.get(this.q.media_url);
    let finished = false;
    const finish = () => {
      if (finished || token !== this.token) return;
      finished = true;
      clearTimeout(this.videoTimeout);
      done();
    };
    video.hidden = false;
    this.mediaBox.className = "media";
    this.mediaBox.replaceChildren(video);
    video.onended = finish;
    video.onerror = finish;
    // Never wait for a stuck video longer than it lasts (or 90 s).
    const watchdog = () => {
      clearTimeout(this.videoTimeout);
      const seconds = isFinite(video.duration) && video.duration > 0 ? video.duration + 8 : 90;
      this.videoTimeout = setTimeout(finish, seconds * 1000);
    };
    if (video.readyState >= 1) watchdog(); else video.onloadedmetadata = watchdog;
    try { video.currentTime = 0; } catch (e) { /* not loaded yet */ }
    video.muted = false;
    video.play().catch(() => {
      video.muted = true;  // the browser refused sound without a click
      video.play().catch(finish);
    });
  }

  skipReading() {
    if (this.phase !== "read") return;
    this.setPhase(this.q.media_type === "video" ? "play" : "answer");
  }

  select(key) {
    if (this.busy) return;
    this.selected = key;
    for (const [k, b] of Object.entries(this.answerButtons)) b.classList.toggle("selected", k === key);
  }

  tick() {
    const now = performance.now();
    const left = (this.deadline - now) / 1000;
    this.clockValue.textContent = fmtClock(left);
    this.clockValue.classList.toggle("warn", left < 120);
    if (left <= 0) return this.timeUp();
    if (this.phaseEnd === null || this.phaseEnd === undefined) return;
    const phaseLeft = (this.phaseEnd - now) / 1000;
    this.phaseValue.textContent = Math.max(0, Math.ceil(phaseLeft)) + " s";
    this.phaseFill.style.width = Math.max(0, 100 * phaseLeft / this.phaseSeconds) + "%";
    this.timerBox.classList.toggle("urgent", phaseLeft <= 5 && this.phase === "answer");
    if (phaseLeft <= 0) {
      if (this.phase === "read") this.skipReading();
      else if (this.phase === "answer") this.next();
    }
  }

  key(e) {
    if (e.ctrlKey || e.metaKey || e.altKey || this.busy) return;
    const k = e.key.toLowerCase();
    const basic = this.q.scope === "basic";
    const map = basic ? { t: "T", y: "T", j: "T", n: "N" } : { a: "A", b: "B", c: "C", 1: "A", 2: "B", 3: "C" };
    if (map[k]) { this.select(map[k]); e.preventDefault(); }
    else if (e.key === "Enter") { this.next(); e.preventDefault(); }
    else if (e.key === " ") { this.skipReading(); e.preventDefault(); }
  }

  async next() {
    if (this.busy) return;
    this.busy = true;
    this.phaseEnd = null;
    this.nextButton.disabled = true;
    const token = ++this.token;  // stops this question's timers and video
    const video = this.q.media_type === "video" && this.media.get(this.q.media_url);
    if (video) video.pause();
    try {
      const result = await api("POST", "exams/" + this.exam.id + "/answer",
                               { position: this.pos, answer: this.selected });
      if (token !== this.token) return;
      if (result.finished) return this.done();
      this.pos++;
      this.showQuestion();
    } catch (e) {
      if (token !== this.token) return;
      if (e.status === 400 || e.status === 404) return this.done();  // e.g. time ran out
      this.error.replaceChildren(e.message + " ", el("button", {
        class: "btn", type: "button", onclick: () => { this.busy = false; this.next(); },
      }, "Spróbuj ponownie"));  // answers stay locked until the retry
    }
  }

  async timeUp() {
    if (this.ending) return;
    this.ending = true;
    this.stop();
    try { await api("POST", "exams/" + this.exam.id + "/finish"); } catch (e) { /* scored anyway */ }
    this.done();
  }

  async quit() {
    if (!confirm("Zakończyć egzamin? Pytania bez odpowiedzi liczą się jako błędne.")) return;
    this.stop();
    try { await api("POST", "exams/" + this.exam.id + "/finish"); } catch (e) { /* scored anyway */ }
    this.done();
  }

  done() {
    const id = this.exam.id;
    stopRunner();
    openResult(id);
  }
}

// --- result and review --------------------------------------------------

async function openResult(id) {
  try {
    const [exam, fresh] = await Promise.all([api("GET", "exams/" + id), api("GET", "me")]);
    me = fresh;
    showResult(exam);
  } catch (e) {
    if (e.status === 401) return loadMe();
    alert(e.message);
  }
}

function showResult(exam) {
  const yesNo = YES_NO[exam.lang] || YES_NO.pl;
  const right = (q) => q.answer !== null && q.answer === q.correct;
  const scored = (scope) => exam.questions.filter((q) => q.scope === scope && right(q))
    .reduce((sum, q) => sum + q.points, 0);
  const wrongCount = exam.questions.filter((q) => !right(q)).length;

  const onlyWrong = el("input", { type: "checkbox", checked: wrongCount > 0 });
  const list = el("div", { class: "stack" });

  function reviewItem(q) {
    const options = q.scope === "basic"
      ? [["T", yesNo[0]], ["N", yesNo[1]]]
      : ["A", "B", "C"].map((k) => [k, k + ") " + (q.answers[k] || "")]);
    let media = null;
    if (q.media_type === "video") {
      media = el("div", { class: "media" }, el("video", {
        src: q.media_url, controls: true, preload: "metadata", playsinline: true,
      }));
    } else if (q.media_type === "image") {
      media = el("div", { class: "media" }, el("img", { src: q.media_url, alt: "Ilustracja do pytania", loading: "lazy" }));
    }
    return el("article", { class: "panel review-item " + (right(q) ? "good" : "bad") },
      el("div", { class: media ? "review-grid" : "" },
        media,
        el("div", {},
          el("div", { class: "review-meta" }, "Pytanie " + (q.position + 1) + " · " +
            (q.scope === "basic" ? "podstawowe" : "specjalistyczne") + " · " + q.points + " pkt"),
          el("p", { class: "review-q" }, q.question || "(pytania nie ma już w bazie)"),
          options.map(([key, text]) => {
            const isCorrect = key === q.correct;
            const isChosen = key === q.answer;
            return el("div", { class: "opt" + (isCorrect ? " correct" : isChosen ? " wrong" : "") },
              text,
              isCorrect && el("span", { class: "who" }, "✓ poprawna"),
              isChosen && el("span", { class: "who" }, "· Twoja odpowiedź"));
          }),
          q.answer === null && el("div", { class: "review-none" }, "Brak odpowiedzi"))));
  }

  function renderList() {
    const items = exam.questions.filter((q) => !onlyWrong.checked || !right(q));
    list.replaceChildren(...(items.length ? items.map(reviewItem)
      : [el("p", { class: "muted" }, "Wszystkie odpowiedzi poprawne!")]));
  }
  onlyWrong.addEventListener("change", renderList);
  renderList();

  show(el("div", { class: "stack" },
    el("section", { class: "panel result-head " + (exam.passed ? "good" : "bad") },
      el("div", { class: "verdict" }, exam.passed ? "WYNIK POZYTYWNY" : "WYNIK NEGATYWNY"),
      el("div", { class: "score" }, exam.score, el("small", {}, " / " + meta.rules.max_points + " pkt")),
      el("div", { class: "muted" }, "Zaliczenie od " + meta.rules.pass_points + " pkt · " +
        categoryLabel(exam.category) + " · " + langName(exam.lang) + " · " + fmtDate(exam.started_at)),
      el("div", { class: "result-parts" },
        el("span", {}, "Część podstawowa: " + scored("basic") + " / " + partMax("basic") + " pkt"),
        el("span", {}, "Część specjalistyczna: " + scored("specialist") + " / " + partMax("specialist") + " pkt"),
        el("span", {}, "Poprawne odpowiedzi: " + (exam.questions.length - wrongCount) + " / " + exam.questions.length)),
      el("div", { class: "result-actions" },
        el("button", { class: "btn primary", type: "button", onclick: () => showIntro(exam.category, exam.lang) }, "Nowy test"),
        el("button", { class: "btn", type: "button", onclick: showDashboard }, "Panel główny"))),
    el("div", { class: "review-bar" },
      el("h2", {}, "Przegląd odpowiedzi"),
      el("label", { class: "check" }, onlyWrong, "tylko błędne")),
    list));
}

start();
