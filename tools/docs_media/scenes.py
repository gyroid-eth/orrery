"""Documentation scenes on the real cockpit, dashboard and phone pages."""

from __future__ import annotations

from PIL import Image, ImageOps


class Gallery:
    def __init__(self, destination, camera):
        self.root = destination
        self.camera = camera

    def still(self, path, size=None, crop=None):
        image = self.frame(size, crop)
        output = self.root / path
        output.parent.mkdir(parents=True, exist_ok=True)
        image.save(output, **({"quality": 91} if output.suffix == ".jpg" else {}))
        print(path, flush=True)

    def frame(self, size=None, crop=None):
        image = self.camera.shot()
        if crop:
            image = image.crop(crop)
        return (
            ImageOps.pad(
                image,
                size,
                method=Image.Resampling.LANCZOS,
                color=image.getpixel((0, 0)),
            )
            if size
            else image
        )

    def gif(self, path, frames):
        output = self.root / path
        output.parent.mkdir(parents=True, exist_ok=True)
        images, durations = zip(*frames, strict=True)
        sample = Image.new("RGB", (180, 120 * len(images)))
        for index, image in enumerate(images):
            sample.paste(ImageOps.contain(image, (180, 120)), (0, 120 * index))
        palette = sample.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
        images = [
            image.quantize(palette=palette, dither=Image.Dither.NONE)
            for image in images
        ]
        images[0].save(
            output,
            save_all=True,
            append_images=images[1:],
            duration=durations,
            disposal=1,
            loop=0,
            optimize=False,
        )
        print(path, flush=True)

    def type_frames(self, selector, text, size=None, crop=None):
        frames = []
        for char in text:
            self.camera.input(selector, char)
            frames.append((self.frame(size, crop), 95))
        frames[-1] = (frames[-1][0], 1250)
        return frames


