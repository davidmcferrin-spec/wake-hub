state.scans = [];
state.scan = null;
state.power = { pdus: [], amts: [], jetkvms: [], plugs: [], ups: [], rokus: [] };

async function refreshScans() {
  state.scans = await api("GET", "/api/v1/scans");
  state.interfaces = await api("GET", "/api/v1/interfaces");
  if (state.scan) state.scan = await api("GET", `/api/v1/scans/${state.scan.id}`);
}

async function refreshPower() {
  state.power.pdus = await api("GET", "/api/v1/pdus");
  state.power.amts = await api("GET", "/api/v1/amt");
  state.power.jetkvms = await api("GET", "/api/v1/jetkvm");
  state.power.plugs = await api("GET", "/api/v1/plugs");
  state.power.ups = await api("GET", "/api/v1/ups");
  state.power.rokus = await api("GET", "/api/v1/rokus");
  state.power.profiles = await api("GET", "/api/v1/credential-profiles");
  state.allDevices = await api("GET", "/api/v1/devices");
}

function formatPairs(names) {
  if (!names) return "";
  return Object.keys(names).sort((a, b) => Number(a) - Number(b)).map((key) => `${key}=${names[key]}`).join(", ");
}

function deviceNamesText(names) {
  const text = formatPairs(names);
  return text ? `Names on the device: ${text}` : "No names have been read from the device yet.";
}

window.findHardware = function (kind, id) {
  const lists = {
    pdu: state.power.pdus,
    amt: state.power.amts,
    jetkvm: state.power.jetkvms,
    plug: state.power.plugs,
    ups: state.power.ups,
    roku: state.power.rokus,
  };
  return (lists[kind] || []).find((item) => item.id === Number(id)) || null;
};

window.hardwareKindLabel = function (kind) {
  return { pdu: "PDU", amt: "AMT", jetkvm: "JetKVM", plug: "Plug", ups: "UPS", roku: "Roku" }[kind] || "Hardware";
};

function hardwareFields(kind, record) {
  const current = record || {};
  const editing = Boolean(record);
  const shown = (name, fallback = "") => {
    const value = current[name];
    if (value == null || value === "") return escapeHtml(fallback);
    return escapeHtml(value);
  };
  const checked = (name) => (current[name] ? "checked" : "");
  const password = (name) => (editing
    ? `<input name="${name}" type="password" value="" placeholder="unchanged" autocomplete="new-password">`
    : `<input name="${name}" type="password" placeholder="Password" autocomplete="new-password">`);
  const choice = (name, options, selected) => {
    const items = options.map(([value, label]) => `<option value="${escapeHtml(value)}" ${String(selected ?? "") === String(value) ? "selected" : ""}>${escapeHtml(label)}</option>`).join("");
    return `<select name="${name}">${items}</select>`;
  };
  const name = `<label>Name<input name="name" required value="${shown("name")}"></label>`;
  const portFallback = kind === "ups" ? "161" : kind === "roku" ? "8060" : (kind === "pdu" || kind === "plug" ? "80" : "");
  const hostPort = `<div class="pair"><label>Host<input name="host" required value="${shown("host")}"></label><label>Port<input name="port" type="number" value="${shown("port", portFallback)}"></label></div>`;
  const tls = `<div class="pair"><label class="check"><input type="checkbox" name="use_tls" ${checked("use_tls")}> TLS</label><label class="check"><input type="checkbox" name="insecure_tls" ${checked("insecure_tls")}> Allow self-signed certificate</label></div>`;
  const login = `<div class="pair"><label>Username<input name="username" value="${shown("username", editing ? "" : "admin")}"></label><label>Password${password("password")}</label></div>`;
  const profiles = (state.power && state.power.profiles) || [];
  const computers = state.allDevices || state.devices || [];
  const recordSelect = (field, rows, selected) => choice(field, [["", "None"], ...rows.map((row) => [String(row.id), row.name])], selected ?? "");
  const saved = `<label>Saved login${recordSelect("credential_profile_id", profiles, current.credential_profile_id)}</label>`;
  const tagText = editing ? (current.tags || []).map((tag) => (String(tag).startsWith("#") ? tag : `#${tag}`)).join(" ") : "";
  const tagsField = `<label>Tags<input name="tags" value="${escapeHtml(tagText)}" placeholder="#Office #TV"></label>`;
  const linked = `<label>Linked device${recordSelect("device_id", computers, current.device_id)}</label>`;
  if (kind === "pdu") {
    const names = editing ? escapeHtml(formatPairs(current.outlet_names)) : "";
    const fromDevice = editing
      ? `<p class="sub device-names">${escapeHtml(deviceNamesText(current.device_outlet_names))}</p>`
      : `<p class="sub">Outlet names are read from the PDU when it is added.</p>`;
    return `${name}${hostPort}${tls}${login}${fromDevice}<label>Local outlet names<input name="outlet_names" value="${names}" placeholder="1=NAS, 2=Desk"></label>${saved}${tagsField}`;
  }
  if (kind === "roku") {
    const help = editing ? "" : `<button type="button" class="ghost icon-button" id="roku-help" aria-expanded="false" aria-controls="roku-help-text">Info</button><p id="roku-help-text" class="sub hidden">Control by mobile apps must be enabled on the TV. Some models need network standby turned on to power back on.</p>`;
    return `${name}${hostPort}${help}${linked}${tagsField}`;
  }
  if (kind === "amt") return `${name}${hostPort}${tls}${login}<div class="pair">${linked}${saved}</div>${tagsField}`;
  if (kind === "jetkvm") {
    const extension = choice("extension", [["", "Not set"], ["atx-power", "ATX"], ["dc-power", "DC"]], current.extension || "");
    const user = `<div class="pair"><label>Username<input name="username" value="${shown("username")}"></label><label>Password${password("password")}</label></div>`;
    return `${name}${hostPort}${tls}<div class="pair"><label>Extension${extension}</label><label class="check"><input type="checkbox" name="poll_metrics" ${checked("poll_metrics")}> Poll DC metrics</label></div>${user}<div class="pair">${linked}${saved}</div>${tagsField}`;
  }
  if (kind === "plug") {
    const plugKind = choice("kind", [["shelly", "Shelly"], ["kasa", "Kasa"]], current.kind || "shelly");
    const protocol = choice("protocol", [["auto", "Auto"], ["xor", "XOR 9999"], ["klap", "KLAP"]], current.protocol || "auto");
    const user = `<div class="pair"><label>Username<input name="username" value="${shown("username")}"></label><label>Password${password("password")}</label></div>`;
    const switchId = `<label>Switch<input name="switch_id" type="number" value="${shown("switch_id", "0")}"></label>`;
    return `${name}${hostPort}<div class="pair"><label>Kind${plugKind}</label><label>Protocol${protocol}</label></div><label class="check"><input type="checkbox" name="insecure_tls" ${checked("insecure_tls")}> Allow self-signed certificate</label>${user}<div class="pair">${switchId}${linked}</div>${saved}${tagsField}`;
  }
  const version = choice("snmp_version", [["1", "SNMP v1"], ["2c", "SNMP v2c"], ["3", "SNMP v3"]], current.snmp_version || "2c");
  const authProto = choice("v3_auth_proto", [["sha", "sha"], ["md5", "md5"], ["none", "none"]], current.v3_auth_proto || "sha");
  const privProto = choice("v3_priv_proto", [["aes", "aes"], ["des", "des"], ["none", "none"]], current.v3_priv_proto || "aes");
  const community = editing
    ? `<input name="community" type="password" value="" placeholder="unchanged" autocomplete="new-password">`
    : `<input name="community" value="public">`;
  const identity = `<div class="pair"><label>Username<input name="v3_user" value="${shown("v3_user")}"></label><label>Community${community}</label></div>`;
  const secrets = `<div class="pair"><label>Password${password("v3_auth")}</label><label>Privacy password${password("v3_priv")}</label></div>`;
  return `${name}${hostPort}<label>SNMP version${version}</label>${identity}${secrets}<div class="pair"><label>Auth protocol${authProto}</label><label>Privacy protocol${privProto}</label></div><div class="pair">${linked}${saved}</div>${tagsField}`;
}

