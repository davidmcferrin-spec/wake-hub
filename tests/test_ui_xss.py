import httpx

from wakehub.inventory import ui_setup

PAYLOAD = "<img src=x onerror=window.__xss=1>"


def test_names_from_the_user_are_not_html(live_server, hub):
    from playwright.sync_api import sync_playwright

    ui_setup(hub, hub.token, "correct horse", client="browser")
    headers = {"Authorization": f"Bearer {hub.token}"}
    httpx.post(
        f"{live_server}/api/v1/devices",
        headers=headers,
        json={"name": PAYLOAD, "mac": "02:00:00:00:00:a1", "host": "10.9.9.9", "tags": [PAYLOAD]},
    )
    httpx.post(
        f"{live_server}/api/v1/credential-profiles",
        headers=headers,
        json={"name": PAYLOAD, "username": "admin", "password": "secret-pw"},
    )
    httpx.post(
        f"{live_server}/api/v1/salvos",
        headers=headers,
        json={"name": PAYLOAD, "steps": [{"target_kind": "tag", "tags": ["Office"], "action": "off"}]},
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(live_server + "/")
        page.fill("#ui-password", "correct horse")
        page.click("button[data-cap=ui_login]")
        page.wait_for_selector("#device-search")
        page.wait_for_selector("text=Salvos")
        assert page.evaluate("() => window.__xss") is None
        assert page.locator("img[src='x']").count() == 0
        page.click("aside button[data-page=power]")
        page.wait_for_selector("select[name=credential_profile_id]")
        page.wait_for_selector("select[name=device_id]")
        assert page.evaluate("() => window.__xss") is None
        assert page.locator("img[src='x']").count() == 0
        page.click("aside button[data-page=devices]")
        page.wait_for_selector("button[data-cap=get_device]")
        page.click("button[data-cap=get_device]")
        page.wait_for_selector("#device-form")
        assert page.evaluate("() => window.__xss") is None
        assert page.locator("img[src='x']").count() == 0
        browser.close()
