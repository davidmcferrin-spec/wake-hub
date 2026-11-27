state.scans = [];
state.scan = null;
state.power = { pdus: [], amts: [], jetkvms: [], plugs: [], ups: [] };

async function refreshScans() {
  state.scans = await api("GET", "/api/v1/scans");
  if (state.scan) state.scan = await api("GET", `/api/v1/scans/${state.scan.id}`);
}

async function refreshPower() {
  state.power.pdus = await api("GET", "/api/v1/pdus");
  state.power.amts = await api("GET", "/api/v1/amt");
  state.power.jetkvms = await api("GET", "/api/v1/jetkvm");
  state.power.plugs = await api("GET", "/api/v1/plugs");
  state.power.ups = await api("GET", "/api/v1/ups");
}

function renderScan() {
  const rows = (state.scan ? state.scan.hosts : []).map((host) => `
    <article class="card">
      <header>
        <h2>${escapeHtml(host.ip)}</h2>
        <span class="pill">${escapeHtml((host.kinds || []).join(", ") || "host")}</span>
      </header>
      <p class="meta">${escapeHtml(host.mac || "no MAC")} · ${escapeHtml(host.hostname || "no name")} · ${escapeHtml(host.vendor || "")}</p>
      <div class="row-actions">
        <button type="button" data-cap="add_from_scan" data-scan="${state.scan.id}" data-host="${host.id}" data-kind="device">Add device</button>
        <button type="button" data-cap="add_from_scan" data-scan="${state.scan.id}" data-host="${host.id}" data-kind="pdu">Add PDU</button>
        <button type="button" data-cap="add_from_scan" data-scan="${state.scan.id}" data-host="${host.id}" data-kind="amt">Add AMT</button>
        <button type="button" data-cap="add_from_scan" data-scan="${state.scan.id}" data-host="${host.id}" data-kind="jetkvm">Add JetKVM</button>
        <button type="button" data-cap="add_from_scan" data-scan="${state.scan.id}" data-host="${host.id}" data-kind="plug">Add plug</button>
        <button type="button" data-cap="add_from_scan" data-scan="${state.scan.id}" data-host="${host.id}" data-kind="ups">Add UPS</button>
      </div>
    </article>`).join("");
  const scans = state.scans.map((scan) => `
    <button type="button" class="ghost" data-cap="scan_results" data-id="${scan.id}">${escapeHtml(scan.cidr)} · ${escapeHtml(scan.status)} ${scan.progress}/${scan.total}</button>
  `).join(" ");
  $("view").innerHTML = `
    <form id="scan-form" class="toolbar">
      <input name="cidr" placeholder="192.168.1.0/24" aria-label="CIDR">
      <button type="submit" data-cap="scan_subnet">Scan subnet</button>
    </form>
    <div class="row-actions">${scans || ""}</div>
    <section class="grid">${rows || `<div class="empty">Start a scan. Host networking is required for ARP and broadcast.</div>`}</section>`;
}

