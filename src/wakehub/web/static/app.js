const state = {
  token: "",
  page: "",
  devices: [],
  status: {},
  actions: [],
  settings: null,
  editing: null,
  focus: null,
  kindFilter: "all",
  deviceQuery: "",
  tagFilter: [],
  tags: [],
  salvos: [],
  salvoDraft: null,
  salvoReplace: false,
  selection: [],
  methodPicks: {},
  effects: null,
  amtAvailable: {},
  confirming: false,
};

const ask = window.confirm.bind(window);
window.confirm = (message) => {
  state.confirming = true;
  try {
    return ask(message);
  } finally {
    state.confirming = false;
  }
};

const titles = {
  devices: ["Inventory", "Devices"],
  scan: ["Discovery", "Scan"],
  power: ["Managed hardware", "Hardware"],
  salvos: ["Sequences", "Salvos"],
  history: ["Log", "History"],
  settings: ["Access", "Settings"],
};

function $(id) {
  return document.getElementById(id);
}

function showBanner(message, isError, existing) {
  const banner = $("banner");
  banner.classList.toggle("error", Boolean(isError));
  banner.replaceChildren();
  if (!message) {
    banner.classList.add("hidden");
    return;
  }
  banner.append(document.createTextNode(message));
  if (existing && existing.id) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ghost";
    button.textContent = `Open ${existing.name}`;
    button.dataset.openKind = existing.kind;
    button.dataset.id = String(existing.id);
    banner.append(document.createTextNode(" "));
    banner.append(button);
  }
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
    const error = new Error(message);
    error.existing = data && data.error ? data.error.existing : null;
    throw error;
  }
  return data;
}

function powerBlock(device) {
  const power = device.power;
  if (!power || !power.metered) return "";
  const bits = [];
  if (power.watts != null) bits.push(`${power.watts} W`);
  if (power.current_a != null) bits.push(`${power.current_a} A`);
  if (power.energy_wh != null) bits.push(`${power.energy_wh} Wh`);
  if (!bits.length) return "";
  const history = power.history || [];
  const series = history.slice().reverse().map((point) => ({ value: point.watts != null ? point.watts : point.current_a })).filter((row) => row.value != null);
  const chart = series.length && typeof sparkline === "function" ? sparkline(series) : "";
  return `<p class="meta">${escapeHtml(bits.join(" · "))}</p>${chart}`;
}

function deviceLinks(device) {
  const hardware = state.power || { pdus: [] };
  const lines = [];
  for (const method of device.methods || []) {
    if (method.kind !== "pdu") continue;
    const item = (hardware.pdus || []).find((row) => row.id === method.pdu_id);
    const outlet = (item && item.outlets || []).find((row) => row.number === method.outlet);
    const label = outlet ? outlet.name : `Outlet ${method.outlet}`;
    const pduName = item ? item.name : "PDU";
    lines.push(`<div class="row-actions">
      <span class="meta">${escapeHtml(pduName)} ${escapeHtml(label)}</span>
      <button type="button" data-cap="set_pdu_outlet" data-fields="action,confirm" data-pdu="${method.pdu_id}" data-pdu-name="${escapeHtml(pduName)}" data-outlet="${method.outlet}" data-outlet-name="${escapeHtml(label)}" data-action="on">On</button>
      <button type="button" class="danger" data-cap="set_pdu_outlet" data-fields="action,confirm" data-pdu="${method.pdu_id}" data-pdu-name="${escapeHtml(pduName)}" data-outlet="${method.outlet}" data-outlet-name="${escapeHtml(label)}" data-action="off">Off</button>
      <button type="button" class="danger" data-cap="set_pdu_outlet" data-fields="action,confirm" data-pdu="${method.pdu_id}" data-pdu-name="${escapeHtml(pduName)}" data-outlet="${method.outlet}" data-outlet-name="${escapeHtml(label)}" data-action="cycle">Cycle</button>
    </div>`);
  }
  return lines.join("");
}

function pill(device) {
  const reach = state.status[device.id];
  const mark = ` data-device-status="${device.id}"`;
  if (!device.enabled) return `<span class="pill off"${mark}>Disabled</span>`;
  if (!reach) return `<span class="pill off"${mark}>Checking</span>`;
  if (reach.reachable === true) return `<span class="pill up"${mark}>Up</span>`;
  if (reach.reachable === false) return `<span class="pill down"${mark}>Down</span>`;
  return `<span class="pill off"${mark}>No address</span>`;
}

function applyDevicePills() {
  document.querySelectorAll("[data-device-status]").forEach((node) => {
    const device = (state.devices || []).find((item) => item.id === Number(node.dataset.deviceStatus));
    if (!device) return;
    const next = document.createElement("template");
    next.innerHTML = pill(device);
    const fresh = next.content.firstElementChild;
    if (!fresh || (node.textContent === fresh.textContent && node.className === fresh.className)) return;
    node.textContent = fresh.textContent;
    node.className = fresh.className;
  });
}

async function pollStatus(force) {
  if (state.pollInFlight || state.confirming || document.hidden || !state.token) return;
  if (!force && Date.now() < (state.pollHold || 0)) return;
  const page = state.page;
  if (page !== "devices" && page !== "power" && page !== "scan" && page !== "history") return;
  state.pollInFlight = true;
  state.pollHold = Date.now() + 400;
  try {
    if (state.page === "devices") {
      const status = await api("GET", "/api/v1/status");
      state.status = {};
      status.forEach((item) => { state.status[item.device_id] = item; });
      applyDevicePills();
    }
    if (state.page === "devices" || state.page === "power") {
      if (window.loadLivePdus) await window.loadLivePdus();
      if (window.loadOperateStatus) await window.loadOperateStatus();
      if (window.pollAmt) window.pollAmt();
    }
    if (state.page === "scan" && window.pollScan) await window.pollScan();
    if (state.page === "history" && window.pollHistory) await window.pollHistory();
  } catch (_error) {
    /* a status poll leaves the page where the operator left it */
  } finally {
    state.pollInFlight = false;
  }
}

window.pollStatus = pollStatus;

function tagChips(tags) {
  return `<div class="tags">${(tags || []).map((tag) => {
    const active = (state.tagFilter || []).some((item) => tagKey(item) === tagKey(tag));
    return `<button type="button" class="tag${active ? " active" : ""}" data-tag="${escapeHtml(tag)}">#${escapeHtml(tag)}</button>`;
  }).join("")}</div>`;
}

function tagKey(value) {
  return String(value || "").replace(/^#+/, "").trim().toLowerCase();
}

function parseSearch(text) {
  const tags = [];
  const words = [];
  String(text || "").split(/[\s,]+/).forEach((part) => {
    if (part.startsWith("#") && part.length > 1) tags.push(part.slice(1));
    else if (part) words.push(part);
  });
  return { q: words.join(" "), tags };
}

function searchValue() {
  return [...(state.tagFilter || []).map((tag) => `#${String(tag).replace(/^#/, "")}`), state.deviceQuery || ""].filter(Boolean).join(" ");
}

function methodName(kind) {
  return { wol: "Wake-on-LAN", amt: "AMT", pdu: "PDU outlet", plug: "plug", jetkvm: "JetKVM", ups: "UPS", roku: "Roku" }[kind] || kind;
}

function methodShort(kind) {
  return { wol: "WOL", amt: "AMT", pdu: "PDU", plug: "plug", jetkvm: "JetKVM", ups: "UPS", roku: "Roku" }[kind] || methodName(kind);
}

function effectNote(kind, action) {
  const table = state.effects && state.effects[kind];
  return (table && table[action]) || "";
}

function storedPick(device, action) {
  const value = (state.methodPicks || {})[`${device.id}:${action}`];
  if (!value || value === "auto") return "auto";
  return methodsForAction(device, action).includes(value) ? value : "auto";
}

function activeKind(device, action) {
  const stored = storedPick(device, action);
  if (stored !== "auto") return stored;
  return (methodForAction(device, action) || {}).kind;
}

const ACTION_KINDS = {
  on: ["wol", "plug", "pdu", "amt", "ups", "jetkvm", "roku"],
  off: ["plug", "pdu", "amt", "ups", "jetkvm", "roku"],
  reboot: ["amt", "plug", "pdu", "ups", "jetkvm"],
  cycle: ["plug", "pdu", "amt", "ups", "jetkvm"],
  shutdown: ["amt", "ups", "jetkvm"],
};

function methodsForAction(device, action) {
  const can = ACTION_KINDS[action] || [];
  const seen = [];
  ((device && device.methods) || [{ kind: "wol" }]).forEach((item) => {
    const kind = item && item.kind;
    if (!kind || seen.includes(kind) || !can.includes(kind)) return;
    seen.push(kind);
  });
  return seen;
}

function methodForAction(device, action) {
  const capable = ((device && device.methods) || [{ kind: "wol" }]).filter((item) => methodsForAction(device, action).includes(item.kind));
  if (action === "off" || action === "reboot") {
    const gentle = capable.find((item) => !["plug", "pdu", "ups"].includes(item.kind));
    if (gentle) return gentle;
  }
  return capable[0] || null;
}

function methodSelect(device, action, label) {
  if (!methodForAction(device, action)) return "";
  const selected = storedPick(device, action);
  const choices = ["auto", ...methodsForAction(device, action)].map((kind) => {
    const text = kind === "auto" ? "Auto" : methodName(kind);
    const mark = kind === selected ? " selected" : "";
    return `<option value="${escapeHtml(kind)}"${mark}>${escapeHtml(text)}</option>`;
  }).join("");
  return `<label class="method-pick"><span>${escapeHtml(label)}</span><select class="action-method" data-action="${action}" aria-label="${escapeHtml(label)} method">${choices}</select></label>`;
}

function actionTitle(verb, kind, action) {
  const full = methodName(kind);
  const note = effectNote(kind, action);
  if (note && (action === "off" || action === "shutdown")) return `${verb} via ${full} (${note})`;
  return `${verb} via ${full}`;
}

function actionButton(device, action, verb, tone) {
  if (!methodForAction(device, action)) return "";
  const kind = activeKind(device, action);
  const label = kind ? `${verb} via ${methodShort(kind)}` : verb;
  const title = kind ? actionTitle(verb, kind, action) : verb;
  return `<button type="button" class="${tone}" data-cap="power_action" data-fields="action,confirm,method" data-action="${action}" data-verb="${escapeHtml(verb)}" data-id="${device.id}" title="${escapeHtml(title)}">${escapeHtml(label)}</button>`;
}

function via(device, action, verb) {
  const kind = activeKind(device, action);
  if (!kind) return verb;
  return `${verb} via ${methodShort(kind)}`;
}

