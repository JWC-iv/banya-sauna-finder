/*
 * Banya Press Sauna Finder.
 * The Squarespace Code Block only needs:
 *   <div id="banya-finder"></div>
 *   <script>window.BANYA_FINDER_CONFIG = { dataUrl: '...' };</script>
 *   <script src="https://<github pages>/site/finder.js"></script>
 * This file loads its own CSS, the Labrada font and the MapLibre map library.
 */
(function () {
  'use strict';

  // ---------- Settings (override any of these in BANYA_FINDER_CONFIG) ----------
  var CONFIG = Object.assign({
    mount: '#banya-finder',
    dataUrl: 'data/venues.json',
    mapStyle: 'https://tiles.openfreemap.org/styles/positron',
    // A filter only appears once this share of venues has a known value for it.
    minFilterCoverage: 0.9,
    showAllFilters: false,
    SHOW_BANYA_APPROVED: false
  }, window.BANYA_FINDER_CONFIG || {});

  var MAPLIBRE_JS = 'https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js';
  var MAPLIBRE_CSS = 'https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css';
  var FONT_CSS = 'https://fonts.googleapis.com/css2?family=Labrada:wght@300;400&display=swap';
  var SCRIPT_URL = document.currentScript ? document.currentScript.src : '';

  // ---------- Labels shown to visitors ----------
  var LABELS = {
    venue_type: {
      bathhouse: 'Bathhouse', banya: 'Banya', korean_spa: 'Korean spa', sauna_studio: 'Sauna studio',
      contrast_therapy: 'Contrast therapy', mobile_or_floating_sauna: 'Mobile or floating', day_spa_day_pass: 'Day spa'
    },
    heat_types: {
      traditional_electric: 'Electric sauna', wood_fired: 'Wood-fired', infrared: 'Infrared',
      steam: 'Steam', smoke: 'Smoke sauna', banya: 'Russian banya'
    },
    cold_plunge: { tub: 'Plunge tub', pool: 'Cold pool', natural_water: 'Natural water', none: 'No cold plunge' },
    access: { walk_in: 'Walk-in', reservation_required: 'Reservation', membership_only: 'Members only' },
    gender_policy: { coed: 'Co-ed', segregated: 'Single-gender', both: 'Co-ed and single-gender days' },
    session_type: { communal: 'Communal', private: 'Private', both: 'Communal or private' }
  };

  // The filter list. Add, remove or reorder entries here; nothing else needs to change.
  var FILTERS = [
    { key: 'venue_type', label: 'Type' },
    { key: 'heat_types', label: 'Heat', isList: true },
    { key: 'cold_plunge', label: 'Cold plunge', skip: ['none'] },
    { key: 'access', label: 'Access' },
    { key: 'gender_policy', label: 'Gender policy' },
    { key: 'session_type', label: 'Sessions' }
  ];

  // Types the public page never shows (gyms are parked for later).
  var HIDDEN_TYPES = ['gym', 'hotel'];

  // ---------- Data loading: the only place that knows where venues come from ----------
  // When the data moves to a backend (e.g. Supabase), only this function changes.
  function loadVenues() {
    return fetch(CONFIG.dataUrl, { cache: 'no-cache' })
      .then(function (r) {
        if (!r.ok) throw new Error('Could not load venues (' + r.status + ')');
        return r.json();
      })
      .then(function (json) {
        var list = Array.isArray(json) ? json : json.venues;
        return list.filter(function (v) { return HIDDEN_TYPES.indexOf(v.venue_type) === -1; });
      });
  }

  // ---------- Small helpers ----------
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function loadCss(href) {
    if (document.querySelector('link[href="' + href + '"]')) return;
    var l = document.createElement('link');
    l.rel = 'stylesheet';
    l.href = href;
    document.head.appendChild(l);
  }
  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      if (window.maplibregl) return resolve();
      var s = document.createElement('script');
      s.src = src;
      s.onload = resolve;
      s.onerror = function () { reject(new Error('Could not load ' + src)); };
      document.head.appendChild(s);
    });
  }
  function milesBetween(a, b) {
    var R = 3958.8, toRad = Math.PI / 180;
    var dLat = (b.lat - a.lat) * toRad, dLng = (b.lng - a.lng) * toRad;
    var h = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(a.lat * toRad) * Math.cos(b.lat * toRad) * Math.sin(dLng / 2) * Math.sin(dLng / 2);
    return 2 * R * Math.asin(Math.sqrt(h));
  }
  function hasValue(v, f) {
    var val = v[f.key];
    if (f.isList) return Array.isArray(val) && val.length > 0;
    return val != null && val !== 'unknown';
  }

  // ---------- Opening hours ----------
  // Handles the common OSM forms, e.g. "Mo,We-Fr 12:00-23:00; Sa,Su 10:00-23:00" and "24/7".
  // Returns true (open), false (closed) or null (can't tell).
  var DAYS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'];
  var STATE_TZ = {
    CA: 'America/Los_Angeles', WA: 'America/Los_Angeles', OR: 'America/Los_Angeles', NV: 'America/Los_Angeles',
    AZ: 'America/Phoenix', CO: 'America/Denver', UT: 'America/Denver', NM: 'America/Denver', WY: 'America/Denver',
    MT: 'America/Denver', ID: 'America/Boise', AK: 'America/Anchorage', HI: 'Pacific/Honolulu',
    TX: 'America/Chicago', IL: 'America/Chicago', MN: 'America/Chicago', WI: 'America/Chicago', IA: 'America/Chicago',
    MO: 'America/Chicago', AR: 'America/Chicago', LA: 'America/Chicago', MS: 'America/Chicago', AL: 'America/Chicago',
    OK: 'America/Chicago', KS: 'America/Chicago', NE: 'America/Chicago', SD: 'America/Chicago', ND: 'America/Chicago',
    TN: 'America/Chicago'
  };

  function parseHours(text) {
    if (!text) return null;
    if (text.trim() === '24/7') return DAYS.map(function () { return [[0, 1440]]; });
    var week = DAYS.map(function () { return []; });
    var rules = text.split(';');
    for (var i = 0; i < rules.length; i++) {
      var m = rules[i].trim().match(/^([A-Za-z,\- ]+?)\s+(off|closed|[\d:,\- ]+)$/);
      if (!m) return null;
      var days = [];
      m[1].replace(/\s/g, '').split(',').forEach(function (part) {
        var ends = part.split('-');
        var a = DAYS.indexOf(ends[0]), b = DAYS.indexOf(ends[1] || ends[0]);
        if (a < 0 || b < 0) { days = null; return; }
        for (var d = a; ; d = (d + 1) % 7) { if (days) days.push(d); if (d === b) break; }
      });
      if (!days) return null;
      var ranges = [];
      if (!/off|closed/.test(m[2])) {
        var ok = m[2].split(',').every(function (r) {
          var t = r.trim().match(/^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$/);
          if (!t) return false;
          var start = +t[1] * 60 + +t[2], end = +t[3] * 60 + +t[4];
          if (end <= start) end += 1440;
          ranges.push([start, end]);
          return true;
        });
        if (!ok) return null;
      }
      days.forEach(function (d) { week[d] = ranges; });
    }
    return week;
  }

  function isOpenNow(v) {
    var week = parseHours(v.hours);
    if (!week) return null;
    var parts = new Intl.DateTimeFormat('en-US', {
      timeZone: STATE_TZ[v.state] || 'America/New_York',
      weekday: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'
    }).formatToParts(new Date());
    var get = function (t) { return parts.filter(function (p) { return p.type === t; })[0].value; };
    var day = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].indexOf(get('weekday'));
    var mins = +get('hour') * 60 + +get('minute');
    var inRange = function (ranges, t) { return ranges.some(function (r) { return t >= r[0] && t < r[1]; }); };
    // Today's hours, or yesterday's hours that ran past midnight.
    return inRange(week[day], mins) || inRange(week[(day + 6) % 7], mins + 1440);
  }

  // ---------- Map pin: black drop with steam lines, drawn at 2x for sharp screens ----------
  var PIN_SVG =
    '<svg xmlns="http://www.w3.org/2000/svg" width="80" height="96" viewBox="0 0 40 48">' +
    '<path d="M20 47C20 47 4 30.5 4 18a16 16 0 1 1 32 0c0 12.5-16 29-16 29z" fill="#000"/>' +
    '<g fill="none" stroke="#EBCEAD" stroke-width="2.2" stroke-linecap="round">' +
    '<path d="M13.5 27c-2.5-2.5 2.5-4.5 0-7s2.5-4.5 0-7"/>' +
    '<path d="M20 27c-2.5-2.5 2.5-4.5 0-7s2.5-4.5 0-7"/>' +
    '<path d="M26.5 27c-2.5-2.5 2.5-4.5 0-7s2.5-4.5 0-7"/></g></svg>';

  // ---------- The finder ----------
  function Finder(root) {
    this.root = root;
    this.venues = [];
    this.active = {};        // filter key -> list of chosen values
    this.openNow = false;
    this.approvedOnly = false;
    this.origin = null;      // { lat, lng, label } after a search
    this.selectedId = null;
    this.view = 'list';
    this.map = null;
    this.popup = null;
    this.originMarker = null;
  }

  Finder.prototype.start = function () {
    var self = this;
    this.renderShell();
    loadVenues()
      .then(function (venues) {
        self.venues = venues;
        self.renderFilters();
        self.update();
        return loadScript(MAPLIBRE_JS).then(function () { self.initMap(); });
      })
      .catch(function (err) {
        self.$('.bf-list').innerHTML = '<li class="bf-empty">Sorry, the sauna list could not be loaded. ' + esc(err.message) + '</li>';
      });
  };

  Finder.prototype.$ = function (sel) { return this.root.querySelector(sel); };

  Finder.prototype.renderShell = function () {
    var self = this;
    this.root.classList.add('bf');
    this.root.innerHTML =
      '<h2 class="bf-title">Find a Sauna</h2>' +
      '<p class="bf-intro">Bathhouses, banyas and sauna studios across the US.</p>' +
      '<form class="bf-search" role="search">' +
      '  <input type="search" name="q" placeholder="City, address or ZIP" aria-label="Search by city, address or ZIP" autocomplete="off">' +
      '  <button class="bf-btn" type="submit">Search</button>' +
      '  <button class="bf-btn bf-btn--ghost" type="button" data-locate>Use my location</button>' +
      '</form>' +
      '<p class="bf-search-msg" aria-live="polite"></p>' +
      '<div class="bf-toolbar">' +
      '  <div class="bf-tabs" role="tablist">' +
      '    <button class="bf-tab" role="tab" data-view="list" aria-selected="true">List</button>' +
      '    <button class="bf-tab" role="tab" data-view="map" aria-selected="false">Map</button>' +
      '  </div>' +
      '  <button class="bf-filter-toggle" type="button" aria-expanded="false">Filters</button>' +
      '  <span class="bf-count" aria-live="polite"></span>' +
      '</div>' +
      '<div class="bf-filters" hidden></div>' +
      '<div class="bf-body">' +
      '  <div class="bf-panel bf-panel--list"><ul class="bf-list"></ul></div>' +
      '  <div class="bf-panel bf-panel--map" hidden><div class="bf-map"></div></div>' +
      '</div>';

    this.$('.bf-search').addEventListener('submit', function (e) {
      e.preventDefault();
      self.search(this.q.value.trim());
    });
    this.$('[data-locate]').addEventListener('click', function () { self.locate(); });
    this.root.querySelectorAll('.bf-tab').forEach(function (tab) {
      tab.addEventListener('click', function () { self.setView(tab.getAttribute('data-view')); });
    });
    this.$('.bf-filter-toggle').addEventListener('click', function () {
      var panel = self.$('.bf-filters');
      panel.hidden = !panel.hidden;
      this.setAttribute('aria-expanded', String(!panel.hidden));
    });
    this.$('.bf-list').addEventListener('click', function (e) {
      if (e.target.closest('a')) return;
      if (e.target.closest('[data-clear]')) return self.clearFilters();
      var card = e.target.closest('.bf-card');
      if (card) self.select(card.getAttribute('data-id'), 'list');
    });
  };

  // Which filters have enough data to be useful.
  Finder.prototype.visibleFilters = function () {
    var venues = this.venues;
    return FILTERS.filter(function (f) {
      if (CONFIG.showAllFilters || !venues.length) return true;
      var known = venues.filter(function (v) { return hasValue(v, f); }).length;
      return known / venues.length >= CONFIG.minFilterCoverage;
    });
  };

  Finder.prototype.renderFilters = function () {
    var self = this;
    var venues = this.venues;
    var html = this.visibleFilters().map(function (f) {
      // Only offer values that at least one venue actually has.
      var present = {};
      venues.forEach(function (v) {
        [].concat(v[f.key] || []).forEach(function (val) { present[val] = true; });
      });
      var chips = Object.keys(LABELS[f.key]).filter(function (val) {
        return present[val] && (f.skip || []).indexOf(val) === -1;
      }).map(function (val) {
        return '<button type="button" class="bf-chip" aria-pressed="false" data-key="' + f.key + '" data-val="' + val + '">' +
          esc(LABELS[f.key][val]) + '</button>';
      }).join('');
      if (!chips) return '';
      return '<div class="bf-group"><p class="bf-group-label">' + esc(f.label) + '</p><div class="bf-chips">' + chips + '</div></div>';
    }).join('');

    var hoursKnown = venues.filter(function (v) { return v.hours; }).length;
    var extras = '';
    if (CONFIG.showAllFilters || hoursKnown / venues.length >= CONFIG.minFilterCoverage) {
      extras += '<button type="button" class="bf-chip" aria-pressed="false" data-special="openNow">Open now</button>';
    }
    if (CONFIG.SHOW_BANYA_APPROVED) {
      extras += '<button type="button" class="bf-chip" aria-pressed="false" data-special="approvedOnly">Banya Approved</button>';
    }
    if (extras) html = '<div class="bf-group"><div class="bf-chips">' + extras + '</div></div>' + html;

    html += '<div class="bf-filter-foot"><span>Places that haven\'t listed a detail are hidden while that filter is on.</span>' +
      '<button type="button" class="bf-link-btn" data-clear>Clear filters</button></div>';

    var panel = this.$('.bf-filters');
    panel.innerHTML = html;
    panel.addEventListener('click', function (e) {
      if (e.target.closest('[data-clear]')) return self.clearFilters();
      var chip = e.target.closest('.bf-chip');
      if (!chip) return;
      var on = chip.getAttribute('aria-pressed') !== 'true';
      chip.setAttribute('aria-pressed', String(on));
      var special = chip.getAttribute('data-special');
      if (special) {
        self[special] = on;
      } else {
        var key = chip.getAttribute('data-key'), val = chip.getAttribute('data-val');
        var list = self.active[key] || [];
        self.active[key] = on ? list.concat(val) : list.filter(function (x) { return x !== val; });
      }
      self.update();
    });
  };

  Finder.prototype.clearFilters = function () {
    this.active = {};
    this.openNow = false;
    this.approvedOnly = false;
    this.root.querySelectorAll('.bf-filters .bf-chip').forEach(function (c) { c.setAttribute('aria-pressed', 'false'); });
    this.update();
  };

  // Within one filter, any chosen value matches. Across filters, all must match.
  Finder.prototype.matches = function (v) {
    var active = this.active;
    var ok = Object.keys(active).every(function (key) {
      var chosen = active[key];
      if (!chosen.length) return true;
      return [].concat(v[key] || []).some(function (val) { return chosen.indexOf(val) !== -1; });
    });
    if (!ok) return false;
    if (this.openNow && isOpenNow(v) !== true) return false;
    if (this.approvedOnly && v.banya_approved !== true) return false;
    return true;
  };

  Finder.prototype.results = function () {
    var self = this;
    var list = this.venues.filter(function (v) { return self.matches(v); });
    list.forEach(function (v) { v._miles = self.origin ? milesBetween(self.origin, v) : null; });
    list.sort(function (a, b) {
      return self.origin ? a._miles - b._miles : a.name.localeCompare(b.name);
    });
    return list;
  };

  Finder.prototype.update = function () {
    var list = this.results();
    this.current = list;
    var n = list.length;
    this.$('.bf-count').textContent = n + (n === 1 ? ' sauna' : ' saunas') +
      (this.origin ? ' near ' + this.origin.label : '');
    this.$('.bf-list').innerHTML = n ? list.map(cardHtml).join('') :
      '<li class="bf-empty">No saunas match these filters. <button type="button" class="bf-link-btn" data-clear>Clear filters</button></li>';
    if (this.selectedId) this.markSelected(this.selectedId);
    this.updateMap();
  };

  function cardHtml(v) {
    var tags = [];
    (v.heat_types || []).forEach(function (h) { tags.push(LABELS.heat_types[h]); });
    if (LABELS.cold_plunge[v.cold_plunge]) tags.push(LABELS.cold_plunge[v.cold_plunge]);
    if (LABELS.access[v.access]) tags.push(LABELS.access[v.access]);
    if (v.day_pass_price_usd != null) tags.push('From $' + v.day_pass_price_usd);
    var open = isOpenNow(v);
    var meta = [LABELS.venue_type[v.venue_type]];
    if (v._miles != null) meta.push(v._miles < 10 ? v._miles.toFixed(1) + ' mi' : Math.round(v._miles) + ' mi');
    if (open !== null) meta.push('<span class="bf-open">' + (open ? 'Open now' : 'Closed now') + '</span>');
    var approved = CONFIG.SHOW_BANYA_APPROVED && v.banya_approved === true ? '<span class="bf-approved">Banya Approved</span>' : '';
    return '<li class="bf-card" data-id="' + esc(v.id) + '" tabindex="0">' +
      '<h3>' + esc(v.name) + approved + '</h3>' +
      '<p class="bf-meta">' + meta.map(function (m, i) { return i === meta.length - 1 && open !== null ? m : esc(m); }).join(' · ') + '</p>' +
      '<p>' + esc(v.address) + ', ' + esc(v.city) + ', ' + esc(v.state) + ' ' + esc(v.zip || '') + '</p>' +
      (v.phone ? '<p><a href="tel:' + esc(v.phone.replace(/[^\d+]/g, '')) + '">' + esc(v.phone) + '</a></p>' : '') +
      (tags.length ? '<div class="bf-tags">' + tags.map(function (t) { return '<span class="bf-tag">' + esc(t) + '</span>'; }).join('') + '</div>' : '') +
      (v.website ? '<a class="bf-accent" href="' + esc(v.website) + '" target="_blank" rel="noopener">Visit website →</a>' : '') +
      '</li>';
  }

  Finder.prototype.setView = function (view) {
    this.view = view;
    this.root.querySelectorAll('.bf-tab').forEach(function (t) {
      t.setAttribute('aria-selected', String(t.getAttribute('data-view') === view));
    });
    this.$('.bf-panel--list').hidden = view !== 'list';
    this.$('.bf-panel--map').hidden = view !== 'map';
    if (!this.map) return;
    this.map.resize();
    // A map that loaded while hidden had no size, so frame the results now.
    if (view === 'map' && this.needsFit) {
      this.needsFit = false;
      this.fitToResults();
    }
  };

  Finder.prototype.isNarrow = function () { return window.matchMedia('(max-width: 899px)').matches; };

  // ---------- Search ----------
  Finder.prototype.search = function (q) {
    var self = this;
    var msg = this.$('.bf-search-msg');
    if (!q) return;
    msg.textContent = 'Searching…';
    // OpenStreetMap's free geocoder. Fine for a prototype; revisit before heavy traffic.
    fetch('https://nominatim.openstreetmap.org/search?format=json&countrycodes=us&limit=1&q=' + encodeURIComponent(q))
      .then(function (r) { return r.json(); })
      .then(function (res) {
        if (!res.length) { msg.textContent = 'We couldn\'t find "' + q + '". Try a city or ZIP code.'; return; }
        msg.textContent = '';
        self.setOrigin(+res[0].lat, +res[0].lon, q);
      })
      .catch(function () { msg.textContent = 'Search is unavailable right now. Please try again.'; });
  };

  Finder.prototype.locate = function () {
    var self = this;
    var msg = this.$('.bf-search-msg');
    if (!navigator.geolocation) { msg.textContent = 'Your browser can\'t share your location.'; return; }
    msg.textContent = 'Finding you…';
    navigator.geolocation.getCurrentPosition(function (pos) {
      msg.textContent = '';
      self.setOrigin(pos.coords.latitude, pos.coords.longitude, 'you');
    }, function () {
      msg.textContent = 'Location is off. Type a city or ZIP instead.';
    });
  };

  Finder.prototype.setOrigin = function (lat, lng, label) {
    this.origin = { lat: lat, lng: lng, label: label };
    this.update();
    if (!this.map) return;
    if (this.originMarker) this.originMarker.remove();
    var dot = document.createElement('div');
    dot.style.cssText = 'width:14px;height:14px;border-radius:50%;background:#fff;border:3px solid #000;';
    this.originMarker = new maplibregl.Marker({ element: dot }).setLngLat([lng, lat]).addTo(this.map);
    // Show the search point and the nearest few saunas.
    var bounds = new maplibregl.LngLatBounds([lng, lat], [lng, lat]);
    this.current.slice(0, 5).forEach(function (v) { bounds.extend([v.lng, v.lat]); });
    this.map.fitBounds(bounds, { padding: 60, maxZoom: 13 });
  };

  // ---------- Map ----------
  Finder.prototype.initMap = function () {
    var self = this;
    var map = this.map = new maplibregl.Map({
      container: this.$('.bf-map'),
      style: CONFIG.mapStyle,
      center: [-98.5, 39.8],
      zoom: 3,
      attributionControl: { compact: true }
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');

    map.on('load', function () {
      var img = new Image(80, 96);
      img.onload = function () {
        map.addImage('bf-pin', img, { pixelRatio: 2 });
        map.addSource('bf-venues', {
          type: 'geojson', data: self.geojson(), cluster: true, clusterRadius: 40, clusterMaxZoom: 11
        });
        map.addLayer({
          id: 'bf-clusters', type: 'circle', source: 'bf-venues', filter: ['has', 'point_count'],
          paint: { 'circle-color': '#000', 'circle-radius': ['step', ['get', 'point_count'], 16, 10, 20, 50, 26],
            'circle-stroke-color': '#EBCEAD', 'circle-stroke-width': 2 }
        });
        map.addLayer({
          id: 'bf-cluster-count', type: 'symbol', source: 'bf-venues', filter: ['has', 'point_count'],
          layout: { 'text-field': ['get', 'point_count_abbreviated'], 'text-font': ['Noto Sans Bold'], 'text-size': 13 },
          paint: { 'text-color': '#EBCEAD' }
        });
        map.addLayer({
          id: 'bf-pins', type: 'symbol', source: 'bf-venues', filter: ['!', ['has', 'point_count']],
          layout: { 'icon-image': 'bf-pin', 'icon-anchor': 'bottom', 'icon-allow-overlap': true,
            'icon-size': ['case', ['==', ['get', 'id'], ''], 1.3, 1] }
        });

        map.on('click', 'bf-clusters', function (e) {
          var f = e.features[0];
          map.getSource('bf-venues').getClusterExpansionZoom(f.properties.cluster_id).then(function (zoom) {
            map.easeTo({ center: f.geometry.coordinates, zoom: zoom });
          });
        });
        map.on('click', 'bf-pins', function (e) { self.select(e.features[0].properties.id, 'map'); });
        ['bf-clusters', 'bf-pins'].forEach(function (layer) {
          map.on('mouseenter', layer, function () { map.getCanvas().style.cursor = 'pointer'; });
          map.on('mouseleave', layer, function () { map.getCanvas().style.cursor = ''; });
        });
        if (self.selectedId) self.select(self.selectedId, 'list');
        else if (self.$('.bf-map').offsetWidth) self.fitToResults();
        else self.needsFit = true;
      };
      img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(PIN_SVG);
    });
  };

  Finder.prototype.geojson = function () {
    return {
      type: 'FeatureCollection',
      features: (this.current || []).map(function (v) {
        return { type: 'Feature', geometry: { type: 'Point', coordinates: [v.lng, v.lat] }, properties: { id: v.id } };
      })
    };
  };

  Finder.prototype.updateMap = function () {
    if (!this.map || !this.map.getSource('bf-venues')) return;
    this.map.getSource('bf-venues').setData(this.geojson());
  };

  Finder.prototype.fitToResults = function () {
    var list = this.current || [];
    if (!list.length) return;
    var bounds = new maplibregl.LngLatBounds([list[0].lng, list[0].lat], [list[0].lng, list[0].lat]);
    list.forEach(function (v) { bounds.extend([v.lng, v.lat]); });
    this.map.fitBounds(bounds, { padding: 60, maxZoom: 13, duration: 0 });
  };

  Finder.prototype.markSelected = function (id) {
    this.root.querySelectorAll('.bf-card').forEach(function (c) {
      c.classList.toggle('is-selected', c.getAttribute('data-id') === id);
    });
    if (this.map && this.map.getLayer('bf-pins')) {
      this.map.setLayoutProperty('bf-pins', 'icon-size', ['case', ['==', ['get', 'id'], id], 1.3, 1]);
    }
  };

  Finder.prototype.select = function (id, from) {
    var v = this.venues.filter(function (x) { return x.id === id; })[0];
    if (!v) return;
    this.selectedId = id;
    this.markSelected(id);
    if (from === 'map') {
      var card = this.$('.bf-card[data-id="' + id + '"]');
      if (card && !this.isNarrow()) card.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    } else if (this.isNarrow()) {
      this.needsFit = false;
      this.setView('map');
    }
    if (!this.map) return;
    if (from !== 'map') this.map.jumpTo({ center: [v.lng, v.lat], zoom: Math.max(this.map.getZoom(), 13) });
    if (this.popup) this.popup.remove();
    this.popup = new maplibregl.Popup({ offset: [0, -44], closeButton: true, maxWidth: '260px' })
      .setLngLat([v.lng, v.lat])
      .setHTML('<div class="bf-pop"><h4>' + esc(v.name) + '</h4>' +
        '<p>' + esc(LABELS.venue_type[v.venue_type]) + (v._miles != null ? ' · ' + v._miles.toFixed(1) + ' mi' : '') + '</p>' +
        '<p>' + esc(v.address) + ', ' + esc(v.city) + '</p>' +
        (v.website ? '<p><a class="bf-accent" href="' + esc(v.website) + '" target="_blank" rel="noopener">Visit website →</a></p>' : '') +
        '</div>')
      .addTo(this.map);
  };

  // ---------- Start ----------
  function boot() {
    var root = document.querySelector(CONFIG.mount);
    if (!root) return;
    loadCss(FONT_CSS);
    loadCss(MAPLIBRE_CSS);
    if (SCRIPT_URL) loadCss(SCRIPT_URL.replace(/finder\.js(\?.*)?$/, 'finder.css'));
    new Finder(root).start();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