const HARDWARE_FIELDS = {
  pdu: "credential_profile_id,host,insecure_tls,name,outlet_names,password,port,tags,use_tls,username",
  amt: "credential_profile_id,device_id,host,insecure_tls,name,password,port,tags,use_tls,username",
  jetkvm: "credential_profile_id,device_id,extension,host,insecure_tls,name,password,poll_metrics,port,tags,use_tls,username",
  plug: "credential_profile_id,device_id,host,insecure_tls,kind,name,password,port,protocol,switch_id,tags,username",
  ups: "community,credential_profile_id,device_id,host,name,port,snmp_version,tags,v3_auth,v3_auth_proto,v3_priv,v3_priv_proto,v3_user",
  roku: "device_id,host,name,port,tags",
};

window.hardwareEditor = function (kind, record) {
  const cap = { pdu: "update_pdu", amt: "update_amt", jetkvm: "update_jetkvm", plug: "update_plug", ups: "update_ups", roku: "update_roku" }[kind];
  const path = { pdu: "pdus", amt: "amt", jetkvm: "jetkvm", plug: "plugs", ups: "ups", roku: "rokus" }[kind];
  const reread = kind === "pdu"
    ? `<button type="button" data-cap="refresh_pdu_outlet_names" data-fields="" data-id="${record.id}">Re-read from device</button>`
    : "";
  return `<form class="hardware-edit hardware-form editor">
    ${hardwareFields(kind, record)}
    <div class="row-actions">
      <button type="button" data-save="1" data-cap="${cap}" data-fields="${HARDWARE_FIELDS[kind]}" data-id="${record.id}" data-path="${path}">Save</button>
      <button type="button" class="danger delete" data-cap="${{ pdu: "remove_pdu", amt: "remove_amt", jetkvm: "remove_jetkvm", plug: "remove_plug", ups: "remove_ups", roku: "remove_roku" }[kind]}" data-fields="" data-id="${record.id}">Delete ${escapeHtml(record.name)}</button>
      ${reread}
    </div>
  </form>`;
};

function payloadFrom(form) {
  const payload = {};
  const data = Object.fromEntries(new FormData(form).entries());
  for (const [key, value] of Object.entries(data)) {
    if (key === "password" || key === "v3_auth" || key === "v3_priv" || (key === "community" && value === "")) {
      if (value !== "") payload[key] = value;
      continue;
    }
    payload[key] = value;
  }
  for (const key of ["use_tls", "insecure_tls", "poll_metrics"]) {
    const box = form.elements[key];
    if (box && box.type === "checkbox") payload[key] = box.checked;
  }
  if (form.elements.outlet_names) {
    const names = {};
    String(form.elements.outlet_names.value || "").split(",").forEach((part) => {
      const splitAt = part.indexOf("=");
      if (splitAt <= 0) return;
      const num = part.slice(0, splitAt).trim();
      const label = part.slice(splitAt + 1).trim();
      if (num && label) names[num] = label;
    });
    payload.outlet_names = names;
  }
  if (form.elements.tags) {
    payload.tags = String(form.elements.tags.value || "").split(/[\s,]+/).map((item) => item.trim()).filter(Boolean);
  }
  for (const key of ["port", "device_id", "switch_id", "credential_profile_id"]) {
    if (!form.elements[key]) continue;
    const raw = String(form.elements[key].value || "").trim();
    if (key === "switch_id") payload[key] = raw === "" ? 0 : Number(raw);
    else payload[key] = raw === "" ? null : Number(raw);
  }
  return payload;
}

window.saveHardware = async function (button) {
  const form = button.closest("form");
  if (!form) return;
  try {
    await api("PATCH", `/api/v1/${button.dataset.path}/${button.dataset.id}`, payloadFrom(form));
    await refreshPower();
    if (state.page === "power") renderPower();
    if (state.page === "devices") render();
    showBanner("Saved");
  } catch (error) {
    showBanner(error.message, true, error.existing);
  }
};

function renderScan() {
  const typed = document.getElementById("cidr");
  const kept = typed ? typed.value : "";
  const interfaces = state.interfaces || [];
  const primary = interfaces.find((item) => item.primary) || interfaces[0];
  const cidrValue = kept || (primary ? primary.cidr : "");
  const options = interfaces.map((item) => `<option value="${escapeHtml(item.cidr)}"${item.primary ? " selected" : ""}>${escapeHtml(item.name)} ${escapeHtml(item.cidr)}</option>`).join("");
  const picker = interfaces.length > 1
    ? `<label>Subnet <select id="cidr-pick" aria-label="Choose a subnet">${options}</select></label>`
    : "";
  const hosts = state.scan ? state.scan.hosts : [];
  const groups = {};
  hosts.forEach((host) => {
    const suggestion = (host.detail && host.detail.suggestion) || { type: "unknown", confidence: "low", reason: "", prefill: { kind: "device" } };
    const key = suggestion.type || "unknown";
    (groups[key] ||= []).push({ host, suggestion });
  });
  const sections = Object.keys(groups).sort().map((key) => {
    const cards = groups[key].map(({ host, suggestion }) => {
      const matches = host.matches || (host.known ? [host.known] : []);
      const addKind = (suggestion.prefill && suggestion.prefill.kind) || "device";
      const blocked = matches.filter((item) => item.kind === addKind);
      const known = matches.length
        ? matches.map((item) => `Already a ${item.kind}: ${item.name}`).join("; ")
        : "New";
      const links = matches.map((item) => `<button type="button" class="ghost" data-open-kind="${escapeHtml(item.kind)}" data-id="${item.id}">Open ${escapeHtml(item.name)}</button>`).join("");
      const attach = host.attach;
      const addLabel = attach ? attach.label : "Add";
      const add = blocked.length ? "" : `<button type="button" class="ghost" data-cap="add_from_scan" data-fields="community,device_id,kind,name,password,plug_kind,username" data-scan="${state.scan.id}" data-host="${host.id}" data-kind="${escapeHtml(addKind)}" data-device-id="${attach ? attach.device_id : ""}" data-plug-kind="${escapeHtml((suggestion.prefill && suggestion.prefill.plug_kind) || "")}">${escapeHtml(addLabel)}</button>`;
      return `
      <article class="card">
        <header><h2>${escapeHtml(host.ip)}</h2><span class="pill">${escapeHtml(suggestion.confidence || "")}</span></header>
        <p class="meta">${escapeHtml(host.hostname || "")} ${escapeHtml(host.vendor || "unknown vendor")} · ${escapeHtml(host.mac || "no MAC")} · ${escapeHtml(known)}</p>
        <p class="sub">${escapeHtml(suggestion.reason || "")}</p>
        <div class="row-actions">${links}${add}</div>
      </article>`;
    }).join("");
    return `<section><h2>${escapeHtml(key)}</h2><div class="grid">${cards}</div></section>`;
  }).join("");
  const scans = state.scans.map((scan) => `
    <div class="row-actions">
      <button type="button" class="ghost" data-cap="scan_results" data-fields="" data-id="${scan.id}">${escapeHtml(scan.cidr)} · ${escapeHtml(scan.status)} ${scan.progress}/${scan.total}</button>
      <button type="button" data-cap="rescan" data-fields="replace" data-id="${scan.id}" data-replace="1">Re-scan</button>
      <button type="button" class="danger" data-cap="delete_scan" data-fields="" data-id="${scan.id}">Delete</button>
    </div>
  `).join("");
  $("view").innerHTML = `
    <p class="lede">Scan finds machines on your network. Deleting a scan does not delete devices you already added.</p>
    <form id="scan-form" class="toolbar">
      ${picker}
      <label>CIDR <input id="cidr" name="cidr" value="${escapeHtml(cidrValue)}" aria-label="CIDR"></label>
      <label class="check"><input type="checkbox" name="replace"> Replace earlier results for this subnet</label>
      <button type="submit" data-cap="scan_subnet" data-fields="cidr,replace">Scan subnet</button>
      <button type="button" class="ghost" data-cap="list_interfaces" data-fields="">Refresh subnets</button>
      <button type="button" class="danger" data-cap="clear_scans" data-fields="confirm">Clear scan history</button>
    </form>
    <div class="stack">${scans || ""}</div>
    ${sections || `<div class="empty"><p>No scans yet. Enter your network, such as 192.168.1.0/24, and scan.</p></div>`}`
  const pick = $("cidr-pick");
  if (pick) pick.addEventListener("change", () => { $("cidr").value = pick.value; });
}

