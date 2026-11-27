import httpx

from wakehub.inventory import ui_setup


def _card(page, name):
    return page.locator("article").filter(has=page.get_by_role("heading", name=name, exact=True))


def test_every_hardware_type_shows_its_controls(live_server, hub):
    from playwright.sync_api import sync_playwright

    ui_setup(hub, hub.token, "correct horse", client="browser")
    headers = {"Authorization": f"Bearer {hub.token}"}
    base = live_server + "/api/v1"
    computer = httpx.post(
        f"{base}/devices",
        headers=headers,
        json={"name": "Office PC", "mac": "02:00:00:00:00:b1", "host": "10.4.0.2"},
    ).json()
    httpx.post(
        f"{base}/amt",
        headers=headers,
        json={"name": "Bare AMT", "host": "10.4.0.3", "password": "secret-amt"},
    )
    httpx.post(
        f"{base}/amt",
        headers=headers,
        json={"name": "Linked AMT", "host": "10.4.0.4", "password": "secret-amt", "device_id": computer["id"]},
    )
    pdu = httpx.post(f"{base}/pdus", headers=headers, json={"name": "Rack PDU", "host": "10.4.0.5", "password": "secret-pdu"}).json()
    hub.write(
        "INSERT INTO pdu_outlets (pdu_id, number, name, tags) VALUES (?, 1, 'NAS', ?)",
        (pdu["id"], '["office"]'),
    )
    httpx.post(f"{base}/jetkvm", headers=headers, json={"name": "Desk KVM", "host": "10.4.0.6"})
    httpx.post(f"{base}/plugs", headers=headers, json={"name": "Lamp Plug", "kind": "shelly", "host": "10.4.0.7"})
    httpx.post(f"{base}/plugs", headers=headers, json={"name": "Kasa Plug", "kind": "kasa", "host": "10.4.0.8"})
    httpx.post(f"{base}/ups", headers=headers, json={"name": "Hall UPS", "host": "10.4.0.9"})
    httpx.post(f"{base}/rokus", headers=headers, json={"name": "Den Roku", "host": "10.4.0.10"})

    def expect(page, name, labels):
        card = _card(page, name)
        card.wait_for()
        for label in labels:
            assert card.locator("button", has_text=label).count() >= 1, f"{name} missing {label}"

    amt = ["Power on", "Off graceful", "Off hard", "Reset", "Power cycle", "Status"]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(live_server + "/")
        page.fill("#ui-password", "correct horse")
        page.click("button[data-cap=ui_login]")
        page.wait_for_selector("#device-search")
        expect(page, "Office PC", ["Wake", "Off", "Reset"])
        assert page.locator("article .method-picker, article .wake-timeout").count() == 0
        expect(page, "Bare AMT", ["Power on", "Off", "Reset", "Status"])
        expect(page, "Office PC", ["Wake via AMT"])
        assert page.get_by_role("heading", name="Linked AMT", exact=True).count() == 0
        expect(page, "Rack PDU", ["On", "Off", "Cycle"])
        expect(page, "Desk KVM", ["Power", "Off", "Reset", "Status"])
        expect(page, "Lamp Plug", ["On", "Off", "Status"])
        expect(page, "Kasa Plug", ["On", "Off"])
        expect(page, "Hall UPS", ["Status", "Bank on", "Bank off"])
        expect(page, "Den Roku", ["On", "Off", "Toggle", "Status"])
        bare = _card(page, "Bare AMT")
        bare.locator(".more-toggle").click()
        bare.locator("button", has_text="Open").click()
        page.wait_for_selector("#back-inventory")
        for label in ["Power on", "Off", "Reset", "Off hard", "Power cycle", "Read status"]:
            assert page.locator("button", has_text=label).count() >= 1
        page.click("button[data-cap=amt_power_state]")
        page.wait_for_selector("#banner:not(.hidden)")
        assert page.locator("button", has_text="Power on").count() >= 1
        assert "Status not read yet." not in page.locator("[id^=amt-status-]").first.inner_text()
        page.click("aside button[data-page=power]")
        page.wait_for_selector("text=Hardware is where you add a box")
        assert "Hardware is where you add a box" in page.inner_text("main")
        hardware = _card(page, "Bare AMT")
        assert hardware.locator("button", has_text="Edit").count() >= 1
        assert hardware.locator("button", has_text="Power on").count() == 0
        assert _card(page, "Rack PDU").locator("button", has_text="Refresh names from device").count() >= 1
        browser.close()


def test_amt_power_requires_confirm(client):
    created = client.post("/api/v1/amt", json={"name": "Bench", "host": "10.4.1.2", "password": "secret-amt"})
    assert created.status_code == 201, created.text
    refused = client.post(f"/api/v1/amt/{created.json()['id']}/power", json={"action": "off_hard", "confirm": False})
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "confirmation_required"
