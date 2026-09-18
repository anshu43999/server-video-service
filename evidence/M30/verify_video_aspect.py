from pathlib import Path

from playwright.sync_api import Page, sync_playwright


ADMIN_URL = "http://127.0.0.1:8080/admin/"
OUTPUT_DIR = Path(__file__).resolve().parent


def load_demo_streams(page: Page) -> None:
    page.goto(ADMIN_URL)
    page.wait_for_timeout(700)
    page.evaluate(
        """
        document.body.classList.remove("auth-locked");
        state.demo = true;
        state.streams = MOCK.streams.map(stream => ({
          stream_id: stream[0],
          source: stream[1],
          frames_received: stream[2],
          yolo_enabled: stream[3],
          confidence: stream[4],
          max_fps: stream[5],
          tag: stream[6],
          state: stream[2] ? "online" : "waiting",
          publish_state: stream[2] ? "connected" : "idle",
        }));
        """
    )


def image_metrics(page: Page, selector: str) -> dict[str, object]:
    return page.locator(selector).first.evaluate(
        """
        image => ({
          objectFit: getComputedStyle(image).objectFit,
          containerWidth: image.clientWidth,
          containerHeight: image.clientHeight,
          imageWidth: image.naturalWidth,
          imageHeight: image.naturalHeight,
        })
        """
    )


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)

        desktop = browser.new_page(viewport={"width": 1440, "height": 900})
        load_demo_streams(desktop)
        desktop.evaluate(
            """
            state.selected = state.streams[0].stream_id;
            renderStreams();
            renderInspector();
            document.querySelector('[data-view="streams"]').click();
            """
        )
        desktop.wait_for_timeout(700)
        desktop_metrics = image_metrics(desktop, ".stream-preview-image")
        print({"desktop": desktop_metrics}, flush=True)
        desktop.screenshot(
            path=OUTPUT_DIR / "M30-T03-desktop-streams.png",
        )

        mobile = browser.new_page(viewport={"width": 390, "height": 844})
        mobile.set_content(
            """
            <!doctype html>
            <html lang="zh-CN">
            <head>
              <meta charset="utf-8">
              <link rel="stylesheet" href="http://127.0.0.1:8080/admin/styles.css">
              <style>body { margin: 0; padding: 16px; }</style>
            </head>
            <body>
              <div class="dashboard-stream-wall">
              <article class="dashboard-stream-card">
                <div class="dashboard-stream-media">
                  <img src="http://127.0.0.1:8080/admin/evidence/evidence_helmet_violation.png" alt="移动视口比例验证">
                  <span class="stream-live-badge"><i></i>LIVE</span>
                </div>
                <div class="dashboard-stream-meta"><b>aspect-check</b></div>
              </article>
              </div>
            </body>
            </html>
            """
        )
        mobile.wait_for_timeout(700)
        mobile_metrics = image_metrics(mobile, ".dashboard-stream-media img")
        print({"mobile": mobile_metrics}, flush=True)
        mobile.screenshot(
            path=OUTPUT_DIR / "M30-T03-mobile-dashboard.png",
        )

        browser.close()

    if desktop_metrics["objectFit"] != "contain":
        raise SystemExit("desktop stream preview is not using contain")
    if mobile_metrics["objectFit"] != "contain":
        raise SystemExit("mobile dashboard stream preview is not using contain")


if __name__ == "__main__":
    main()
