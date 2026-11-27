import httpx

from wakehub.inventory import ui_setup


def test_run_salvo_previews_the_devices_before_confirm(live_server, hub):
    from playwright.sync_api import sync_playwright

    ui_setup(hub, hub.token, "correct horse", client="browser")
    headers = {"Authorization": f"Bearer {hub.token}"}
    httpx.post(
        f"{live_server}/api/v1/devices",
        headers=headers,
        json={"name": "Desk", "mac": "02:00:00:00:00:41", "host": "127.0.0.1", "broadcast": "127.0.0.1", "reach_timeout": 1, "tags": ["#Office"]},
    )
    httpx.post(
        f"{live_server}/api/v1/salvos",
        headers=headers,
        json={"name": "Home Away", "steps": [{"target_kind": "tag", "tags": ["Office"], "action": "wake", "delay_seconds": 0}]},
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        seen = []
        page.on("dialog", lambda dialog: seen.append(dialog.message) or dialog.accept())
        page.goto(live_server + "/")
        page.fill("#ui-password", "correct horse")
        page.click("button[data-cap=ui_login]")
        page.wait_for_selector("button[data-cap=run_salvo]")
        page.click("button[data-cap=run_salvo]")
        page.wait_for_selector("#banner:not(.hidden)")
        assert seen and "Desk" in seen[0]
        assert "Home Away" in seen[0]
        assert "ran 1" in page.inner_text("#banner")
        browser.close()