function outletShown(outlet) {
  const wanted = (typeof state !== "undefined" && state.tagFilter) || [];
  if (!wanted.length) return true;
  const owned = (outlet.tags || []).map((tag) => String(tag).toLowerCase());
  return wanted.every((tag) => owned.includes(String(tag).toLowerCase()));
}

function outletRow(pduId, outlet) {
  if (!outletShown(outlet)) return "";
  const stateText = outlet.on === true ? "on" : outlet.on === false ? "off" : "state unknown";
  const tags = (outlet.tags || []).join(" ");
  return `<div class="row-actions outlet-line" data-outlet-row="${outlet.number}">
    <span>${escapeHtml(outlet.name)} · ${escapeHtml(stateText)}</span>
    <button type="button" data-cap="set_pdu_outlet" data-fields="action,confirm" data-pdu="${pduId}" data-outlet="${outlet.number}" data-action="on">On</button>
    <button type="button" class="danger" data-cap="set_pdu_outlet" data-fields="action,confirm" data-pdu="${pduId}" data-outlet="${outlet.number}" data-action="off">Off</button>
    <button type="button" class="danger" data-cap="set_pdu_outlet" data-fields="action,confirm" data-pdu="${pduId}" data-outlet="${outlet.number}" data-action="cycle">Cycle</button>
    <input class="outlet-tags" value="${escapeHtml(tags)}" aria-label="Tags for ${escapeHtml(outlet.name)}">
    <button type="button" data-cap="update_pdu_outlet" data-fields="tags" data-pdu="${pduId}" data-outlet="${outlet.number}">Save tags</button>
  </div>`;
}

window.loadLivePdus = async function () {
  const nodes = [...document.querySelectorAll("[data-pdu-live]")];
  await Promise.all(nodes.map(async (node) => {
    const id = node.dataset.pduLive;
    const bank = document.getElementById(`pdu-bank-${id}`);
    try {
      const data = await api("GET", `/api/v1/pdus/${id}/outlets`);
      if (bank) bank.textContent = `Bank current ${(data.bank_amps || []).map((value) => `${value} A`).join(", ") || "unknown"}.`;
      const rows = (data.outlets || []).map((outlet) => outletRow(id, outlet)).join("") || `<p class="sub">No outlets stored yet.</p>`;
      const summary = node.querySelector("summary");
      if (summary) {
        node.innerHTML = "";
        node.append(summary);
        node.insertAdjacentHTML("beforeend", rows);
      } else node.innerHTML = rows;
    } catch (error) {
      if (bank) bank.textContent = error.message;
    }
  }));
};

function statusPill(key, label) {
  const extra = key.startsWith("amt-") ? ` id="amt-status-${key.slice(4)}"` : "";
  return `<span class="pill off"${extra} data-live-status="${key}">${escapeHtml(label)}</span>`;
}

window.hardwareControls = function (kind, item, full) {
  const id = item.id;
  if (kind === "amt") {
    const more = full ? `
        <button type="button" class="danger" data-cap="amt_power" data-fields="action,confirm" data-id="${id}" data-action="off_hard">Off hard</button>
        <button type="button" class="danger" data-cap="amt_power" data-fields="action,confirm" data-id="${id}" data-action="cycle">Power cycle</button>
        <button type="button" class="ghost" data-cap="amt_power_state" data-fields="" data-id="${id}">Read status</button>` : `
        <button type="button" class="ghost" data-cap="amt_power_state" data-fields="" data-id="${id}">Status</button>`;
    return `
      ${statusPill(`amt-${id}`, "Checking")}
      <div class="row-actions">
        <button type="button" class="primary" data-cap="amt_power" data-fields="action,confirm" data-id="${id}" data-action="on">Power on</button>
        <button type="button" class="danger" data-cap="amt_power" data-fields="action,confirm" data-id="${id}" data-action="shutdown">Off</button>
        <button type="button" class="danger" data-cap="amt_power" data-fields="action,confirm" data-id="${id}" data-action="reboot">Reset</button>
        ${more}
      </div>`;
  }
  if (kind === "pdu") {
    const rows = (item.outlets || []).map((outlet) => outletRow(id, outlet)).join("");
    return `
      ${statusPill(`pdu-${id}`, "Checking")}
      <details class="outlets" id="pdu-${id}" data-pdu-live="${id}">
        <summary>Outlets</summary>
        ${rows || `<p class="sub">No outlets stored yet.</p>`}
      </details>`;
  }
  if (kind === "jetkvm") {
    const more = full ? `
        <button type="button" class="ghost" data-cap="jetkvm_status" data-fields="" data-id="${id}">Read status</button>
        <button type="button" class="ghost" data-cap="jetkvm_power" data-fields="action,confirm,extension" data-id="${id}" data-action="dc-on" data-extension="dc-power">DC on</button>
        <button type="button" class="danger" data-cap="jetkvm_power" data-fields="action,confirm,extension" data-id="${id}" data-action="dc-off" data-extension="dc-power">DC off</button>
        <a class="ghost" data-cap="jetkvm_console" data-fields="" href="${escapeHtml(item.console_url || "")}" target="_blank" rel="noopener">Open console</a>` : `
        <button type="button" class="ghost" data-cap="jetkvm_status" data-fields="" data-id="${id}">Status</button>`;
    return `
      ${statusPill(`jetkvm-${id}`, "Checking")}
      <div class="row-actions">
        <button type="button" class="primary" data-cap="jetkvm_power" data-fields="action,confirm,extension" data-id="${id}" data-action="power-short">Power</button>
        <button type="button" class="danger" data-cap="jetkvm_power" data-fields="action,confirm,extension" data-id="${id}" data-action="power-long">Off</button>
        <button type="button" class="danger" data-cap="jetkvm_power" data-fields="action,confirm,extension" data-id="${id}" data-action="reset">Reset</button>
        ${more}
      </div>`;
  }
  if (kind === "plug") {
    const more = full ? `
        <button type="button" class="ghost" data-cap="plug_status" data-fields="" data-id="${id}">Read status</button>
        <button type="button" class="ghost" data-cap="plug_power" data-fields="action,confirm,cycle_seconds" data-id="${id}" data-action="toggle">Toggle</button>
        <button type="button" class="danger" data-cap="plug_power" data-fields="action,confirm,cycle_seconds" data-id="${id}" data-action="cycle">Cycle</button>` : `
        <button type="button" class="ghost" data-cap="plug_status" data-fields="" data-id="${id}">Status</button>`;
    return `
      ${statusPill(`plug-${id}`, "Checking")}
      <div class="row-actions">
        <button type="button" class="primary" data-cap="plug_power" data-fields="action,confirm,cycle_seconds" data-id="${id}" data-action="on">On</button>
        <button type="button" class="danger" data-cap="plug_power" data-fields="action,confirm,cycle_seconds" data-id="${id}" data-action="off">Off</button>
        ${more}
      </div>`;
  }
  if (kind === "ups") {
    const more = full ? `
        <label class="sub">Delay <input class="ups-delay" name="delay_seconds" type="number" placeholder="seconds" aria-label="Delay seconds"></label>
        <button type="button" class="primary" data-cap="ups_action" data-fields="action,confirm,delay_seconds,outlet" data-id="${id}" data-action="turn_on">Turn on</button>
        <button type="button" class="danger" data-cap="ups_action" data-fields="action,confirm,delay_seconds,outlet" data-id="${id}" data-action="shutdown">Shutdown</button>
        <button type="button" class="danger" data-cap="ups_action" data-fields="action,confirm,delay_seconds,outlet" data-id="${id}" data-action="reboot">Reboot</button>
        <button type="button" class="danger" data-cap="ups_action" data-fields="action,confirm,delay_seconds,outlet" data-id="${id}" data-action="turn_off">Turn off</button>` : "";
    return `
      ${statusPill(`ups-${id}`, "Checking")}
      <div class="row-actions">
        <button type="button" class="ghost" data-cap="ups_status" data-fields="" data-id="${id}">Status</button>
        <label class="sub">Bank <input class="ups-outlet" name="outlet" type="number" placeholder="bank" aria-label="Outlet bank"></label>
        <button type="button" class="primary" data-cap="ups_action" data-fields="action,confirm,delay_seconds,outlet" data-id="${id}" data-action="outlet_on">Bank on</button>
        <button type="button" class="danger" data-cap="ups_action" data-fields="action,confirm,delay_seconds,outlet" data-id="${id}" data-action="outlet_off">Bank off</button>
        ${more}
      </div>`;
  }
  if (kind === "roku") {
    return `
      ${statusPill(`roku-${id}`, "Checking")}
      <div class="row-actions">
        <button type="button" class="primary" data-cap="roku_power" data-fields="action,confirm" data-id="${id}" data-action="on">On</button>
        <button type="button" class="danger" data-cap="roku_power" data-fields="action,confirm" data-id="${id}" data-action="off">Off</button>
        <button type="button" class="ghost" data-cap="roku_power" data-fields="action,confirm" data-id="${id}" data-action="toggle">Toggle</button>
        <button type="button" class="ghost" data-cap="roku_status" data-fields="" data-id="${id}">Status</button>
      </div>`;
  }
  return "";
};