function renderPower() {
  const pduCards = state.power.pdus.map((pdu) => `
    <article class="card">
      <h2>${escapeHtml(pdu.name)}</h2>
      <p class="meta">${escapeHtml(pdu.host)}</p>
      <div class="row-actions">
        <button type="button" data-cap="list_pdu_outlets" data-id="${pdu.id}">Outlets</button>
        <button type="button" data-cap="update_pdu" data-id="${pdu.id}">Edit</button>
        <button type="button" class="danger" data-cap="remove_pdu" data-id="${pdu.id}">Remove</button>
      </div>
      <div id="pdu-${pdu.id}"></div>
    </article>`).join("");
  const amtCards = state.power.amts.map((item) => `
    <article class="card">
      <h2>${escapeHtml(item.name)}</h2>
      <p class="meta">${escapeHtml(item.host)}:${item.port}</p>
      <div class="row-actions">
        <button type="button" data-cap="amt_power_state" data-id="${item.id}">Power state</button>
        <button type="button" data-cap="update_amt" data-id="${item.id}">Edit</button>
        <button type="button" class="danger" data-cap="remove_amt" data-id="${item.id}">Remove</button>
      </div>
    </article>`).join("");
  const jetCards = state.power.jetkvms.map((item) => `
    <article class="card">
      <h2>${escapeHtml(item.name)}</h2>
      <p class="meta">${escapeHtml(item.host)}</p>
      <div class="row-actions">
        <button type="button" data-cap="jetkvm_status" data-id="${item.id}">Status</button>
        <button type="button" data-cap="jetkvm_power" data-id="${item.id}" data-action="power-short">Power press</button>
        <button type="button" class="danger" data-cap="jetkvm_power" data-id="${item.id}" data-action="power-long">Force off</button>
        <button type="button" class="danger" data-cap="jetkvm_power" data-id="${item.id}" data-action="reset">Reset</button>
        <a class="ghost" data-cap="jetkvm_console" href="${escapeHtml(item.console_url)}" target="_blank" rel="noopener">Open console</a>
        <button type="button" data-cap="update_jetkvm" data-id="${item.id}">Edit</button>
        <button type="button" class="danger" data-cap="remove_jetkvm" data-id="${item.id}">Remove</button>
      </div>
    </article>`).join("");
  const plugCards = state.power.plugs.map((item) => `
    <article class="card">
      <h2>${escapeHtml(item.name)}</h2>
      <p class="meta">${escapeHtml(item.kind)} · ${escapeHtml(item.host)}</p>
      <div class="row-actions">
        <button type="button" data-cap="plug_status" data-id="${item.id}">Status</button>
        <button type="button" data-cap="plug_power" data-id="${item.id}" data-action="on">On</button>
        <button type="button" class="danger" data-cap="plug_power" data-id="${item.id}" data-action="off">Off</button>
        <button type="button" data-cap="plug_power" data-id="${item.id}" data-action="toggle">Toggle</button>
        <button type="button" class="danger" data-cap="plug_power" data-id="${item.id}" data-action="cycle">Cycle</button>
        <button type="button" data-cap="update_plug" data-id="${item.id}">Edit</button>
        <button type="button" class="danger" data-cap="remove_plug" data-id="${item.id}">Remove</button>
      </div>
    </article>`).join("");
  const upsCards = state.power.ups.map((item) => `
    <article class="card">
      <h2>${escapeHtml(item.name)}</h2>
      <p class="meta">SNMP ${escapeHtml(item.snmp_version)} · ${escapeHtml(item.host)}</p>
      <p class="sub">Shutdown, reboot and outlet off drop power to everything on this UPS.</p>
      <div class="row-actions">
        <button type="button" data-cap="ups_status" data-id="${item.id}">Status</button>
        <button type="button" class="danger" data-cap="ups_action" data-id="${item.id}" data-action="shutdown">Shutdown</button>
        <button type="button" class="danger" data-cap="ups_action" data-id="${item.id}" data-action="reboot">Reboot</button>
        <button type="button" class="danger" data-cap="ups_action" data-id="${item.id}" data-action="turn_off">Turn off</button>
        <button type="button" data-cap="ups_action" data-id="${item.id}" data-action="battery_test">Battery test</button>
        <button type="button" data-cap="update_ups" data-id="${item.id}">Edit</button>
        <button type="button" class="danger" data-cap="remove_ups" data-id="${item.id}">Remove</button>
      </div>
    </article>`).join("");
  $("view").innerHTML = `
    <section>
      <h2>Synaccess PDU</h2>
      <form id="pdu-form" class="editor fields">
        <input name="name" placeholder="Name" required>
        <input name="host" placeholder="IP" required>
        <input name="username" placeholder="Username" value="admin">
        <input name="password" placeholder="Password" type="password">
        <button type="submit" data-cap="add_pdu">Add PDU</button>
      </form>
      <div class="grid">${pduCards}</div>
    </section>
      <section data-cap="list_amt">
      <h2>Intel AMT</h2>
      <form id="amt-form" class="editor fields">
        <input name="name" placeholder="Name" required>
        <input name="host" placeholder="IP" required>
        <input name="username" placeholder="Username" value="admin">
        <input name="password" placeholder="Password" type="password" required>
        <label class="check"><input type="checkbox" name="use_tls"> TLS</label>
        <label class="check"><input type="checkbox" name="insecure_tls" checked> Allow self-signed</label>
        <button type="submit" data-cap="add_amt">Add AMT</button>
      </form>
      <div class="grid">${amtCards}</div>
    </section>
      <section data-cap="list_jetkvm">
      <h2>JetKVM</h2>
      <form id="jet-form" class="editor fields">
        <input name="name" placeholder="Name" required>
        <input name="host" placeholder="IP" required>
        <input name="password" placeholder="Password or blank" type="password">
        <button type="submit" data-cap="add_jetkvm">Add JetKVM</button>
      </form>
      <div class="grid">${jetCards}</div>
    </section>
      <section data-cap="list_plugs">
      <h2>Smart plugs</h2>
      <form id="plug-form" class="editor fields">
        <input name="name" placeholder="Name" required>
        <select name="kind"><option value="shelly">Shelly</option><option value="kasa">Kasa</option></select>
        <input name="host" placeholder="IP" required>
        <input name="username" placeholder="User or TP-Link email">
        <input name="password" placeholder="Password" type="password">
        <select name="protocol"><option value="auto">Auto</option><option value="xor">XOR 9999</option><option value="klap">KLAP</option></select>
        <button type="submit" data-cap="add_plug">Add plug</button>
      </form>
      <div class="grid">${plugCards}</div>
    </section>
      <section data-cap="list_ups">
      <h2>CyberPower UPS</h2>
      <p class="sub">Destructive UPS actions need confirmation and can shut down every load.</p>
      <form id="ups-form" class="editor fields">
        <input name="name" placeholder="Name" required>
        <input name="host" placeholder="IP" required>
        <select name="snmp_version"><option value="1">SNMP v1</option><option value="2c" selected>SNMP v2c</option><option value="3">SNMP v3</option></select>
        <input name="community" placeholder="Community" value="public">
        <input name="v3_user" placeholder="v3 user">
        <input name="v3_auth" placeholder="v3 auth key" type="password">
        <input name="v3_priv" placeholder="v3 privacy key" type="password">
        <button type="submit" data-cap="add_ups">Add UPS</button>
      </form>
      <div class="grid">${upsCards}</div>
      <button type="button" class="ghost" data-cap="list_metrics">Refresh readings</button>
    </section>`;
}