function recordCard(spec) {
  const kind = spec.kind;
  const id = spec.id;
  const check = spec.check === false ? "" : `<label class="check"><input type="checkbox" class="select-record" data-kind="${escapeHtml(kind)}" data-id="${id}" ${isSelected(kind, id) ? "checked" : ""} aria-label="Select ${escapeHtml(spec.name)}"></label>`;
  const title = spec.title ? ` title="${escapeHtml(spec.title)}"` : "";
  const name = spec.open === false
    ? escapeHtml(spec.name)
    : `<button type="button" class="name-button" data-open-kind="${escapeHtml(kind)}" data-id="${id}">${escapeHtml(spec.name)}</button>`;
  return `
    <article class="card" data-kind="${escapeHtml(kind)}">
      <header class="card-head">
        ${check}
        <h2>${name}</h2>
        ${spec.badge || ""}
      </header>
      ${spec.meta ? `<p class="meta"${title}>${escapeHtml(spec.meta)}</p>` : ""}
      ${spec.body || ""}
      <div class="row-actions actions">
        ${spec.primary || ""}
        <div class="more">
          <button type="button" class="ghost more-toggle" aria-haspopup="menu" aria-expanded="false">More</button>
          <div class="menu hidden">${spec.more || ""}</div>
        </div>
      </div>
    </article>`;
}

window.recordCard = recordCard;

function deviceCard(device) {
  return recordCard({
    kind: "device",
    id: device.id,
    name: device.name,
    badge: pill(device),
    meta: `${device.host || "no host"} · ${device.mac || "no MAC"}`,
    title: `Broadcast ${device.broadcast}:${device.wol_port}`,
    body: `${powerBlock(device)}${tagChips(device.tags)}`,
    primary: `${actionButton(device, "on", "Wake", "primary")}${actionButton(device, "off", "Off", "danger")}${actionButton(device, "reboot", "Reset", "danger")}`,
    more: `
      <div class="method-picks">
        ${methodSelect(device, "on", "Wake")}
        ${methodSelect(device, "off", "Off")}
        ${methodSelect(device, "reboot", "Reset")}
        ${methodSelect(device, "cycle", "Cycle")}
        ${methodSelect(device, "shutdown", "Shutdown")}
      </div>
      <button type="button" class="ghost" data-open-kind="device" data-id="${device.id}">Open</button>
      <button type="button" class="ghost" data-cap="get_device" data-fields="" data-id="${device.id}" aria-label="Edit ${escapeHtml(device.name)}">Edit</button>
      ${actionButton(device, "cycle", "Cycle", "danger")}
      ${actionButton(device, "shutdown", "Shutdown", "danger")}
      <button type="button" class="danger delete" data-cap="remove_device" data-fields="" data-id="${device.id}">Delete</button>`,
  });
}

function hardwareChoices(kind, selected) {
  const power = state.power || {};
  const rows = { amt: power.amts, jetkvm: power.jetkvms, plug: power.plugs, pdu: power.pdus, ups: power.ups, roku: power.rokus }[kind] || [];
  const options = rows.map((row) => `<option value="${row.id}" ${Number(selected) === Number(row.id) ? "selected" : ""}>${escapeHtml(row.name)}</option>`).join("");
  return `<select class="method-target" aria-label="${escapeHtml(methodName(kind))}"><option value="">New</option>${options}</select>`;
}

function methodEditor(device) {
  const methods = (device && device.methods && device.methods.length) ? device.methods : [{ kind: "wol" }];
  return methods.map((method) => methodRow(method)).join("");
}

function methodSummary(kind, record, method) {
  if (kind === "wol") return "Wake-on-LAN";
  if (!record || !record.host) return `${methodName(kind)}: new`;
  const port = record.port ? `:${record.port}` : "";
  const tls = record.use_tls ? ", TLS" : "";
  const outlet = kind === "pdu" ? `, outlet ${method && method.outlet || 1}` : "";
  return `${methodName(kind)}: ${record.host}${port}${tls}${outlet}`;
}

function methodRow(method, open) {
  const kind = method.kind || "wol";
  const ref = method.amt_id || method.jetkvm_id || method.plug_id || method.pdu_id || method.ups_id || method.roku_id || "";
  const record = findMethodRecord(kind, ref);
  const login = (state.power && state.power.profiles || []).map((item) => `<option value="${item.id}" ${record && Number(record.credential_profile_id) === Number(item.id) ? "selected" : ""}>${escapeHtml(item.name)}</option>`).join("");
  const fields = kind === "wol" ? `<p class="sub">Uses this device's MAC address and broadcast.</p>` : `
    <label>Record ${hardwareChoices(kind, ref)}</label>
    <label>Host <input name="method_host" value="${escapeHtml(record && record.host || "")}"></label>
    <label>Port <input name="method_port" type="number" value="${escapeHtml(record && record.port || "")}"></label>
    <label class="check"><input type="checkbox" name="method_tls" ${record && record.use_tls ? "checked" : ""}> TLS</label>
    <label>Username <input name="method_username" value="${escapeHtml(record && record.username || "")}"></label>
    <label>Password <input name="method_password" type="password" placeholder="Leave blank to keep"></label>
    <label>Saved login <select name="method_profile"><option value="">None</option>${login}</select></label>
    ${kind === "pdu" ? `<label>Outlet <input name="method_outlet" type="number" value="${escapeHtml(method.outlet || 1)}"></label>` : ""}`;
  return `<details class="method-row" data-kind="${kind}" data-ref="${ref}" ${open ? "open" : ""}>
    <summary>${escapeHtml(methodSummary(kind, record, method))}</summary>
    ${fields}
    <div class="row-actions">
      <button type="button" class="ghost" data-move="up">Up</button>
      <button type="button" class="ghost" data-move="down">Down</button>
      <button type="button" class="ghost test-method" data-cap="test_target" data-fields="broadcast,community,confirm,host,insecure_tls,kind,mac,password,plug_kind,port,snmp_version,use_tls,username">Test</button>
      <button type="button" class="danger" data-remove-method="1">Remove</button>
    </div>
  </details>`;
}

