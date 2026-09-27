gsap.registerPlugin(InertiaPlugin);
gsap.registerPlugin(SplitText);
gsap.registerPlugin(ScrollTrigger);
gsap.registerPlugin(Flip);

let lenis;

function initLenis() {
  lenis = new Lenis({
    duration: 1.25,
    wheelMultiplier: 0.75,
    easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
  });
  lenis.on("scroll", ScrollTrigger.update);
  gsap.ticker.add((time) => {
    lenis.raf(time * 1000);
  });
  gsap.ticker.lagSmoothing(0);

  lenis.scrollTo(0, {
    immediate: true,
    lock: true,
    force: true,
  });
}

function initFOUC() {
  const loadEls = document.querySelectorAll("[data-anim-load]");
  loadEls.forEach((el) => {
    if (el.hasAttribute("data-fouc-prevent")) {
      return;
    } else {
      gsap.set(el, {
        visibility: "visible",
      });
    }
  });
  $("body").addClass("is-loaded");
  ScrollTrigger.refresh();
}

function initTextSplit() {
  $("[data-split=chars]").each(function () {
    const toSplit = $(this);
    SplitText.create(toSplit, {
      type: "chars, lines",
      mask: "chars",
      charsClass: "char",
      linesClass: "line",
    });
  });
  $("[data-split=words]").each(function () {
    const toSplit = $(this);
    SplitText.create(toSplit, {
      type: "words, lines",
      mask: "lines",
      wordsClass: "word",
      linesClass: "line",
    });
  });
  $("[data-split=lines]").each(function () {
    const toSplit = $(this);
    SplitText.create(toSplit, {
      type: "lines",
      mask: "lines",
      linesClass: "line",
    });
  });
  $("[data-split=rich-lines]").each(function () {
    const toSplit = $(this).children();
    SplitText.create(toSplit, {
      type: "lines",
      mask: "lines",
      linesClass: "line",
    });
  });
  $("[data-split=ul-lines]").each(function () {
    const toSplit = $(this).children();
    SplitText.create(toSplit, {
      type: "lines",
      linesClass: "line",
    });
  });
}

function initGlobalParallax() {
  const mm = gsap.matchMedia();

  mm.add(
    {
      isMobile: "(max-width:479px)",
      isMobileLandscape: "(max-width:767px)",
      isTablet: "(max-width:991px)",
      isDesktop: "(min-width:992px)",
    },
    (context) => {
      const { isMobile, isMobileLandscape, isTablet } = context.conditions;

      const ctx = gsap.context(() => {
        document
          .querySelectorAll('[data-parallax="trigger"]')
          .forEach((trigger) => {
            // Check if this trigger has to be disabled on smaller breakpoints
            const disable = trigger.getAttribute("data-parallax-disable");
            if (
              (disable === "mobile" && isMobile) ||
              (disable === "mobileLandscape" && isMobileLandscape) ||
              (disable === "tablet" && isTablet)
            ) {
              return;
            }

            // Optional: you can target an element inside a trigger if necessary
            const target =
              trigger.querySelector('[data-parallax="target"]') || trigger;

            // Get the direction value to decide between xPercent or yPercent tween
            const direction =
              trigger.getAttribute("data-parallax-direction") || "vertical";
            const prop = direction === "horizontal" ? "xPercent" : "yPercent";

            // Get the scrub value, our default is 'true' because that feels nice with Lenis
            const scrubAttr = trigger.getAttribute("data-parallax-scrub");
            const scrub = scrubAttr ? parseFloat(scrubAttr) : true;

            // Get the start position in %
            const startAttr = trigger.getAttribute("data-parallax-start");
            const startVal = startAttr !== null ? parseFloat(startAttr) : 20;

            // Get the end position in %
            const endAttr = trigger.getAttribute("data-parallax-end");
            const endVal = endAttr !== null ? parseFloat(endAttr) : -20;

            // Get the start value of the ScrollTrigger
            const scrollStartRaw =
              trigger.getAttribute("data-parallax-scroll-start") ||
              "top bottom";
            const scrollStart = `clamp(${scrollStartRaw})`;

            // Get the end value of the ScrollTrigger
            const scrollEndRaw =
              trigger.getAttribute("data-parallax-scroll-end") || "bottom top";
            const scrollEnd = `clamp(${scrollEndRaw})`;

            gsap.fromTo(
              target,
              { [prop]: startVal },
              {
                [prop]: endVal,
                ease: "none",
                scrollTrigger: {
                  trigger,
                  start: scrollStart,
                  end: scrollEnd,
                  scrub,
                },
              }
            );
          });
      });

      return () => ctx.revert();
    }
  );
}

