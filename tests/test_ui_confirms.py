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
        options = unraid.locator(".action-method option").all_text_contents()
        assert "Wake-on-LAN" not in options
        assert "AMT" in options
        unraid.get_by_role("button", name="Off via AMT").click()
        assert any("UNRAID" in text and "AMT" in text for text in messages)
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