window.loadOperateStatus = async function () {
  const nodes = [...document.querySelectorAll("[data-live-status]")];
  await Promise.all(nodes.map(async (node) => {
    const [kind, id] = String(node.dataset.liveStatus).split("-");
    const path = { roku: "rokus", plug: "plugs", ups: "ups", amt: "amt", jetkvm: "jetkvm" }[kind];
    if (!path) return;
    try {
      const data = await api("GET", `/api/v1/${path}/${id}/status`);
      let label = "Ready";
      if (kind === "roku") {
        const mode = data.power_mode || "";
        label = mode === "PowerOn" ? "On" : mode === "DisplayOff" || mode === "Ready" ? "Standby" : mode === "Suspend" || mode === "Headless" ? "Off" : "Unreachable";
      } else if (kind === "plug") label = data.on ? "On" : "Off";
      node.textContent = label;
      node.className = label === "On" || label === "Ready" ? "pill up" : label === "Off" ? "pill down" : label === "Standby" ? "pill off" : "pill bad";
    } catch (_error) {
      node.textContent = "Unreachable";
      node.className = "pill bad";
    }
  }));
};

function renderPower() {
  const profiles = (state.power.profiles || []).map((item, index) => window.recordCard({
    kind: "login",
    id: item.id,
    name: item.name,
    check: false,
    open: false,
    meta: `${item.username || "no username"} · ${item.password_set ? "password stored" : "no password"}`,
    primary: index === 0 ? `<button type="button" class="ghost" data-cap="update_credential_profile" data-fields="name,password,username" data-id="${item.id}">Replace this login</button>` : "",
    more: `<button type="button" class="danger delete" data-cap="remove_credential_profile" data-fields="force" data-id="${item.id}">Delete</button>`,
  })).join("");
  const pduCards = state.power.pdus.map((pdu) => window.recordCard({
    kind: "pdu",
    id: pdu.id,
    name: pdu.name,
    meta: pdu.host,
    body: tagChips(pdu.tags),
    primary: `
      <button type="button" class="ghost" data-cap="update_pdu" data-fields="credential_profile_id,host,insecure_tls,name,outlet_names,password,port,tags,use_tls,username" data-id="${pdu.id}">Edit</button>
      <button type="button" class="ghost" data-cap="refresh_pdu_outlet_names" data-fields="" data-id="${pdu.id}">Refresh names from device</button>`,
    more: `
      <button type="button" class="ghost" data-cap="list_pdu_outlets" data-fields="" data-id="${pdu.id}" hidden>Show outlets</button>
      <button type="button" class="danger delete" data-cap="remove_pdu" data-fields="" data-id="${pdu.id}">Delete</button>`,
  })).join("");
  const amtCards = state.power.amts.map((item) => window.recordCard({
    kind: "amt",
    id: item.id,
    name: item.name,
    meta: `${item.host}:${item.port}`,
    body: tagChips(item.tags),
    primary: `<button type="button" class="ghost" data-cap="update_amt" data-fields="credential_profile_id,device_id,host,insecure_tls,name,password,port,tags,use_tls,username" data-id="${item.id}">Edit</button>`,
    more: `<button type="button" class="danger delete" data-cap="remove_amt" data-fields="" data-id="${item.id}">Delete</button>`,
  })).join("");
  const jetCards = state.power.jetkvms.map((item) => window.recordCard({
    kind: "jetkvm",
    id: item.id,
    name: item.name,
    meta: item.host,
    body: tagChips(item.tags),
    primary: `<button type="button" class="ghost" data-cap="update_jetkvm" data-fields="credential_profile_id,device_id,extension,host,insecure_tls,name,password,poll_metrics,port,tags,use_tls,username" data-id="${item.id}">Edit</button>`,
    more: `<button type="button" class="danger delete" data-cap="remove_jetkvm" data-fields="" data-id="${item.id}">Delete</button>`,
  })).join("");
  const plugCard = (item) => window.recordCard({
    kind: "plug",
    id: item.id,
    name: item.name,
    meta: `${item.kind} · ${item.host}`,
    body: tagChips(item.tags),
    primary: `<button type="button" class="ghost" data-cap="update_plug" data-fields="credential_profile_id,device_id,host,insecure_tls,kind,name,password,port,protocol,switch_id,tags,username" data-id="${item.id}">Edit</button>`,
    more: `<button type="button" class="danger delete" data-cap="remove_plug" data-fields="" data-id="${item.id}">Delete</button>`,
  });
  const shellyPlugs = state.power.plugs.filter((item) => item.kind !== "kasa");
  const kasaPlugs = state.power.plugs.filter((item) => item.kind === "kasa");
  const upsCards = state.power.ups.map((item) => window.recordCard({
    kind: "ups",
    id: item.id,
    name: item.name,
    meta: `SNMP ${item.snmp_version} · ${item.host}`,
    body: tagChips(item.tags),
    primary: `<button type="button" class="ghost" data-cap="update_ups" data-fields="community,credential_profile_id,device_id,host,name,port,snmp_version,tags,v3_auth,v3_auth_proto,v3_priv,v3_priv_proto,v3_user" data-id="${item.id}">Edit</button>`,
    more: `<button type="button" class="danger delete" data-cap="remove_ups" data-fields="" data-id="${item.id}">Delete</button>`,
  })).join("");
  const rokuCards = (state.power.rokus || []).map((item) => window.recordCard({
    kind: "roku",
    id: item.id,
    name: item.name,
    meta: `${item.host}:${item.port}`,
    body: tagChips(item.tags),
    primary: `<button type="button" class="ghost" data-cap="update_roku" data-fields="device_id,host,name,port,tags" data-id="${item.id}">Edit</button>`,
    more: `<button type="button" class="danger delete" data-cap="remove_roku" data-fields="" data-id="${item.id}">Delete</button>`,
  })).join("");
  const counts = {
    pdu: state.power.pdus.length,
    amt: state.power.amts.length,
    jetkvm: state.power.jetkvms.length,
    shelly: shellyPlugs.length,
    kasa: kasaPlugs.length,
    ups: state.power.ups.length,
    roku: (state.power.rokus || []).length,
  };
  const typeList = [
    ["pdu", "PDU"],
    ["amt", "AMT"],
    ["jetkvm", "JetKVM"],
    ["shelly", "Shelly"],
    ["kasa", "Kasa"],
    ["ups", "UPS"],
    ["roku", "Roku"],
  ];
  const allowed = ["all", ...typeList.map((item) => item[0])];
  let tab = state.hardwareTab || "all";
  if (!allowed.includes(tab)) tab = "all";
  state.hardwareTab = tab;
  const showType = (id) => tab === id || (tab === "all" && counts[id] > 0);
  const tabButton = (id, label, count) => {
    const selected = tab === id;
    return `<button type="button" class="ghost tab" role="tab" id="hw-tab-${id}" data-hw-tab="${id}" aria-selected="${selected}" aria-controls="hw-panel-${id}" tabindex="${selected ? "0" : "-1"}">${escapeHtml(label)}<span class="count">${count}</span></button>`;
  };
  const visibleTypes = typeList.filter(([id]) => counts[id] > 0 || tab === id);
  const hiddenTypes = typeList.filter(([id]) => counts[id] === 0 && tab !== id);
  const addType = hiddenTypes.length
    ? `<label class="add-type">Add type <select id="hw-add-type" aria-label="Add a hardware type"><option value="">Choose</option>${hiddenTypes.map(([id, label]) => `<option value="${id}">${escapeHtml(label)}</option>`).join("")}</select></label>`
    : "";
  const plugKind = tab === "kasa" || (tab === "all" && !counts.shelly && counts.kasa) ? "kasa" : "shelly";
  const plugCards = (tab === "kasa" ? kasaPlugs : tab === "shelly" ? shellyPlugs : state.power.plugs).map(plugCard).join("");
  const plugShown = tab === "shelly" || tab === "kasa" || (tab === "all" && (counts.shelly + counts.kasa) > 0);
  $("view").innerHTML = `
    <section class="panel" style="padding:1rem" data-cap="list_credential_profiles" data-fields="">
      <h2>Saved logins</h2>
      <p class="lede">A saved login is optional. Pick it when you add a box, instead of typing the password again.</p>
      <form id="profile-form" class="editor fields">
        <input name="name" placeholder="Name" required>
        <input name="username" placeholder="Username">
        <input name="password" type="password" placeholder="Password">
        <button type="submit" data-cap="add_credential_profile" data-fields="name,password,username">Save login</button>
      </form>
      <div class="grid">${profiles}</div>
    </section>
    <p class="lede">Hardware is where you add a box and set its address and login. Devices is where you turn things on and off.</p>
    <div id="hw-tabs" class="tablist" role="tablist" aria-label="Hardware types">
      ${tabButton("all", "All", Object.values(counts).reduce((sum, count) => sum + count, 0))}
      ${visibleTypes.map(([id, label]) => tabButton(id, label, counts[id])).join("")}
      ${addType}
    </div>
    <div id="hw-panel-all"></div>
    <section data-cap="list_pdus" data-fields="" id="hw-panel-pdu" role="tabpanel" aria-labelledby="hw-tab-pdu" class="${showType("pdu") ? "" : "hidden"}">
      <h2>PDU</h2>
      <p class="lede">A power strip. Outlet names are read from the device when you add it.</p>
      <button type="button" class="ghost" data-add-form="pdu-form">Add PDU</button>
      <form id="pdu-form" class="editor hardware-form hidden">
        ${hardwareFields("pdu", null)}
        <div class="row-actions">
          <button type="button" class="ghost" data-cap="test_target" data-fields="broadcast,community,confirm,host,insecure_tls,kind,mac,password,plug_kind,port,snmp_version,use_tls,username" data-kind="pdu">Test</button>
          <button type="submit" data-cap="add_pdu" data-fields="credential_profile_id,host,insecure_tls,name,outlet_names,password,port,tags,use_tls,username">Add PDU</button>
        </div>
      </form>
      <div class="grid">${pduCards}</div>
    </section>
    <section data-cap="list_amt" data-fields="" id="hw-panel-amt" role="tabpanel" aria-labelledby="hw-tab-amt" class="${showType("amt") ? "" : "hidden"}">
      <h2>AMT</h2>
      <p class="lede">Remote power for a vPro computer. The username and password belong to that computer.</p>
      <button type="button" class="ghost" data-add-form="amt-form">Add AMT</button>
      <form id="amt-form" class="editor hardware-form hidden">
        ${hardwareFields("amt", null)}
        <div class="row-actions">
          <button type="button" class="ghost" data-cap="test_target" data-fields="broadcast,community,confirm,host,insecure_tls,kind,mac,password,plug_kind,port,snmp_version,use_tls,username" data-kind="amt">Test</button>
          <button type="submit" data-cap="add_amt" data-fields="credential_profile_id,device_id,host,insecure_tls,name,password,port,tags,use_tls,username">Add AMT</button>
        </div>
      </form>
      <div class="grid">${amtCards}</div>
    </section>
    <section data-cap="list_jetkvm" data-fields="" id="hw-panel-jetkvm" role="tabpanel" aria-labelledby="hw-tab-jetkvm" class="${showType("jetkvm") ? "" : "hidden"}">
      <h2>JetKVM</h2>
      <p class="lede">A local keyboard and power button. Force off holds the button down.</p>
      <button type="button" class="ghost" data-add-form="jet-form">Add JetKVM</button>
      <form id="jet-form" class="editor hardware-form hidden">
        ${hardwareFields("jetkvm", null)}
        <div class="row-actions">
          <button type="button" class="ghost" data-cap="test_target" data-fields="broadcast,community,confirm,host,insecure_tls,kind,mac,password,plug_kind,port,snmp_version,use_tls,username" data-kind="jetkvm">Test</button>
          <button type="submit" data-cap="add_jetkvm" data-fields="credential_profile_id,device_id,extension,host,insecure_tls,name,password,poll_metrics,port,tags,use_tls,username">Add JetKVM</button>
        </div>
      </form>
      <div class="grid">${jetCards}</div>
    </section>
    <section data-cap="list_plugs" data-fields="" id="hw-panel-${plugKind}" role="tabpanel" aria-labelledby="hw-tab-${plugKind}" class="${plugShown ? "" : "hidden"}">
      <h2>${plugKind === "kasa" ? "Kasa" : "Shelly"}</h2>
      <p class="lede">A smart plug. Use its own login, or pick a saved one.</p>
      <button type="button" class="ghost" data-add-form="plug-form">Add plug</button>
      <form id="plug-form" class="editor hardware-form hidden">
        ${hardwareFields("plug", { kind: plugKind })}
        <div class="row-actions">
          <button type="button" class="ghost" data-cap="test_target" data-fields="broadcast,community,confirm,host,insecure_tls,kind,mac,password,plug_kind,port,snmp_version,use_tls,username" data-kind="plug">Test</button>
          <button type="submit" data-cap="add_plug" data-fields="credential_profile_id,device_id,host,insecure_tls,kind,name,password,port,protocol,switch_id,tags,username">Add plug</button>
        </div>
      </form>
      <div class="grid">${plugCards}</div>
    </section>
    <section data-cap="list_ups" data-fields="" id="hw-panel-ups" role="tabpanel" aria-labelledby="hw-tab-ups" class="${showType("ups") ? "" : "hidden"}">
      <h2>UPS</h2>
      <p class="lede">A battery backup. Shutdown and outlet-off ask you to confirm, because they can turn everything off.</p>
      <button type="button" class="ghost" data-add-form="ups-form">Add UPS</button>
      <form id="ups-form" class="editor hardware-form hidden">
        ${hardwareFields("ups", null)}
        <div class="row-actions">
          <button type="button" class="ghost" data-cap="test_target" data-fields="broadcast,community,confirm,host,insecure_tls,kind,mac,password,plug_kind,port,snmp_version,use_tls,username" data-kind="ups">Test</button>
          <button type="submit" data-cap="add_ups" data-fields="community,credential_profile_id,device_id,host,name,port,snmp_version,tags,v3_auth,v3_auth_proto,v3_priv,v3_priv_proto,v3_user">Add UPS</button>
        </div>
      </form>
      <div class="grid">${upsCards}</div>
      <button type="button" class="ghost" data-cap="list_metrics" data-fields="device_id,limit,metric,source_id,source_kind">Refresh readings</button>
    </section>
    <section data-cap="list_rokus" data-fields="" id="hw-panel-roku" role="tabpanel" aria-labelledby="hw-tab-roku" class="${showType("roku") ? "" : "hidden"}">
      <h2>Roku</h2>
      <p class="lede">A Roku on your network.</p>
      <button type="button" class="ghost" data-add-form="roku-form">Add Roku</button>
      <form id="roku-form" class="editor hardware-form hidden">
        ${hardwareFields("roku", null)}
        <div class="row-actions">
          <button type="button" class="ghost" data-cap="test_target" data-fields="broadcast,community,confirm,host,insecure_tls,kind,mac,password,plug_kind,port,snmp_version,use_tls,username" data-kind="roku">Test</button>
          <button type="submit" data-cap="add_roku" data-fields="device_id,host,name,port,tags">Add Roku</button>
        </div>
      </form>
      <div class="grid">${rokuCards}</div>
    </section>`;
  wireHardwareTabs();
}