def save_cockpit(c, root, url):
    d = Gallery(root, c)
    j = c.js
    c.open(
        url + "/cockpit.html?demo=1",
        "document.documentElement?.dataset.demo==='on' && typeof availableSessions!=='undefined' && availableSessions.size>=7",
        """localStorage.setItem('oc-first-flight-v1','{"seen":true,"open":false}');
              localStorage.setItem('oc-full-tour-v1','{"seen":true,"open":false}');
              localStorage.setItem('orrery.demo-mask-locations.v1','0');
              localStorage.setItem('oc-term-font','15');""",
    )
    j("Promise.all([pollAgents(),pollGraph(),pollMail()])")
    c.wait("document.querySelector('#roster [data-agent]')")
    c.click("#newAgentBtn")
    c.wait("spawnCatalog?.providers?.length>=5")
    c.input("#spawnTask", "Review keyboard navigation.")
    c.click("#spawnModelButton")
    c.wait("!document.getElementById('spawnModelSheet').hidden")
    box = c.rect("#spawnLauncher")
    sheet = c.rect("#spawnModelSheet")
    launch_crop = (
        int(box[0]) - 18,
        int(box[1]) - 16,
        int(box[2]) + 18,
        max(int(sheet[3]) + 35, int(box[3]) + 208),
    )
    launch_size = (
        1000,
        round(
            (launch_crop[3] - launch_crop[1]) * 1000 / (launch_crop[2] - launch_crop[0])
        ),
    )
    frames = [(d.frame(launch_size, launch_crop), 1250)]
    c.click('#providerTabs [data-family="deepseek"]')
    c.wait("!document.getElementById('spawnHarnesses').hidden")
    frames.append((d.frame(launch_size, launch_crop), 2050))
    c.click('#providerTabs [data-family="local"]')
    frames.append((d.frame(launch_size, launch_crop), 2100))
    c.click("#spawnModelButton")
    c.click("#spawnComputerUse")
    c.wait("document.getElementById('spawnComputerMenu').matches(':popover-open')")
    frames.append((d.frame(launch_size, launch_crop), 2050))
    c.click("#spawnComputerUse")
    c.click("#spawnBrowserUse")
    c.wait("document.getElementById('spawnBrowserMenu').matches(':popover-open')")
    frames.append((d.frame(launch_size, launch_crop), 2200))
    d.gif("docs/images/cockpit-native-spawn.gif", frames)
    j("closeSpawnModal()")

    c.resize(1220, 740)
    j(
        "window.captureNames=['AmberCurie','PatientFaraday','NimbleTuring'];captureNames.forEach(name=>requestAttach(name,true))"
    )
    c.wait("panes.size>=3")
    j(
        "replaceSplitSessions(captureNames);splitVisible=true;focusSplitSession('AmberCurie');selectSplitPreset('wide')"
    )
    c.click("#mailGraphBtn")
    c.wait("document.querySelectorAll('.split-cell').length===3")
    j("terminalFontSize=14;applyTerminalSettings()")
    d.still("docs/images/cockpit_overview.png", (1488, 900))
    j(
        "replaceSplitSessions([]);splitVisible=false;focusSession('AmberCurie');renderStage()"
    )
    j("conversationView.open()")
    c.wait(
        "document.querySelectorAll('.conversation-event').length>=4 && document.querySelector('.conversation-table-copy')"
    )
    j(
        "if(!document.querySelector('.screen').classList.contains('conversation-full'))document.querySelector('.conversation-expand')?.click()"
    )
    c.wait("document.querySelector('.screen').classList.contains('conversation-full')")
    review = c.rect(".screen")
    d.still(
        "docs/images/cockpit_history.png",
        crop=(int(review[0]) - 6, 100, int(review[2]) + 6, 734),
    )
    j("conversationView.close();showAgentDetail(tiles.get('PatientFaraday'))")
    c.wait("!agentDetail.hidden && agentDetail.querySelector('[data-computer]')")
    bounds = c.rect("#agentDetail")
    crop = (
        0,
        max(0, int(bounds[1]) - 18),
        min(c.size[0], int(bounds[2]) + 24),
        min(c.size[1], int(bounds[3]) + 28),
    )
    d.still("docs/images/cockpit_roster_detail.png", crop=crop)
    j("hideAgentDetail(tiles.get('PatientFaraday'));focusSession('PatientFaraday')")
    c.input("#promptInput", "/")
    c.wait("document.querySelectorAll('.sm-it').length>=2")
    bounds = c.rect(".prompt-card")
    menu = c.rect("#slashMenu")
    crop = (
        max(0, int(min(bounds[0], menu[0])) - 8),
        int(menu[1]) - 16,
        min(c.size[0], int(max(bounds[2], menu[2])) + 10),
        int(bounds[3]) + 10,
    )
    d.still("docs/images/cockpit_skill_menu.png", crop=crop)
    j(
        "promptInput.value='';promptInput.dispatchEvent(new Event('input',{bubbles:true}));closeSlashMenu()"
    )
    c.resize(1120, 645)
    j("focusSession('PatientFaraday');terminalFontSize=16;applyTerminalSettings()")
    prompt = c.rect(".prompt-card")
    need_crop = (0, 0, min(c.size[0], int(prompt[2]) + 18), c.size[1])
    need_size = (1060, round(645 * 1060 / need_crop[2]))
    c.wait("document.getElementById('needChip').textContent.includes('need you')")
    frames = [(d.frame(need_size, need_crop), 1850)]
    c.click("#needChip")
    c.wait("document.getElementById('needChip').getAttribute('aria-pressed')==='true'")
    frames.append((d.frame(need_size, need_crop), 1500))
    c.click('#roster [data-agent="PatientFaraday"]')
    c.wait("activeSession()==='PatientFaraday'")
    frames.append((d.frame(need_size, need_crop), 1950))
    frames.extend(d.type_frames("#promptInput", "1", need_size, need_crop))
    c.key("Enter")
    c.wait("document.getElementById('promptInput').value===''")
    c.wait(
        "!currentAgentNamed('PatientFaraday') || currentAgentNamed('PatientFaraday').act_state==='wait'"
    )
    c.wait(
        "(()=>{const b=panes.get(activeId).term.buffer.active;return Array.from({length:b.length},(_,i)=>b.getLine(i).translateToString(true)).join(' ').includes('Added the shortcuts')})()"
    )
    frames.append((d.frame(need_size, need_crop), 2400))
    d.gif("docs/images/cockpit_need_you.gif", frames)
    c.click("#needChip")
    j("focusSession('AmberCurie');conversationView.open()")
    c.wait("document.querySelector('.conversation-table-copy')")
    j(
        "if(!document.querySelector('.screen').classList.contains('conversation-full'))document.querySelector('.conversation-expand')?.click()"
    )
    c.wait("document.querySelector('.screen').classList.contains('conversation-full')")
    c.wait("document.getElementById('promptSend').title==='Stop agent (Esc)'")
    c.js("document.getElementById('promptInput').focus()")
    c.wait("!document.getElementById('toast').classList.contains('on')")
    prompt = c.rect(".prompt-card")
    stop_crop = (int(prompt[0]) - 10, 205, int(prompt[2]) + 10, c.size[1])
    stop_size = (
        900,
        round((stop_crop[3] - stop_crop[1]) * 900 / (stop_crop[2] - stop_crop[0])),
    )
    frames = [(d.frame(stop_size, stop_crop), 2600)]
    c.key("Escape")
    c.wait("document.getElementById('toast').innerText.includes('Interrupted')")
    j("pollAgents()")
    c.wait("document.getElementById('promptSend').title!=='Stop agent (Esc)'")
    c.wait(
        "document.querySelector('.conversation-events').textContent.includes('Paused the review')"
    )
    frames.append((d.frame(stop_size, stop_crop), 2500))
    d.gif("docs/images/cockpit_composer_calm.gif", frames)
    j("conversationView.close()")
    c.resize(1240, 740)
    c.click("#planetariumBtn")
    c.wait("document.querySelector('#planetariumOverlay.on .planetarium-svg')")
    planet = c.rect(".planetarium-panel")
    crop = (int(planet[0]), int(planet[1]), int(planet[2]), int(planet[3]))
    d.still("docs/images/cockpit_planetarium.png", crop=crop)
    c.key("Escape")

    c.click("#networkBtn")
    c.wait("!!networkFrame.contentDocument?.querySelector('#demo-card .go')")
    j("""(async()=>{
        const win=networkFrame.contentWindow, doc=networkFrame.contentDocument;
        doc.querySelector('#demo-card .go').click();
        doc.querySelector('#demo-strip')?.remove();doc.querySelector('#demo-ring')?.remove();
        const demo=win.AGENTSTACK_DEMO;
        demo.stories['docs-reel']=await (await fetch('/fixture-reel')).json();demo.useStory('docs-reel');
        const frozen=win.Date.now()+38000;win.Date.now=()=>frozen;
        win.setView('net');await win.netTick();
        win.openPanel('Bright-Curie');
    })()""")
    c.wait(
        "!networkFrame.contentDocument.querySelector('#demo-card') && networkFrame.contentDocument.body.innerText.includes('OPEN IN COCKPIT')"
    )
    panel = j("""(()=>{const frame=networkFrame.getBoundingClientRect();
        const doc=networkFrame.contentDocument, panel=doc.querySelector('#term .tm-box');
        const r=panel.getBoundingClientRect();
        return [frame.x+r.left, frame.y+r.top, frame.x+r.right, frame.y+r.bottom];})()""")
    crop = (
        max(0, int(panel[0]) - 12),
        max(0, int(panel[1]) - 8),
        min(c.size[0], int(panel[2]) + 12),
        min(c.size[1], int(panel[1]) + 344),
    )
    d.still("docs/images/cockpit_telemetry_open_in_cockpit.png", crop=crop)
    c.click("#networkClose")

    j("OrreryFullTour.checklist.show()")
    c.wait("!OrreryFullTour.checklist.el.hidden")
    tour_size = (1080, 675)
    frames = [(d.frame(tour_size), 1850)]
    c.click("#newAgentBtn")
    c.wait("spawnOverlay.classList.contains('on')")
    j("""(() => {
      const task = document.querySelector('#spawnTask');
      task.value = '';
      task.dispatchEvent(new Event('input', {bubbles: true}));
    })()""")
    frames.extend(d.type_frames("#spawnTask", "Check the release.", tour_size))
    # The response is a fixture. No shell, tmux, agent, or Mail process runs.
    c.click("#spawnDirButton")
    c.wait("!document.querySelector('#spawnDirUse').disabled")
    c.click("#spawnDirUse")
    c.wait("!document.querySelector('#spawnSubmit').disabled")
    frames.append((d.frame(tour_size), 1100))
    c.click("#spawnSubmit")
    c.wait(
        "!spawnOverlay.classList.contains('on') || spawnStatus.classList.contains('error')"
    )
    if j("spawnOverlay.classList.contains('on')"):
        raise RuntimeError("The fixture launch failed")
    j("pollAgents()")
    c.wait("document.querySelector('#roster [data-agent=WarmLovelace]')")
    c.click('#roster [data-agent="WarmLovelace"]')
    c.wait("activeSession()==='WarmLovelace'")
    frames.append((d.frame(tour_size), 1650))
    frames.extend(d.type_frames("#promptInput", "What changed?", tour_size))
    c.key("Enter")
    c.wait("document.getElementById('promptInput').value===''")
    frames.append((d.frame(tour_size), 2450))
    d.gif("docs/images/fulltour/1-start-choose-talk.gif", frames)


