(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = String(text);
    return node;
  };
  const money = (value) => typeof value === "number" ? `${value.toLocaleString("vi-VN")} ₫` : "—";
  const fallback = (value) => value == null || value === "" ? "—" : String(value);
  let activeView = "conversation";

  function switchView(view) {
    for (const name of ["conversation", "reference", "calls"]) {
      $(`${name}-screen`).hidden = name !== view;
      document.querySelector(`[data-view="${name}"]`).classList.toggle("nav-active", name === view);
    }
    activeView = view;
    if (view === "reference") loadReference();
    if (view === "calls") loadCalls();
  }

  function card(parent, title, meta, body) {
    const item = el("article", "data-card");
    item.append(el("strong", "", title), el("small", "", meta));
    if (body) item.append(el("p", "", body));
    parent.append(item);
  }

  async function loadReference() {
    const on = $("reference-date").value;
    const orderOn = $("order-date").value;
    if (!on) { $("reference-status").textContent = "Chọn ngày cuộc gọi."; return; }
    $("reference-status").textContent = "Đang đọc dữ liệu nguồn…";
    try {
      const query = new URLSearchParams({on});
      if (orderOn) query.set("order_on", orderOn);
      const response = await fetch(`/api/reference?${query}`, {credentials: "same-origin"});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const products = $("products-list");
      products.replaceChildren();
      for (const item of data.products) {
        const dateText = item.stock_effective_on || "tồn kho gốc";
        card(products, item.name, `${item.sku} · ${item.category} · ${item.brand}`,
          `Giá niêm yết ${money(item.list_price_vnd)} · tồn ${item.stock_on} (mốc ${dateText})`);
        for (const variant of data.variants.filter((row) => row.parent_sku === item.sku)) {
          card(products, `↳ ${variant.variant_sku}`, `${fallback(variant.size_label)} · ${fallback(variant.color)}`,
            `Chênh giá ${money(variant.price_delta_vnd)} · tồn ${variant.stock_on} (mốc ${variant.stock_effective_on || "tồn kho gốc"})`);
        }
      }
      const promos = $("promotions-list");
      promos.replaceChildren();
      for (const item of data.promotions) {
        card(promos, item.name, `${item.promo_code} · ${item.starts_on} → ${item.ends_on}`,
          `Loại ${item.promo_type} · áp dụng: ${JSON.stringify(item.applies_to)} · điều kiện: ${JSON.stringify(item.conditions)}`);
      }
      if (!data.promotions.length) promos.append(el("p", "", "Không có chương trình hiệu lực vào ngày này."));
      const policies = $("policies-list");
      policies.replaceChildren();
      for (const item of data.policies) {
        const details = el("details", "policy-card");
        details.append(el("summary", "", item.title),
          el("small", "", `${item.document_id} · ${item.date_basis} · ${item.effective_from || "không giới hạn"} → ${item.effective_until || "không giới hạn"}`),
          el("p", "", item.body));
        policies.append(details);
      }
      if (!data.policies.length) policies.append(el("p", "", "Không có đoạn chính sách công khai phù hợp ngày đã chọn."));
      $("reference-status").textContent = `${data.products.length} sản phẩm · ${data.variants.length} biến thể · ${data.promotions.length} khuyến mãi · ${data.policies.length} đoạn chính sách.`;
    } catch (error) {
      $("reference-status").textContent = `Không tải được dữ liệu: ${error.message}`;
    }
  }

  async function loadCalls() {
    $("calls-status").textContent = "Đang tải cuộc gọi…";
    try {
      const response = await fetch("/api/calls", {credentials: "same-origin"});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const {calls} = await response.json();
      const list = $("calls-list");
      list.replaceChildren();
      for (const call of calls) {
        const button = el("button", "call-card");
        button.type = "button";
        button.append(el("strong", "", call.last_customer_text || "Cuộc gọi chưa có lời khách"),
          el("small", "", `${call.call_date} · ${call.status === "open" ? "Đang mở" : "Đã đóng"} · ${call.turns} lượt · ${call.identity_status === "known" ? "CRM đã xác minh" : "Chưa xác minh CRM"}`));
        button.addEventListener("click", () => showCall(call.id));
        list.append(button);
      }
      if (!calls.length) list.append(el("p", "", "Chưa có cuộc gọi nào trên phiên truy cập này."));
      $("calls-status").textContent = `${calls.length} cuộc gọi gần đây.`;
      return calls;
    } catch (error) {
      $("calls-status").textContent = `Không tải được cuộc gọi: ${error.message}`;
      return [];
    }
  }

  async function showCall(id) {
    const detail = $("call-detail");
    detail.textContent = "Đang tải nội dung…";
    try {
      const response = await fetch(`/api/calls/${encodeURIComponent(id)}`, {credentials: "same-origin"});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const call = await response.json();
      detail.replaceChildren(el("p", "", `Mã phiên ${call.session_id} · ${call.call_date} · ${call.status === "open" ? "Đang mở" : "Đã đóng"}`));
      for (const message of call.messages) {
        const item = el("div", "call-detail-message");
        item.append(el("small", "", `${message.role === "customer" ? "Khách hàng" : "Tư vấn viên AI"} · lượt ${message.turn_no}`),
          el("div", "", message.content));
        detail.append(item);
      }
      if (!call.messages.length) detail.append(el("p", "", "Chưa có lời thoại."));
      if (call.status === "open") {
        const close = el("button", "call-close", "Đóng cuộc gọi");
        close.type = "button";
        close.addEventListener("click", async () => {
          close.disabled = true;
          const result = await fetch(`/api/calls/${encodeURIComponent(id)}/close`, {method: "POST", credentials: "same-origin"});
          if (!result.ok) { close.disabled = false; $("calls-status").textContent = `Không đóng được cuộc gọi (${result.status}).`; return; }
          await loadCalls();
          await showCall(id);
        });
        detail.append(close);
      }
    } catch (error) {
      detail.textContent = `Không tải được nội dung: ${error.message}`;
    }
  }

  async function renderPreviousSummary() {
    const calls = await loadCalls();
    const previous = calls.find((call) => call.last_customer_text);
    if (!previous) return;
    $("brief-content").textContent = `Lần trước (${previous.call_date}): ${previous.last_customer_text}\n${previous.turns} lượt trao đổi. Xem chi tiết tại Quản lý cuộc gọi.`;
  }

  document.querySelectorAll("[data-view]").forEach((button) =>
    button.addEventListener("click", () => switchView(button.dataset.view)));
  $("load-reference").addEventListener("click", loadReference);
  $("refresh-calls").addEventListener("click", loadCalls);
  window.TeleSaleWorkspace = {loadCalls, loadReference, renderPreviousSummary,
    currentView: () => activeView};
})();
