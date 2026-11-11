/* Licensed under the Apache License, Version 2.0. See the COPYRIGHT and LICENSE files in the project root for details.
 *
 * cserver.cmeta.targets (Supported compute): the numbers, the four pillars, the matrix of the targets against the
 * operating systems, the matrix of the programs against the targets (filtered by an OS, a target), the commands to try;
 * one search at the top (it stays there while the page scrolls) narrows both matrices. Everything comes from CMT_DATA
 * (api/v1.py); the state (q, target, os) is kept in the address so a view can be shared; A- / A+ (the size) and the
 * theme - the one of every page of a cMeta server, cmeta.theme - are kept in the browser.
 */
(function () {
  'use strict';

  var D = window.CMT_DATA || {};
  var C = window.CMT_CONFIG || {};
  var root = document.getElementById('cmt');
  if (!root) return;

  var $ = function (id) { return document.getElementById(id); };
  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]; }); };

  if (D.error) {
    $('cmt-err').hidden = false;
    $('cmt-err').textContent = 'The data could not be read: ' + D.error;
    return;
  }

  var SHARED_THEME = 'cmeta.theme';                  // the theme of every page of a cMeta server (2026-11-10)
  var THEME_KEY = 'cserver.cmeta.targets.theme', SCALE_KEY = 'cserver.cmeta.targets.scale';
  function stored(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function store(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } }

  // the theme: inside the cPlatform's shell the shell's (it may switch without a reload; no switch of our own); on a
  // cMeta server the one theme of its pages (cmeta.theme in this browser), this page's switch, followed when another
  // page (another tab) changes it; else the server's (?dark=1)
  function setDark(dark) {
    root.classList.toggle('dark', !!dark);
    paintKinds();
  }
  function paintKinds() {
    var dark = root.classList.contains('dark');
    (D.kinds || []).forEach(function (k) { root.style.setProperty('--k-' + k.id, dark ? (k.dark || k.light) : k.light); });
  }
  if (C.hosted) {
    root.classList.add('hosted');
    $('cmt-theme').hidden = true;
    var follow = function () {
      var t = document.documentElement.getAttribute('data-ctp-theme');
      setDark(t ? t === 'dark' : C.dark_mode === true);
    };
    new MutationObserver(follow).observe(document.documentElement, {attributes: true, attributeFilter: ['data-ctp-theme']});
    follow();
  } else {
    var t0 = stored(SHARED_THEME) || stored(THEME_KEY);
    setDark(t0 ? t0 === 'dark' : C.dark_mode === true);
    $('cmt-theme').addEventListener('click', function () {
      var dark = !root.classList.contains('dark');
      setDark(dark);
      store(SHARED_THEME, dark ? 'dark' : 'light');
      store(THEME_KEY, dark ? 'dark' : 'light');
    });
    window.addEventListener('storage', function (e) { if (e.key === SHARED_THEME && e.newValue) setDark(e.newValue === 'dark'); });
  }

  // the size: A- / A+ (kept in this browser), or ?font=1.2 in the address - the whole of the page under the search
  var scale = 1;
  function setScale(s, keep) {
    scale = Math.max(0.7, Math.min(2.2, Math.round(s * 10) / 10));
    $('cmt-body').style.zoom = String(scale);
    if (keep) store(SCALE_KEY, String(scale));
  }
  var askedFont = parseFloat((/[?&]font=([\d.]+)/.exec(location.search) || [])[1]);
  setScale(askedFont > 0 ? askedFont : (parseFloat(stored(SCALE_KEY)) || 1), false);
  $('cmt-smaller').addEventListener('click', function () { setScale(scale - 0.1, true); });
  $('cmt-bigger').addEventListener('click', function () { setScale(scale + 0.1, true); });

  var OS = D.os || [];
  var osName = {};
  OS.forEach(function (o) { osName[o.id] = o.name; });
  var kindName = {};
  (D.kinds || []).forEach(function (k) { kindName[k.id] = k.name; });
  var targets = D.targets || [];
  var tById = {};
  targets.forEach(function (t) { tById[t.id] = t; });
  var progTargets = targets.filter(function (t) { return t.status !== 'placeholder'; });
  var programs = D.programs || [];

  // state from the address
  var sp = new URLSearchParams(location.search);
  var st = {q: (C.state && C.state.q) || sp.get('q') || '', target: (C.state && C.state.target) || sp.get('target') || '',
            os: (C.state && C.state.os) || sp.get('os') || ''};

  function copyButton(cmd) { return '<button type="button" class="cmt-cp" data-copy="' + esc(cmd) + '" aria-label="Copy the command">copy</button>'; }
  function cmdLine(cmd) { return '<div class="cmt-cmd"><code>' + esc(cmd) + '</code>' + copyButton(cmd) + '</div>'; }

  // ---- the numbers
  var c = D.counts || {};
  var stats = [[c.programs, 'programs', 'described once'], [c.targets, 'compute targets', (c.planned ? c.planned + ' more planned' : '')],
               [OS.length, 'operating systems', OS.map(function (o) { return o.name; }).join(' · ')],
               [c.tools, 'tools', 'detected or installed on the way'], [c.tasks, 'tasks', 'the steps they are built from']];
  $('cmt-stats').innerHTML = stats.map(function (s) {
    return '<div class="cmt-stat"><b>' + esc(s[0]) + '</b><span>' + esc(s[1]) + '</span>' + (s[2] ? '<small>' + esc(s[2]) + '</small>' : '') + '</div>';
  }).join('');

  // ---- the four pillars
  $('cmt-pillars').innerHTML = (D.pillars || []).map(function (p, i) {
    return '<div class="cmt-pillar"><h3><span class="n">' + (i + 1) + '</span>' + esc(p.title) + '</h3><p>' + esc(p.text) + '</p>' + (p.cmd ? cmdLine(p.cmd) : '') + '</div>';
  }).join('');

  // ---- the search (the box at the top): its words narrow both tables - a program when every word is in its name, what
  // it does, its tags, its targets or its family; a target when every word is in its name, its hardware, what it is,
  // its kind - or when it runs one of the programs the words keep (a program's name finds where it runs)
  function words() { return st.q.toLowerCase().split(/\s+/).filter(Boolean); }
  function progHits(p, ws) {
    var hay = (p.alias + ' ' + p.name + ' ' + p.desc + ' ' + p.tags.join(' ') + ' ' + p.targets.join(' ') + ' ' + p.family).toLowerCase();
    return ws.every(function (w) { return hay.indexOf(w) >= 0; });
  }
  function targetHits(t, ws, kept) {
    if (!ws.length) return true;
    var hay = (t.id + ' ' + (t.name || '') + ' ' + (t.hardware || '') + ' ' + (t.desc || '') + ' ' + (kindName[t.kind] || t.kind)).toLowerCase();
    return ws.every(function (w) { return hay.indexOf(w) >= 0; }) || kept.some(function (p) { return p.targets.indexOf(t.id) >= 0; });
  }

  // ---- the targets against the operating systems
  function osCell(t, o) {
    if (t.status === 'placeholder') return '<td class="c planned" data-tip="' + esc(t.name + ': planned') + '">·</td>';
    var runs = o.device ? t.device_os === o.id : (!t.device_os && t.host_os.indexOf(o.id) >= 0);
    var drives = !o.device && t.device_os && t.host_os.indexOf(o.id) >= 0;
    if (runs) return '<td class="c" data-tip="' + esc(t.name + ' runs on ' + o.name + (o.note ? ' (' + o.note + ')' : '')) + '"><i class="cmt-dot k-' + esc(t.kind) + '"></i></td>';
    if (drives) return '<td class="c" data-tip="' + esc(t.name + ': built, installed and launched from ' + o.name) + '"><i class="cmt-dot drive k-' + esc(t.kind) + '"></i></td>';
    return '<td class="c"></td>';
  }
  function tosTable() {
    var h = '<thead><tr><th class="l">Target</th><th class="l hw">Hardware</th>' +
            OS.map(function (o) { return '<th class="c' + (o.device ? ' dev' : '') + '" title="' + esc(o.note || '') + '">' + esc(o.name) + '</th>'; }).join('') +
            '<th class="c">Programs</th></tr></thead><tbody>';
    var groups = (D.kinds || []).map(function (k) { return {id: k.id, name: k.name, rows: []}; });
    var planned = {id: 'planned', name: 'Planned', rows: []};
    var ws = words(), kept = ws.length ? programs.filter(function (p) { return progHits(p, ws); }) : [];
    var n = 0;
    targets.forEach(function (t) {
      if (!targetHits(t, ws, kept)) return;
      n++;
      if (t.status === 'placeholder') { planned.rows.push(t); return; }
      var g = groups.filter(function (x) { return x.id === t.kind; })[0];
      (g || planned).rows.push(t);
    });
    groups.concat([planned]).forEach(function (g) {
      if (!g.rows.length) return;
      h += '<tr class="grp"><th colspan="' + (OS.length + 3) + '"><i class="sw k-' + esc(g.id) + '"></i>' + esc(g.name) + '</th></tr>';
      g.rows.forEach(function (t) {
        h += '<tr class="cmt-trow' + (st.target === t.id ? ' on' : '') + (t.status === 'placeholder' ? ' muted' : '') + '" data-target="' + esc(t.id) + '" tabindex="0">' +
             '<th class="l"><code>' + esc(t.id) + '</code></th><td class="l hw" title="' + esc(t.desc) + '">' + esc(t.hardware || t.name) + '</td>' +
             OS.map(function (o) { return osCell(t, o); }).join('') +
             '<td class="c n">' + (t.status === 'placeholder' ? 'planned' : (t.programs || '–')) + '</td></tr>';
      });
    });
    $('cmt-tos').innerHTML = h + '</tbody>';
    $('cmt-tempty').hidden = n > 0;
    return n;
  }

  // ---- the programs against the targets
  function osBadges(p) {
    var b = OS.filter(function (o) { return p.os.indexOf(o.id) >= 0; }).map(function (o) { return '<span class="cmt-os" title="runs on ' + esc(o.name) + '">' + esc(o.name) + '</span>'; });
    Object.keys(p.via || {}).forEach(function (o) { b.push('<span class="cmt-os via" title="on ' + esc(osName[o] || o) + ' through ' + esc(p.via[o]) + '">' + esc(osName[o] || o) + ' via ' + esc(String(p.via[o]).split(':')[0]) + '</span>'); });
    return b.join('');
  }
  function shown() {
    var ws = words();
    return programs.filter(function (p) {
      if (st.target && p.targets.indexOf(st.target) < 0) return false;
      if (st.os && p.os.indexOf(st.os) < 0 && !(p.via || {})[st.os]) return false;
      return !ws.length || progHits(p, ws);
    });
  }
  function ptmTable() {
    var list = shown();
    var kinds = (D.kinds || []).map(function (k) { return {id: k.id, name: k.short || k.name, cols: progTargets.filter(function (t) { return t.kind === k.id; })}; })
                .filter(function (k) { return k.cols.length; });
    var cols = [];
    kinds.forEach(function (k) { cols = cols.concat(k.cols); });
    var h = '<thead><tr class="kinds"><th class="l prog"></th>' +
            kinds.map(function (k) { return '<th class="kh k-' + esc(k.id) + '" colspan="' + k.cols.length + '">' + esc(k.name) + '</th>'; }).join('') +
            '<th class="l"></th></tr><tr class="tg"><th class="l prog">Program</th>' +
            cols.map(function (t) {
              return '<th class="v' + (st.target === t.id ? ' on' : '') + '" data-target="' + esc(t.id) + '" data-tip="' + esc(t.id + ': ' + (t.hardware || t.name) + ' - click to keep its programs') + '"><span>' + esc(t.id) + '</span></th>';
            }).join('') + '<th class="l">Runs on</th></tr></thead><tbody>';
    var fam = null;
    list.forEach(function (p) {
      if (p.family !== fam) {
        fam = p.family;
        h += '<tr class="fam"><th colspan="' + (cols.length + 2) + '">' + esc(fam) + '</th></tr>';
      }
      h += '<tr class="prow" data-alias="' + esc(p.alias) + '" tabindex="0"><th class="l prog"><span class="pn">' + esc(p.alias) + '</span>' +
           (p.desc ? '<span class="pd">' + esc(p.desc) + '</span>' : '') + '</th>' +
           cols.map(function (t) {
             return p.targets.indexOf(t.id) >= 0 ? '<td class="c' + (st.target === t.id ? ' on' : '') + '" data-tip="' + esc(p.alias + ' on ' + t.id) + '"><i class="cmt-dot k-' + esc(t.kind) + '"></i></td>'
                                                 : '<td class="c' + (st.target === t.id ? ' on' : '') + '"></td>';
           }).join('') + '<td class="l osb">' + osBadges(p) + '</td></tr>';
    });
    $('cmt-ptm').innerHTML = h + '</tbody>';
    $('cmt-count').textContent = list.length + (list.length === programs.length ? '' : ' of ' + programs.length) + ' programs' +
      (st.target ? ' on ' + st.target : '') + (st.os ? ' for ' + (osName[st.os] || st.os) : '');
    $('cmt-empty').hidden = list.length > 0;
    $('cmt-clear').hidden = !(st.q || st.target || st.os);
  }
  function detailRow(p) {
    var cmds = p.targets.map(function (t) { return cmdLine('cx program run ' + p.alias + ' ' + t); }).join('');
    var link = p.link ? '<a href="' + esc(p.link) + '">its page →</a>' : '';
    var tags = p.tags.map(function (t) { return '<span class="cmt-tag">' + esc(t) + '</span>'; }).join('');
    var req = p.requires_os.length ? '<div class="cmt-note">needs ' + p.requires_os.map(function (o) { return esc(osName[o] || o); }).join(' or ') + '; elsewhere through its route' + '</div>' : '';
    return '<tr class="pdet"><td colspan="99"><div class="cmt-det"><div class="cmt-det-h"><b>' + esc(p.name) + '</b> <span class="cmt-repo">' + esc(p.repo) + '</span> ' + link + '</div>' +
           (p.desc ? '<p>' + esc(p.desc) + '</p>' : '') + (tags ? '<div class="cmt-tags">' + tags + '</div>' : '') + req + cmds + '</div></td></tr>';
  }

  function osChips() {
    $('cmt-os-chips').innerHTML = '<button type="button" data-os=""' + (st.os ? '' : ' class="on"') + '>any OS</button>' +
      OS.map(function (o) { return '<button type="button" data-os="' + esc(o.id) + '"' + (st.os === o.id ? ' class="on"' : '') + '>' + esc(o.name) + '</button>'; }).join('');
  }

  function keep() {
    var q = new URLSearchParams(location.search);
    ['q', 'target', 'os'].forEach(function (k) { if (st[k]) q.set(k, st[k]); else q.delete(k); });
    var s = q.toString();
    try { history.replaceState(null, '', location.pathname + (s ? '?' + s : '') + location.hash); } catch (e) { /* ignore */ }
  }
  // what the search keeps, beside it: the targets and the programs it leaves in the tables
  function render() {
    var nt = tosTable();
    osChips();
    ptmTable();
    keep();
    var all = targets.length, np = st.q ? programs.filter(function (p) { return progHits(p, words()); }).length : programs.length;
    $('cmt-qcount').textContent = st.q ? nt + ' of ' + all + ' targets · ' + np + ' of ' + programs.length + ' programs' : '';
  }

  function pickTarget(id, scroll) {
    st.target = st.target === id ? '' : id;
    render();
    if (scroll && st.target) $('cmt-sec-prog').scrollIntoView({behavior: 'smooth', block: 'start'});
  }

  // ---- the commands to try
  $('cmt-cmds').innerHTML = [
    ['pip install cmeta', 'the engine: the cx command (or the interactive installer of the cMeta project)'],
    ['cx repo get cTuningLabs@cmeta-aops', 'the open-source tools, tasks, targets and programs'],
    ['cx program targets', 'the targets this machine knows, and where each works'],
    ['cx program run test-hello-c-cpu cpu', 'the smallest program: compile and run it with what this machine has'],
    ['cx program run test-nmm-c-cpu android-cpu', 'the same kind of program on a phone over adb (the NDK set up on the way)'],
    ['cx cserver.cmeta.targets matrix', 'this page\'s first matrix in a terminal']
  ].map(function (x) { return '<div class="cmt-try-row">' + cmdLine(x[0]) + '<span>' + esc(x[1]) + '</span></div>'; }).join('');

  // ---- events
  $('cmt-q').value = st.q;
  $('cmt-q').addEventListener('input', function () { st.q = this.value.trim(); render(); });
  $('cmt-q').addEventListener('keydown', function (ev) { if (ev.key === 'Escape') { this.value = ''; st.q = ''; render(); } });
  // "/" anywhere but in a field: to the search
  document.addEventListener('keydown', function (ev) {
    var tag = (ev.target && ev.target.tagName) || '';
    if (ev.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(tag) && !ev.target.isContentEditable) { ev.preventDefault(); $('cmt-q').focus(); }
  });
  $('cmt-clear').addEventListener('click', function () { st.q = ''; st.target = ''; st.os = ''; $('cmt-q').value = ''; render(); });
  $('cmt-os-chips').addEventListener('click', function (ev) {
    var b = ev.target.closest('button');
    if (!b) return;
    st.os = b.getAttribute('data-os') || '';
    osChips(); ptmTable(); keep();
  });
  $('cmt-tos').addEventListener('click', function (ev) { var r = ev.target.closest('tr.cmt-trow'); if (r) pickTarget(r.getAttribute('data-target'), true); });
  $('cmt-tos').addEventListener('keydown', function (ev) { var r = ev.target.closest('tr.cmt-trow'); if (r && (ev.key === 'Enter' || ev.key === ' ')) { ev.preventDefault(); pickTarget(r.getAttribute('data-target'), true); } });
  $('cmt-ptm').addEventListener('click', function (ev) {
    var th = ev.target.closest('th.v');
    if (th) { pickTarget(th.getAttribute('data-target'), false); return; }
    if (ev.target.closest('a, button')) return;
    var r = ev.target.closest('tr.prow');
    if (!r) return;
    var next = r.nextElementSibling;
    if (next && next.classList.contains('pdet')) { next.remove(); r.classList.remove('open'); return; }
    var p = programs.filter(function (x) { return x.alias === r.getAttribute('data-alias'); })[0];
    if (!p) return;
    r.insertAdjacentHTML('afterend', detailRow(p));
    r.classList.add('open');
  });
  $('cmt-ptm').addEventListener('keydown', function (ev) { var r = ev.target.closest('tr.prow'); if (r && ev.key === 'Enter') r.click(); });

  // copy a command
  root.addEventListener('click', function (ev) {
    var b = ev.target.closest('.cmt-cp');
    if (!b) return;
    var t = b.getAttribute('data-copy');
    var done = function () { b.textContent = 'copied'; setTimeout(function () { b.textContent = 'copy'; }, 1200); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(t).then(done, done);
    else done();
  });

  // the hover layer: one tooltip for every cell that carries data-tip, larger than the mark it explains
  var tip = $('cmt-tip');
  root.addEventListener('mouseover', function (ev) {
    var el = ev.target.closest('[data-tip]');
    if (!el) { tip.hidden = true; return; }
    tip.textContent = el.getAttribute('data-tip');
    tip.hidden = false;
  });
  root.addEventListener('mousemove', function (ev) {
    if (tip.hidden) return;
    var x = ev.clientX + 14, y = ev.clientY + 16;
    var w = tip.offsetWidth, h = tip.offsetHeight;
    if (x + w > window.innerWidth - 8) x = ev.clientX - w - 10;
    if (y + h > window.innerHeight - 8) y = ev.clientY - h - 12;
    tip.style.left = x + 'px';
    tip.style.top = y + 'px';
  });
  root.addEventListener('mouseleave', function () { tip.hidden = true; });

  render();
})();
