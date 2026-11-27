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
};

const titles = {
  devices: ["Inventory", "Devices"],
  scan: ["Discovery", "Scan"],
  power: ["Managed hardware", "Hardware"],
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
  if (!power || !power.metered) {
    return `<p class="sub">No metered source is linked. A smart plug, PDU, UPS, or JetKVM DC supply would show watts here.</p>`;
  }
  const bits = [];
  if (power.watts != null) bits.push(`${power.watts} W`);
  if (power.current_a != null) bits.push(`${power.current_a} A`);
  if (power.energy_wh != null) bits.push(`${power.energy_wh} Wh`);
  const source = power.source ? power.source.label : "meter";
  if (!bits.length) {
    return `<p class="sub">${escapeHtml(power.message || `${source} has not reported yet.`)}</p>`;
  }
  const history = power.history || [];
  const unit = history.some((point) => point.watts != null) ? "W" : "A";
  const series = history.slice().reverse().map((point) => ({ value: point.watts != null ? point.watts : point.current_a })).filter((row) => row.value != null);
  const chart = series.length && typeof sparkline === "function" ? `<p class="sub">Recent ${unit}</p>${sparkline(series)}` : "";
  return `<p class="sub">${bits.join(" · ")} from ${escapeHtml(source)}</p>${chart}`;
}

function deviceLinks(device) {
  const hardware = state.power || { pdus: [], amts: [], jetkvms: [], plugs: [], ups: [] };
  const lines = [];
  const test = `data-cap="test_target" data-fields="broadcast,community,confirm,host,insecure_tls,kind,mac,password,plug_kind,port,snmp_version,use_tls,username"`;
  lines.push(`<button type="button" class="ghost" ${test} data-kind="wol" data-confirm="false" data-mac="${escapeHtml(device.mac || "")}" data-broadcast="${escapeHtml(device.broadcast)}" data-host="${escapeHtml(device.host || "")}">Test wake</button>`);
  lines.push(`<button type="button" class="ghost" ${test} data-kind="wol" data-confirm="true" data-mac="${escapeHtml(device.mac || "")}" data-broadcast="${escapeHtml(device.broadcast)}" data-host="${escapeHtml(device.host || "")}">Send wake packet</button>`);
  for (const method of device.methods || []) {
    if (method.kind === "pdu") {
      const item = (hardware.pdus || []).find((row) => row.id === method.pdu_id);
      lines.push(`<p class="sub">PDU ${escapeHtml(item ? item.name : "outlet")} outlet ${method.outlet}. Off and reboot ask for confirmation.</p>`);
    } else if (method.kind === "plug") {
      const item = (hardware.plugs || []).find((row) => row.id === method.plug_id);
      lines.push(`<p class="sub">Smart plug ${escapeHtml(item ? item.name : "plug")} can cut power to this computer.</p>`);
    } else if (method.kind === "amt") {
      const item = (hardware.amts || []).find((row) => row.id === method.amt_id);
      lines.push(`<p class="sub">Intel AMT ${escapeHtml(item ? item.name : "endpoint")} reads power state and can shut the PC down.</p>`);
    } else if (method.kind === "jetkvm") {
      const item = (hardware.jetkvms || []).find((row) => row.id === method.jetkvm_id);
      lines.push(`<p class="sub">JetKVM ${escapeHtml(item ? item.name : "endpoint")} presses the power button. Shutdown is a short press. Force off is the long press.</p>`);
    } else if (method.kind === "ups") {
      const item = (hardware.ups || []).find((row) => row.id === method.ups_id);
      lines.push(`<p class="sub">UPS ${escapeHtml(item ? item.name : "card")} can drop every load on that UPS. Those actions ask for confirmation.</p>`);
    } else if (method.kind === "roku") {
      const item = (hardware.rokus || []).find((row) => row.id === method.roku_id);
      lines.push(`<p class="sub">Roku ${escapeHtml(item ? item.name : "TV")} uses External Control on port 8060. Control by mobile apps must be enabled. Power off asks for confirmation.</p>`);
    }
  }
  return `<div class="row-actions">${lines.join("")}</div>`;
}