function findMethodRecord(kind, id) {
  const power = state.power || {};
  const rows = { amt: power.amts, jetkvm: power.jetkvms, plug: power.plugs, pdu: power.pdus, ups: power.ups, roku: power.rokus }[kind] || [];
  return rows.find((row) => Number(row.id) === Number(id)) || null;
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
          <input id="broadcast" name="broadcast" value="${value("broadcast", "255.255.255.255")}" title="Magic packets are sent to this address">
          <p class="sub">Magic packets go to this broadcast address and the WOL port. Wake, outlets, plugs, and AMT are the buttons on the device card.</p>
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
        <div class="span-2">
          <label for="reach_timeout">Wake timeout (seconds)</label>
          <input id="reach_timeout" name="reach_timeout" type="number" value="${device && device.reach_timeout != null ? escapeHtml(device.reach_timeout) : ""}" placeholder="${escapeHtml((state.settings && state.settings.default_wake_timeout) || 30)}">
          <p class="sub">Leave blank to use the default in Settings at the moment you wake the device.</p>
        </div>
        <div class="span-2" id="method-list">
          <p class="sub">Methods are tried in this order. The first one that can do the action is used.</p>
          ${methodEditor(device)}
          <div class="row-actions">
            <label>Add method
              <select id="new-method-kind" aria-label="Method to add">
                <option value="amt">AMT</option>
                <option value="jetkvm">JetKVM</option>
                <option value="plug">Plug</option>
                <option value="pdu">PDU outlet</option>
                <option value="ups">UPS</option>
                <option value="roku">Roku</option>
                <option value="wol">Wake-on-LAN</option>
              </select>
            </label>
            <button type="button" class="ghost" id="add-method">Add method</button>
          </div>
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
          <input id="tags" name="tags" value="${escapeHtml((device && device.tags || []).map((tag) => String(tag).startsWith("#") ? tag : `#${tag}`).join(" "))}" placeholder="#Office #TV">
        </div>
        <div class="span-2">
          <label for="notes">Notes</label>
          <textarea id="notes" name="notes">${value("notes")}</textarea>
        </div>
      </div>
      <label class="check"><input type="checkbox" name="enabled" ${!device || device.enabled ? "checked" : ""}> Enabled</label>
      <div class="editor-footer">
        ${device
          ? `<button type="submit" data-cap="update_device" data-fields="broadcast,enabled,host,mac,methods,name,notes,power_method,reach_mode,reach_port,reach_timeout,secureon,tags,wake_strategy,wol_port">Save</button>`
          : `<button type="submit" data-cap="add_device" data-fields="broadcast,enabled,host,mac,methods,name,notes,power_method,reach_mode,reach_port,reach_timeout,secureon,tags,wake_strategy,wol_port">Add device</button>`}
        ${device ? `<button type="button" class="danger delete" data-cap="remove_device" data-fields="" data-id="${device.id}">Delete ${escapeHtml(device.name)}</button>` : ""}
        <button type="button" class="ghost" id="close-editor">Close</button>
      </div>
    </form>`;
}

function linkedHardware(kind, item) {
  const key = { amt: "amt_id", jetkvm: "jetkvm_id", plug: "plug_id", roku: "roku_id" }[kind];
  if (!key) return false;
  const mentioned = (state.devices || []).some((device) => (device.methods || []).some((method) => method.kind === kind && Number(method[key]) === Number(item.id)));
  return mentioned || Boolean(item.device_id);
}

function hardwareInventory() {
  const power = state.power || { pdus: [], amts: [], jetkvms: [], plugs: [], ups: [] };
  return [
    ...(power.pdus || []).map((item) => ({ kind: "pdu", label: "PDU", item })),
    ...(power.amts || []).filter((item) => !linkedHardware("amt", item)).map((item) => ({ kind: "amt", label: "AMT", item })),
    ...(power.jetkvms || []).filter((item) => !linkedHardware("jetkvm", item)).map((item) => ({ kind: "jetkvm", label: "JetKVM", item })),
    ...(power.plugs || []).filter((item) => !linkedHardware("plug", item)).map((item) => ({ kind: "plug", label: "Plug", item })),
    ...(power.ups || []).map((item) => ({ kind: "ups", label: "UPS", item })),
    ...(power.rokus || []).filter((item) => !linkedHardware("roku", item)).map((item) => ({ kind: "roku", label: "Roku", item })),
  ];
}

function isSelected(kind, id) {
  return (state.selection || []).some((item) => item.kind === kind && Number(item.id) === Number(id));
}

function removeCap(kind) {
  return {
    device: "remove_device",
    pdu: "remove_pdu",
    amt: "remove_amt",
    jetkvm: "remove_jetkvm",
    plug: "remove_plug",
    ups: "remove_ups",
    roku: "remove_roku",
  }[kind] || "remove_device";
}

function hardwareInventoryCard(entry) {
  const item = entry.item;
  const port = item.port ? `:${item.port}` : "";
  const controls = window.hardwareControls ? window.hardwareControls(entry.kind, item, false) : "";
  const marker = '<div class="row-actions">';
  const splitAt = controls.lastIndexOf(marker);
  const body = splitAt >= 0 ? controls.slice(0, splitAt) : controls;
  const primary = splitAt >= 0 ? controls.slice(splitAt + marker.length).replace(/<\/div>\s*$/, "") : "";
  return recordCard({
    kind: entry.kind,
    id: item.id,
    name: item.name,
    badge: `<span class="pill">${escapeHtml(entry.label)}</span>`,
    meta: `${item.host || "no host"}${port}`,
    body: `${tagChips(item.tags)}${body}`,
    primary,
    more: `
      <button type="button" class="ghost" data-open-kind="${entry.kind}" data-id="${item.id}">Open</button>
      <button type="button" class="ghost" data-edit-kind="${entry.kind}" data-id="${item.id}" aria-label="Edit ${escapeHtml(item.name)}">Edit</button>
      <button type="button" class="danger delete" data-cap="${removeCap(entry.kind)}" data-fields="" data-id="${item.id}">Delete</button>`,
  });
}

function blankSalvoStep() {
  return { target_kind: "tag", target_id: "", tags: "", action: "off", delay_seconds: 0 };
}

function salvoDraft() {
  if (!state.salvoDraft) state.salvoDraft = { id: null, name: "", on_error: "stop", steps: [blankSalvoStep()] };
  if (!state.salvoDraft.steps.length) state.salvoDraft.steps = [blankSalvoStep()];
  return state.salvoDraft;
}

function captureSalvoDraft() {
  const form = document.getElementById("salvo-form");
  if (!form) return;
  const steps = [...form.querySelectorAll(".salvo-step")].map((row) => ({
    target_kind: row.querySelector(".salvo-target").value,
    target_id: row.querySelector(".salvo-id") ? row.querySelector(".salvo-id").value : "",
    tags: row.querySelector(".salvo-tags") ? row.querySelector(".salvo-tags").value : "",
    action: row.querySelector(".salvo-action").value,
    delay_seconds: row.querySelector(".salvo-delay").value,
  }));
  const previous = state.salvoDraft;
  state.salvoDraft = {
    id: previous && previous.id,
    name: form.elements.name.value,
    slug: form.elements.slug ? form.elements.slug.value : "",
    on_error: form.elements.on_error.value,
    steps: steps.length ? steps : [blankSalvoStep()],
  };
}

function salvoPayload(draft) {
  const payload = {
    name: draft.name,
    on_error: draft.on_error,
    steps: draft.steps.map((step) => ({
      target_kind: step.target_kind,
      target_id: step.target_kind === "tag" || step.target_id === "" ? null : Number(step.target_id),
      tags: String(step.tags || "").split(/[\s,]+/).map((item) => item.trim()).filter(Boolean),
      action: step.action,
      delay_seconds: Number(step.delay_seconds || 0),
    })),
  };
  if (String(draft.slug || "").trim()) payload.slug = String(draft.slug).trim();
  return payload;
}

function salvoRecordOptions(kind, selected) {
  const outlets = [];
  ((state.power && state.power.pdus) || []).forEach((pdu) => {
    (pdu.outlets || []).forEach((outlet) => {
      if (outlet.id) outlets.push({ id: outlet.id, name: `${pdu.name} ${outlet.name}` });
    });
  });
  const records = kind === "device" ? state.devices : kind === "plug" ? ((state.power && state.power.plugs) || []) : kind === "outlet" ? outlets : ((state.power && state.power.rokus) || []);
  if (!records.length) return `<option value="">No ${kind} records</option>`;
  return records.map((item) => `<option value="${escapeHtml(item.id)}" ${String(selected) === String(item.id) ? "selected" : ""}>${escapeHtml(item.name)}</option>`).join("");
}

function salvoStepHtml(step) {
  const kind = step.target_kind || "tag";
  const actions = ["wake", "on", "off", "cycle", "shutdown"].map((action) => `<option value="${action}" ${step.action === action ? "selected" : ""}>${action}</option>`).join("");
  const kinds = [["tag", "Tags"], ["device", "Computer"], ["plug", "Plug"], ["roku", "Roku"], ["outlet", "PDU outlet"]]
    .map(([value, label]) => `<option value="${value}" ${kind === value ? "selected" : ""}>${label}</option>`).join("");
  const target = kind === "tag"
    ? `<input class="salvo-tags" value="${escapeHtml(step.tags || "")}" placeholder="#Lights #LivingRoom" aria-label="Tags"><input class="salvo-id" type="hidden" value="">`
    : `<select class="salvo-id" aria-label="Record">${salvoRecordOptions(kind, step.target_id)}</select><input class="salvo-tags" type="hidden" value="">`;
  return `<div class="salvo-step">
    <select class="salvo-action" aria-label="Action">${actions}</select>
    <select class="salvo-target" aria-label="Target">${kinds}</select>
    ${target}
    <input class="salvo-delay" type="number" min="0" max="3600" value="${escapeHtml(step.delay_seconds ?? 0)}" aria-label="Delay seconds">
  </div>`;
}

function salvoTags(salvo) {
  const tags = [];
  (salvo.steps || []).forEach((step) => {
    if (step.target_kind === "tag") (step.tags || []).forEach((tag) => tags.push(tag));
  });
  return tags;
}

function salvoLastRun(salvo) {
  const last = salvo.last_run;
  if (!last || !last.results) return `<p class="sub">No run yet.</p>`;
  const lines = last.results.map((item) => `${item.ok ? "ok" : "failed"} ${item.action} ${item.name || ""}`).join("; ");
  return `<p class="sub">Last run ${escapeHtml(last.ran_at || "")}: ${escapeHtml(lines)}</p>`;
}

function salvoUrl(salvo) {
  const slug = salvo.slug || salvo.id;
  return `${location.origin}/api/v1/salvos/${encodeURIComponent(slug)}/run`;
}

function salvoPanel() {
  const draft = salvoDraft();
  const cards = (state.salvos || []).map((salvo) => `
    <article class="card">
      <h2>${escapeHtml(salvo.name)}</h2>
      <p class="meta">${escapeHtml(salvo.slug || "")}</p>
      <p class="sub">${salvo.steps.length} step${salvo.steps.length === 1 ? "" : "s"} · ${escapeHtml((salvoTags(salvo) || []).map((tag) => `#${tag}`).join(" ") || "no tags")} · ${salvo.on_error === "continue" ? "continue on error" : "stop on error"}</p>
      ${salvoLastRun(salvo)}
      <label>Home Assistant URL<input readonly value="${escapeHtml(salvoUrl(salvo))}" aria-label="Home Assistant URL for ${escapeHtml(salvo.name)}"></label>
      <div class="row-actions">
        <button type="button" class="ghost copy-salvo-url" data-url="${escapeHtml(salvoUrl(salvo))}">Copy URL</button>
      </div>
      <div class="row-actions">
        <button type="button" class="primary" data-cap="run_salvo" data-fields="confirm,dry_run" data-id="${escapeHtml(salvo.slug || salvo.id)}">Run</button>
        <button type="button" class="ghost" data-cap="get_salvo" data-fields="" data-id="${escapeHtml(salvo.slug || salvo.id)}">Edit</button>
        <button type="button" class="ghost" data-cap="duplicate_salvo" data-fields="" data-id="${escapeHtml(salvo.slug || salvo.id)}">Duplicate</button>
        <button type="button" class="danger" data-cap="remove_salvo" data-fields="" data-id="${escapeHtml(salvo.slug || salvo.id)}">Delete</button>
      </div>
    </article>`).join("");
  const showEditor = Boolean(state.salvoSlug || state.salvoComposer || (draft && draft.id));
  return `<section class="panel salvo-layout">
    <p class="lede">A sequence such as Home Away. One confirmation covers the whole run, after a preview.</p>
    <div class="row-actions"><button type="button" class="primary" id="new-salvo">New sequence</button></div>
    <form id="salvo-form" class="hardware-form ${showEditor ? "" : "hidden"}">
      <label>Name<input name="name" value="${escapeHtml(draft.name || "")}" required></label>
      <label>Short link<input name="slug" value="${escapeHtml(draft.slug || "")}" placeholder="home-away"></label>
      <p class="sub">The slug is the stable path, for example /api/v1/salvos/home-away/run. Leave it blank to build one from the name. Renaming the salvo does not change it.</p>
      <label>If a step fails
        <select name="on_error">
          <option value="stop" ${draft.on_error !== "continue" ? "selected" : ""}>Stop</option>
          <option value="continue" ${draft.on_error === "continue" ? "selected" : ""}>Continue</option>
        </select>
      </label>
      <p class="sub">Each row is a step: action, one computer or plug or Roku or a set of tags that must all match, and seconds to wait before that step.</p>
      ${draft.steps.map((step) => salvoStepHtml(step)).join("")}
      <div class="row-actions">
        <button type="button" class="ghost" id="add-salvo-step">Add step</button>
        <button type="button" class="ghost" data-cap="list_salvos" data-fields="">Refresh salvos</button>
        ${draft.id
          ? `<button type="button" data-cap="update_salvo" data-fields="name,on_error,slug,steps" data-id="${escapeHtml(draft.id)}">Update salvo</button>`
          : `<button type="submit" data-cap="add_salvo" data-fields="name,on_error,slug,steps">Save salvo</button>`}
      </div>
    </form>
    <div class="grid">${cards || `<div class="empty"><p>No sequences yet. Name one, such as Home Away, and add a step.</p></div>`}</div>
  </section>`;
}

function wireSalvoForm() {
  const addStep = $("add-salvo-step");
  if (addStep) {
    addStep.addEventListener("click", () => {
      captureSalvoDraft();
      salvoDraft().steps.push(blankSalvoStep());
      state.salvoReplace = true;
      render();
    });
  }
  document.querySelectorAll(".salvo-target").forEach((select) => {
    select.addEventListener("change", () => render());
  });
}

window.saveSalvo = async function (id) {
  captureSalvoDraft();
  const payload = salvoPayload(salvoDraft());
  if (id) await api("PATCH", `/api/v1/salvos/${id}`, payload);
  else await api("POST", "/api/v1/salvos", payload);
  state.salvoDraft = null;
  state.salvoReplace = true;
  showBanner("Saved");
  await refreshDevices();
  render();
};

window.editSalvo = async function (el) {
  const salvo = await api("GET", `/api/v1/salvos/${el.dataset.id}`);
  state.salvoDraft = {
    id: salvo.slug || salvo.id,
    name: salvo.name,
    slug: salvo.slug || "",
    on_error: salvo.on_error,
    steps: (salvo.steps.length ? salvo.steps : [blankSalvoStep()]).map((step) => ({
      target_kind: step.target_kind,
      target_id: step.target_id || "",
      tags: (step.tags || []).map((tag) => `#${tag}`).join(" "),
      action: step.action,
      delay_seconds: step.delay_seconds,
    })),
  };
  state.salvoReplace = true;
  state.page = "salvos";
  state.salvoSlug = salvo.slug || "";
  writeRoute("salvos", state.salvoSlug);
  render();
};