function initLoadAnimations() {
  const isMobile = window.innerWidth <= 768;
  if (isMobile) return;
  const globalIntroDelay = 0.5;

  $("[data-anim-load=chars]").each(function () {
    const elDelay = parseFloat($(this).attr("data-anim-load-delay")) || 0;

    gsap.from($(this).find(".char"), {
      delay: globalIntroDelay + elDelay,
      xPercent: 100,
      duration: 1.5,
      ease: "expo.out",
      stagger: {
        each: 0.125,
      },
    });
  });

  $("[data-anim-load=words]").each(function () {
    const elDelay = parseFloat($(this).attr("data-anim-load-delay")) || 0;

    gsap.from($(this).find(".word"), {
      delay: globalIntroDelay + elDelay,
      yPercent: 125,
      duration: 1.5,
      ease: "expo.out",
      stagger: {
        each: 0.05,
      },
    });
  });

  $("[data-anim-load=lines]").each(function () {
    const elDelay = parseFloat($(this).attr("data-anim-load-delay")) || 0;

    gsap.from($(this).find(".line"), {
      xPercent: 100,
      scale: 0.5,
      delay: globalIntroDelay + elDelay,
      duration: 1.75,
      ease: "expo.out",
      stagger: {
        each: 0.125,
      },
    });
  });

  $("[data-anim-load=scale]").each(function () {
    const elDelay = $(this).attr("data-anim-load-delay") || 0;

    gsap.from($(this), {
      scale: 1.25,
      delay: elDelay,
      duration: 3,
      ease: "power3.out",
    });
  });

  $("[data-anim-load=slide-up-fade]").each(function () {
    const elDelay = $(this).attr("data-anim-load-delay") || 0;

    gsap.from($(this), {
      yPercent: 50,
      opacity: 0,
      delay: globalIntroDelay + elDelay,
      duration: 2,
      ease: "expo.out",
    });
  });

  $("[data-anim-load=children-slide-up-fade]").each(function () {
    const elDelay = $(this).attr("data-anim-load-delay") || 0;

    gsap.from($(this).children(), {
      yPercent: 50,
      opacity: 0,
      delay: globalIntroDelay + elDelay,
      duration: 2,
      ease: "expo.out",
      stagger: {
        each: 0.125,
      },
    });
  });

  $("[data-anim-load=mask]").each(function () {
    const elDelay = parseFloat($(this).attr("data-anim-load-delay")) || 6;

    gsap.fromTo(
      $(this),
      {
        clipPath: "polygon(0% 0%, 100% 0%, 100% 100%, 0% 100%)",
      },
      {
        delay: globalIntroDelay + elDelay,
        clipPath: "polygon(0% 0%, 0% 0%, 0% 100%, 0% 100%)",
        duration: 1.75,
        ease: "expo.inOut",
      }
    );
  });

  $("[data-anim-load=nav-logo]").each(function () {
    const elDelay = parseFloat($(this).attr("data-anim-load-delay")) || 0;

    gsap.from($(this).find(".g_logo_split_svg"), {
      xPercent: 125,
      delay: globalIntroDelay + elDelay,
      ease: "expo.out",
      duration: 1.5,
      stagger: {
        each: 0.05,
      },
    });
  });

  $("[data-anim-load=nav-button]").each(function () {
    const elDelay = parseFloat($(this).attr("data-anim-load-delay")) || 0;

    gsap.fromTo(
      $(this),
      {
        clipPath: "polygon(0% 0%, 100% 0%, 100% 0%, 0% 0%)",
      },
      {
        clipPath: "polygon(0% 0%, 100% 0%, 100% 100%, 0% 100%)",
        delay: globalIntroDelay + elDelay,
        ease: "expo.out",
        duration: 1.5,
      }
    );
  });
}

function initScrollAnimations() {
  $("[data-anim-scroll=chars]").each(function () {
    gsap.from($(this).find(".char"), {
      xPercent: 100,
      duration: 1.5,
      ease: "expo.out",
      stagger: {
        each: 0.125,
      },
      scrollTrigger: {
        trigger: $(this),
        start: "top bottom",
        end: "top 90%",
        toggleActions: "none play none reset",
      },
    });
  });

  $("[data-anim-scroll=words]").each(function () {
    gsap.from($(this).find(".word"), {
      yPercent: 115,
      // xPercent: 25,
      duration: 2,
      ease: "expo.out",
      stagger: {
        each: 0.05,
      },
      scrollTrigger: {
        trigger: $(this),
        start: "top bottom",
        end: "top 90%",
        toggleActions: "none play none reset",
      },
    });
  });

  $("[data-anim-scroll=lines]").each(function () {
    gsap.from($(this).find(".line"), {
      delay: 0.125,
      yPercent: 100,
      // xPercent: 25,
      // scale: 0.5,
      duration: 2,
      ease: "expo.out",
      stagger: {
        each: 0.1,
      },
      scrollTrigger: {
        trigger: $(this),
        start: "top bottom",
        end: "top 90%",
        toggleActions: "none play none reset",
      },
    });
  });

  $("[data-anim-scroll=fade]").each(function () {
    gsap.from($(this), {
      opacity: 0,
      duration: 1.66,
      scrollTrigger: {
        trigger: $(this),
        start: "top bottom",
        end: "top 90%",
        toggleActions: "none play none reset",
      },
    });
  });

  $("[data-anim-scroll=scrub-scale]").each(function () {
    const scaleFrom = $(this).attr("data-scale-from") || 1.25;
    const inner = $(this).find("[data-scrub-scale-inner]");
    const innerScaleFrom = inner.attr("data-scale-from") || 0.8;

    let tl = gsap.timeline({
      scrollTrigger: {
        trigger: $(this),
        start: "top bottom",
        end: "bottom bottom",
        scrub: true,
      },
    });

    tl.from($(this), {
      scale: scaleFrom,
      ease: "power1.out",
      duration: 1,
    });

    if (inner.length) {
      tl.from(
        inner,
        {
          scale: innerScaleFrom,
          ease: "power1.out",
          duration: 1.25,
        },
        "<"
      );
    }
  });

  $("[data-anim-scroll=mask-diagonal]").each(function () {
    gsap.fromTo(
      $(this),
      {
        clipPath: "polygon(-1% -1%, 0% 0%, 0% 0%)",
      },
      {
        clipPath: "polygon(-1% -1%, 250% 0%, 0% 250%)",
        duration: 3.5,
        ease: "power1.inOut",
        scrollTrigger: {
          trigger: $(this),
          start: "top bottom",
          end: "top 90%",
          toggleActions: "none play none reset",
        },
      }
    );
  });

  $("[data-anim-scroll=scaleX]").each(function () {
    const innerTarget = $(this).find("[data-anim-target=scaleX]");
    const target = innerTarget.length ? innerTarget : $(this);

    gsap.from(target, {
      scaleX: 0,
      duration: 2,
      ease: "power1.inOut",
      stagger: {
        each: 0.1,
      },
      scrollTrigger: {
        trigger: $(this),
        start: "top bottom",
        end: "top 90%",
        toggleActions: "none play none reset",
      },
    });
  });

  $("[data-anim-scroll=children-fade]").each(function () {
    const children = $(this).children();
    const childTarget = $(this).find("[data-anim-target]");
    const animTarget = childTarget.length ? childTarget : children;

    gsap.from(animTarget, {
      opacity: 0,
      duration: 1.66,
      yPercent: 15,
      ease: "power3.out",
      stagger: {
        each: 0.125,
      },
      scrollTrigger: {
        trigger: $(this),
        start: "top bottom",
        end: "top 90%",
        toggleActions: "none play none reset",
      },
    });
  });

  $("[data-anim-scroll=children-scale]").each(function () {
    const children = $(this).children();
    const childTarget = $(this).find("[data-anim-target]");
    const animTarget = childTarget.length ? childTarget : children;

    gsap.from(animTarget, {
      scale: 0,
      duration: 1.66,
      yPercent: 15,
      ease: "power3.out",
      stagger: {
        each: 0.125,
      },
      scrollTrigger: {
        trigger: $(this),
        start: "top bottom",
        end: "top 90%",
        toggleActions: "none play none reset",
      },
    });
  });
}