function selectHardwareTab(id) {
  state.hardwareTab = id;
  try { localStorage.setItem("wakehub-hardware-tab", id); } catch (_error) { /* private mode */ }
  writeRoute("power", id === "all" ? "" : id);
  renderPower();
  const selected = document.getElementById(`hw-tab-${id}`);
  if (selected) selected.focus();
}

function wireHardwareTabs() {
  const list = document.getElementById("hw-tabs");
  if (!list) return;
  list.querySelectorAll("[data-hw-tab]").forEach((button) => {
    button.addEventListener("click", () => selectHardwareTab(button.dataset.hwTab));
  });
  list.addEventListener("keydown", (event) => {
    if (!["ArrowRight", "ArrowLeft", "Home", "End"].includes(event.key)) return;
    const tabs = [...list.querySelectorAll("[role=tab]")];
    const index = Math.max(0, tabs.indexOf(document.activeElement));
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
    if (event.key === "ArrowLeft") next = (index + tabs.length - 1) % tabs.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = tabs.length - 1;
    event.preventDefault();
    tabs[next].focus();
    selectHardwareTab(tabs[next].dataset.hwTab);
  });
  const menu = document.getElementById("hw-add-type");
  if (menu) {
    menu.addEventListener("change", () => {
      if (menu.value) selectHardwareTab(menu.value);
    });
  }
}