function pill(device) {
  const reach = state.status[device.id];
  if (!device.enabled) return '<span class="pill off">disabled</span>';
  if (!reach) return '<span class="pill off">checking</span>';
  if (reach.reachable === true) return '<span class="pill up">up</span>';
  if (reach.reachable === false) return '<span class="pill down">down</span>';
  return '<span class="pill off">no host</span>';
}

function tagChips(tags) {
  return `<div class="tags">${(tags || []).map((tag) => {
    const active = (state.tagFilter || []).some((item) => item.toLowerCase() === String(tag).toLowerCase());
    return `<button type="button" class="tag${active ? " active" : ""}" data-tag="${escapeHtml(tag)}">#${escapeHtml(tag)}</button>`;
  }).join("")}</div>`;
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

function deviceCard(device) {
  return `
    <article class="card">
      <header>
        <label class="check"><input type="checkbox" class="select-record" data-kind="device" data-id="${device.id}" ${isSelected("device", device.id) ? "checked" : ""} aria-label="Select ${escapeHtml(device.name)}"></label>
        <h2>${escapeHtml(device.name)}</h2>
        ${pill(device)}
        <button type="button" class="danger delete" data-cap="remove_device" data-fields="" data-id="${device.id}">Delete</button>
      </header>
      <p class="meta">${escapeHtml(device.host || "no host")} · ${escapeHtml(device.mac || "no MAC")}</p>
      ${powerBlock(device)}
      <p class="sub">Broadcast ${escapeHtml(device.broadcast)}:${device.wol_port}. Wake-on-LAN, and any PDU outlet, plug, AMT, JetKVM or UPS linked below, are controlled from this computer.</p>
      ${deviceLinks(device)}
      ${tagChips(device.tags)}
      <div class="row-actions">
        <label class="sub">Method <select class="method-picker" aria-label="Power method"><option value="auto">auto</option><option value="wol">wol</option><option value="pdu">pdu</option><option value="amt">amt</option><option value="jetkvm">jetkvm</option><option value="plug">plug</option><option value="ups">ups</option></select></label>
        <input class="wake-timeout" name="timeout" type="number" placeholder="timeout" aria-label="Wake timeout">
        <button type="button" class="primary" data-cap="wake_device" data-fields="timeout" data-id="${device.id}">Wake</button>
        <button type="button" class="ghost" data-cap="power_action" data-fields="action,confirm,method" data-action="on" data-id="${device.id}">On</button>
        <button type="button" class="danger" data-cap="power_action" data-fields="action,confirm,method" data-action="off" data-id="${device.id}">Off</button>
        <button type="button" class="danger" data-cap="power_action" data-fields="action,confirm,method" data-action="cycle" data-id="${device.id}">Cycle</button>
        <button type="button" class="danger" data-cap="power_action" data-fields="action,confirm,method" data-action="reboot" data-id="${device.id}">Reboot</button>
        <button type="button" class="danger" data-cap="power_action" data-fields="action,confirm,method" data-action="shutdown" data-id="${device.id}">Shutdown</button>
        <button type="button" class="ghost" data-cap="device_status" data-fields="" data-id="${device.id}">Status</button>
        <button type="button" class="ghost" data-cap="get_device" data-fields="" data-id="${device.id}">Edit</button>
        <button type="button" class="ghost" data-cap="device_metrics" data-fields="limit" data-id="${device.id}">Metrics</button>
        <button type="button" class="ghost" data-cap="set_device_enabled" data-fields="enabled" data-id="${device.id}" data-enabled="${device.enabled ? "0" : "1"}">${device.enabled ? "Disable" : "Enable"}</button>
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
          <input id="tags" name="tags" value="${escapeHtml((device && device.tags || []).map((tag) => String(tag).startsWith("#") ? tag : `#${tag}`).join(" "))}" placeholder="#Office #TV">
        </div>
        <div class="span-2">
          <label for="notes">Notes</label>
          <textarea id="notes" name="notes">${value("notes")}</textarea>
        </div>
      </div>
      <label class="check"><input type="checkbox" name="enabled" ${!device || device.enabled ? "checked" : ""}> Enabled</label>
      <div class="row-actions" style="margin-top:0.8rem">
        <div>
          <label for="link-pdu">Linked PDU</label>
          <input id="link-pdu" name="pdu_id" type="number" placeholder="pdu id">
        </div>
        <div>
          <label for="link-outlet">Outlet</label>
          <input id="link-outlet" name="outlet" type="number" placeholder="outlet">
        </div>
        <div>
          <label for="link-amt">Linked AMT</label>
          <input id="link-amt" name="amt_id" type="number" placeholder="amt id">
        </div>
        <div>
          <label for="link-jet">Linked JetKVM</label>
          <input id="link-jet" name="jetkvm_id" type="number" placeholder="jetkvm id">
        </div>
        <div>
          <label for="link-plug">Linked plug</label>
          <input id="link-plug" name="plug_id" type="number" placeholder="plug id">
        </div>
        <div>
          <label for="link-ups">Linked UPS</label>
          <input id="link-ups" name="ups_id" type="number" placeholder="ups id">
        </div>
        ${device
          ? `<button type="submit" data-cap="update_device" data-fields="broadcast,enabled,host,mac,methods,name,notes,reach_mode,reach_port,reach_timeout,secureon,tags,wake_strategy,wol_port">Save</button>`
          : `<button type="submit" data-cap="add_device" data-fields="broadcast,enabled,host,mac,methods,name,notes,reach_mode,reach_port,reach_timeout,secureon,tags,wake_strategy,wol_port">Add device</button>`}
        ${device ? `<button type="button" class="danger delete" data-cap="remove_device" data-fields="" data-id="${device.id}">Delete ${escapeHtml(device.name)}</button>` : ""}
        <button type="button" class="ghost" id="close-editor">Close</button>
      </div>
    </form>`;
}

function hardwareInventory() {
  const power = state.power || { pdus: [], amts: [], jetkvms: [], plugs: [], ups: [] };
  return [
    ...(power.pdus || []).map((item) => ({ kind: "pdu", label: "PDU", item })),
    ...(power.amts || []).map((item) => ({ kind: "amt", label: "AMT", item })),
    ...(power.jetkvms || []).map((item) => ({ kind: "jetkvm", label: "JetKVM", item })),
    ...(power.plugs || []).map((item) => ({ kind: "plug", label: "Plug", item })),
    ...(power.ups || []).map((item) => ({ kind: "ups", label: "UPS", item })),
    ...(power.rokus || []).map((item) => ({ kind: "roku", label: "Roku", item })),
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
  return `
    <article class="card" data-kind="${entry.kind}">
      <header>
        <label class="check"><input type="checkbox" class="select-record" data-kind="${entry.kind}" data-id="${item.id}" ${isSelected(entry.kind, item.id) ? "checked" : ""} aria-label="Select ${escapeHtml(item.name)}"></label>
        <h2>${escapeHtml(item.name)}</h2>
        <span class="pill">${entry.label}</span>
        <button type="button" class="danger delete" data-cap="${removeCap(entry.kind)}" data-fields="" data-id="${item.id}">Delete</button>
      </header>
      <p class="meta">${escapeHtml(item.host || "no host")}${item.port ? `:${item.port}` : ""}</p>
      ${tagChips(item.tags)}
      <div class="row-actions">
        <button type="button" data-open-kind="${entry.kind}" data-id="${item.id}">Open</button>
      </div>
    </article>`;
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
  const records = kind === "device" ? state.devices : kind === "plug" ? ((state.power && state.power.plugs) || []) : ((state.power && state.power.rokus) || []);
  if (!records.length) return `<option value="">No ${kind} records</option>`;
  return records.map((item) => `<option value="${item.id}" ${String(selected) === String(item.id) ? "selected" : ""}>${escapeHtml(item.name)}</option>`).join("");
}

function salvoStepHtml(step) {
  const kind = step.target_kind || "tag";
  const actions = ["wake", "on", "off", "cycle", "shutdown"].map((action) => `<option value="${action}" ${step.action === action ? "selected" : ""}>${action}</option>`).join("");
  const kinds = [["tag", "Tags"], ["device", "Computer"], ["plug", "Plug"], ["roku", "Roku"]]
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

function salvoPanel() {
  const draft = salvoDraft();
  const cards = (state.salvos || []).map((salvo) => `
    <article class="card">
      <h2>${escapeHtml(salvo.name)}</h2>
      <p class="meta">${escapeHtml(salvo.slug || "")}</p>
      <p class="sub">${salvo.steps.length} step${salvo.steps.length === 1 ? "" : "s"} · ${salvo.on_error === "continue" ? "continue on error" : "stop on error"}</p>
      <div class="row-actions">
        <button type="button" class="primary" data-cap="run_salvo" data-fields="confirm,dry_run" data-id="${escapeHtml(salvo.slug || salvo.id)}">Run</button>
        <button type="button" class="ghost" data-cap="get_salvo" data-fields="" data-id="${escapeHtml(salvo.slug || salvo.id)}">Edit</button>
        <button type="button" class="ghost" data-cap="duplicate_salvo" data-fields="" data-id="${escapeHtml(salvo.slug || salvo.id)}">Duplicate</button>
        <button type="button" class="danger" data-cap="remove_salvo" data-fields="" data-id="${escapeHtml(salvo.slug || salvo.id)}">Delete</button>
      </div>
    </article>`).join("");
  return `<section class="panel" style="padding:1rem;margin-bottom:1rem">
    <h2>Salvos</h2>
    <p class="lede">A salvo is a named sequence, such as Home Away or All Lights Off. One confirmation covers the whole run, after a preview of every device it will hit.</p>
    <form id="salvo-form" class="hardware-form">
      <label>Name<input name="name" value="${escapeHtml(draft.name || "")}" required></label>
      <label>Slug<input name="slug" value="${escapeHtml(draft.slug || "")}" placeholder="home-away"></label>
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
    <div class="grid">${cards || `<div class="empty">No salvos yet.</div>`}</div>
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
    (step.targets || []).forEach((target) => lines.push(`${step.action} ${target.name}${wait}`));
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
};

