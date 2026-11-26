"""Capture an isolated browser context through an existing Chrome CDP service."""

from __future__ import annotations

import base64
import io
import itertools
import json
import time
import urllib.request
from contextlib import contextmanager

from PIL import Image
from websockets.sync.client import connect


class CDP:
    def __init__(self, address):
        self.socket = connect(address, max_size=32 * 1024 * 1024, open_timeout=6)
        self.sequence = itertools.count(1)

    def call(self, method, timeout=12, **params):
        request = next(self.sequence)
        self.socket.send(json.dumps(dict(id=request, method=method, params=params)))
        deadline = time.monotonic() + timeout
        while True:
            result = json.loads(
                self.socket.recv(timeout=max(0, deadline - time.monotonic()))
            )
            if result.get("id") != request:
                continue
            if "error" in result:
                raise RuntimeError(f"{method}: {result['error']}")
            return result.get("result", {})


class Camera:
    def __init__(self, page, viewport, phone):
        self.page = page
        width, height = viewport
        self.phone = phone
        self.scale = 2 if phone else 1
        self.size = (width * self.scale, height * self.scale)
        self.page.call("Page.enable")
        self.page.call("Runtime.enable")
        self.page.call(
            "Emulation.setDeviceMetricsOverride",
            width=width,
            height=height,
            deviceScaleFactor=self.scale,
            mobile=phone,
        )
        self.page.call("Emulation.setTimezoneOverride", timezoneId="UTC")
        self.page.call("Emulation.setFocusEmulationEnabled", enabled=True)
        self.page.call("Network.enable")
        self.page.call(
            "Network.setBlockedURLs",
            urls=[
                "http://127.0.0.1:8770/*",
                "http://127.0.0.1:8765/*",
                "http://127.0.0.1:8791/*",
                "http://127.0.0.1:9443/*",
                "https://127.0.0.1:9443/*",
            ],
        )

    def resize(self, width, height):
        self.page.call(
            "Emulation.setDeviceMetricsOverride",
            width=width,
            height=height,
            deviceScaleFactor=self.scale,
            mobile=self.phone,
        )
        self.size = (width * self.scale, height * self.scale)

    def js(self, source):
        result = self.page.call(
            "Runtime.evaluate",
            expression=source,
            returnByValue=True,
            awaitPromise=True,
            userGesture=True,
        )
        if "exceptionDetails" in result:
            raise RuntimeError(
                result["result"].get("description", result["exceptionDetails"]["text"])
            )
        return result["result"].get("value")

    def wait(self, condition, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.js(f"Boolean({condition})"):
                return
            time.sleep(0.1)
        raise RuntimeError(f"Page did not reach the capture state: {condition}")

    def open(self, url, ready, init=None):
        if init:
            self.page.call("Page.addScriptToEvaluateOnNewDocument", source=init)
        self.page.call("Page.bringToFront")
        self.page.call("Page.navigate", url=url)
        self.wait(ready, timeout=20)

    def click(self, selector):
        self.js(f"document.querySelector({json.dumps(selector)}).click()")

    def key(self, key):
        code = {"Enter": 13, "Escape": 27}[key]
        for event in ("keyDown", "keyUp"):
            self.page.call(
                "Input.dispatchKeyEvent",
                type=event,
                key=key,
                code=key,
                windowsVirtualKeyCode=code,
            )

    def input(self, selector, text):
        self.js(f"document.querySelector({json.dumps(selector)}).focus()")
        self.page.call("Input.insertText", text=text)

    def rect(self, selector):
        return self.js(f"""(()=>{{
            const r=document.querySelector({json.dumps(selector)}).getBoundingClientRect();
            return [r.left,r.top,r.right,r.bottom];
        }})()""")

    def shot(self):
        # Capture from this target's surface only. Window capture can show
        # another tab when a second client is using the same Chrome service.
        self.page.call("Page.bringToFront")
        time.sleep(0.18)
        for attempt in range(3):
            try:
                screenshot = self.page.call(
                    "Page.captureScreenshot",
                    timeout=7,
                    format="png",
                    fromSurface=True,
                    captureBeyondViewport=False,
                )
                break
            except TimeoutError:
                if attempt == 2:
                    raise
                self.page.call("Page.bringToFront")
        image = Image.open(io.BytesIO(base64.b64decode(screenshot["data"]))).convert(
            "RGB"
        )
        if image.width != self.size[0] or image.height < self.size[1]:
            raise RuntimeError(f"Expected the {self.size} viewport, got {image.size}")
        return image.crop((0, 0, *self.size))


@contextmanager
def camera(endpoint, viewport, phone=False):
    def request(path):
        with urllib.request.urlopen(endpoint.rstrip("/") + path, timeout=6) as reply:
            return json.load(reply)

    browser = CDP(request("/json/version")["webSocketDebuggerUrl"])
    try:
        context = browser.call("Target.createBrowserContext", disposeOnDetach=True)[
            "browserContextId"
        ]
        try:
            target = browser.call(
                "Target.createTarget", url="about:blank", browserContextId=context
            )["targetId"]
            page = next(
                entry for entry in request("/json/list") if entry["id"] == target
            )
            connection = CDP(page["webSocketDebuggerUrl"])
            try:
                yield Camera(connection, viewport, phone)
            finally:
                connection.socket.close()
        finally:
            browser.call("Target.disposeBrowserContext", browserContextId=context)
    finally:
        browser.socket.close()