function sparkline(rows) {
  const values = rows.map((row) => Number(row.value)).filter((value) => Number.isFinite(value)).reverse();
  if (!values.length) return "";
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const points = values.map((value, index) => {
    const x = (index / Math.max(values.length - 1, 1)) * 240;
    const y = 48 - ((value - min) / span) * 40;
    return `${x},${y}`;
  }).join(" ");
  return `<svg viewBox="0 0 240 56" width="240" height="56"><polyline fill="none" stroke="#0e6b4f" stroke-width="2" points="${points}"></polyline></svg>`;
}

window.handlePowerCap = async function handlePowerCap(button) {
  const cap = button.dataset.cap;
  const id = Number(button.dataset.id);
  const known = ["scan_results", "add_from_scan", "delete_scan", "clear_scans", "rescan", "list_pdu_outlets", "set_pdu_outlet", "update_pdu_outlet", "refresh_pdu_outlet_names", "update_pdu", "remove_pdu", "amt_power_state", "amt_power", "update_amt", "remove_amt", "jetkvm_status", "jetkvm_power", "update_jetkvm", "remove_jetkvm", "plug_status", "plug_power", "update_plug", "remove_plug", "ups_status", "ups_action", "update_ups", "remove_ups", "roku_status", "roku_power", "update_roku", "remove_roku", "list_metrics"];
  if (!known.includes(cap)) return false;
  try {
    if (cap === "scan_results") {
      state.scan = await api("GET", `/api/v1/scans/${id}`);
    } else if (cap === "delete_scan") {
      if (!window.confirm("Delete this scan? Devices already added stay in the inventory.")) return true;
      await api("DELETE", `/api/v1/scans/${id}`);
      if (state.scan && state.scan.id === id) state.scan = null;
      await refreshScans();
      showBanner("Scan deleted");
    } else if (cap === "clear_scans") {
      if (!window.confirm("Clear all scan history? Devices already added stay in the inventory.")) return true;
      const result = await api("POST", "/api/v1/scans/clear", { confirm: true });
      state.scan = null;
      await refreshScans();
      showBanner(`Cleared ${result.removed} scans`);
    } else if (cap === "rescan") {
      const replace = button.dataset.replace !== "0";
      state.scan = await api("POST", `/api/v1/scans/${id}/rescan`, { replace });
      showBanner(replace ? "Re-scan started. Earlier results for this subnet were removed." : "Re-scan started. Earlier results were kept.");
      window.setTimeout(async () => {
        await refreshScans();
        if (state.scan) state.scan = await api("GET", `/api/v1/scans/${state.scan.id}`);
        if (state.page === "scan") renderScan();
      }, 1200);
    } else if (cap === "add_from_scan") {
      const body = { kind: button.dataset.kind };
      if (button.dataset.plugKind) body.plug_kind = button.dataset.plugKind;
      if (button.dataset.deviceId) body.device_id = Number(button.dataset.deviceId);
      if (body.kind === "amt") {
        const password = window.prompt("AMT password");
        if (!password) return true;
        body.password = password;
      }
      await api("POST", `/api/v1/scans/${button.dataset.scan}/hosts/${button.dataset.host}/add`, body);
      showBanner("Added from scan");
    } else if (cap === "list_pdu_outlets") {
      const data = await api("GET", `/api/v1/pdus/${id}/outlets`);
      const slot = document.getElementById(`pdu-${id}`);
      if (slot) {
        slot.innerHTML = data.outlets.map((outlet) => `
          <div class="row-actions">
            <span>${escapeHtml(outlet.name)} ${outlet.on ? "on" : "off"}</span>
            <button type="button" data-cap="set_pdu_outlet" data-fields="action,confirm" data-pdu="${id}" data-outlet="${outlet.number}" data-action="on">On</button>
            <button type="button" class="danger" data-cap="set_pdu_outlet" data-fields="action,confirm" data-pdu="${id}" data-outlet="${outlet.number}" data-action="off">Off</button>
            <button type="button" class="danger" data-cap="set_pdu_outlet" data-fields="action,confirm" data-pdu="${id}" data-outlet="${outlet.number}" data-action="reboot">Reboot</button>
          </div>`).join("") + `<p class="sub">Bank current ${escapeHtml((data.bank_amps || []).join(" A, "))} A. Not per outlet.</p>`;
      }
      return true;
    } else if (cap === "update_pdu_outlet") {
      const row = button.closest("[data-outlet-row]");
      const raw = row && row.querySelector(".outlet-tags") ? row.querySelector(".outlet-tags").value : "";
      const tags = String(raw).split(/[\s,]+/).map((item) => item.trim()).filter(Boolean);
      await api("PATCH", `/api/v1/pdus/${button.dataset.pdu}/outlets/${button.dataset.outlet}`, { tags });
      showBanner("Outlet tags saved");
      return true;
    } else if (cap === "set_pdu_outlet") {
      const action = button.dataset.action;
      if ((action === "off" || action === "reboot" || action === "cycle") && !window.confirm(action === "off" ? "Turn this outlet off?" : "Cycle this outlet?")) return true;
      await api("POST", `/api/v1/pdus/${button.dataset.pdu}/outlets/${button.dataset.outlet}`, { action, confirm: action !== "on" });
    } else if (cap === "remove_pdu" || cap === "remove_amt" || cap === "remove_jetkvm" || cap === "remove_plug" || cap === "remove_ups" || cap === "remove_roku") {
      const kind = { remove_pdu: "pdu", remove_amt: "amt", remove_jetkvm: "jetkvm", remove_plug: "plug", remove_ups: "ups", remove_roku: "roku" }[cap];
      await window.confirmDelete([{ kind, id }], []);
      return true;
    } else if (cap === "amt_power_state") {
      const slot = document.getElementById(`amt-status-${id}`);
      try {
        const data = await api("GET", `/api/v1/amt/${id}/power`);
        const text = `${data.name || "AMT"} is ${data.power_name || "unknown"}`;
        if (slot) slot.textContent = text;
        showBanner(text);
      } catch (error) {
        if (slot) slot.textContent = error.message;
        throw error;
      }
      return true;
    } else if (cap === "amt_power") {
      const action = button.dataset.action;
      const destructive = action !== "on";
      if (destructive && !window.confirm(`Confirm AMT ${action}?`)) return true;
      const data = await api("POST", `/api/v1/amt/${id}/power`, { action, confirm: destructive });
      const slot = document.getElementById(`amt-status-${id}`);
      const text = `${data.name || "AMT"} ${action}`;
      if (slot) slot.textContent = text;
      showBanner(text);
      return true;
    } else if (cap === "jetkvm_status") {
      const data = await api("GET", `/api/v1/jetkvm/${id}/status`);
      showBanner(data.reachable ? "JetKVM reachable" : "JetKVM did not answer");
    } else if (cap === "jetkvm_power") {
      const action = button.dataset.action;
      const destructive = action === "power-long" || action === "reset" || action === "dc-off";
      if (destructive && !window.confirm("Confirm JetKVM " + action + "?")) return true;
      await api("POST", `/api/v1/jetkvm/${id}/power`, { action, confirm: destructive, extension: button.dataset.extension || "auto" });
    } else if (cap === "plug_status") {
      const data = await api("GET", `/api/v1/plugs/${id}/status`);
      showBanner(data.on ? "Plug on" : "Plug off");
    } else if (cap === "plug_power") {
      const action = button.dataset.action;
      if ((action === "off" || action === "cycle") && !window.confirm("Confirm plug " + action + "?")) return true;
      await api("POST", `/api/v1/plugs/${id}/power`, { action, confirm: action === "off" || action === "cycle" });
    } else if (cap === "ups_status") {
      const data = await api("GET", `/api/v1/ups/${id}/status`);
      showBanner(`${data.output_status}, load ${data.load_pct ?? "?"}%`);
    } else if (cap === "roku_status") {
      const data = await api("GET", `/api/v1/rokus/${id}/status`);
      showBanner(`${data.name || "Roku"} ${data.model || ""} is ${data.power_mode || "unknown"}`.trim());
    } else if (cap === "roku_power") {
      const action = button.dataset.action;
      const destructive = action === "off" || action === "toggle";
      if (destructive && !window.confirm(action === "toggle" ? "Power can turn the Roku off. Confirm?" : "Turn the Roku off?")) return true;
      const data = await api("POST", `/api/v1/rokus/${id}/power`, { action, confirm: destructive });
      showBanner(`${data.name || "Roku"} is ${data.power_mode || action}`);
    } else if (cap === "ups_action") {
      const action = button.dataset.action;
      if (!window.confirm("This can drop every load on the UPS. Confirm " + action + "?")) return true;
      await api("POST", `/api/v1/ups/${id}/action`, { action, confirm: true });
    } else if (cap === "refresh_pdu_outlet_names") {
      const data = await api("POST", `/api/v1/pdus/${id}/outlet-names`);
      await refreshPower();
      const note = document.querySelector("form.hardware-edit .device-names");
      if (note) note.textContent = deviceNamesText(data.device_outlet_names);
      else if (state.page === "power") renderPower();
      else if (state.page === "devices") render();
      showBanner("Outlet names read from the PDU");
      return true;
    } else if (cap === "list_metrics") {
      const rows = await api("GET", "/api/v1/metrics?limit=60");
      showBanner(rows.length ? `${rows.length} readings` : "No readings yet");
    } else if (cap.startsWith("update_")) {
      if (button.dataset.save === "1") {
        await window.saveHardware(button);
        return true;
      }
      const card = button.closest("article");
      if (!card || card.querySelector("form.hardware-edit")) return true;
      const record = window.findHardware(cap.slice("update_".length), id);
      if (!record) return true;
      card.insertAdjacentHTML("beforeend", window.hardwareEditor(cap.slice("update_".length), record));
      return true;
    }
    if (state.page === "power") renderPower();
    if (state.page === "scan") renderScan();
  } catch (error) {
    showBanner(error.message, true, error.existing);
  }
  return true;
};

