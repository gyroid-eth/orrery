"""Capture the README team story using the real cockpit and a demo vault fixture."""

from __future__ import annotations

import json
import shutil
import subprocess
import time

from PIL import Image, ImageOps

from guide_scenes import (
    GUIDES, PREFERENCES, VIEWPORT, GuideFrames, capture_sequence, crop_rect,
)
from scenes import Gallery

CANVAS = (1120, 640)


def open_hero(camera, url):
    camera.open(
        url + "/cockpit.html?demo=1",
        "typeof availableSessions !== 'undefined' && availableSessions.has('AmberCurie')",
        PREFERENCES,
    )
    camera.page.call("Emulation.setEmulatedMedia", features=[
        {"name": "prefers-reduced-motion", "value": "no-preference"},
    ])
    camera.js("""
      const printStyle=document.createElement('style');
      printStyle.textContent='@media print{.app{height:759px}}';
      document.head.append(printStyle);
      document.querySelector('.grid').style.setProperty('--mail-width','415px');
      Promise.all([pollAgents(),pollGraph(),pollMail(),document.fonts.ready])
    """)
    camera.wait("document.querySelector('#roster [data-agent=AmberCurie]')")
    camera.click("#roster [data-agent=AmberCurie]")
    camera.wait("""
      activeSession()==='AmberCurie' && document.querySelectorAll('#orrery .mini-agent').length===1
    """)


def send_and_show_team(camera, request):
    frames = capture_sequence(camera, (0, 0, *VIEWPORT), 4.25, """
      (() => {
        const input = document.querySelector('#promptInput');
        const letters = Array.from(REQUEST_TEXT);
        const interval = 1050 / letters.length;
        window.heroStarted = 0;
        letters.forEach((letter, index) => setTimeout(() => {
          input.focus({preventScroll:true});
          document.execCommand('insertText', false, letter);
        }, 330 + index * interval));
        setTimeout(() => document.querySelector('#promptSend').click(), 1610);
        [1950, 2390, 2810, 3230].forEach(delay => setTimeout(async () => {
          const team = await fetch('/fixture-team', {method:'POST'});
          if(!team.ok) return;
          window.heroStarted++;
          await Promise.all([pollAgents(), pollGraph()]);
        }, delay));
        return true;
      })()
    """.replace("REQUEST_TEXT", json.dumps(request)))
    camera.wait("""
      window.heroStarted===4 && document.querySelector('#promptInput').value==='' &&
      document.querySelectorAll('#orrery .mini-agent').length===5 &&
      ['PatientFaraday','NimbleTuring','CalmGauss','SageNoether'].every(
        name=>document.querySelector('#roster [data-agent="'+name+'"]')
      )
    """)
    return frames


def record_team_mail(camera):
    # One fixed framing for the entire moving shot.
    area = crop_rect(camera, "#mailRail", padding=0, height=525)
    frames = capture_sequence(camera, area, 4.45, """
          (() => {
            const seen=new Set();
            const mini=document.querySelector('#orrery');
            new MutationObserver(()=>{
              for(const subject of mini.querySelectorAll('.orrery-arrival-subject')){
                seen.add(subject.textContent.trim());
              }
              window.heroArrivalSubjects=[...seen];
            }).observe(mini,{childList:true,subtree:true});
            [370,960,1500,2110].forEach(delay=>setTimeout(async ()=>{
              const report=await fetch('/fixture-team-report',{method:'POST'});
              if(report.ok)await pollMail();
            },delay));
            return true;
          })()
    """)
    subjects = camera.js("window.heroArrivalSubjects||[]")
    if len(subjects) < 2:
        raise RuntimeError(f"The team clip needs two visible Mail arrivals: {subjects}")
    print("Mail arrival subjects:", subjects, flush=True)
    return frames


