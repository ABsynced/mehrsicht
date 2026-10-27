/* Mehrsicht — small interactive pieces. Plain JavaScript, no libraries.
   Every feature checks first whether its element exists on the page. */
(function () {
  "use strict";
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  /* ---------- Side menu (drawer) ---------- */
  const drawer = $("[data-drawer]");
  if (drawer) {
    let lastFocus = null;
    const open = () => {
      lastFocus = document.activeElement;
      drawer.classList.add("open");
      drawer.setAttribute("aria-hidden", "false");
      const btn = $(".panel [data-close-drawer]", drawer);
      if (btn) btn.focus();
    };
    const close = () => {
      drawer.classList.remove("open");
      drawer.setAttribute("aria-hidden", "true");
      if (lastFocus) lastFocus.focus();
    };
    $$("[data-open-drawer]").forEach((b) => b.addEventListener("click", open));
    $$("[data-close-drawer]").forEach((b) => b.addEventListener("click", close));
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && drawer.classList.contains("open")) close(); });
  }

  /* Close the edition dropdown when clicking elsewhere. */
  document.addEventListener("click", (e) => {
    $$("details.edition[open]").forEach((d) => { if (!d.contains(e.target)) d.removeAttribute("open"); });
  });

  /* ---------- Hero carousel ---------- */
  const carousel = $("[data-carousel]");
  if (carousel) {
    const slides = $$(".slide", carousel);
    const segs = $$(".segments button", carousel);
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const ms = 5000;
    carousel.style.setProperty("--slide-ms", ms + "ms");
    let index = 0, timer = null, paused = false;

    const show = (i) => {
      index = (i + slides.length) % slides.length;
      slides.forEach((s, k) => s.classList.toggle("active", k === index));
      segs.forEach((b, k) => {
        b.classList.toggle("done", k < index);
        b.classList.remove("current");
        if (k === index) { void b.offsetWidth; b.classList.add("current"); } // restart the fill animation
      });
    };
    const start = () => {
      clearInterval(timer);
      if (!reduce) timer = setInterval(() => { if (!paused) show(index + 1); }, ms);
    };
    $("[data-next]", carousel).addEventListener("click", () => { show(index + 1); start(); });
    $("[data-prev]", carousel).addEventListener("click", () => { show(index - 1); start(); });
    segs.forEach((b) => b.addEventListener("click", () => { show(Number(b.dataset.go)); start(); }));
    const pause = (v) => { paused = v; carousel.classList.toggle("paused", v); };
    carousel.addEventListener("mouseenter", () => pause(true));
    carousel.addEventListener("mouseleave", () => pause(false));
    carousel.addEventListener("focusin", () => pause(true));
    carousel.addEventListener("focusout", () => pause(false));
    show(0);
    start();
  }

  /* ---------- Small helpers: browser storage, toast, copy ---------- */
  const store = {
    get(key, fallback) { try { return JSON.parse(localStorage.getItem("ms-" + key)) || fallback; } catch (e) { return fallback; } },
    set(key, value) { try { localStorage.setItem("ms-" + key, JSON.stringify(value)); } catch (e) { /* private mode */ } },
  };
  const ROOT = document.body.dataset.root || "";
  const toastEl = $("[data-toast]");
  let toastTimer = null;
  const toast = (msg) => {
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toastEl.hidden = true; }, 2600);
  };
  const copy = (text) => {
    const done = () => toast("Link kopiert");
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done, () => fallbackCopy(text));
    else fallbackCopy(text);
    function fallbackCopy(t) {
      const ta = document.createElement("textarea");
      ta.value = t; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); done(); } catch (e) { toast("Kopieren nicht möglich"); }
      ta.remove();
    }
  };
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  /* ---------- Sticky header: shadow once the page scrolls ---------- */
  const header = $("[data-sticky]");
  if (header) {
    const onScroll = () => header.classList.toggle("is-stuck", window.scrollY > 40);
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  /* ---------- Load more: show N items, then a button for the next N ---------- */
  const loaders = $$("[data-loadmore]").map((box) => {
    const size = Number(box.dataset.pageSize) || 12;
    const btn = $("[data-loadmore-btn]", box);
    const count = $("[data-loadmore-count]", box);
    let shown = size;
    const refresh = () => {
      let n = 0;
      $$("[data-lm-item]", box).forEach((el) => {
        if (el.dataset.out === "1") { el.hidden = true; return; }
        n++;
        el.hidden = n > shown;
      });
      if (btn) btn.hidden = n <= shown;
      if (count) count.textContent = "(" + (n - shown) + " weitere)";
    };
    if (btn) btn.addEventListener("click", () => { shown += size; refresh(); });
    box._lmReset = () => { shown = size; refresh(); };
    box._lmRefresh = refresh;
    refresh();
    return box;
  });

  /* ---------- Hidden stories (button "Ausblenden" on a story page) ---------- */
  const hiddenIds = new Set(store.get("hidden", []));
  const markHidden = () => {
    $$("[data-id]").forEach((el) => {
      if (!hiddenIds.has(el.dataset.id)) return;
      if (el.hasAttribute("data-lm-item")) el.dataset.out = "1";
      else el.hidden = true;
    });
    loaders.forEach((b) => b._lmRefresh());
  };

  /* ---------- Follow topics ---------- */
  const followed = () => store.get("follow", []);
  const syncFollow = () => {
    const slugs = new Set(followed().map((f) => f.slug));
    $$("[data-follow]").forEach((b) => {
      const on = slugs.has(b.dataset.follow);
      b.setAttribute("aria-pressed", String(on));
      b.setAttribute("aria-label", (on ? "Nicht mehr folgen: " : "Folgen: ") + b.dataset.name);
    });
    $$("[data-follow-dot]").forEach((d) => { d.hidden = slugs.size === 0; });
  };
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-follow]");
    if (!b) return;
    e.preventDefault();
    let list = followed();
    const slug = b.dataset.follow;
    if (list.some((f) => f.slug === slug)) {
      list = list.filter((f) => f.slug !== slug);
      toast("Du folgst " + b.dataset.name + " nicht mehr");
    } else {
      list.push({ slug, name: b.dataset.name, path: b.dataset.path });
      toast("Du folgst jetzt " + b.dataset.name);
    }
    store.set("follow", list);
    syncFollow();
    renderForYou();
  });

  /* ---------- Copy buttons ---------- */
  document.addEventListener("click", (e) => {
    const c = e.target.closest("[data-copy]");
    if (c) { copy(c.dataset.copy); const d = c.closest("details"); if (d) d.removeAttribute("open"); }
    const l = e.target.closest("[data-copy-link]");
    if (l) copy(location.href);
  });
  document.addEventListener("click", (e) => {
    $$("details.kebab[open]").forEach((d) => { if (!d.contains(e.target)) d.removeAttribute("open"); });
  });

  /* ---------- Story page: share, save, hide, compare, article tabs ---------- */
  const storyEl = $("[data-story]");
  if (storyEl) {
    const id = storyEl.dataset.story;
    const url = encodeURIComponent(location.href);
    const title = encodeURIComponent(storyEl.dataset.storyTitle + " – Mehrsicht");
    const links = {
      x: "https://twitter.com/intent/tweet?url=" + url + "&text=" + title,
      linkedin: "https://www.linkedin.com/sharing/share-offsite/?url=" + url,
      facebook: "https://www.facebook.com/sharer/sharer.php?u=" + url,
      whatsapp: "https://wa.me/?text=" + title + "%20" + url,
      mail: "mailto:?subject=" + title + "&body=" + url,
    };
    $$("[data-share]").forEach((a) => { a.href = links[a.dataset.share] || "#"; });

    const saveBtn = $("[data-save]");
    const saveLabel = $("[data-save-label]");
    const isSaved = () => store.get("saved", []).some((x) => x.id === id);
    const syncSave = () => {
      const on = isSaved();
      saveBtn.setAttribute("aria-pressed", String(on));
      saveLabel.textContent = on ? "Gemerkt" : "Merken";
    };
    saveBtn.addEventListener("click", () => {
      let list = store.get("saved", []);
      if (isSaved()) { list = list.filter((x) => x.id !== id); toast("Nicht mehr gemerkt"); }
      else {
        list.unshift({ id, title: storyEl.dataset.storyTitle, path: storyEl.dataset.storyPath, image: storyEl.dataset.storyImage, topic: storyEl.dataset.storyTopic });
        toast("Gemerkt – zu finden unter „Für dich“");
      }
      store.set("saved", list);
      syncSave();
    });
    syncSave();

    const hideBtn = $("[data-hide-story]");
    hideBtn.addEventListener("click", () => {
      if (hiddenIds.has(id)) { hiddenIds.delete(id); toast("Wieder eingeblendet"); hideBtn.lastElementChild.textContent = "Ausblenden"; }
      else { hiddenIds.add(id); toast("Ausgeblendet: erscheint nicht mehr auf der Startseite"); hideBtn.lastElementChild.textContent = "Einblenden"; }
      store.set("hidden", Array.from(hiddenIds));
    });
    if (hiddenIds.has(id)) hideBtn.lastElementChild.textContent = "Einblenden";

    const cmpBtn = $("[data-compare-open]");
    const cmp = $("[data-compare]");
    if (cmpBtn && cmp) cmpBtn.addEventListener("click", () => {
      cmp.hidden = !cmp.hidden;
      cmpBtn.setAttribute("aria-expanded", String(!cmp.hidden));
      $$("[data-side-text]").forEach((p) => { if (!cmp.hidden) p.hidden = true; });
      if (cmp.hidden) { const sel = $("[data-side][aria-selected=true]"); if (sel) sel.click(); }
    });

    // Article list: Alle / Links / Mitte / Rechts, search, sort
    const list = $("[data-art-list]");
    if (list) {
      const cards = $$(".art-card", list);
      const empty = $("[data-art-empty]", list);
      const q = $("[data-art-search]");
      const sort = $("[data-art-sort]");
      let bucket = "";
      const apply = () => {
        const term = q ? q.value.trim().toLowerCase() : "";
        let n = 0;
        cards.forEach((c) => {
          const ok = (!bucket || c.dataset.bucket === bucket) && (!term || c.dataset.text.includes(term));
          c.dataset.out = ok ? "0" : "1";
          if (ok) n++;
        });
        if (empty) empty.hidden = n > 0;
        list._lmReset();
      };
      $$("[data-art-tab]").forEach((tb) => tb.addEventListener("click", () => {
        bucket = tb.dataset.artTab;
        $$("[data-art-tab]").forEach((x) => x.setAttribute("aria-selected", String(x === tb)));
        apply();
      }));
      if (q) q.addEventListener("input", apply);
      // Distribution panel: click an outlet logo -> jump to its article in the list
      const allTab = $("[data-art-tab='']");
      $$("[data-jump]").forEach((b) => b.addEventListener("click", (e) => {
        const card = document.getElementById("art-" + b.dataset.jump);
        if (!card) return;
        e.preventDefault();
        if (card.dataset.out === "1") { if (q) q.value = ""; if (allTab) allTab.click(); }
        const more = $("[data-loadmore-btn]", list);
        let guard = 50;
        while (card.hidden && more && !more.hidden && guard--) more.click();
        card.scrollIntoView({ behavior: "smooth", block: "start" });
        card.classList.remove("flash"); void card.offsetWidth; card.classList.add("flash");
      }));
      if (sort) sort.addEventListener("change", () => {
        const k = sort.value;
        cards.slice().sort((a, b) => {
          if (k === "old") return (a.dataset.time || "").localeCompare(b.dataset.time || "");
          if (k === "lean") return Number(a.dataset.lean) - Number(b.dataset.lean);
          return (b.dataset.time || "").localeCompare(a.dataset.time || "");
        }).forEach((c) => list.insertBefore(c, empty));
        apply();
      });
    }
  }

  /* ---------- Homepage news list: search, sorting, fact-check filter ---------- */
  const news = $("[data-news]");
  if (news && news.hasAttribute("data-filterable") === false && $("[data-sort]")) {
    const items = $$(".news-item", news);
    const features = $$(".feature[data-filterable]");
    const empty = $("[data-empty]", news);
    const search = $("[data-search]");
    const form = $("[data-search-form]");
    let onlyChecks = false;
    const params = new URLSearchParams(location.search);
    if (search && params.get("q")) search.value = params.get("q");

    const apply = () => {
      const q = search ? search.value.trim().toLowerCase() : "";
      let visible = 0;
      const test = (el) => (!q || el.dataset.text.includes(q)) && (!onlyChecks || Number(el.dataset.checks) > 0) && !hiddenIds.has(el.dataset.id);
      items.forEach((el) => { const ok = test(el); el.dataset.out = ok ? "0" : "1"; if (ok) visible++; });
      features.forEach((el) => { const ok = test(el); el.hidden = !ok; if (ok) visible++; });
      if (empty) empty.hidden = visible > 0;
      news._lmReset();
    };
    if (search) search.addEventListener("input", () => {
      apply();
      if (search.value.trim().length > 1) { const sec = $("#nachrichten"); if (sec && sec.getBoundingClientRect().top > window.innerHeight) sec.scrollIntoView({ behavior: "smooth" }); }
    });
    if (form) form.addEventListener("submit", (e) => { e.preventDefault(); apply(); const sec = $("#nachrichten"); if (sec) sec.scrollIntoView({ behavior: "smooth" }); });

    $$("[data-sort]").forEach((btn) => btn.addEventListener("click", () => {
      const key = btn.dataset.sort;
      $$("[data-sort]").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
      items.slice().sort((a, b) => {
        if (key === "recent") return (b.dataset.recent || "").localeCompare(a.dataset.recent || "");
        return Number(b.dataset[key]) - Number(a.dataset[key]);
      }).forEach((el) => news.insertBefore(el, empty));
      news._lmReset();
    }));
    const checksBtn = $("[data-filter-checks]");
    if (checksBtn) checksBtn.addEventListener("click", () => {
      onlyChecks = !onlyChecks;
      checksBtn.setAttribute("aria-pressed", String(onlyChecks));
      apply();
    });
    apply();
  }

  /* ---------- "Für dich" page ---------- */
  function card(s) {
    const img = s.image ? '<div class="media"><img src="' + ROOT + esc(s.image) + '" alt="" loading="lazy"></div>' : '<div class="media" style="--tint:#5B6270"></div>';
    const p = s.p || { l: 0, m: 100, r: 0 };
    const line = s.n ? '<span class="cov-line"><span class="cov-mini"><i class="l" style="flex:' + p.l + '"></i><i class="m" style="flex:' + p.m + '"></i><i class="r" style="flex:' + p.r + '"></i></span>' + s.n + " Quellen</span>" : "";
    return '<a class="gcard" data-lm-item href="' + ROOT + esc(s.path) + '">' + img + '<span class="gcard-body"><span class="kick">' + esc(s.topic || "") + (s.ago ? " · " + esc(s.ago) : "") + "</span><strong>" + esc(s.title) + "</strong>" + line + "</span></a>";
  }
  function renderForYou() {
    const page = $("[data-for-you]");
    if (!page) return;
    const index = JSON.parse($("[data-story-index]").textContent);
    const follows = followed();
    const slugs = new Set(follows.map((f) => f.slug));
    $("[data-followed]").innerHTML = follows.map((f) =>
      '<span class="tchip tchip--light"><a href="' + ROOT + esc(f.path) + '"><span>' + esc(f.name) + '</span></a><button type="button" class="follow follow--chip" data-follow="' + esc(f.slug) + '" data-name="' + esc(f.name) + '" data-path="' + esc(f.path) + '" aria-pressed="true"><svg class="i-plus" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M12 5v14M5 12h14"/></svg><svg class="i-check" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6"><path d="M5 12l5 5 9-10"/></svg></button></span>').join("");
    $("[data-followed-empty]").hidden = follows.length > 0;
    const box = $("[data-for-you-stories]");
    const btn = $("[data-loadmore-btn]", box);
    $$("[data-lm-item]", box).forEach((el) => el.remove());
    const mine = index.filter((s) => s.topics.some((t) => slugs.has(t)) && !hiddenIds.has(s.id));
    btn.insertAdjacentHTML("beforebegin", mine.map(card).join(""));
    $("[data-for-you-empty]").hidden = !follows.length || mine.length > 0;
    box._lmReset();
    const saved = store.get("saved", []);
    $("[data-saved]").innerHTML = saved.map(card).join("");
    $("[data-saved-empty]").hidden = saved.length > 0;
    $("[data-hidden-count]").textContent = hiddenIds.size ? hiddenIds.size + " Geschichte(n) ausgeblendet." : "Keine Geschichten ausgeblendet.";
  }
  const unhide = $("[data-unhide-all]");
  if (unhide) unhide.addEventListener("click", () => { hiddenIds.clear(); store.set("hidden", []); renderForYou(); toast("Alle Geschichten wieder eingeblendet"); });

  /* ---------- Fact-check page: filter by verdict ---------- */
  const fcTabs = $$("[data-verdict-tab]");
  if (fcTabs.length) fcTabs.forEach((tb) => tb.addEventListener("click", () => {
    fcTabs.forEach((x) => x.setAttribute("aria-selected", String(x === tb)));
    const v = tb.dataset.verdictTab;
    const grid = $(".fc-grid");
    $$("[data-verdict]", grid).forEach((c) => { c.dataset.out = !v || c.dataset.verdict === v ? "0" : "1"; });
    grid._lmReset();
  }));

  syncFollow();
  markHidden();
  renderForYou();

  /* ---------- Parliament: seat plan + coalition calculator ---------- */
  const parlJson = $("[data-parliament-json]");
  const hemi = $("[data-hemicycle]");
  if (parlJson && hemi) {
    const P = JSON.parse(parlJson.textContent);
    const svg = $("svg", hemi);
    const ns = "http://www.w3.org/2000/svg";
    const selected = new Set(P.default_coalition || []);

    // Seat positions: rows of a half circle, seats ordered left to right.
    const rows = P.total > 650 ? 13 : 12, r0 = 0.36, seats = [];
    const radii = Array.from({ length: rows }, (_, i) => r0 + i * (1 - r0) / (rows - 1));
    const sum = radii.reduce((a, b) => a + b, 0);
    const counts = radii.map((r) => Math.round(P.total * r / sum));
    counts[rows - 1] += P.total - counts.reduce((a, b) => a + b, 0);
    radii.forEach((r, i) => {
      for (let j = 0; j < counts[i]; j++) {
        const th = Math.PI - j * Math.PI / (counts[i] - 1);
        seats.push({ th, x: 500 + 480 * r * Math.cos(th), y: 505 - 480 * r * Math.sin(th) });
      }
    });
    seats.sort((a, b) => b.th - a.th);
    const owner = [];
    P.groups.forEach((g) => { for (let k = 0; k < g.seats; k++) owner.push(g); });
    const radius = P.total > 650 ? 7.6 : 8.2;
    const circles = seats.map((s, i) => {
      const c = document.createElementNS(ns, "circle");
      c.setAttribute("cx", s.x.toFixed(1));
      c.setAttribute("cy", s.y.toFixed(1));
      c.setAttribute("r", radius);
      c.setAttribute("fill", owner[i].color);
      c.dataset.group = owner[i].id;
      svg.appendChild(c);
      return c;
    });

    const chipsBox = $("[data-party-chips]");
    const bar = $("[data-coal-bar]");
    const verdict = $("[data-coal-verdict]");
    const total = $("[data-coal-seats]");
    P.groups.forEach((g) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "party-chip";
      b.style.setProperty("--party", g.color);
      b.innerHTML = '<i class="dot"></i>' + g.name + ' <span class="mono">' + g.seats + "</span>";
      b.addEventListener("click", () => { selected.has(g.id) ? selected.delete(g.id) : selected.add(g.id); update(); });
      b.dataset.group = g.id;
      chipsBox.appendChild(b);
    });

    function update() {
      const any = selected.size > 0;
      circles.forEach((c) => { c.style.opacity = !any || selected.has(c.dataset.group) ? 1 : 0.15; });
      $$(".party-chip", chipsBox).forEach((b) => b.setAttribute("aria-pressed", String(selected.has(b.dataset.group))));
      $$(".seg-fill", bar).forEach((n) => n.remove());
      let seatsSum = 0;
      P.groups.filter((g) => selected.has(g.id)).forEach((g) => {
        seatsSum += g.seats;
        const s = document.createElement("span");
        s.className = "seg-fill";
        s.style.cssText = "display:block;height:100%;width:" + (g.seats / P.total * 100) + "%;background:" + g.color;
        bar.appendChild(s);
      });
      total.textContent = seatsSum;
      const ok = seatsSum >= P.majority;
      verdict.className = "verdict-line " + (!any ? "" : ok ? "ok" : "no");
      verdict.textContent = !any ? "Keine Fraktion gewählt"
        : ok ? "Mehrheit: " + seatsSum + " Sitze (+" + (seatsSum - P.majority) + ")"
        : "Keine Mehrheit: es fehlen " + (P.majority - seatsSum) + " Sitze";
    }
    update();
  }

  /* ---------- Newsletter form ---------- */
  $$("[data-newsletter]").forEach((form) => {
    const email = $("input[type=email]", form);
    const error = $("[data-nl-error]", form);
    email.addEventListener("input", () => { error.hidden = true; });
    form.addEventListener("submit", (e) => {
      const valid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.value.trim());
      if (!valid) { e.preventDefault(); error.hidden = false; email.focus(); return; }
      const action = form.getAttribute("action");
      if (!action || action === "#") {
        // No newsletter service connected yet: just show the thank-you note.
        e.preventDefault();
        $("[data-nl-fields]", form).hidden = true;
        $("[data-nl-ok]", form).hidden = false;
      }
    });
  });

  /* ---------- Story page: perspective tabs ---------- */
  const tabs = $$("[data-side]");
  if (tabs.length) {
    tabs.forEach((t) => t.addEventListener("click", () => {
      tabs.forEach((x) => x.setAttribute("aria-selected", String(x === t)));
      $$("[data-side-text]").forEach((p) => { p.hidden = p.dataset.sideText !== t.dataset.side; });
    }));
  }

  /* ---------- Story page: fact-check highlights ---------- */
  const marks = $$(".fc-mark");
  const boxes = $$("[data-fc-box]");
  let marksOn = true;
  const openBox = (id) => {
    if (!marksOn) return;
    boxes.forEach((b) => { b.hidden = b.dataset.fcBox !== id; });
    marks.forEach((m) => m.setAttribute("aria-expanded", String(m.dataset.fcTarget === id)));
  };
  marks.forEach((m) => {
    m.addEventListener("click", () => openBox(m.dataset.fcTarget));
    m.addEventListener("mouseenter", () => openBox(m.dataset.fcTarget));
  });
  if (marks.length) openBox(marks[0].dataset.fcTarget);
  const sw = $("[data-marks-switch]");
  if (sw) sw.addEventListener("click", () => {
    marksOn = !marksOn;
    sw.setAttribute("aria-checked", String(marksOn));
    document.body.classList.toggle("marks-off", !marksOn);
    if (!marksOn) boxes.forEach((b) => { b.hidden = true; });
    else if (marks.length) openBox(marks[0].dataset.fcTarget);
  });
})();
