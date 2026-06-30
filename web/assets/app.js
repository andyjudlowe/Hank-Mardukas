// Client-side filtering & sorting over server-rendered match cards.
(function () {
  var q = document.getElementById('q');
  var species = document.getElementById('species');
  var borough = document.getElementById('borough');
  var tier = document.getElementById('tier');
  var sort = document.getElementById('sort');
  var container = document.getElementById('cards');
  var empty = document.getElementById('empty');
  var counter = document.getElementById('visible-count');
  if (!container) return;
  var cards = Array.prototype.slice.call(container.querySelectorAll('.card'));

  function apply() {
    var term = (q.value || '').trim().toLowerCase();
    var sp = species.value, bo = borough.value, ti = tier.value;
    var visible = 0;
    cards.forEach(function (c) {
      var ok = true;
      if (sp && c.dataset.species !== sp) ok = false;
      if (bo && c.dataset.borough !== bo && c.dataset.lostborough !== bo) ok = false;
      if (ti && c.dataset.tier !== ti) ok = false;
      if (term && c.dataset.text.indexOf(term) === -1) ok = false;
      c.hidden = !ok;
      if (ok) visible++;
    });
    if (empty) empty.hidden = visible !== 0;
    if (counter) counter.textContent = visible + ' shown';
  }

  function resort() {
    var key = sort.value === 'photo' ? 'photo' : 'conf';
    cards.sort(function (a, b) {
      return parseFloat(b.dataset[key]) - parseFloat(a.dataset[key]);
    });
    cards.forEach(function (c) { container.appendChild(c); });
  }

  [q, species, borough, tier].forEach(function (el) {
    el.addEventListener('input', apply);
  });
  sort.addEventListener('change', function () { resort(); apply(); });
  apply();
})();