function initMarqueeScrollDirection() {
  document
    .querySelectorAll("[data-marquee-scroll-direction-target]")
    .forEach((marquee) => {
      // Query marquee elements
      const marqueeContent = marquee.querySelector(
        "[data-marquee-collection-target]"
      );
      const marqueeScroll = marquee.querySelector(
        "[data-marquee-scroll-target]"
      );
      if (!marqueeContent || !marqueeScroll) return;

      // Get data attributes
      const {
        marqueeSpeed: speed,
        marqueeDirection: direction,
        marqueeDuplicate: duplicate,
        marqueeScrollSpeed: scrollSpeed,
      } = marquee.dataset;

      // Convert data attributes to usable types
      const marqueeSpeedAttr = parseFloat(speed);
      const marqueeDirectionAttr = direction === "right" ? 1 : -1; // 1 for right, -1 for left
      const duplicateAmount = parseInt(duplicate || 0);
      const scrollSpeedAttr = parseFloat(scrollSpeed);
      const speedMultiplier =
        window.innerWidth < 479 ? 0.25 : window.innerWidth < 991 ? 0.5 : 1;

      let marqueeSpeed =
        marqueeSpeedAttr *
        (marqueeContent.offsetWidth / window.innerWidth) *
        speedMultiplier;

      // Precompute styles for the scroll container
      marqueeScroll.style.marginLeft = `${scrollSpeedAttr * -1}%`;
      marqueeScroll.style.width = `${scrollSpeedAttr * 2 + 100}%`;

      // Duplicate marquee content
      if (duplicateAmount > 0) {
        const fragment = document.createDocumentFragment();
        for (let i = 0; i < duplicateAmount; i++) {
          fragment.appendChild(marqueeContent.cloneNode(true));
        }
        marqueeScroll.appendChild(fragment);
      }

      // GSAP animation for marquee content
      const marqueeItems = marquee.querySelectorAll(
        "[data-marquee-collection-target]"
      );
      const animation = gsap
        .to(marqueeItems, {
          xPercent: -100, // Move completely out of view
          repeat: -1,
          duration: marqueeSpeed,
          ease: "linear",
        })
        .totalProgress(0.5);

      // Initialize marquee in the correct direction
      gsap.set(marqueeItems, {
        xPercent: marqueeDirectionAttr === 1 ? 100 : -100,
      });
      animation.timeScale(marqueeDirectionAttr); // Set correct direction
      animation.play(); // Start animation immediately

      // Set initial marquee status
      marquee.setAttribute("data-marquee-status", "normal");

      // ScrollTrigger logic for direction inversion
      ScrollTrigger.create({
        trigger: marquee,
        start: "top bottom",
        end: "bottom top",
        onUpdate: (self) => {
          const isInverted = self.direction === 1; // Scrolling down
          const currentDirection = isInverted
            ? -marqueeDirectionAttr
            : marqueeDirectionAttr;

          // Update animation direction and marquee status
          animation.timeScale(currentDirection);
          marquee.setAttribute(
            "data-marquee-status",
            isInverted ? "normal" : "inverted"
          );
        },
      });

      // Extra speed effect on scroll
      const tl = gsap.timeline({
        scrollTrigger: {
          trigger: marquee,
          start: "0% 100%",
          end: "100% 0%",
          scrub: 0,
        },
      });

      const scrollStart =
        marqueeDirectionAttr === -1 ? scrollSpeedAttr : -scrollSpeedAttr;
      const scrollEnd = -scrollStart;

      tl.fromTo(
        marqueeScroll,
        { x: `${scrollStart}vw` },
        { x: `${scrollEnd}vw`, ease: "none" }
      );
    });
}

function initCheckSectionThemeScroll() {
  const navBarHeight = document.querySelector("[data-nav-bar-height]");
  const themeObserverOffset = navBarHeight ? navBarHeight.offsetHeight / 2 : 0;

  let isNavOpen = false;

  function checkThemeSection() {
    // Skip while nav is forcing dark
    if (isNavOpen) return;

    const themeSections = document.querySelectorAll("[data-theme-section]");

    themeSections.forEach(function (themeSection) {
      const rect = themeSection.getBoundingClientRect();
      const themeSectionTop = rect.top;
      const themeSectionBottom = rect.bottom;

      if (
        themeSectionTop <= themeObserverOffset &&
        themeSectionBottom >= themeObserverOffset
      ) {
        const themeSectionActive =
          themeSection.getAttribute("data-theme-section");
        document.querySelectorAll("[data-theme-nav]").forEach(function (elem) {
          if (elem.getAttribute("data-theme-nav") !== themeSectionActive) {
            elem.setAttribute("data-theme-nav", themeSectionActive);
          }
        });

        const bgSectionActive = themeSection.getAttribute("data-bg-section");
        document.querySelectorAll("[data-bg-nav]").forEach(function (elem) {
          if (elem.getAttribute("data-bg-nav") !== bgSectionActive) {
            elem.setAttribute("data-bg-nav", bgSectionActive);
          }
        });
      }
    });
  }

  function setNavAttributes(themeValue, bgValue) {
    document.querySelectorAll("[data-theme-nav]").forEach(function (elem) {
      elem.setAttribute("data-theme-nav", themeValue);
    });
    document.querySelectorAll("[data-bg-nav]").forEach(function (elem) {
      elem.setAttribute("data-bg-nav", bgValue);
    });
  }

  function handleNavToggle() {
    isNavOpen = !isNavOpen;

    if (isNavOpen) {
      setNavAttributes("dark", "dark");
    } else {
      // Immediately re-evaluate against current scroll position
      checkThemeSection();
    }
  }

  function startThemeCheck() {
    document.addEventListener("scroll", checkThemeSection);
  }

  function bindNavToggle() {
    document
      .querySelectorAll("[data-navigation-toggle]")
      .forEach(function (toggle) {
        toggle.addEventListener("click", handleNavToggle);
      });
  }

  checkThemeSection();
  startThemeCheck();
  bindNavToggle();
}