function renderDevices() {
  if (!state.salvoReplace) captureSalvoDraft();
  state.salvoReplace = false;
  if (state.focus && window.hardwareEditor && window.findHardware) {
    const record = window.findHardware(state.focus.kind, state.focus.id);
    $("view").innerHTML = record
      ? `<div class="row-actions"><button type="button" class="ghost" id="back-inventory">Back</button><button type="button" class="danger delete" data-cap="${removeCap(state.focus.kind)}" data-fields="" data-id="${record.id}">Delete ${escapeHtml(record.name)}</button></div>${window.hardwareEditor(state.focus.kind, record)}`
      : `<div class="row-actions"><button type="button" class="ghost" id="back-inventory">Back</button></div><div class="empty">That hardware record is gone.</div>`;
    return;
  }
  const kind = state.kindFilter || "all";
  const query = (state.deviceQuery || "").toLowerCase();
  const wanted = state.tagFilter || [];
  const matches = (item) => {
    const text = !query || `${item.name} ${item.host || ""}`.toLowerCase().includes(query);
    const owned = (item.tags || []).map((tag) => String(tag).toLowerCase());
    const tagged = !wanted.length || wanted.every((tag) => owned.includes(String(tag).toLowerCase()));
    return text && tagged;
  };
  const computers = (kind === "all" || kind === "device" ? state.devices.filter(matches) : []).map(deviceCard).join("");
  const hardware = hardwareInventory()
    .filter((entry) => (kind === "all" || kind === entry.kind) && matches(entry.item))
    .map(hardwareInventoryCard)
    .join("");
  const cards = `${computers}${hardware}` || `<div class="empty">Nothing in this view yet.</div>`;
  $("view").innerHTML = `
    <div class="toolbar">
      <form id="filter-form" class="inline">
        <input id="device-search" name="q" data-cap="list_tags" data-fields="" placeholder="Search or #Office" aria-label="Search" value="${escapeHtml(searchValue())}" autocomplete="off">
        <button type="submit" data-cap="list_devices" data-fields="q,tag,tags">Search</button>
      </form>
      <div id="tag-suggest" class="row-actions"></div>
      <button type="button" data-cap="tag_action" data-fields="action,confirm,tags" data-action="wake">Wake tagged</button>
      <button type="button" class="danger" data-cap="tag_action" data-fields="action,confirm,tags" data-action="off">Power off tagged</button>
      <button type="button" class="danger delete" id="delete-selected" data-cap="bulk_remove" data-fields="confirm,tags,targets">Delete selected</button>
      <button type="button" class="danger delete" id="delete-tagged" data-cap="bulk_remove" data-fields="confirm,tags,targets">Delete tagged</button>
      <label class="sub">Type
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
      <button type="button" class="primary" id="new-device">Add device</button>
      <button type="button" class="ghost" data-cap="list_status" data-fields="">Refresh status</button>
    </div>
    ${salvoPanel()}
    <section class="grid">${cards}</section>
    ${state.metrics && state.metrics.length && typeof sparkline === "function" ? `<div class="card">${sparkline(state.metrics)}</div>` : ""}
    <div id="editor-slot">${state.editing ? editorHtml() : ""}</div>`;
  const filter = $("kind-filter");
  if (filter) {
    filter.value = kind;
    filter.addEventListener("change", () => {
      state.kindFilter = filter.value;
      render();
    });
  }
  const search = $("device-search");
  if (search) search.addEventListener("input", () => suggestTags(search));
  wireSalvoForm();
}

