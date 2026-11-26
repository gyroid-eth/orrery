"""Record the same task review in Terminal, Reader and the file preview."""

from guide_scenes import (
    GUIDES, PREFERENCES, GuideFrames, capture_sequence, union_crop,
)
from scenes import Gallery


def save_reader(camera, destination, url, language):
    camera.open(url + "/cockpit.html?demo=1",
                "document.querySelector('#roster [data-agent=AmberCurie]')", PREFERENCES)
    camera.click("#roster [data-agent=AmberCurie]")
    camera.wait("activeSession()==='AmberCurie' && document.querySelector('.xterm-screen')")
    camera.js("document.fonts.ready")
    area = union_crop(camera, (".screen", ".promptbar"))
    gallery = Gallery(destination, GuideFrames(camera))
    frames = capture_sequence(camera, area, 10.3, """
      (() => {
        const capture = {output:false, reader:false, preview:false, returned:false};
        window.readerCapture = capture;
        const chip = () => document.querySelector('.conversation-file');
        const preview = () => document.querySelector('.conversation-preview:not([hidden])');
        setTimeout(async () => {
          capture.output = (await fetch('/fixture-reader-output',{method:'POST'})).ok;
        }, 240);
        setTimeout(() => document.querySelector('#conversationToggle').click(), 3150);
        setTimeout(() => {
          if(!document.querySelector('.screen').classList.contains('conversation-full'))
            document.querySelector('.conversation-expand').click();
        }, 3490);
        setTimeout(() => {
          capture.reader = !!document.querySelector('.conversation-events table') &&
            !!document.querySelector('.conversation-steps-toggle[aria-expanded=false]');
          chip()?.focus({preventScroll:true});
        }, 5450);
        setTimeout(() => chip()?.click(), 6020);
        setTimeout(() => {
          capture.preview = !!preview()?.querySelector('table') && !!preview()?.querySelector('ol');
        }, 7200);
        setTimeout(() => document.querySelector('.conversation-preview-close')?.click(), 8600);
        setTimeout(() => {
          capture.returned = !!chip() && !preview();
        }, 9300);
        return true;
      })()
    """)
    state = camera.js("window.readerCapture")
    if not all(state.values()):
        raise RuntimeError(f"Missing Reader stages: {state}")
    file = "read-a-file.gif" if language == "ja" else "read-a-file.en.gif"
    gallery.gif(GUIDES / file, frames)
    print(f"{language}: {len(frames)} captured frames; {state}", flush=True)
