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
        ("#conversationToggle", .08, 1.02),
        (".promptbar", .04, .02),
        ("#orrery", .08, .15),
        ("#mail", .957, .025),
        (".topstat.crew", .94, 1.92),
        ("#networkBtn", .91, 1.04),
        ("#settingsBtn", .12, 1.04),
        ("#usageBtn", .93, 1.04),
        ("#planetariumBtn", .50, 1.04),
        ("#rosterSelectBtn", .12, 1.04),
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


def cut(gallery, name, frames, size):
    pictures = []
    for image, hold in frames:
        limit = tuple(min(target, round(source * 1.35)) for source, target in zip(image.size, size))
        fitted = ImageOps.contain(image, limit, method=Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", size, "#101114")
        canvas.paste(fitted, ((size[0] - fitted.width) // 2, (size[1] - fitted.height) // 2))
        pictures.append((canvas, hold))
    gallery.gif(GUIDES / name, pictures)


def header_control_frame(camera, gallery, selector):
    area = union_crop(camera, (".topstat.crew", ".header-actions", "#usageBtn"))
    image = gallery.frame(crop=area)
    left, top, right, bottom = camera.rect(selector)
    pen = ImageDraw.Draw(image)
    pen.rounded_rectangle((left-area[0], top-area[1], right-area[0], bottom-area[1]),
                          radius=5, outline="#e5a75a", width=2)
    return image


def panel_frame(camera, gallery, selector, *, height=None):
    return gallery.frame(crop=crop_rect(camera, selector, padding=8, height=height))


def union_crop(camera, selectors):
    boxes = [crop_rect(camera, selector, padding=8) for selector in selectors]
    return min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)


def move_pointer(camera, selector, *, click=False):
    left, top, right, bottom = camera.rect(selector)
    point = {"x": (left + right) / 2, "y": (top + bottom) / 2}
    camera.page.call("Input.dispatchMouseEvent", type="mouseMoved", **point)
    if click:
        for event in ("mousePressed", "mouseReleased"):
            camera.page.call("Input.dispatchMouseEvent", type=event, button="left", clickCount=1, **point)


def save_first_flight(camera, gallery):
    camera.click("#settingsBtn")
    camera.wait("document.getElementById('settingsPopover').matches(':popover-open')")
    camera.js("document.getElementById('firstFlightBtn').scrollIntoView({block:'center'})")
    menu = panel_frame(camera, gallery, ".flight-settings")
    camera.click("#firstFlightBtn")
    camera.wait("document.querySelector('.flight-guide[data-tour=first-flight]:not([hidden])')")
    panel = ".flight-guide[data-tour=first-flight] .flight-panel"
    frames = [(menu, 1800), (panel_frame(camera, gallery, panel, height=463), 2450)]
    camera.click(".flight-guide[data-tour=first-flight] [data-step=talk] .flight-line")
    camera.wait("OrreryTour.firstFlight.state.current.id==='talk'")
    frames.append((panel_frame(camera, gallery, panel, height=463), 2100))
    cut(gallery, "first-flight.gif", frames, (475, 479))
    camera.click(".flight-guide[data-tour=first-flight] .flight-close")

    camera.click("#settingsBtn")
    camera.js("document.getElementById('helpMapBtn').scrollIntoView({block:'center'})")
    menu = panel_frame(camera, gallery, ".flight-settings")
    camera.click("#helpMapBtn")
    camera.wait("document.querySelector('.flight-map:not([hidden]) .flight-map-note[data-step=settings]').offsetWidth")
    time.sleep(.2)
    area = union_crop(camera, (
        "#settingsBtn",
        ".flight-map-note[data-step=settings]",
        ".flight-map-note[data-step=usage]",
    ))
    cut(gallery, "help-map.gif", [(menu, 1850), (gallery.frame(crop=area), 4250)], (650, 360))
    camera.click(".flight-map-close")


def save_usage(camera, gallery):
    activity = union_crop(camera, (".topstat.crew", "#needChip"))
    gallery.still(GUIDES / "agent-activity.png", crop=activity)
    button = header_control_frame(camera, gallery, "#usageBtn")
    camera.click("#usageBtn")
    camera.wait("document.querySelector('#usagePopover:popover-open .up-reset')?.textContent.includes('next reset')")
    popup = panel_frame(camera, gallery, "#usagePopover")
    cut(gallery, "check-usage.gif", [(button, 1550), (popup, 4750)], (540, 334))
    camera.js("document.getElementById('usagePopover').hidePopover()")


def save_settings(camera, gallery):
    camera.click("#settingsBtn")
    frames = []
    for selector, change, duration in (
        ("#colorThemePreference", "this.value='light';this.dispatchEvent(new Event('change',{bubbles:true}));", 2300),
        ("#terminalFontSize", "this.value='15';this.dispatchEvent(new Event('input',{bubbles:true}));", 2050),
        ("#miniViewNetwork", "this.click();", 2300),
    ):
        camera.js(f"""(() => {{
          const control=document.querySelector({json.dumps(selector)});
          control.scrollIntoView({{block:'center'}});
          (function(){{{change}}}).call(control);
        }})()""")
        time.sleep(.17)
        area = camera.js(f"""(() => {{
          const row = document.querySelector({json.dumps(selector)}).closest('.settings-row')
            || document.querySelector({json.dumps(selector)}).closest('section');
          const b=row.getBoundingClientRect(), panel=document.querySelector('#settingsPopover').getBoundingClientRect();
          return [Math.round(panel.left),Math.max(0,Math.round(b.top-15)),
            Math.round(panel.right),Math.min(innerHeight,Math.round(b.bottom+15))];
        }})()""")
        frames.append((gallery.frame(crop=area), duration))
    cut(gallery, "adjust-cockpit.gif", frames, (535, 206))
    camera.click("#miniViewOrrery")
    camera.js("""const theme=document.getElementById('colorThemePreference');
      theme.value='dark';theme.dispatchEvent(new Event('change',{bubbles:true}));
      document.getElementById('settingsPopover').hidePopover()""")


def save_planetarium(camera, gallery):
    header = header_control_frame(camera, gallery, "#planetariumBtn")
    camera.click("#planetariumBtn")
    planet_agent = ".planet-agent[data-agent=BrightHopper]"
    camera.wait(f"document.querySelector('#planetariumOverlay.on {planet_agent}')")
    areas = camera.js("""(() => {
      const rects = [...document.querySelectorAll('.planet-agent')].map(n=>n.getBoundingClientRect());
      return [Math.max(0,Math.round(Math.min(...rects.map(r=>r.left))-12)),
        Math.max(0,Math.round(Math.min(...rects.map(r=>r.top))-12)),
        Math.min(innerWidth,Math.round(Math.max(...rects.map(r=>r.right))+12)),
        Math.min(innerHeight,Math.round(Math.max(...rects.map(r=>r.bottom))+12))];
    })()""")
    graph = gallery.frame(crop=areas)
    move_pointer(camera, planet_agent + " .orrery-hit", click=True)
    camera.wait("activeSession()==='BrightHopper' && !document.getElementById('planetariumOverlay').classList.contains('on')")
    target = panel_frame(camera, gallery, ".screen", height=184)
    cut(gallery, "planetarium.gif", [(header, 1100), (graph, 3650), (target, 2050)], (675, 303))
    camera.click("#roster [data-agent=AmberCurie]")
    camera.wait("activeSession()==='AmberCurie'")


def save_mini_details(camera, gallery):
    target = "#orrery .mini-agent[data-agent=PatientFaraday] .orrery-hit"
    rail = crop_rect(camera, "#mailRail", padding=0, height=530)
    frames = [(gallery.frame(crop=rail), 1250)]
    move_pointer(camera, target)
    camera.wait("!agentDetail.hidden && agentDetail.querySelector('[data-browser=temporary]')")
    frames.append((gallery.frame(crop=rail), 3500))
    move_pointer(camera, "#newAgentBtn")
    camera.wait("agentDetail.hidden")
    frames.append((gallery.frame(crop=rail), 1300))
    gallery.gif(GUIDES / "mini-graph-detail.gif", frames)

    move_pointer(camera, "#roster [data-agent=PatientFaraday]")
    camera.wait("!agentDetail.hidden && agentDetail.querySelector('[data-browser=temporary]')")
    gallery.still("docs/images/cockpit_roster_detail.png", crop=crop_rect(camera, "#agentDetail"))
    move_pointer(camera, "#newAgentBtn")
    camera.wait("agentDetail.hidden")

    graph = crop_rect(camera, "#orrery", padding=5)
    ready = gallery.frame(crop=graph)
    move_pointer(camera, target)
    camera.wait("!agentDetail.hidden && agentDetail.querySelector('[data-computer=off]')")
    camera.click("#agentDetail [data-computer=off]")
    camera.wait("document.querySelector('.agent-permission-confirm[open]')")
    prompt = panel_frame(camera, gallery, ".agent-permission-confirm")
    camera.js("permissionApply.click()")
    camera.wait("document.querySelector('#orrery .mini-agent[data-agent=PatientFaraday]')?.textContent.includes('Restarting')")
    pending = gallery.frame(crop=graph)
    camera.wait("!pendingAgentAction('PatientFaraday')")
    camera.js("pollAgents()")
    camera.wait("document.querySelector('#orrery .mini-agent[data-agent=PatientFaraday]') && currentAgentNamed('PatientFaraday').computer_use==='off'")
    restored = gallery.frame(crop=graph)
    cut(gallery, "mini-graph-restart.gif", [(ready, 1150), (prompt, 1600), (pending, 2350), (restored, 1750)], (560, 330))


def save_select(camera, gallery):
    roster = crop_rect(camera, ".col.roster", padding=0, height=455)
    frames = [(gallery.frame(crop=roster), 1100)]
    camera.click("#rosterSelectBtn")
    camera.click("#roster [data-agent=WarmLovelace]")
    camera.click("#roster [data-agent=PatientFaraday]")
    camera.wait("document.getElementById('rosterBulkCount').textContent.includes('2 selected')")
    frames.append((gallery.frame(crop=roster), 2050))
    camera.click("#rosterBulkExit")
    camera.wait("document.getElementById('rosterBulkExit').textContent.includes('Confirm')")
    frames.append((gallery.frame(crop=roster), 3000))
    gallery.gif(GUIDES / "select-agents.gif", frames)
    camera.click("#rosterSelectBtn")


def save_telemetry(camera, gallery):
    header = header_control_frame(camera, gallery, "#networkBtn")
    camera.click("#networkBtn")
    camera.wait("networkFrame.contentDocument?.querySelector('#demo-card .go')", timeout=18)
    camera.js("""(async () => {
      const win=networkFrame.contentWindow, doc=networkFrame.contentDocument;
      doc.querySelector('#demo-card .go').click();
      doc.querySelector('#demo-strip')?.remove();
      doc.querySelector('#demo-ring')?.remove();
      const demo=win.AGENTSTACK_DEMO;
      demo.stories['docs-reel']=await (await fetch('/fixture-reel')).json();
      demo.useStory('docs-reel');
      const frozen=win.Date.now()+38000;
      win.Date.now=()=>frozen;
      win.setView('net');
      await win.netTick();
      win.openPanel('Bright-Curie');
    })()""")
    camera.wait("networkFrame.contentDocument?.querySelector('#term .tm-box')?.innerText.includes('OPEN IN COCKPIT')")
    areas = camera.js("""(() => {
      const iframe=networkFrame.getBoundingClientRect(), doc=networkFrame.contentDocument;
      const panel=doc.querySelector('#term .tm-box').getBoundingClientRect();
      const actions=doc.querySelector('#tm-exit-btn').getBoundingClientRect();
      const left=Math.round(iframe.left+panel.left), top=Math.round(iframe.top+panel.top);
      const right=Math.round(iframe.left+panel.right), actionStart=Math.round(iframe.left+actions.left-8);
      return [[left,top,left+570,Math.min(innerHeight,top+268)],
        [Math.max(0,actionStart),top,Math.min(innerWidth,right),top+83]];
    })()""")
    cut(gallery, "view-telemetry.gif", [
        (header, 1250), (gallery.frame(crop=areas[0]), 3200), (gallery.frame(crop=areas[1]), 2400)
    ], (680, 320))
    camera.click("#networkClose")


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
    camera.js("document.querySelector('.maildrawer .drawer-head button').click()")
    save_first_flight(camera, gallery)
    save_usage(camera, gallery)
    save_settings(camera, gallery)
    save_planetarium(camera, gallery)
    save_mini_details(camera, gallery)
    save_select(camera, gallery)
    save_telemetry(camera, gallery)
