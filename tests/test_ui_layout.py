import httpx

from wakehub.inventory import ui_setup


def test_devices_toolbar_and_hardware_tabs(live_server, hub):
    from playwright.sync_api import sync_playwright

    ui_setup(hub, hub.token, "correct horse", client="browser")
    headers = {"Authorization": f"Bearer {hub.token}"}
    office = httpx.post(
        f"{live_server}/api/v1/devices",
        headers=headers,
        json={"name": "Office PC", "mac": "02:00:00:00:00:31", "host": "10.9.4.1"},
    ).json()
    httpx.post(
        f"{live_server}/api/v1/amt",
        headers=headers,
        json={"name": "Office vPro", "host": "10.9.4.3", "password": "secret-amt", "device_id": office["id"]},
    )
    tv = httpx.post(
        f"{live_server}/api/v1/devices",
        headers=headers,
        json={"name": "Living TV", "mac": "02:00:00:00:00:32", "host": "10.9.4.4"},
    ).json()
    httpx.post(
        f"{live_server}/api/v1/rokus",
        headers=headers,
        json={"name": "Living Roku", "host": "10.9.4.5", "device_id": tv["id"]},
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
        page.click("button[data-add-form=pdu-form]")
        assert page.locator("#pdu-form").is_visible()
        assert page.locator("#amt-form").is_hidden()
        page.get_by_role("tab", name="PDU").focus()
        page.keyboard.press("ArrowLeft")
        assert page.get_by_role("tab", name="All").get_attribute("aria-selected") == "true"
        page.set_viewport_size({"width": 800, "height": 900})
        page.click("aside button[data-page=devices]")
        page.locator("#kind-filter").wait_for(state="visible")
        page.wait_for_function(
            """() => {
              const search = document.querySelector("#device-search");
              const kind = document.querySelector("#kind-filter");
              if (!search || !kind) return false;
              const shown = getComputedStyle(kind).display !== "none" && getComputedStyle(kind).visibility !== "hidden";
              const a = search.getBoundingClientRect();
              const b = kind.getBoundingClientRect();
              if (!shown || a.width < 1 || b.width < 1) return false;
              const mark = [Math.round(a.y), Math.round(b.y), Math.round(a.width), Math.round(b.width)].join(",");
              const previous = search.getAttribute("data-settled");
              search.setAttribute("data-settled", mark);
              return previous === mark && Math.abs(a.y - b.y) < 8;
            }"""
        )

        def menus_fit(width):
            page.set_viewport_size({"width": width, "height": 900})
            page.wait_for_selector("article.card .more-toggle")
            overflow = page.evaluate(
                """() => [...document.querySelectorAll("article.card")].flatMap((card) => {
                  const limit = card.getBoundingClientRect().right + 1;
                  return [...card.querySelectorAll(".actions > button, .actions .more-toggle")].filter((el) => {
                    const box = el.getBoundingClientRect();
                    return box.width > 0 && box.right > limit;
                  }).map((el) => el.innerText.trim());
                })"""
            )
            assert overflow == [], (width, overflow)
            page.evaluate("() => document.querySelectorAll('.more .menu').forEach((node) => node.classList.add('hidden'))")
            toggles = page.locator("article.card:visible .more-toggle")
            for index in range(toggles.count()):
                page.evaluate("() => document.querySelectorAll('.more .menu').forEach((node) => node.classList.add('hidden'))")
                toggles.nth(index).click()
                page.wait_for_function(
                    """() => {
                      const menu = document.querySelector(".more .menu:not(.hidden)");
                      if (!menu || menu.dataset.placed !== "1") return false;
                      const box = menu.getBoundingClientRect();
                      return box.width > 20 && box.height > 20;
                    }"""
                )
                fit = page.evaluate(
                    """() => {
                      const menu = document.querySelector(".more .menu:not(.hidden)").getBoundingClientRect();
                      const side = document.querySelector(".sidebar").getBoundingClientRect();
                      const overlaps = !(menu.right <= side.left + 1 || menu.left >= side.right - 1 || menu.bottom <= side.top + 1 || menu.top >= side.bottom - 1);
                      const inside = menu.left >= -1 && menu.top >= -1 && menu.right <= window.innerWidth + 1 && menu.bottom <= window.innerHeight + 1;
                      return { inside, overlaps, left: menu.left, top: menu.top, right: menu.right, bottom: menu.bottom };
                    }"""
                )
                assert fit["inside"] and not fit["overlaps"], (width, index, fit)
            page.evaluate("() => document.querySelectorAll('.more .menu').forEach((node) => node.classList.add('hidden'))")

        for width in (600, 800, 1024, 1280):
            menus_fit(width)
        page.click("aside button[data-page=power]")
        page.wait_for_selector("#hw-tabs")
        for width in (600, 800, 1024, 1280):
            menus_fit(width)
        page.set_viewport_size({"width": 1280, "height": 900})
        page.click("aside button[data-page=devices]")
        page.wait_for_selector("article.card")
        row = page.evaluate(
            """() => {
              const card = [...document.querySelectorAll("article.card")].find((node) => node.dataset.kind === "device" && node.innerText.includes("Office PC"));
              const tops = [...card.querySelectorAll(".actions > button, .actions .more-toggle")].map((el) => el.getBoundingClientRect().top);
              return { tops, spread: Math.max(...tops) - Math.min(...tops) };
            }"""
        )
        assert row["spread"] < 4, row
        tv_card = page.locator("article", has_text="Living TV")
        assert tv_card.get_by_role("button", name="Reset").count() == 0
        assert tv_card.get_by_role("button", name="Wake", exact=False).count() >= 1
        office = page.locator("article", has_text="Office PC")
        office.locator(".more-toggle").click()
        office.get_by_role("button", name="Edit").click()
        page.wait_for_selector("#device-form")
        order = page.evaluate(
            """() => {
              const pick = document.querySelector("#new-method-kind");
              const add = document.querySelector("#add-method");
              pick.value = "plug";
              add.click();
              pick.value = "jetkvm";
              add.click();
              return [...document.querySelectorAll("#method-list details.method-row")].map((node) => node.dataset.kind);
            }"""
        )
        assert order.index("jetkvm") < order.index("wol") < order.index("plug")
        browser.close()