def save_team_hero(camera, destination, url, language):
    open_hero(camera, url)
    gallery = Gallery(destination, GuideFrames(camera))
    request = "今日のタスクを整理して" if language == "ja" else "Plan today's tasks"
    frames = send_and_show_team(camera, request)
    frames.extend(record_team_mail(camera))
    camera.click("#conversationToggle")
    camera.wait("document.querySelector('.conversation-events table tbody')?.children.length===4")
    if not camera.js("document.querySelector('.screen').classList.contains('conversation-full')"):
        camera.click(".conversation-expand")
    camera.wait("document.querySelector('.screen').classList.contains('conversation-full')")
    time.sleep(.3)
    area = crop_rect(camera, ".screen", height=510)
    frames.append((gallery.frame(crop=area), 2650))
    file = GUIDES / ("team-hero.gif" if language == "ja" else "team-hero.en.gif")
    for canvas in (CANVAS, (1050, 600), (980, 560)):
        fitted = [
            (ImageOps.pad(image, canvas, method=Image.Resampling.LANCZOS, color="#101114"), hold)
            for image, hold in frames
        ]
        gallery.gif(file, fitted)
        output = destination / file
        if output.stat().st_size > 3_000_000 and shutil.which("gifsicle"):
            packed = output.with_suffix(".optimized.gif")
            subprocess.run(
                ["gifsicle", "-O3", str(output), "-o", str(packed)], check=True,
            )
            if packed.stat().st_size < output.stat().st_size:
                packed.replace(output)
            else:
                packed.unlink()
        if (destination / file).stat().st_size <= 3_000_000:
            break
    with Image.open(destination / file) as result:
        count = result.n_frames
        duration = 0
        for index in range(count):
            result.seek(index)
            duration += result.info["duration"]
    size = (destination / file).stat().st_size
    if not 10_000 <= duration <= 12_000 or size > 3_000_000 or count <= 40:
        raise RuntimeError(f"Unexpected README GIF: {count} frames, {duration} ms, {size} bytes")
    print(f"README team GIF ({language}): {count} frames, {duration} ms, {size} bytes", flush=True)


def save_readme_phone(camera, destination, url):
    """Show a list entry, the conversation, and a confirmed phone send."""
    roster_entry = '#attention [data-terminal-name="Turing"]'
    camera.open(url + "/", """
      document.documentElement.dataset.demoSync==='ready' &&
      document.querySelector('#attention [data-terminal-name="Turing"]:not([disabled])')
    """)
    camera.js("document.fonts.ready")
    gallery = Gallery(destination, GuideFrames(camera))
    size = (390, 844)
    frames = [(gallery.frame(size), 1500)]
    camera.click(roster_entry)
    camera.wait("document.querySelector('#terminal-sheet .conversation-mode')?.innerText.includes('release notes')")
    field = "#terminal-sheet textarea"
    camera.wait(f"!!document.querySelector('{field}')")
    frames.append((gallery.frame(size), 2100))
    for char in "次を教えて":
        camera.input(field, char)
        frames.append((gallery.frame(size), 120))
    frames[-1] = frames[-1][0], 650
    camera.click('#terminal-sheet button[aria-label="Review input"]')
    camera.wait("document.getElementById('terminal-sheet').innerText.includes('Send once')")
    frames.append((gallery.frame(size), 1450))
    camera.js("""
      [...document.querySelectorAll('#terminal-sheet button')]
        .find(button=>button.textContent.trim()==='Send once').click()
    """)
    camera.wait("document.getElementById('terminal-sheet').innerText.includes('Received by terminal')")
    frames.append((gallery.frame(size), 2150))
    gallery.gif(GUIDES / "mobile.gif", frames)

    camera.js("OrreryMobileTerminal.close()")
    camera.wait("!document.getElementById('terminal-sheet').open")
    camera.resize(820, 1180)
    camera.wait("""
      innerWidth===820 && document.documentElement.scrollWidth===innerWidth &&
      !document.getElementById('activity').hidden && !document.getElementById('graph-panel').hidden
    """)
    gallery.still(GUIDES / "mobile-ipad.png", (820, 1180))
