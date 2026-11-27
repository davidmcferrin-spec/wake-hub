const state = {
  token: "",
  page: "devices",
  devices: [],
  status: {},
  actions: [],
  settings: null,
  editing: null,
};

const titles = {
  devices: ["Inventory", "Devices"],
  scan: ["Discovery", "Scan"],
  power: ["Control", "Power"],
  history: ["Log", "History"],
  settings: ["Access", "Settings"],
};

function $(id) {
  return document.getElementById(id);
}

function showBanner(message, isError) {
  const banner = $("banner");
  banner.classList.toggle("error", Boolean(isError));
  if (!message) {
    banner.classList.add("hidden");
    banner.textContent = "";
    return;
  }
  banner.textContent = message;
  banner.classList.remove("hidden");
}

async function api(method, path, body) {
  const response = await fetch(path, {
    method,
    headers: {
      Authorization: `Bearer ${state.token}`,
      "Content-Type": "application/json",
      "X-Wake-Hub-Source": "ui",
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const message = data && data.error ? data.error.message : response.statusText;
    throw new Error(message);
  }
  return data;
}

function pill(device) {
  const reach = state.status[device.id];
  if (!device.enabled) return '<span class="pill off">disabled</span>';
  if (!reach) return '<span class="pill off">checking</span>';
  if (reach.reachable === true) return '<span class="pill up">up</span>';
  if (reach.reachable === false) return '<span class="pill down">down</span>';
  return '<span class="pill off">no host</span>';
}

function deviceCard(device) {
  const tags = (device.tags || []).map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("");
  return `
    <article class="card">
      <header>
        <h2>${escapeHtml(device.name)}</h2>
        ${pill(device)}
      </header>
      <p class="meta">${escapeHtml(device.host || "no host")} · ${escapeHtml(device.mac || "no MAC")}</p>
      <p class="sub">Broadcast ${escapeHtml(device.broadcast)}:${device.wol_port}</p>
      <div class="tags">${tags}</div>
      <div class="row-actions">
        <button type="button" class="primary" data-cap="wake_device" data-id="${device.id}">Wake</button>
        <button type="button" class="ghost" data-cap="power_action" data-id="${device.id}">Power on</button>
        <button type="button" class="ghost" data-cap="device_status" data-id="${device.id}">Status</button>
        <button type="button" class="ghost" data-cap="get_device" data-id="${device.id}">Edit</button>
        <button type="button" class="ghost" data-cap="device_metrics" data-id="${device.id}">Metrics</button>
        <button type="button" class="ghost" data-cap="set_device_enabled" data-id="${device.id}" data-enabled="${device.enabled ? "0" : "1"}">${device.enabled ? "Disable" : "Enable"}</button>
      </div>
    </article>`;
}

function editorHtml() {
  const device = state.editing && state.editing !== "new"
    ? state.devices.find((item) => item.id === state.editing)
    : null;
  const value = (field, fallback = "") => escapeHtml(device && device[field] != null ? device[field] : fallback);
  return `
    <form id="device-form" class="editor">
      <h2>${device ? "Edit device" : "Add device"}</h2>
      <div class="fields">
        <div>
          <label for="name">Name</label>
          <input id="name" name="name" required value="${value("name")}">
        </div>
        <div>
          <label for="mac">MAC</label>
          <input id="mac" name="mac" placeholder="AA:BB:CC:DD:EE:FF" value="${value("mac")}">
        </div>
        <div>
          <label for="host">IP or hostname</label>
          <input id="host" name="host" value="${value("host")}">
        </div>
        <div>
          <label for="broadcast">Broadcast</label>
          <input id="broadcast" name="broadcast" value="${value("broadcast", "255.255.255.255")}">
        </div>
        <div>
          <label for="wol_port">WOL port</label>
          <input id="wol_port" name="wol_port" type="number" min="1" max="65535" value="${value("wol_port", 9)}">
        </div>
        <div>
          <label for="secureon">SecureOn password</label>
          <input id="secureon" name="secureon" type="password" placeholder="${device && device.secureon_set ? "stored, leave blank to keep" : "optional"}">
        </div>
        <div>
          <label for="reach_mode">Reachability</label>
          <select id="reach_mode" name="reach_mode">
            <option value="icmp" ${!device || device.reach_mode === "icmp" ? "selected" : ""}>ICMP ping</option>
            <option value="tcp" ${device && device.reach_mode === "tcp" ? "selected" : ""}>TCP port</option>
          </select>
        </div>
        <div>
          <label for="reach_port">TCP port</label>
          <input id="reach_port" name="reach_port" type="number" value="${value("reach_port")}">
        </div>
        <div>
          <label for="reach_timeout">Wake timeout (seconds)</label>
          <input id="reach_timeout" name="reach_timeout" type="number" value="${value("reach_timeout", 30)}">
        </div>
        <div>
          <label for="wake_strategy">Wake strategy</label>
          <select id="wake_strategy" name="wake_strategy">
            <option value="wol_only" ${!device || device.wake_strategy === "wol_only" ? "selected" : ""}>Magic packet only</option>
            <option value="power_then_wol" ${device && device.wake_strategy === "power_then_wol" ? "selected" : ""}>Power on, then magic packet</option>
          </select>
        </div>
        <div>
          <label for="tags">Tags</label>
          <input id="tags" name="tags" value="${escapeHtml((device && device.tags || []).join(", "))}" placeholder="desk, lab">
        </div>
        <div class="span-2">
          <label for="notes">Notes</label>
          <textarea id="notes" name="notes">${value("notes")}</textarea>
        </div>
      </div>
      <label class="check"><input type="checkbox" name="enabled" ${!device || device.enabled ? "checked" : ""}> Enabled</label>
      <div class="row-actions" style="margin-top:0.8rem">
        ${device
          ? `<button type="submit" data-cap="update_device">Save</button>`
          : `<button type="submit" data-cap="add_device">Add device</button>`}
        ${device ? `<button type="button" class="danger" data-cap="remove_device" data-id="${device.id}">Remove</button>` : ""}
        <button type="button" class="ghost" id="close-editor">Close</button>
      </div>
    </form>`;
}

function renderDevices() {
  const cards = state.devices.map(deviceCard).join("") || `<div class="empty">No devices yet. Add one, then send a magic packet.</div>`;
  $("view").innerHTML = `
    <div class="toolbar">
      <button type="button" class="primary" id="new-device">Add device</button>
      <button type="button" class="ghost" data-cap="list_status">Refresh status</button>
    </div>
    <section class="grid">${cards}</section>
    ${state.metrics && state.metrics.length && typeof sparkline === "function" ? `<div class="card">${sparkline(state.metrics)}</div>` : ""}
    <div id="editor-slot">${state.editing ? editorHtml() : ""}</div>`;
}

function renderHistory() {
  const rows = state.actions.map((item) => `
    <tr>
      <td>${escapeHtml(item.created_at)}</td>
      <td>${escapeHtml(item.source)}</td>
      <td>${escapeHtml(item.target_name || "")}</td>
      <td>${escapeHtml(item.action)}</td>
      <td>${item.ok ? "ok" : "failed"}</td>
      <td>${escapeHtml(item.detail)}</td>
    </tr>`).join("");
  $("view").innerHTML = rows
    ? `<table><thead><tr><th>Time</th><th>Source</th><th>Target</th><th>Action</th><th>Result</th><th>Detail</th></tr></thead><tbody>${rows}</tbody></table>`
    : `<div class="empty">No power actions yet.</div>`;
}

function renderSettings() {
  const settings = state.settings || { ui_password_set: false, cors_origins: [] };
  $("view").innerHTML = `
    <section class="panel" style="padding:1rem" data-cap="get_access_token">
      <h2>API token</h2>
      <p class="lede">The REST API and MCP both require this bearer token. It is shown here because the UI is the place you copy it from.</p>
      <p class="token" id="token-value">${escapeHtml(state.token)}</p>
      <div class="row-actions">
        <button type="button" class="ghost" id="copy-token">Copy</button>
        <button type="button" class="danger" data-cap="rotate_token">Rotate token</button>
      </div>
    </section>
    <form id="settings-form" class="editor">
      <h2>Browser access</h2>
      <label for="cors">CORS origins</label>
      <input id="cors" name="cors" value="${escapeHtml(settings.cors_origins.join(", "))}">
      <label for="new-password">UI password ${settings.ui_password_set ? "(one is set)" : "(required, at least 8 characters)"}</label>
      <input id="new-password" name="ui_password" type="password" autocomplete="new-password" placeholder="leave blank to keep">
      <label for="poll">Metrics poll seconds</label>
      <input id="poll" name="metrics_poll_seconds" type="number" value="${settings.metrics_poll_seconds || 60}">
      <label for="retention">Metrics retention days</label>
      <input id="retention" name="metrics_retention_days" type="number" value="${settings.metrics_retention_days || 30}">
      <label class="check"><input type="checkbox" name="clear_ui_password"> Remove the UI password</label>
      <div class="row-actions" style="margin-top:0.8rem">
        <button type="submit" data-cap="update_settings">Save settings</button>
      </div>
    </form>`;
}

function render() {
  const [kicker, title] = titles[state.page];
  $("page-kicker").textContent = kicker;
  $("page-title").textContent = title;
  document.querySelectorAll(".sidebar button").forEach((button) => {
    button.setAttribute("aria-current", button.dataset.page === state.page ? "page" : "false");
  });
  if (state.page === "devices") renderDevices();
  if (state.page === "scan") renderScan();
  if (state.page === "power") renderPower();
  if (state.page === "history") renderHistory();
  if (state.page === "settings") renderSettings();
}

async function refreshDevices() {
  state.devices = await api("GET", "/api/v1/devices");
  const status = await api("GET", "/api/v1/status");
  state.status = {};
  status.forEach((item) => { state.status[item.device_id] = item; });
}

async function refreshActions() {
  state.actions = await api("GET", "/api/v1/actions?limit=200");
}

async function refreshSettings() {
  state.settings = await api("GET", "/api/v1/settings");
  const token = await api("GET", "/api/v1/access-token");
  state.token = token.token;
}

async function show(page) {
  state.page = page;
  showBanner("");
  try {
    if (page === "devices") await refreshDevices();
    if (page === "scan") await refreshScans();
    if (page === "power") await refreshPower();
    if (page === "history") await refreshActions();
    if (page === "settings") await refreshSettings();
  } catch (error) {
    showBanner(error.message, true);
  }
  render();
}

function formData(form) {
  return Object.fromEntries(new FormData(form).entries());
}

function devicePayload(form) {
  const data = formData(form);
  const tags = data.tags ? data.tags.split(",").map((item) => item.trim()).filter(Boolean) : [];
  const payload = {
    name: data.name,
    mac: data.mac || null,
    host: data.host || null,
    broadcast: data.broadcast || "255.255.255.255",
    wol_port: Number(data.wol_port || 9),
    notes: data.notes || "",
    tags,
    enabled: form.elements.enabled.checked,
    reach_mode: data.reach_mode,
    reach_port: data.reach_port ? Number(data.reach_port) : null,
    reach_timeout: Number(data.reach_timeout || 30),
    wake_strategy: data.wake_strategy,
  };
  if (data.secureon) payload.secureon = data.secureon;
  return payload;
}

async function onClick(event) {
  const pageButton = event.target.closest("[data-page]");
  if (pageButton) {
    await show(pageButton.dataset.page);
    return;
  }
  if (event.target.id === "new-device") {
    state.editing = "new";
    render();
    return;
  }
  if (event.target.id === "close-editor") {
    state.editing = null;
    render();
    return;
  }
  if (event.target.id === "copy-token") {
    await navigator.clipboard.writeText(state.token);
    showBanner("Token copied.");
    return;
  }
  const button = event.target.closest("[data-cap]");
  if (!button || button.type === "submit") return;
  if (window.handlePowerCap && await window.handlePowerCap(button)) return;
  const id = Number(button.dataset.id);
  try {
    if (button.dataset.cap === "wake_device") {
      const result = await api("POST", `/api/v1/devices/${id}/wake`);
      showBanner(reachText(result));
      await refreshDevices();
    } else if (button.dataset.cap === "power_action") {
      const result = await api("POST", `/api/v1/devices/${id}/power`, { action: "on", method: "wol" });
      showBanner(reachText(result));
      await refreshDevices();
    } else if (button.dataset.cap === "device_status") {
      const result = await api("GET", `/api/v1/devices/${id}/status`);
      state.status[id] = result;
      showBanner(result.reachable === true ? `${result.name} is up` : `${result.name} did not answer`);
    } else if (button.dataset.cap === "get_device") {
      state.editing = id;
    } else if (button.dataset.cap === "set_device_enabled") {
      await api("POST", `/api/v1/devices/${id}/enabled`, { enabled: button.dataset.enabled === "1" });
      await refreshDevices();
    } else if (button.dataset.cap === "remove_device") {
      if (!window.confirm("Remove this device?")) return;
      await api("DELETE", `/api/v1/devices/${id}`);
      state.editing = null;
      await refreshDevices();
    } else if (button.dataset.cap === "device_metrics") {
      const rows = await api("GET", `/api/v1/devices/${id}/metrics?limit=80`);
      state.metrics = rows;
      showBanner(rows.length ? `${rows.length} samples` : "No samples yet");
    } else if (button.dataset.cap === "list_status") {
      await refreshDevices();
    } else if (button.dataset.cap === "rotate_token") {
      if (!window.confirm("Rotate the API token? Existing scripts will stop working.")) return;
      const result = await api("POST", "/api/v1/access-token/rotate");
      state.token = result.token;
      showBanner("Token rotated. Copy the new value into other services.");
    }
    render();
  } catch (error) {
    showBanner(error.message, true);
    render();
  }
}

function reachText(result) {
  if (result.reachable === true) return `${result.name} answered in ${result.elapsed_s}s`;
  if (result.reachable === false) return `${result.name}: packet sent, host did not answer`;
  return `${result.name}: packet sent (no host to probe)`;
}

async function onSubmit(event) {
  const form = event.target;
  if (form.id === "setup-form") {
    event.preventDefault();
    const response = await fetch("/api/v1/ui/setup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_token: $("setup-token").value, password: $("setup-password").value }),
    });
    const data = await response.json();
    if (!response.ok) {
      $("setup-error").textContent = data.error ? data.error.message : "Setup failed";
      return;
    }
    $("setup").classList.add("hidden");
    await boot();
    return;
  }
  if (form.id === "login-form") {
    event.preventDefault();
    const password = $("ui-password").value;
    const response = await fetch("/api/v1/ui/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    const data = await response.json();
    if (!response.ok) {
      $("login-error").textContent = data.error ? data.error.message : "Login failed";
      return;
    }
    $("login").classList.add("hidden");
    await boot();
    return;
  }
  if (form.id === "device-form") {
    event.preventDefault();
    try {
      const payload = devicePayload(form);
      if (state.editing && state.editing !== "new") {
        await api("PATCH", `/api/v1/devices/${state.editing}`, payload);
      } else {
        await api("POST", "/api/v1/devices", payload);
      }
      state.editing = null;
      showBanner("Device saved.");
      await refreshDevices();
      render();
    } catch (error) {
      showBanner(error.message, true);
    }
    return;
  }
  if (form.id === "settings-form") {
    event.preventDefault();
    const data = formData(form);
    const payload = {
      cors_origins: data.cors.split(",").map((item) => item.trim()).filter(Boolean),
      clear_ui_password: Boolean(form.elements.clear_ui_password.checked),
      metrics_poll_seconds: Number(data.metrics_poll_seconds || 60),
      metrics_retention_days: Number(data.metrics_retention_days || 30),
    };
    if (data.ui_password) payload.ui_password = data.ui_password;
    try {
      state.settings = await api("PATCH", "/api/v1/settings", payload);
      showBanner("Settings saved.");
      render();
    } catch (error) {
      showBanner(error.message, true);
    }
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function boot() {
  const response = await fetch("/api/v1/ui/session");
  if (response.status === 401) {
    const data = await response.json();
    $("app").classList.add("hidden");
    if (data.setup_required) {
      $("login").classList.add("hidden");
      $("setup").classList.remove("hidden");
    } else {
      $("setup").classList.add("hidden");
      $("login").classList.remove("hidden");
    }
    return;
  }
  const data = await response.json();
  state.token = data.token;
  $("app").classList.remove("hidden");
  await show("devices");
  window.setInterval(() => {
    if (state.page !== "devices" || !state.token || state.editing) return;
    refreshDevices().then(() => {
      if (!state.editing && state.page === "devices") render();
    }).catch(() => {});
  }, 10000);
}

document.body.addEventListener("click", (event) => {
  onClick(event).catch((error) => showBanner(error.message, true));
});
document.body.addEventListener("submit", (event) => {
  onSubmit(event).catch((error) => showBanner(error.message, true));
});
boot().catch((error) => showBanner(error.message, true));