window.duplicateSalvo = async function (el) {
  await api("POST", `/api/v1/salvos/${el.dataset.id}/duplicate`);
  showBanner("Salvo copied");
  await refreshDevices();
  render();
};

window.deleteSalvo = async function (el) {
  if (!window.confirm("Delete this salvo?")) return;
  await api("DELETE", `/api/v1/salvos/${el.dataset.id}`);
  if (state.salvoDraft && String(state.salvoDraft.id) === String(el.dataset.id)) state.salvoDraft = null;
  showBanner("Salvo deleted");
  await refreshDevices();
  render();
};

window.runSalvo = async function (el) {
  const id = el.dataset.id;
  const preview = await api("POST", `/api/v1/salvos/${id}/run`, { dry_run: true, confirm: false });
  const lines = [];
  (preview.steps || []).forEach((step) => {
    const wait = step.delay_seconds ? ` after ${step.delay_seconds}s` : "";
    const via = step.method && step.method !== "auto" ? ` via ${methodName(step.method)}` : "";
    (step.targets || []).forEach((target) => lines.push(`${step.action} ${target.name}${via}${wait}`));
  });
  if (!lines.length) {
    showBanner(`${preview.name} does not match any devices.`, true);
    return;
  }
  if (!window.confirm(`${preview.name} will:\n${lines.join("\n")}`)) return;
  const result = await api("POST", `/api/v1/salvos/${id}/run`, { dry_run: false, confirm: true });
  const targets = (result.steps || []).flatMap((step) => step.targets || []);
  const failed = targets.filter((item) => !item.ok).length;
  showBanner(result.stopped ? `${preview.name} stopped after an error.` : `${preview.name} ran ${targets.length}.`, failed > 0);
  state.salvoReplace = true;
  await refreshDevices();
  render();
};

function deviceCardsHtml() {
  const kind = state.kindFilter || "all";
  const query = (state.deviceQuery || "").toLowerCase();
  const wanted = state.tagFilter || [];
  const matches = (item) => {
    const text = !query || `${item.name} ${item.host || ""}`.toLowerCase().includes(query);
    const owned = (item.tags || []).map(tagKey);
    const outletTags = (item.outlets || []).flatMap((outlet) => outlet.tags || []).map(tagKey);
    const tagged = !wanted.length || wanted.every((tag) => owned.includes(tagKey(tag)) || outletTags.includes(tagKey(tag)));
    return text && tagged;
  };
  const computers = (kind === "all" || kind === "device" ? state.devices.filter(matches) : []).map(deviceCard).join("");
  const hardware = hardwareInventory()
    .filter((entry) => (kind === "all" || kind === entry.kind) && matches(entry.item))
    .map(hardwareInventoryCard)
    .join("");
  if (computers || hardware) return `${computers}${hardware}`;
  const any = (state.devices || []).length || hardwareInventory().length;
  if (!any && !query && !wanted.length) {
    return `<div class="empty"><p>No devices yet. Scan your network or add a device.</p><div class="row-actions"><button type="button" class="primary" id="empty-add">Add device</button><button type="button" class="ghost" data-page="scan">Scan your network</button></div></div>`;
  }
  return `<div class="empty">Nothing matches this search.</div>`;
}

function syncBulkBar() {
  const bar = $("bulk-bar");
  if (!bar) return;
  const selected = state.selection || [];
  const tags = state.tagFilter || [];
  const show = selected.length > 0 || tags.length > 0;
  bar.classList.toggle("hidden", !show);
  const label = $("bulk-label");
  const parts = [];
  if (selected.length) parts.push(`${selected.length} selected`);
  if (tags.length) parts.push(tags.map((tag) => `#${tag}`).join(" "));
  if (label) label.textContent = parts.join(" · ");
  bar.querySelectorAll("[data-action]").forEach((button) => {
    button.classList.toggle("hidden", !tags.length);
  });
  const selectedDelete = $("delete-selected");
  const taggedDelete = $("delete-tagged");
  if (selectedDelete) selectedDelete.classList.toggle("hidden", !selected.length);
  if (taggedDelete) taggedDelete.classList.toggle("hidden", !tags.length);
}

function renderDevices() {
  if (!state.salvoReplace) captureSalvoDraft();
  state.salvoReplace = false;
  if (state.focus && state.focus.kind !== "device" && window.hardwareEditor && window.findHardware) {
    const record = window.findHardware(state.focus.kind, state.focus.id);
    const body = state.focus.mode === "edit"
      ? (window.hardwareEditor ? window.hardwareEditor(state.focus.kind, record) : "")
      : (window.hardwareControls ? window.hardwareControls(state.focus.kind, record, true) : "");
    $("view").innerHTML = record
      ? `<div class="row-actions"><button type="button" class="ghost" id="back-inventory">Back</button><button type="button" class="ghost" data-edit-kind="${state.focus.kind}" data-id="${record.id}">Edit</button><button type="button" class="danger delete" data-cap="${removeCap(state.focus.kind)}" data-fields="" data-id="${record.id}">Delete ${escapeHtml(record.name)}</button></div>${body}`
      : `<div class="row-actions"><button type="button" class="ghost" id="back-inventory">Back</button></div><div class="empty">That record is gone. Go back and pick another.</div>`;
    if (window.loadLivePdus) window.loadLivePdus();
    if (window.loadOperateStatus) window.loadOperateStatus();
    return;
  }
  if (state.focus && state.focus.kind === "device") {
    const device = (state.devices || []).find((item) => item.id === Number(state.focus.id));
    if (!device) {
      state.focus = null;
    } else if (state.focus.mode === "edit") {
      state.editing = device.id;
      state.focus = null;
    } else {
      const methods = (device.methods || []).map((item) => `<li>${escapeHtml(methodName(item.kind))}</li>`).join("");
      $("view").innerHTML = `
        <div class="row-actions"><button type="button" class="ghost" id="back-inventory">Back</button><button type="button" class="ghost" data-cap="get_device" data-fields="" data-id="${device.id}">Edit</button></div>
        <article class="card detail">
          <header class="card-head"><h2>${escapeHtml(device.name)}</h2>${pill(device)}</header>
          <p class="meta">${escapeHtml(device.host || "no host")} · ${escapeHtml(device.mac || "no MAC")}</p>
          ${tagChips(device.tags)}
          <div class="row-actions actions">
            ${actionButton(device, "on", "Wake", "primary")}
            ${actionButton(device, "off", "Off", "danger")}
            ${actionButton(device, "reboot", "Reset", "danger")}
            ${actionButton(device, "cycle", "Cycle", "danger")}
            ${actionButton(device, "shutdown", "Shutdown", "danger")}
          </div>
          <h3>Methods</h3>
          <ol>${methods}</ol>
          <h3>Linked outlets</h3>
          ${deviceLinks(device) || `<p class="sub">No outlet is linked.</p>`}
          <h3>Power history</h3>
          <div id="power-history"><p class="sub">Loading samples.</p></div>
          <div class="row-actions">
            <button type="button" class="sr-only" data-cap="wake_device" data-fields="method,timeout" data-id="${device.id}">Send magic packet</button>
            <button type="button" class="ghost" data-cap="device_status" data-fields="" data-id="${device.id}">Status</button>
            <button type="button" class="ghost" data-cap="device_metrics" data-fields="limit" data-id="${device.id}">Metrics</button>
            <button type="button" class="ghost" data-cap="set_device_enabled" data-fields="enabled" data-id="${device.id}" data-enabled="${device.enabled ? "0" : "1"}">${device.enabled ? "Disable" : "Enable"}</button>
          </div>
        </article>`;
      api("GET", `/api/v1/devices/${device.id}/metrics?limit=40`).then((rows) => {
        const slot = $("power-history");
        if (!slot) return;
        slot.innerHTML = rows.length && typeof sparkline === "function" ? sparkline(rows.map((row) => ({ value: row.watts || row.value || 0 }))) : `<p class="sub">No samples yet.</p>`;
      }).catch(() => {
        const slot = $("power-history");
        if (slot) slot.innerHTML = `<p class="sub">No samples yet.</p>`;
      });
      return;
    }
  }
  const kind = state.kindFilter || "all";
  $("view").innerHTML = `
    <div class="toolbar">
      <form id="filter-form" class="search-line">
        <input id="device-search" name="q" data-cap="list_tags" data-fields="" placeholder="Search or #Office" aria-label="Search" value="${escapeHtml(searchValue())}" autocomplete="off">
        <button type="submit" class="sr-only" tabindex="-1" aria-hidden="true" data-cap="list_devices" data-fields="q,tag,tags">Search</button>
      </form>
      <div id="tag-suggest" class="row-actions"></div>
      <label>Type
        <select id="kind-filter" aria-label="Type">
          <option value="all">All</option>
          <option value="device">Computers</option>
          <option value="pdu">PDU</option>
          <option value="amt">AMT</option>
          <option value="jetkvm">JetKVM</option>
          <option value="plug">Plug</option>
          <option value="ups">UPS</option>
          <option value="roku">Roku</option>
        </select>
      </label>
    </div>
    <div id="bulk-bar" class="bulk-bar hidden" role="region" aria-label="Actions for the current selection">
      <span id="bulk-label"></span>
      <button type="button" class="ghost" data-cap="tag_action" data-fields="action,confirm,tags" data-action="wake">Wake</button>
      <button type="button" class="danger" data-cap="tag_action" data-fields="action,confirm,tags" data-action="off">Power off</button>
      <button type="button" class="danger delete" id="delete-selected" data-cap="bulk_remove" data-fields="confirm,tags,targets">Delete</button>
      <button type="button" class="danger delete" id="delete-tagged" data-cap="bulk_remove" data-fields="confirm,tags,targets">Delete tagged</button>
    </div>
    <p class="lede">A device is a machine. Wake-on-LAN, outlets, and plugs are ways to control it. Hardware is where you add a box and set its address.</p>
    <section id="device-grid" class="grid" data-query="${escapeHtml(searchValue())}">${deviceCardsHtml()}</section>
    ${state.metrics && state.metrics.length && typeof sparkline === "function" ? `<div class="card">${sparkline(state.metrics)}</div>` : ""}
    <div id="editor-slot">${state.editing ? editorHtml() : ""}</div>`;
  const filter = $("kind-filter");
  if (filter) {
    filter.value = kind;
    filter.addEventListener("change", () => {
      state.kindFilter = filter.value;
      const grid = $("device-grid");
      if (grid) {
        grid.innerHTML = deviceCardsHtml();
        if (window.bindOutlets) window.bindOutlets(grid);
      } else render();
    });
  }
  const search = $("device-search");
  if (search) {
    search.addEventListener("input", () => {
      const parsed = parseSearch(search.value);
      state.deviceQuery = parsed.q;
      state.tagFilter = parsed.tags;
      suggestTags(search);
      const grid = $("device-grid");
      if (grid) {
        grid.innerHTML = deviceCardsHtml();
        if (window.bindOutlets) window.bindOutlets(grid);
      }
      syncBulkBar();
    });
  }
  syncBulkBar();
  wireSalvoForm();
  if (window.loadLivePdus) window.loadLivePdus();
  if (window.loadOperateStatus) window.loadOperateStatus();
}

