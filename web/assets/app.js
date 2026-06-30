// Client-side filtering, sorting, scroll-reveal, and "not a match" rejection
// over server-rendered match cards.
(function () {
  var q = document.getElementById('q');
  var species = document.getElementById('species');
  var borough = document.getElementById('borough');
  var tier = document.getElementById('tier');
  var sort = document.getElementById('sort');
  var container = document.getElementById('cards');
  var empty = document.getElementById('empty');
  var counter = document.getElementById('visible-count');
  var hiddenToggle = document.getElementById('hidden-toggle');
  if (!container) return;
  var cards = Array.prototype.slice.call(container.querySelectorAll('.card'));

  // "Not a match" is per-browser only (this is a static, no-backend site) --
  // it declutters your own view. To permanently hide a match for everyone,
  // run `python -m petmatch.review` and rebuild the dashboard.
  var STORAGE_KEY = 'petmatch_rejected_v1';
  var rejected = {};
  try {
    JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]').forEach(function (id) {
      rejected[id] = true;
    });
  } catch (e) { /* localStorage unavailable */ }
  var showRejected = false;

  function saveRejected() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(Object.keys(rejected)));
    } catch (e) { /* ignore */ }
  }

  function updateHiddenToggle() {
    if (!hiddenToggle) return;
    var n = Object.keys(rejected).length;
    if (n === 0) {
      hiddenToggle.hidden = true;
      return;
    }
    hiddenToggle.hidden = false;
    hiddenToggle.textContent = showRejected
      ? 'Hide ' + n + ' rejected again'
      : n + ' rejected — show';
  }

  function apply() {
    var term = (q.value || '').trim().toLowerCase();
    var sp = species.value, bo = borough.value, ti = tier.value;
    var visible = 0;
    cards.forEach(function (c) {
      var isRejected = !!rejected[c.dataset.id];
      var ok = true;
      if (isRejected && !showRejected) ok = false;
      if (sp && c.dataset.species !== sp) ok = false;
      if (bo && c.dataset.borough !== bo && c.dataset.lostborough !== bo) ok = false;
      if (ti && c.dataset.tier !== ti) ok = false;
      if (term && c.dataset.text.indexOf(term) === -1) ok = false;
      c.classList.toggle('is-rejected', isRejected && showRejected);
      c.hidden = !ok;
      if (ok) visible++;
    });
    if (empty) empty.hidden = visible !== 0;
    if (counter) counter.textContent = visible + ' shown';
    updateHiddenToggle();
  }

  function resort() {
    var key = sort.value === 'photo' ? 'photo' : 'conf';
    cards.sort(function (a, b) {
      return parseFloat(b.dataset[key]) - parseFloat(a.dataset[key]);
    });
    cards.forEach(function (c) { container.appendChild(c); });
  }

  container.addEventListener('click', function (e) {
    var btn = e.target.closest ? e.target.closest('.reject-btn') : null;
    if (!btn) return;
    var card = btn.closest('.card');
    if (!card) return;
    rejected[card.dataset.id] = true;
    saveRejected();
    card.classList.add('is-leaving');
    window.setTimeout(apply, 240);
  });

  if (hiddenToggle) {
    hiddenToggle.addEventListener('click', function () {
      showRejected = !showRejected;
      apply();
    });
  }

  [q, species, borough, tier].forEach(function (el) {
    el.addEventListener('input', apply);
  });
  sort.addEventListener('change', function () { resort(); apply(); });

  resort();
  apply();

  // Satisfying-but-restrained scroll reveal: cards fade/slide in as they
  // enter the viewport, lightly staggered. Skips entirely if the visitor
  // has asked for reduced motion.
  var reduceMotion = window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (!reduceMotion && 'IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('in-view');
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.1, rootMargin: '0px 0px -10% 0px' });
    cards.forEach(function (c, i) {
      c.style.transitionDelay = (i % 6) * 45 + 'ms';
      io.observe(c);
    });
  } else {
    cards.forEach(function (c) { c.classList.add('in-view'); });
  }
})();
