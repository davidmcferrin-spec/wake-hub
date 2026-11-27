import httpx

from wakehub.inventory import ui_setup


def test_devices_toolbar_and_hardware_tabs(live_server, hub):
    from playwright.sync_api import sync_playwright

    ui_setup(hub, hub.token, "correct horse", client="browser")
    headers = {"Authorization": f"Bearer {hub.token}"}
    httpx.post(
        f"{live_server}/api/v1/devices",
        headers=headers,
        json={"name": "Office PC", "mac": "02:00:00:00:00:31", "host": "10.9.4.1"},
    )
    httpx.post(f"{live_server}/api/v1/pdus", headers=headers, json={"name": "Rack PDU", "host": "10.9.4.2"})
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(live_server + "/")
        page.fill("#ui-password", "correct horse")
        page.click("button[data-cap=ui_login]")
        page.wait_for_selector("#device-search")
        assert page.locator("#page-actions button", has_text="Add device").count() == 1
        assert page.locator("#page-actions button", has_text="Refresh").count() == 1
        assert page.locator("#filter-form button.sr-only").count() == 1
        assert page.locator("#bulk-bar").is_hidden()
        page.locator("article", has_text="Office PC").locator(".select-record").check()
        page.wait_for_selector("#bulk-bar:not(.hidden)")
        assert "1 selected" in page.inner_text("#bulk-label")
        page.click("aside button[data-page=power]")
        page.wait_for_selector("#hw-tabs")
        assert page.get_by_role("tab", name="PDU").count() == 1
        page.get_by_role("tab", name="PDU").click()
        assert "/#/hardware/pdu" in page.url
        assert page.locator("#pdu-form").is_visible()
        assert page.locator("#amt-form").is_hidden()
        page.keyboard.press("ArrowLeft")
        assert page.get_by_role("tab", name="All").get_attribute("aria-selected") == "true"
        page.set_viewport_size({"width": 800, "height": 900})
        page.click("aside button[data-page=devices]")
        page.wait_for_selector("#device-search")
        box = page.locator("#device-search").bounding_box()
        kind = page.locator("#kind-filter").bounding_box()
        assert box and kind
        assert abs(box["y"] - kind["y"]) < 8
        browser.close()
