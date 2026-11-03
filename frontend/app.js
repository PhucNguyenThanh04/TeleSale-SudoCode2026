(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const speech = window.TeleSaleSpeech;
  const workspace = window.TeleSaleWorkspace;
  const visitorMode = location.hostname === "telesale.ktoxz.id.vn";
  let returningBrowser = false;
  const ui = {
    channel: $("channel"), identity: $("identity"), callDate: $("call-date"),
    authLabel: $("auth-label"), authIndicator: $("auth-indicator"),
    setup: $("setup-form"), form: $("chat-form"), input: $("message-input"),
    inputMode: $("input-mode"), send: $("send-button"), messages: $("messages"),
    empty: $("empty-state"), error: $("error-box"), newSession: $("new-session"),
    session: $("session-value"), identityStatus: $("identity-value"),
    handoff: $("handoff-value"), turnCount: $("turn-count"),
    brief: $("brief-content"), connection: $("connection-label"), serviceState: $("service-state"),
  };

  let sessionId = null;
  let turnCount = 0;
  let pendingTurn = null;
  let busy = false;
  let accessReady = false;

  function showError(message) {
    ui.error.textContent = message;
    ui.error.hidden = false;
  }

  function clearError() {
    ui.error.textContent = "";
    ui.error.hidden = true;
  }

  function setBusy(value) {
    busy = value;
    ui.send.disabled = value;
    ui.send.firstChild.textContent = value ? "Đang gửi " : "Gửi tin ";
    ui.connection.textContent = value ? "Đang xử lý" : "Sẵn sàng";
  }

  async function connectLocalSession() {
    const response = await fetch(visitorMode ? "/api/auth/visitor-session" : "/api/auth/local-session", {
      method: "POST", credentials: "same-origin",
    });
    if (!response.ok) throw new Error("Không thiết lập được phiên truy cập nội bộ.");
    accessReady = true;
    const access = await response.json();
    returningBrowser = Boolean(access.returning_browser);
    ui.authLabel.textContent = visitorMode ? "Phiên mô phỏng đã kết nối" : "Đã kết nối";
    ui.authIndicator.classList.add("active");
    if (visitorMode) {
      $("identity-help").textContent = "Mô phỏng định danh do Hotline, Fanpage hoặc Zalo chuyển vào để hệ thống tra CRM.";
      $("access-help").textContent = "Phiên mô phỏng dùng HttpOnly cookie, không dùng Bearer JWT.";
      ui.identityStatus.textContent = "Chờ định danh từ kênh";
      if (returningBrowser) workspace.renderPreviousSummary();
    }
  }

  function makeMessage(kind, text, meta) {
    ui.empty?.remove();
    ui.empty = null;
    const article = document.createElement("article");
    article.className = `message ${kind}`;
    const label = document.createElement("span");
    label.className = "message-label";
    label.textContent = kind === "customer" ? "Khách hàng" : "Tư vấn viên AI";
    const body = document.createElement("div");
    body.className = "message-body";
    body.textContent = text;
    const caption = document.createElement("span");
    caption.className = "message-meta";
    caption.textContent = meta;
    article.append(label, body, caption);
    ui.messages.append(article);
    ui.messages.scrollTop = ui.messages.scrollHeight;
    return { article, caption };
  }

  function setSetupLocked(locked) {
    for (const field of ui.setup.elements) field.disabled = locked;
  }

  function updateIdentityField() {
    const hotline = ui.channel.value === "hotline";
    const zalo = ui.channel.value === "zalo_oa";
    $("identity-label").textContent = hotline ? "Số điện thoại gọi đến"
      : zalo ? "Zalo ID từ kênh" : "Facebook ID từ kênh";
    ui.identity.placeholder = hotline ? "Ví dụ: 0984726714"
      : zalo ? "Ví dụ: zalo_hoa73" : "Ví dụ: fb.hoa.479";
    ui.identity.inputMode = hotline ? "numeric" : "text";
    if (hotline) ui.identity.setAttribute("pattern", "0[0-9]{9}");
    else ui.identity.removeAttribute("pattern");
    $("identity-note").textContent = hotline
      ? "Số phải gồm 10 chữ số và bắt đầu bằng 0."
      : "Định danh này mô phỏng metadata do nền tảng chuyển vào, không lấy từ nội dung khách nhắn.";
  }

  function renderBrief(brief) {
    if (!brief || typeof brief !== "object" || Object.keys(brief).length === 0) return;
    ui.brief.replaceChildren();
    const fields = [
      ["customer_name", "Khách hàng"], ["n_previous_sessions", "Số phiên trước"],
      ["open_blockers", "Điểm còn vướng"], ["open_questions", "Câu hỏi mở"],
      ["suggested_opening", "Gợi ý mở đầu"],
      ["suggested_next_action", "Bước tiếp theo"],
      ["stale_warnings", "Cần kiểm lại"],
    ];
    let shown = 0;
    for (const [key, label] of fields) {
      const value = brief[key];
      if (value == null || value === "" || (Array.isArray(value) && !value.length)) continue;
      const p = document.createElement("p");
      p.textContent = `${label}: ${Array.isArray(value) ? value.join(", ") : String(value)}`;
      ui.brief.append(p);
      shown += 1;
    }
    if (brief.last_session && typeof brief.last_session === "object") {
      const p = document.createElement("p");
      p.textContent = `Lần trước: ${brief.last_session.summary || brief.last_session.date || "Đã có lịch sử"}`;
      ui.brief.prepend(p);
      shown += 1;
    }
    if (!shown) ui.brief.textContent = "Đã có tóm tắt trong hệ thống; chưa có trường hiển thị phù hợp.";
  }

  function updateFolio(data) {
    sessionId = data.session_id;
    ui.session.textContent = sessionId;
    const identity = { known: "Đã xác định", unknown: "Chưa xác định", ambiguous: "Cần xác minh" };
    ui.identityStatus.textContent = identity[data.identity_status] || "Chưa xác định";
    ui.handoff.textContent = data.needs_handoff
      ? (data.handoff_ticket_id ? `Cần chuyển · ${data.handoff_ticket_id}` : "Cần chuyển")
      : "Chưa yêu cầu";
    turnCount += 1;
    ui.turnCount.textContent = String(turnCount).padStart(2, "0");
    renderBrief(data.call_brief);
    setSetupLocked(true);
  }

  function readableError(status, data) {
    if (status === 401) return "Phiên truy cập đã hết hạn. Hãy tải lại trang rồi bắt đầu cuộc gọi mới.";
    if (status === 422) return "Thông tin phiên chưa hợp lệ. Kiểm tra kênh, định danh và ngày cuộc gọi.";
    if (status === 503) return "Dịch vụ tư vấn đang bận. Bạn có thể thử gửi lại cùng lượt tin.";
    if (status === 429) return "Bạn đã gửi quá nhiều lượt trong một phút. Vui lòng đợi rồi thử lại.";
    return typeof data?.detail === "string" ? data.detail : `Không gửi được tin (mã ${status}).`;
  }

  async function sendTurn(turn) {
    clearError();
    setBusy(true);
    const agentStarted = performance.now();
    speech.setStage("agent", "đang xử lý lượt hội thoại…");
    // Fill the otherwise silent model/tool wait with a short, non-business
    // acknowledgement. The verified answer replaces it as soon as it is ready.
    speech.acknowledge();
    turn.view.caption.textContent = "Đang xử lý…";
    turn.retry?.remove();
    turn.retry = null;
    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(turn.payload),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(readableError(response.status, data));
      if (!data.session_id || !data.agent_text || data.client_msg_id !== turn.payload.client_msg_id) {
        throw new Error("Phản hồi từ hệ thống chưa đầy đủ. Vui lòng kiểm tra trước khi gửi tiếp.");
      }
      updateFolio(data);
      const reply = makeMessage("agent", data.agent_text, "Đã trả lời");
      window.TeleSaleKnowledge.attachFeedback(reply.article, data.session_id, turnCount);
      if (workspace.currentView() === "calls") workspace.loadCalls();
      const timing = response.headers.get("Server-Timing");
      speech.setStage("agent", `xong sau ${Math.round(performance.now() - agentStarted)} ms${timing ? ` · ${timing}` : ""}`);
      speech.speak(data.agent_text);
      turn.view.caption.textContent = "Đã gửi";
      pendingTurn = null;
      ui.input.value = "";
      ui.input.focus();
    } catch (error) {
      speech.setStage("agent", `lỗi sau ${Math.round(performance.now() - agentStarted)} ms`);
      const message = error instanceof TypeError
        ? "Không kết nối được với máy chủ. Kiểm tra backend rồi thử lại."
        : error.message;
      showError(message);
      turn.view.caption.textContent = "Chưa hoàn tất";
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "retry-button";
      retry.textContent = "Gửi lại lượt này";
      retry.addEventListener("click", () => sendTurn(turn));
      turn.view.article.append(retry);
      turn.retry = retry;
      pendingTurn = turn;
    } finally {
      setBusy(false);
    }
  }

  ui.form.addEventListener("submit", (event) => {
    event.preventDefault();
    speech.primePlayback();
    if (busy) return;
    clearError();
    if (pendingTurn) {
      showError("Lượt trước chưa hoàn tất. Hãy gửi lại lượt đó trước khi tiếp tục.");
      return;
    }
    const text = ui.input.value.trim();
    if (!text) return;
    if (!accessReady) {
      showError("Đang kết nối phiên nội bộ. Vui lòng thử lại sau giây lát.");
      return;
    }
    if (!sessionId && (!ui.identity.value.trim() || !ui.callDate.value)) {
      showError("Hãy điền định danh từ kênh và ngày cuộc gọi.");
      ui.identity.focus();
      return;
    }
    const payload = {
      client_msg_id: crypto.randomUUID(), text,
      customer_input_mode: ui.inputMode.value,
    };
    if (sessionId) payload.session_id = sessionId;
    else {
      payload.channel = ui.channel.value;
      payload.channel_identity = ui.identity.value.trim();
      payload.call_date = ui.callDate.value;
    }
    const turn = { payload, view: makeMessage("customer", text, "Đang gửi…"), retry: null };
    sendTurn(turn);
  });

  speech.setCanRecord(() => {
    if (busy || pendingTurn) { showError("Hãy hoàn tất lượt hội thoại hiện tại trước khi ghi âm."); return false; }
    if (!accessReady) { showError("Phiên truy cập chưa sẵn sàng."); return false; }
    if (!sessionId && (!ui.identity.value.trim() || !ui.callDate.value)) {
      showError("Hãy điền định danh từ kênh và ngày cuộc gọi trước khi ghi âm.");
      return false;
    }
    clearError();
    return true;
  });
  speech.setTranscriptHandler((text) => {
    ui.input.value = text;
    ui.inputMode.value = "asr_transcript";
    ui.form.requestSubmit();
  });

  ui.input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      ui.form.requestSubmit();
    }
  });
  ui.newSession.addEventListener("click", () => {
    if (busy) return;
    sessionId = null;
    turnCount = 0;
    pendingTurn = null;
    speech.stopPlayback();
    speech.setStage("agent", "chờ lời khách");
    speech.setStage("tts", "chờ câu trả lời");
    setSetupLocked(false);
    ui.messages.replaceChildren();
    ui.session.textContent = "Chưa bắt đầu";
    ui.identityStatus.textContent = "Chờ định danh từ kênh";
    ui.handoff.textContent = "Chưa yêu cầu";
    ui.turnCount.textContent = "00";
    ui.brief.textContent = "Chưa có thông tin từ phiên trước.";
    ui.input.value = "";
    clearError();
    const prompt = document.createElement("div");
    prompt.className = "empty-state";
    prompt.innerHTML = '<div class="empty-emblem" aria-hidden="true">✦</div><p class="eyebrow">TRANG MỚI</p><h3>Bắt đầu cuộc gọi tiếp theo.</h3><p>Kiểm tra lại định danh và ngày cuộc gọi trước khi gửi tin đầu tiên.</p>';
    ui.messages.append(prompt);
    ui.empty = prompt;
    if (visitorMode) workspace.renderPreviousSummary();
    ui.identity.focus();
  });
  ui.channel.addEventListener("change", updateIdentityField);
  updateIdentityField();
  Promise.allSettled([fetch("/health").then((response) => response.ok), speech.checkHealth()])
    .then(([backend, audio]) => {
      const backendReady = backend.status === "fulfilled" && backend.value;
      const audioReady = audio.status === "fulfilled" && audio.value;
      ui.serviceState.textContent = backendReady && audioReady ? "Pipeline trực tuyến"
        : backendReady ? "Âm thanh chưa sẵn sàng" : "Backend chưa sẵn sàng";
      if (!backendReady) ui.connection.textContent = "Mất kết nối";
    });
  connectLocalSession().catch((error) => {
    ui.authLabel.textContent = "Chưa kết nối";
    showError(error.message);
  });
})();
