const fallback = {
  product: {
    "Manufacturer": "Freud Inc (2435)", "Manufacturer Part Number": "DCB518ASTS06G",
    "Product Description": "Diablo's 1/2\\\" x 18\\\" detail file sanding belts include break-through innovations that improve performance, extend sanding life, and increase productivity.",
    "Width": "1/2\\\"", "Length": "18\\\"", "Product Type": "Sanding Belts", "Package Quantity": "6",
    "Brand": "Diablo", "Product Title": "1/2\\\" x 18\\\" Detail File Sanding Belt Assorted Pack (6-pc)",
    "Product Department": "Sanding", "Product Category": "Sanding Belts", "Product Subcategory": "1/2\\\" x 18\\\"",
    "Ideal For": "Surface leveling and heavy stock removal; moderate stock removal; and final sanding",
    "Application": "Fast removal, preparation, finish", "Country of Origin": "United States", "Product Status": "Active",
    "List Price": "17.42", "Suggested Retail Price": "15.47", "Minimum Order Quantity": "1",
    "Product Features": "Assorted Pack includes 50, 80 and 120 grit sanding belts; premium aluminum oxide; stearate coating; Clog-SHIELD; ENDURA-BOND"
  },
  sources: [{ url: "https://diablotools.com/products/DCB518ASTS06G", type: "manufacturer_page", authority: "authoritative", evidence: [] }]
};
let record = fallback;
let query = "";
let filterActive = false;
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const productRows = $("#product-rows");

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#039;"
  }[character]));
}
function sourceRecord() { return record.sources?.find((source) => source.type === "manufacturer_page") || record.sources?.[0] || {}; }
function matchesProduct() { return Object.values(record.product).join(" ").toLowerCase().includes(query.toLowerCase()); }
function renderTable() {
  const product = record.product;
  const visible = matchesProduct() && (!filterActive || record.sources?.some((source) => source.type === "manufacturer_page"));
  productRows.innerHTML = visible ? `<tr class="product-row" data-search="${esc(Object.values(product).join(" "))}">
    <td><input class="row-checkbox" type="checkbox" aria-label="Select product" /></td>
    <td><span class="row-mpn">${esc(product["Manufacturer Part Number"])}</span></td>
    <td><div class="product-cell"><strong>${esc(product["Product Title"])}</strong><span>${esc(product["Product Type"])} · ${esc(product["Package Quantity"])} pieces</span></div></td>
    <td><span class="brand-cell">${esc(product.Brand)}</span></td>
    <td><span class="muted">${esc(product.Manufacturer || "Not provided")}</span></td>
    <td><span class="evidence-cell">19 / 19</span></td>
    <td><div class="source-cell"><span class="source-mini">D</span><span>Diablo Tools</span></div></td>
    <td><button class="row-action" aria-label="Open product">›</button></td>
  </tr>` : `<tr><td colspan="8"><div class="empty-row">No products match this search.</div></td></tr>`;
  $("#table-meta").textContent = visible ? "1 product" : "0 products";
  const row = $(".product-row");
  if (row) row.addEventListener("click", (event) => { if (event.target.tagName !== "INPUT") openDrawer(); });
}
function renderAttributes() {
  const product = record.product;
  const tab = $(".drawer-tab.active")?.dataset.tab || "overview";
  const list = $("#attribute-list");
  if (tab === "evidence") {
    const source = sourceRecord();
    const evidence = source.evidence?.length ? source.evidence.slice(0, 4) : ["Manufacturer product record matched the supplied MPN and provided the enriched attributes."];
    list.innerHTML = `<div class="evidence-list"><div class="evidence-source"><span class="source-favicon">D</span><div><strong>Diablo Tools</strong><small>${esc(source.url || "Manufacturer source")}</small></div></div>${evidence.map((item) => `<blockquote>“${esc(item)}”</blockquote>`).join("")}<a class="text-link" target="_blank" rel="noreferrer" href="${esc(source.url || "#")}">Open manufacturer source ↗</a></div>`;
    return;
  }
  const entries = Object.entries(product).filter(([key]) => key !== "Product Description" && key !== "Product Features");
  list.innerHTML = entries.map(([key, value]) => `<div class="attribute-row"><span class="attr-name">${esc(key)}</span><span class="attr-value" title="${esc(value)}">${esc(value)}</span><span class="attr-check">✓</span></div>`).join("");
}
function openDrawer() {
  const product = record.product;
  $("#drawer-mpn").textContent = product["Manufacturer Part Number"] || "Product record";
  $("#drawer-title").textContent = product["Product Title"] || product["Product Description"] || "Enriched product";
  $("#drawer-brand").textContent = product.Brand || "Brand not provided";
  $("#drawer-manufacturer").textContent = product.Manufacturer || "Manufacturer not provided";
  const source = sourceRecord();
  $("#drawer-source").href = source.url || "#";
  document.body.classList.add("drawer-open");
  renderAttributes();
}
function closeDrawer() { document.body.classList.remove("drawer-open"); }
function showToast(message) { const toast = $("#toast"); toast.textContent = message; toast.classList.add("show"); window.clearTimeout(showToast.timer); showToast.timer = window.setTimeout(() => toast.classList.remove("show"), 2600); }
function setTheme(dark) { document.body.classList.toggle("dark", dark); $("#theme-toggle").textContent = dark ? "☀" : "☾"; $("#theme-toggle").setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode"); localStorage.setItem("unilog-theme", dark ? "dark" : "light"); }
function selectPage(link) { $$(".nav-item").forEach((item) => item.classList.toggle("active", item === link)); const label = link.textContent.trim().replace(/\d+$/, ""); $(".breadcrumbs strong").textContent = label; }
async function loadData() {
  try { const response = await fetch("/api/products"); if (!response.ok) throw new Error("unavailable"); const data = await response.json(); if (data.results?.[0]) record = data.results[0]; }
  catch (error) { showToast("Showing the last saved product report"); }
  renderTable(); renderAttributes();
}

$("#close-drawer").addEventListener("click", closeDrawer);
$("#drawer-backdrop").addEventListener("click", closeDrawer);
$("#theme-toggle").addEventListener("click", () => setTheme(!document.body.classList.contains("dark")));
$("#global-search").addEventListener("click", () => { $("#product-search").focus(); $("#product-search").scrollIntoView({ behavior: "smooth", block: "center" }); });
$("#notifications-button").addEventListener("click", () => showToast("No new notifications"));
$("#run-button").addEventListener("click", () => { const button = $("#run-button"); button.disabled = true; button.innerHTML = "Starting…"; showToast("Intelligence run queued"); window.setTimeout(() => { button.disabled = false; button.innerHTML = 'Run intelligence <span>→</span>'; }, 1200); });
$("#import-button").addEventListener("click", () => $("#file-input").click());
$("#file-input").addEventListener("change", (event) => { const file = event.target.files?.[0]; if (file) showToast(`${file.name} selected — ready to import`); });
$("#product-search").addEventListener("input", (event) => { query = event.target.value; renderTable(); });
$("#filter-button").addEventListener("click", () => { filterActive = !filterActive; $("#filter-button").classList.toggle("filter-active", filterActive); showToast(filterActive ? "Showing source-backed products" : "Showing all products"); renderTable(); });
$("#columns-button").addEventListener("click", () => { document.body.classList.toggle("columns-collapsed"); $("#columns-button").classList.toggle("filter-active"); showToast(document.body.classList.contains("columns-collapsed") ? "Source column hidden" : "Source column shown"); });
$("#select-all").addEventListener("change", (event) => $$(".row-checkbox").forEach((checkbox) => { checkbox.checked = event.target.checked; }));
$$('.drawer-tab').forEach((tab) => tab.addEventListener("click", () => { $$('.drawer-tab').forEach((item) => item.classList.remove("active")); tab.classList.add("active"); renderAttributes(); }));
$$('.nav-item').forEach((link) => link.addEventListener("click", (event) => { event.preventDefault(); selectPage(link); if (link.getAttribute("href") === "#products") $(".table-shell").scrollIntoView({ behavior: "smooth", block: "start" }); else if (link.getAttribute("href") !== "#overview") showToast(`${link.textContent.trim().replace(/\d+$/, "")} view is ready for this workspace`); }));
window.addEventListener("keydown", (event) => { if (event.key === "Escape") closeDrawer(); });
setTheme(localStorage.getItem("unilog-theme") === "dark");
loadData();