document.body.addEventListener("submit", async (event) => {
  const edit = event.target.closest ? event.target.closest("form.hardware-edit") : null;
  if (edit) {
    const button = edit.querySelector("[data-save]");
    if (button) await window.saveHardware(button);
    return;
  }
  const form = event.target;
  if (!form || !["pdu-form", "amt-form", "jet-form", "plug-form", "ups-form", "roku-form", "scan-form", "profile-form"].includes(form.id)) return;
  const data = Object.fromEntries(new FormData(form).entries());
  try {
    if (form.id === "scan-form") {
      state.scan = await api("POST", "/api/v1/scans", { cidr: data.cidr || null, replace: Boolean(form.elements.replace && form.elements.replace.checked) });
      showBanner("Scan started");
      window.setTimeout(async () => {
        await refreshScans();
        if (state.page === "scan") renderScan();
      }, 1200);
    } else if (form.id === "pdu-form") {
      await api("POST", "/api/v1/pdus", payloadFrom(form));
    } else if (form.id === "amt-form") {
      await api("POST", "/api/v1/amt", payloadFrom(form));
    } else if (form.id === "jet-form") {
      await api("POST", "/api/v1/jetkvm", payloadFrom(form));
    } else if (form.id === "plug-form") {
      await api("POST", "/api/v1/plugs", payloadFrom(form));
    } else if (form.id === "profile-form") {
      await api("POST", "/api/v1/credential-profiles", { name: data.name, username: data.username || "", password: data.password || null });
    } else if (form.id === "ups-form") {
      await api("POST", "/api/v1/ups", payloadFrom(form));
    } else if (form.id === "roku-form") {
      await api("POST", "/api/v1/rokus", payloadFrom(form));
    }
    if (form.id !== "scan-form") {
      await refreshPower();
      renderPower();
      showBanner("Saved");
    } else {
      await refreshScans();
      renderScan();
    }
  } catch (error) {
    showBanner(error.message, true, error.existing);
  }
});