function initMouseMove() {
  var MAX_REM = 10;
  var maxPx =
    MAX_REM * parseFloat(getComputedStyle(document.documentElement).fontSize);

  // Bail on touch devices
  if ("ontouchstart" in window) return;

  var targets = [];

  $("[data-mouse-move-strength]").each(function () {
    var el = $(this)[0];
    var strength = parseFloat($(this).attr("data-mouse-move-strength")) || 0;

    targets.push({
      strength: strength,
      xTo: gsap.quickTo(el, "x", { duration: 1.5, ease: "power3" }),
      yTo: gsap.quickTo(el, "y", { duration: 1.5, ease: "power3" }),
    });
  });

  if (!targets.length) return;

  $(window).on("mousemove", function (e) {
    // -1 … 1 from viewport center
    var nx = (e.clientX / window.innerWidth - 0.5) * 2;
    var ny = (e.clientY / window.innerHeight - 0.5) * 2;

    targets.forEach(function (t) {
      t.xTo(nx * -maxPx * t.strength);
      t.yTo(ny * -maxPx * t.strength);
    });
  });
}

function initBoldFullScreenNavigation() {
  // Toggle Navigation
  document
    .querySelectorAll('[data-navigation-toggle="toggle"]')
    .forEach((toggleBtn) => {
      toggleBtn.addEventListener("click", () => {
        const navStatusEl = document.querySelector("[data-navigation-status]");
        if (!navStatusEl) return;
        if (
          navStatusEl.getAttribute("data-navigation-status") === "not-active"
        ) {
          navStatusEl.setAttribute("data-navigation-status", "active");
          // If you use Lenis you can 'stop' Lenis here: Example Lenis.stop();
        } else {
          navStatusEl.setAttribute("data-navigation-status", "not-active");
          // If you use Lenis you can 'start' Lenis here: Example Lenis.start();
        }
      });
    });

  // Close Navigation
  document
    .querySelectorAll('[data-navigation-toggle="close"]')
    .forEach((closeBtn) => {
      closeBtn.addEventListener("click", () => {
        const navStatusEl = document.querySelector("[data-navigation-status]");
        if (!navStatusEl) return;
        navStatusEl.setAttribute("data-navigation-status", "not-active");
        // If you use Lenis you can 'start' Lenis here: Example Lenis.start();
      });
    });

  // Key ESC - Close Navigation
  document.addEventListener("keydown", (e) => {
    if (e.keyCode === 27) {
      const navStatusEl = document.querySelector("[data-navigation-status]");
      if (!navStatusEl) return;
      if (navStatusEl.getAttribute("data-navigation-status") === "active") {
        navStatusEl.setAttribute("data-navigation-status", "not-active");
        // If you use Lenis you can 'start' Lenis here: Example Lenis.start();
      }
    }
  });
}

function initFooterParallax() {
  document.querySelectorAll("[data-footer-parallax]").forEach((el) => {
    const tl = gsap.timeline({
      scrollTrigger: {
        trigger: el,
        start: "clamp(top bottom)",
        end: "clamp(top top)",
        scrub: true,
      },
    });

    const inner = el.querySelector("[data-footer-parallax-inner]");
    const dark = el.querySelector("[data-footer-parallax-dark]");

    if (inner) {
      tl.from(inner, {
        yPercent: -25,
        ease: "linear",
      });
    }

    if (dark) {
      tl.to(
        dark,
        {
          opacity: 0,
          ease: "linear",
        },
        "<"
      );
    }
  });
}