def save_dashboard(c, root, url):
    d = Gallery(root, c)
    j = c.js
    c.open(
        url + "/dashboard?lang=en&tune=L:150,KR:6800,GR:0.008",
        "typeof AGENTSTACK_DEMO!=='undefined' && !!document.querySelector('#demo-card .go')",
    )
    c.click("#demo-card .go")
    j("""(async()=>{
      document.querySelector('#demo-strip').style.display='none';document.querySelector('#demo-ring').style.opacity='0';
      const demo=window.AGENTSTACK_DEMO;
      demo.stories['docs-reel']=await (await fetch('/fixture-reel')).json();demo.useStory('docs-reel');
      const catalog=await (await fetch('/fixture-catalog')).json();
      const fetchDemo=window.fetch.bind(window);
      window.fetch=async (request,options)=>{
        if(String(request).split('?')[0]==='/api/spawn-names'){
          const response=await fetchDemo(request,options);
          const original=await response.json();
          return new Response(JSON.stringify({...original,providers:catalog.providers,computer_use:true}),
             {headers:{'Content-Type':'application/json'}});
        }
        return fetchDemo(request,options);
      };
      const realNow=Date.now.bind(Date);
      window.docsPhase=async phase=>{
        Date.now=realNow;demo.restart();
        const frozen=realNow()+Math.round((phase-demo.opensAt())*1000);
        Date.now=()=>frozen;
        if(document.body.dataset.view==='net')await netTick();else await tick();
      };
    })()""")
    c.resize(1460, 1020)
    j("docsPhase(28)")
    d.still("docs/images/deck_growing.png", (1460, 1020))
    j("docsPhase(42)")
    c.wait("document.body.innerText.includes('APPROVAL')")
    d.still("docs/images/deck_humanloop.png", (1460, 1020))
    c.resize(1460, 860)
    j("setView('net');docsPhase(42)")
    c.wait("gmap.size>=12")
    c.wait("!simRAF")
    j("""(() => {
      // Keep transient Mail cards from covering the links or the open thread.
      const style = document.createElement('style');
      style.textContent = '.mail-card, .mail-comet { visibility: hidden }';
      document.head.append(style);
      fitView();
    })()""")
    d.still("docs/img/network.jpg")

    network_size = (1168, 688)
    frames = [(d.frame(network_size), 1300)]
    j(
        "(()=>{const edge=AGENTSTACK_DEMO.payloads.graph().edges.sort((a,b)=>b.count-a.count)[0];return openDrawer(edge.source,edge.target)})()"
    )
    c.wait(
        "document.querySelector('#edrawer').classList.contains('on') && /Keyboard result|Ready for review/.test(document.getElementById('ed-list').textContent)"
    )
    frames.append((d.frame(network_size), 3300))
    d.gif("docs/img/network-mail.gif", frames)
    c.key("Escape")
    j("setView('deck');openSpawnModal()")
    c.resize(1600, 1280)
    c.wait("spmProviders.length>=5")
    c.input("#spm-task", "Review the release notes.")
    j(
        "selectSpawnProvider('gemini');SPM('spm-advanced').open=true;SPM('spm-parent').scrollIntoView({block:'nearest'})"
    )
    c.wait("spmSelectedProvider==='gemini' && !SPM('spm-parent').value")
    bounds = c.rect(".spm-frame")
    d.still(
        "docs/images/new_agent_capabilities_dark.png",
        crop=(int(bounds[0]), int(bounds[1]), int(bounds[2]), int(bounds[3])),
    )
    j(
        "SPM('spm-advanced').open=false;SPM('spm-providers').scrollIntoView({block:'center'})"
    )
    launch_size = (1000, 625)
    box = c.rect("#spm-providers")
    harness = c.rect("#spm-harnesses")
    launch_crop = (
        int(box[0]) - 32,
        int(box[1]) - 115,
        int(harness[2]) + 24,
        int(box[3]) + 47,
    )
    launch_size = (
        1000,
        round(
            (launch_crop[3] - launch_crop[1]) * 1000 / (launch_crop[2] - launch_crop[0])
        ),
    )
    frames = [(d.frame(launch_size, launch_crop), 1500)]
    j("selectSpawnProvider('deepseek')")
    frames.append((d.frame(launch_size, launch_crop), 1850))
    c.click('#spm-harnesses [data-harness="hermes"]')
    frames.append((d.frame(launch_size, launch_crop), 1850))
    j("selectSpawnProvider('local-qwen')")
    frames.append((d.frame(launch_size, launch_crop), 2400))
    d.gif("docs/img/native-harness-selection.gif", frames)


