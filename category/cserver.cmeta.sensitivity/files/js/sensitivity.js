/* Licensed under the Apache License, Version 2.0. See the COPYRIGHT and LICENSE files in the project root for details.
 *
 * cserver.cmeta.sensitivity (Sensitivity and access - cMeta for organisations): the lessons of index.html one at a time
 * with Back / Next, a table of contents and a bar of steps (or all on one page); the lesson kept in the address
 * (?lesson=N) so a link opens it; the labels' table and the check from CMS_DATA (files/sensitivity.yaml); lesson 6 asked
 * live from the server (?native_action=scope, under the scope the host passed for the reader). A- / A+ (the size) and the
 * theme - the one of every page of a cMeta server, cmeta.theme - are kept in the browser.
 */
(function () {
  'use strict';

  var D = window.CMS_DATA || {};
  var C = window.CMS_CONFIG || {};
  var root = document.getElementById('cms');
  if (!root) return;

  var $ = function (id) { return document.getElementById(id); };
  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]; }); };

  var SHARED_THEME = 'cmeta.theme';                  // the theme of every page of a cMeta server
  var THEME_KEY = 'cserver.cmeta.sensitivity.theme', SCALE_KEY = 'cserver.cmeta.sensitivity.scale';
  function stored(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function store(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } }

  // ------------------------------------------------------------------ the theme and the size
  // inside the cPlatform's shell the shell's theme (it may switch without a reload; no switch of our own); on a cMeta
  // server the one theme of its pages (cmeta.theme), this page's switch, followed when another tab changes it
  function paintLabels() {
    var dark = root.classList.contains('dark');
    (D.labels || []).forEach(function (l) { root.style.setProperty('--l-' + l.id, dark ? (l.dark || l.light) : l.light); });
  }
  function setDark(dark) { root.classList.toggle('dark', !!dark); paintLabels(); }
  if (C.hosted) {
    root.classList.add('hosted');
    $('cms-theme').hidden = true;
    var follow = function () {
      var t = document.documentElement.getAttribute('data-ctp-theme');
      setDark(t ? t === 'dark' : C.dark_mode === true);
    };
    new MutationObserver(follow).observe(document.documentElement, {attributes: true, attributeFilter: ['data-ctp-theme']});
    follow();
  } else {
    var t0 = stored(SHARED_THEME) || stored(THEME_KEY);
    setDark(t0 ? t0 === 'dark' : C.dark_mode === true);
    $('cms-theme').addEventListener('click', function () {
      var dark = !root.classList.contains('dark');
      setDark(dark);
      store(SHARED_THEME, dark ? 'dark' : 'light');
      store(THEME_KEY, dark ? 'dark' : 'light');
    });
    window.addEventListener('storage', function (e) { if (e.key === SHARED_THEME && e.newValue) setDark(e.newValue === 'dark'); });
  }

  var scale = 1;
  function setScale(s, keep) {
    scale = Math.max(0.7, Math.min(2.2, Math.round(s * 10) / 10));
    $('cms-body').style.zoom = String(scale);
    if (keep) store(SCALE_KEY, String(scale));
  }
  var askedFont = parseFloat((/[?&]font=([\d.]+)/.exec(location.search) || [])[1]);
  setScale(askedFont > 0 ? askedFont : (parseFloat(stored(SCALE_KEY)) || 1), false);
  $('cms-smaller').addEventListener('click', function () { setScale(scale - 0.1, true); });
  $('cms-bigger').addEventListener('click', function () { setScale(scale + 0.1, true); });

  // ------------------------------------------------------------------ the labels (lesson 1)
  function chip(id, text) {
    return '<span class="cms-label l-' + esc(id) + '">' + esc(text || id) + '</span>';
  }
  var labelName = {};
  (function () {
    var rows = ['<thead><tr><th>label</th><th>for</th><th>for example</th><th>also read as</th></tr></thead><tbody>'];
    (D.labels || []).forEach(function (l) {
      labelName[l.id] = l.name;
      rows.push('<tr><td>' + chip(l.id, l.name) + '</td><td>' + esc(l.for) + '</td><td class="cms-muted">' + esc(l.examples) +
                '</td><td class="cms-syn">' + (l.synonyms || []).map(function (s) { return '<code>' + esc(s) + '</code>'; }).join(' ') + '</td></tr>');
    });
    rows.push('</tbody>');
    $('cms-labels').innerHTML = rows.join('');
  })();

  // ------------------------------------------------------------------ the lessons, the table of contents, the steps
  var lessons = Array.prototype.slice.call(root.querySelectorAll('.cms-lesson'));
  var current = Math.max(1, Math.min(lessons.length, parseInt(C.lesson, 10) || 1));
  var seen = {};
  var all = /[?&]all=1\b/.test(location.search);

  $('cms-toc').innerHTML = lessons.map(function (s, i) {
    return '<a href="?lesson=' + (i + 1) + '" data-n="' + (i + 1) + '"><span class="n">' + (i + 1) + '</span><span class="t">' +
           esc(s.getAttribute('data-title')) + '</span></a>';
  }).join('');
  $('cms-steps').innerHTML = lessons.map(function () { return '<i></i>'; }).join('');

  function keepAddress() {
    try {
      var q = new URLSearchParams(location.search);
      q.set('lesson', String(current));
      if (all) q.set('all', '1'); else q.delete('all');
      history.replaceState(null, '', location.pathname + '?' + q.toString() + location.hash);
    } catch (e) { /* an old browser: the address stays as it was */ }
  }

  function show(n, scroll) {
    current = Math.max(1, Math.min(lessons.length, n));
    seen[current] = true;
    lessons.forEach(function (s, i) { s.classList.toggle('on', i + 1 === current); });
    Array.prototype.forEach.call($('cms-toc').querySelectorAll('a'), function (a) {
      var k = parseInt(a.getAttribute('data-n'), 10);
      a.classList.toggle('on', !all && k === current);
      a.classList.toggle('done', !!seen[k] && k !== current);
    });
    Array.prototype.forEach.call($('cms-steps').children, function (b, i) { b.classList.toggle('on', i < current); });
    $('cms-prev').disabled = current === 1;
    $('cms-next').disabled = current === lessons.length;
    $('cms-where').textContent = current + ' of ' + lessons.length + ' - ' + lessons[current - 1].getAttribute('data-title');
    if (current === 6 || all) live(false);
    keepAddress();
    if (scroll) root.scrollIntoView({block: 'start', behavior: 'smooth'});
  }

  function setAll(on) {
    all = !!on;
    root.classList.toggle('all', all);
    $('cms-all').setAttribute('aria-pressed', all ? 'true' : 'false');
    show(current, false);
  }

  $('cms-toc').addEventListener('click', function (e) {
    var a = e.target.closest('a[data-n]');
    if (!a) return;
    e.preventDefault();
    var n = parseInt(a.getAttribute('data-n'), 10);
    if (all) {
      var s = lessons[n - 1];
      current = n;
      keepAddress();
      if (s) s.scrollIntoView({block: 'start', behavior: 'smooth'});
      return;
    }
    show(n, true);
  });
  $('cms-prev').addEventListener('click', function () { show(current - 1, true); });
  $('cms-next').addEventListener('click', function () { show(current + 1, true); });
  $('cms-all').addEventListener('click', function () { setAll(!all); });
  document.addEventListener('keydown', function (e) {
    if (all || e.altKey || e.ctrlKey || e.metaKey) return;
    var t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
    if (e.key === 'ArrowRight') { show(current + 1, true); }
    if (e.key === 'ArrowLeft') { show(current - 1, true); }
  });

  // ------------------------------------------------------------------ lesson 6: what you can see, asked live
  var asked = false;
  function yes(b) { return b ? '<span class="cms-yes">yes</span>' : '<span class="cms-no">-</span>'; }

  function renderLive(j) {
    var box = $('cms-live');
    if (!j || j.error) {
      box.innerHTML = '<p class="cms-warn">The engine could not say: ' + esc((j && j.error) || 'no answer') + '</p>';
      return;
    }
    if (j.supported === false) {
      box.innerHTML = '<p>' + esc(j.message) + '</p>';
      return;
    }
    var out = [];
    var facts = [];
    if (j.scoped) {
      facts.push('<span>Your clearance: ' + (j.clearance ? chip(j.clearance, labelName[j.clearance] || j.clearance) :
                 '<b>none</b> <span class="cms-muted">(some repositories are hidden from you by name)</span>') + '</span>');
      facts.push('<span>Writes: ' + (j.write_scoped ? '<b>only into the repositories marked yes</b>' :
                 '<b>not limited by the engine</b> <span class="cms-muted">(the site\'s own rules apply)</span>') + '</span>');
    } else {
      facts.push('<span><b>No scope</b>: you read everything this machine holds - as from a shell on it.</span>');
    }
    facts.push('<span class="cms-muted">engine ' + esc(j.engine || '?') + '</span>');
    out.push('<div class="cms-facts">' + facts.join('') + '</div>');

    if (j.scoped && j.admin) {
      out.push('<p class="cms-note">You are an administrator here: every repository is listed, with why your own request reads ' +
               'it or not. Each person sees only the rows they read.</p>');
    } else if (j.scoped) {
      out.push('<p class="cms-note">The repositories you read are listed; the names of the others are not shown to you.</p>');
    } else if (!j.listed) {
      out.push('<p class="cms-note">This server names its repositories only to a browser on its own machine, behind its ' +
               'password, or to its administrators.</p>');
    }

    var rows = j.rows || [];
    // the write column only where the engine limits writes (write_repos): a site that keeps its own write rules
    // passes none, and the engine's "yes" for every repository read would say more than the site allows
    var writes = !!j.write_scoped;
    if (rows.length) {
      var t = ['<thead><tr><th>repository</th><th>sensitivity</th><th>read</th>' + (writes ? '<th>write</th>' : '') +
               '<th>why</th></tr></thead><tbody>'];
      rows.forEach(function (r) {
        t.push('<tr><td><code>' + esc(r.alias) + '</code></td><td>' + chip(r.sensitivity, labelName[r.sensitivity] || r.sensitivity) +
               (r.from_text ? ' <span class="cms-from">' + esc(r.from_text) + '</span>' : '') + '</td><td>' + yes(r.read) +
               '</td>' + (writes ? '<td>' + yes(r.write) + '</td>' : '') + '<td class="cms-why">' + esc(r.why_text) + '</td></tr>');
      });
      t.push('</tbody>');
      out.push('<div class="cms-scroll"><table class="cms-live-table">' + t.join('') + '</table></div>');
      out.push('<p class="cms-muted cms-small">' + rows.length + ' repositories listed: you read ' + j.read +
               (writes ? ', you may write into ' + j.write : '') + '.</p>');
    } else if (j.listed !== false) {
      out.push('<p class="cms-note">You read no repository of this server.</p>');
    }
    box.innerHTML = out.join('');
  }

  function live(force) {
    if (asked && !force) return;
    asked = true;
    $('cms-live').innerHTML = '<p class="cms-muted">Asking the engine ...</p>';
    var url = (C.api_url || '?') + 'native_action=scope';
    fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}', credentials: 'same-origin'})
      .then(function (r) { return r.json(); })
      .then(renderLive)
      .catch(function (e) { renderLive({error: String(e)}); });
  }
  $('cms-refresh').addEventListener('click', function () { live(true); });

  // ------------------------------------------------------------------ lesson 8: the check
  var answered = {}, right = 0;
  var quiz = D.quiz || [];
  function score() {
    var n = Object.keys(answered).length;
    $('cms-score').innerHTML = n ? (right + ' of ' + n + ' right' + (n === quiz.length ?
      (right === quiz.length ? ' - all of them.' : '. <button type="button" class="cms-tool" id="cms-again">Try again</button>') : '')) : '';
    var again = $('cms-again');
    if (again) again.addEventListener('click', resetQuiz);
  }
  function renderQuiz() {
    $('cms-quiz').innerHTML = quiz.map(function (q, i) {
      return '<li data-q="' + i + '"><p class="cms-q">' + esc(q.q) + '</p><div class="cms-opts">' +
        (q.options || []).map(function (o, k) { return '<button type="button" class="cms-opt" data-k="' + k + '">' + esc(o) + '</button>'; }).join('') +
        '</div><p class="cms-explain" hidden></p></li>';
    }).join('');
  }
  function resetQuiz() { answered = {}; right = 0; renderQuiz(); score(); }
  $('cms-quiz').addEventListener('click', function (e) {
    var b = e.target.closest('.cms-opt');
    if (!b || b.disabled) return;
    var li = b.closest('li[data-q]');
    var i = parseInt(li.getAttribute('data-q'), 10), k = parseInt(b.getAttribute('data-k'), 10);
    if (answered[i] !== undefined) return;
    var q = quiz[i] || {};
    var ok = k === q.answer;
    answered[i] = k;
    if (ok) right += 1;
    Array.prototype.forEach.call(li.querySelectorAll('.cms-opt'), function (x) {
      var kk = parseInt(x.getAttribute('data-k'), 10);
      x.disabled = true;
      if (kk === q.answer) x.classList.add('right');
      else if (kk === k) x.classList.add('wrong');
    });
    var ex = li.querySelector('.cms-explain');
    ex.hidden = false;
    ex.textContent = (ok ? 'Right. ' : 'Not quite. ') + (q.why || '');
    score();
  });
  renderQuiz();

  setAll(all);
})();
