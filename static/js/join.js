(() => {
  const $ = (id) => document.getElementById(id);
  let csrf = "";
  const message = (value, error = true) => {
    $("message").textContent = value || "";
    $("message").style.color = error ? "#9c2b2b" : "#24734b";
  };
  const labels = {
    ONBOARDING_SESSION_REQUIRED: "Откройте ссылку приглашения ещё раз.",
    INVITE_UNAVAILABLE: "Ссылка больше не действует. Попросите владельца группы создать новую.",
    ONBOARDING_SESSION_EXPIRED: "Срок подключения истёк. Откройте ссылку приглашения снова.",
    CONSENT_REQUIRED: "Подтвердите согласие, чтобы продолжить.",
    PROFILE_DISABLED: "Этот профиль отключён. Обратитесь к владельцу группы.",
    ONBOARDING_RATE_LIMITED: "Слишком много попыток. Попробуйте позже.",
    MAX_ACCOUNT_REGISTRATION_REQUIRED: "Для этого номера ещё нет аккаунта MAX. Зарегистрируйте его в официальном приложении MAX и начните подключение по ссылке заново.",
    MAX_AUTH_FAILED: "Не удалось подтвердить вход MAX. Начните вход заново или запросите новый код.",
    MAX_CODE_TIMEOUT: "Код не пришёл за 5 минут. Проверьте номер и запросите новый код.",
    MAX_AUTH_UNAVAILABLE: "Подключение к MAX сейчас недоступно. Обратитесь к владельцу группы.",
    PROXY_ASSIGNMENT_REQUIRED: "Для группы не настроен маршрут подключения к MAX. Обратитесь к владельцу группы.",
    MAX_CLOUD_PASSWORD_REJECTED: "Облачный пароль не подошёл. Запросите новый код и повторите вход.",
    PROFILE_NAME_CONFIRMATION_REQUIRED: "Сначала подтвердите ФИО существующего профиля.",
  };
  async function api(path, options = {}) {
    const headers = { ...(options.body ? { "Content-Type": "application/json" } : {}), ...(options.headers || {}) };
    if (options.method && options.method !== "GET") headers["X-Onboarding-CSRF"] = csrf;
    const response = await fetch(path, { credentials: "same-origin", cache: "no-store", ...options, headers });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(labels[data.detail] || data.detail || "Не удалось выполнить запрос.");
    return data;
  }
  async function load() {
    const state = await api("/api/public/onboarding/status");
    csrf = state.csrf_token;
    $("group").textContent = `Группа: ${state.group_name}`;
    $("consentText").textContent = `Разрешаю commentbot отправлять сообщения от имени моего MAX-аккаунта в группу «${state.group_name}» в назначенный мне день недели. Я могу отозвать согласие, отключив аккаунт.`;
    if (state.phone) {
      $("startForm").hidden = true;
      $("next").hidden = false;
      $("phoneHint").textContent = state.phone ? `Телефон: ${state.phone}` : "";
    }
    render(state);
    return state;
  }
  function render(state) {
    $("codeForm").hidden = state.state !== "waiting_code";
    $("passwordForm").hidden = state.state !== "waiting_password";
    $("membership").hidden = !["waiting_membership", "finalizing"].includes(state.state) || state.name_confirmation_required;
    $("nameForm").hidden = !state.name_confirmation_required || !["waiting_membership", "finalizing"].includes(state.state);
    if (!$("nameForm").hidden && !$("confirmedName").value) {
      $("confirmedName").value = state.existing_name || state.full_name || "";
    }
    $("maxLink").href = state.invite_link || "#";
    const text = {
      requesting_code: "Запрашиваем код MAX…",
      waiting_code: "Код запрошен у MAX. Проверьте сообщения в приложении MAX и SMS. Если код не придёт, через 5 минут можно будет запросить новый.",
      verifying_code: "Проверяем код…",
      verifying_password: "Проверяем пароль…",
      waiting_membership: "После входа откройте приглашение MAX и вступите в группу.",
      finalizing: "Проверяем профиль и сохраняем подключение…",
      completed: "Аккаунт подключён к группе.",
      failed: "Не удалось завершить вход. Можно запросить новый код.",
      interrupted: "Вход прервался. Нажмите «Запросить новый код», чтобы начать заново.",
      created: "Заполните данные для подключения.",
    };
    const failed = ["failed", "interrupted"].includes(state.state);
    $("stepText").textContent = failed && labels[state.last_error_code]
      ? labels[state.last_error_code]
      : (state.hint || text[state.state] || "Подключение к группе MAX");
    if (failed || state.state === "waiting_code") message("");
    const canRetry = failed;
    if (!canRetry) $("retryAuth")?.remove();
    if (canRetry) {
      const button = document.getElementById("retryAuth");
      if (!button) {
        const retry = document.createElement("button");
        retry.id = "retryAuth"; retry.type = "button";
        retry.addEventListener("click", async () => {
          retry.disabled = true;
          try { await api("/api/public/onboarding/resend-code", { method: "POST" }); await poll(); }
          catch (error) { message(error.message); retry.disabled = false; }
        });
        $("next").append(retry);
      }
      $("retryAuth").textContent = ["MAX_AUTH_UNAVAILABLE", "PROXY_ASSIGNMENT_REQUIRED"].includes(state.last_error_code)
        ? "Повторить подключение" : "Запросить новый код";
    }
  }
  async function poll() {
    try {
      const state = await load();
      if (["requesting_code", "waiting_code", "verifying_code", "verifying_password", "finalizing"].includes(state.state)) {
        window.setTimeout(poll, 1800);
      }
    } catch (error) { message(error.message); }
  }
  $("startForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.currentTarget.querySelector("button");
    button.disabled = true;
    message("");
    try {
      const result = await api("/api/public/onboarding/start", {
        method: "POST",
        body: JSON.stringify({ full_name: $("fullName").value, phone: $("phone").value, consent: $("consent").checked }),
      });
      $("startForm").hidden = true;
      $("next").hidden = false;
      $("phoneHint").textContent = `Номер: ${result.phone_masked}`;
      message("Данные сохранены.", false);
      poll();
    } catch (error) {
      message(error.message);
      button.disabled = false;
    }
  });
  $("codeForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    try { await api("/api/public/onboarding/code", { method: "POST", body: JSON.stringify({ code: $("code").value }) }); $("code").value = ""; poll(); }
    catch (error) { message(error.message); }
  });
  $("passwordForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    try { await api("/api/public/onboarding/password", { method: "POST", body: JSON.stringify({ password: $("password").value }) }); $("password").value = ""; poll(); }
    catch (error) { message(error.message); }
  });
  $("nameForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    try { await api("/api/public/onboarding/confirm-name", { method: "POST", body: JSON.stringify({ full_name: $("confirmedName").value }) }); $("nameForm").hidden = true; poll(); }
    catch (error) { message(error.message); }
  });
  $("checkMembership").addEventListener("click", async () => {
    try { const result = await api("/api/public/onboarding/check-membership", { method: "POST" }); if (result.joined) message("Аккаунт подключён к группе.", false); else message("Членство пока не подтверждено. Вступите в MAX и проверьте ещё раз."); poll(); }
    catch (error) { message(error.message); }
  });
  load().then((state) => { if (state.phone) poll(); }).catch((error) => message(error.message));
})();

