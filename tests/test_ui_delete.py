import httpx

from wakehub.inventory import ui_setup


def test_delete_button_names_the_device_and_the_salvos(live_server, hub):
    from playwright.sync_api import sync_playwright

    ui_setup(hub, hub.token, "correct horse", client="browser")
    headers = {"Authorization": f"Bearer {hub.token}"}
    desk = httpx.post(
        f"{live_server}/api/v1/devices",
        headers=headers,
        json={"name": "Desk", "mac": "02:00:00:00:00:91", "host": "127.0.0.1", "broadcast": "127.0.0.1", "reach_timeout": 1},
    ).json()
    httpx.post(
        f"{live_server}/api/v1/plugs",
        headers=headers,
        json={"name": "Lamp", "kind": "shelly", "host": "127.0.0.2"},
    )
    httpx.post(
        f"{live_server}/api/v1/salvos",
        headers=headers,
        json={"name": "Home Away", "steps": [{"target_kind": "device", "target_id": desk["id"], "action": "off"}]},
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        messages = []

        def on_dialog(dialog):
            messages.append(dialog.message)
            if len(messages) == 1:
                dialog.accept()
            else:
                dialog.dismiss()

        page.on("dialog", on_dialog)
        page.goto(live_server + "/")
        page.fill("#ui-password", "correct horse")
        page.click("button[data-cap=ui_login]")
        page.wait_for_selector("#device-search")
        page.locator("article", has_text="Desk").locator(".more-toggle").click()
        page.locator("article", has_text="Desk").locator("button.delete").click()
        page.wait_for_selector("#banner:not(.hidden)")
        assert "Delete Desk?" in messages[0]
        assert "Home Away" in messages[0]
        assert "Deleted Desk" in page.inner_text("#banner")
        assert page.locator("article", has_text="Desk").count() == 0

        page.locator("article", has_text="Lamp").locator(".select-record").check()
        page.wait_for_selector("#bulk-bar:not(.hidden)")
        with page.expect_event("dialog"):
            page.click("#delete-selected")
        assert "Delete Lamp?" in messages[1]
        assert page.locator("article", has_text="Lamp").count() == 1
        lamp = page.locator("article", has_text="Lamp")
        lamp.locator(".more-toggle").click()
        lamp.locator("button", has_text="Open").click()
        page.wait_for_selector("#back-inventory")
        assert page.locator("button.delete", has_text="Delete Lamp").count() >= 1
        browser.close()
