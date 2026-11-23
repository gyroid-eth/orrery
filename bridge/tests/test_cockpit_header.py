"""Arc meters and the existing cockpit actions, using fixture data."""
import json
import re

import pytest

from test_cockpit_tour import tour_browser


def show_usage(evaluate):
    providers = [
        dict(provider='claude', status='ok', windows=[
            dict(label='5h', remaining_percent=9), dict(label='Weekly', remaining_percent=82)]),
        dict(provider='codex', status='ok', windows=[dict(label='Weekly', remaining_percent=100)]),
        dict(provider='antigravity', status='ok', windows=[
            dict(label='Daily', limit='Gemini Models', remaining_percent=45)]),
        dict(provider='dsh', status='ok', measurement_kind='balance',
             balance=dict(total_balance='7.24', is_available=True), windows=[]),
    ]
    evaluate("usageData={providers:" + json.dumps(providers) + "};renderUsagePill()")


@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_header_arcs_keep_binding_percent_balance_and_hover(tour_browser, theme):
    _, evaluate = tour_browser
    evaluate("OrreryColorTheme.setPreference(" + json.dumps(theme) + ")")
    show_usage(evaluate)
    result = evaluate("""(()=>{
      const pill=document.getElementById('usageBtn');
      const color=name=>{const s=document.createElement('span');s.style.color=name;
        document.body.appendChild(s);const c=getComputedStyle(s).color;s.remove();return c;};
      return {theme:OrreryColorTheme.resolved,label:pill.getAttribute('aria-label'),
        providers:[...pill.querySelectorAll('.up-p')].map(slot=>{
          const arc=slot.querySelector('.up-meter-fill');
          return {name:slot.dataset.provider,value:slot.querySelector('b').textContent,
            amount:slot.style.getPropertyValue('--usage-left'),title:slot.title,
            stroke:arc&&getComputedStyle(arc).stroke};
        }), colors:[color('var(--theme-status-alert,#d2685e)'),color('var(--ln-local)'),color('var(--amber)')]};
    })()""")
    assert result['theme'] == theme
    assert result['label'] == 'Usage left. Claude 9%, Codex 100%, Antigravity (Gemini) 45%, DeepSeek $7'
    assert [(p['name'], p['value'], p['amount']) for p in result['providers']] == [
        ('claude', '9%', '9'), ('codex', '100%', '100'), ('antigravity', '45%', '45'), ('dsh', '$7', '')]
    assert [p['stroke'] for p in result['providers']] == [*result['colors'], None]
    assert [p['title'] for p in result['providers']] == [
        'Claude 5h: 9% left', 'Codex Weekly: 100% left',
        'Antigravity (Gemini) Gemini Models · Daily: 45% left', 'DeepSeek: $7.24 · account available']


def test_header_controls_open_their_existing_surfaces(tour_browser):
    _, evaluate = tour_browser
    show_usage(evaluate)
    state = evaluate("""(()=>{
      const byId=id=>document.getElementById(id);
      const ids=['settingsBtn','planetariumBtn','networkBtn'];
      const labels=ids.map(id=>{const control=byId(id);return [control.title,control.getAttribute('aria-label'),
        !!control.querySelector('svg[aria-hidden="true"]'),control.textContent.trim()];});
      const symbols=[byId('networkBtn').querySelectorAll('circle').length,!!byId('planetariumBtn').querySelector('ellipse')];
      byId('settingsBtn').click();const settings=byId('settingsPopover').matches(':popover-open');
      byId('settingsPopover').hidePopover();
      byId('planetariumBtn').click();const planetarium=!!document.querySelector('#planetariumOverlay.on');
      OrreryRail.closePlanetarium();
      byId('networkBtn').click();const telemetry=byId('networkOverlay').classList.contains('on');
      byId('networkClose').click();
      usageHidden=new Set(['claude','codex','antigravity','dsh']);renderUsagePill();renderUsagePopover();
      const fallback=byId('usageBtn').querySelector('.usage-fallback').getBoundingClientRect().width>0;
      byId('usageBtn').click();const usage=byId('usagePopover').matches(':popover-open');
      return {labels,symbols,settings,planetarium,telemetry,usage,fallback,clock:byId('clock').textContent};
    })()""")
    assert state['labels'] == [
        ['Settings', 'Open cockpit settings', True, ''],
        ['Planetarium', 'Open the planetarium', True, ''],
        ['Telemetry', 'Open telemetry dashboard', True, '']]
    assert state['symbols'] == [5, True]
    assert all(state[name] for name in ('settings', 'planetarium', 'telemetry', 'usage', 'fallback')), state
    assert re.fullmatch(r'\d{2}:\d{2}:\d{2}', state['clock'])


@pytest.mark.parametrize('width', [280, 390, 680, 900, 901, 1101, 1440])
def test_header_fits_with_four_providers_and_both_statuses(tour_browser, width):
    client, evaluate = tour_browser
    show_usage(evaluate)
    client.call('Emulation.setDeviceMetricsOverride', width=width, height=844, deviceScaleFactor=1, mobile=False)
    result = evaluate("""(()=>{
      setLink('closed','disconnected');needChip.hidden=false;needCount.textContent='2';
      const header=document.querySelector('.cockpit-header'),r=header.getBoundingClientRect();
      const nodes=[...header.querySelectorAll('.brand,.topstat, .header-actions button, .usage-pill .up-p, .clock')]
        .filter(node=>!node.hidden);
      const boxes=nodes.map(node=>[node.id||node.className,node.getBoundingClientRect()]);
      const outside=boxes.filter(([,b])=>!b.width||!b.height||b.left<r.left||b.right>r.right||b.top<r.top||b.bottom>r.bottom)
        .map(([name])=>name);
      const conflicts=boxes.flatMap(([a,p],i)=>boxes.slice(i+1).filter(([,q])=>
        p.left<q.right&&p.right>q.left&&p.top<q.bottom&&p.bottom>q.top).map(([b])=>[a,b]));
      return {width:innerWidth,outside,conflicts};
    })()""")
    assert result == {'width': width, 'outside': [], 'conflicts': []}


def test_side_checklist_stays_below_both_header_rows(tour_browser):
    client, evaluate = tour_browser
    client.call('Emulation.setDeviceMetricsOverride', width=820, height=844, deviceScaleFactor=1, mobile=False)
    show_usage(evaluate)
    assert evaluate("""(()=>{
      const flight=OrreryTour.firstFlight;flight.reset();flight.show();
      return flight.el.getBoundingClientRect().top>=document.querySelector('.cockpit-header').getBoundingClientRect().bottom;
    })()""")