function suggestTags(input) {
  const box = $("tag-suggest");
  if (!box) return;
  const match = input.value.match(/(?:^|\s)#([^\s#]*)$/);
  if (!match) {
    box.replaceChildren();
    return;
  }
  const prefix = tagKey(match[1]);
  const options = (state.tags || []).filter((tag) => tagKey(tag).startsWith(prefix)).slice(0, 8);
  box.innerHTML = options.map((tag) => `<button type="button" class="ghost" data-complete-tag="${escapeHtml(tag)}">#${escapeHtml(tag)}</button>`).join("");
}

function sourceLabel(source) {
  return { ui: "UI", api: "API", mcp: "MCP" }[source] || source || "";
}

function historyRow(item) {
  return `<tr data-action-id="${item.id}">
      <td>${escapeHtml(item.created_at)}</td>
      <td>${escapeHtml(sourceLabel(item.source))}</td>
      <td>${escapeHtml(item.target_name || "")}</td>
      <td>${escapeHtml(item.action)}</td>
      <td>${item.ok ? "ok" : "failed"}</td>
      <td>${escapeHtml(item.detail)}</td>
    </tr>`;
}

window.pollHistory = async function () {
  if (state.historyQuiet && Date.now() < state.historyQuiet) return;
  const form = document.getElementById("history-form");
  if (!form) return;
  const filter = state.historyFilter || { device_id: "", limit: "100" };
  const limit = Math.max(1, Number(filter.limit) || 100);
  const params = new URLSearchParams();
  if (filter.device_id) params.set("device_id", String(filter.device_id));
  params.set("limit", String(limit));
  try {
    const rows = await api("GET", `/api/v1/actions?${params}`);
    state.actions = rows;
    let table = document.getElementById("history-table");
    if (!table && rows.length) {
      const empty = document.querySelector("#view .empty");
      if (empty) empty.remove();
      form.insertAdjacentHTML("afterend", `<table id="history-table"><thead><tr><th>Time</th><th>Source</th><th>Target</th><th>Action</th><th>Result</th><th>Detail</th></tr></thead><tbody></tbody></table>`);
      table = document.getElementById("history-table");
    }
    const body = table && table.querySelector("tbody");
    if (!body) return;
    const have = new Set([...body.querySelectorAll("[data-action-id]")].map((row) => row.dataset.actionId));
    const newer = rows.filter((item) => !have.has(String(item.id)));
    const scroller = document.scrollingElement;
    const top = scroller ? scroller.scrollTop : 0;
    for (let index = newer.length - 1; index >= 0; index -= 1) {
      body.insertAdjacentHTML("afterbegin", historyRow(newer[index]));
    }
    while (body.children.length > limit) body.lastElementChild.remove();
    if (scroller) scroller.scrollTop = top;
  } catch (_error) {
    state.historyQuiet = Date.now() + 20000;
  }
};

function renderHistory() {
  const rows = state.actions.map((item) => historyRow(item)).join("");
  $("view").innerHTML = `
    <form id="history-form" class="toolbar">
      <input name="device_id" type="number" placeholder="device id" aria-label="Device id" value="${escapeHtml((state.historyFilter && state.historyFilter.device_id) || "")}">
      <input name="limit" type="number" value="${escapeHtml((state.historyFilter && state.historyFilter.limit) || "100")}" aria-label="Limit">
      <button type="submit" data-cap="list_actions" data-fields="device_id,limit">Refresh log</button>
    </form>
    ${rows
      ? `<table id="history-table"><thead><tr><th>Time</th><th>Source</th><th>Target</th><th>Action</th><th>Result</th><th>Detail</th></tr></thead><tbody>${rows}</tbody></table>`
      : `<div class="empty"><p>Nothing has been switched yet. Wake a device and the result will show here.</p></div>`}`;
}

function renderSettings() {
  const settings = state.settings || { ui_password_set: false, cors_origins: [] };
  $("view").innerHTML = `
    <section class="panel" style="padding:1rem" data-cap="get_settings" data-fields="">
      <h2>Browser access</h2>
      ${(settings.control_merges || []).length ? `<p class="sub">Folded into a device: ${escapeHtml((settings.control_merges || []).map((item) => `${item.hardware} (${item.kind}) into ${item.into}`).join("; "))}.</p>` : ""}
      ${(settings.duplicate_records || []).length ? `<p class="sub">Duplicate hosts were left in place: ${escapeHtml((settings.duplicate_records || []).map((item) => `${item.kind} ${item.key} (${item.names})`).join("; "))}. Remove the extras by hand.</p>` : ""}
    </section>
    <section class="panel" style="padding:1rem" data-cap="get_access_token" data-fields="">
      <h2>API token</h2>
      <p class="lede">The REST API and MCP both require this bearer token. It is shown here because the UI is the place you copy it from.</p>
      <p class="token" id="token-value">${escapeHtml(state.token)}</p>
      <div class="row-actions">
        <button type="button" class="ghost" id="copy-token">Copy</button>
        <button type="button" class="danger" data-cap="rotate_token" data-fields="">Rotate token</button>
      </div>
    </section>
    <form id="settings-form" class="editor">
      <h2>Settings</h2>
      <div class="fields">
        <div>
          <label for="cors">Sites allowed to call this hub</label>
          <input id="cors" name="cors" value="${escapeHtml(settings.cors_origins.join(", "))}">
        </div>
        <div>
          <label for="new-password">New sign-in password ${settings.ui_password_set ? "(leave blank to keep the current one)" : "(at least 8 characters)"}</label>
          <input id="new-password" name="ui_password" type="password" autocomplete="new-password" placeholder="Leave blank to keep">
        </div>
        <div>
          <label for="default-wake-timeout">Default wake timeout (seconds)</label>
          <input id="default-wake-timeout" name="default_wake_timeout" type="number" min="1" max="300" value="${settings.default_wake_timeout || 30}">
        </div>
        <div>
          <label for="session-days">Remember this browser (days)</label>
          <input id="session-days" name="session_days" type="number" min="1" max="365" value="${settings.session_days || 30}">
        </div>
        <div>
          <label for="poll">How often to read power (seconds)</label>
          <input id="poll" name="metrics_poll_seconds" type="number" value="${settings.metrics_poll_seconds || 60}">
        </div>
        <div>
          <label for="retention">Keep power history (days)</label>
          <input id="retention" name="metrics_retention_days" type="number" value="${settings.metrics_retention_days || 30}">
        </div>
        <div>
          <label for="scan-keep">Keep the last N scans (0 keeps all)</label>
          <input id="scan-keep" name="scan_keep" type="number" min="0" max="500" value="${settings.scan_keep || 0}">
        </div>
        <div>
          <label for="scan-keep-days">Drop scans older than N days (0 keeps every age)</label>
          <input id="scan-keep-days" name="scan_keep_days" type="number" min="0" max="3650" value="${settings.scan_keep_days || 0}">
        </div>
      </div>
      <label class="check"><input type="checkbox" name="clear_ui_password"> Remove the sign-in password</label>
      <div class="row-actions">
        <button type="submit" data-cap="update_settings" data-fields="clear_ui_password,cors_origins,default_wake_timeout,metrics_poll_seconds,metrics_retention_days,scan_keep,scan_keep_days,session_days,ui_password">Save settings</button>
        <button type="button" class="ghost" data-cap="ui_logout" data-fields="">Sign out</button>
      </div>
    </form>`;
}

function renderSalvos() {
  if (!state.salvoReplace) captureSalvoDraft();
  const replaced = state.salvoReplace;
  state.salvoReplace = false;
  if (state.salvoSlug) {
    const found = (state.salvos || []).find((item) => item.slug === state.salvoSlug || String(item.id) === String(state.salvoSlug));
    const same = state.salvoDraft && String(state.salvoDraft.id) === String(found && (found.slug || found.id)) && state.salvoDraft.name;
    if (found && !same) {
      state.salvoDraft = {
        id: found.slug || found.id,
        name: found.name,
        slug: found.slug || "",
        on_error: found.on_error,
        steps: (found.steps.length ? found.steps : [blankSalvoStep()]).map((step) => ({
          target_kind: step.target_kind,
          target_id: step.target_id || "",
          tags: (step.tags || []).map((tag) => `#${tag}`).join(" "),
          action: step.action,
          delay_seconds: step.delay_seconds,
        })),
      };
    }
  }
  $("view").innerHTML = salvoPanel();
  wireSalvoForm();
  document.querySelectorAll(".copy-salvo-url").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(button.dataset.url);
        showBanner("Copied the Home Assistant URL");
      } catch (_error) {
        showBanner("Select the URL and copy it.", true);
      }
    });
  });
}