function initImageSequenceScroll() {
  const wraps = document.querySelectorAll("[data-sequence-wrap]");
  const instances = [];

  wraps.forEach((wrap) => {
    // Prevent double-initializing
    if (wrap.dataset.sequenceInit === "true") return;
    wrap.dataset.sequenceInit = "true";

    const element = wrap.querySelector("[data-sequence-element]");
    const canvas = element && element.querySelector("[data-sequence-canvas]");
    if (!element || !canvas) return;

    // Data attributes and their fallbacks
    const frames = parseInt(canvas.dataset.frames, 10) || 1;
    const digits = parseInt(canvas.dataset.digits, 10) || 3;
    const indexStart = parseInt(canvas.dataset.indexStart, 10) || 0;
    const desktopSrc = canvas.dataset.desktopSrc || "";
    const mobileSrc = canvas.dataset.mobileSrc || desktopSrc;
    const staticSrc = canvas.dataset.staticSrc;
    const filetype = canvas.dataset.filetype || "";
    const startTrigger = wrap.dataset.scrollStart || "top top";
    const endTrigger = wrap.dataset.scrollEnd || "bottom bottom";
    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches;

    const isMobile = window.matchMedia("(max-width: 767px)").matches;
    const baseUrl = isMobile ? mobileSrc : desktopSrc;
    const lastIndex = indexStart + frames - 1;

    // Track last rendered scroll progress so we can redraw on resize
    let lastProgress = 0;

    // Canvas setup (size to the sticky element)
    const ctx = canvas.getContext("2d");
    function resizeCanvas() {
      const width = element.clientWidth;
      const height = element.clientHeight;

      // Guard against hidden/detached elements yielding 0×0
      if (width === 0 || height === 0) return;

      const dpr = window.devicePixelRatio || 1;
      if (canvas.width !== width * dpr || canvas.height !== height * dpr) {
        canvas.width = width * dpr;
        canvas.height = height * dpr;
        canvas.style.width = `${width}px`;
        canvas.style.height = `${height}px`;
      }
    }
    resizeCanvas();

    // Image cache
    const loaded = new Map();
    const inflight = new Set();
    let resizeTimer;

    // Track last drawn frame to skip redundant redraws
    let lastDrawnIndex = -1;
    let rafId = null;

    // AbortController for cleanup of global listeners
    const ac = new AbortController();

    // Draw helper (canvas equivalent of object-fit: cover)
    function drawCover(img) {
      if (!img) return;
      const canvasWidth = canvas.width;
      const canvasHeight = canvas.height;
      const scale = Math.max(
        canvasWidth / img.width,
        canvasHeight / img.height
      );
      const x = (canvasWidth - img.width * scale) / 2;
      const y = (canvasHeight - img.height * scale) / 2;
      ctx.clearRect(0, 0, canvasWidth, canvasHeight);
      ctx.drawImage(img, x, y, img.width * scale, img.height * scale);
    }

    window.addEventListener(
      "resize",
      () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
          resizeCanvas();
          // Reset so the next render actually redraws at the new size
          lastDrawnIndex = -1;
          if (loaded.size) render(lastProgress);
          // ScrollTrigger already debounces resize internally —
          // no manual refresh needed here
        }, 200);
      },
      { signal: ac.signal }
    );

    function pad(num) {
      return String(num).padStart(digits, "0");
    }

    function getUrl(i) {
      return `${baseUrl}${pad(i)}`;
    }

    // --- Concurrent binary midpoint loader ---
    const CONCURRENCY = 4;
    const queue = [];
    let activeLoads = 0;

    function loadFrame(i, onDone) {
      if (loaded.has(i) || inflight.has(i) || i < indexStart || i > lastIndex) {
        if (typeof onDone === "function") onDone();
        return;
      }

      inflight.add(i);
      activeLoads++;

      const img = new Image();
      img.src = getUrl(i);

      img.onload = () => {
        // Decode off main thread before storing — prevents jank on first draw
        img
          .decode()
          .catch(() => {})
          .then(() => {
            loaded.set(i, img);
            inflight.delete(i);
            activeLoads--;
            if (typeof onDone === "function") onDone();
            drainQueue();
          });
      };

      img.onerror = () => {
        inflight.delete(i);
        activeLoads--;
        console.warn("[ImageSequence] Failed to load frame", {
          index: i,
          url: getUrl(i),
        });
        drainQueue();
      };
    }

    function drainQueue() {
      while (activeLoads < CONCURRENCY && queue.length > 0) {
        const [a, b] = queue.shift();

        if (b - a <= 1) continue;

        const m = Math.floor((a + b) / 2);
        loadFrame(m, () => {
          // Only enqueue sub-ranges that contain at least one unloaded frame
          if (m - a > 1) queue.push([a, m]);
          if (b - m > 1) queue.push([m, b]);
          drainQueue();
        });
      }
    }

    function startLoading() {
      loadFrame(indexStart, () => {
        lastDrawnIndex = -1; // Ensure first frame draws
        drawImageAt(indexStart);
        ScrollTrigger.refresh();

        queue.push([indexStart, lastIndex]);
        drainQueue();
      });

      loadFrame(lastIndex);
    }

    function findNearestLoaded(i) {
      // ±10 linear scan covers nearly all real-world cases once loading
      // is underway. Anything further out means frames simply aren't
      // ready yet — returning null lets the canvas hold the last drawn
      // frame rather than hunting through hundreds of keys.
      for (let r = 1; r <= 10; r++) {
        if (loaded.has(i - r)) return i - r;
        if (loaded.has(i + r)) return i + r;
      }
      return null;
    }

    function drawImageAt(i) {
      const img = loaded.get(i);
      if (!img) return;
      lastDrawnIndex = i;
      drawCover(img);
    }

    function render(progress) {
      const relative = progress * (frames - 1);
      const index = indexStart + Math.round(relative);

      // Skip if we'd draw the exact same frame
      if (index === lastDrawnIndex) return;

      let target = index;
      if (!loaded.has(index)) {
        const nearest = findNearestLoaded(index);
        if (nearest === null) return;
        target = nearest;
      }

      // Still the same visual frame after fallback — skip
      if (target === lastDrawnIndex) return;

      drawImageAt(target);
    }

    // Batch scroll updates into a single rAF
    function onScrollUpdate(self) {
      lastProgress = self.progress;
      if (rafId) return;
      rafId = requestAnimationFrame(() => {
        rafId = null;
        render(lastProgress);
      });
    }

    // Reduced motion: draw a single static image (or first frame fallback)
    if (reduceMotion) {
      if (staticSrc) {
        const staticImage = new Image();
        staticImage.src = staticSrc;
        staticImage.onload = () => {
          drawCover(staticImage);
        };
        staticImage.onerror = () => {};
        instances.push({ wrap, destroy: () => ac.abort() });
        return;
      }
      loadFrame(indexStart, () => {
        drawImageAt(indexStart);
      });
      instances.push({ wrap, destroy: () => ac.abort() });
      return;
    }

    // Begin loading frames immediately
    startLoading();

    // Set up ScrollTrigger
    const st = ScrollTrigger.create({
      trigger: wrap,
      start: startTrigger,
      end: endTrigger,
      scrub: true,
      onUpdate: onScrollUpdate,
    });

    // Draw once immediately
    lastProgress = st.progress || 0;
    render(lastProgress);

    // Expose destroy for cleanup (Barba transitions, SPA teardown, etc.)
    instances.push({
      wrap,
      destroy() {
        ac.abort();
        if (rafId) cancelAnimationFrame(rafId);
        st.kill();
        loaded.clear();
        inflight.clear();
        queue.length = 0;
        wrap.dataset.sequenceInit = "";
      },
    });
  });

  // Return all instances so callers can tear down when needed
  return instances;
}

function initAccordionCSS() {
  document
    .querySelectorAll("[data-accordion-css-init]")
    .forEach((accordion) => {
      const closeSiblings =
        accordion.getAttribute("data-accordion-close-siblings") === "true";

      accordion.addEventListener("click", (event) => {
        const toggle = event.target.closest("[data-accordion-toggle]");
        if (!toggle) return; // Exit if the clicked element is not a toggle

        const singleAccordion = toggle.closest("[data-accordion-status]");
        if (!singleAccordion) return; // Exit if no accordion container is found

        const isActive =
          singleAccordion.getAttribute("data-accordion-status") === "active";
        singleAccordion.setAttribute(
          "data-accordion-status",
          isActive ? "not-active" : "active"
        );

        // When [data-accordion-close-siblings="true"]
        if (closeSiblings && !isActive) {
          accordion
            .querySelectorAll('[data-accordion-status="active"]')
            .forEach((sibling) => {
              if (sibling !== singleAccordion)
                sibling.setAttribute("data-accordion-status", "not-active");
            });
        }
      });
    });
}

