import httpx

from wakehub.inventory import ui_setup


def test_poll_skips_when_busy_and_buttons_do_not_wait_for_it(live_server, hub):
    from playwright.sync_api import sync_playwright

    ui_setup(hub, hub.token, "correct horse", client="browser")
    headers = {"Authorization": f"Bearer {hub.token}"}
    httpx.post(
        f"{live_server}/api/v1/devices",
        headers=headers,
        json={"name": "Office PC", "mac": "02:00:00:00:00:51", "host": "10.9.6.1", "reach_timeout": 1},
    )
    httpx.post(
        f"{live_server}/api/v1/amt",
        headers=headers,
        json={"name": "Bench vPro", "host": "10.9.6.8", "password": "secret-amt"},
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1100, "height": 900})
        hits = []

        def amt(route):
            hits.append(route.request.url)
            if hits.count("fail") or route.request.url.endswith("/status"):
                route.fulfill(status=404, content_type="application/json", body='{"error":{"message":"missing"}}')
                return
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"name":"Bench vPro","power_name":"on","power_state":2,"available":[2,8]}',
            )

        page.route("**/api/v1/amt/**", amt)
        page.set_default_timeout(8000)
        page.goto(live_server + "/")
        page.fill("#ui-password", "correct horse")
        page.click("button[data-cap=ui_login]")
        page.wait_for_selector("article.card")
        held = []

        def hold_status(route):
            held.append(route)

        page.route("**/api/v1/status", hold_status)
        page.evaluate("() => { window.pollStatus(true); window.pollStatus(true); }")
        page.wait_for_timeout(200)
        assert len(held) == 1
        held[0].fulfill(status=200, content_type="application/json", body="[]")
        page.unroute("**/api/v1/status", hold_status)
        page.evaluate("() => { window.pollStatus = () => new Promise(() => {}); }")
        wake = page.locator("article", has_text="Office PC").get_by_role("button", name="Wake")
        with page.expect_response("**/api/v1/devices/**/power"):
            wake.click()
        page.wait_for_function(
            """() => {
              const button = [...document.querySelectorAll("article button")].find((el) => el.innerText.includes("Wake"));
              return button && !button.disabled && button.getAttribute("aria-busy") !== "true";
            }""",
            timeout=8000,
        )
        page.wait_for_function(
            """() => [...document.querySelectorAll("[data-live-status]")].some((node) => node.dataset.liveStatus.startsWith("amt-") && node.textContent === "On")"""
        )
        assert not any(url.endswith("/status") for url in hits)
        card = page.locator("article", has_text="Bench vPro")
        card.locator("button", has_text="Status").click()
        page.wait_for_function(
            """() => {
              const node = document.querySelector("[data-live-status^='amt-']");
              return node && node.textContent.includes("is on");
            }"""
        )
        hits.append("fail")
        with page.expect_response("**/api/v1/amt/**/power"):
            page.evaluate(
                """() => {
                  const node = document.querySelector("[data-live-status^='amt-']");
                  node.dataset.amtPolled = "0";
                  window.pollAmt();
                }"""
            )
        assert "is on" in page.locator("[data-live-status^='amt-']").inner_text()
        browser.close()