function readRoute() {
  const raw = (location.hash || "").replace(/^#\/?/, "");
  const slash = raw.indexOf("/");
  const head = decodeURIComponent(slash === -1 ? raw : raw.slice(0, slash));
  const tail = decodeURIComponent(slash === -1 ? "" : raw.slice(slash + 1));
  const pages = { devices: "devices", scan: "scan", hardware: "power", salvos: "salvos", history: "history", settings: "settings" };
  if (head === "devices") return { page: "devices", slug: /^\d+$/.test(tail) ? tail : "" };
  if (head === "salvos") return { page: "salvos", slug: tail };
  if (head === "hardware") return { page: "power", slug: tail };
  if (pages[head]) return { page: pages[head], slug: "" };
  return { page: "devices", slug: "" };
}

function writeRoute(page, slug) {
  const name = page === "power" ? "hardware" : page;
  const deviceRoute = page === "devices" && slug && /^\d+$/.test(String(slug));
  const next = slug && (page === "salvos" || page === "power" || deviceRoute) ? `#/${name}/${encodeURIComponent(slug)}` : `#/${name}`;
  if (location.hash !== next) history.replaceState(null, "", next);
}

function rememberPicks() {
  document.querySelectorAll("article.card .action-method").forEach((select) => {
    const card = select.closest("article.card");
    const marked = card && card.querySelector("[data-id]");
    if (!marked || !select.dataset.action) return;
    state.methodPicks[`${marked.dataset.id}:${select.dataset.action}`] = select.value;
  });
}

function captureTransient() {
  rememberPicks();
  const menus = [...document.querySelectorAll("article.card .more .menu:not(.hidden)")].map((node) => {
    const card = node.closest("article.card");
    const marked = card && card.querySelector("[data-id]");
    return card ? `${card.dataset.kind}:${marked ? marked.dataset.id : ""}` : "";
  }).filter(Boolean);
  const methods = [...document.querySelectorAll("details.method-row[open]")].map((node) => `${node.dataset.kind}:${node.dataset.ref || ""}`);
  const active = document.activeElement;
  let focus = null;
  if (active && active !== document.body && active.closest && active.closest("#view, #page-actions")) {
    focus = {
      id: active.id || "",
      name: active.getAttribute("name") || "",
      cap: (active.dataset && active.dataset.cap) || "",
      dataId: (active.dataset && active.dataset.id) || "",
      summary: active.classList && active.classList.contains("more-toggle"),
      start: typeof active.selectionStart === "number" ? active.selectionStart : null,
      end: typeof active.selectionEnd === "number" ? active.selectionEnd : null,
    };
  }
  return { menus, methods, focus };
}

function cardByKey(key) {
  const split = key.indexOf(":");
  const kind = key.slice(0, split);
  const id = key.slice(split + 1);
  return [...document.querySelectorAll("article.card")].find((card) => {
    if (card.dataset.kind !== kind) return false;
    const marked = card.querySelector("[data-id]");
    return marked && marked.dataset.id === id;
  });
}

function contentBounds() {
  const margin = 8;
  const bounds = { left: margin, top: margin, right: window.innerWidth - margin, bottom: window.innerHeight - margin };
  const sidebar = document.querySelector(".sidebar");
  if (!sidebar) return bounds;
  const box = sidebar.getBoundingClientRect();
  if (box.width < 1 || box.height < 1) return bounds;
  const onLeft = box.left <= margin && box.height > window.innerHeight * 0.45;
  if (onLeft) bounds.left = Math.max(bounds.left, box.right + margin);
  else if (box.width > window.innerWidth * 0.6 && box.bottom < window.innerHeight * 0.45) bounds.top = Math.max(bounds.top, box.bottom + margin);
  return bounds;
}

function placeMenu(wrap) {
  const menu = wrap.querySelector(".menu");
  const toggle = wrap.querySelector(".more-toggle");
  if (!menu || !toggle || menu.classList.contains("hidden")) return;
  const anchor = toggle.getBoundingClientRect();
  const bounds = contentBounds();
  menu.style.maxWidth = `${Math.max(120, bounds.right - bounds.left)}px`;
  menu.style.maxHeight = `${Math.max(160, bounds.bottom - bounds.top)}px`;
  const width = Math.min(menu.offsetWidth, bounds.right - bounds.left);
  const height = menu.offsetHeight;
  const roomRight = bounds.right - anchor.left;
  const roomLeft = anchor.right - bounds.left;
  let left = roomRight >= width || roomRight >= roomLeft ? anchor.left : anchor.right - width;
  left = Math.max(bounds.left, Math.min(left, bounds.right - width));
  let top = anchor.bottom + 6;
  if (top + height > bounds.bottom) top = Math.max(bounds.top, anchor.top - height - 6);
  if (top < bounds.top) top = bounds.top;
  menu.style.left = `${Math.round(left)}px`;
  menu.style.top = `${Math.round(top)}px`;
  const placed = menu.getBoundingClientRect();
  if (placed.bottom > bounds.bottom) menu.style.top = `${Math.round(Math.max(bounds.top, bounds.bottom - placed.height))}px`;
  if (placed.right > bounds.right) menu.style.left = `${Math.round(Math.max(bounds.left, bounds.right - placed.width))}px`;
  menu.dataset.placed = "1";
  if (toggle) toggle.setAttribute("aria-expanded", "true");
}

let menuScrollArmed = false;

function closeMenus() {
  menuScrollArmed = false;
  document.querySelectorAll(".more .menu").forEach((menu) => menu.classList.add("hidden"));
  document.querySelectorAll(".more-toggle").forEach((toggle) => toggle.setAttribute("aria-expanded", "false"));
}

function armMenuScroll() {
  menuScrollArmed = false;
  requestAnimationFrame(() => { menuScrollArmed = true; });
}

function restoreTransient(saved) {
  if (!saved) return;
  saved.menus.forEach((key) => {
    const card = cardByKey(key);
    const wrap = card && card.querySelector(".more");
    const menu = wrap && wrap.querySelector(".menu");
    if (menu) {
      menu.classList.remove("hidden");
      placeMenu(wrap);
      armMenuScroll();
    }
  });
  saved.methods.forEach((key) => {
    const split = key.indexOf(":");
    const kind = key.slice(0, split);
    const ref = key.slice(split + 1);
    const row = [...document.querySelectorAll("details.method-row")].find((node) => node.dataset.kind === kind && (node.dataset.ref || "") === ref);
    if (row) row.open = true;
  });
  const focus = saved.focus;
  if (!focus) return;
  let target = focus.id ? document.getElementById(focus.id) : null;
  if (!target && focus.summary && focus.dataId) {
    const card = [...document.querySelectorAll("article.card")].find((node) => {
      const marked = node.querySelector("[data-id]");
      return marked && marked.dataset.id === focus.dataId;
    });
    target = card && card.querySelector(".more-toggle");
  }
  if (!target && focus.cap && focus.dataId) target = document.querySelector(`[data-cap="${focus.cap}"][data-id="${focus.dataId}"]`);
  if (!target && focus.name && /^[A-Za-z0-9_-]+$/.test(focus.name)) target = document.querySelector(`#view [name="${focus.name}"]`);
  if (!target || !target.focus) return;
  target.focus();
  if (focus.start != null && target.setSelectionRange) {
    try { target.setSelectionRange(focus.start, focus.end); } catch (_error) { /* some inputs have no caret */ }
  }
}

function render() {
  const transient = captureTransient();
  const [kicker, title] = titles[state.page] || ["Wake Hub", "Wake Hub"];
  $("page-kicker").textContent = kicker;
  $("page-title").textContent = title;
  document.querySelectorAll(".sidebar button").forEach((button) => {
    button.setAttribute("aria-current", button.dataset.page === state.page ? "page" : "false");
  });
  const actions = $("page-actions");
  if (actions) {
    const showAdd = state.page === "devices" && !state.focus && !state.editing;
    actions.innerHTML = showAdd
      ? `<button type="button" class="primary" id="new-device">Add device</button><button type="button" class="ghost" data-cap="list_status" data-fields="">Refresh</button>`
      : "";
  }
  if (state.page === "devices") renderDevices();
  if (state.page === "scan") renderScan();
  if (state.page === "power") renderPower();
  if (state.page === "salvos") renderSalvos();
  if (state.page === "history") renderHistory();
  if (state.page === "settings") renderSettings();
  if (state.page === "devices" && state.focus && state.focus.kind === "device") {
    const device = (state.devices || []).find((item) => item.id === Number(state.focus.id));
    if (device) {
      $("page-kicker").textContent = "Device";
      $("page-title").textContent = device.name;
    }
  } else if (state.page === "devices" && state.focus && window.findHardware) {
    const record = window.findHardware(state.focus.kind, state.focus.id);
    if (record) {
      $("page-kicker").textContent = window.hardwareKindLabel(state.focus.kind);
      $("page-title").textContent = record.name;
    }
  }
  restoreTransient(transient);
  if (window.bindOutlets) window.bindOutlets();
  if (window.pollAmt && (state.page === "devices" || state.page === "power")) window.pollAmt();
  Object.entries(state.amtAvailable || {}).forEach(([id, available]) => {
    if (typeof applyAmtAvailable === "function") applyAmtAvailable(id, available);
  });
}

let deviceGeneration = 0;

async function refreshDevices() {
  // A slower search must not paint over the one the operator typed next.
  const generation = ++deviceGeneration;
  const params = new URLSearchParams();
  if (state.deviceQuery) params.set("q", state.deviceQuery);
  if (state.tagFilter && state.tagFilter.length) params.set("tags", state.tagFilter.join(","));
  const query = params.toString();
  const devices = await api("GET", `/api/v1/devices${query ? `?${query}` : ""}`);
  if (generation !== deviceGeneration) return;
  state.devices = devices;
  const withEffects = (state.devices || []).find((item) => item.effects);
  if (withEffects) state.effects = withEffects.effects;
  if (typeof refreshPower === "function") await refreshPower();
  if (generation !== deviceGeneration) return;
  try {
    const tags = await api("GET", "/api/v1/tags");
    if (generation !== deviceGeneration) return;
    state.tags = tags;
  } catch (_error) {
    if (generation !== deviceGeneration) return;
    state.tags = state.tags || [];
  }
  const salvos = await api("GET", "/api/v1/salvos");
  if (generation !== deviceGeneration) return;
  state.salvos = salvos;
  const status = await api("GET", "/api/v1/status");
  if (generation !== deviceGeneration) return;
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

async function show(page, slug) {
  state.page = page;
  state.salvoSlug = page === "salvos" ? (slug || "") : "";
  if (page === "power" && slug) state.hardwareTab = slug;
  if (page === "devices" && arguments.length > 1) {
    if (slug && /^\d+$/.test(String(slug))) {
      state.focus = { kind: "device", id: Number(slug), mode: "view" };
      state.editing = null;
    } else {
      state.focus = null;
    }
  }
  if (page === "salvos" && state.salvoSlug) {
    const draft = state.salvoDraft;
    const same = draft && String(draft.id) === state.salvoSlug && draft.name;
    if (!same) state.salvoReplace = true;
  }
  const routeSlug = page === "salvos"
    ? state.salvoSlug
    : page === "power" && state.hardwareTab && state.hardwareTab !== "all"
      ? state.hardwareTab
      : page === "devices" && state.focus && state.focus.kind === "device"
        ? String(state.focus.id)
        : "";
  writeRoute(page, routeSlug);
  showBanner("");
  if (state.booted) render();
  try {
    if (page === "devices" || page === "salvos") await refreshDevices();
    if (page === "scan") await refreshScans();
    if (page === "power") await refreshPower();
    if (page === "history") await refreshActions();
    if (page === "settings") await refreshSettings();
  } catch (error) {
    showBanner(error.message, true, error.existing);
  }
  const active = document.activeElement;
  const typing = active && active.closest && active.closest("#view input, #view textarea, #view select");
  const addOpen = document.querySelector("form.hardware-form:not(.hidden)");
  if (!document.querySelector("form.hardware-edit") && !typing && !addOpen) render();
}

function formData(form) {
  return Object.fromEntries(new FormData(form).entries());
}

function linkedMethods(data) {
  const methods = [{ kind: "wol" }];
  if (data.pdu_id) methods.push({ kind: "pdu", pdu_id: Number(data.pdu_id), outlet: Number(data.outlet || 1) });
  if (data.amt_id) methods.push({ kind: "amt", amt_id: Number(data.amt_id) });
  if (data.jetkvm_id) methods.push({ kind: "jetkvm", jetkvm_id: Number(data.jetkvm_id) });
  if (data.plug_id) methods.push({ kind: "plug", plug_id: Number(data.plug_id) });
  if (data.ups_id) methods.push({ kind: "ups", ups_id: Number(data.ups_id) });
  return methods;
}

function devicePayload(form) {
  const data = formData(form);
  const tags = data.tags ? data.tags.split(/[\s,]+/).map((item) => item.trim()).filter(Boolean) : [];
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
    wake_strategy: data.wake_strategy,
  };
  if (data.secureon) payload.secureon = data.secureon;
  const timeout = String(data.reach_timeout || "").trim();
  payload.reach_timeout = timeout ? Number(timeout) : null;
  const methods = readMethods(form);
  if (methods) payload.methods = methods;
  return payload;
}

function readMethods(form) {
  const rows = [...form.querySelectorAll(".method-row")];
  if (!rows.length) return null;
  return rows.map((row) => {
    const kind = row.dataset.kind;
    if (kind === "wol") return { kind: "wol" };
    const key = { amt: "amt_id", jetkvm: "jetkvm_id", plug: "plug_id", pdu: "pdu_id", ups: "ups_id", roku: "roku_id" }[kind];
    const select = row.querySelector(".method-target");
    const id = Number((select && select.value) || (!select && row.dataset.ref) || 0);
    const method = { kind };
    if (key && id) method[key] = id;
    const host = row.querySelector("[name=method_host]");
    if (host) method.host = host.value.trim();
    const port = row.querySelector("[name=method_port]");
    if (port && String(port.value).trim()) method.port = Number(port.value);
    const tls = row.querySelector("[name=method_tls]");
    if (tls) method.use_tls = tls.checked;
    const username = row.querySelector("[name=method_username]");
    if (username) method.username = username.value;
    const password = row.querySelector("[name=method_password]");
    if (password && password.value) method.password = password.value;
    const profile = row.querySelector("[name=method_profile]");
    if (profile) method.credential_profile_id = profile.value ? Number(profile.value) : null;
    const outlet = row.querySelector("[name=method_outlet]");
    if (kind === "pdu") method.outlet = Number(outlet && outlet.value || 1);
    return method;
  }).filter((method) => method.kind === "wol" || method.host || Object.keys(method).some((name) => name.endsWith("_id")));
}

async function onClick(event) {
  if (event.target.closest("input, select, textarea, label")) return;
  const pageButton = event.target.closest("button[data-page], a[data-page]");
  if (pageButton) {
    await show(pageButton.dataset.page);
    return;
  }
  if (event.target.id === "new-device" || event.target.id === "empty-add") {
    state.focus = null;
    state.editing = "new";
    render();
    return;
  }
  if (event.target.id === "close-editor") {
    state.editing = null;
    render();
    return;
  }
  if (event.target.id === "test-wake-method") {
    const form = document.getElementById("device-form");
    const method = form && form.elements.power_method ? form.elements.power_method.value : "wol";
    const result = await api("POST", "/api/v1/test", {
      kind: method === "auto" || method === "wol" ? "wol" : method,
      confirm: false,
      host: form.elements.host.value,
      mac: form.elements.mac.value,
      timeout: Number(form.elements.reach_timeout.value || 30),
    });
    showBanner(result.message || (result.ok ? "Test ok" : "Test failed"), result.ok === false);
    return;
  }
  if (event.target.id === "copy-token") {
    await navigator.clipboard.writeText(state.token);
    showBanner("Token copied.");
    return;
  }
  const button = event.target.closest("button[data-cap], a[data-cap]");
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
      state.focus = null;
      state.editing = id;
      writeRoute("devices", "");
    } else if (button.dataset.cap === "set_device_enabled") {
      await api("POST", `/api/v1/devices/${id}/enabled`, { enabled: button.dataset.enabled === "1" });
      await refreshDevices();
    } else if (button.dataset.cap === "remove_device") {
      await window.confirmDelete([{ kind: "device", id }], []);
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
    showBanner(error.message, true, error.existing);
    render();
  }
}