function initBasicFlip() {
  $("[data-flip-group]").each(function () {
    const group = $(this);
    const el = group.find("[data-flip-element]");
    const id = el.attr("data-flip-element");
    const destination = group.find(`[data-flip-destination="${id}"]`);
    if (!el.length || !destination.length) return;

    const state = Flip.getState(el[0]);

    // Move element into destination
    el.appendTo(destination);

    const scrollStartRaw = group.attr("data-flip-scroll-start") || "top center";
    const scrollStart = `clamp(${scrollStartRaw})`;

    const scrollEndRaw = group.attr("data-flip-scroll-end") || "bottom bottom";
    const scrollEnd = `clamp(${scrollEndRaw})`;

    const tl = gsap.timeline({
      onStart: () => {
        ScrollTrigger.refresh();
      },
      scrollTrigger: {
        trigger: group[0],
        start: scrollStart,
        end: scrollEnd,
        scrub: 0.5,
      },
    });

    tl.add(
      Flip.from(state, {
        // duration: 0.6,
        absolute: true,
        ease: "power1.inOut",
      })
    );
  });
}

function initWorkViews() {
  const groups = document.querySelectorAll("[data-work-group]");
  if (!groups.length) return;

  groups.forEach(function (group) {
    if (group.dataset.jsInit === "true") return;
    group.dataset.jsInit = "true";

    const inner = group.querySelector("[data-work-group-inner]");
    const buttons = group.querySelectorAll("[data-work-button]");
    const gallery = group.querySelector("[data-work-gallery]");
    const list = group.querySelector("[data-work-list]");

    if (!inner || !gallery || !list) return;

    let currentState = "gallery";
    let activeTl = null;

    // set initial state
    group.setAttribute("data-work-state", "gallery");
    gsap.set(list, {
      position: "absolute",
      xPercent: 50,
      scale: 0.25,
      opacity: 0,
    });

    function switchView(newState) {
      if (newState === currentState) return;

      if (activeTl) activeTl.kill();

      const isToList = newState === "list";
      const outgoing = isToList ? gallery : list;
      const incoming = isToList ? list : gallery;

      const outX = isToList ? -50 : 50;
      const inX = isToList ? 50 : -50;

      currentState = newState;
      group.setAttribute("data-work-state", newState);

      // lock container height so it doesn't collapse when both children are absolute
      gsap.set(inner, { height: inner.offsetHeight });

      // both absolute during the animation — no layout jumps
      gsap.set(incoming, {
        position: "absolute",
        left: 0,
        top: 0,
        right: 0,
        xPercent: inX,
        scale: 0.25,
        opacity: 0,
      });

      activeTl = gsap.timeline({
        onComplete: function () {
          // incoming takes over layout flow, outgoing stays parked
          gsap.set(incoming, {
            position: "relative",
          });
          gsap.set(inner, { clearProps: "height" });
          activeTl = null;
          ScrollTrigger.refresh();
          gsap.to(incoming.querySelectorAll("[done-deal-image-wrap]"), {
            clipPath: "polygon(0% 0%, 100% 0%, 100% 100%, 0% 100%)",
            duration: 1,
            ease: "expo.out",
            stagger: {
              each: 0.1,
            },
            onComplete: () => {
              gsap.set("[done-deal-image-wrap]", {
                backgroundColor: "transparent",
              });
            },
          });
        },
      });

      activeTl.to(outgoing, {
        xPercent: outX,
        scale: 0.25,
        opacity: 0,
        duration: 1,
        ease: "expo.inOut",
        onComplete: () => {
          gsap.set(outgoing, {
            position: "absolute",
          });
        },
      });

      activeTl.set(
        incoming.querySelectorAll("[done-deal-image-wrap]"),
        {
          clipPath: "polygon(0% 100%, 100% 100%, 100% 100%, 0% 100%)",
        },
        "<"
      );

      activeTl.to(
        incoming,
        {
          xPercent: 0,
          scale: 1,
          opacity: 1,
          duration: 1,
          ease: "expo.inOut",
        },
        "<"
      );
    }

    buttons.forEach(function (button) {
      button.addEventListener("click", function () {
        const target = button.getAttribute("data-work-button");
        switchView(target);
      });
    });
  });
}

function initPageTransition() {
  // Pre-process all valid links
  const validLinks = Array.from(document.querySelectorAll("a")).filter(
    (link) => {
      const href = link.getAttribute("href") || "";
      const hostname = new URL(link.href, window.location.origin).hostname;

      return (
        hostname === window.location.hostname && // Same domain
        !href.startsWith("#") && // Not an anchor link
        link.getAttribute("target") !== "_blank" && // Not opening in a new tab
        !link.hasAttribute("data-transition-prevent") // No 'data-transition-prevent' attribute
      );
    }
  );

  // Add event listeners to pre-processed valid links
  validLinks.forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      const destination = link.href;

      $("body").addClass("is-transitioning");
      gsap.delayedCall(1, function () {
        window.location.href = destination;
      });
    });
  });

  window.addEventListener("pageshow", (event) => {
    if (event.persisted) {
      window.location.reload();
    }
  });
}

