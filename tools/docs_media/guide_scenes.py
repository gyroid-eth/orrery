"""Capture the task guides from the real cockpit and number its screen map."""

from __future__ import annotations

import base64
import io
import json
import subprocess
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from scenes import Gallery

GUIDES = Path("docs/images/guides")
VIEWPORT = (1320, 760)
PREFERENCES = """
localStorage.setItem('oc-first-flight-v1','{"seen":true,"open":false}');
localStorage.setItem('oc-full-tour-v1','{"seen":true,"open":false}');
localStorage.setItem('orrery.color-theme.v1','dark');
localStorage.setItem('oc-mini-mail-graph','1');
localStorage.setItem('oc-mini-graph-height','248');
"""


class GuideFrames:
    def __init__(self, camera):
        self.camera = camera
        self.use_screenshot = True

    def shot(self):
        page = self.camera.page
        if self.use_screenshot:
            try:
                shot = page.call("Page.captureScreenshot", timeout=3, format="png",
                                 fromSurface=True, captureBeyondViewport=False)
                image = Image.open(io.BytesIO(base64.b64decode(shot["data"]))).convert("RGB")
                if image.size == VIEWPORT:
                    return image
            except TimeoutError:
                pass
            self.use_screenshot = False

        width, height = VIEWPORT
        pdf = page.call("Page.printToPDF", printBackground=True, paperWidth=width / 96,
                        paperHeight=height / 96, marginLeft=0, marginRight=0,
                        marginTop=0, marginBottom=0)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "frame"
            source = output.with_suffix(".pdf")
            source.write_bytes(base64.b64decode(pdf["data"]))
            subprocess.run(
                ["pdftoppm", "-singlefile", "-r", "96", "-png", source, output],
                check=True,
            )
            with Image.open(output.with_suffix(".png")) as image:
                return image.convert("RGB").crop((0, 0, width, height))


def crop_rect(camera, selector, *, padding=3, height=None):
    left, top, right, bottom = camera.rect(selector)
    if height is not None:
        bottom = min(bottom, top + height)
    return (
        max(0, round(left - padding)), max(0, round(top - padding)),
        min(VIEWPORT[0], round(right + padding)), min(VIEWPORT[1], round(bottom + padding)),
    )


def save_map(camera, gallery, destination):
    image = gallery.frame()
    pen = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=17)
    # In the same order as the legend in docs/cockpit-map.md.
    markers = [
        ("#newAgentBtn", .79, 1.22),
        ("#roster", .09, .16),
        ("#conversationToggle", -.85, .5),
        (".promptbar", .04, -.10),
        ("#orrery", .08, .15),
        ("#mail", .94, .035),
        (".topstat.crew", .52, 1.92),
        ("#networkBtn", .48, 1.64),
        ("#settingsBtn", .48, 1.64),
    ]
    radius = 13
    for number, (selector, fx, fy) in enumerate(markers, 1):
        left, top, right, bottom = camera.rect(selector)
        x, y = left + (right - left) * fx, top + (bottom - top) * fy
        pen.ellipse((x-radius, y-radius, x+radius, y+radius), fill="#fff3d8",
                    outline="#d98a32", width=2)
        pen.text((x, y), str(number), font=font, anchor="mm", fill="#22222a")
    image.save(destination / GUIDES / "cockpit-map.png")


def select_reader(camera):
    camera.click("#conversationToggle")
    camera.wait("document.querySelector('.conversation-file')")
    if not camera.js("document.querySelector('.screen').classList.contains('conversation-full')"):
        camera.click(".conversation-expand")
    camera.wait("document.querySelector('.screen').classList.contains('conversation-full')")
    # Let the rail transition settle before taking a discrete shot.
    time.sleep(.26)


def save_read_file(camera, gallery):
    select_reader(camera)
    area = crop_rect(camera, ".screen", height=430)
    frames = [(gallery.frame(crop=area), 1500)]
    camera.js("document.querySelector('.conversation-file').focus()")
    frames.append((gallery.frame(crop=area), 650))
    camera.click(".conversation-file")
    camera.wait("document.querySelector('.conversation-preview:not([hidden])')?.innerText.includes('Task board')")
    time.sleep(.24)
    frames.append((gallery.frame(crop=area), 3850))
    gallery.gif(GUIDES / "read-a-file.gif", frames)
    camera.js("conversationView.close()")


def type_in_cuts(camera, gallery, selector, chunks, frames, area):
    for text, hold in chunks:
        camera.input(selector, text)
        frames.append((gallery.frame(crop=area), hold))


