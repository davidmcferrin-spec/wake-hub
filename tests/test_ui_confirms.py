import httpx

from wakehub.inventory import ui_setup


def test_confirms_name_the_target_and_use_menu_skips_wol(live_server, hub):
    from playwright.sync_api import sync_playwright

    ui_setup(hub, hub.token, "correct horse", client="browser")
    headers = {"Authorization": f"Bearer {hub.token}"}
    base = live_server + "/api/v1"
    office = httpx.post(f"{base}/devices", headers=headers, json={"name": "UNRAID", "mac": "02:00:00:00:00:91", "host": "10.9.9.1"}).json()
    httpx.post(f"{base}/amt", headers=headers, json={"name": "UNRAID vPRO", "host": "10.9.9.2", "password": "secret-amt", "device_id": office["id"]})
    bare = httpx.post(f"{base}/amt", headers=headers, json={"name": "Bench AMT", "host": "10.9.9.3", "password": "secret-amt"}).json()
    pdu = httpx.post(f"{base}/pdus", headers=headers, json={"name": "Rack PDU", "host": "10.9.9.4", "password": "secret-pdu"}).json()
    hub.write("INSERT INTO pdu_outlets (pdu_id, number, name, tags) VALUES (?, 1, 'NAS', '[]')", (pdu["id"],))
    httpx.post(
        f"{base}/salvos",
        headers=headers,
        json={"name": "Lights out", "steps": [{"target_kind": "device", "target_id": office["id"], "action": "off", "method": "plug"}]},
    )
    messages = []

    def on_dialog(dialog):
        messages.append(dialog.message)
        dialog.dismiss()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.on("dialog", on_dialog)
        page.goto(live_server + "/")
        page.fill("#ui-password", "correct horse")
        page.click("button[data-cap=ui_login]")
        page.wait_for_selector("#device-search")
        unraid = page.locator("article").filter(has=page.get_by_role("heading", name="UNRAID", exact=True))
        unraid.locator(".more-toggle").click()
        wake_options = unraid.locator('.action-method[data-action="on"] option').all_text_contents()
        off_options = unraid.locator('.action-method[data-action="off"] option').all_text_contents()
        assert "Wake-on-LAN" in wake_options
        assert "Wake-on-LAN" not in off_options
        assert "AMT" in off_options
        unraid.get_by_role("button", name="Off via AMT").click()
        assert any("Turn off UNRAID via AMT (hard power off)" in text for text in messages)
        unraid.locator(".more-toggle").click()
        unraid.get_by_role("button", name="Shutdown via AMT").click()
        assert any("Shut down UNRAID via AMT (soft graceful off)" in text for text in messages)
        bench = page.locator("article").filter(has=page.get_by_role("heading", name="Bench AMT", exact=True))
        bench.get_by_role("button", name="Off", exact=True).click()
        assert any("Bench AMT" in text and "AMT" in text for text in messages)
        rack = page.locator("article").filter(has=page.get_by_role("heading", name="Rack PDU", exact=True))
        rack.locator("summary", has_text="Outlets").click()
        rack.get_by_role("button", name="Off", exact=True).click()
        assert any("NAS" in text and "Rack PDU" in text for text in messages)
        page.click("aside button[data-page=salvos]")
        page.wait_for_selector("button[data-cap=run_salvo]")
        with page.expect_event("dialog") as pending:
            page.click("button[data-cap=run_salvo]")
        assert "via plug" in pending.value.message
        assert bare["id"]
        browser.close()


def test_unraid_can_force_wol_for_wake_and_off_does_not_use_it(live_server, hub, monkeypatch):
    from playwright.sync_api import sync_playwright

    packets = []
    monkeypatch.setattr("wakehub.inventory.send_magic_packet", lambda *_args, **_kwargs: packets.append(True))
    monkeypatch.setattr("wakehub.inventory.wait_until_reachable", lambda *_args, **_kwargs: (False, 0))
    ui_setup(hub, hub.token, "correct horse", client="browser")
    headers = {"Authorization": f"Bearer {hub.token}"}
    base = live_server + "/api/v1"
    office = httpx.post(f"{base}/devices", headers=headers, json={"name": "UNRAID", "mac": "02:00:00:00:00:91", "host": "10.9.9.1"}).json()
    amt = httpx.post(f"{base}/amt", headers=headers, json={"name": "UNRAID vPRO", "host": "10.9.9.2", "password": "secret-amt", "device_id": office["id"]}).json()
    pdu = httpx.post(f"{base}/pdus", headers=headers, json={"name": "Rack PDU", "host": "10.9.9.4", "password": "secret-pdu"}).json()
    saved = httpx.patch(
        f"{base}/devices/{office['id']}",
        headers=headers,
        json={"methods": [{"kind": "amt", "amt_id": amt["id"]}, {"kind": "wol"}, {"kind": "pdu", "pdu_id": pdu["id"], "outlet": 1}]},
    )
    assert saved.status_code == 200, saved.text
    posted = []

    def capture(route):
        posted.append(route.request.post_data or "")
        route.fulfill(status=200, content_type="application/json", body='{"ok": true, "name": "UNRAID"}')

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.on("dialog", lambda dialog: dialog.accept())
        page.goto(live_server + "/")
        page.fill("#ui-password", "correct horse")
        page.click("button[data-cap=ui_login]")
        page.wait_for_selector("#device-search")
        unraid = page.locator("article").filter(has=page.get_by_role("heading", name="UNRAID", exact=True))
        unraid.locator(".more-toggle").click()
        wake = unraid.locator('.action-method[data-action="on"]')
        off = unraid.locator('.action-method[data-action="off"]')
        assert "Wake-on-LAN" in wake.locator("option").all_text_contents()
        assert "PDU outlet" in off.locator("option").all_text_contents()
        assert "Wake-on-LAN" not in off.locator("option").all_text_contents()
        wake.select_option("wol")
        expect_wake = unraid.get_by_role("button", name="Wake via WOL")
        expect_wake.wait_for()
        page.click("#page-title")
        page.wait_for_timeout(12000)
        assert wake.input_value() == "wol"
        expect_wake.click()
        page.wait_for_function(
            """() => {
              const banner = document.querySelector("#banner");
              return banner && !banner.classList.contains("hidden") && banner.textContent.includes("packet sent");
            }"""
        )
        assert packets, "Wake via Wake-on-LAN did not send a magic packet"
        page.route("**/api/v1/devices/*/power", capture)
        page.evaluate(
            """() => {
              const select = document.querySelector('article .action-method[data-action="off"]');
              const option = document.createElement("option");
              option.value = "wol";
              option.textContent = "Wake-on-LAN";
              select.append(option);
              select.value = "wol";
            }"""
        )
        unraid.get_by_role("button", name="Off via AMT").click()
        assert posted and '"method":"wol"' not in posted[-1]
        assert '"method":"auto"' in posted[-1]
        browser.close()
