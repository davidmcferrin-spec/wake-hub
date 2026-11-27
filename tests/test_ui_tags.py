import httpx

from wakehub.inventory import ui_setup


def test_tag_chips_filter_the_device_list(live_server, hub):
    from playwright.sync_api import sync_playwright

    ui_setup(hub, hub.token, "correct horse", client="browser")
    headers = {"Authorization": f"Bearer {hub.token}"}
    httpx.post(f"{live_server}/api/v1/devices", headers=headers, json={"name": "Desk", "mac": "02:00:00:00:00:11", "host": "10.9.3.1", "tags": ["#Office", "#TV"]})
    httpx.post(f"{live_server}/api/v1/devices", headers=headers, json={"name": "Spare", "mac": "02:00:00:00:00:12", "host": "10.9.3.2", "tags": ["Lab"]})
    httpx.post(f"{live_server}/api/v1/rokus", headers=headers, json={"name": "Den TV", "host": "10.9.3.3", "tags": ["#TV"]})
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(live_server + "/")
        page.fill("#ui-password", "correct horse")
        page.click("button[data-cap=ui_login]")
        page.wait_for_selector("#device-search")
        assert page.locator("input[name=tag]").count() == 0
        assert page.locator("button", has_text="Filter").count() == 0
        assert page.locator("button.tag", has_text="#Office").count() >= 1
        page.locator("button.tag", has_text="#Office").first.click()
        page.wait_for_function("document.querySelector('#device-search').value.includes('#Office')")
        assert "Desk" in page.inner_text("#view")
        assert "Spare" not in page.inner_text("#view")
        page.fill("#device-search", "#Office #TV")
        page.locator("#device-search").press("Enter")
        page.wait_for_function("!document.body.innerText.includes('Spare')")
        assert "Desk" in page.inner_text("#view")
        assert "Den TV" not in page.inner_text("#view")
        page.fill("#device-search", "")
        page.locator("#filter-form").evaluate("form => form.requestSubmit()")
        page.wait_for_selector("text=Spare")
        page.select_option("#kind-filter", "roku")
        page.wait_for_selector("text=Den TV")
        assert "Desk" not in page.inner_text("#view")
        browser.close()
