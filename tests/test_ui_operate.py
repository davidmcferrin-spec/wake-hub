import httpx

from wakehub.inventory import ui_setup

POWER = [
    "roku_power",
    "amt_power",
    "plug_power",
    "jetkvm_power",
    "ups_action",
    "set_pdu_outlet",
    "power_action",
    "wake_device",
]


def test_saving_an_edit_keeps_the_linked_amt(live_server, hub):
    from playwright.sync_api import sync_playwright

    from wakehub.controls import fold_linked_controls
    from wakehub.inventory import ui_setup

    ui_setup(hub, hub.token, "correct horse", client="browser")
    headers = {"Authorization": f"Bearer {hub.token}"}
    device = httpx.post(
        f"{live_server}/api/v1/devices",
        headers=headers,
        json={"name": "UNRAID", "mac": "02:00:00:00:00:97", "host": "192.168.0.97"},
    ).json()
    httpx.post(
        f"{live_server}/api/v1/amt",
        headers=headers,
        json={"name": "UNRAID vPRO", "host": "192.168.0.41", "port": 16992, "password": "secret-amt", "device_id": device["id"]},
    )
    fold_linked_controls(hub)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(live_server + "/")
        page.fill("#ui-password", "correct horse")
        page.click("button[data-cap=ui_login]")
        page.wait_for_selector("#device-search")
        card = page.locator("article").filter(has=page.get_by_role("heading", name="UNRAID", exact=True))
        assert card.locator("button", has_text="Wake via AMT").count() == 1
        assert page.get_by_role("heading", name="UNRAID vPRO", exact=True).count() == 0
        card.locator("summary", has_text="More").click()
        card.get_by_role("button", name="Edit").click()
        page.wait_for_selector("#device-form")
        page.click("#device-form button[type=submit]")
        page.wait_for_selector("#banner:not(.hidden)")
        saved = httpx.get(f"{live_server}/api/v1/devices/{device['id']}", headers=headers).json()
        assert [item["kind"] for item in saved["methods"]] == ["amt", "wol"]
        browser.close()


def test_devices_operate_and_hardware_is_setup_only(live_server, hub):
    from playwright.sync_api import sync_playwright

    ui_setup(hub, hub.token, "correct horse", client="browser")
    headers = {"Authorization": f"Bearer {hub.token}"}
    base = live_server + "/api/v1"
    httpx.post(f"{base}/devices", headers=headers, json={"name": "Office PC", "mac": "02:00:00:00:00:c1", "host": "10.4.2.2"})
    pdu = httpx.post(f"{base}/pdus", headers=headers, json={"name": "Rack PDU", "host": "10.4.2.5", "password": "secret"}).json()
    hub.write("INSERT INTO pdu_outlets (pdu_id, number, name, tags) VALUES (?, 1, 'NAS', '[]')", (pdu["id"],))
    httpx.post(f"{base}/amt", headers=headers, json={"name": "Bare AMT", "host": "10.4.2.3", "password": "secret-amt"})
    httpx.post(f"{base}/jetkvm", headers=headers, json={"name": "Desk KVM", "host": "10.4.2.6"})
    httpx.post(f"{base}/plugs", headers=headers, json={"name": "Lamp Plug", "kind": "shelly", "host": "10.4.2.7"})
    httpx.post(f"{base}/ups", headers=headers, json={"name": "Hall UPS", "host": "10.4.2.9"})
    httpx.post(f"{base}/rokus", headers=headers, json={"name": "Den Roku", "host": "10.4.2.10"})

    def card(page, name):
        return page.locator("article").filter(has=page.get_by_role("heading", name=name, exact=True))

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(live_server + "/")
        page.fill("#ui-password", "correct horse")
        page.click("button[data-cap=ui_login]")
        page.wait_for_selector("#device-search")
        checks = {
            "Office PC": (["Wake", "Off"], ".pill"),
            "Den Roku": (["On", "Off", "Toggle"], "[data-live-status]"),
            "Lamp Plug": (["On", "Off"], "[data-live-status]"),
            "Bare AMT": (["Power on", "Off", "Reset"], "[data-live-status]"),
            "Desk KVM": (["Power", "Off", "Reset"], "[data-live-status]"),
            "Hall UPS": (["Status", "Bank on", "Bank off"], "[data-live-status]"),
            "Rack PDU": (["On", "Off", "Cycle"], "[data-live-status]"),
        }
        for name, (labels, status) in checks.items():
            box = card(page, name)
            box.wait_for()
            assert box.locator(status).count() >= 1, name
            for label in labels:
                assert box.locator("button", has_text=label).count() >= 1, f"{name} missing {label}"
        page.click("aside button[data-page=power]")
        page.wait_for_selector("#hw-tabs")
        for cap in POWER:
            assert page.locator(f"main button[data-cap={cap}]:visible").count() == 0, cap
        assert page.locator("main button", has_text="Edit").count() >= 1
        page.get_by_role("tab", name="Roku").click()
        page.click("button[data-add-form=roku-form]")
        page.click("#roku-help")
        assert "Control by mobile apps" in page.inner_text("#roku-help-text")
        browser.close()