function reachText(result) {
  const name = (result && result.name) || "This device";
  if (result && result.reason) return `${name}: ${result.reason}`;
  if (result && result.amt_id != null) return `${name}: AMT command sent`;
  if (result && result.reachable === true) return `${name} answered in ${result.elapsed_s}s`;
  if (result && result.reachable === false) return `${name}: packet sent, host did not answer`;
  if (result && result.sent) return `${name}: packet sent (no host to probe)`;
  return `${name}: command sent`;
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
      const nameError = /name/i.test(error.message || "");
      if (nameError) markField(form, "name", error.message);
      showBanner(error.message, true, error.existing);
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
      session_days: Number(data.session_days || 30),
      scan_keep: Number(data.scan_keep || 0),
      scan_keep_days: Number(data.scan_keep_days || 0),
      default_wake_timeout: Number(data.default_wake_timeout || 30),
    };
    if (data.ui_password) payload.ui_password = data.ui_password;
    try {
      state.settings = await api("PATCH", "/api/v1/settings", payload);
      showBanner("Settings saved.");
      render();
    } catch (error) {
      showBanner(error.message, true, error.existing);
    }
    return;
  }
  if (form.id === "filter-form") {
    event.preventDefault();
    const parsed = parseSearch(String(new FormData(form).get("q") || ""));
    state.deviceQuery = parsed.q;
    state.tagFilter = parsed.tags;
    try {
      await refreshDevices();
      render();
    } catch (error) {
      showBanner(error.message, true, error.existing);
    }
    return;
  }
  if (form.id === "salvo-form") {
    event.preventDefault();
    try {
      await window.saveSalvo(salvoDraft().id || null);
    } catch (error) {
      showBanner(error.message, true, error.existing);
    }
    return;
  }
  if (form.id === "history-form") {
    event.preventDefault();
    const data = new FormData(form);
    const params = new URLSearchParams();
    if (data.get("device_id")) params.set("device_id", String(data.get("device_id")));
    if (data.get("limit")) params.set("limit", String(data.get("limit")));
    try {
      state.historyFilter = { device_id: data.get("device_id") || "", limit: data.get("limit") || "100" };
      state.actions = await api("GET", `/api/v1/actions?${params}`);
      render();
    } catch (error) {
      showBanner(error.message, true, error.existing);
    }
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
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
  $("setup").classList.add("hidden");
  $("login").classList.add("hidden");
  $("app").classList.remove("hidden");
  if (!state.page) {
    const route = readRoute();
    await show(route.page, route.slug);
  }
  if (state.booted) return;
  state.booted = true;
  window.setInterval(() => { pollStatus(); }, 8000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) pollStatus();
  });
}

function markField(form, name, message) {
  const input = form && form.elements ? form.elements[name] : null;
  if (!input) return;
  input.setAttribute("aria-invalid", "true");
  let note = input.parentElement.querySelector(".field-error");
  if (!note) {
    note = document.createElement("p");
    note.className = "field-error";
    note.setAttribute("role", "alert");
    input.after(note);
  }
  note.textContent = message;
}

document.addEventListener("invalid", (event) => {
  const input = event.target;
  if (!input || !input.form) return;
  event.preventDefault();
  const label = input.labels && input.labels[0] ? input.labels[0].textContent.trim() : "This";
  const message = input.validity.valueMissing
    ? `Enter ${label.replace(/\(.*\)/, "").trim().toLowerCase() || "a value"}.`
    : input.validity.tooShort
      ? "Use at least 8 characters."
      : "Check this field and try again.";
  markField(input.form, input.name, message);
  input.focus();
}, true);

document.addEventListener("input", (event) => {
  const input = event.target;
  if (!input || !input.removeAttribute) return;
  input.removeAttribute("aria-invalid");
  const note = input.parentElement && input.parentElement.querySelector(".field-error");
  if (note) note.remove();
});

window.runTest = async function (el) {
  const form = el.closest("form");
  const body = form ? Object.fromEntries(new FormData(form).entries()) : {};
  body.kind = el.dataset.kind || body.kind || "wol";
  body.confirm = el.dataset.confirm === "true";
  if (el.dataset.mac) body.mac = el.dataset.mac;
  if (el.dataset.broadcast) body.broadcast = el.dataset.broadcast;
  if (el.dataset.host) body.host = el.dataset.host;
  if (form && form.elements.use_tls) body.use_tls = Boolean(form.elements.use_tls.checked);
  if (form && form.elements.insecure_tls) body.insecure_tls = Boolean(form.elements.insecure_tls.checked);
  try {
    const result = await api("POST", "/api/v1/test", body);
    showBanner(result.message, !result.ok);
  } catch (error) {
    showBanner(error.message, true, error.existing);
  }
};

window.signOut = async function () {
  await fetch("/api/v1/ui/logout", { method: "POST" });
  state.page = "";
  state.token = "";
  $("app").classList.add("hidden");
  $("setup").classList.add("hidden");
  $("login").classList.remove("hidden");
};

window.saveProfile = async function (el) {
  const form = document.getElementById("profile-form");
  if (!form || !el.dataset.id) return;
  const data = Object.fromEntries(new FormData(form).entries());
  await api("PATCH", `/api/v1/credential-profiles/${el.dataset.id}`, data);
  await refreshPower();
  renderPower();
};

window.removeProfile = async function (el) {
  const path = `/api/v1/credential-profiles/${el.dataset.id}`;
  try {
    await api("DELETE", path);
  } catch (error) {
    const records = (error.existing && error.existing.records) || [];
    if (!records.length) throw error;
    const names = records.map((item) => `${item.kind} ${item.name}`).join(", ");
    if (!window.confirm(`${names} use this login. Remove it and clear those links?`)) return;
    await api("DELETE", `${path}?force=true`);
  }
  await refreshPower();
  renderPower();
};

document.addEventListener("submit", (event) => {
  // A form submit reloads the page, and boot opens Devices.
  event.preventDefault();
}, true);
window.confirmDelete = async function (targets, tags) {
  const preview = await api("POST", "/api/v1/inventory/remove", { confirm: false, targets: targets || [], tags: tags || [] });
  const names = (preview.targets || []).map((item) => item.name);
  if (!names.length) {
    showBanner(tags && tags.length ? "Nothing has those tags." : "Select a record first.", true);
    return;
  }
  const listed = names.length > 8 ? `${names.slice(0, 8).join(", ")} and ${names.length - 8} more` : names.join(", ");
  const salvos = preview.salvos || [];
  const warning = salvos.length ? ` Salvos that will lose a step: ${salvos.join(", ")}.` : "";
  const prompt = names.length === 1 ? `Delete ${listed}?` : `Delete ${names.length} records (${listed})?`;
  if (!window.confirm(`${prompt}${warning}`)) return;
  await api("POST", "/api/v1/inventory/remove", {
    confirm: true,
    targets: preview.targets.map((item) => ({ kind: item.kind, id: item.id })),
    tags: [],
  });
  state.selection = [];
  state.editing = null;
  state.focus = null;
  await refreshDevices();
  if (typeof refreshPower === "function") await refreshPower();
  if (state.page === "power") renderPower();
  else render();
  showBanner(`Deleted ${listed}`);
};