def save_phone(c, root, url):
    d = Gallery(root, c)
    j = c.js
    c.open(
        url + "/",
        "document.documentElement?.dataset.demoSync==='ready' && document.getElementById('attention')?.children.length>0",
    )
    c.click('[data-mode="all"]')
    c.click("#graph-fullscreen")
    frames = [(d.frame(), 1750)]
    # Search selects the same Graph node regardless of the force layout.
    c.click("#graph-search-toggle")
    field = j("document.querySelector('#graph-search input').id")
    frames.extend(d.type_frames("#" + field, "Turing"))
    c.wait("document.querySelector('#agent-results .agent-result-focus')")
    c.click("#agent-results .agent-result-focus")
    c.click("#graph-search-toggle")
    frames.append((d.frame(), 1550))
    j(
        "OrreryMobileTerminal.open('Turing',OrreryMobileIdentity.forName('Turing'),'terminal')"
    )
    c.wait(
        "document.querySelector('#terminal-output')?.textContent.includes('Keyboard shortcuts')"
    )
    frames.append((d.frame(), 1550))
    c.click('#terminal-sheet button[aria-label="Conversation"]')
    c.wait(
        "document.querySelector('#terminal-sheet .conversation-mode')?.textContent.includes('release review')"
    )
    conversation = "#terminal-sheet .conversation-list"
    j(f"document.querySelector('{conversation}').scrollTop=0")
    c.wait(f"document.querySelector('{conversation}').scrollTop===0")
    frames.append((d.frame(), 1600))
    # Scroll by one complete message, keeping the next portrait below the bar.
    j(f"""(() => {{
      const list = document.querySelector('{conversation}');
      const first = list.querySelector('[data-id="earlier-0"]');
      const next = list.querySelector('[data-id="earlier-1"]');
      list.scrollTop = next.offsetTop - first.offsetTop;
    }})()""")
    frames.append((d.frame(), 1600))
    c.wait("!!document.querySelector('#terminal-sheet textarea')")
    frames.extend(d.type_frames("#terminal-sheet textarea", "Check mobile."))
    j(
        """[...document.querySelectorAll('#terminal-sheet button')].find(b=>b.textContent.trim()==='Review input'||b.getAttribute('aria-label')==='Review input')?.click()"""
    )
    c.wait("document.getElementById('terminal-sheet').innerText.includes('Send once')")
    j(f"document.querySelector('{conversation}').scrollTop=0")
    c.wait(f"document.querySelector('{conversation}').scrollTop===0")
    frames.append((d.frame(), 2000))
    j(
        """[...document.querySelectorAll('#terminal-sheet button')].find(b=>b.textContent.trim()==='Send once')?.click()"""
    )
    c.wait(
        "document.getElementById('terminal-sheet').innerText.includes('Received by terminal')"
    )
    j(f"document.querySelector('{conversation}').scrollTop=0")
    frames.append((d.frame(), 2100))
    d.gif("docs/images/mobile-graph-to-terminal.gif", frames)

    j("OrreryMobileTerminal.close()")
    c.resize(390, 844)
    j(
        "if(document.querySelector('#graph-fullscreen').getAttribute('aria-expanded')==='true')document.querySelector('#graph-fullscreen').click()"
    )
    c.click("[data-view=activity]")
    c.wait("document.querySelector('#events .mail-route')")
    c.click("#events .mail-route")
    c.wait(
        "document.getElementById('message-sheet').open && document.getElementById('message-body').textContent.includes('Review input')"
    )
    d.still("docs/images/mobile-mail.png")