def save_start(camera, gallery):
    camera.click("#newAgentBtn")
    camera.wait("spawnOverlay.classList.contains('on') && spawnCatalog?.providers?.length>=5")
    camera.click("#spawnDirButton")
    camera.wait("!document.querySelector('#spawnDirUse').disabled")
    camera.click("#spawnDirUse")
    camera.wait("document.querySelector('#spawnDirSheet').hidden")

    launch = crop_rect(camera, "#spawnLauncher", padding=20)
    frames = [(gallery.frame(crop=launch), 660)]
    type_in_cuts(camera, gallery, "#spawnTask",
                 [("Review the ", 240), ("task board", 1160)], frames, launch)
    camera.wait("!document.querySelector('#spawnSubmit').disabled")
    camera.click("#spawnSubmit")
    camera.wait("!spawnOverlay.classList.contains('on') || spawnStatus.classList.contains('error')")
    if camera.js("spawnOverlay.classList.contains('on')"):
        raise RuntimeError(camera.js("spawnStatus.textContent"))
    camera.js("pollAgents()")
    camera.wait("document.querySelector('#roster [data-agent=WarmLovelace]') && availableSessions.has('WarmLovelace')")
    new_agent = "#roster [data-agent=WarmLovelace]"
    camera.click(new_agent)
    camera.wait("activeSession()==='WarmLovelace'")
    time.sleep(.32)
    left, top, right, bottom = crop_rect(camera, new_agent, padding=10)
    frames.append((gallery.frame(crop=(left, max(56, top - 65), right, bottom)), 950))
    compose = crop_rect(camera, ".promptbar", padding=8)
    type_in_cuts(camera, gallery, "#promptInput",
                 [("What should we ", 260), ("work on next?", 1160)], frames, compose)
    camera.key("Enter")
    camera.wait("document.querySelector('#promptInput').value===''")
    select_reader(camera)
    frames.append((gallery.frame(crop=crop_rect(camera, ".screen", height=365)), 2600))
    color = "#101114"
    size = (760, 346)
    gallery.gif(GUIDES / "start-an-agent.gif", [
        (ImageOps.pad(image, size, color=color), duration) for image, duration in frames
    ])
    camera.js("conversationView.close();focusSession('AmberCurie');renderStage()")


def collect_screencast(page, seconds, crop):
    frames = []
    last_frame = float("-inf")
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            packet = json.loads(page.socket.recv(timeout=.25))
        except TimeoutError:
            continue
        if packet.get("method") != "Page.screencastFrame":
            continue
        event = packet["params"]
        page.socket.send(json.dumps({
            "id": next(page.sequence), "method": "Page.screencastFrameAck",
            "params": {"sessionId": event["sessionId"]},
        }))
        metadata = event["metadata"]
        timestamp = metadata["timestamp"]
        if timestamp - last_frame < .092:
            continue
        last_frame = timestamp
        image = Image.open(io.BytesIO(base64.b64decode(event["data"]))).convert("RGB")
        scale = image.width / metadata["deviceWidth"]
        frames.append((timestamp, image.crop(tuple(round(edge * scale) for edge in crop))))
    return frames


def save_read_mail(camera, gallery):
    camera.wait("activeSession()==='AmberCurie' && document.querySelector('.mail-request')")
    camera.page.call("Emulation.setEmulatedMedia", features=[
        {"name": "prefers-reduced-motion", "value": "no-preference"},
    ])
    left, top, right, _ = crop_rect(camera, "#mailRail")
    crop = left, top, right, min(top + 526, VIEWPORT[1])
    page = camera.page
    page.call("Page.startScreencast", format="jpeg", quality=86,
              maxWidth=1600, maxHeight=1000, everyNthFrame=1)
    try:
        camera.js("""
        (() => {
          setTimeout(async () => {
            await fetch('/fixture-guide-mail', {method:'POST'});
            await pollMail();
          }, 650);
          setTimeout(() => {
            const row = [...document.querySelectorAll('.mail-request')]
              .find(item => item.textContent.includes('Task board reviewed'));
            row?.click();
          }, 3600);
          return true;
        })()
        """)
        frames = collect_screencast(page, 5, crop)
    finally:
        page.call("Page.stopScreencast")
    if len(frames) < 10:
        raise RuntimeError("Mail screencast did not capture the arrival")
    camera.wait("document.querySelector('.drawer-body')?.innerText.includes('experiment notes')")
    pictures = [
        (image, min(1000, max(90, round((after-before) * 100) * 10)))
        for (before, image), (after, _) in zip(frames, frames[1:])
    ]
    pictures.append((frames[-1][1], 6800 - sum(duration for _, duration in pictures)))
    if pictures[-1][1] < 1300:
        raise RuntimeError("The Mail preview needs time to be read")
    gallery.gif(GUIDES / "read-mail.gif", pictures)


def save_guides(camera, destination, url):
    (destination / GUIDES).mkdir(parents=True, exist_ok=True)
    camera.open(url + "/cockpit.html?demo=1", """
      typeof availableSessions !== 'undefined' && availableSessions.has('AmberCurie')
    """, PREFERENCES)
    camera.js("""
      const printStyle=document.createElement('style');
      printStyle.textContent='@media print{.app{height:759px}}';
      document.head.append(printStyle);
      document.querySelector('.grid').style.setProperty('--mail-width','406px');
      Promise.all([pollAgents(),pollGraph(),pollMail(),document.fonts.ready])
    """)
    camera.wait("document.querySelector('#roster [data-agent=AmberCurie]')")
    camera.click("#roster [data-agent=AmberCurie]")
    camera.wait("""
      activeSession()==='AmberCurie' &&
      document.querySelectorAll('#orrery .mini-agent').length>=4 &&
      document.querySelector('.mail-request')
    """)
    gallery = Gallery(destination, GuideFrames(camera))
    save_map(camera, gallery, destination)
    save_read_file(camera, gallery)
    save_start(camera, gallery)
    save_read_mail(camera, gallery)
