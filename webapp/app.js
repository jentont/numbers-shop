/* Solutions Numbers — витрина Telegram-аккаунтов.
   Без сборки: один файл, ванильный JS. Данные — /api/*, подпись initData.
   Длинных лент нет: страны, лоты, покупки и история листаются страницами. */
(() => {
"use strict";

const tg = window.Telegram && window.Telegram.WebApp;
const qs = new URLSearchParams(location.search);
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const PAGE = { c: 8, l: 8, o: 6, h: 6 };
const S = {
  me: null, lang: "en", home: null, country: null, sort: "cheap", cat: "all", q: "", region: "all", csort: "pop",
  filters: { pmin: "", pmax: "", premium: false, nopass: false, fresh: false, origin: "" },
  page: { c: 0, l: 0, o: 0, h: 0 }, amount: 250, tab: "market", poll: {}, cart: [], hist: [], orders: [],
};

// ── i18n ────────────────────────────────────────────────────────────
function t(key, vars) {
  const d = I18N[S.lang] || I18N.en;
  let s = d[key] ?? I18N.en[key] ?? key;
  if (vars) for (const k in vars) s = s.replaceAll("{" + k + "}", vars[k]);http://localhost:8090/?dev=1&tab=wallet
  return s;
}
let regionNames = null;
function cname(iso2) {
  try {
    if (!regionNames || regionNames._lang !== S.lang) { regionNames = new Intl.DisplayNames([S.lang, "en"], { type: "region" }); regionNames._lang = S.lang; }
    return regionNames.of(iso2) || iso2;
  } catch { return iso2; }
}
function applyI18n() {
  document.documentElement.lang = S.lang;
  document.body.dir = RTL.includes(S.lang) ? "rtl" : "ltr";
  $$("[data-t]").forEach((el) => { el.textContent = t(el.dataset.t); });
  $$("[data-tp]").forEach((el) => { el.placeholder = t(el.dataset.tp); });
  $("#lang-v").textContent = LANGS[S.lang];
}

// ── иконки ──────────────────────────────────────────────────────────
function ic(name, cls = "ic") {
  const body = (window.ICONS || {})[name] || "";
  return `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
}
function paintIcons(root = document) { $$("[data-i]", root).forEach((el) => { if (!el.querySelector("svg")) el.insertAdjacentHTML("afterbegin", ic(el.dataset.i)); }); }

// ── страны ──────────────────────────────────────────────────────────
const C = window.NUM_COUNTRIES || {};   // из webapp/countries.js (tools/gen_countries.py)
const REGIONS = window.NUM_REGIONS || {};
const iso2 = (c3) => (C[c3] || ["", ""])[0];
const dial = (c3) => (C[c3] || ["", ""])[1];
// Флаги — свои SVG (эмодзи-флагов нет на Windows и в Telegram Desktop).
const flagImg = (c2) => `<img class="fl" src="static/flags/${c2.toLowerCase()}.svg" alt="${c2}" loading="lazy" draggable="false">`;
const flag = (c3) => { const c = iso2(c3); return c ? flagImg(c) : ic("globe"); };
const cn = (c3) => cname(iso2(c3) || c3);
function mask(c3, seed) {
  let n = Math.abs(seed | 0);
  const digit = () => { n = (n * 9301 + 49297) % 233280; return String(n % 10); };
  return `+${dial(c3)} ${digit()}${digit()}• ••• ••${digit()}${digit()}`;
}

// ── деньги и время ──────────────────────────────────────────────────
function money(kop) {
  const r = kop / 100;
  return new Intl.NumberFormat(S.lang === "ru" ? "ru-RU" : undefined, { maximumFractionDigits: r % 1 ? 2 : 0 }).format(r) + " ₽";
}
function ago(ts) {
  const d = Math.max(0, Date.now() / 1000 - ts);
  if (d < 3600) return t("ago_m", { n: Math.max(1, Math.round(d / 60)) });
  if (d < 86400) return t("ago_h", { n: Math.round(d / 3600) });
  return t("ago_d", { n: Math.round(d / 86400) });
}

// ── API ─────────────────────────────────────────────────────────────
async function api(path, body) {
  const headers = { "Content-Type": "application/json" };
  if (tg && tg.initData) headers["X-Init-Data"] = tg.initData;
  else if (qs.get("dev")) headers["X-Dev"] = qs.get("dev");
  const r = await fetch(path, { method: body ? "POST" : "GET", headers, body: body ? JSON.stringify(body) : undefined });
  let data = {};
  try { data = await r.json(); } catch { /* пусто */ }
  if (!r.ok) { const e = new Error(data.error || "err"); e.data = data; throw e; }
  return data;
}
function errText(e) {
  const code = (e && e.message) || "err";
  if (code === "need_sub") { subGate(); return t("sub_fail"); }
  if (code.startsWith("min:")) return t("min_amount", { p: money(+code.slice(4) * 100) });
  if (code === "no_money") return t("no_money", { p: money(Math.max(0, e.data.need - S.me.balance)) });
  if (code === "price_changed") return t("price_changed", { p: money(e.data.price) });
  if (code === "not_subscribed") return t("gw_need_sub");
  if (code === "off") return t("gw_off");
  if (code === "terms") return t("terms_err");
  if (code === "day_limit") return t("day_limit", { n: e.data.limit });
  return (I18N.en[code] ? t(code) : t("err"));
}

// Звёзды — белые: белая звезда на чёрном кружке (жёлтый эмодзи ⭐ не используем).
function starIc(cls = "ic") {
  return `<svg class="${cls}" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" aria-hidden="true">${(window.ICONS || {}).star || ""}</svg>`;
}
const starDot = () => `<span class="star-dot">${starIc()}</span>`;
const starsNote = (n) => esc(t("stars_note", { n })).replace("⭐", starDot());

// ── мелочи UI ───────────────────────────────────────────────────────
let toastTimer;
function toast(msg) {
  const el = $("#toast"); el.textContent = msg; el.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => (el.hidden = true), 2800);
}
const haptic = (k = "light") => { try { tg && tg.HapticFeedback.impactOccurred(k); } catch {} };
const notifyH = (k) => { try { tg && tg.HapticFeedback.notificationOccurred(k); } catch {} };
function copy(text) {
  (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).catch(() => {
    const ta = document.createElement("textarea"); ta.value = text; document.body.append(ta); ta.select(); document.execCommand("copy"); ta.remove();
  });
  notifyH("success"); toast(t("copied"));
}
function openLink(url) { if (!url) return; if (tg && url.includes("t.me/")) tg.openTelegramLink(url); else if (tg) tg.openLink(url); else window.open(url, "_blank"); }
function setBalance(kop) { S.me.balance = kop; $("#bal-val").textContent = money(kop); $("#w-bal").textContent = money(kop); }

// Страницы: ‹ 1 2 3 … 9 ›
function pager(el, key, total) {
  const per = PAGE[key], pages = Math.ceil(total / per);
  if (pages <= 1) { el.innerHTML = ""; return; }
  const cur = Math.min(S.page[key], pages - 1);
  const nums = [];
  for (let i = 0; i < pages; i++) {
    if (i === 0 || i === pages - 1 || Math.abs(i - cur) <= 1) nums.push(i);
    else if (nums[nums.length - 1] !== "…") nums.push("…");
  }
  el.innerHTML = `<button type="button" data-page="${key}:${cur - 1}" ${cur === 0 ? "disabled" : ""}>${ic("back")}</button>` +
    nums.map((n) => (n === "…" ? "<span>…</span>" : `<button type="button" data-page="${key}:${n}" class="${n === cur ? "is-on" : ""}">${n + 1}</button>`)).join("") +
    `<button type="button" data-page="${key}:${cur + 1}" ${cur >= pages - 1 ? "disabled" : ""}>${ic("chevron")}</button>`;
}
const slice = (arr, key) => { const per = PAGE[key]; const pages = Math.max(1, Math.ceil(arr.length / per)); S.page[key] = Math.min(Math.max(0, S.page[key]), pages - 1); return arr.slice(S.page[key] * per, S.page[key] * per + per); };

// Горизонтальные ленты: палец листает сам, мышь — перетаскиванием.
function dragScroll(el) {
  if (el._drag) return; el._drag = true;
  let x0 = 0, s0 = 0, down = false, moved = false;
  el.addEventListener("pointerdown", (e) => { if (e.pointerType !== "mouse") return; down = true; moved = false; x0 = e.clientX; s0 = el.scrollLeft; });
  window.addEventListener("pointermove", (e) => {
    if (!down) return; const dx = e.clientX - x0;
    if (Math.abs(dx) > 4) { moved = true; el.classList.add("is-drag"); }
    el.scrollLeft = s0 - dx;
  });
  window.addEventListener("pointerup", () => { if (!down) return; down = false; setTimeout(() => el.classList.remove("is-drag"), 0); });
  el.addEventListener("click", (e) => { if (moved) { e.stopPropagation(); e.preventDefault(); moved = false; } }, true);
  el.addEventListener("wheel", (e) => { if (Math.abs(e.deltaY) > Math.abs(e.deltaX) && el.scrollWidth > el.clientWidth) { el.scrollLeft += e.deltaY; e.preventDefault(); } }, { passive: false });
}

// ── корзина (хранится у человека в браузере) ─────────────────────────
function loadCart() { try { S.cart = JSON.parse(localStorage.getItem("sn_cart") || "[]"); } catch { S.cart = []; } }
function saveCart() { try { localStorage.setItem("sn_cart", JSON.stringify(S.cart)); } catch {} renderCartBadge(); }
function renderCartBadge() { const n = S.cart.length; $("#cart-n").hidden = !n; $("#cart-n").textContent = n; }
const inCart = (id) => S.cart.some((x) => x.id === id);
function toggleCart(l) {
  if (inCart(l.id)) S.cart = S.cart.filter((x) => x.id !== l.id);
  else S.cart.push({ id: l.id, country: l.country, price: l.price, premium: l.premium, password: l.password, session_days: l.session_days, published: l.published });
  saveCart(); haptic();
}
function cartSheet() {
  const total = S.cart.reduce((s, x) => s + x.price, 0);
  const el = sheet(`<h2>${t("cart")}</h2>
    ${S.cart.length ? `<div class="list">${S.cart.map((l) => `
      <div class="row cart-row"><span class="row-ic">${flag(l.country)}</span>
        <span class="row-t"><span class="num" style="font-weight:800;direction:ltr">${mask(l.country, l.id)}</span><small>${esc(cn(l.country))}</small></span>
        <span class="row-price"><b>${money(l.price)}</b></span>
        <button class="x" type="button" data-rm="${l.id}">${ic("x")}</button></div>`).join("")}</div>
      <div class="cart-total"><span>${t("total")}</span><b>${money(total)}</b></div>
      ${S.me.balance >= total ? `<button class="btn btn-ink btn-wide" id="buy-all" type="button">${ic("cart")}${t("buy_all")}</button>`
        : `<button class="btn btn-ink btn-wide" id="cart-top" type="button">${ic("plus")}${t("topup_btn")}</button><div class="note">${t("no_money", { p: money(total - S.me.balance) })}</div>`}`
      : `<div class="empty">${ic("cart")}${t("cart_empty")}</div>`}`);
  el.onclick = async (e) => {
    const rm = e.target.closest("[data-rm]");
    if (rm) { S.cart = S.cart.filter((x) => x.id !== +rm.dataset.rm); saveCart(); return cartSheet(); }
    if (e.target.closest("#cart-top")) { closeSheet(); S.amount = Math.max(S.me.topup_min, Math.ceil((total - S.me.balance) / 100)); return topupSheet(); }
    const b = e.target.closest("#buy-all"); if (!b) return;
    if (!S.me.terms_ok) return needTerms(cartSheet);
    b.disabled = true; let ok = 0; const n = S.cart.length;
    for (const l of [...S.cart]) {
      try { const r = await api("/api/buy", { item_id: l.id, price: l.price }); setBalance(r.balance); ok++; }
      catch (err) { if (err.message === "no_money") break; }
      S.cart = S.cart.filter((x) => x.id !== l.id);
    }
    saveCart(); notifyH(ok ? "success" : "error"); toast(t("bought_n", { n: ok, m: n })); closeSheet(); openTab("orders");
  };
}

// ── шторка ──────────────────────────────────────────────────────────
let sheetClose = null;
function sheet(html, onClose) {
  $("#sheet-body").innerHTML = html; paintIcons($("#sheet-body"));
  $$(".hscroll", $("#sheet-body")).forEach(dragScroll);
  $("#sheet-wrap").hidden = false; sheetClose = onClose || null; updateBack();
  $("#sheet").scrollTop = 0;
  return $("#sheet-body");
}
function closeSheet() { $("#sheet-wrap").hidden = true; clearTimeout(S.poll.order); const f = sheetClose; sheetClose = null; f && f(); updateBack(); }

// ── навигация ───────────────────────────────────────────────────────
function show(screen) {
  $$(".screen").forEach((s) => s.classList.toggle("is-on", s.dataset.screen === screen));
  const tab = screen === "country" ? "market" : screen;
  $$("#tabbar button").forEach((b) => b.classList.toggle("is-on", b.dataset.tab === tab));
  S.screen = screen; window.scrollTo(0, 0); updateBack();
}
function updateBack() {
  if (!tg) return;
  (!$("#sheet-wrap").hidden || S.screen === "country") ? tg.BackButton.show() : tg.BackButton.hide();
}
function goBack() {
  if (!$("#sheet-wrap").hidden) return closeSheet();
  if (S.screen === "country") return show("market");
}

// ── главная ─────────────────────────────────────────────────────────
async function loadHome() {
  try { S.home = await api("/api/home"); } catch (e) { toast(errText(e)); return; }
  $("#demo").hidden = !S.home.demo;
  if (S.home.buy_paused) { $("#demo").hidden = false; $("#demo").textContent = t("buy_paused"); }
  renderHome();
}
function renderCats() {
  const cats = [["all", "globe", "cat_all"], ["instant", "bolt", "cat_instant"], ["fresh", "flame", "cat_fresh"], ["promo", "percent", "cat_promo"]];
  $("#cats").innerHTML = cats.map(([id, i, k]) => `<button class="chip ${S.cat === id ? "is-on" : ""}" data-cat="${id}" type="button">${ic(i)}${t(k)}</button>`).join("");
  const regs = [["all", "reg_all"], ["cis", "reg_cis"], ["eu", "reg_eu"], ["asia", "reg_asia"], ["am", "reg_am"], ["af", "reg_af"]];
  $("#regions").innerHTML = regs.map(([id, k]) => `<button class="chip ${S.region === id ? "is-on" : ""}" data-region="${id}" type="button">${t(k)}</button>`).join("");
  const sorts = [["pop", "csort_pop"], ["up", "csort_up"], ["down", "csort_down"], ["name", "csort_name"]];
  $("#csort").innerHTML = sorts.map(([id, k]) => `<button class="chip ${S.csort === id ? "is-on" : ""}" data-csort="${id}" type="button">${id === "up" || id === "down" ? ic("sort") : ""}${t(k)}</button>`).join("");
}
function miniCard(l) {
  return `<button class="mini" type="button" data-lot="${l.id}">
    <span class="flag">${flag(l.country)}</span>
    <span class="num">${mask(l.country, l.id)}</span>
    <span class="meta">${l.published ? ago(l.published) : esc(cn(l.country))}</span>
    <span class="price">${money(l.price)}${l.old ? `<s>${money(l.old)}</s>` : ""}</span>
  </button>`;
}
function renderHome() {
  const h = S.home; if (!h) return;
  renderCats();
  const inst = [...(h.instant || [])].sort((a, b) => b.count - a.count)[0];
  $("#hero").innerHTML = inst && (S.cat === "all" || S.cat === "instant") ? `
    <div class="hero">
      <span class="hero-tag">${ic("bolt")}${t("instant_title")}</span>
      <h2>${flag(inst.country)} ${esc(cn(inst.country))} +${dial(inst.country)}</h2>
      <p>${t("instant_sub", { n: inst.count })}</p>
      <div class="hero-row">
        <div class="hero-num"><b>${money(inst.price)}</b><small>${mask(inst.country, inst.count * 7)}</small></div>
        <button class="btn-hero" type="button" data-instant="${inst.country}">${ic("bolt")}${t("buy")}</button>
      </div>
    </div>` : "";
  $("#arrivals").innerHTML = (h.arrivals || []).length && S.cat === "all" ? `<div class="arrivals hscroll">${h.arrivals.map((a) => `
    <button class="arr" type="button" data-country="${a.country}">${ic("truck")}<span>${flag(a.country)} <b>${esc(cn(a.country))}</b> ${t("arrival", { n: a.count })} · ${ago(a.at)}</span></button>`).join("")}</div>` : "";
  $("#sec-fresh").hidden = !(h.fresh || []).length || (S.cat !== "all" && S.cat !== "fresh");
  $("#fresh").innerHTML = (h.fresh || []).map(miniCard).join("");
  $("#sec-promo").hidden = !(h.promos || []).length || (S.cat !== "all" && S.cat !== "promo");
  $("#promos").innerHTML = (h.promos || []).map((p) => `
    <button class="promo-card" type="button" data-country="${p.country}"><span>${flag(p.country)} ${esc(cn(p.country))}</span><b>−${p.percent}%</b></button>`).join("");
  $$(".hscroll").forEach(dragScroll);
  renderCountries();
}
function renderCountries() {
  const h = S.home; if (!h) return;
  const q = S.q.trim().toLowerCase().replace(/^\+/, "");
  const reg = S.region !== "all" ? REGIONS[S.region].split(" ") : null;
  let list = h.countries.filter((c) => {
    if (S.cat === "instant" && !c.instant) return false;
    if (S.cat === "promo" && !c.promo) return false;
    if (reg && !reg.includes(c.country)) return false;
    if (!q) return true;
    return cn(c.country).toLowerCase().includes(q) || dial(c.country).startsWith(q) || c.country.toLowerCase().includes(q);
  });
  if (S.csort === "up") list.sort((a, b) => a.from - b.from);
  else if (S.csort === "down") list.sort((a, b) => b.from - a.from);
  else if (S.csort === "name") list.sort((a, b) => cn(a.country).localeCompare(cn(b.country), S.lang));
  $("#ccount").textContent = t("ccount", { n: list.length });
  if (!list.length && h.market_down) { $("#countries").innerHTML = `<div class="empty" style="grid-column:1/-1">${ic("clock")}${t("market_down")}</div>`; $("#c-pager").innerHTML = ""; return; }
  $("#countries").innerHTML = list.length ? slice(list, "c").map((c) => `
    <button class="ctile" type="button" data-country="${c.country}">
      ${flag(c.country)}
      <span class="tagc">${c.instant ? `<span class="badge ink">${ic("bolt")}</span>` : ""}${c.promo ? `<span class="badge">−${c.promo}%</span>` : ""}</span>
      <b>${esc(cn(c.country))}</b>
      <small>+${dial(c.country)} · ${t("lots_n", { n: c.count })}</small>
      <span class="p">${t("from", { p: money(c.from) })}</span>
    </button>`).join("") : `<div class="empty" style="grid-column:1/-1">${ic("search")}${t("empty_lots")}</div>`;
  pager($("#c-pager"), "c", list.length);
}

// ── страна ──────────────────────────────────────────────────────────
async function openCountry(c3) {
  S.country = c3; S.lots = null; S.page.l = 0;
  const info = (S.home && S.home.countries.find((c) => c.country === c3)) || { count: 0, instant: 0 };
  $("#c-head").innerHTML = `<span class="flag">${flag(c3)}</span><div><h1>${esc(cn(c3))}</h1><small>+${dial(c3)} · ${t("lots_n", { n: info.count })}</small></div>`;
  $("#c-instant").innerHTML = instantRow(c3);
  renderSorts(); show("country");
  $("#lots").innerHTML = '<div class="skel"></div>'.repeat(5); $("#l-pager").innerHTML = "";
  await loadLots();
}
function instantRow(c3) {
  const inst = ((S.home && S.home.instant) || []).find((x) => x.country === c3);
  if (!inst) return "";
  return `<div class="hero" style="margin:12px 0"><span class="hero-tag">${ic("bolt")}${t("instant_title")}</span>
    <p style="margin-top:8px">${t("instant_sub", { n: inst.count })}</p>
    <div class="hero-row"><div class="hero-num"><b>${money(inst.price)}</b></div>
    <button class="btn-hero" type="button" data-instant="${c3}">${ic("bolt")}${t("buy")}</button></div></div>`;
}
function renderSorts() {
  const sorts = [["cheap", "sort_cheap"], ["expensive", "sort_exp"], ["new", "sort_new"], ["old", "sort_old"]];
  $("#sorts").innerHTML = sorts.map(([id, k]) => `<button class="chip ${S.sort === id ? "is-on" : ""}" data-sort="${id}" type="button">${t(k)}</button>`).join("");
  const f = S.filters; $("#filter-dot").hidden = !(f.pmin || f.pmax || f.premium || f.nopass || f.fresh || f.origin);
}
async function loadLots() {
  const f = S.filters, p = new URLSearchParams({ country: S.country, sort: S.sort });
  if (f.pmin) p.set("pmin", f.pmin); if (f.pmax) p.set("pmax", f.pmax);
  if (f.premium) p.set("premium", "1"); if (f.nopass) p.set("nopass", "1"); if (f.fresh) p.set("fresh", "1"); if (f.origin) p.set("origin", f.origin);
  const c3 = S.country;
  try {
    const r = await api("/api/lots?" + p);
    if (S.country !== c3) return;
    S.lots = r.items; S.page.l = 0; renderLots();
  } catch (e) { $("#lots").innerHTML = `<div class="empty">${ic("info")}${errText(e)}</div>`; }
}
function lotBadges(l) {
  const b = [];
  if (l.premium) b.push(`<span class="badge ink">${ic("crown")}Premium</span>`);
  if (l.password) b.push(`<span class="badge">${ic("lock")}2FA</span>`);
  if (l.session_days) b.push(`<span class="badge">${ic("clock")}${t("session", { n: l.session_days })}</span>`);
  if (l.stars) b.push(`<span class="badge">${ic("star")}${l.stars}</span>`);
  if (l.gifts) b.push(`<span class="badge">${ic("gift")}${l.gifts}</span>`);
  if (l.published > Date.now() / 1000 - 86400) b.push(`<span class="badge ok">${ic("sparkles")}${t("cat_fresh")}</span>`);
  return b.join("");
}
function renderLots() {
  const items = S.lots || [];
  $("#lots").innerHTML = items.length ? slice(items, "l").map((l) => `
    <button class="row lot" type="button" data-lot="${l.id}">
      <span class="row-ic">${flag(l.country)}</span>
      <span class="row-t"><span class="num">${mask(l.country, l.id)}</span><span class="badges">${lotBadges(l)}</span></span>
      <span class="row-price"><b>${money(l.price)}</b>${l.old ? `<small><s>${money(l.old)}</s></small>` : ""}${inCart(l.id) ? `<small>${ic("cart")}</small>` : ""}</span>
    </button>`).join("") : `<div class="empty">${ic("search")}${t("empty_lots")}</div>`;
  pager($("#l-pager"), "l", items.length);
}
function filterSheet() {
  const f = { ...S.filters };
  const origins = [["", "origin_any"], ["autoreg", "origin_autoreg"], ["personal", "origin_personal"], ["self_registration", "origin_self"], ["resale", "origin_resale"]];
  const el = sheet(`
    <h2>${t("filters")}</h2>
    <div class="f-group"><small>${t("price")}</small><div class="f-range">
      <input id="f-pmin" type="number" inputmode="numeric" placeholder="${t("price_from")}" value="${esc(f.pmin)}">
      <input id="f-pmax" type="number" inputmode="numeric" placeholder="${t("price_to")}" value="${esc(f.pmax)}"></div></div>
    <div class="toggle ${f.premium ? "is-on" : ""}" data-tg="premium"><span>${t("premium")}</span><i></i></div>
    <div class="toggle ${f.nopass ? "is-on" : ""}" data-tg="nopass"><span>${t("no2fa")}</span><i></i></div>
    <div class="toggle ${f.fresh ? "is-on" : ""}" data-tg="fresh"><span>${t("fresh_only")}</span><i></i></div>
    <div class="f-group"><small>${t("origin")}</small><div class="chips">${origins.map(([v, k]) => `<button class="chip ${f.origin === v ? "is-on" : ""}" data-or="${v}" type="button">${t(k)}</button>`).join("")}</div></div>
    <div class="grid2"><button class="btn btn-soft" id="f-reset" type="button">${t("reset")}</button><button class="btn btn-ink" id="f-apply" type="button">${t("apply")}</button></div>`);
  el.onclick = (e) => {
    const tgl = e.target.closest("[data-tg]"); if (tgl) { f[tgl.dataset.tg] = !f[tgl.dataset.tg]; tgl.classList.toggle("is-on"); haptic(); }
    const or = e.target.closest("[data-or]"); if (or) { f.origin = or.dataset.or; $$("[data-or]", el).forEach((b) => b.classList.toggle("is-on", b === or)); }
    if (e.target.closest("#f-reset")) { S.filters = { pmin: "", pmax: "", premium: false, nopass: false, fresh: false, origin: "" }; closeSheet(); renderSorts(); loadLots(); }
    if (e.target.closest("#f-apply")) { f.pmin = $("#f-pmin").value; f.pmax = $("#f-pmax").value; S.filters = f; closeSheet(); renderSorts(); loadLots(); }
  };
}

// ── лот, похожие и покупка ──────────────────────────────────────────
function allLots() { return [...(S.lots || []), ...((S.home && S.home.fresh) || []), ...(S.similarPool || [])]; }
function findLot(id) { return allLots().find((l) => l.id === id); }
function similarTo(l) {
  const pool = allLots().filter((x, i, a) => x.id !== l.id && x.country === l.country && a.findIndex((y) => y.id === x.id) === i);
  return pool.sort((a, b) => Math.abs(a.price - l.price) - Math.abs(b.price - l.price)).slice(0, 8);
}
async function ensureSimilar(l) {
  if (similarTo(l).length >= 3 || S.country === l.country) return;
  try { const r = await api("/api/lots?country=" + l.country); S.similarPool = r.items; } catch {}
}
function lotSheet(id) {
  const l = findLot(id); if (!l) return;
  haptic();
  const enough = S.me.balance >= l.price;
  const cell = (k, v) => `<div class="cell"><small>${k}</small><b>${v}</b></div>`;
  const seen = l.last_seen ? (Date.now() / 1000 - l.last_seen < 86400 ? t("seen_recent") : t("seen", { n: Math.round((Date.now() / 1000 - l.last_seen) / 86400) })) : "—";
  const sim = similarTo(l);
  const el = sheet(`
    <h2>${flag(l.country)} ${esc(cn(l.country))}</h2>
    <div class="sub">${t("account")} · <span style="direction:ltr;unicode-bidi:isolate">${mask(l.country, l.id)}</span></div>
    <div class="badges">${lotBadges(l)}</div>
    <div class="grid2">
      ${cell(t("session_l"), l.session_days ? t("session", { n: l.session_days }) : "—")}
      ${cell(t("online"), seen)}
      ${cell(t("origin"), t({ autoreg: "origin_autoreg", personal: "origin_personal", self_registration: "origin_self", resale: "origin_resale" }[l.origin] || "origin_any"))}
      ${cell(t("twofa"), l.password ? ic("check") : "—")}
      ${cell(t("channels"), l.channels || 0)}
      ${cell(t("contacts"), l.contacts || 0)}
      ${l.stars ? cell(t("stars"), l.stars) : ""}${l.gifts ? cell(t("gifts"), l.gifts) : ""}
    </div>
    <div class="note" style="text-align:start;margin:-4px 0 12px">${ic("shield")} ${t("checked_note")}</div>
    <div class="sheet-acts">
      <button class="btn btn-soft ${inCart(l.id) ? "is-on" : ""}" id="to-cart" type="button" aria-label="${t("add_cart")}">${ic("cart")}</button>
      ${enough ? `<button class="btn btn-ink" id="buy" type="button">${ic("bolt")}${t("buy_for", { p: money(l.price) })}</button>`
               : `<button class="btn btn-ink" id="need" type="button">${ic("plus")}${t("topup_btn")}</button>`}
    </div>
    ${enough ? "" : `<div class="note">${t("no_money", { p: money(l.price - S.me.balance) })}</div>`}
    ${sim.length ? `<div class="similar"><h3>${ic("sparkles")}${t("similar")}</h3><div class="hscroll">${sim.map(miniCard).join("")}</div></div>` : ""}`);
  if (sim.length < 3) ensureSimilar(l).then(() => { if (!$("#sheet-wrap").hidden && $("#to-cart") && similarTo(l).length > sim.length) lotSheet(id); });
  el.onclick = async (e) => {
    const other = e.target.closest("[data-lot]"); if (other) return lotSheet(+other.dataset.lot);
    if (e.target.closest("#to-cart")) { toggleCart(l); e.target.closest("#to-cart").classList.toggle("is-on", inCart(l.id)); toast(inCart(l.id) ? t("in_cart") : t("removed")); if (S.screen === "country") renderLots(); return; }
    if (e.target.closest("#need")) { closeSheet(); S.amount = Math.max(S.me.topup_min, Math.ceil((l.price - S.me.balance) / 100)); return topupSheet(); }
    const b = e.target.closest("#buy"); if (!b) return;
    if (!S.me.terms_ok) return needTerms(() => lotSheet(l.id));
    b.disabled = true;
    try {
      const r = await api("/api/buy", { item_id: l.id, price: l.price });
      setBalance(r.balance); notifyH("success");
      S.cart = S.cart.filter((x) => x.id !== l.id); saveCart();
      orderSheet(r.order);
      S.lots = (S.lots || []).filter((x) => x.id !== l.id); if (S.screen === "country") renderLots();
    } catch (err) {
      b.disabled = false; notifyH("error"); toast(errText(err));
      if (err.message === "gone") { closeSheet(); S.lots = (S.lots || []).filter((x) => x.id !== l.id); renderLots(); }
      if (err.message === "price_changed") { l.price = err.data.price; lotSheet(l.id); }
    }
  };
}
async function buyInstant(c3) {
  if (!S.me.terms_ok) return needTerms(() => buyInstant(c3));
  haptic("medium");
  sheet(`<div style="text-align:center"><div class="loader"></div><h2>${t("checking")}</h2></div>`);
  try {
    const r = await api("/api/buy", { instant: c3 });
    setBalance(r.balance); notifyH("success"); orderSheet(r.order); loadHome();
  } catch (e) {
    closeSheet(); notifyH("error"); toast(errText(e));
    if (e.message === "no_money") { S.amount = Math.max(S.me.topup_min, Math.ceil((e.data.need - S.me.balance) / 100)); topupSheet(); }
  }
}
function orderSheet(o) {
  clearTimeout(S.poll.order);
  if (o.status === "pending") {
    sheet(`<div style="text-align:center"><div class="loader"></div><h2>${t("buying")}</h2><div class="sub">${t("buying_sub")}</div></div>`);
    const tick = async () => {
      try {
        const r = await api("/api/order/" + o.id);
        if (r.order.status !== "pending") { setBalance(r.balance); if (!$("#sheet-wrap").hidden) orderSheet(r.order); if (S.tab === "orders") loadOrders(); notifyH(r.order.status === "done" ? "success" : "error"); return; }
      } catch {}
      S.poll.order = setTimeout(tick, 2000);
    };
    S.poll.order = setTimeout(tick, 1500);
    return;
  }
  if (o.status === "refunded") {
    sheet(`<div class="empty">${ic("refund")}<h2>${t("st_refunded")}</h2><div>${t("refunded")}</div></div>`);
    return;
  }
  const el = sheet(`
    <h2>${ic("check")} ${t("done_title")}</h2>
    <div class="sub">${flag(o.country)} ${esc(cn(o.country))} · #${o.id}${o.source === "giveaway" ? " · " + t("src_giveaway") : o.source === "ref" ? " · " + t("src_ref") : ""}</div>
    <small class="note" style="text-align:start;display:block">${t("phone")}</small>
    <div class="big-num"><b>${esc(o.phone || "—")}</b><button class="copy" type="button" data-copy="${esc(o.phone)}">${ic("copy")}</button></div>
    ${o.password ? `<small class="note" style="text-align:start;display:block">${t("password")}</small><div class="big-num"><b>${esc(o.password)}</b><button class="copy" type="button" data-copy="${esc(o.password)}">${ic("copy")}</button></div>` : ""}
    <div class="code-box" id="code-box"><small>${t("code_hint")}</small></div>
    <button class="btn btn-ink btn-wide" id="get-code" type="button">${ic("key")}${t("get_code")}</button>
    ${o.can_report ? `<button class="btn btn-soft btn-wide" id="report" type="button" style="margin-top:8px">${ic("shield")}${t("report")}</button>
      <div class="note">${t("report_note", { h: o.guarantee_h })}</div>` : ""}`);
  el.onclick = async (e) => {
    const c = e.target.closest("[data-copy]"); if (c) return copy(c.dataset.copy);
    const rep = e.target.closest("#report");
    if (rep) {
      rep.disabled = true; rep.innerHTML = ic("clock") + t("checking");
      try {
        const r = await api("/api/report", { order: o.id });
        if (r.result === "refunded") { setBalance(r.balance); notifyH("success"); sheet(`<div class="empty">${ic("refund")}<h2>${t("st_refunded")}</h2><div>${t("report_ok")}</div></div>`); }
        else { toast(t(r.result === "valid" ? "report_valid" : "report_unknown")); rep.disabled = false; rep.innerHTML = ic("shield") + t("report"); }
      } catch (err) { toast(errText(err)); rep.disabled = false; rep.innerHTML = ic("shield") + t("report"); }
      return;
    }
    const b = e.target.closest("#get-code"); if (!b) return;
    b.disabled = true;
    try {
      const r = await api("/api/code", { order: o.id });
      $("#code-box").innerHTML = `<b>${esc(r.code)}</b><small>${r.date ? ago(r.date) : ""}</small>`;
      $("#code-box").onclick = () => copy(r.code); notifyH("success");
    } catch (err) { toast(errText(err)); }
    setTimeout(() => (b.disabled = false), 5000);
  };
}

// ── покупки ─────────────────────────────────────────────────────────
async function loadOrders() {
  if (!S.orders.length) $("#orders").innerHTML = '<div class="skel"></div>'.repeat(3);
  try { S.orders = (await api("/api/orders")).items; } catch (e) { $("#orders").innerHTML = `<div class="empty">${errText(e)}</div>`; return; }
  renderOrders();
}
function renderOrders() {
  const items = S.orders;
  $("#orders").innerHTML = items.length ? slice(items, "o").map((o) => {
    const st = { pending: ["", "st_pending"], done: ["ok", "st_done"], refunded: ["bad", "st_refunded"] }[o.status] || ["", o.status];
    return `<button class="row" type="button" data-order="${o.id}">
      <span class="row-ic">${flag(o.country)}</span>
      <span class="row-t"><b class="num" style="direction:ltr">${esc(o.phone || mask(o.country, o.id))}</b>
        <small>#${o.id} · ${new Date(o.created * 1000).toLocaleDateString(S.lang)}${o.source === "giveaway" ? " · " + t("src_giveaway") : o.source === "ref" ? " · " + t("src_ref") : ""}</small></span>
      <span class="row-price"><span class="badge ${st[0]}">${t(st[1])}</span><small>${o.price ? money(o.price) : ic("gift")}</small></span>
    </button>`;
  }).join("") : `<div class="empty">${ic("bag")}${t("orders_empty")}<button class="btn btn-ink" type="button" data-tab-go="market">${ic("home")}${t("tab_market")}</button></div>`;
  pager($("#o-pager"), "o", items.length);
}

// ── конкурс ─────────────────────────────────────────────────────────
async function loadGw() {
  let g, rf;
  try { [g, rf] = await Promise.all([api("/api/giveaway"), api("/api/ref")]); } catch (e) { $("#gw").innerHTML = `<div class="empty">${errText(e)}</div>`; return; }
  S.gwData = g; S.ref = rf;
  const h = new Date(g.draw_at * 1000).toLocaleTimeString("ru-RU", { hour: "2-digit", timeZone: "Europe/Moscow" }).slice(0, 2);
  $("#gw").innerHTML = `
    <div class="gw-card">
      <div class="gift">${ic("gift")}</div>
      <h2>${t("gw_head")}</h2>
      <p>${t("gw_text", { h })}</p>
      <div class="timer" id="timer"></div>
      <small style="color:var(--hero-hint)">${t("gw_count", { n: g.count })}</small>
      ${!g.on ? `<button class="btn" disabled type="button">${t("gw_off")}</button>` : g.joined ? `<button class="btn" disabled type="button">${ic("check")}${t("gw_joined")}</button>` : `<button class="btn" id="gw-join" type="button">${ic("ticket")}${t("gw_join")}</button>`}
    </div>
    <div class="gw-steps">
      ${g.channel ? `<button class="row" type="button" id="gw-ch"><span class="row-ic">${ic("megaphone")}</span><span class="row-t"><b>${t("gw_sub")}</b></span><span class="row-go">${ic("external")}</span></button>` : ""}
    </div>
    ${g.winners.length ? `<div class="sec"><div class="sec-h"><h3>${ic("trophy")}${t("gw_winners")}</h3></div><div class="list">${g.winners.map((w) => `
      <div class="row"><span class="row-ic">${ic(w.status === "done" ? "trophy" : "clock")}</span><span class="row-t"><b>${esc(w.status === "done" ? w.name : t("gw_skipped"))}</b><small>${esc(w.day)}</small></span></div>`).join("")}</div></div>` : ""}
    ${refCard(rf)}`;
  tickTimer();
}
function refCard(r) {
  const pct = Math.round((r.progress / r.goal) * 100);
  return `<div class="sec"><div class="sec-h"><h3>${ic("users")}${t("ref_title")}</h3><small>${t("ref_claimed", { n: r.claimed })}</small></div>
    <div class="refc">
      <p>${t("ref_text", { goal: r.goal, p: money(r.prize_max * 100) })}</p>
      <div class="ref-bar"><i style="width:${pct}%"></i></div>
      <div class="ref-row"><b>${r.progress} / ${r.goal}</b><small>${t("ref_invited", { n: r.invited })}</small></div>
      <div class="big-num" style="margin:10px 0"><b style="font-size:13px;word-break:break-all">${esc(r.link)}</b><button class="copy" type="button" data-copy-ref>${ic("copy")}</button></div>
      <div class="grid2" style="margin:0">
        <button class="btn btn-soft" type="button" id="ref-share">${ic("send")}${t("ref_share")}</button>
        <button class="btn btn-ink" type="button" id="ref-claim" ${r.claimable ? "" : "disabled"}>${ic("gift")}${t("ref_claim")}</button>
      </div>
      ${r.need_channel ? `<div class="note">${t("ref_rule")}</div>` : ""}
    </div></div>`;
}
function tickTimer() {
  clearTimeout(S.poll.timer);
  const el = $("#timer"); if (!el || !S.gwData) return;
  const left = Math.max(0, S.gwData.draw_at - Date.now() / 1000);
  const p = (n) => String(Math.floor(n)).padStart(2, "0");
  el.innerHTML = [[left / 3600, "h"], [(left % 3600) / 60, "m"], [left % 60, "s"]].map(([v, k]) => `<div><b>${p(v)}</b><small>${t(k)}</small></div>`).join("");
  if (S.tab === "gw") S.poll.timer = setTimeout(tickTimer, 1000);
}

// ── кошелёк: пополнить, отправить, промокод ─────────────────────────
function renderWallet() {
  $("#w-id").textContent = "ID " + S.me.id;
  $("#hist-sub").textContent = "";
  api("/api/history?page=0").then((r) => { $("#hist-sub").textContent = r.total ? t("ops_n", { n: r.total }) : t("history_empty"); }).catch(() => {});
}
function topupSheet() {
  const amounts = [100, 250, 500, 1000];
  const logo = (f) => `<img class="pay-logo" src="static/pay/${f}.jpg" alt="" draggable="false">`;
  const sym = { cryptobot: logo("send"), xrocket: logo("xrocket"), ton: logo("tonkeeper"), stars: starIc() };
  const render = () => {
    const stars = Math.max(1, Math.ceil(S.amount / S.me.star_rub * S.me.stars_markup));
    return `<h2>${t("topup")}</h2><div class="sub">${t("balance")}: ${money(S.me.balance)}</div>
      <div class="amounts">${amounts.map((a) => `<button type="button" data-amount="${a}" class="${S.amount === a ? "is-on" : ""}">${a} ₽</button>`).join("")}</div>
      <label class="amount-in"><input id="amount" type="number" inputmode="decimal" min="1" value="${S.amount}"><span>₽</span></label>
      <div class="list" id="methods">${S.me.methods.length ? S.me.methods.map((x) => `
        <button class="row" type="button" data-pay="${x.id}">
          <span class="row-ic pay-ic ${x.id === "stars" ? "pay-stars" : ""}">${sym[x.id] || ic("card")}</span>
          <span class="row-t"><b>${esc(x.title)}</b><small>${x.id === "stars" ? starsNote(stars) : x.id === "ton" ? "Tonkeeper · TON" : "USDT · TON · BTC"}</small></span>
          <span class="row-go">${ic("chevron")}</span></button>`).join("") : `<div class="empty">${t("err")}</div>`}</div>`;
  };
  const el = sheet(render());
  el.onclick = (e) => {
    const a = e.target.closest("[data-amount]");
    if (a) { S.amount = +a.dataset.amount; el.innerHTML = render(); paintIcons(el); return; }
    const p = e.target.closest("[data-pay]"); if (p) pay(p.dataset.pay);
  };
  el.oninput = (e) => {
    if (e.target.id !== "amount") return;
    S.amount = Math.max(0, +e.target.value || 0);
    $$("[data-amount]", el).forEach((b) => b.classList.toggle("is-on", +b.dataset.amount === S.amount));
    const stars = Math.max(1, Math.ceil(S.amount / S.me.star_rub * S.me.stars_markup));
    const st = $('[data-pay="stars"] small', el); if (st) st.innerHTML = starsNote(stars);
  };
}
function sendSheet() {
  const el = sheet(`<h2>${t("send")}</h2><div class="sub">${t("send_sub")}</div>
    <input class="field" id="s-to" placeholder="${t("send_ph")}" autocomplete="off">
    <label class="amount-in"><input id="s-amt" type="number" inputmode="decimal" placeholder="${t("amount")}"><span>₽</span></label>
    <button class="btn btn-ink btn-wide" id="s-go" type="button">${ic("send")}${t("send")}</button>
    <div class="note">${t("balance")}: ${money(S.me.balance)}</div>`);
  el.onclick = async (e) => {
    const b = e.target.closest("#s-go"); if (!b) return;
    const to = $("#s-to").value.trim(), rub = +$("#s-amt").value;
    if (!to || !rub) return toast(t("send_fill"));
    b.disabled = true;
    try {
      const r = await api("/api/transfer", { to, rub });
      setBalance(r.balance); notifyH("success"); toast(t("send_ok", { p: money(rub * 100), name: r.to })); closeSheet(); loadHistory();
    } catch (err) { b.disabled = false; notifyH("error"); toast(errText(err)); }
  };
}
function promoSheet() {
  const el = sheet(`<h2>${t("promo")}</h2><div class="sub">${t("promo_sub")}</div>
    <input class="field" id="p-code" placeholder="${t("promo_ph")}" autocomplete="off" style="text-transform:uppercase">
    <button class="btn btn-ink btn-wide" id="p-go" type="button">${ic("ticket")}${t("activate")}</button>`);
  el.onclick = async (e) => {
    const b = e.target.closest("#p-go"); if (!b) return;
    const code = $("#p-code").value.trim(); if (!code) return;
    b.disabled = true;
    try {
      const r = await api("/api/promo", { code });
      setBalance(r.balance); notifyH("success"); toast(t("promo_ok", { p: money(r.amount) })); closeSheet(); loadHistory();
    } catch (err) { b.disabled = false; notifyH("error"); toast(errText(err)); }
  };
}
async function loadHistory() { if (S.tab === "wallet") renderWallet(); }
async function historySheet(page = 0) {
  let r; try { r = await api("/api/history?page=" + page); } catch (e) { return toast(errText(e)); }
  const k = { topup: ["plus", "hist_topup"], buy: ["cart", "hist_buy"], refund: ["refund", "hist_refund"], admin: ["info", "hist_admin"],
              send: ["send", "hist_send"], receive: ["gift", "hist_receive"], promo: ["ticket", "hist_promo"] };
  const pages = Math.max(1, Math.ceil(r.total / r.per));
  const el = sheet(`<h2>${t("history")}</h2><div class="sub">${t("ops_n", { n: r.total })}</div>
    <div class="list">${r.items.length ? r.items.map((h) => `
      <div class="row"><span class="row-ic">${ic((k[h.reason] || ["info"])[0])}</span>
        <span class="row-t"><b>${t((k[h.reason] || ["", "hist_admin"])[1])}</b><small>${new Date(h.created_at * 1000).toLocaleString(S.lang, { dateStyle: "short", timeStyle: "short" })}</small></span>
        <span class="row-price"><b class="${h.delta > 0 ? "hist-plus" : ""}">${h.delta > 0 ? "+" : "−"}${money(Math.abs(h.delta))}</b></span></div>`).join("")
      : `<div class="empty">${ic("history")}${t("history_empty")}</div>`}</div>
    ${pages > 1 ? `<div class="pager">
      <button type="button" data-hp="${page - 1}" ${page === 0 ? "disabled" : ""}>${ic("back")}</button>
      <span>${page + 1} / ${pages}</span>
      <button type="button" data-hp="${page + 1}" ${page >= pages - 1 ? "disabled" : ""}>${ic("chevron")}</button></div>` : ""}`);
  el.onclick = (e) => { const b = e.target.closest("[data-hp]"); if (b && !b.disabled) { haptic(); historySheet(+b.dataset.hp); } };
}
function renderHistory() {
  const k = { topup: ["plus", "hist_topup"], buy: ["cart", "hist_buy"], refund: ["refund", "hist_refund"], admin: ["info", "hist_admin"],
              send: ["send", "hist_send"], receive: ["gift", "hist_receive"], promo: ["ticket", "hist_promo"] };
  $("#history").innerHTML = S.hist.length ? slice(S.hist, "h").map((h) => `
    <div class="row"><span class="row-ic">${ic((k[h.reason] || ["info"])[0])}</span>
      <span class="row-t"><b>${t((k[h.reason] || ["", "hist_admin"])[1])}</b><small>${new Date(h.created_at * 1000).toLocaleString(S.lang, { dateStyle: "short", timeStyle: "short" })}</small></span>
      <span class="row-price"><b class="${h.delta > 0 ? "hist-plus" : ""}">${h.delta > 0 ? "+" : "−"}${money(Math.abs(h.delta))}</b></span></div>`).join("")
    : `<div class="empty">${ic("history")}${t("history_empty")}</div>`;
  pager($("#h-pager"), "h", S.hist.length);
}
async function pay(provider) {
  const rub = +($("#amount") && $("#amount").value) || S.amount;
  if (rub < S.me.topup_min) return toast(t("min_amount", { p: money(S.me.topup_min * 100) }));
  haptic("medium");
  let inv;
  try { inv = await api("/api/topup", { provider, rub }); } catch (e) { return toast(errText(e)); }
  if (provider === "stars" && tg && tg.openInvoice) {
    tg.openInvoice(inv.pay_url, (status) => { if (status === "paid") watchInvoice(inv.invoice_id, true); });
    return;
  }
  sheet(`<div style="text-align:center"><div class="loader"></div><h2>${t("pay_wait")}</h2>
    <div class="sub">${esc(inv.title)} · ${inv.amount} ${esc(inv.asset)}</div>
    ${provider === "ton" ? `<div class="big-num"><b style="font-size:14px;word-break:break-all">${esc(inv.wallet)}</b><button class="copy" type="button" data-copy="${esc(inv.wallet)}">${ic("copy")}</button></div><div class="note">${t("ton_hint", { a: inv.amount, c: inv.comment })}</div>` : ""}
    <button class="btn btn-ink btn-wide" type="button" id="pay-open">${ic("external")}${esc(inv.title)}</button></div>`)
    .onclick = (e) => { const c = e.target.closest("[data-copy]"); if (c) copy(c.dataset.copy); if (e.target.closest("#pay-open")) openLink(inv.pay_url); };
  openLink(inv.pay_url);
  watchInvoice(inv.invoice_id);
}
function watchInvoice(id, fast) {
  let n = 0;
  const tick = async () => {
    n++;
    try {
      const r = await api("/api/invoice/" + id);
      if (r.status === "paid") { setBalance(r.balance); notifyH("success"); toast(t("pay_ok")); if (!$("#sheet-wrap").hidden) closeSheet(); loadHistory(); return; }
      if (r.status === "expired") return;
    } catch {}
    if (n < 120) S.poll["inv" + id] = setTimeout(tick, fast ? 1500 : 5000);
  };
  tick();
}

// ── условия и политика ──────────────────────────────────────────────
async function legalSheet(kind) {
  const lang = S.lang === "ru" ? "ru" : "en";
  let html = "";
  try { html = await (await fetch(`static/legal/${kind}.${lang}.html?v=1`)).text(); } catch { return toast(t("err")); }
  sheet(`<div class="legal">${html}</div>`);
}
// Без принятых условий покупок нет — сервер проверяет это сам, здесь только окно.
function needTerms(then) {
  if (S.me.terms_ok) return then();
  const el = sheet(`<div class="accept">
      <div class="accept-ic">${ic("shield")}</div>
      <h2>${t("accept_title")}</h2>
      <p>${t("accept_text", { n: S.me.max_per_day })}</p>
      <div class="list" style="margin:14px 0">
        <button class="row" type="button" data-legal-in="terms"><span class="row-ic">${ic("book")}</span><span class="row-t"><b>${t("terms")}</b></span><span class="row-go">${ic("chevron")}</span></button>
        <button class="row" type="button" data-legal-in="privacy"><span class="row-ic">${ic("shield")}</span><span class="row-t"><b>${t("privacy")}</b></span><span class="row-go">${ic("chevron")}</span></button>
      </div>
      <button class="btn btn-ink btn-wide" id="accept" type="button">${ic("check")}${t("accept_btn")}</button></div>`);
  el.onclick = async (e) => {
    const l = e.target.closest("[data-legal-in]"); if (l) return legalSheet(l.dataset.legalIn);
    if (!e.target.closest("#accept")) return;
    try { await api("/api/accept", {}); } catch (err) { return toast(errText(err)); }
    S.me.terms_ok = true; notifyH("success"); closeSheet(); then();
  };
}

// ── обязательная подписка на канал ──────────────────────────────────
function subGate(after) {
  let el = $("#subgate");
  if (!el) {
    el = document.createElement("div"); el.id = "subgate"; el.className = "subgate";
    document.body.append(el);
  }
  el.hidden = false;
  el.innerHTML = `<div class="subgate-in">
      <div class="accept-ic">${ic("megaphone")}</div>
      <h2>${t("sub_title")}</h2>
      <p>${t("sub_text", { ch: esc(S.me.channel_name || "") })}</p>
      <button class="btn btn-ink btn-wide" id="sub-go" type="button">${ic("external")}${t("sub_btn")}</button>
      <button class="btn btn-soft btn-wide" id="sub-check" type="button" style="margin-top:8px">${ic("check")}${t("sub_check")}</button>
    </div>`;
  $("#sub-go").onclick = () => openLink(S.me.channel);
  $("#sub-check").onclick = async () => {
    try {
      const r = await api("/api/sub", {});
      if (r.need_sub) { notifyH("error"); return toast(t("sub_fail")); }
    } catch { return toast(t("err")); }
    notifyH("success"); el.hidden = true; S.me.need_sub = false;
    if (after) after(); else if (!S.me.tour_done) tour(0); else { $("#app").hidden = false; openTab(S.tab); }
  };
}

// ── вкладки ─────────────────────────────────────────────────────────
function openTab(tab) {
  S.tab = tab; show(tab); haptic();
  if (tab === "market") loadHome();
  if (tab === "orders") { S.page.o = 0; loadOrders(); }
  if (tab === "gw") loadGw();
  if (tab === "wallet") renderWallet();
}

// ── язык ────────────────────────────────────────────────────────────
function langSheet(after) {
  const el = sheet(`<h2>${t("language")}</h2><div class="sub"></div><div class="langs">${Object.entries(LANGS).map(([k, v]) => `<button type="button" data-lang="${k}" class="${S.lang === k ? "is-on" : ""}">${v}</button>`).join("")}</div>`);
  el.onclick = async (e) => {
    const b = e.target.closest("[data-lang]"); if (!b) return;
    S.lang = b.dataset.lang; applyI18n(); closeSheet(); haptic();
    api("/api/lang", { lang: S.lang }).catch(() => {});
    after ? after() : openTab(S.tab);
  };
}

// ── обучение ────────────────────────────────────────────────────────
const TOUR = [
  { core: "lang", sats: ["fl:GB", "fl:RU", "fl:ES", "fl:CN"] },
  { core: "wallet", sats: ["card", "gem", "star", "coin"] },
  { core: "globe", sats: ["fl:US", "fl:IN", "fl:DE", "fl:BR"] },
  { core: "cart", sats: ["bolt", "check", "sparkles", "phone"] },
  { core: "key", sats: ["phone", "lock", "shield", "copy"] },
];
function tour(step = 0) {
  $("#tour").hidden = false; $("#app").hidden = true;
  const s = TOUR[step], pos = [[-8, 18], [78, 4], [86, 72], [2, 80]];
  $("#tour-stage").innerHTML = `<div class="tour-art"><div class="ring"></div><div class="disc"></div>
    ${s.sats.map((x, i) => `<div class="sat" style="left:${pos[i][0]}%;top:${pos[i][1]}%">${x.startsWith("fl:") ? flagImg(x.slice(3)) : ic(x)}</div>`).join("")}
    <div class="core">${ic(s.core)}</div></div>`;
  $("#tour-step").textContent = t("step", { n: step + 1, m: TOUR.length });
  $("#tour-title").textContent = t("tour" + step + "_t");
  $("#tour-text").textContent = t("tour" + step + "_x");
  $("#tour-dots").innerHTML = TOUR.map((_, i) => `<i class="${i === step ? "is-on" : ""}"></i>`).join("");
  $("#tour-next").textContent = step === TOUR.length - 1 ? t("start") : t("next");
  $("#tour-lang").innerHTML = ic("lang") + LANGS[S.lang];
  $("#tour-lang").hidden = step !== 0;
  $("#tour-skip").textContent = t("skip");
  $("#tour-next").onclick = () => { haptic(); step < TOUR.length - 1 ? tour(step + 1) : endTour(); };
  $("#tour-skip").onclick = endTour;
  $("#tour-lang").onclick = () => langSheet(() => tour(0));
}
function endTour() {
  $("#tour").hidden = true; $("#app").hidden = false;
  api("/api/tour", {}).catch(() => {}); S.me.tour_done = true; applyI18n(); openTab(S.tab);
}

// ── события ─────────────────────────────────────────────────────────
function bind() {
  document.addEventListener("click", (e) => {
    const el = (s) => e.target.closest(s);
    let x;
    if ((x = el("[data-tab]"))) return openTab(x.dataset.tab);
    if ((x = el("[data-tab-go]"))) return openTab(x.dataset.tabGo);
    if (el("#sheet-wrap")) return;  // внутри шторки — свои обработчики
    if ((x = el("[data-page]"))) {
      const [key, n] = x.dataset.page.split(":"); S.page[key] = +n; haptic();
      ({ c: renderCountries, l: renderLots, o: renderOrders, h: renderHistory })[key]();
      const anchor = { c: "#regions", l: "#sorts", o: ".h1", h: "#history" }[key];
      const a = $(anchor, $(".screen.is-on")) || $(anchor); if (a) window.scrollTo({ top: a.getBoundingClientRect().top + scrollY - 80, behavior: "smooth" });
      return;
    }
    if ((x = el("[data-scroll]"))) { const [id, d] = x.dataset.scroll.split(":"); const box = $("#" + id); box.scrollBy({ left: (+d) * box.clientWidth * .8 * (document.body.dir === "rtl" ? -1 : 1), behavior: "smooth" }); return; }
    if ((x = el("[data-cat]"))) { S.cat = x.dataset.cat; S.page.c = 0; haptic(); renderHome(); return; }
    if ((x = el("[data-region]"))) { S.region = x.dataset.region; S.page.c = 0; haptic(); renderCats(); renderCountries(); return; }
    if ((x = el("[data-csort]"))) { S.csort = x.dataset.csort; S.page.c = 0; haptic(); renderCats(); renderCountries(); return; }
    if ((x = el("[data-sort]"))) { S.sort = x.dataset.sort; haptic(); renderSorts(); loadLots(); return; }
    if ((x = el("[data-instant]"))) return buyInstant(x.dataset.instant);
    if ((x = el("[data-lot]"))) return lotSheet(+x.dataset.lot);
    if ((x = el("[data-country]"))) { haptic(); return openCountry(x.dataset.country); }
    if ((x = el("[data-order]"))) { const o = S.orders.find((y) => y.id === +x.dataset.order); return o && orderSheet(o); }
    if (el("#filter-btn")) return filterSheet();
    if (el("#cart-btn")) return cartSheet();
    if (el("#bal") || el("#act-topup")) return topupSheet();
    if (el("#act-send")) return sendSheet();
    if (el("#act-promo")) return promoSheet();
    if (el("#set-lang")) return langSheet();
    if (el("#set-tour")) return tour(0);
    if (el("#open-history")) return historySheet(0);
    if ((x = el("[data-legal]"))) return legalSheet(x.dataset.legal);
    if (el("#set-support")) return openLink(S.me.support ? "https://t.me/" + S.me.support : "");
    if (el("#gw-ch")) return openLink(S.gwData.channel);
    if (el("[data-copy-ref]")) return copy(S.ref.link);
    if (el("#ref-share")) return openLink(`https://t.me/share/url?url=${encodeURIComponent(S.ref.link)}&text=${encodeURIComponent(t("share_text"))}`);
    if ((x = el("#ref-claim"))) {
      x.disabled = true;
      api("/api/ref/claim", {}).then((r) => { notifyH("success"); orderSheet(r.order); loadGw(); })
        .catch((err) => { x.disabled = false; notifyH("error"); toast(err.message === "ref_not_enough" ? t("ref_not_enough", { n: err.data.need }) : errText(err)); });
      return;
    }
    if (el("#gw-join")) {
      api("/api/giveaway/join", {}).then(() => { notifyH("success"); loadGw(); }).catch((err) => {
        toast(errText(err)); if (err.message === "not_subscribed" && S.gwData.channel) openLink(S.gwData.channel);
      });
    }
  });
  $("#sheet-bg").onclick = closeSheet;
  $("#q").addEventListener("input", (e) => { S.q = e.target.value; S.page.c = 0; renderCountries(); });
  if (tg) tg.BackButton.onClick(goBack);
}

// ── старт ───────────────────────────────────────────────────────────
async function boot() {
  if (tg) { tg.ready(); tg.expand(); try { tg.disableVerticalSwipes && tg.disableVerticalSwipes(); } catch {} }
  const dark = tg ? tg.colorScheme === "dark" : (qs.get("theme") === "dark");
  document.body.classList.toggle("dark", dark);
  try { if (tg) { tg.setHeaderColor(dark ? "#0A0A0B" : "#F3F3F1"); tg.setBackgroundColor(dark ? "#0A0A0B" : "#F3F3F1"); } } catch {}
  paintIcons(); bind(); loadCart(); renderCartBadge();
  try { S.me = await api("/api/me"); }
  catch { $("#boot").innerHTML = `<div class="empty">${ic("lock")}Open this app from the Telegram bot</div>`; return; }
  S.lang = S.me.lang in I18N ? S.me.lang : "en";
  applyI18n(); setBalance(S.me.balance);
  const startTab = qs.get("tab");
  S.tab = ["orders", "gw", "wallet"].includes(startTab) ? startTab : "market";
  $("#boot").classList.add("is-out"); setTimeout(() => $("#boot").remove(), 400);
  if (S.me.need_sub) return subGate();
  if (!S.me.tour_done || qs.get("tour") === "1") tour(0);
  else { $("#app").hidden = false; openTab(S.tab); }
  setInterval(() => { if (S.tab === "market" && S.screen === "market" && $("#sheet-wrap").hidden) loadHome(); }, 45000);
}
boot();
})();
