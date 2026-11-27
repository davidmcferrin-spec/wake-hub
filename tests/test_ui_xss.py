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
        page.click("aside button[data-page=salvos]")
        page.wait_for_selector("button.copy-salvo-url")
        assert page.evaluate("() => window.__xss") is None
        assert page.locator("img[src='x']").count() == 0
        page.click("aside button[data-page=power]")
        page.select_option("#hw-add-type", "amt")
        page.click("button[data-add-form=amt-form]")
        page.wait_for_selector("#amt-form select[name=credential_profile_id]")
        page.wait_for_selector("#amt-form select[name=device_id]")
        assert page.evaluate("() => window.__xss") is None
        assert page.locator("img[src='x']").count() == 0
        page.click("aside button[data-page=devices]")
        page.wait_for_selector("#device-search")
        page.wait_for_function(
            """() => {
              const node = document.querySelector("#device-search");
              if (!node) return false;
              const box = node.getBoundingClientRect();
              const mark = [box.x, box.y, box.width].join(",");
              const previous = node.getAttribute("data-settled");
              node.setAttribute("data-settled", mark);
              return previous === mark && box.width > 0;
            }"""
        )
        page.locator("article .more-toggle").click()
        page.locator("button[data-cap=get_device]").wait_for(state="visible")
        page.click("button[data-cap=get_device]")
        page.wait_for_selector("#device-form")
        assert page.evaluate("() => window.__xss") is None
        assert page.locator("img[src='x']").count() == 0
        browser.close()