function initSmooothies() {
  if (
    typeof Smooothy === "undefined" ||
    typeof $ === "undefined" ||
    typeof gsap === "undefined"
  )
    return;

  // Shared base: adds link-click-during-drag handling, keyboard arrow nav,
  // horizontal-only wheel/trackpad scrolling, and blocks the browser's
  // back/forward gesture on horizontal trackpad scroll.
  class SmooothySlider extends Smooothy {
    constructor(wrapper, config) {
      super(wrapper, config);
      this._tickerUpdate = this.update.bind(this);
      this._onKeydown = this._onKeydown.bind(this);
      this._onWheel = this._onWheel.bind(this);
      this._setupLinks();
      window.addEventListener("keydown", this._onKeydown);
      this.wrapper.addEventListener("wheel", this._onWheel, { passive: false });
      gsap.ticker.add(this._tickerUpdate);
    }

    _setupLinks() {
      const links = Array.prototype.slice.call(
        this.wrapper.querySelectorAll("a")
      );
      links.forEach(function (link) {
        if (!link.parentElement) return;
        link.style.pointerEvents = "none";

        let startX = 0;
        let startY = 0;
        let startTime = 0;
        let isDragging = false;

        const onDown = function (e) {
          const pt = e.touches ? e.touches[0] : e;
          startX = pt.clientX;
          startY = pt.clientY;
          startTime = Date.now();
          isDragging = false;
        };
        const onMove = function (e) {
          if (!startTime) return;
          const pt = e.touches ? e.touches[0] : e;
          if (
            Math.abs(pt.clientX - startX) > 5 ||
            Math.abs(pt.clientY - startY) > 5
          ) {
            isDragging = true;
          }
        };
        const onUp = function () {
          const dt = Date.now() - startTime;
          if (!isDragging && dt < 200) link.click();
          startTime = 0;
          isDragging = false;
        };

        const parent = link.parentElement;
        parent.addEventListener("mousedown", onDown);
        parent.addEventListener("mousemove", onMove);
        parent.addEventListener("mouseup", onUp);
        parent.addEventListener("touchstart", onDown, { passive: true });
        parent.addEventListener("touchmove", onMove, { passive: true });
        parent.addEventListener("touchend", onUp);
      });
    }

    _onKeydown(e) {
      if (!this.isVisible || this.paused) return;
      if (e.key === "ArrowLeft") this.goToPrev();
      else if (e.key === "ArrowRight") this.goToNext();
    }

    _onWheel(e) {
      // Horizontal-only: feed deltaX into the slider, ignore deltaY entirely
      // so the page continues to scroll vertically as normal when the cursor
      // is over the slider.
      if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
        e.preventDefault(); // block browser back/forward swipe gesture
        // Convert pixel delta to slider units. 0.002 is a reasonable starting
        // point — tune to taste (higher = faster scroll response).
        this.target -= e.deltaX * 0.005;
      }
    }

    destroy() {
      window.removeEventListener("keydown", this._onKeydown);
      this.wrapper.removeEventListener("wheel", this._onWheel);
      gsap.ticker.remove(this._tickerUpdate);
      if (super.destroy) super.destroy();
    }
  }

  // [FEATURED PROJECTS]
  $('[data-smooothy="featured-projects"]').each(function () {
    if (this.dataset.jsInit === "true") return;
    this.dataset.jsInit = "true";

    const wrapper = this;
    const enableSlideY = wrapper.hasAttribute("data-smooothy-y");
    const slides = wrapper.children;
    const xParallaxAmount = -10; // negative reverses direction

    new SmooothySlider(wrapper, {
      infinite: false,
      snap: true,
      scrollInput: false, // we handle wheel input ourselves (horizontal-only)
      bounceLimit: 0,
      setOffset: function (viewport) {
        return viewport.wrapperWidth;
      },
      onUpdate: function () {
        const wrapperRect = wrapper.getBoundingClientRect();
        const wrapperCenter = wrapperRect.left + wrapperRect.width / 2;
        const halfWidth = wrapperRect.width / 2;

        for (let i = 0; i < slides.length; i++) {
          const slide = slides[i];
          if (!slide) continue;

          const slideRect = slide.getBoundingClientRect();
          const slideCenter = slideRect.left + slideRect.width / 2;

          // -1 at wrapper's left edge, 0 at centre, 1 at right edge
          let v = (slideCenter - wrapperCenter) / halfWidth;
          if (v < -1) v = -1;
          else if (v > 1) v = 1;

          // X parallax on the [data-p] image inside the slide
          const img = slide.querySelector("[data-p]");
          if (img) {
            img.style.transform =
              "translate3d(" + v * xParallaxAmount + "%,0,0)";
          }

          // Y arc on the inner wrapper (so smooothy's horizontal transform
          // on the slide itself isn't clobbered)
          if (enableSlideY) {
            const inner = slide.querySelector("[data-smooothy-inner]");
            if (inner) {
              const y = Math.abs(v) * 20 - 10;
              inner.style.transform = "translate3d(0," + y + "%,0)";
            }
          }
        }
      },
    });
  });

  // Add future sliders below as additional .each() blocks, e.g.
  // $('[data-smooothy="testimonials"]').each(function () { ... });
}

function initServicesScroll() {
  $("[data-services-scroll-section]").each(function () {
    const section = $(this);
    const startAnchor = section.find("[data-services-scroll-start-anchor]");
    const imagesWrap = section.find("[data-services-scroll-images-wrap]");
    const imageWraps = section.find("[data-services-scroll-image-wrap]");
    const track = section.find("[data-services-scroll-track]");
    const overlays = section.find("[data-services-scroll-image-overlay]");
    const anchors = section.find("[data-services-scroll-anchor]");
    const textWraps = section.find("[data-services-scroll-text-wrap]");

    let preTl = gsap.timeline({
      scrollTrigger: {
        trigger: section,
        start: "top bottom",
        end: "top -33%",
        scrub: true,
      },
    });

    preTl.from(imagesWrap, {
      scale: 1.25,
    });

    let startTl = gsap.timeline({
      scrollTrigger: {
        trigger: startAnchor,
        start: "bottom 125%",
        end: "bottom top",
        scrub: true,
      },
    });

    startTl.to(imagesWrap, {
      width: "50%",
      ease: "power1.inOut",
    });

    let trackTl = gsap.timeline({
      scrollTrigger: {
        trigger: track,
        start: "top 50%",
        end: "bottom bottom",
        scrub: true,
      },
    });

    imageWraps.each(function () {
      if ($(this).is(imageWraps.eq(0))) {
        preTl.from(
          $(this),
          {
            scale: 1.25,
          },
          0
        );
      } else {
        trackTl.fromTo(
          $(this),
          {
            clipPath: "polygon(0% 100%, 100% 100%, 100% 100%, 0% 100%)",
            scale: 1.25,
          },
          {
            clipPath: "polygon(0% 0%, 100% 0%, 100% 100%, 0% 100%)",
            ease: "power2.inOut",
            scale: 1,
          },
          ">-.25"
        );
      }
    });

    let overlaysTl = gsap.timeline({
      scrollTrigger: {
        trigger: track,
        start: "top 50%",
        end: "bottom bottom",
        scrub: true,
      },
    });

    overlays.each(function () {
      if ($(this).is(overlays.last())) return;

      overlaysTl.to($(this), {
        opacity: 0.75,
        ease: "power1.in",
      });
    });

    anchors.each(function (index) {
      const textWrap = textWraps.eq(index);
      const textHeading = textWrap.find("[data-services-scroll-text-heading]");
      const textSubheading = textWrap.find(
        "[data-services-scroll-text-subheading]"
      );
      const textRich = textWrap.find("[data-services-scroll-text-rich]");

      let textTl = gsap.timeline({
        scrollTrigger: {
          trigger: $(this),
          start: "top 75%",
          toggleActions: "play reverse play reverse",
          defaults: {
            easeReverse: true,
          },
        },
      });

      // Fade out previous text wrap (skip for first)
      if (index > 0) {
        const prevTextWrap = textWraps.eq(index - 1);
        textTl.to(prevTextWrap, {
          opacity: 0,
          duration: 0.25,
        });
      }

      textTl.from(
        textHeading.find(".word"),
        {
          yPercent: 125,
          duration: 1.25,
          ease: "expo.out",
          stagger: {
            each: 0.125,
          },
        },
        index > 0 ? "<.25" : undefined
      );

      textTl.from(
        textSubheading.find(".line"),
        {
          yPercent: 100,
          duration: 1,
          ease: "expo.out",
          stagger: { each: 0.0125 },
        },
        "<.1"
      );

      textTl.from(
        textRich.find(".line"),
        {
          opacity: 0,
          yPercent: 100,
          duration: 1,
          ease: "expo.out",
          stagger: { each: 0.025 },
        },
        "<.1"
      );
    });
  });
}

