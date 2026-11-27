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
        for label in ["Power on", "Off", "Reset", "Shut down", "Power cycle", "Read status"]:
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


def test_amt_card_disables_actions_the_firmware_does_not_advertise(live_server, hub):
    import json

    from playwright.sync_api import sync_playwright

    ui_setup(hub, hub.token, "correct horse", client="browser")
    headers = {"Authorization": f"Bearer {hub.token}"}
    created = httpx.post(
        live_server + "/api/v1/amt",
        headers=headers,
        json={"name": "Bare AMT", "host": "10.4.0.3", "password": "secret-amt"},
    ).json()
    body = json.dumps({"name": "Bare AMT", "power_state": 2, "power_name": "on", "available": [2, 8, 10], "amt_id": created["id"]})

    def fulfill(route):
        if route.request.method == "GET" and route.request.url.rstrip("/").endswith("/power"):
            route.fulfill(status=200, content_type="application/json", body=body)
        else:
            route.fallback()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.route("**/power", fulfill)
        page.goto(live_server + "/")
        page.fill("#ui-password", "correct horse")
        page.click("button[data-cap=ui_login]")
        page.wait_for_selector("#device-search")
        card = _card(page, "Bare AMT")
        card.locator(".more-toggle").click()
        card.locator("button", has_text="Open").click()
        page.wait_for_selector("#back-inventory")
        off = page.locator("button[data-cap=amt_power][data-action=off]")
        shutdown = page.locator("button[data-cap=amt_power][data-action=shutdown]")
        assert off.count() >= 1
        assert shutdown.count() >= 1
        assert page.locator("button[data-action=off_hard]").count() == 0
        page.click("button[data-cap=amt_power_state]")
        page.wait_for_function("() => document.querySelector('button[data-action=shutdown]').disabled")
        assert off.first.is_enabled()
        assert shutdown.first.is_disabled()
        browser.close()


def test_refused_amt_shutdown_is_logged(client, hub, monkeypatch):
    created = client.post("/api/v1/amt", json={"name": "Bench", "host": "10.4.1.2", "password": "secret-amt"}).json()

    class Fake:
        def request_power(self, action):
            from wakehub.clients.amt import parse_method_return

            parse_method_return("<ReturnValue>2</ReturnValue>", action=action)

    monkeypatch.setattr("wakehub.power.amt_client", lambda _hub, amt_id: (hub.query_one("SELECT * FROM amt_endpoints WHERE id = ?", (amt_id,)), Fake()))
    refused = client.post(f"/api/v1/amt/{created['id']}/power", json={"action": "shutdown", "confirm": True})
    assert refused.status_code == 502
    assert refused.json()["error"]["message"] == "AMT refused graceful shutdown (needs the Intel LMS/OS agent running); use Off"
    logged = [row for row in client.get("/api/v1/actions").json() if row["action"] == "amt_shutdown"]
    assert logged and logged[0]["ok"] is False


def test_amt_power_requires_confirm(client):
    created = client.post("/api/v1/amt", json={"name": "Bench", "host": "10.4.1.2", "password": "secret-amt"})
    assert created.status_code == 201, created.text
    refused = client.post(f"/api/v1/amt/{created.json()['id']}/power", json={"action": "off", "confirm": False})
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "confirmation_required"
    retired = client.post(f"/api/v1/amt/{created.json()['id']}/power", json={"action": "off_hard", "confirm": True})
    assert retired.status_code == 400
    assert retired.json()["error"]["message"] == "use off"