window.runTagAction = async function (el) {
  const tags = state.tagFilter || [];
  if (!tags.length) {
    showBanner("Type a #tag or click a chip first.", true);
    return;
  }
  const action = el.dataset.action || "wake";
  const label = action === "wake" ? "Wake" : action === "off" ? "Power off" : "Power on";
  if (!window.confirm(`${label} everything tagged ${tags.map((tag) => `#${tag}`).join(" and ")}?`)) return;
  const result = await api("POST", "/api/v1/tags/action", { tags, action, confirm: true });
  const failed = (result.results || []).filter((item) => !item.ok).length;
  showBanner(result.matched ? `${label} sent to ${result.matched}${failed ? `, ${failed} failed` : ""}` : "No records use those tags.", failed > 0);
  await refreshDevices();
  render();
};

document.body.addEventListener("change", (event) => {
  const methodPick = event.target.closest && event.target.closest(".method-target");
  if (methodPick) {
    const row = methodPick.closest(".method-row");
    const record = findMethodRecord(row.dataset.kind, methodPick.value);
    const host = row.querySelector("[name=method_host]");
    if (host) host.value = (record && record.host) || "";
    const port = row.querySelector("[name=method_port]");
    if (port) port.value = (record && record.port) || "";
    const tls = row.querySelector("[name=method_tls]");
    if (tls) tls.checked = Boolean(record && record.use_tls);
    const username = row.querySelector("[name=method_username]");
    if (username) username.value = (record && record.username) || "";
    const profile = row.querySelector("[name=method_profile]");
    if (profile) profile.value = record && record.credential_profile_id ? String(record.credential_profile_id) : "";
    row.dataset.ref = record ? String(record.id) : "";
    const summary = row.querySelector("summary");
    const outlet = row.querySelector("[name=method_outlet]");
    if (summary) summary.textContent = methodSummary(row.dataset.kind, record, { outlet: outlet && outlet.value });
    return;
  }
  const box = event.target.closest && event.target.closest(".select-record");
  if (!box) return;
  const item = { kind: box.dataset.kind, id: Number(box.dataset.id) };
  state.selection = (state.selection || []).filter((row) => !(row.kind === item.kind && Number(row.id) === item.id));
  if (box.checked) state.selection.push(item);
  syncBulkBar();
});

window.addEventListener("hashchange", () => {
  if (!state.token) return;
  const route = readRoute();
  show(route.page, route.slug).catch((error) => showBanner(error.message, true, error.existing));
});

window.addEventListener("resize", () => {
  document.querySelectorAll(".more .menu:not(.hidden)").forEach((menu) => placeMenu(menu.parentElement));
});
window.addEventListener("scroll", () => {
  if (menuScrollArmed) closeMenus();
}, true);
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  const menu = document.querySelector(".more .menu:not(.hidden)");
  if (!menu) return;
  const toggle = menu.parentElement.querySelector(".more-toggle");
  closeMenus();
  if (toggle) toggle.focus();
});

document.body.addEventListener("change", (event) => {
  const select = event.target.closest && event.target.closest("select.action-method");
  if (!select) return;
  rememberPicks();
  const card = select.closest("article");
  const action = select.dataset.action;
  const button = card && [...card.querySelectorAll("button[data-cap=power_action]")].find((node) => node.dataset.action === action);
  if (!button) return;
  const device = (state.devices || []).find((item) => item.id === Number(button.dataset.id));
  const verb = button.dataset.verb || "Wake";
  const kind = select.value !== "auto" ? select.value : (methodForAction(device, action) || {}).kind;
  if (!kind) return;
  button.textContent = `${verb} via ${methodShort(kind)}`;
  button.title = actionTitle(verb, kind, action);
});

document.body.addEventListener("click", (event) => {
  const toggle = event.target.closest && event.target.closest(".more-toggle");
  if (toggle) {
    const wrap = toggle.closest(".more");
    const menu = wrap.querySelector(".menu");
    const opening = menu.classList.contains("hidden");
    closeMenus();
    if (opening) {
      menu.classList.remove("hidden");
      toggle.setAttribute("aria-expanded", "true");
      placeMenu(wrap);
      armMenuScroll();
    }
    return;
  }
  if (!event.target.closest || !event.target.closest(".more")) closeMenus();
  const menuButton = event.target.closest && event.target.closest(".more .menu button, .more .menu a");
  if (menuButton) {
    const menu = menuButton.closest(".menu");
    if (menu) menu.classList.add("hidden");
    const toggle = menuButton.closest(".more").querySelector(".more-toggle");
    if (toggle) toggle.setAttribute("aria-expanded", "false");
  }
  const completion = event.target.closest("[data-complete-tag]");
  if (completion) {
    const input = $("device-search");
    if (input) {
      input.value = input.value.replace(/(?:^|\s)#([^\s#]*)$/, (full, _fragment) => {
        const prefix = full.startsWith(" ") || full.startsWith("#") ? full.slice(0, full.indexOf("#")) : "";
        return `${prefix}#${completion.dataset.completeTag} `;
      });
      input.focus();
    }
    return;
  }
  const chip = event.target.closest("[data-tag]");
  if (chip && chip.dataset.tag) {
    const tag = chip.dataset.tag;
    const key = tagKey(tag);
    const has = (state.tagFilter || []).some((item) => tagKey(item) === key);
    state.tagFilter = has
      ? state.tagFilter.filter((item) => tagKey(item) !== key)
      : [...(state.tagFilter || []), tag];
    refreshDevices().then(() => render()).catch((error) => showBanner(error.message, true, error.existing));
    return;
  }
  if (event.target.id === "back-inventory") {
    state.focus = null;
    state.editing = null;
    show("devices", "").catch((error) => showBanner(error.message, true, error.existing));
    return;
  }
  const save = event.target.closest("[data-save]");
  if (save && window.saveHardware) {
    window.saveHardware(save).catch((error) => showBanner(error.message, true, error.existing));
    return;
  }
  const field = event.target.closest("input, select, textarea, label");
  if (field && !event.target.closest("button, a")) return;
  if (event.target.id === "new-salvo") {
    state.salvoComposer = true;
    state.salvoReplace = true;
    render();
    return;
  }
  if (event.target.dataset && event.target.dataset.addForm) {
    const form = $(event.target.dataset.addForm);
    if (form) form.classList.toggle("hidden");
    return;
  }
  if (event.target.dataset && event.target.dataset.move) {
    const row = event.target.closest(".method-row");
    const other = event.target.dataset.move === "up" ? row.previousElementSibling : row.nextElementSibling;
    if (other && other.classList.contains("method-row")) {
      if (event.target.dataset.move === "up") row.parentElement.insertBefore(row, other);
      else row.parentElement.insertBefore(other, row);
    }
    return;
  }
  if (event.target.dataset && event.target.dataset.removeMethod) {
    const row = event.target.closest(".method-row");
    if (row) row.remove();
    return;
  }
  if (event.target.classList && event.target.classList.contains("test-method")) {
    const row = event.target.closest(".method-row");
    const kind = row.dataset.kind === "auto" ? "wol" : row.dataset.kind;
    const host = row.querySelector("[name=method_host]");
    api("POST", "/api/v1/test", { kind: kind === "wol" ? "wol" : kind, confirm: false, host: host ? host.value : "", mac: "" }).then((result) => {
      showBanner(result.message || "Test finished", result.ok === false);
    }).catch((error) => showBanner(error.message, true));
    return;
  }
  if (event.target.id === "add-method") {
    const kind = $("new-method-kind").value;
    const list = $("method-list");
    const holder = document.createElement("div");
    holder.innerHTML = methodRow({ kind }, true);
    const node = holder.firstElementChild;
    const rows = [...list.querySelectorAll(":scope > details.method-row")];
    const wol = rows.find((row) => row.dataset.kind === "wol");
    const actions = list.querySelector(":scope > .row-actions");
    if ((kind === "amt" || kind === "jetkvm") && wol) list.insertBefore(node, wol);
    else if (kind === "wol") {
      const after = rows.find((row) => ["plug", "pdu", "ups", "roku"].includes(row.dataset.kind));
      if (after) list.insertBefore(node, after);
      else if (actions) list.insertBefore(node, actions);
      else list.append(node);
    } else if (actions) list.insertBefore(node, actions);
    else list.append(node);
    return;
  }
  if (event.target.id === "roku-help") {
    const note = $("roku-help-text");
    if (note) {
      note.classList.toggle("hidden");
      event.target.setAttribute("aria-expanded", note.classList.contains("hidden") ? "false" : "true");
    }
    return;
  }
  const gear = event.target.closest("[data-edit-kind]");
  if (gear) {
    const kind = gear.dataset.editKind;
    const id = Number(gear.dataset.id);
    state.editing = null;
    state.focus = { kind, id, mode: "edit" };
    show("devices").catch((error) => showBanner(error.message, true, error.existing));
    return;
  }
  const opener = event.target.closest("[data-open-kind]");
  if (opener) {
    const kind = opener.dataset.openKind;
    const id = Number(opener.dataset.id);
    state.editing = null;
    if (kind === "device") {
      state.editing = null;
      state.focus = { kind: "device", id, mode: "view" };
      show("devices", String(id)).catch((error) => showBanner(error.message, true, error.existing));
    } else {
      state.focus = { kind, id };
      show("devices").catch((error) => showBanner(error.message, true, error.existing));
    }
    return;
  }
  const nav = event.target.closest("button[data-page], a[data-page]");
  if (nav && nav.dataset.page) {
    state.focus = null;
    show(nav.dataset.page).catch((error) => showBanner(error.message, true, error.existing));
    return;
  }
  const control = event.target.closest("button[data-cap], a[data-cap]");
  if (control && control.type !== "submit") {
    const handler = window.CONTROL_HANDLERS && window.CONTROL_HANDLERS[control.dataset.cap];
    if (handler) {
      control.disabled = true;
      control.setAttribute("aria-busy", "true");
      Promise.resolve(handler(control)).catch((error) => showBanner(error.message, true, error.existing)).finally(() => {
        if (control.isConnected) {
          control.disabled = false;
          control.removeAttribute("aria-busy");
        }
      });
      return;
    }
  }
  if (control && control.type === "submit") return;
  onClick(event).catch((error) => showBanner(error.message, true, error.existing));
});
document.body.addEventListener("submit", (event) => {
  onSubmit(event).catch((error) => showBanner(error.message, true, error.existing));
});
boot().catch((error) => showBanner(error.message, true, error.existing));