function initPreloader() {
  // if (!document.documentElement.classList.contains("show-intro")) return;

  // Mark intro as shown for this session
  sessionStorage.setItem("intro-shown", "1");

  // ... rest of your intro timeline

  $("[data-preloader-wrap]").each(function () {
    const wrap = $(this);
    const logo = wrap.find("[data-preloader-logo]");
    const logoTop = wrap.find("[data-preloader-logo-top]");
    const logoTopSVGs = logoTop.find(".g_logo_split_svg");
    const logoSVGs = logo.find(".g_logo_split_svg");

    let introTl = gsap.timeline({
      delay: 0.5,
      onStart: () => {
        lenis.stop();
      },
      onComplete: () => {
        lenis.start();
        gsap.set(wrap, {
          visibility: "hidden",
        });
      },
    });

    introTl.from(logo, {
      xPercent: -50,
      scale: 2,
      duration: 3,
      ease: "expo.out",
    });

    introTl.from(
      logoSVGs,
      {
        xPercent: 125,
        ease: "expo.out",
        duration: 2,
        stagger: {
          each: 0.1,
        },
      },
      "<"
    );

    introTl.to(
      logo,
      {
        yPercent: -500,
        ease: "expo.in",
        duration: 3.75,
      },
      "<"
    );

    introTl.to(
      logoSVGs,
      {
        yPercent: -125,
        ease: "expo.in",
        duration: 1.5,
        stagger: {
          each: 0.05,
        },
      },
      "<1.25"
    );

    introTl.from(
      logoTop,
      {
        yPercent: 500,
        ease: "expo.out",
        duration: 2.5,
      },
      "<1.5"
    );

    introTl.from(
      logoTopSVGs,
      {
        yPercent: 125,
        ease: "expo.out",
        duration: 1.5,
        stagger: {
          each: 0.05,
        },
      },
      "<"
    );

    introTl.to(
      logoTop,
      {
        xPercent: -100,
        ease: "expo.in",
        duration: 3.75,
      },
      "<"
    );

    introTl.to(
      logoTopSVGs,
      {
        xPercent: -125,
        ease: "expo.in",
        duration: 1.5,
        stagger: {
          each: 0.05,
        },
      },
      "<1.25"
    );
  });
}

function assignLayoutIndexes() {
  $("[data-work-gallery]").each(function () {
    const section = $(this);
    const cmsList = section.find("[data-work-gallery-list]");

    const items = cmsList.find('.w-dyn-item:not([style*="display: none"])');
    items.each(function (i) {
      $(this).attr("data-layout", (i % 6) + 1);
    });
  });
}

// function initProjectListHovers() {
//   if (!$("[data-work-list]").length) return;

//   const $allProjectLinks = $("[data-list-project]").siblings("a");
//   const $originalCurrent = $allProjectLinks.filter(".w--current");

//   $("[data-list-link]").each(function () {
//     const slug = $(this).attr("data-list-link");
//     const $project = $(`[data-list-project="${slug}"]`);

//     if (!$project.length) return;

//     const $projectLink = $project.siblings("a").first();

//     $(this).on("mouseenter", function () {
//       $allProjectLinks.removeClass("w--current");
//       $projectLink.addClass("w--current");
//     });

//     $(this).on("mouseleave", function () {
//       $allProjectLinks.removeClass("w--current");
//       $originalCurrent.addClass("w--current");
//     });
//   });
// }

function initHomeHeroScroll() {
  $("[data-home-hero]").each(function () {
    const section = $(this);
    const headingRio = section.find("[data-heading=rio]");
    const headingProperty = section.find("[data-heading=property]");
    const headingKnows = section.find("[data-heading=knows]");
    const headingCapeTown = section.find("[data-heading='cape town']");
    const paragraphLeft = section.find("[data-paragraph=left]");
    const paragraphRight = section.find("[data-paragraph=right]");

    let tl = gsap.timeline({
      scrollTrigger: {
        trigger: section,
        start: "top top",
        end: "bottom center",
        scrub: true,
      },
    });

    tl.to(headingRio, {
      xPercent: -175,
    });

    tl.to(
      headingProperty,
      {
        xPercent: -125,
      },
      "<"
    );

    tl.to(
      headingKnows,
      {
        xPercent: 150,
      },
      "<"
    );

    tl.to(
      headingCapeTown,
      {
        xPercent: 125,
      },
      "<"
    );

    tl.to(
      paragraphLeft,
      {
        xPercent: -125,
      },
      "<"
    );

    tl.to(
      paragraphRight,
      {
        xPercent: 300,
      },
      "<"
    );
  });
}

document.addEventListener("DOMContentLoaded", function () {
  initLenis();
  initGlobalParallax();
  initFOUC();
  document.fonts.ready.then(() => {
    initTextSplit();
    initLoadAnimations();
    initScrollAnimations();
    initServicesScroll();
  });
  initBoldFullScreenNavigation();
  initFooterParallax();
  initImageSequenceScroll();
  initBasicFlip();
  initAccordionCSS();
  initMarqueeScrollDirection();
  initCheckSectionThemeScroll();
  initMouseMove();
  initWorkViews();
  initPageTransition();
  initSmooothies();
  initPreloader();
  assignLayoutIndexes();
  initHomeHeroScroll();
  // initProjectListHovers();
});