function suggestTags(input) {
  const box = $("tag-suggest");
  if (!box) return;
  const match = input.value.match(/(?:^|\s)#([^\s#]*)$/);
  if (!match) {
    box.replaceChildren();
    return;
  }
  const prefix = match[1].toLowerCase();
  const options = (state.tags || []).filter((tag) => tag.toLowerCase().startsWith(prefix)).slice(0, 8);
  box.innerHTML = options.map((tag) => `<button type="button" class="ghost" data-complete-tag="${escapeHtml(tag)}">#${escapeHtml(tag)}</button>`).join("");
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
  $("view").innerHTML = `
    <form id="history-form" class="toolbar">
      <input name="device_id" type="number" placeholder="device id" aria-label="Device id">
      <input name="limit" type="number" value="100" aria-label="Limit">
      <button type="submit" data-cap="list_actions" data-fields="device_id,limit">Refresh log</button>
    </form>
    ${rows
      ? `<table><thead><tr><th>Time</th><th>Source</th><th>Target</th><th>Action</th><th>Result</th><th>Detail</th></tr></thead><tbody>${rows}</tbody></table>`
      : `<div class="empty">No power actions yet.</div>`}`;
}

function renderSettings() {
  const settings = state.settings || { ui_password_set: false, cors_origins: [] };
  $("view").innerHTML = `
    <section class="panel" style="padding:1rem" data-cap="get_settings" data-fields="">
      <h2>Browser access</h2>
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
      <h2>Browser access</h2>
      <label for="cors">CORS origins</label>
      <input id="cors" name="cors" value="${escapeHtml(settings.cors_origins.join(", "))}">
      <label for="new-password">UI password ${settings.ui_password_set ? "(one is set)" : "(required, at least 8 characters)"}</label>
      <input id="new-password" name="ui_password" type="password" autocomplete="new-password" placeholder="leave blank to keep">
      <label for="poll">Metrics poll seconds</label>
      <input id="poll" name="metrics_poll_seconds" type="number" value="${settings.metrics_poll_seconds || 60}">
      <label for="retention">Metrics retention days</label>
      <input id="retention" name="metrics_retention_days" type="number" value="${settings.metrics_retention_days || 30}">
      <label for="scan-keep">Keep the last N scans (0 keeps all)</label>
      <input id="scan-keep" name="scan_keep" type="number" min="0" max="500" value="${settings.scan_keep || 0}">
      <label for="scan-keep-days">Drop scans older than N days (0 keeps every age)</label>
      <input id="scan-keep-days" name="scan_keep_days" type="number" min="0" max="3650" value="${settings.scan_keep_days || 0}">
      <label class="check"><input type="checkbox" name="clear_ui_password"> Remove the UI password</label>
      <div class="row-actions" style="margin-top:0.8rem">
        <label for="session-days">Remember this browser (days)</label>
        <input id="session-days" name="session_days" type="number" min="1" max="365" value="${settings.session_days || 30}">
        <button type="submit" data-cap="update_settings" data-fields="clear_ui_password,cors_origins,metrics_poll_seconds,metrics_retention_days,scan_keep,scan_keep_days,session_days,ui_password">Save settings</button>
        <button type="button" class="ghost" data-cap="ui_logout" data-fields="">Sign out</button>
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
  if (state.page === "devices" && state.focus && window.findHardware) {
    const record = window.findHardware(state.focus.kind, state.focus.id);
    if (record) {
      $("page-kicker").textContent = window.hardwareKindLabel(state.focus.kind);
      $("page-title").textContent = record.name;
    }
  }
}

async function refreshDevices() {
  const params = new URLSearchParams();
  if (state.deviceQuery) params.set("q", state.deviceQuery);
  if (state.tagFilter && state.tagFilter.length) params.set("tags", state.tagFilter.join(","));
  state.devices = await api("GET", `/api/v1/devices${params.toString() ? `?${params}` : ""}`);
  if (typeof refreshPower === "function") await refreshPower();
  try {
    state.tags = await api("GET", "/api/v1/tags");
  } catch (_error) {
    state.tags = state.tags || [];
  }
  state.salvos = await api("GET", "/api/v1/salvos");
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
    showBanner(error.message, true, error.existing);
  }
  render();
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
    methods: linkedMethods(data),
    reach_mode: data.reach_mode,
    reach_port: data.reach_port ? Number(data.reach_port) : null,
    reach_timeout: Number(data.reach_timeout || 30),
    wake_strategy: data.wake_strategy,
  };
  if (data.secureon) payload.secureon = data.secureon;
  return payload;
}

async function onClick(event) {
  if (event.target.closest("input, select, textarea, label")) return;
  const pageButton = event.target.closest("button[data-page], a[data-page]");
  if (pageButton) {
    await show(pageButton.dataset.page);
    return;
  }
  if (event.target.id === "new-device") {
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
      state.editing = id;
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
  $("setup").classList.add("hidden");
  $("login").classList.add("hidden");
  $("app").classList.remove("hidden");
  if (!state.page) await show("devices");
  if (state.booted) return;
  state.booted = true;
  window.setInterval(() => {
    if (state.page !== "devices" || !state.token || state.editing || state.focus) return;
    refreshDevices().then(() => {
      if (!state.editing && !state.focus && state.page === "devices") render();
    }).catch(() => {});
  }, 10000);
}

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
  await api("DELETE", `/api/v1/credential-profiles/${el.dataset.id}`);
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
  const box = event.target.closest && event.target.closest(".select-record");
  if (!box) return;
  const item = { kind: box.dataset.kind, id: Number(box.dataset.id) };
  state.selection = (state.selection || []).filter((row) => !(row.kind === item.kind && Number(row.id) === item.id));
  if (box.checked) state.selection.push(item);
});

document.body.addEventListener("click", (event) => {
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
    const key = tag.toLowerCase();
    const has = (state.tagFilter || []).some((item) => item.toLowerCase() === key);
    state.tagFilter = has
      ? state.tagFilter.filter((item) => item.toLowerCase() !== key)
      : [...(state.tagFilter || []), tag];
    refreshDevices().then(() => render()).catch((error) => showBanner(error.message, true, error.existing));
    return;
  }
  if (event.target.id === "back-inventory") {
    state.focus = null;
    render();
    return;
  }
  const save = event.target.closest("[data-save]");
  if (save && window.saveHardware) {
    window.saveHardware(save).catch((error) => showBanner(error.message, true, error.existing));
    return;
  }
  const field = event.target.closest("input, select, textarea, label");
  if (field && !event.target.closest("button, a")) return;
  const opener = event.target.closest("[data-open-kind]");
  if (opener) {
    const kind = opener.dataset.openKind;
    const id = Number(opener.dataset.id);
    state.editing = null;
    if (kind === "device") {
      state.focus = null;
      state.editing = id;
      show("devices").catch((error) => showBanner(error.message, true, error.existing));
    } else {
      state.focus = { kind, id };
      show("devices").catch((error) => showBanner(error.message, true, error.existing));
    }
    return;
  }
  const nav = event.target.closest("button[data-page], a[data-page]");
  if (nav && nav.closest("aside")) {
    state.focus = null;
    show(nav.dataset.page).catch((error) => showBanner(error.message, true, error.existing));
    return;
  }
  const control = event.target.closest("button[data-cap], a[data-cap]");
  if (control && control.type !== "submit") {
    const handler = window.CONTROL_HANDLERS && window.CONTROL_HANDLERS[control.dataset.cap];
    if (handler) {
      Promise.resolve(handler(control)).catch((error) => showBanner(error.message, true, error.existing));
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