window.CONTROL_HANDLERS = {
  list_devices() { return show("devices"); },
  get_device(el) { state.focus = null; state.editing = Number(el.dataset.id); writeRoute("devices", ""); render(); },
  add_device() { state.editing = "new"; render(); },
  update_device(el) { state.editing = Number(el.dataset.id); render(); },
  remove_device(el) { return onClick({ target: el }); },
  bulk_remove(el) {
    if (el.id === "delete-tagged") return window.confirmDelete([], state.tagFilter || []);
    const checked = [...document.querySelectorAll(".select-record:checked")].map((box) => ({
      kind: box.dataset.kind,
      id: Number(box.dataset.id),
    }));
    return window.confirmDelete(checked.length ? checked : (state.selection || []), []);
  },
  set_device_enabled(el) { return onClick({ target: el }); },
  wake_device(el) { return onClick({ target: el }); },
  power_action(el) { return sendPower(el); },
  device_status(el) { return onClick({ target: el }); },
  list_status(el) { return onClick({ target: el }); },
  list_actions() { return show("history"); },
  get_settings() { return show("settings"); },
  update_settings() { return show("settings"); },
  get_access_token() { return show("settings"); },
  rotate_token(el) { return onClick({ target: el }); },
  ui_login() { $("login").classList.remove("hidden"); },
  ui_setup() { $("setup").classList.remove("hidden"); },
  get_ui_session() {},
  ui_logout() { return window.signOut(); },
  list_interfaces() { return show("scan"); },
  test_target(el) { return window.runTest(el); },
  list_credential_profiles() { return show("power"); },
  add_credential_profile() { return show("power"); },
  update_credential_profile(el) { return window.saveProfile(el); },
  remove_credential_profile(el) { return window.removeProfile(el); },
  list_pdus() { return show("power"); },
  add_pdu() { return show("power"); },
  update_pdu(el) { return window.handlePowerCap(el); },
  remove_pdu(el) { return window.handlePowerCap(el); },
  list_pdu_outlets(el) { return window.handlePowerCap(el); },
  refresh_pdu_outlet_names(el) { return window.handlePowerCap(el); },
  set_pdu_outlet(el) { return window.handlePowerCap(el); },
  list_amt() { return show("power"); },
  add_amt() { return show("power"); },
  update_amt(el) { return window.handlePowerCap(el); },
  remove_amt(el) { return window.handlePowerCap(el); },
  amt_power_state(el) { return window.handlePowerCap(el); },
  list_jetkvm() { return show("power"); },
  add_jetkvm() { return show("power"); },
  update_jetkvm(el) { return window.handlePowerCap(el); },
  remove_jetkvm(el) { return window.handlePowerCap(el); },
  jetkvm_status(el) { return window.handlePowerCap(el); },
  jetkvm_power(el) { return window.handlePowerCap(el); },
  jetkvm_console() {},
  list_plugs() { return show("power"); },
  add_plug() { return show("power"); },
  update_plug(el) { return window.handlePowerCap(el); },
  remove_plug(el) { return window.handlePowerCap(el); },
  plug_status(el) { return window.handlePowerCap(el); },
  plug_power(el) { return window.handlePowerCap(el); },
  list_ups() { return show("power"); },
  add_ups() { return show("power"); },
  update_ups(el) { return window.handlePowerCap(el); },
  remove_ups(el) { return window.handlePowerCap(el); },
  ups_status(el) { return window.handlePowerCap(el); },
  ups_action(el) { return sendUps(el); },
  list_rokus() { return show("power"); },
  add_roku() { return show("power"); },
  update_roku(el) { return window.handlePowerCap(el); },
  remove_roku(el) { return window.handlePowerCap(el); },
  roku_status(el) { return window.handlePowerCap(el); },
  roku_power(el) { return window.handlePowerCap(el); },
  list_tags() {},
  tag_action(el) { return window.runTagAction(el); },
  list_salvos() { return refreshDevices().then(() => { if (state.page === "salvos") render(); }); },
  amt_power(el) { return window.handlePowerCap(el); },
  update_pdu_outlet(el) { return window.handlePowerCap(el); },
  get_salvo(el) { return window.editSalvo(el); },
  add_salvo() {},
  update_salvo(el) { return window.saveSalvo(el.dataset.id); },
  remove_salvo(el) { return window.deleteSalvo(el); },
  duplicate_salvo(el) { return window.duplicateSalvo(el); },
  run_salvo(el) { return window.runSalvo(el); },
  scan_subnet() { return show("scan"); },
  list_scans() { return show("scan"); },
  delete_scan(el) { return window.handlePowerCap(el); },
  clear_scans(el) { return window.handlePowerCap(el); },
  rescan(el) { return window.handlePowerCap(el); },
  scan_results(el) { return window.handlePowerCap(el); },
  add_from_scan(el) { return window.handlePowerCap(el); },
  device_metrics(el) { return onClick({ target: el }); },
  list_metrics(el) { return window.handlePowerCap(el); },
};

async function sendPower(el) {
  const id = Number(el.dataset.id);
  const action = el.dataset.action || "on";
  const device = (state.devices || []).find((item) => item.id === id);
  const pick = el.closest("article") && el.closest("article").querySelector(".action-method");
  const method = (pick && pick.value) || "auto";
  const destructive = action !== "on";
  if (destructive && !window.confirm(`Confirm ${action}?`)) return;
  const result = await api("POST", `/api/v1/devices/${id}/power`, { action, method, confirm: destructive });
  showBanner(result.noop ? result.reason : reachText(result));
  await refreshDevices();
  render();
}

async function sendUps(el) {
  const card = el.closest("article");
  const action = el.dataset.action;
  const delay = card.querySelector(".ups-delay").value;
  const outlet = card.querySelector(".ups-outlet").value;
  const destructive = !["turn_on", "outlet_on"].includes(action);
  if (destructive && !window.confirm("This can drop every load on the UPS. Confirm " + action + "?")) return;
  const body = { action, confirm: destructive };
  if (delay) body.delay_seconds = Number(delay);
  if (outlet) body.outlet = Number(outlet);
  const data = await api("POST", `/api/v1/ups/${el.dataset.id}/action`, body);
  showBanner(data.warning || action);
}