function sparkline(rows) {
  const values = rows.map((row) => row.value).reverse();
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
  const known = ["scan_results", "add_from_scan", "list_pdu_outlets", "set_pdu_outlet", "update_pdu", "remove_pdu", "amt_power_state", "update_amt", "remove_amt", "jetkvm_status", "jetkvm_power", "update_jetkvm", "remove_jetkvm", "plug_status", "plug_power", "update_plug", "remove_plug", "ups_status", "ups_action", "update_ups", "remove_ups", "list_metrics"];
  if (!known.includes(cap)) return false;
  try {
    if (cap === "scan_results") {
      state.scan = await api("GET", `/api/v1/scans/${id}`);
    } else if (cap === "add_from_scan") {
      const body = { kind: button.dataset.kind };
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
            <button type="button" data-cap="set_pdu_outlet" data-pdu="${id}" data-outlet="${outlet.number}" data-action="on">On</button>
            <button type="button" class="danger" data-cap="set_pdu_outlet" data-pdu="${id}" data-outlet="${outlet.number}" data-action="off">Off</button>
            <button type="button" class="danger" data-cap="set_pdu_outlet" data-pdu="${id}" data-outlet="${outlet.number}" data-action="reboot">Reboot</button>
          </div>`).join("") + `<p class="sub">Bank current ${data.bank_amps.join(" A, ")} A. Not per outlet.</p>`;
      }
      return true;
    } else if (cap === "set_pdu_outlet") {
      const action = button.dataset.action;
      if ((action === "off" || action === "reboot") && !window.confirm(`Confirm outlet ${action}?`)) return true;
      await api("POST", `/api/v1/pdus/${button.dataset.pdu}/outlets/${button.dataset.outlet}`, { action, confirm: action !== "on" });
    } else if (cap === "remove_pdu" || cap === "remove_amt" || cap === "remove_jetkvm" || cap === "remove_plug" || cap === "remove_ups") {
      if (!window.confirm("Remove this record?")) return true;
      const path = { remove_pdu: "pdus", remove_amt: "amt", remove_jetkvm: "jetkvm", remove_plug: "plugs", remove_ups: "ups" }[cap];
      await api("DELETE", `/api/v1/${path}/${id}`);
      await refreshPower();
    } else if (cap === "amt_power_state") {
      const data = await api("GET", `/api/v1/amt/${id}/power`);
      showBanner(`${data.power_name}`);
    } else if (cap === "jetkvm_status") {
      const data = await api("GET", `/api/v1/jetkvm/${id}/status`);
      showBanner(data.reachable ? "JetKVM reachable" : "JetKVM did not answer");
    } else if (cap === "jetkvm_power") {
      const action = button.dataset.action;
      const destructive = action === "power-long" || action === "reset" || action === "dc-off";
      if (destructive && !window.confirm("Confirm JetKVM " + action + "?")) return true;
      await api("POST", `/api/v1/jetkvm/${id}/power`, { action, confirm: destructive });
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
    } else if (cap === "ups_action") {
      const action = button.dataset.action;
      if (!window.confirm("This can drop every load on the UPS. Confirm " + action + "?")) return true;
      await api("POST", `/api/v1/ups/${id}/action`, { action, confirm: true });
    } else if (cap === "list_metrics") {
      const rows = await api("GET", "/api/v1/metrics?limit=60");
      showBanner(rows.length ? `${rows.length} readings` : "No readings yet");
    } else if (cap.startsWith("update_")) {
      const name = window.prompt("New name");
      if (!name) return true;
      const path = { update_pdu: "pdus", update_amt: "amt", update_jetkvm: "jetkvm", update_plug: "plugs", update_ups: "ups" }[cap];
      await api("PATCH", `/api/v1/${path}/${id}`, { name });
      await refreshPower();
    }
    if (state.page === "power") renderPower();
    if (state.page === "scan") renderScan();
  } catch (error) {
    showBanner(error.message, true);
  }
  return true;
};

document.body.addEventListener("submit", async (event) => {
  const form = event.target;
  if (!["pdu-form", "amt-form", "jet-form", "plug-form", "ups-form", "scan-form"].includes(form.id)) return;
  event.preventDefault();
  const data = Object.fromEntries(new FormData(form).entries());
  try {
    if (form.id === "scan-form") {
      state.scan = await api("POST", "/api/v1/scans", { cidr: data.cidr || null });
      showBanner("Scan started");
      window.setTimeout(async () => {
        await refreshScans();
        if (state.page === "scan") renderScan();
      }, 1200);
    } else if (form.id === "pdu-form") {
      await api("POST", "/api/v1/pdus", data);
    } else if (form.id === "amt-form") {
      data.use_tls = form.elements.use_tls.checked;
      data.insecure_tls = form.elements.insecure_tls.checked;
      await api("POST", "/api/v1/amt", data);
    } else if (form.id === "jet-form") {
      await api("POST", "/api/v1/jetkvm", data);
    } else if (form.id === "plug-form") {
      await api("POST", "/api/v1/plugs", data);
    } else if (form.id === "ups-form") {
      await api("POST", "/api/v1/ups", data);
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
    showBanner(error.message, true);
  }
});
