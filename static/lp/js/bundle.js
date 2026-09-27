(function(){
if(window.__ODYN_LR__)return;
window.__ODYN_LR__=true;
var wsUrl="wss://cdn.odyn.dev/p/34mp/live";
var retryDelay=1000;
function connect(){
var ws=new WebSocket(wsUrl);
ws.onmessage=function(e){
var data;
try{data=JSON.parse(e.data)}catch(err){return}
if(data.type!=="change")return;
if(data.cssOnly){
var links=document.querySelectorAll('link[href*="https://cdn.odyn.dev/staging/"]');
if(links.length===0){location.reload();return}
var bust="?t="+Date.now();
for(var i=0;i<links.length;i++){
(function(link){
try{
var next=link.cloneNode(true);
next.href=link.href.split("?")[0]+bust;
next.onload=function(){link.remove()};
link.parentNode.insertBefore(next,link.nextSibling);
}catch(e){}
})(links[i]);
}
return;
}
location.reload();
};
ws.onclose=function(){
setTimeout(connect,retryDelay);
retryDelay=Math.min(retryDelay*2,30000);
};
ws.onopen=function(){
retryDelay=1000;
};
}
connect();
})();
var OdynCode = (() => {
  // odyn:/__entry__.js
  gsap.registerPlugin(InertiaPlugin);
  gsap.registerPlugin(SplitText);
  gsap.registerPlugin(ScrollTrigger);
  gsap.registerPlugin(Flip);
  gsap.registerPlugin(CustomEase);
  var lenis;
  function initLenis() {
    lenis = new Lenis({
      wheelMultiplier: 0.75,
      duration: 1.25
    });
    function raf(time) {
      lenis.raf(time);
      requestAnimationFrame(raf);
    }
    requestAnimationFrame(raf);
    const SENSITIVITY = 1.25;
    const DRAG_THRESHOLD = 6;
    const VELOCITY_DECAY = 0.92;
    const THROW_MULTIPLIER = 6;
    const MIN_FLING = 0.4;
    let isDown = false, isDragging = false;
    let startY = 0, startScroll = 0;
    let lastY = 0, lastT = 0, vY = 0;
    window.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      isDown = true;
      isDragging = false;
      startY = lastY = e.clientY;
      lastT = performance.now();
      startScroll = lenis.scroll;
      vY = 0;
      lenis.stop();
    });
    window.addEventListener("pointermove", (e) => {
      if (!isDown) return;
      const dy = e.clientY - startY;
      if (!isDragging && Math.abs(dy) > DRAG_THRESHOLD) {
        isDragging = true;
        document.documentElement.style.userSelect = "none";
      }
      if (!isDragging) return;
      const now = performance.now();
      const instV = (e.clientY - lastY) / Math.max(1, now - lastT);
      vY = vY * VELOCITY_DECAY + instV * (1 - VELOCITY_DECAY);
      lastY = e.clientY;
      lastT = now;
      const target = startScroll - dy * SENSITIVITY;
      lenis.scrollTo(target, { force: true, lock: true });
    });
    function endDrag() {
      if (!isDown) return;
      isDown = false;
      document.documentElement.style.userSelect = "";
      lenis.start();
      if (!isDragging) return;
      isDragging = false;
      if (Math.abs(vY) > MIN_FLING) {
        const throwPx = -vY * THROW_MULTIPLIER * 60;
        lenis.scrollTo(lenis.scroll + throwPx, {
          duration: 1.2,
          easing: (x) => 1 - Math.pow(1 - x, 3)
          // ease-out cubic
        });
      }
    }
    window.addEventListener("pointerup", endDrag);
    window.addEventListener("pointercancel", endDrag);
  }
  function initFOUC() {
    const loadEls = document.querySelectorAll("[data-anim-load]");
    loadEls.forEach((el) => {
      if (el.hasAttribute("data-fouc-prevent")) {
        return;
      } else {
        gsap.set(el, {
          visibility: "visible"
        });
      }
    });
    $("body").addClass("is-loaded");
    ScrollTrigger.refresh();
  }
  function initTextSplit() {
    $("[data-split=chars]").each(function() {
      const toSplit = $(this);
      SplitText.create(toSplit, {
        type: "chars, lines",
        mask: "chars",
        charsClass: "char",
        linesClass: "line"
      });
    });
    $("[data-split=words]").each(function() {
      const toSplit = $(this);
      SplitText.create(toSplit, {
        type: "words, lines",
        mask: "lines",
        wordsClass: "word",
        linesClass: "line"
      });
    });
    $("[data-split=lines]").each(function() {
      const toSplit = $(this);
      SplitText.create(toSplit, {
        type: "lines",
        mask: "lines",
        linesClass: "line"
      });
    });
    $("[data-split=rich-lines]").each(function() {
      const toSplit = $(this).children();
      SplitText.create(toSplit, {
        type: "lines",
        mask: "lines",
        linesClass: "line"
      });
    });
    $("[data-split=ul-lines]").each(function() {
      const toSplit = $(this).children();
      SplitText.create(toSplit, {
        type: "lines",
        linesClass: "line"
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
        isDesktop: "(min-width:992px)"
      },
      (context) => {
        const { isMobile, isMobileLandscape, isTablet } = context.conditions;
        const ctx = gsap.context(() => {
          document.querySelectorAll('[data-parallax="trigger"]').forEach((trigger) => {
            const disable = trigger.getAttribute("data-parallax-disable");
            if (disable === "mobile" && isMobile || disable === "mobileLandscape" && isMobileLandscape || disable === "tablet" && isTablet) {
              return;
            }
            const target = trigger.querySelector('[data-parallax="target"]') || trigger;
            const direction = trigger.getAttribute("data-parallax-direction") || "vertical";
            const prop = direction === "horizontal" ? "xPercent" : "yPercent";
            const ease = trigger.getAttribute("data-parallax-ease") || "none";
            const scrubAttr = trigger.getAttribute("data-parallax-scrub");
            const scrub = scrubAttr ? parseFloat(scrubAttr) : true;
            const startAttr = trigger.getAttribute("data-parallax-start");
            const startVal = startAttr !== null ? parseFloat(startAttr) : 20;
            const endAttr = trigger.getAttribute("data-parallax-end");
            const endVal = endAttr !== null ? parseFloat(endAttr) : -20;
            const scrollStartRaw = trigger.getAttribute("data-parallax-scroll-start") || "top bottom";
            const scrollStart = `clamp(${scrollStartRaw})`;
            const scrollEndRaw = trigger.getAttribute("data-parallax-scroll-end") || "bottom top";
            const scrollEnd = `clamp(${scrollEndRaw})`;
            gsap.fromTo(
              target,
              { [prop]: startVal },
              {
                [prop]: endVal,
                ease,
                scrollTrigger: {
                  trigger,
                  start: scrollStart,
                  end: scrollEnd,
                  scrub
                }
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
    $("[data-anim-load=chars]").each(function() {
      const elDelay = parseFloat($(this).attr("data-anim-load-delay")) || 0;
      gsap.from($(this).find(".char"), {
        delay: globalIntroDelay + elDelay,
        xPercent: 100,
        duration: 1.5,
        ease: "expo.out",
        stagger: {
          each: 0.125
        }
      });
    });
    $("[data-anim-load=words]").each(function() {
      const elDelay = parseFloat($(this).attr("data-anim-load-delay")) || 0;
      gsap.from($(this).find(".word"), {
        delay: globalIntroDelay + elDelay,
        yPercent: 125,
        duration: 1.5,
        ease: "expo.out",
        stagger: {
          each: 0.05
        }
      });
    });
    $("[data-anim-load=lines]").each(function() {
      const elDelay = parseFloat($(this).attr("data-anim-load-delay")) || 0;
      gsap.from($(this).find(".line"), {
        xPercent: 100,
        scale: 0.5,
        delay: globalIntroDelay + elDelay,
        duration: 1.75,
        ease: "expo.out",
        stagger: {
          each: 0.125
        }
      });
    });
    $("[data-anim-load=scale]").each(function() {
      const elDelay = $(this).attr("data-anim-load-delay") || 0;
      gsap.from($(this), {
        scale: 1.25,
        delay: elDelay,
        duration: 3,
        ease: "power3.out"
      });
    });
    $("[data-anim-load=slide-up-fade]").each(function() {
      const elDelay = $(this).attr("data-anim-load-delay") || 0;
      gsap.from($(this), {
        yPercent: 50,
        opacity: 0,
        delay: globalIntroDelay + elDelay,
        duration: 2,
        ease: "expo.out"
      });
    });
    $("[data-anim-load=children-slide-up-fade]").each(function() {
      const elDelay = $(this).attr("data-anim-load-delay") || 0;
      gsap.from($(this).children(), {
        yPercent: 50,
        opacity: 0,
        delay: globalIntroDelay + elDelay,
        duration: 2,
        ease: "expo.out",
        stagger: {
          each: 0.125
        }
      });
    });
    $("[data-anim-load=mask]").each(function() {
      const elDelay = parseFloat($(this).attr("data-anim-load-delay")) || 6;
      gsap.fromTo(
        $(this),
        {
          clipPath: "polygon(0% 0%, 100% 0%, 100% 100%, 0% 100%)"
        },
        {
          delay: globalIntroDelay + elDelay,
          clipPath: "polygon(0% 0%, 0% 0%, 0% 100%, 0% 100%)",
          duration: 1.75,
          ease: "expo.inOut"
        }
      );
    });
    $("[data-anim-load=nav-logo]").each(function() {
      const elDelay = parseFloat($(this).attr("data-anim-load-delay")) || 0;
      gsap.from($(this).find(".g_logo_split_svg"), {
        xPercent: 125,
        delay: globalIntroDelay + elDelay,
        ease: "expo.out",
        duration: 1.5,
        stagger: {
          each: 0.05
        }
      });
    });
    $("[data-anim-load=nav-button]").each(function() {
      const elDelay = parseFloat($(this).attr("data-anim-load-delay")) || 0;
      gsap.fromTo(
        $(this),
        {
          clipPath: "polygon(0% 0%, 100% 0%, 100% 0%, 0% 0%)"
        },
        {
          clipPath: "polygon(0% 0%, 100% 0%, 100% 100%, 0% 100%)",
          delay: globalIntroDelay + elDelay,
          ease: "expo.out",
          duration: 1.5
        }
      );
    });
  }
  function initScrollAnimations() {
    $("[data-anim-scroll=chars]").each(function() {
      gsap.from($(this).find(".char"), {
        xPercent: 100,
        duration: 1.5,
        ease: "expo.out",
        stagger: {
          each: 0.125
        },
        scrollTrigger: {
          trigger: $(this),
          start: "top bottom",
          end: "top 90%",
          toggleActions: "none play none reset"
        }
      });
    });
    $("[data-anim-scroll=words]").each(function() {
      gsap.from($(this).find(".word"), {
        yPercent: 115,
        // xPercent: 25,
        duration: 2,
        ease: "expo.out",
        stagger: {
          each: 0.05
        },
        scrollTrigger: {
          trigger: $(this),
          start: "top bottom",
          end: "top 90%",
          toggleActions: "none play none reset"
        }
      });
    });
    $("[data-anim-scroll=lines]").each(function() {
      gsap.from($(this).find(".line"), {
        delay: 0.125,
        yPercent: 100,
        // xPercent: 25,
        // scale: 0.5,
        duration: 2,
        ease: "expo.out",
        stagger: {
          each: 0.1
        },
        scrollTrigger: {
          trigger: $(this),
          start: "top bottom",
          end: "top 90%",
          toggleActions: "none play none reset"
        }
      });
    });
    $("[data-anim-scroll=fade]").each(function() {
      gsap.from($(this), {
        opacity: 0,
        duration: 1.66,
        scrollTrigger: {
          trigger: $(this),
          start: "top bottom",
          end: "top 90%",
          toggleActions: "none play none reset"
        }
      });
    });
    $("[data-anim-scroll=scrub-scale]").each(function() {
      const scaleFrom = $(this).attr("data-scale-from") || 1.25;
      const inner = $(this).find("[data-scrub-scale-inner]");
      const innerScaleFrom = inner.attr("data-scale-from") || 0.8;
      let tl = gsap.timeline({
        scrollTrigger: {
          trigger: $(this),
          start: "top bottom",
          end: "bottom bottom",
          scrub: true
        }
      });
      tl.from($(this), {
        scale: scaleFrom,
        ease: "power1.out",
        duration: 1
      });
      if (inner.length) {
        tl.from(
          inner,
          {
            scale: innerScaleFrom,
            ease: "power1.out",
            duration: 1.25
          },
          "<"
        );
      }
    });
    $("[data-anim-scroll=mask-diagonal]").each(function() {
      gsap.fromTo(
        $(this),
        {
          clipPath: "polygon(-1% -1%, 0% 0%, 0% 0%)"
        },
        {
          clipPath: "polygon(-1% -1%, 250% 0%, 0% 250%)",
          duration: 3.5,
          ease: "power1.inOut",
          scrollTrigger: {
            trigger: $(this),
            start: "top bottom",
            end: "top 90%",
            toggleActions: "none play none reset"
          }
        }
      );
    });
    $("[data-anim-scroll=scaleX]").each(function() {
      const innerTarget = $(this).find("[data-anim-target=scaleX]");
      const target = innerTarget.length ? innerTarget : $(this);
      gsap.from(target, {
        scaleX: 0,
        duration: 2,
        ease: "power1.inOut",
        stagger: {
          each: 0.1
        },
        scrollTrigger: {
          trigger: $(this),
          start: "top bottom",
          end: "top 90%",
          toggleActions: "none play none reset"
        }
      });
    });
    $("[data-anim-scroll=children-fade]").each(function() {
      const children = $(this).children();
      const childTarget = $(this).find("[data-anim-target]");
      const animTarget = childTarget.length ? childTarget : children;
      gsap.from(animTarget, {
        opacity: 0,
        duration: 1.66,
        yPercent: 15,
        ease: "power3.out",
        stagger: {
          each: 0.125
        },
        scrollTrigger: {
          trigger: $(this),
          start: "top bottom",
          end: "top 90%",
          toggleActions: "none play none reset"
        }
      });
    });
    $("[data-anim-scroll=children-scale]").each(function() {
      const children = $(this).children();
      const childTarget = $(this).find("[data-anim-target]");
      const animTarget = childTarget.length ? childTarget : children;
      gsap.from(animTarget, {
        scale: 0,
        duration: 1.66,
        yPercent: 15,
        ease: "power3.out",
        stagger: {
          each: 0.125
        },
        scrollTrigger: {
          trigger: $(this),
          start: "top bottom",
          end: "top 90%",
          toggleActions: "none play none reset"
        }
      });
    });
  }
  function initMarqueeScrollDirection() {
    document.querySelectorAll("[data-marquee-scroll-direction-target]").forEach((marquee) => {
      const marqueeContent = marquee.querySelector(
        "[data-marquee-collection-target]"
      );
      const marqueeScroll = marquee.querySelector(
        "[data-marquee-scroll-target]"
      );
      if (!marqueeContent || !marqueeScroll) return;
      const {
        marqueeSpeed: speed,
        marqueeDirection: direction,
        marqueeDuplicate: duplicate,
        marqueeScrollSpeed: scrollSpeed
      } = marquee.dataset;
      const marqueeSpeedAttr = parseFloat(speed);
      const marqueeDirectionAttr = direction === "right" ? 1 : -1;
      const duplicateAmount = parseInt(duplicate || 0);
      const scrollSpeedAttr = parseFloat(scrollSpeed);
      const speedMultiplier = window.innerWidth < 479 ? 0.25 : window.innerWidth < 991 ? 0.5 : 1;
      let marqueeSpeed = marqueeSpeedAttr * (marqueeContent.offsetWidth / window.innerWidth) * speedMultiplier;
      marqueeScroll.style.marginLeft = `${scrollSpeedAttr * -1}%`;
      marqueeScroll.style.width = `${scrollSpeedAttr * 2 + 100}%`;
      if (duplicateAmount > 0) {
        const fragment = document.createDocumentFragment();
        for (let i = 0; i < duplicateAmount; i++) {
          fragment.appendChild(marqueeContent.cloneNode(true));
        }
        marqueeScroll.appendChild(fragment);
      }
      const marqueeItems = marquee.querySelectorAll(
        "[data-marquee-collection-target]"
      );
      const animation = gsap.to(marqueeItems, {
        xPercent: -100,
        // Move completely out of view
        repeat: -1,
        duration: marqueeSpeed,
        ease: "linear"
      }).totalProgress(0.5);
      gsap.set(marqueeItems, {
        xPercent: marqueeDirectionAttr === 1 ? 100 : -100
      });
      animation.timeScale(marqueeDirectionAttr);
      animation.play();
      marquee.setAttribute("data-marquee-status", "normal");
      ScrollTrigger.create({
        trigger: marquee,
        start: "top bottom",
        end: "bottom top",
        onUpdate: (self) => {
          const isInverted = self.direction === 1;
          const currentDirection = isInverted ? -marqueeDirectionAttr : marqueeDirectionAttr;
          animation.timeScale(currentDirection);
          marquee.setAttribute(
            "data-marquee-status",
            isInverted ? "normal" : "inverted"
          );
        }
      });
      const tl = gsap.timeline({
        scrollTrigger: {
          trigger: marquee,
          start: "0% 100%",
          end: "100% 0%",
          scrub: 0
        }
      });
      const scrollStart = marqueeDirectionAttr === -1 ? scrollSpeedAttr : -scrollSpeedAttr;
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
      if (isNavOpen) return;
      const themeSections = document.querySelectorAll("[data-theme-section]");
      themeSections.forEach(function(themeSection) {
        const rect = themeSection.getBoundingClientRect();
        const themeSectionTop = rect.top;
        const themeSectionBottom = rect.bottom;
        if (themeSectionTop <= themeObserverOffset && themeSectionBottom >= themeObserverOffset) {
          const themeSectionActive = themeSection.getAttribute("data-theme-section");
          document.querySelectorAll("[data-theme-nav]").forEach(function(elem) {
            if (elem.getAttribute("data-theme-nav") !== themeSectionActive) {
              elem.setAttribute("data-theme-nav", themeSectionActive);
            }
          });
          const bgSectionActive = themeSection.getAttribute("data-bg-section");
          document.querySelectorAll("[data-bg-nav]").forEach(function(elem) {
            if (elem.getAttribute("data-bg-nav") !== bgSectionActive) {
              elem.setAttribute("data-bg-nav", bgSectionActive);
            }
          });
        }
      });
    }
    function setNavAttributes(themeValue, bgValue) {
      document.querySelectorAll("[data-theme-nav]").forEach(function(elem) {
        elem.setAttribute("data-theme-nav", themeValue);
      });
      document.querySelectorAll("[data-bg-nav]").forEach(function(elem) {
        elem.setAttribute("data-bg-nav", bgValue);
      });
    }
    function handleNavToggle() {
      isNavOpen = !isNavOpen;
      if (isNavOpen) {
        setNavAttributes("dark", "transparent");
      } else {
        checkThemeSection();
      }
    }
    function startThemeCheck() {
      document.addEventListener("scroll", checkThemeSection);
    }
    function bindNavToggle() {
      document.querySelectorAll("[data-navigation-toggle]").forEach(function(toggle) {
        toggle.addEventListener("click", handleNavToggle);
      });
    }
    checkThemeSection();
    startThemeCheck();
    bindNavToggle();
  }
  function initMouseMove() {
    var MAX_REM = 10;
    var maxPx = MAX_REM * parseFloat(getComputedStyle(document.documentElement).fontSize);
    if ("ontouchstart" in window) return;
    var targets = [];
    $("[data-mouse-move-strength]").each(function() {
      var el = $(this)[0];
      var strength = parseFloat($(this).attr("data-mouse-move-strength")) || 0;
      targets.push({
        strength,
        xTo: gsap.quickTo(el, "x", { duration: 1.5, ease: "power3" }),
        yTo: gsap.quickTo(el, "y", { duration: 1.5, ease: "power3" })
      });
    });
    if (!targets.length) return;
    $(window).on("mousemove", function(e) {
      var nx = (e.clientX / window.innerWidth - 0.5) * 2;
      var ny = (e.clientY / window.innerHeight - 0.5) * 2;
      targets.forEach(function(t) {
        t.xTo(nx * -maxPx * t.strength);
        t.yTo(ny * -maxPx * t.strength);
      });
    });
  }
  function initBoldFullScreenNavigation() {
    document.querySelectorAll('[data-navigation-toggle="toggle"]').forEach((toggleBtn) => {
      toggleBtn.addEventListener("click", () => {
        const navStatusEl = document.querySelector("[data-navigation-status]");
        if (!navStatusEl) return;
        if (navStatusEl.getAttribute("data-navigation-status") === "not-active") {
          navStatusEl.setAttribute("data-navigation-status", "active");
          lenis.stop();
        } else {
          navStatusEl.setAttribute("data-navigation-status", "not-active");
          lenis.start();
        }
      });
    });
    document.querySelectorAll('[data-navigation-toggle="close"]').forEach((closeBtn) => {
      closeBtn.addEventListener("click", () => {
        const navStatusEl = document.querySelector("[data-navigation-status]");
        if (!navStatusEl) return;
        navStatusEl.setAttribute("data-navigation-status", "not-active");
      });
    });
    document.addEventListener("keydown", (e) => {
      if (e.keyCode === 27) {
        const navStatusEl = document.querySelector("[data-navigation-status]");
        if (!navStatusEl) return;
        if (navStatusEl.getAttribute("data-navigation-status") === "active") {
          navStatusEl.setAttribute("data-navigation-status", "not-active");
        }
      }
    });
    $("[data-navbar]").each(function() {
      const nav = $(this);
      const showAnim = gsap.from(nav, {
        yPercent: -100,
        paused: true,
        duration: 0.5,
        ease: "power1.out",
        easeReverse: true
      }).progress(1);
      ScrollTrigger.create({
        start: "top top",
        end: "max",
        onUpdate: (self) => {
          self.direction === -1 ? showAnim.play() : showAnim.reverse();
        }
      });
    });
  }
  function initFooterParallax() {
    document.querySelectorAll("[data-footer-parallax]").forEach((el) => {
      const tl = gsap.timeline({
        scrollTrigger: {
          trigger: el,
          start: "clamp(top bottom)",
          end: "clamp(top top)",
          scrub: true
        }
      });
      const inner = el.querySelector("[data-footer-parallax-inner]");
      const dark = el.querySelector("[data-footer-parallax-dark]");
      if (inner) {
        tl.from(inner, {
          yPercent: -25,
          ease: "linear"
        });
      }
      if (dark) {
        tl.to(
          dark,
          {
            opacity: 0,
            ease: "linear"
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
      if (wrap.dataset.sequenceInit === "true") return;
      wrap.dataset.sequenceInit = "true";
      const element = wrap.querySelector("[data-sequence-element]");
      const canvas = element && element.querySelector("[data-sequence-canvas]");
      if (!element || !canvas) return;
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
      let lastProgress = 0;
      const ctx = canvas.getContext("2d");
      function resizeCanvas() {
        const width = element.clientWidth;
        const height = element.clientHeight;
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
      const loaded = /* @__PURE__ */ new Map();
      const inflight = /* @__PURE__ */ new Set();
      let resizeTimer;
      let lastDrawnIndex = -1;
      let rafId = null;
      const ac = new AbortController();
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
            lastDrawnIndex = -1;
            if (loaded.size) render(lastProgress);
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
          img.decode().catch(() => {
          }).then(() => {
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
            url: getUrl(i)
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
            if (m - a > 1) queue.push([a, m]);
            if (b - m > 1) queue.push([m, b]);
            drainQueue();
          });
        }
      }
      function startLoading() {
        loadFrame(indexStart, () => {
          lastDrawnIndex = -1;
          drawImageAt(indexStart);
          ScrollTrigger.refresh();
          queue.push([indexStart, lastIndex]);
          drainQueue();
        });
        loadFrame(lastIndex);
      }
      function findNearestLoaded(i) {
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
        if (index === lastDrawnIndex) return;
        let target = index;
        if (!loaded.has(index)) {
          const nearest = findNearestLoaded(index);
          if (nearest === null) return;
          target = nearest;
        }
        if (target === lastDrawnIndex) return;
        drawImageAt(target);
      }
      function onScrollUpdate(self) {
        lastProgress = self.progress;
        if (rafId) return;
        rafId = requestAnimationFrame(() => {
          rafId = null;
          render(lastProgress);
        });
      }
      if (reduceMotion) {
        if (staticSrc) {
          const staticImage = new Image();
          staticImage.src = staticSrc;
          staticImage.onload = () => {
            drawCover(staticImage);
          };
          staticImage.onerror = () => {
          };
          instances.push({ wrap, destroy: () => ac.abort() });
          return;
        }
        loadFrame(indexStart, () => {
          drawImageAt(indexStart);
        });
        instances.push({ wrap, destroy: () => ac.abort() });
        return;
      }
      startLoading();
      const st = ScrollTrigger.create({
        trigger: wrap,
        start: startTrigger,
        end: endTrigger,
        scrub: true,
        onUpdate: onScrollUpdate
      });
      lastProgress = st.progress || 0;
      render(lastProgress);
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
        }
      });
    });
    return instances;
  }
  function initAccordionCSS() {
    document.querySelectorAll("[data-accordion-css-init]").forEach((accordion) => {
      const closeSiblings = accordion.getAttribute("data-accordion-close-siblings") === "true";
      accordion.addEventListener("click", (event) => {
        const toggle = event.target.closest("[data-accordion-toggle]");
        if (!toggle) return;
        const singleAccordion = toggle.closest("[data-accordion-status]");
        if (!singleAccordion) return;
        const isActive = singleAccordion.getAttribute("data-accordion-status") === "active";
        singleAccordion.setAttribute(
          "data-accordion-status",
          isActive ? "not-active" : "active"
        );
        if (closeSiblings && !isActive) {
          accordion.querySelectorAll('[data-accordion-status="active"]').forEach((sibling) => {
            if (sibling !== singleAccordion)
              sibling.setAttribute("data-accordion-status", "not-active");
          });
        }
      });
    });
  }
  function initBasicFlip() {
    $("[data-flip-group]").each(function() {
      const group = $(this);
      const el = group.find("[data-flip-element]");
      const id = el.attr("data-flip-element");
      const destination = group.find(`[data-flip-destination="${id}"]`);
      if (!el.length || !destination.length) return;
      const state = Flip.getState(el[0]);
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
          scrub: 0.5
        }
      });
      tl.add(
        Flip.from(state, {
          // duration: 0.6,
          absolute: true,
          ease: "power1.inOut"
        })
      );
    });
  }
  function initWorkViews() {
    const groups = document.querySelectorAll("[data-work-group]");
    if (!groups.length) return;
    groups.forEach(function(group) {
      if (group.dataset.jsInit === "true") return;
      group.dataset.jsInit = "true";
      const inner = group.querySelector("[data-work-group-inner]");
      const buttons = group.querySelectorAll("[data-work-button]");
      const gallery = group.querySelector("[data-work-gallery]");
      const list = group.querySelector("[data-work-list]");
      if (!inner || !gallery || !list) return;
      let currentState = "gallery";
      let activeTl = null;
      group.setAttribute("data-work-state", "gallery");
      gsap.set(list, {
        position: "absolute",
        xPercent: 50,
        scale: 0.25,
        opacity: 0
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
        gsap.set(inner, { height: inner.offsetHeight });
        gsap.set(incoming, {
          position: "absolute",
          left: 0,
          top: 0,
          right: 0,
          xPercent: inX,
          scale: 0.25,
          opacity: 0
        });
        activeTl = gsap.timeline({
          onComplete: function() {
            gsap.set(incoming, {
              position: "relative"
            });
            gsap.set(inner, { clearProps: "height" });
            activeTl = null;
            ScrollTrigger.refresh();
            gsap.to(incoming.querySelectorAll("[done-deal-image-wrap]"), {
              clipPath: "polygon(0% 0%, 100% 0%, 100% 100%, 0% 100%)",
              duration: 1,
              ease: "expo.out",
              stagger: {
                each: 0.1
              },
              onComplete: () => {
                gsap.set("[done-deal-image-wrap]", {
                  backgroundColor: "transparent"
                });
              }
            });
          }
        });
        activeTl.to(outgoing, {
          xPercent: outX,
          scale: 0.25,
          opacity: 0,
          duration: 1,
          ease: "expo.inOut",
          onComplete: () => {
            gsap.set(outgoing, {
              position: "absolute"
            });
          }
        });
        activeTl.set(
          incoming.querySelectorAll("[done-deal-image-wrap]"),
          {
            clipPath: "polygon(0% 100%, 100% 100%, 100% 100%, 0% 100%)"
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
            ease: "expo.inOut"
          },
          "<"
        );
      }
      buttons.forEach(function(button) {
        button.addEventListener("click", function() {
          const target = button.getAttribute("data-work-button");
          switchView(target);
        });
      });
    });
  }
  function initPageTransition() {
    const validLinks = Array.from(document.querySelectorAll("a")).filter(
      (link) => {
        const href = link.getAttribute("href") || "";
        const hostname = new URL(link.href, window.location.origin).hostname;
        return hostname === window.location.hostname && // Same domain
        !href.startsWith("#") && // Not an anchor link
        link.getAttribute("target") !== "_blank" && // Not opening in a new tab
        !link.hasAttribute("data-transition-prevent");
      }
    );
    validLinks.forEach((link) => {
      link.addEventListener("click", (event) => {
        event.preventDefault();
        const destination = link.href;
        $("body").addClass("is-transitioning");
        gsap.delayedCall(1, function() {
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
    if (typeof Smooothy === "undefined" || typeof $ === "undefined" || typeof gsap === "undefined")
      return;
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
        links.forEach(function(link) {
          if (!link.parentElement) return;
          link.style.pointerEvents = "none";
          let startX = 0;
          let startY = 0;
          let startTime = 0;
          let isDragging = false;
          const onDown = function(e) {
            const pt = e.touches ? e.touches[0] : e;
            startX = pt.clientX;
            startY = pt.clientY;
            startTime = Date.now();
            isDragging = false;
          };
          const onMove = function(e) {
            if (!startTime) return;
            const pt = e.touches ? e.touches[0] : e;
            if (Math.abs(pt.clientX - startX) > 5 || Math.abs(pt.clientY - startY) > 5) {
              isDragging = true;
            }
          };
          const onUp = function() {
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
        if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
          e.preventDefault();
          this.target -= e.deltaX * 5e-3;
        }
      }
      destroy() {
        window.removeEventListener("keydown", this._onKeydown);
        this.wrapper.removeEventListener("wheel", this._onWheel);
        gsap.ticker.remove(this._tickerUpdate);
        if (super.destroy) super.destroy();
      }
    }
    $('[data-smooothy="featured-projects"]').each(function() {
      if (this.dataset.jsInit === "true") return;
      this.dataset.jsInit = "true";
      const wrapper = this;
      const enableSlideY = wrapper.hasAttribute("data-smooothy-y");
      const slides = wrapper.children;
      const xParallaxAmount = -10;
      new SmooothySlider(wrapper, {
        infinite: false,
        snap: true,
        scrollInput: false,
        // we handle wheel input ourselves (horizontal-only)
        bounceLimit: 0,
        setOffset: function(viewport) {
          return viewport.wrapperWidth;
        },
        onUpdate: function() {
          const wrapperRect = wrapper.getBoundingClientRect();
          const wrapperCenter = wrapperRect.left + wrapperRect.width / 2;
          const halfWidth = wrapperRect.width / 2;
          for (let i = 0; i < slides.length; i++) {
            const slide = slides[i];
            if (!slide) continue;
            const slideRect = slide.getBoundingClientRect();
            const slideCenter = slideRect.left + slideRect.width / 2;
            let v = (slideCenter - wrapperCenter) / halfWidth;
            if (v < -1) v = -1;
            else if (v > 1) v = 1;
            const img = slide.querySelector("[data-p]");
            if (img) {
              img.style.transform = "translate3d(" + v * xParallaxAmount + "%,0,0)";
            }
            if (enableSlideY) {
              const inner = slide.querySelector("[data-smooothy-inner]");
              if (inner) {
                const y = Math.abs(v) * 20 - 10;
                inner.style.transform = "translate3d(0," + y + "%,0)";
              }
            }
          }
        }
      });
    });
  }
  function initServicesScroll() {
    $("[data-services-scroll-section]").each(function() {
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
          scrub: true
        }
      });
      preTl.from(imagesWrap, {
        scale: 1.25
      });
      let startTl = gsap.timeline({
        scrollTrigger: {
          trigger: startAnchor,
          start: "bottom 125%",
          end: "bottom top",
          scrub: true
        }
      });
      startTl.to(imagesWrap, {
        width: "50%",
        ease: "power1.inOut"
      });
      let trackTl = gsap.timeline({
        scrollTrigger: {
          trigger: track,
          start: "top 50%",
          end: "bottom bottom",
          scrub: true
        }
      });
      imageWraps.each(function() {
        if ($(this).is(imageWraps.eq(0))) {
          preTl.from(
            $(this),
            {
              scale: 1.25
            },
            0
          );
        } else {
          trackTl.fromTo(
            $(this),
            {
              clipPath: "polygon(0% 100%, 100% 100%, 100% 100%, 0% 100%)",
              scale: 1.25
            },
            {
              clipPath: "polygon(0% 0%, 100% 0%, 100% 100%, 0% 100%)",
              ease: "power2.inOut",
              scale: 1
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
          scrub: true
        }
      });
      overlays.each(function() {
        if ($(this).is(overlays.last())) return;
        overlaysTl.to($(this), {
          opacity: 0.75,
          ease: "power1.in"
        });
      });
      anchors.each(function(index) {
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
            toggleActions: "play reverse play reverse"
          },
          defaults: {
            easeReverse: true,
            ease: "expo.out"
          }
        });
        if (index > 0) {
          const prevTextWrap = textWraps.eq(index - 1);
          textTl.to(prevTextWrap, {
            opacity: 0,
            duration: 0.25
          });
        }
        textTl.from(
          textHeading.find(".word"),
          {
            yPercent: 125,
            duration: 1.25,
            ease: "expo.out",
            stagger: {
              each: 0.125
            }
          },
          index > 0 ? "<.25" : void 0
        );
        textTl.from(
          textSubheading.find(".line"),
          {
            yPercent: 100,
            duration: 1,
            ease: "expo.out",
            stagger: { each: 0.0125 }
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
            stagger: { each: 0.025 }
          },
          "<.1"
        );
      });
    });
  }
  function initPreloader() {
    sessionStorage.setItem("intro-shown", "1");
    $("[data-preloader-wrap]").each(function() {
      const wrap = $(this);
      const logo = wrap.find("[data-preloader-logo]");
      const mid = wrap.find("[data-preloader-mid]");
      const logoSVGs = logo.find(".g_logo_split_svg");
      const barWrap = wrap.find("[data-preloader-bar-wrap]");
      const bar = wrap.find("[data-preloader-bar]");
      let introTl = gsap.timeline({
        delay: 0.5,
        onStart: () => {
          lenis.stop();
        },
        onComplete: () => {
          lenis.start();
          gsap.set(wrap, {
            visibility: "hidden"
          });
        }
      });
      introTl.fromTo(logo, {
        x: 0,
        scale: 2
      }, {
        x: "6vw",
        scale: 1,
        duration: 2.5,
        ease: "expo.out"
      });
      introTl.from(
        logoSVGs,
        {
          xPercent: 125,
          ease: "expo.out",
          duration: 1.5,
          stagger: {
            each: 0.1
          }
        },
        "<"
      );
      introTl.to(logo, {
        x: 0,
        duration: 2,
        ease: "expo.inOut"
      }, "<1");
      introTl.from(barWrap, {
        scaleX: 0,
        duration: 2,
        ease: "expo.inOut"
      }, "<");
      introTl.to(bar, {
        scaleX: 1,
        duration: 2.5,
        ease: CustomEase.create("custom", "M0,0 C0,0 0.049,0.023 0.063,0.036 0.078,0.05 0.105,0.04 0.12,0.055 0.133,0.068 0.213,0.07 0.227,0.083 0.242,0.097 0.3,0.133 0.315,0.147 0.328,0.16 0.342,0.198 0.357,0.213 0.371,0.226 0.361,0.299 0.376,0.314 0.389,0.327 0.369,0.346 0.383,0.359 0.398,0.373 0.533,0.375 0.558,0.376 0.673,0.38 0.759,0.506 0.846,0.507 1.007,0.507 1,1 1,1 ")
      }, "<1");
      introTl.to(
        logo,
        {
          xPercent: -300,
          ease: "expo.in",
          duration: 2.5
        },
        "<1.75"
      );
      introTl.to(
        barWrap,
        {
          xPercent: -300,
          ease: "expo.in",
          duration: 2.5
        },
        "<"
      );
      introTl.to(
        logoSVGs,
        {
          xPercent: -125,
          ease: "expo.in",
          duration: 1.5,
          stagger: {
            each: 0.05
          }
        },
        "<"
      );
      introTl.to(barWrap, {
        scaleX: 0,
        ease: "expo.in",
        duration: 1.5
      }, "<.25");
    });
  }
  function assignLayoutIndexes() {
    $("[data-work-gallery]").each(function() {
      const section = $(this);
      const cmsList = section.find("[data-work-gallery-list]");
      const items = cmsList.find('.w-dyn-item:not([style*="display: none"])');
      items.each(function(i) {
        $(this).attr("data-layout", i % 6 + 1);
      });
    });
  }
  function initHomeHeroScroll() {
    $("[data-home-hero]").each(function() {
      const section = $(this);
      const headingRio = section.find("[data-heading=rio]");
      const headingProperty = section.find("[data-heading=property]");
      const headingKnows = section.find("[data-heading=knows]");
      const headingCapeTown = section.find("[data-heading='cape town']");
      const paragraphLeft = section.find("[data-paragraph=left]");
      const paragraphRight = section.find("[data-paragraph=right]");
      const overlay = section.find("[data-home-hero-overlay]");
      let tl = gsap.timeline({
        scrollTrigger: {
          trigger: section,
          start: "top top",
          end: "bottom center",
          scrub: true
        }
      });
      tl.to(headingRio, {
        xPercent: -175
      });
      tl.to(
        headingProperty,
        {
          xPercent: -125
        },
        "<"
      );
      tl.to(
        headingKnows,
        {
          xPercent: 150
        },
        "<"
      );
      tl.to(
        headingCapeTown,
        {
          xPercent: 125
        },
        "<"
      );
      tl.to(
        paragraphLeft,
        {
          xPercent: -125
        },
        "<"
      );
      tl.to(
        paragraphRight,
        {
          xPercent: 300
        },
        "<"
      );
      tl.to(overlay, {
        opacity: 0,
        ease: "power2.inOut"
      }, "<");
    });
  }
  document.addEventListener("DOMContentLoaded", function() {
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
    initHomeHeroScroll();
  });
})();
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJzb3VyY2VzIjpbIi9fX2VudHJ5X18uanMiXSwic291cmNlc0NvbnRlbnQiOlsiLy8gc2NyaXB0LmpzXG5nc2FwLnJlZ2lzdGVyUGx1Z2luKEluZXJ0aWFQbHVnaW4pO1xuZ3NhcC5yZWdpc3RlclBsdWdpbihTcGxpdFRleHQpO1xuZ3NhcC5yZWdpc3RlclBsdWdpbihTY3JvbGxUcmlnZ2VyKTtcbmdzYXAucmVnaXN0ZXJQbHVnaW4oRmxpcCk7XG5nc2FwLnJlZ2lzdGVyUGx1Z2luKEN1c3RvbUVhc2UpIFxuXG5sZXQgbGVuaXM7XG5cbmZ1bmN0aW9uIGluaXRMZW5pcygpIHtcbiAgLy8gbGVuaXMgPSBuZXcgTGVuaXMoe1xuICAvLyAgIGR1cmF0aW9uOiAxLjI1LFxuICAvLyAgIHdoZWVsTXVsdGlwbGllcjogMC43NSxcbiAgLy8gICAvLyBlYXNpbmc6ICh0KSA9PiBNYXRoLm1pbigxLCAxLjAwMSAtIE1hdGgucG93KDIsIC0xMCAqIHQpKSxcbiAgLy8gfSk7XG4gIC8vIGxlbmlzLm9uKFwic2Nyb2xsXCIsIFNjcm9sbFRyaWdnZXIudXBkYXRlKTtcbiAgLy8gZ3NhcC50aWNrZXIuYWRkKCh0aW1lKSA9PiB7XG4gIC8vICAgbGVuaXMucmFmKHRpbWUgKiAxMDAwKTtcbiAgLy8gfSk7XG4gIC8vIGdzYXAudGlja2VyLmxhZ1Ntb290aGluZygwKTtcblxuICAvLyBsZW5pcy5zY3JvbGxUbygwLCB7XG4gIC8vICAgaW1tZWRpYXRlOiB0cnVlLFxuICAvLyAgIGxvY2s6IHRydWUsXG4gIC8vICAgZm9yY2U6IHRydWUsXG4gIC8vIH0pO1xuXG5cbiAgIGxlbmlzID0gbmV3IExlbmlzKHtcbiAgICAgd2hlZWxNdWx0aXBsaWVyOiAwLjc1LFxuICAgICAgIGR1cmF0aW9uOiAxLjI1LFxuICB9KTtcblxuICBmdW5jdGlvbiByYWYodGltZSkgeyBsZW5pcy5yYWYodGltZSk7IHJlcXVlc3RBbmltYXRpb25GcmFtZShyYWYpOyB9XG4gIHJlcXVlc3RBbmltYXRpb25GcmFtZShyYWYpO1xuXG4gIC8vIC0tLSBkcmFnLXRvLXNjcm9sbCAtLS1cbiAgY29uc3QgU0VOU0lUSVZJVFkgPSAxLjI1OyAgICAgLy8gMToxIHBpeGVsIG1hcHBpbmc7ID4xID0gZmFzdGVyIGRyYWdcbiAgY29uc3QgRFJBR19USFJFU0hPTEQgPSA2OyAgICAvLyBtYXRjaGVzIGNoYW1wJ3MgNnB4IGNsaWNrL2RyYWcgc3BsaXRcbiAgY29uc3QgVkVMT0NJVFlfREVDQVkgPSAwLjkyOyAvLyBleHBvbmVudGlhbCBzbW9vdGhpbmcgZm9yIHJlbGVhc2UgdmVsb2NpdHlcbiAgY29uc3QgVEhST1dfTVVMVElQTElFUiA9IDY7IC8vIGhvdyBmYXIgdGhlIGluZXJ0aWEgXCJ0aHJvd1wiIGV4dGVuZHNcbiAgY29uc3QgTUlOX0ZMSU5HID0gMC40OyAgICAgICAvLyBweC9tcyBiZWxvdyB3aGljaCB3ZSBkb24ndCBmbGluZ1xuXG4gIGxldCBpc0Rvd24gPSBmYWxzZSwgaXNEcmFnZ2luZyA9IGZhbHNlO1xuICBsZXQgc3RhcnRZID0gMCwgc3RhcnRTY3JvbGwgPSAwO1xuICBsZXQgbGFzdFkgPSAwLCBsYXN0VCA9IDAsIHZZID0gMDtcblxuICB3aW5kb3cuYWRkRXZlbnRMaXN0ZW5lcigncG9pbnRlcmRvd24nLCAoZSkgPT4ge1xuICAgIC8vIGlnbm9yZSByaWdodC1jbGljaywgYnV0dG9ucywgaW5wdXRzLCBsaW5rcyBpZiB5b3UgbGlrZVxuICAgIGlmIChlLmJ1dHRvbiAhPT0gMCkgcmV0dXJuO1xuICAgIGlzRG93biA9IHRydWU7IGlzRHJhZ2dpbmcgPSBmYWxzZTtcbiAgICBzdGFydFkgPSBsYXN0WSA9IGUuY2xpZW50WTtcbiAgICBsYXN0VCA9IHBlcmZvcm1hbmNlLm5vdygpO1xuICAgIHN0YXJ0U2Nyb2xsID0gbGVuaXMuc2Nyb2xsOyAgICAgICAvLyBMZW5pcyBleHBvc2VzIHRoZSBzbW9vdGhlZCBzY3JvbGxcbiAgICB2WSA9IDA7XG4gICAgbGVuaXMuc3RvcCgpOyAgICAgICAgICAgICAgICAgICAgIC8vIGZyZWV6ZSBMZW5pcyB3aGlsZSB3ZSBkcml2ZSBpdCBtYW51YWxseVxuICB9KTtcblxud2luZG93LmFkZEV2ZW50TGlzdGVuZXIoJ3BvaW50ZXJtb3ZlJywgKGUpID0+IHtcbiAgaWYgKCFpc0Rvd24pIHJldHVybjtcbiAgY29uc3QgZHkgPSBlLmNsaWVudFkgLSBzdGFydFk7XG4gIGlmICghaXNEcmFnZ2luZyAmJiBNYXRoLmFicyhkeSkgPiBEUkFHX1RIUkVTSE9MRCkge1xuICAgIGlzRHJhZ2dpbmcgPSB0cnVlO1xuICAgIGRvY3VtZW50LmRvY3VtZW50RWxlbWVudC5zdHlsZS51c2VyU2VsZWN0ID0gJ25vbmUnO1xuICB9XG4gIGlmICghaXNEcmFnZ2luZykgcmV0dXJuO1xuXG4gIC8vIHZlbG9jaXR5IHRyYWNraW5nICh1bmNoYW5nZWQpXG4gIGNvbnN0IG5vdyA9IHBlcmZvcm1hbmNlLm5vdygpO1xuICBjb25zdCBpbnN0ViA9IChlLmNsaWVudFkgLSBsYXN0WSkgLyBNYXRoLm1heCgxLCBub3cgLSBsYXN0VCk7XG4gIHZZID0gdlkgKiBWRUxPQ0lUWV9ERUNBWSArIGluc3RWICogKDEgLSBWRUxPQ0lUWV9ERUNBWSk7XG4gIGxhc3RZID0gZS5jbGllbnRZOyBsYXN0VCA9IG5vdztcblxuICAvLyBVcGRhdGUgdGhlIFRBUkdFVCBvbmx5IOKAlCBsZXQgTGVuaXMgbGVycCB0b3dhcmQgaXQuXG4gIGNvbnN0IHRhcmdldCA9IHN0YXJ0U2Nyb2xsIC0gZHkgKiBTRU5TSVRJVklUWTtcbiAgbGVuaXMuc2Nyb2xsVG8odGFyZ2V0LCB7IGZvcmNlOiB0cnVlLCBsb2NrOiB0cnVlIH0pOyAgIC8vIG5vIGBpbW1lZGlhdGVgXG59KTtcblxuICBmdW5jdGlvbiBlbmREcmFnKCkge1xuICAgIGlmICghaXNEb3duKSByZXR1cm47XG4gICAgaXNEb3duID0gZmFsc2U7XG4gICAgZG9jdW1lbnQuZG9jdW1lbnRFbGVtZW50LnN0eWxlLnVzZXJTZWxlY3QgPSAnJztcbiAgICBsZW5pcy5zdGFydCgpOyAgICAgICAgICAgICAgICAgICAgLy8gaGFuZCBjb250cm9sIGJhY2sgdG8gTGVuaXNcblxuICAgIGlmICghaXNEcmFnZ2luZykgcmV0dXJuO1xuICAgIGlzRHJhZ2dpbmcgPSBmYWxzZTtcblxuICAgIC8vIEluZXJ0aWE6IHByb2plY3QgYSBcInRocm93XCIgdGFyZ2V0IGZyb20gcmVsZWFzZSB2ZWxvY2l0eSwgbGV0IExlbmlzIGxlcnAgdG8gaXQuXG4gICAgaWYgKE1hdGguYWJzKHZZKSA+IE1JTl9GTElORykge1xuICAgICAgY29uc3QgdGhyb3dQeCA9IC12WSAqIFRIUk9XX01VTFRJUExJRVIgKiA2MDsgLy8gfnBlci1mcmFtZSB0byB0b3RhbFxuICAgICAgbGVuaXMuc2Nyb2xsVG8obGVuaXMuc2Nyb2xsICsgdGhyb3dQeCwge1xuICAgICAgICBkdXJhdGlvbjogMS4yLFxuICAgICAgICBlYXNpbmc6ICh4KSA9PiAxIC0gTWF0aC5wb3coMSAtIHgsIDMpLCAvLyBlYXNlLW91dCBjdWJpY1xuICAgICAgfSk7XG4gICAgfVxuICB9XG4gIHdpbmRvdy5hZGRFdmVudExpc3RlbmVyKCdwb2ludGVydXAnLCBlbmREcmFnKTtcbiAgICB3aW5kb3cuYWRkRXZlbnRMaXN0ZW5lcigncG9pbnRlcmNhbmNlbCcsIGVuZERyYWcpO1xuXG5cbiAgLy8gIGxlbmlzID0gbmV3IExlbmlzKHsgbGVycDogMC4xIH0pO1xuXG4gIC8vIC8vIExlbmlzIHJBRiBsb29wXG4gIC8vIGZ1bmN0aW9uIHJhZih0aW1lKSB7XG4gIC8vICAgbGVuaXMucmFmKHRpbWUpO1xuICAvLyAgIHJlcXVlc3RBbmltYXRpb25GcmFtZShyYWYpO1xuICAvLyB9XG4gIC8vIHJlcXVlc3RBbmltYXRpb25GcmFtZShyYWYpO1xuXG4gIC8vIC8vIC0tLSBkcmFnLXRvLXNjcm9sbCBjb25maWcgLS0tXG4gIC8vIGNvbnN0IFNFTlNJVElWSVRZID0gMS41OyAgICAgICAvLyAxOjEgcGl4ZWwgbWFwcGluZzsgPjEgPSBkcmFnIG1vdmVzIHBhZ2UgZmFzdGVyXG4gIC8vIGNvbnN0IERSQUdfVEhSRVNIT0xEID0gNjsgICAgICAvLyBweCBiZWZvcmUgYSBjbGljayBiZWNvbWVzIGEgZHJhZ1xuICAvLyBjb25zdCBEUkFHX0xFUlAgPSAwLjA2OyAgICAgICAgLy8gMC4uMSwgaGlnaGVyID0gdGlnaHRlciBmb2xsb3csIGxvd2VyID0gbW9yZSBsYWdcbiAgLy8gY29uc3QgVkVMT0NJVFlfREVDQVkgPSAwLjkyOyAgIC8vIHNtb290aGluZyBvbiByZWxlYXNlLXZlbG9jaXR5IHNhbXBsaW5nXG4gIC8vIGNvbnN0IFRIUk9XX01VTFRJUExJRVIgPSAxMjsgICAvLyBob3cgZmFyIGluZXJ0aWEgY2FycmllcyBvbiByZWxlYXNlXG4gIC8vIGNvbnN0IE1JTl9GTElORyA9IDAuNDsgICAgICAgICAvLyBweC9tcyBiZWxvdyB3aGljaCB3ZSBkb24ndCBmbGluZ1xuXG4gIC8vIC8vIC0tLSBkcmFnIHN0YXRlIC0tLVxuICAvLyBsZXQgaXNEb3duID0gZmFsc2UsIGlzRHJhZ2dpbmcgPSBmYWxzZTtcbiAgLy8gbGV0IHN0YXJ0WSA9IDAsIHN0YXJ0U2Nyb2xsID0gMDtcbiAgLy8gbGV0IGxhc3RZID0gMCwgbGFzdFQgPSAwLCB2WSA9IDA7XG5cbiAgLy8gbGV0IGRyYWdUYXJnZXQgPSAwOyAgICAgICAgICAgIC8vIHdoZXJlIHRoZSBjdXJzb3IgXCJ3YW50c1wiIHNjcm9sbCB0byBiZVxuICAvLyBsZXQgZHJhZ0N1cnJlbnQgPSAwOyAgICAgICAgICAgIC8vIHdoZXJlIHdlIGFjdHVhbGx5IGFyZSAobGVycGVkKVxuICAvLyBsZXQgbGFzdEZyYW1lVCA9IDA7ICAgICAgICAgICAgIC8vIGZvciBmcmFtZS1yYXRlLWluZGVwZW5kZW50IGxlcnBcblxuICAvLyAvLyAtLS0gcG9pbnRlciBoYW5kbGVycyAtLS1cbiAgLy8gd2luZG93LmFkZEV2ZW50TGlzdGVuZXIoJ3BvaW50ZXJkb3duJywgKGUpID0+IHtcbiAgLy8gICBpZiAoZS5idXR0b24gIT09IDApIHJldHVybjtcblxuICAvLyAgIGlzRG93biA9IHRydWU7XG4gIC8vICAgaXNEcmFnZ2luZyA9IGZhbHNlO1xuICAvLyAgIHN0YXJ0WSA9IGxhc3RZID0gZS5jbGllbnRZO1xuICAvLyAgIGxhc3RUID0gcGVyZm9ybWFuY2Uubm93KCk7XG4gIC8vICAgdlkgPSAwO1xuXG4gIC8vICAgc3RhcnRTY3JvbGwgPSBsZW5pcy5zY3JvbGw7XG4gIC8vICAgZHJhZ0N1cnJlbnQgPSBkcmFnVGFyZ2V0ID0gc3RhcnRTY3JvbGw7XG4gIC8vIH0pO1xuXG4gIC8vIHdpbmRvdy5hZGRFdmVudExpc3RlbmVyKCdwb2ludGVybW92ZScsIChlKSA9PiB7XG4gIC8vICAgaWYgKCFpc0Rvd24pIHJldHVybjtcblxuICAvLyAgIGNvbnN0IGR5ID0gZS5jbGllbnRZIC0gc3RhcnRZO1xuXG4gIC8vICAgaWYgKCFpc0RyYWdnaW5nICYmIE1hdGguYWJzKGR5KSA+IERSQUdfVEhSRVNIT0xEKSB7XG4gIC8vICAgICBpc0RyYWdnaW5nID0gdHJ1ZTtcbiAgLy8gICAgIGRvY3VtZW50LmRvY3VtZW50RWxlbWVudC5zdHlsZS5jdXJzb3IgPSAnZ3JhYmJpbmcnO1xuICAvLyAgICAgZG9jdW1lbnQuZG9jdW1lbnRFbGVtZW50LnN0eWxlLnVzZXJTZWxlY3QgPSAnbm9uZSc7XG5cbiAgLy8gICAgIC8vIEhhbmQgY29udHJvbCB0byBvdXIgbWFudWFsIGxlcnAgbG9vcFxuICAvLyAgICAgbGVuaXMuc3RvcCgpO1xuICAvLyAgICAgbGFzdEZyYW1lVCA9IHBlcmZvcm1hbmNlLm5vdygpO1xuICAvLyAgICAgcmVxdWVzdEFuaW1hdGlvbkZyYW1lKHRpY2tEcmFnKTtcbiAgLy8gICB9XG4gIC8vICAgaWYgKCFpc0RyYWdnaW5nKSByZXR1cm47XG5cbiAgLy8gICAvLyBUcmFjayBpbnN0YW50YW5lb3VzIHZlbG9jaXR5IChweC9tcyksIGxvdy1wYXNzIGZpbHRlcmVkIOKAlCB1c2VkIG9uIHJlbGVhc2VcbiAgLy8gICBjb25zdCBub3cgPSBwZXJmb3JtYW5jZS5ub3coKTtcbiAgLy8gICBjb25zdCBpbnN0ViA9IChlLmNsaWVudFkgLSBsYXN0WSkgLyBNYXRoLm1heCgxLCBub3cgLSBsYXN0VCk7XG4gIC8vICAgdlkgPSB2WSAqIFZFTE9DSVRZX0RFQ0FZICsgaW5zdFYgKiAoMSAtIFZFTE9DSVRZX0RFQ0FZKTtcbiAgLy8gICBsYXN0WSA9IGUuY2xpZW50WTtcbiAgLy8gICBsYXN0VCA9IG5vdztcblxuICAvLyAgIC8vIEp1c3QgbW92ZSB0aGUgdGFyZ2V0IOKAlCB0aGUgckFGIGxvb3AgbGVycHMgdG93YXJkIGl0LlxuICAvLyAgIC8vIERyYWcgRE9XTiByZXZlYWxzIGNvbnRlbnQgQUJPVkUgKHBhZ2Ugc2Nyb2xscyB1cCksIHNvIHN1YnRyYWN0IGR5LlxuICAvLyAgIC8vIEZsaXAgdGhlIHNpZ24gZm9yIFwiaVBhZC1zdHlsZVwiIGNvbnRlbnQtZm9sbG93cy1maW5nZXIuXG4gIC8vICAgZHJhZ1RhcmdldCA9IHN0YXJ0U2Nyb2xsIC0gZHkgKiBTRU5TSVRJVklUWTtcbiAgLy8gfSk7XG5cbiAgLy8gZnVuY3Rpb24gZW5kRHJhZygpIHtcbiAgLy8gICBpZiAoIWlzRG93bikgcmV0dXJuO1xuICAvLyAgIGlzRG93biA9IGZhbHNlO1xuICAvLyAgIGRvY3VtZW50LmRvY3VtZW50RWxlbWVudC5zdHlsZS5jdXJzb3IgPSAnJztcbiAgLy8gICBkb2N1bWVudC5kb2N1bWVudEVsZW1lbnQuc3R5bGUudXNlclNlbGVjdCA9ICcnO1xuXG4gIC8vICAgaWYgKCFpc0RyYWdnaW5nKSB7XG4gIC8vICAgICAvLyBJdCB3YXMganVzdCBhIGNsaWNrIOKAlCBtYWtlIHN1cmUgTGVuaXMgaXMgcnVubmluZy5cbiAgLy8gICAgIGxlbmlzLnN0YXJ0KCk7XG4gIC8vICAgICByZXR1cm47XG4gIC8vICAgfVxuICAvLyAgIGlzRHJhZ2dpbmcgPSBmYWxzZTtcblxuICAvLyAgIC8vIFJlLXN5bmMgTGVuaXMgdG8gd2hlcmUgd2UgYWN0dWFsbHkgZW5kZWQgdXAgYmVmb3JlIGhhbmRpbmcgYmFjayBjb250cm9sLlxuICAvLyAgIGxlbmlzLnN0YXJ0KCk7XG4gIC8vICAgbGVuaXMuc2Nyb2xsVG8oZHJhZ0N1cnJlbnQsIHsgaW1tZWRpYXRlOiB0cnVlLCBmb3JjZTogdHJ1ZSB9KTtcblxuICAvLyAgIC8vIEluZXJ0aWEgdGhyb3cg4oCUIGxldCBMZW5pcyBlYXNlIGZyb20gY3VycmVudCB0byBwcm9qZWN0ZWQgdGFyZ2V0LlxuICAvLyAgIGlmIChNYXRoLmFicyh2WSkgPiBNSU5fRkxJTkcpIHtcbiAgLy8gICAgIGNvbnN0IHRocm93UHggPSAtdlkgKiBUSFJPV19NVUxUSVBMSUVSICogNjA7XG4gIC8vICAgICBsZW5pcy5zY3JvbGxUbyhkcmFnQ3VycmVudCArIHRocm93UHgsIHtcbiAgLy8gICAgICAgZHVyYXRpb246IDEuMixcbiAgLy8gICAgICAgZWFzaW5nOiAoeCkgPT4gMSAtIE1hdGgucG93KDEgLSB4LCAzKSwgLy8gZWFzZS1vdXQgY3ViaWNcbiAgLy8gICAgICAgZm9yY2U6IHRydWUsXG4gIC8vICAgICB9KTtcbiAgLy8gICB9XG4gIC8vIH1cbiAgLy8gd2luZG93LmFkZEV2ZW50TGlzdGVuZXIoJ3BvaW50ZXJ1cCcsIGVuZERyYWcpO1xuICAvLyB3aW5kb3cuYWRkRXZlbnRMaXN0ZW5lcigncG9pbnRlcmNhbmNlbCcsIGVuZERyYWcpO1xuXG4gIC8vIC8vIC0tLSBtYW51YWwgbGVycCBsb29wIChvbmx5IHJ1bnMgd2hpbGUgZHJhZ2dpbmcpIC0tLVxuICAvLyBmdW5jdGlvbiB0aWNrRHJhZygpIHtcbiAgLy8gICBpZiAoIWlzRHJhZ2dpbmcpIHJldHVybjtcblxuICAvLyAgIGNvbnN0IG5vdyA9IHBlcmZvcm1hbmNlLm5vdygpO1xuICAvLyAgIGNvbnN0IGRlbHRhTVMgPSBub3cgLSBsYXN0RnJhbWVUO1xuICAvLyAgIGxhc3RGcmFtZVQgPSBub3c7XG5cbiAgLy8gICAvLyBGcmFtZS1yYXRlLWluZGVwZW5kZW50IGxlcnAgZmFjdG9yXG4gIC8vICAgY29uc3QgdCA9IDEgLSBNYXRoLnBvdygxIC0gRFJBR19MRVJQLCBkZWx0YU1TIC8gMTYuNjY2Nyk7XG4gIC8vICAgZHJhZ0N1cnJlbnQgKz0gKGRyYWdUYXJnZXQgLSBkcmFnQ3VycmVudCkgKiB0O1xuXG4gIC8vICAgd2luZG93LnNjcm9sbFRvKDAsIGRyYWdDdXJyZW50KTtcblxuICAvLyAgIHJlcXVlc3RBbmltYXRpb25GcmFtZSh0aWNrRHJhZyk7XG4gIC8vIH1cbn1cblxuZnVuY3Rpb24gaW5pdEZPVUMoKSB7XG4gIGNvbnN0IGxvYWRFbHMgPSBkb2N1bWVudC5xdWVyeVNlbGVjdG9yQWxsKFwiW2RhdGEtYW5pbS1sb2FkXVwiKTtcbiAgbG9hZEVscy5mb3JFYWNoKChlbCkgPT4ge1xuICAgIGlmIChlbC5oYXNBdHRyaWJ1dGUoXCJkYXRhLWZvdWMtcHJldmVudFwiKSkge1xuICAgICAgcmV0dXJuO1xuICAgIH0gZWxzZSB7XG4gICAgICBnc2FwLnNldChlbCwge1xuICAgICAgICB2aXNpYmlsaXR5OiBcInZpc2libGVcIixcbiAgICAgIH0pO1xuICAgIH1cbiAgfSk7XG4gICQoXCJib2R5XCIpLmFkZENsYXNzKFwiaXMtbG9hZGVkXCIpO1xuICBTY3JvbGxUcmlnZ2VyLnJlZnJlc2goKTtcbn1cblxuZnVuY3Rpb24gaW5pdFRleHRTcGxpdCgpIHtcbiAgJChcIltkYXRhLXNwbGl0PWNoYXJzXVwiKS5lYWNoKGZ1bmN0aW9uICgpIHtcbiAgICBjb25zdCB0b1NwbGl0ID0gJCh0aGlzKTtcbiAgICBTcGxpdFRleHQuY3JlYXRlKHRvU3BsaXQsIHtcbiAgICAgIHR5cGU6IFwiY2hhcnMsIGxpbmVzXCIsXG4gICAgICBtYXNrOiBcImNoYXJzXCIsXG4gICAgICBjaGFyc0NsYXNzOiBcImNoYXJcIixcbiAgICAgIGxpbmVzQ2xhc3M6IFwibGluZVwiLFxuICAgIH0pO1xuICB9KTtcbiAgJChcIltkYXRhLXNwbGl0PXdvcmRzXVwiKS5lYWNoKGZ1bmN0aW9uICgpIHtcbiAgICBjb25zdCB0b1NwbGl0ID0gJCh0aGlzKTtcbiAgICBTcGxpdFRleHQuY3JlYXRlKHRvU3BsaXQsIHtcbiAgICAgIHR5cGU6IFwid29yZHMsIGxpbmVzXCIsXG4gICAgICBtYXNrOiBcImxpbmVzXCIsXG4gICAgICB3b3Jkc0NsYXNzOiBcIndvcmRcIixcbiAgICAgIGxpbmVzQ2xhc3M6IFwibGluZVwiLFxuICAgIH0pO1xuICB9KTtcbiAgJChcIltkYXRhLXNwbGl0PWxpbmVzXVwiKS5lYWNoKGZ1bmN0aW9uICgpIHtcbiAgICBjb25zdCB0b1NwbGl0ID0gJCh0aGlzKTtcbiAgICBTcGxpdFRleHQuY3JlYXRlKHRvU3BsaXQsIHtcbiAgICAgIHR5cGU6IFwibGluZXNcIixcbiAgICAgIG1hc2s6IFwibGluZXNcIixcbiAgICAgIGxpbmVzQ2xhc3M6IFwibGluZVwiLFxuICAgIH0pO1xuICB9KTtcbiAgJChcIltkYXRhLXNwbGl0PXJpY2gtbGluZXNdXCIpLmVhY2goZnVuY3Rpb24gKCkge1xuICAgIGNvbnN0IHRvU3BsaXQgPSAkKHRoaXMpLmNoaWxkcmVuKCk7XG4gICAgU3BsaXRUZXh0LmNyZWF0ZSh0b1NwbGl0LCB7XG4gICAgICB0eXBlOiBcImxpbmVzXCIsXG4gICAgICBtYXNrOiBcImxpbmVzXCIsXG4gICAgICBsaW5lc0NsYXNzOiBcImxpbmVcIixcbiAgICB9KTtcbiAgfSk7XG4gICQoXCJbZGF0YS1zcGxpdD11bC1saW5lc11cIikuZWFjaChmdW5jdGlvbiAoKSB7XG4gICAgY29uc3QgdG9TcGxpdCA9ICQodGhpcykuY2hpbGRyZW4oKTtcbiAgICBTcGxpdFRleHQuY3JlYXRlKHRvU3BsaXQsIHtcbiAgICAgIHR5cGU6IFwibGluZXNcIixcbiAgICAgIGxpbmVzQ2xhc3M6IFwibGluZVwiLFxuICAgIH0pO1xuICB9KTtcbn1cblxuZnVuY3Rpb24gaW5pdEdsb2JhbFBhcmFsbGF4KCkge1xuICBjb25zdCBtbSA9IGdzYXAubWF0Y2hNZWRpYSgpO1xuXG4gIG1tLmFkZChcbiAgICB7XG4gICAgICBpc01vYmlsZTogXCIobWF4LXdpZHRoOjQ3OXB4KVwiLFxuICAgICAgaXNNb2JpbGVMYW5kc2NhcGU6IFwiKG1heC13aWR0aDo3NjdweClcIixcbiAgICAgIGlzVGFibGV0OiBcIihtYXgtd2lkdGg6OTkxcHgpXCIsXG4gICAgICBpc0Rlc2t0b3A6IFwiKG1pbi13aWR0aDo5OTJweClcIixcbiAgICB9LFxuICAgIChjb250ZXh0KSA9PiB7XG4gICAgICBjb25zdCB7IGlzTW9iaWxlLCBpc01vYmlsZUxhbmRzY2FwZSwgaXNUYWJsZXQgfSA9IGNvbnRleHQuY29uZGl0aW9ucztcblxuICAgICAgY29uc3QgY3R4ID0gZ3NhcC5jb250ZXh0KCgpID0+IHtcbiAgICAgICAgZG9jdW1lbnRcbiAgICAgICAgICAucXVlcnlTZWxlY3RvckFsbCgnW2RhdGEtcGFyYWxsYXg9XCJ0cmlnZ2VyXCJdJylcbiAgICAgICAgICAuZm9yRWFjaCgodHJpZ2dlcikgPT4ge1xuICAgICAgICAgICAgLy8gQ2hlY2sgaWYgdGhpcyB0cmlnZ2VyIGhhcyB0byBiZSBkaXNhYmxlZCBvbiBzbWFsbGVyIGJyZWFrcG9pbnRzXG4gICAgICAgICAgICBjb25zdCBkaXNhYmxlID0gdHJpZ2dlci5nZXRBdHRyaWJ1dGUoXCJkYXRhLXBhcmFsbGF4LWRpc2FibGVcIik7XG4gICAgICAgICAgICBpZiAoXG4gICAgICAgICAgICAgIChkaXNhYmxlID09PSBcIm1vYmlsZVwiICYmIGlzTW9iaWxlKSB8fFxuICAgICAgICAgICAgICAoZGlzYWJsZSA9PT0gXCJtb2JpbGVMYW5kc2NhcGVcIiAmJiBpc01vYmlsZUxhbmRzY2FwZSkgfHxcbiAgICAgICAgICAgICAgKGRpc2FibGUgPT09IFwidGFibGV0XCIgJiYgaXNUYWJsZXQpXG4gICAgICAgICAgICApIHtcbiAgICAgICAgICAgICAgcmV0dXJuO1xuICAgICAgICAgICAgfVxuXG4gICAgICAgICAgICAvLyBPcHRpb25hbDogeW91IGNhbiB0YXJnZXQgYW4gZWxlbWVudCBpbnNpZGUgYSB0cmlnZ2VyIGlmIG5lY2Vzc2FyeVxuICAgICAgICAgICAgY29uc3QgdGFyZ2V0ID1cbiAgICAgICAgICAgICAgdHJpZ2dlci5xdWVyeVNlbGVjdG9yKCdbZGF0YS1wYXJhbGxheD1cInRhcmdldFwiXScpIHx8IHRyaWdnZXI7XG5cbiAgICAgICAgICAgIC8vIEdldCB0aGUgZGlyZWN0aW9uIHZhbHVlIHRvIGRlY2lkZSBiZXR3ZWVuIHhQZXJjZW50IG9yIHlQZXJjZW50IHR3ZWVuXG4gICAgICAgICAgICBjb25zdCBkaXJlY3Rpb24gPVxuICAgICAgICAgICAgICB0cmlnZ2VyLmdldEF0dHJpYnV0ZShcImRhdGEtcGFyYWxsYXgtZGlyZWN0aW9uXCIpIHx8IFwidmVydGljYWxcIjtcbiAgICAgICAgICAgIGNvbnN0IHByb3AgPSBkaXJlY3Rpb24gPT09IFwiaG9yaXpvbnRhbFwiID8gXCJ4UGVyY2VudFwiIDogXCJ5UGVyY2VudFwiO1xuXG4gICAgICAgICAgICBjb25zdCBlYXNlID0gdHJpZ2dlci5nZXRBdHRyaWJ1dGUoXCJkYXRhLXBhcmFsbGF4LWVhc2VcIikgfHwgXCJub25lXCI7XG5cbiAgICAgICAgICAgIC8vIEdldCB0aGUgc2NydWIgdmFsdWUsIG91ciBkZWZhdWx0IGlzICd0cnVlJyBiZWNhdXNlIHRoYXQgZmVlbHMgbmljZSB3aXRoIExlbmlzXG4gICAgICAgICAgICBjb25zdCBzY3J1YkF0dHIgPSB0cmlnZ2VyLmdldEF0dHJpYnV0ZShcImRhdGEtcGFyYWxsYXgtc2NydWJcIik7XG4gICAgICAgICAgICBjb25zdCBzY3J1YiA9IHNjcnViQXR0ciA/IHBhcnNlRmxvYXQoc2NydWJBdHRyKSA6IHRydWU7XG5cbiAgICAgICAgICAgIC8vIEdldCB0aGUgc3RhcnQgcG9zaXRpb24gaW4gJVxuICAgICAgICAgICAgY29uc3Qgc3RhcnRBdHRyID0gdHJpZ2dlci5nZXRBdHRyaWJ1dGUoXCJkYXRhLXBhcmFsbGF4LXN0YXJ0XCIpO1xuICAgICAgICAgICAgY29uc3Qgc3RhcnRWYWwgPSBzdGFydEF0dHIgIT09IG51bGwgPyBwYXJzZUZsb2F0KHN0YXJ0QXR0cikgOiAyMDtcblxuICAgICAgICAgICAgLy8gR2V0IHRoZSBlbmQgcG9zaXRpb24gaW4gJVxuICAgICAgICAgICAgY29uc3QgZW5kQXR0ciA9IHRyaWdnZXIuZ2V0QXR0cmlidXRlKFwiZGF0YS1wYXJhbGxheC1lbmRcIik7XG4gICAgICAgICAgICBjb25zdCBlbmRWYWwgPSBlbmRBdHRyICE9PSBudWxsID8gcGFyc2VGbG9hdChlbmRBdHRyKSA6IC0yMDtcblxuICAgICAgICAgICAgLy8gR2V0IHRoZSBzdGFydCB2YWx1ZSBvZiB0aGUgU2Nyb2xsVHJpZ2dlclxuICAgICAgICAgICAgY29uc3Qgc2Nyb2xsU3RhcnRSYXcgPVxuICAgICAgICAgICAgICB0cmlnZ2VyLmdldEF0dHJpYnV0ZShcImRhdGEtcGFyYWxsYXgtc2Nyb2xsLXN0YXJ0XCIpIHx8XG4gICAgICAgICAgICAgIFwidG9wIGJvdHRvbVwiO1xuICAgICAgICAgICAgY29uc3Qgc2Nyb2xsU3RhcnQgPSBgY2xhbXAoJHtzY3JvbGxTdGFydFJhd30pYDtcblxuICAgICAgICAgICAgLy8gR2V0IHRoZSBlbmQgdmFsdWUgb2YgdGhlIFNjcm9sbFRyaWdnZXJcbiAgICAgICAgICAgIGNvbnN0IHNjcm9sbEVuZFJhdyA9XG4gICAgICAgICAgICAgIHRyaWdnZXIuZ2V0QXR0cmlidXRlKFwiZGF0YS1wYXJhbGxheC1zY3JvbGwtZW5kXCIpIHx8IFwiYm90dG9tIHRvcFwiO1xuICAgICAgICAgICAgY29uc3Qgc2Nyb2xsRW5kID0gYGNsYW1wKCR7c2Nyb2xsRW5kUmF3fSlgO1xuXG4gICAgICAgICAgICBnc2FwLmZyb21UbyhcbiAgICAgICAgICAgICAgdGFyZ2V0LFxuICAgICAgICAgICAgICB7IFtwcm9wXTogc3RhcnRWYWwgfSxcbiAgICAgICAgICAgICAge1xuICAgICAgICAgICAgICAgIFtwcm9wXTogZW5kVmFsLFxuICAgICAgICAgICAgICAgIGVhc2U6IGVhc2UsXG4gICAgICAgICAgICAgICAgc2Nyb2xsVHJpZ2dlcjoge1xuICAgICAgICAgICAgICAgICAgdHJpZ2dlcixcbiAgICAgICAgICAgICAgICAgIHN0YXJ0OiBzY3JvbGxTdGFydCxcbiAgICAgICAgICAgICAgICAgIGVuZDogc2Nyb2xsRW5kLFxuICAgICAgICAgICAgICAgICAgc2NydWIsXG4gICAgICAgICAgICAgICAgfSxcbiAgICAgICAgICAgICAgfVxuICAgICAgICAgICAgKTtcbiAgICAgICAgICB9KTtcbiAgICAgIH0pO1xuXG4gICAgICByZXR1cm4gKCkgPT4gY3R4LnJldmVydCgpO1xuICAgIH1cbiAgKTtcbn1cblxuZnVuY3Rpb24gaW5pdExvYWRBbmltYXRpb25zKCkge1xuICBjb25zdCBpc01vYmlsZSA9IHdpbmRvdy5pbm5lcldpZHRoIDw9IDc2ODtcbiAgaWYgKGlzTW9iaWxlKSByZXR1cm47XG4gIGNvbnN0IGdsb2JhbEludHJvRGVsYXkgPSAwLjU7XG5cbiAgJChcIltkYXRhLWFuaW0tbG9hZD1jaGFyc11cIikuZWFjaChmdW5jdGlvbiAoKSB7XG4gICAgY29uc3QgZWxEZWxheSA9IHBhcnNlRmxvYXQoJCh0aGlzKS5hdHRyKFwiZGF0YS1hbmltLWxvYWQtZGVsYXlcIikpIHx8IDA7XG5cbiAgICBnc2FwLmZyb20oJCh0aGlzKS5maW5kKFwiLmNoYXJcIiksIHtcbiAgICAgIGRlbGF5OiBnbG9iYWxJbnRyb0RlbGF5ICsgZWxEZWxheSxcbiAgICAgIHhQZXJjZW50OiAxMDAsXG4gICAgICBkdXJhdGlvbjogMS41LFxuICAgICAgZWFzZTogXCJleHBvLm91dFwiLFxuICAgICAgc3RhZ2dlcjoge1xuICAgICAgICBlYWNoOiAwLjEyNSxcbiAgICAgIH0sXG4gICAgfSk7XG4gIH0pO1xuXG4gICQoXCJbZGF0YS1hbmltLWxvYWQ9d29yZHNdXCIpLmVhY2goZnVuY3Rpb24gKCkge1xuICAgIGNvbnN0IGVsRGVsYXkgPSBwYXJzZUZsb2F0KCQodGhpcykuYXR0cihcImRhdGEtYW5pbS1sb2FkLWRlbGF5XCIpKSB8fCAwO1xuXG4gICAgZ3NhcC5mcm9tKCQodGhpcykuZmluZChcIi53b3JkXCIpLCB7XG4gICAgICBkZWxheTogZ2xvYmFsSW50cm9EZWxheSArIGVsRGVsYXksXG4gICAgICB5UGVyY2VudDogMTI1LFxuICAgICAgZHVyYXRpb246IDEuNSxcbiAgICAgIGVhc2U6IFwiZXhwby5vdXRcIixcbiAgICAgIHN0YWdnZXI6IHtcbiAgICAgICAgZWFjaDogMC4wNSxcbiAgICAgIH0sXG4gICAgfSk7XG4gIH0pO1xuXG4gICQoXCJbZGF0YS1hbmltLWxvYWQ9bGluZXNdXCIpLmVhY2goZnVuY3Rpb24gKCkge1xuICAgIGNvbnN0IGVsRGVsYXkgPSBwYXJzZUZsb2F0KCQodGhpcykuYXR0cihcImRhdGEtYW5pbS1sb2FkLWRlbGF5XCIpKSB8fCAwO1xuXG4gICAgZ3NhcC5mcm9tKCQodGhpcykuZmluZChcIi5saW5lXCIpLCB7XG4gICAgICB4UGVyY2VudDogMTAwLFxuICAgICAgc2NhbGU6IDAuNSxcbiAgICAgIGRlbGF5OiBnbG9iYWxJbnRyb0RlbGF5ICsgZWxEZWxheSxcbiAgICAgIGR1cmF0aW9uOiAxLjc1LFxuICAgICAgZWFzZTogXCJleHBvLm91dFwiLFxuICAgICAgc3RhZ2dlcjoge1xuICAgICAgICBlYWNoOiAwLjEyNSxcbiAgICAgIH0sXG4gICAgfSk7XG4gIH0pO1xuXG4gICQoXCJbZGF0YS1hbmltLWxvYWQ9c2NhbGVdXCIpLmVhY2goZnVuY3Rpb24gKCkge1xuICAgIGNvbnN0IGVsRGVsYXkgPSAkKHRoaXMpLmF0dHIoXCJkYXRhLWFuaW0tbG9hZC1kZWxheVwiKSB8fCAwO1xuXG4gICAgZ3NhcC5mcm9tKCQodGhpcyksIHtcbiAgICAgIHNjYWxlOiAxLjI1LFxuICAgICAgZGVsYXk6IGVsRGVsYXksXG4gICAgICBkdXJhdGlvbjogMyxcbiAgICAgIGVhc2U6IFwicG93ZXIzLm91dFwiLFxuICAgIH0pO1xuICB9KTtcblxuICAkKFwiW2RhdGEtYW5pbS1sb2FkPXNsaWRlLXVwLWZhZGVdXCIpLmVhY2goZnVuY3Rpb24gKCkge1xuICAgIGNvbnN0IGVsRGVsYXkgPSAkKHRoaXMpLmF0dHIoXCJkYXRhLWFuaW0tbG9hZC1kZWxheVwiKSB8fCAwO1xuXG4gICAgZ3NhcC5mcm9tKCQodGhpcyksIHtcbiAgICAgIHlQZXJjZW50OiA1MCxcbiAgICAgIG9wYWNpdHk6IDAsXG4gICAgICBkZWxheTogZ2xvYmFsSW50cm9EZWxheSArIGVsRGVsYXksXG4gICAgICBkdXJhdGlvbjogMixcbiAgICAgIGVhc2U6IFwiZXhwby5vdXRcIixcbiAgICB9KTtcbiAgfSk7XG5cbiAgJChcIltkYXRhLWFuaW0tbG9hZD1jaGlsZHJlbi1zbGlkZS11cC1mYWRlXVwiKS5lYWNoKGZ1bmN0aW9uICgpIHtcbiAgICBjb25zdCBlbERlbGF5ID0gJCh0aGlzKS5hdHRyKFwiZGF0YS1hbmltLWxvYWQtZGVsYXlcIikgfHwgMDtcblxuICAgIGdzYXAuZnJvbSgkKHRoaXMpLmNoaWxkcmVuKCksIHtcbiAgICAgIHlQZXJjZW50OiA1MCxcbiAgICAgIG9wYWNpdHk6IDAsXG4gICAgICBkZWxheTogZ2xvYmFsSW50cm9EZWxheSArIGVsRGVsYXksXG4gICAgICBkdXJhdGlvbjogMixcbiAgICAgIGVhc2U6IFwiZXhwby5vdXRcIixcbiAgICAgIHN0YWdnZXI6IHtcbiAgICAgICAgZWFjaDogMC4xMjUsXG4gICAgICB9LFxuICAgIH0pO1xuICB9KTtcblxuICAkKFwiW2RhdGEtYW5pbS1sb2FkPW1hc2tdXCIpLmVhY2goZnVuY3Rpb24gKCkge1xuICAgIGNvbnN0IGVsRGVsYXkgPSBwYXJzZUZsb2F0KCQodGhpcykuYXR0cihcImRhdGEtYW5pbS1sb2FkLWRlbGF5XCIpKSB8fCA2O1xuXG4gICAgZ3NhcC5mcm9tVG8oXG4gICAgICAkKHRoaXMpLFxuICAgICAge1xuICAgICAgICBjbGlwUGF0aDogXCJwb2x5Z29uKDAlIDAlLCAxMDAlIDAlLCAxMDAlIDEwMCUsIDAlIDEwMCUpXCIsXG4gICAgICB9LFxuICAgICAge1xuICAgICAgICBkZWxheTogZ2xvYmFsSW50cm9EZWxheSArIGVsRGVsYXksXG4gICAgICAgIGNsaXBQYXRoOiBcInBvbHlnb24oMCUgMCUsIDAlIDAlLCAwJSAxMDAlLCAwJSAxMDAlKVwiLFxuICAgICAgICBkdXJhdGlvbjogMS43NSxcbiAgICAgICAgZWFzZTogXCJleHBvLmluT3V0XCIsXG4gICAgICB9XG4gICAgKTtcbiAgfSk7XG5cbiAgJChcIltkYXRhLWFuaW0tbG9hZD1uYXYtbG9nb11cIikuZWFjaChmdW5jdGlvbiAoKSB7XG4gICAgY29uc3QgZWxEZWxheSA9IHBhcnNlRmxvYXQoJCh0aGlzKS5hdHRyKFwiZGF0YS1hbmltLWxvYWQtZGVsYXlcIikpIHx8IDA7XG5cbiAgICBnc2FwLmZyb20oJCh0aGlzKS5maW5kKFwiLmdfbG9nb19zcGxpdF9zdmdcIiksIHtcbiAgICAgIHhQZXJjZW50OiAxMjUsXG4gICAgICBkZWxheTogZ2xvYmFsSW50cm9EZWxheSArIGVsRGVsYXksXG4gICAgICBlYXNlOiBcImV4cG8ub3V0XCIsXG4gICAgICBkdXJhdGlvbjogMS41LFxuICAgICAgc3RhZ2dlcjoge1xuICAgICAgICBlYWNoOiAwLjA1LFxuICAgICAgfSxcbiAgICB9KTtcbiAgfSk7XG5cbiAgJChcIltkYXRhLWFuaW0tbG9hZD1uYXYtYnV0dG9uXVwiKS5lYWNoKGZ1bmN0aW9uICgpIHtcbiAgICBjb25zdCBlbERlbGF5ID0gcGFyc2VGbG9hdCgkKHRoaXMpLmF0dHIoXCJkYXRhLWFuaW0tbG9hZC1kZWxheVwiKSkgfHwgMDtcblxuICAgIGdzYXAuZnJvbVRvKFxuICAgICAgJCh0aGlzKSxcbiAgICAgIHtcbiAgICAgICAgY2xpcFBhdGg6IFwicG9seWdvbigwJSAwJSwgMTAwJSAwJSwgMTAwJSAwJSwgMCUgMCUpXCIsXG4gICAgICB9LFxuICAgICAge1xuICAgICAgICBjbGlwUGF0aDogXCJwb2x5Z29uKDAlIDAlLCAxMDAlIDAlLCAxMDAlIDEwMCUsIDAlIDEwMCUpXCIsXG4gICAgICAgIGRlbGF5OiBnbG9iYWxJbnRyb0RlbGF5ICsgZWxEZWxheSxcbiAgICAgICAgZWFzZTogXCJleHBvLm91dFwiLFxuICAgICAgICBkdXJhdGlvbjogMS41LFxuICAgICAgfVxuICAgICk7XG4gIH0pO1xufVxuXG5mdW5jdGlvbiBpbml0U2Nyb2xsQW5pbWF0aW9ucygpIHtcbiAgJChcIltkYXRhLWFuaW0tc2Nyb2xsPWNoYXJzXVwiKS5lYWNoKGZ1bmN0aW9uICgpIHtcbiAgICBnc2FwLmZyb20oJCh0aGlzKS5maW5kKFwiLmNoYXJcIiksIHtcbiAgICAgIHhQZXJjZW50OiAxMDAsXG4gICAgICBkdXJhdGlvbjogMS41LFxuICAgICAgZWFzZTogXCJleHBvLm91dFwiLFxuICAgICAgc3RhZ2dlcjoge1xuICAgICAgICBlYWNoOiAwLjEyNSxcbiAgICAgIH0sXG4gICAgICBzY3JvbGxUcmlnZ2VyOiB7XG4gICAgICAgIHRyaWdnZXI6ICQodGhpcyksXG4gICAgICAgIHN0YXJ0OiBcInRvcCBib3R0b21cIixcbiAgICAgICAgZW5kOiBcInRvcCA5MCVcIixcbiAgICAgICAgdG9nZ2xlQWN0aW9uczogXCJub25lIHBsYXkgbm9uZSByZXNldFwiLFxuICAgICAgfSxcbiAgICB9KTtcbiAgfSk7XG5cbiAgJChcIltkYXRhLWFuaW0tc2Nyb2xsPXdvcmRzXVwiKS5lYWNoKGZ1bmN0aW9uICgpIHtcbiAgICBnc2FwLmZyb20oJCh0aGlzKS5maW5kKFwiLndvcmRcIiksIHtcbiAgICAgIHlQZXJjZW50OiAxMTUsXG4gICAgICAvLyB4UGVyY2VudDogMjUsXG4gICAgICBkdXJhdGlvbjogMixcbiAgICAgIGVhc2U6IFwiZXhwby5vdXRcIixcbiAgICAgIHN0YWdnZXI6IHtcbiAgICAgICAgZWFjaDogMC4wNSxcbiAgICAgIH0sXG4gICAgICBzY3JvbGxUcmlnZ2VyOiB7XG4gICAgICAgIHRyaWdnZXI6ICQodGhpcyksXG4gICAgICAgIHN0YXJ0OiBcInRvcCBib3R0b21cIixcbiAgICAgICAgZW5kOiBcInRvcCA5MCVcIixcbiAgICAgICAgdG9nZ2xlQWN0aW9uczogXCJub25lIHBsYXkgbm9uZSByZXNldFwiLFxuICAgICAgfSxcbiAgICB9KTtcbiAgfSk7XG5cbiAgJChcIltkYXRhLWFuaW0tc2Nyb2xsPWxpbmVzXVwiKS5lYWNoKGZ1bmN0aW9uICgpIHtcbiAgICBnc2FwLmZyb20oJCh0aGlzKS5maW5kKFwiLmxpbmVcIiksIHtcbiAgICAgIGRlbGF5OiAwLjEyNSxcbiAgICAgIHlQZXJjZW50OiAxMDAsXG4gICAgICAvLyB4UGVyY2VudDogMjUsXG4gICAgICAvLyBzY2FsZTogMC41LFxuICAgICAgZHVyYXRpb246IDIsXG4gICAgICBlYXNlOiBcImV4cG8ub3V0XCIsXG4gICAgICBzdGFnZ2VyOiB7XG4gICAgICAgIGVhY2g6IDAuMSxcbiAgICAgIH0sXG4gICAgICBzY3JvbGxUcmlnZ2VyOiB7XG4gICAgICAgIHRyaWdnZXI6ICQodGhpcyksXG4gICAgICAgIHN0YXJ0OiBcInRvcCBib3R0b21cIixcbiAgICAgICAgZW5kOiBcInRvcCA5MCVcIixcbiAgICAgICAgdG9nZ2xlQWN0aW9uczogXCJub25lIHBsYXkgbm9uZSByZXNldFwiLFxuICAgICAgfSxcbiAgICB9KTtcbiAgfSk7XG5cbiAgJChcIltkYXRhLWFuaW0tc2Nyb2xsPWZhZGVdXCIpLmVhY2goZnVuY3Rpb24gKCkge1xuICAgIGdzYXAuZnJvbSgkKHRoaXMpLCB7XG4gICAgICBvcGFjaXR5OiAwLFxuICAgICAgZHVyYXRpb246IDEuNjYsXG4gICAgICBzY3JvbGxUcmlnZ2VyOiB7XG4gICAgICAgIHRyaWdnZXI6ICQodGhpcyksXG4gICAgICAgIHN0YXJ0OiBcInRvcCBib3R0b21cIixcbiAgICAgICAgZW5kOiBcInRvcCA5MCVcIixcbiAgICAgICAgdG9nZ2xlQWN0aW9uczogXCJub25lIHBsYXkgbm9uZSByZXNldFwiLFxuICAgICAgfSxcbiAgICB9KTtcbiAgfSk7XG5cbiAgJChcIltkYXRhLWFuaW0tc2Nyb2xsPXNjcnViLXNjYWxlXVwiKS5lYWNoKGZ1bmN0aW9uICgpIHtcbiAgICBjb25zdCBzY2FsZUZyb20gPSAkKHRoaXMpLmF0dHIoXCJkYXRhLXNjYWxlLWZyb21cIikgfHwgMS4yNTtcbiAgICBjb25zdCBpbm5lciA9ICQodGhpcykuZmluZChcIltkYXRhLXNjcnViLXNjYWxlLWlubmVyXVwiKTtcbiAgICBjb25zdCBpbm5lclNjYWxlRnJvbSA9IGlubmVyLmF0dHIoXCJkYXRhLXNjYWxlLWZyb21cIikgfHwgMC44O1xuXG4gICAgbGV0IHRsID0gZ3NhcC50aW1lbGluZSh7XG4gICAgICBzY3JvbGxUcmlnZ2VyOiB7XG4gICAgICAgIHRyaWdnZXI6ICQodGhpcyksXG4gICAgICAgIHN0YXJ0OiBcInRvcCBib3R0b21cIixcbiAgICAgICAgZW5kOiBcImJvdHRvbSBib3R0b21cIixcbiAgICAgICAgc2NydWI6IHRydWUsXG4gICAgICB9LFxuICAgIH0pO1xuXG4gICAgdGwuZnJvbSgkKHRoaXMpLCB7XG4gICAgICBzY2FsZTogc2NhbGVGcm9tLFxuICAgICAgZWFzZTogXCJwb3dlcjEub3V0XCIsXG4gICAgICBkdXJhdGlvbjogMSxcbiAgICB9KTtcblxuICAgIGlmIChpbm5lci5sZW5ndGgpIHtcbiAgICAgIHRsLmZyb20oXG4gICAgICAgIGlubmVyLFxuICAgICAgICB7XG4gICAgICAgICAgc2NhbGU6IGlubmVyU2NhbGVGcm9tLFxuICAgICAgICAgIGVhc2U6IFwicG93ZXIxLm91dFwiLFxuICAgICAgICAgIGR1cmF0aW9uOiAxLjI1LFxuICAgICAgICB9LFxuICAgICAgICBcIjxcIlxuICAgICAgKTtcbiAgICB9XG4gIH0pO1xuXG4gICQoXCJbZGF0YS1hbmltLXNjcm9sbD1tYXNrLWRpYWdvbmFsXVwiKS5lYWNoKGZ1bmN0aW9uICgpIHtcbiAgICBnc2FwLmZyb21UbyhcbiAgICAgICQodGhpcyksXG4gICAgICB7XG4gICAgICAgIGNsaXBQYXRoOiBcInBvbHlnb24oLTElIC0xJSwgMCUgMCUsIDAlIDAlKVwiLFxuICAgICAgfSxcbiAgICAgIHtcbiAgICAgICAgY2xpcFBhdGg6IFwicG9seWdvbigtMSUgLTElLCAyNTAlIDAlLCAwJSAyNTAlKVwiLFxuICAgICAgICBkdXJhdGlvbjogMy41LFxuICAgICAgICBlYXNlOiBcInBvd2VyMS5pbk91dFwiLFxuICAgICAgICBzY3JvbGxUcmlnZ2VyOiB7XG4gICAgICAgICAgdHJpZ2dlcjogJCh0aGlzKSxcbiAgICAgICAgICBzdGFydDogXCJ0b3AgYm90dG9tXCIsXG4gICAgICAgICAgZW5kOiBcInRvcCA5MCVcIixcbiAgICAgICAgICB0b2dnbGVBY3Rpb25zOiBcIm5vbmUgcGxheSBub25lIHJlc2V0XCIsXG4gICAgICAgIH0sXG4gICAgICB9XG4gICAgKTtcbiAgfSk7XG5cbiAgJChcIltkYXRhLWFuaW0tc2Nyb2xsPXNjYWxlWF1cIikuZWFjaChmdW5jdGlvbiAoKSB7XG4gICAgY29uc3QgaW5uZXJUYXJnZXQgPSAkKHRoaXMpLmZpbmQoXCJbZGF0YS1hbmltLXRhcmdldD1zY2FsZVhdXCIpO1xuICAgIGNvbnN0IHRhcmdldCA9IGlubmVyVGFyZ2V0Lmxlbmd0aCA/IGlubmVyVGFyZ2V0IDogJCh0aGlzKTtcblxuICAgIGdzYXAuZnJvbSh0YXJnZXQsIHtcbiAgICAgIHNjYWxlWDogMCxcbiAgICAgIGR1cmF0aW9uOiAyLFxuICAgICAgZWFzZTogXCJwb3dlcjEuaW5PdXRcIixcbiAgICAgIHN0YWdnZXI6IHtcbiAgICAgICAgZWFjaDogMC4xLFxuICAgICAgfSxcbiAgICAgIHNjcm9sbFRyaWdnZXI6IHtcbiAgICAgICAgdHJpZ2dlcjogJCh0aGlzKSxcbiAgICAgICAgc3RhcnQ6IFwidG9wIGJvdHRvbVwiLFxuICAgICAgICBlbmQ6IFwidG9wIDkwJVwiLFxuICAgICAgICB0b2dnbGVBY3Rpb25zOiBcIm5vbmUgcGxheSBub25lIHJlc2V0XCIsXG4gICAgICB9LFxuICAgIH0pO1xuICB9KTtcblxuICAkKFwiW2RhdGEtYW5pbS1zY3JvbGw9Y2hpbGRyZW4tZmFkZV1cIikuZWFjaChmdW5jdGlvbiAoKSB7XG4gICAgY29uc3QgY2hpbGRyZW4gPSAkKHRoaXMpLmNoaWxkcmVuKCk7XG4gICAgY29uc3QgY2hpbGRUYXJnZXQgPSAkKHRoaXMpLmZpbmQoXCJbZGF0YS1hbmltLXRhcmdldF1cIik7XG4gICAgY29uc3QgYW5pbVRhcmdldCA9IGNoaWxkVGFyZ2V0Lmxlbmd0aCA/IGNoaWxkVGFyZ2V0IDogY2hpbGRyZW47XG5cbiAgICBnc2FwLmZyb20oYW5pbVRhcmdldCwge1xuICAgICAgb3BhY2l0eTogMCxcbiAgICAgIGR1cmF0aW9uOiAxLjY2LFxuICAgICAgeVBlcmNlbnQ6IDE1LFxuICAgICAgZWFzZTogXCJwb3dlcjMub3V0XCIsXG4gICAgICBzdGFnZ2VyOiB7XG4gICAgICAgIGVhY2g6IDAuMTI1LFxuICAgICAgfSxcbiAgICAgIHNjcm9sbFRyaWdnZXI6IHtcbiAgICAgICAgdHJpZ2dlcjogJCh0aGlzKSxcbiAgICAgICAgc3RhcnQ6IFwidG9wIGJvdHRvbVwiLFxuICAgICAgICBlbmQ6IFwidG9wIDkwJVwiLFxuICAgICAgICB0b2dnbGVBY3Rpb25zOiBcIm5vbmUgcGxheSBub25lIHJlc2V0XCIsXG4gICAgICB9LFxuICAgIH0pO1xuICB9KTtcblxuICAkKFwiW2RhdGEtYW5pbS1zY3JvbGw9Y2hpbGRyZW4tc2NhbGVdXCIpLmVhY2goZnVuY3Rpb24gKCkge1xuICAgIGNvbnN0IGNoaWxkcmVuID0gJCh0aGlzKS5jaGlsZHJlbigpO1xuICAgIGNvbnN0IGNoaWxkVGFyZ2V0ID0gJCh0aGlzKS5maW5kKFwiW2RhdGEtYW5pbS10YXJnZXRdXCIpO1xuICAgIGNvbnN0IGFuaW1UYXJnZXQgPSBjaGlsZFRhcmdldC5sZW5ndGggPyBjaGlsZFRhcmdldCA6IGNoaWxkcmVuO1xuXG4gICAgZ3NhcC5mcm9tKGFuaW1UYXJnZXQsIHtcbiAgICAgIHNjYWxlOiAwLFxuICAgICAgZHVyYXRpb246IDEuNjYsXG4gICAgICB5UGVyY2VudDogMTUsXG4gICAgICBlYXNlOiBcInBvd2VyMy5vdXRcIixcbiAgICAgIHN0YWdnZXI6IHtcbiAgICAgICAgZWFjaDogMC4xMjUsXG4gICAgICB9LFxuICAgICAgc2Nyb2xsVHJpZ2dlcjoge1xuICAgICAgICB0cmlnZ2VyOiAkKHRoaXMpLFxuICAgICAgICBzdGFydDogXCJ0b3AgYm90dG9tXCIsXG4gICAgICAgIGVuZDogXCJ0b3AgOTAlXCIsXG4gICAgICAgIHRvZ2dsZUFjdGlvbnM6IFwibm9uZSBwbGF5IG5vbmUgcmVzZXRcIixcbiAgICAgIH0sXG4gICAgfSk7XG4gIH0pO1xufVxuXG5mdW5jdGlvbiBpbml0TWFycXVlZVNjcm9sbERpcmVjdGlvbigpIHtcbiAgZG9jdW1lbnRcbiAgICAucXVlcnlTZWxlY3RvckFsbChcIltkYXRhLW1hcnF1ZWUtc2Nyb2xsLWRpcmVjdGlvbi10YXJnZXRdXCIpXG4gICAgLmZvckVhY2goKG1hcnF1ZWUpID0+IHtcbiAgICAgIC8vIFF1ZXJ5IG1hcnF1ZWUgZWxlbWVudHNcbiAgICAgIGNvbnN0IG1hcnF1ZWVDb250ZW50ID0gbWFycXVlZS5xdWVyeVNlbGVjdG9yKFxuICAgICAgICBcIltkYXRhLW1hcnF1ZWUtY29sbGVjdGlvbi10YXJnZXRdXCJcbiAgICAgICk7XG4gICAgICBjb25zdCBtYXJxdWVlU2Nyb2xsID0gbWFycXVlZS5xdWVyeVNlbGVjdG9yKFxuICAgICAgICBcIltkYXRhLW1hcnF1ZWUtc2Nyb2xsLXRhcmdldF1cIlxuICAgICAgKTtcbiAgICAgIGlmICghbWFycXVlZUNvbnRlbnQgfHwgIW1hcnF1ZWVTY3JvbGwpIHJldHVybjtcblxuICAgICAgLy8gR2V0IGRhdGEgYXR0cmlidXRlc1xuICAgICAgY29uc3Qge1xuICAgICAgICBtYXJxdWVlU3BlZWQ6IHNwZWVkLFxuICAgICAgICBtYXJxdWVlRGlyZWN0aW9uOiBkaXJlY3Rpb24sXG4gICAgICAgIG1hcnF1ZWVEdXBsaWNhdGU6IGR1cGxpY2F0ZSxcbiAgICAgICAgbWFycXVlZVNjcm9sbFNwZWVkOiBzY3JvbGxTcGVlZCxcbiAgICAgIH0gPSBtYXJxdWVlLmRhdGFzZXQ7XG5cbiAgICAgIC8vIENvbnZlcnQgZGF0YSBhdHRyaWJ1dGVzIHRvIHVzYWJsZSB0eXBlc1xuICAgICAgY29uc3QgbWFycXVlZVNwZWVkQXR0ciA9IHBhcnNlRmxvYXQoc3BlZWQpO1xuICAgICAgY29uc3QgbWFycXVlZURpcmVjdGlvbkF0dHIgPSBkaXJlY3Rpb24gPT09IFwicmlnaHRcIiA/IDEgOiAtMTsgLy8gMSBmb3IgcmlnaHQsIC0xIGZvciBsZWZ0XG4gICAgICBjb25zdCBkdXBsaWNhdGVBbW91bnQgPSBwYXJzZUludChkdXBsaWNhdGUgfHwgMCk7XG4gICAgICBjb25zdCBzY3JvbGxTcGVlZEF0dHIgPSBwYXJzZUZsb2F0KHNjcm9sbFNwZWVkKTtcbiAgICAgIGNvbnN0IHNwZWVkTXVsdGlwbGllciA9XG4gICAgICAgIHdpbmRvdy5pbm5lcldpZHRoIDwgNDc5ID8gMC4yNSA6IHdpbmRvdy5pbm5lcldpZHRoIDwgOTkxID8gMC41IDogMTtcblxuICAgICAgbGV0IG1hcnF1ZWVTcGVlZCA9XG4gICAgICAgIG1hcnF1ZWVTcGVlZEF0dHIgKlxuICAgICAgICAobWFycXVlZUNvbnRlbnQub2Zmc2V0V2lkdGggLyB3aW5kb3cuaW5uZXJXaWR0aCkgKlxuICAgICAgICBzcGVlZE11bHRpcGxpZXI7XG5cbiAgICAgIC8vIFByZWNvbXB1dGUgc3R5bGVzIGZvciB0aGUgc2Nyb2xsIGNvbnRhaW5lclxuICAgICAgbWFycXVlZVNjcm9sbC5zdHlsZS5tYXJnaW5MZWZ0ID0gYCR7c2Nyb2xsU3BlZWRBdHRyICogLTF9JWA7XG4gICAgICBtYXJxdWVlU2Nyb2xsLnN0eWxlLndpZHRoID0gYCR7c2Nyb2xsU3BlZWRBdHRyICogMiArIDEwMH0lYDtcblxuICAgICAgLy8gRHVwbGljYXRlIG1hcnF1ZWUgY29udGVudFxuICAgICAgaWYgKGR1cGxpY2F0ZUFtb3VudCA+IDApIHtcbiAgICAgICAgY29uc3QgZnJhZ21lbnQgPSBkb2N1bWVudC5jcmVhdGVEb2N1bWVudEZyYWdtZW50KCk7XG4gICAgICAgIGZvciAobGV0IGkgPSAwOyBpIDwgZHVwbGljYXRlQW1vdW50OyBpKyspIHtcbiAgICAgICAgICBmcmFnbWVudC5hcHBlbmRDaGlsZChtYXJxdWVlQ29udGVudC5jbG9uZU5vZGUodHJ1ZSkpO1xuICAgICAgICB9XG4gICAgICAgIG1hcnF1ZWVTY3JvbGwuYXBwZW5kQ2hpbGQoZnJhZ21lbnQpO1xuICAgICAgfVxuXG4gICAgICAvLyBHU0FQIGFuaW1hdGlvbiBmb3IgbWFycXVlZSBjb250ZW50XG4gICAgICBjb25zdCBtYXJxdWVlSXRlbXMgPSBtYXJxdWVlLnF1ZXJ5U2VsZWN0b3JBbGwoXG4gICAgICAgIFwiW2RhdGEtbWFycXVlZS1jb2xsZWN0aW9uLXRhcmdldF1cIlxuICAgICAgKTtcbiAgICAgIGNvbnN0IGFuaW1hdGlvbiA9IGdzYXBcbiAgICAgICAgLnRvKG1hcnF1ZWVJdGVtcywge1xuICAgICAgICAgIHhQZXJjZW50OiAtMTAwLCAvLyBNb3ZlIGNvbXBsZXRlbHkgb3V0IG9mIHZpZXdcbiAgICAgICAgICByZXBlYXQ6IC0xLFxuICAgICAgICAgIGR1cmF0aW9uOiBtYXJxdWVlU3BlZWQsXG4gICAgICAgICAgZWFzZTogXCJsaW5lYXJcIixcbiAgICAgICAgfSlcbiAgICAgICAgLnRvdGFsUHJvZ3Jlc3MoMC41KTtcblxuICAgICAgLy8gSW5pdGlhbGl6ZSBtYXJxdWVlIGluIHRoZSBjb3JyZWN0IGRpcmVjdGlvblxuICAgICAgZ3NhcC5zZXQobWFycXVlZUl0ZW1zLCB7XG4gICAgICAgIHhQZXJjZW50OiBtYXJxdWVlRGlyZWN0aW9uQXR0ciA9PT0gMSA/IDEwMCA6IC0xMDAsXG4gICAgICB9KTtcbiAgICAgIGFuaW1hdGlvbi50aW1lU2NhbGUobWFycXVlZURpcmVjdGlvbkF0dHIpOyAvLyBTZXQgY29ycmVjdCBkaXJlY3Rpb25cbiAgICAgIGFuaW1hdGlvbi5wbGF5KCk7IC8vIFN0YXJ0IGFuaW1hdGlvbiBpbW1lZGlhdGVseVxuXG4gICAgICAvLyBTZXQgaW5pdGlhbCBtYXJxdWVlIHN0YXR1c1xuICAgICAgbWFycXVlZS5zZXRBdHRyaWJ1dGUoXCJkYXRhLW1hcnF1ZWUtc3RhdHVzXCIsIFwibm9ybWFsXCIpO1xuXG4gICAgICAvLyBTY3JvbGxUcmlnZ2VyIGxvZ2ljIGZvciBkaXJlY3Rpb24gaW52ZXJzaW9uXG4gICAgICBTY3JvbGxUcmlnZ2VyLmNyZWF0ZSh7XG4gICAgICAgIHRyaWdnZXI6IG1hcnF1ZWUsXG4gICAgICAgIHN0YXJ0OiBcInRvcCBib3R0b21cIixcbiAgICAgICAgZW5kOiBcImJvdHRvbSB0b3BcIixcbiAgICAgICAgb25VcGRhdGU6IChzZWxmKSA9PiB7XG4gICAgICAgICAgY29uc3QgaXNJbnZlcnRlZCA9IHNlbGYuZGlyZWN0aW9uID09PSAxOyAvLyBTY3JvbGxpbmcgZG93blxuICAgICAgICAgIGNvbnN0IGN1cnJlbnREaXJlY3Rpb24gPSBpc0ludmVydGVkXG4gICAgICAgICAgICA/IC1tYXJxdWVlRGlyZWN0aW9uQXR0clxuICAgICAgICAgICAgOiBtYXJxdWVlRGlyZWN0aW9uQXR0cjtcblxuICAgICAgICAgIC8vIFVwZGF0ZSBhbmltYXRpb24gZGlyZWN0aW9uIGFuZCBtYXJxdWVlIHN0YXR1c1xuICAgICAgICAgIGFuaW1hdGlvbi50aW1lU2NhbGUoY3VycmVudERpcmVjdGlvbik7XG4gICAgICAgICAgbWFycXVlZS5zZXRBdHRyaWJ1dGUoXG4gICAgICAgICAgICBcImRhdGEtbWFycXVlZS1zdGF0dXNcIixcbiAgICAgICAgICAgIGlzSW52ZXJ0ZWQgPyBcIm5vcm1hbFwiIDogXCJpbnZlcnRlZFwiXG4gICAgICAgICAgKTtcbiAgICAgICAgfSxcbiAgICAgIH0pO1xuXG4gICAgICAvLyBFeHRyYSBzcGVlZCBlZmZlY3Qgb24gc2Nyb2xsXG4gICAgICBjb25zdCB0bCA9IGdzYXAudGltZWxpbmUoe1xuICAgICAgICBzY3JvbGxUcmlnZ2VyOiB7XG4gICAgICAgICAgdHJpZ2dlcjogbWFycXVlZSxcbiAgICAgICAgICBzdGFydDogXCIwJSAxMDAlXCIsXG4gICAgICAgICAgZW5kOiBcIjEwMCUgMCVcIixcbiAgICAgICAgICBzY3J1YjogMCxcbiAgICAgICAgfSxcbiAgICAgIH0pO1xuXG4gICAgICBjb25zdCBzY3JvbGxTdGFydCA9XG4gICAgICAgIG1hcnF1ZWVEaXJlY3Rpb25BdHRyID09PSAtMSA/IHNjcm9sbFNwZWVkQXR0ciA6IC1zY3JvbGxTcGVlZEF0dHI7XG4gICAgICBjb25zdCBzY3JvbGxFbmQgPSAtc2Nyb2xsU3RhcnQ7XG5cbiAgICAgIHRsLmZyb21UbyhcbiAgICAgICAgbWFycXVlZVNjcm9sbCxcbiAgICAgICAgeyB4OiBgJHtzY3JvbGxTdGFydH12d2AgfSxcbiAgICAgICAgeyB4OiBgJHtzY3JvbGxFbmR9dndgLCBlYXNlOiBcIm5vbmVcIiB9XG4gICAgICApO1xuICAgIH0pO1xufVxuXG5mdW5jdGlvbiBpbml0Q2hlY2tTZWN0aW9uVGhlbWVTY3JvbGwoKSB7XG4gIGNvbnN0IG5hdkJhckhlaWdodCA9IGRvY3VtZW50LnF1ZXJ5U2VsZWN0b3IoXCJbZGF0YS1uYXYtYmFyLWhlaWdodF1cIik7XG4gIGNvbnN0IHRoZW1lT2JzZXJ2ZXJPZmZzZXQgPSBuYXZCYXJIZWlnaHQgPyBuYXZCYXJIZWlnaHQub2Zmc2V0SGVpZ2h0IC8gMiA6IDA7XG5cbiAgbGV0IGlzTmF2T3BlbiA9IGZhbHNlO1xuXG4gIGZ1bmN0aW9uIGNoZWNrVGhlbWVTZWN0aW9uKCkge1xuICAgIC8vIFNraXAgd2hpbGUgbmF2IGlzIGZvcmNpbmcgZGFya1xuICAgIGlmIChpc05hdk9wZW4pIHJldHVybjtcblxuICAgIGNvbnN0IHRoZW1lU2VjdGlvbnMgPSBkb2N1bWVudC5xdWVyeVNlbGVjdG9yQWxsKFwiW2RhdGEtdGhlbWUtc2VjdGlvbl1cIik7XG5cbiAgICB0aGVtZVNlY3Rpb25zLmZvckVhY2goZnVuY3Rpb24gKHRoZW1lU2VjdGlvbikge1xuICAgICAgY29uc3QgcmVjdCA9IHRoZW1lU2VjdGlvbi5nZXRCb3VuZGluZ0NsaWVudFJlY3QoKTtcbiAgICAgIGNvbnN0IHRoZW1lU2VjdGlvblRvcCA9IHJlY3QudG9wO1xuICAgICAgY29uc3QgdGhlbWVTZWN0aW9uQm90dG9tID0gcmVjdC5ib3R0b207XG5cbiAgICAgIGlmIChcbiAgICAgICAgdGhlbWVTZWN0aW9uVG9wIDw9IHRoZW1lT2JzZXJ2ZXJPZmZzZXQgJiZcbiAgICAgICAgdGhlbWVTZWN0aW9uQm90dG9tID49IHRoZW1lT2JzZXJ2ZXJPZmZzZXRcbiAgICAgICkge1xuICAgICAgICBjb25zdCB0aGVtZVNlY3Rpb25BY3RpdmUgPVxuICAgICAgICAgIHRoZW1lU2VjdGlvbi5nZXRBdHRyaWJ1dGUoXCJkYXRhLXRoZW1lLXNlY3Rpb25cIik7XG4gICAgICAgIGRvY3VtZW50LnF1ZXJ5U2VsZWN0b3JBbGwoXCJbZGF0YS10aGVtZS1uYXZdXCIpLmZvckVhY2goZnVuY3Rpb24gKGVsZW0pIHtcbiAgICAgICAgICBpZiAoZWxlbS5nZXRBdHRyaWJ1dGUoXCJkYXRhLXRoZW1lLW5hdlwiKSAhPT0gdGhlbWVTZWN0aW9uQWN0aXZlKSB7XG4gICAgICAgICAgICBlbGVtLnNldEF0dHJpYnV0ZShcImRhdGEtdGhlbWUtbmF2XCIsIHRoZW1lU2VjdGlvbkFjdGl2ZSk7XG4gICAgICAgICAgfVxuICAgICAgICB9KTtcblxuICAgICAgICBjb25zdCBiZ1NlY3Rpb25BY3RpdmUgPSB0aGVtZVNlY3Rpb24uZ2V0QXR0cmlidXRlKFwiZGF0YS1iZy1zZWN0aW9uXCIpO1xuICAgICAgICBkb2N1bWVudC5xdWVyeVNlbGVjdG9yQWxsKFwiW2RhdGEtYmctbmF2XVwiKS5mb3JFYWNoKGZ1bmN0aW9uIChlbGVtKSB7XG4gICAgICAgICAgaWYgKGVsZW0uZ2V0QXR0cmlidXRlKFwiZGF0YS1iZy1uYXZcIikgIT09IGJnU2VjdGlvbkFjdGl2ZSkge1xuICAgICAgICAgICAgZWxlbS5zZXRBdHRyaWJ1dGUoXCJkYXRhLWJnLW5hdlwiLCBiZ1NlY3Rpb25BY3RpdmUpO1xuICAgICAgICAgIH1cbiAgICAgICAgfSk7XG4gICAgICB9XG4gICAgfSk7XG4gIH1cblxuICBmdW5jdGlvbiBzZXROYXZBdHRyaWJ1dGVzKHRoZW1lVmFsdWUsIGJnVmFsdWUpIHtcbiAgICBkb2N1bWVudC5xdWVyeVNlbGVjdG9yQWxsKFwiW2RhdGEtdGhlbWUtbmF2XVwiKS5mb3JFYWNoKGZ1bmN0aW9uIChlbGVtKSB7XG4gICAgICBlbGVtLnNldEF0dHJpYnV0ZShcImRhdGEtdGhlbWUtbmF2XCIsIHRoZW1lVmFsdWUpO1xuICAgIH0pO1xuICAgIGRvY3VtZW50LnF1ZXJ5U2VsZWN0b3JBbGwoXCJbZGF0YS1iZy1uYXZdXCIpLmZvckVhY2goZnVuY3Rpb24gKGVsZW0pIHtcbiAgICAgIGVsZW0uc2V0QXR0cmlidXRlKFwiZGF0YS1iZy1uYXZcIiwgYmdWYWx1ZSk7XG4gICAgfSk7XG4gIH1cblxuICBmdW5jdGlvbiBoYW5kbGVOYXZUb2dnbGUoKSB7XG4gICAgaXNOYXZPcGVuID0gIWlzTmF2T3BlbjtcblxuICAgIGlmIChpc05hdk9wZW4pIHtcbiAgICAgIHNldE5hdkF0dHJpYnV0ZXMoXCJkYXJrXCIsIFwidHJhbnNwYXJlbnRcIik7XG4gICAgfSBlbHNlIHtcbiAgICAgIC8vIEltbWVkaWF0ZWx5IHJlLWV2YWx1YXRlIGFnYWluc3QgY3VycmVudCBzY3JvbGwgcG9zaXRpb25cbiAgICAgIGNoZWNrVGhlbWVTZWN0aW9uKCk7XG4gICAgfVxuICB9XG5cbiAgZnVuY3Rpb24gc3RhcnRUaGVtZUNoZWNrKCkge1xuICAgIGRvY3VtZW50LmFkZEV2ZW50TGlzdGVuZXIoXCJzY3JvbGxcIiwgY2hlY2tUaGVtZVNlY3Rpb24pO1xuICB9XG5cbiAgZnVuY3Rpb24gYmluZE5hdlRvZ2dsZSgpIHtcbiAgICBkb2N1bWVudFxuICAgICAgLnF1ZXJ5U2VsZWN0b3JBbGwoXCJbZGF0YS1uYXZpZ2F0aW9uLXRvZ2dsZV1cIilcbiAgICAgIC5mb3JFYWNoKGZ1bmN0aW9uICh0b2dnbGUpIHtcbiAgICAgICAgdG9nZ2xlLmFkZEV2ZW50TGlzdGVuZXIoXCJjbGlja1wiLCBoYW5kbGVOYXZUb2dnbGUpO1xuICAgICAgfSk7XG4gIH1cblxuICBjaGVja1RoZW1lU2VjdGlvbigpO1xuICBzdGFydFRoZW1lQ2hlY2soKTtcbiAgYmluZE5hdlRvZ2dsZSgpO1xufVxuXG5mdW5jdGlvbiBpbml0TW91c2VNb3ZlKCkge1xuICB2YXIgTUFYX1JFTSA9IDEwO1xuICB2YXIgbWF4UHggPVxuICAgIE1BWF9SRU0gKiBwYXJzZUZsb2F0KGdldENvbXB1dGVkU3R5bGUoZG9jdW1lbnQuZG9jdW1lbnRFbGVtZW50KS5mb250U2l6ZSk7XG5cbiAgLy8gQmFpbCBvbiB0b3VjaCBkZXZpY2VzXG4gIGlmIChcIm9udG91Y2hzdGFydFwiIGluIHdpbmRvdykgcmV0dXJuO1xuXG4gIHZhciB0YXJnZXRzID0gW107XG5cbiAgJChcIltkYXRhLW1vdXNlLW1vdmUtc3RyZW5ndGhdXCIpLmVhY2goZnVuY3Rpb24gKCkge1xuICAgIHZhciBlbCA9ICQodGhpcylbMF07XG4gICAgdmFyIHN0cmVuZ3RoID0gcGFyc2VGbG9hdCgkKHRoaXMpLmF0dHIoXCJkYXRhLW1vdXNlLW1vdmUtc3RyZW5ndGhcIikpIHx8IDA7XG5cbiAgICB0YXJnZXRzLnB1c2goe1xuICAgICAgc3RyZW5ndGg6IHN0cmVuZ3RoLFxuICAgICAgeFRvOiBnc2FwLnF1aWNrVG8oZWwsIFwieFwiLCB7IGR1cmF0aW9uOiAxLjUsIGVhc2U6IFwicG93ZXIzXCIgfSksXG4gICAgICB5VG86IGdzYXAucXVpY2tUbyhlbCwgXCJ5XCIsIHsgZHVyYXRpb246IDEuNSwgZWFzZTogXCJwb3dlcjNcIiB9KSxcbiAgICB9KTtcbiAgfSk7XG5cbiAgaWYgKCF0YXJnZXRzLmxlbmd0aCkgcmV0dXJuO1xuXG4gICQod2luZG93KS5vbihcIm1vdXNlbW92ZVwiLCBmdW5jdGlvbiAoZSkge1xuICAgIC8vIC0xIOKApiAxIGZyb20gdmlld3BvcnQgY2VudGVyXG4gICAgdmFyIG54ID0gKGUuY2xpZW50WCAvIHdpbmRvdy5pbm5lcldpZHRoIC0gMC41KSAqIDI7XG4gICAgdmFyIG55ID0gKGUuY2xpZW50WSAvIHdpbmRvdy5pbm5lckhlaWdodCAtIDAuNSkgKiAyO1xuXG4gICAgdGFyZ2V0cy5mb3JFYWNoKGZ1bmN0aW9uICh0KSB7XG4gICAgICB0LnhUbyhueCAqIC1tYXhQeCAqIHQuc3RyZW5ndGgpO1xuICAgICAgdC55VG8obnkgKiAtbWF4UHggKiB0LnN0cmVuZ3RoKTtcbiAgICB9KTtcbiAgfSk7XG59XG5cbmZ1bmN0aW9uIGluaXRCb2xkRnVsbFNjcmVlbk5hdmlnYXRpb24oKSB7XG4gIC8vIFRvZ2dsZSBOYXZpZ2F0aW9uXG4gIGRvY3VtZW50XG4gICAgLnF1ZXJ5U2VsZWN0b3JBbGwoJ1tkYXRhLW5hdmlnYXRpb24tdG9nZ2xlPVwidG9nZ2xlXCJdJylcbiAgICAuZm9yRWFjaCgodG9nZ2xlQnRuKSA9PiB7XG4gICAgICB0b2dnbGVCdG4uYWRkRXZlbnRMaXN0ZW5lcihcImNsaWNrXCIsICgpID0+IHtcbiAgICAgICAgY29uc3QgbmF2U3RhdHVzRWwgPSBkb2N1bWVudC5xdWVyeVNlbGVjdG9yKFwiW2RhdGEtbmF2aWdhdGlvbi1zdGF0dXNdXCIpO1xuICAgICAgICBpZiAoIW5hdlN0YXR1c0VsKSByZXR1cm47XG4gICAgICAgIGlmIChcbiAgICAgICAgICBuYXZTdGF0dXNFbC5nZXRBdHRyaWJ1dGUoXCJkYXRhLW5hdmlnYXRpb24tc3RhdHVzXCIpID09PSBcIm5vdC1hY3RpdmVcIlxuICAgICAgICApIHtcbiAgICAgICAgICBuYXZTdGF0dXNFbC5zZXRBdHRyaWJ1dGUoXCJkYXRhLW5hdmlnYXRpb24tc3RhdHVzXCIsIFwiYWN0aXZlXCIpO1xuICAgICAgICAgIGxlbmlzLnN0b3AoKTtcbiAgICAgICAgfSBlbHNlIHtcbiAgICAgICAgICBuYXZTdGF0dXNFbC5zZXRBdHRyaWJ1dGUoXCJkYXRhLW5hdmlnYXRpb24tc3RhdHVzXCIsIFwibm90LWFjdGl2ZVwiKTtcbiAgICAgICAgICBsZW5pcy5zdGFydCgpOyAgICAgICAgfVxuICAgICAgfSk7XG4gICAgfSk7XG5cbiAgLy8gQ2xvc2UgTmF2aWdhdGlvblxuICBkb2N1bWVudFxuICAgIC5xdWVyeVNlbGVjdG9yQWxsKCdbZGF0YS1uYXZpZ2F0aW9uLXRvZ2dsZT1cImNsb3NlXCJdJylcbiAgICAuZm9yRWFjaCgoY2xvc2VCdG4pID0+IHtcbiAgICAgIGNsb3NlQnRuLmFkZEV2ZW50TGlzdGVuZXIoXCJjbGlja1wiLCAoKSA9PiB7XG4gICAgICAgIGNvbnN0IG5hdlN0YXR1c0VsID0gZG9jdW1lbnQucXVlcnlTZWxlY3RvcihcIltkYXRhLW5hdmlnYXRpb24tc3RhdHVzXVwiKTtcbiAgICAgICAgaWYgKCFuYXZTdGF0dXNFbCkgcmV0dXJuO1xuICAgICAgICBuYXZTdGF0dXNFbC5zZXRBdHRyaWJ1dGUoXCJkYXRhLW5hdmlnYXRpb24tc3RhdHVzXCIsIFwibm90LWFjdGl2ZVwiKTtcbiAgICAgICAgLy8gSWYgeW91IHVzZSBMZW5pcyB5b3UgY2FuICdzdGFydCcgTGVuaXMgaGVyZTogRXhhbXBsZSBMZW5pcy5zdGFydCgpO1xuICAgICAgfSk7XG4gICAgfSk7XG5cbiAgLy8gS2V5IEVTQyAtIENsb3NlIE5hdmlnYXRpb25cbiAgZG9jdW1lbnQuYWRkRXZlbnRMaXN0ZW5lcihcImtleWRvd25cIiwgKGUpID0+IHtcbiAgICBpZiAoZS5rZXlDb2RlID09PSAyNykge1xuICAgICAgY29uc3QgbmF2U3RhdHVzRWwgPSBkb2N1bWVudC5xdWVyeVNlbGVjdG9yKFwiW2RhdGEtbmF2aWdhdGlvbi1zdGF0dXNdXCIpO1xuICAgICAgaWYgKCFuYXZTdGF0dXNFbCkgcmV0dXJuO1xuICAgICAgaWYgKG5hdlN0YXR1c0VsLmdldEF0dHJpYnV0ZShcImRhdGEtbmF2aWdhdGlvbi1zdGF0dXNcIikgPT09IFwiYWN0aXZlXCIpIHtcbiAgICAgICAgbmF2U3RhdHVzRWwuc2V0QXR0cmlidXRlKFwiZGF0YS1uYXZpZ2F0aW9uLXN0YXR1c1wiLCBcIm5vdC1hY3RpdmVcIik7XG4gICAgICAgIC8vIElmIHlvdSB1c2UgTGVuaXMgeW91IGNhbiAnc3RhcnQnIExlbmlzIGhlcmU6IEV4YW1wbGUgTGVuaXMuc3RhcnQoKTtcbiAgICAgIH1cbiAgICB9XG4gIH0pO1xuXG4gICQoXCJbZGF0YS1uYXZiYXJdXCIpLmVhY2goZnVuY3Rpb24oKSB7XG4gICAgY29uc3QgbmF2ID0gJCh0aGlzKTtcblxuICAgIGNvbnN0IHNob3dBbmltID0gZ3NhcC5mcm9tKG5hdiwgeyBcbiAgICAgIHlQZXJjZW50OiAtMTAwLFxuICAgICAgcGF1c2VkOiB0cnVlLFxuICAgICAgZHVyYXRpb246IDAuNSxcbiAgICAgIGVhc2U6IFwicG93ZXIxLm91dFwiLFxuICAgICAgZWFzZVJldmVyc2U6IHRydWUsXG4gICAgfSkucHJvZ3Jlc3MoMSk7XG4gICAgXG4gICAgU2Nyb2xsVHJpZ2dlci5jcmVhdGUoe1xuICAgICAgc3RhcnQ6IFwidG9wIHRvcFwiLFxuICAgICAgZW5kOiBcIm1heFwiLFxuICAgICAgb25VcGRhdGU6IChzZWxmKSA9PiB7XG4gICAgICAgIHNlbGYuZGlyZWN0aW9uID09PSAtMSA/IHNob3dBbmltLnBsYXkoKSA6IHNob3dBbmltLnJldmVyc2UoKVxuICAgICAgfVxuICAgIH0pO1xuICB9KVxufVxuXG5mdW5jdGlvbiBpbml0Rm9vdGVyUGFyYWxsYXgoKSB7XG4gIGRvY3VtZW50LnF1ZXJ5U2VsZWN0b3JBbGwoXCJbZGF0YS1mb290ZXItcGFyYWxsYXhdXCIpLmZvckVhY2goKGVsKSA9PiB7XG4gICAgY29uc3QgdGwgPSBnc2FwLnRpbWVsaW5lKHtcbiAgICAgIHNjcm9sbFRyaWdnZXI6IHtcbiAgICAgICAgdHJpZ2dlcjogZWwsXG4gICAgICAgIHN0YXJ0OiBcImNsYW1wKHRvcCBib3R0b20pXCIsXG4gICAgICAgIGVuZDogXCJjbGFtcCh0b3AgdG9wKVwiLFxuICAgICAgICBzY3J1YjogdHJ1ZSxcbiAgICAgIH0sXG4gICAgfSk7XG5cbiAgICBjb25zdCBpbm5lciA9IGVsLnF1ZXJ5U2VsZWN0b3IoXCJbZGF0YS1mb290ZXItcGFyYWxsYXgtaW5uZXJdXCIpO1xuICAgIGNvbnN0IGRhcmsgPSBlbC5xdWVyeVNlbGVjdG9yKFwiW2RhdGEtZm9vdGVyLXBhcmFsbGF4LWRhcmtdXCIpO1xuXG4gICAgaWYgKGlubmVyKSB7XG4gICAgICB0bC5mcm9tKGlubmVyLCB7XG4gICAgICAgIHlQZXJjZW50OiAtMjUsXG4gICAgICAgIGVhc2U6IFwibGluZWFyXCIsXG4gICAgICB9KTtcbiAgICB9XG5cbiAgICBpZiAoZGFyaykge1xuICAgICAgdGwudG8oXG4gICAgICAgIGRhcmssXG4gICAgICAgIHtcbiAgICAgICAgICBvcGFjaXR5OiAwLFxuICAgICAgICAgIGVhc2U6IFwibGluZWFyXCIsXG4gICAgICAgIH0sXG4gICAgICAgIFwiPFwiXG4gICAgICApO1xuICAgIH1cbiAgfSk7XG59XG5cbmZ1bmN0aW9uIGluaXRJbWFnZVNlcXVlbmNlU2Nyb2xsKCkge1xuICBjb25zdCB3cmFwcyA9IGRvY3VtZW50LnF1ZXJ5U2VsZWN0b3JBbGwoXCJbZGF0YS1zZXF1ZW5jZS13cmFwXVwiKTtcbiAgY29uc3QgaW5zdGFuY2VzID0gW107XG5cbiAgd3JhcHMuZm9yRWFjaCgod3JhcCkgPT4ge1xuICAgIC8vIFByZXZlbnQgZG91YmxlLWluaXRpYWxpemluZ1xuICAgIGlmICh3cmFwLmRhdGFzZXQuc2VxdWVuY2VJbml0ID09PSBcInRydWVcIikgcmV0dXJuO1xuICAgIHdyYXAuZGF0YXNldC5zZXF1ZW5jZUluaXQgPSBcInRydWVcIjtcblxuICAgIGNvbnN0IGVsZW1lbnQgPSB3cmFwLnF1ZXJ5U2VsZWN0b3IoXCJbZGF0YS1zZXF1ZW5jZS1lbGVtZW50XVwiKTtcbiAgICBjb25zdCBjYW52YXMgPSBlbGVtZW50ICYmIGVsZW1lbnQucXVlcnlTZWxlY3RvcihcIltkYXRhLXNlcXVlbmNlLWNhbnZhc11cIik7XG4gICAgaWYgKCFlbGVtZW50IHx8ICFjYW52YXMpIHJldHVybjtcblxuICAgIC8vIERhdGEgYXR0cmlidXRlcyBhbmQgdGhlaXIgZmFsbGJhY2tzXG4gICAgY29uc3QgZnJhbWVzID0gcGFyc2VJbnQoY2FudmFzLmRhdGFzZXQuZnJhbWVzLCAxMCkgfHwgMTtcbiAgICBjb25zdCBkaWdpdHMgPSBwYXJzZUludChjYW52YXMuZGF0YXNldC5kaWdpdHMsIDEwKSB8fCAzO1xuICAgIGNvbnN0IGluZGV4U3RhcnQgPSBwYXJzZUludChjYW52YXMuZGF0YXNldC5pbmRleFN0YXJ0LCAxMCkgfHwgMDtcbiAgICBjb25zdCBkZXNrdG9wU3JjID0gY2FudmFzLmRhdGFzZXQuZGVza3RvcFNyYyB8fCBcIlwiO1xuICAgIGNvbnN0IG1vYmlsZVNyYyA9IGNhbnZhcy5kYXRhc2V0Lm1vYmlsZVNyYyB8fCBkZXNrdG9wU3JjO1xuICAgIGNvbnN0IHN0YXRpY1NyYyA9IGNhbnZhcy5kYXRhc2V0LnN0YXRpY1NyYztcbiAgICBjb25zdCBmaWxldHlwZSA9IGNhbnZhcy5kYXRhc2V0LmZpbGV0eXBlIHx8IFwiXCI7XG4gICAgY29uc3Qgc3RhcnRUcmlnZ2VyID0gd3JhcC5kYXRhc2V0LnNjcm9sbFN0YXJ0IHx8IFwidG9wIHRvcFwiO1xuICAgIGNvbnN0IGVuZFRyaWdnZXIgPSB3cmFwLmRhdGFzZXQuc2Nyb2xsRW5kIHx8IFwiYm90dG9tIGJvdHRvbVwiO1xuICAgIGNvbnN0IHJlZHVjZU1vdGlvbiA9IHdpbmRvdy5tYXRjaE1lZGlhKFxuICAgICAgXCIocHJlZmVycy1yZWR1Y2VkLW1vdGlvbjogcmVkdWNlKVwiXG4gICAgKS5tYXRjaGVzO1xuXG4gICAgY29uc3QgaXNNb2JpbGUgPSB3aW5kb3cubWF0Y2hNZWRpYShcIihtYXgtd2lkdGg6IDc2N3B4KVwiKS5tYXRjaGVzO1xuICAgIGNvbnN0IGJhc2VVcmwgPSBpc01vYmlsZSA/IG1vYmlsZVNyYyA6IGRlc2t0b3BTcmM7XG4gICAgY29uc3QgbGFzdEluZGV4ID0gaW5kZXhTdGFydCArIGZyYW1lcyAtIDE7XG5cbiAgICAvLyBUcmFjayBsYXN0IHJlbmRlcmVkIHNjcm9sbCBwcm9ncmVzcyBzbyB3ZSBjYW4gcmVkcmF3IG9uIHJlc2l6ZVxuICAgIGxldCBsYXN0UHJvZ3Jlc3MgPSAwO1xuXG4gICAgLy8gQ2FudmFzIHNldHVwIChzaXplIHRvIHRoZSBzdGlja3kgZWxlbWVudClcbiAgICBjb25zdCBjdHggPSBjYW52YXMuZ2V0Q29udGV4dChcIjJkXCIpO1xuICAgIGZ1bmN0aW9uIHJlc2l6ZUNhbnZhcygpIHtcbiAgICAgIGNvbnN0IHdpZHRoID0gZWxlbWVudC5jbGllbnRXaWR0aDtcbiAgICAgIGNvbnN0IGhlaWdodCA9IGVsZW1lbnQuY2xpZW50SGVpZ2h0O1xuXG4gICAgICAvLyBHdWFyZCBhZ2FpbnN0IGhpZGRlbi9kZXRhY2hlZCBlbGVtZW50cyB5aWVsZGluZyAww5cwXG4gICAgICBpZiAod2lkdGggPT09IDAgfHwgaGVpZ2h0ID09PSAwKSByZXR1cm47XG5cbiAgICAgIGNvbnN0IGRwciA9IHdpbmRvdy5kZXZpY2VQaXhlbFJhdGlvIHx8IDE7XG4gICAgICBpZiAoY2FudmFzLndpZHRoICE9PSB3aWR0aCAqIGRwciB8fCBjYW52YXMuaGVpZ2h0ICE9PSBoZWlnaHQgKiBkcHIpIHtcbiAgICAgICAgY2FudmFzLndpZHRoID0gd2lkdGggKiBkcHI7XG4gICAgICAgIGNhbnZhcy5oZWlnaHQgPSBoZWlnaHQgKiBkcHI7XG4gICAgICAgIGNhbnZhcy5zdHlsZS53aWR0aCA9IGAke3dpZHRofXB4YDtcbiAgICAgICAgY2FudmFzLnN0eWxlLmhlaWdodCA9IGAke2hlaWdodH1weGA7XG4gICAgICB9XG4gICAgfVxuICAgIHJlc2l6ZUNhbnZhcygpO1xuXG4gICAgLy8gSW1hZ2UgY2FjaGVcbiAgICBjb25zdCBsb2FkZWQgPSBuZXcgTWFwKCk7XG4gICAgY29uc3QgaW5mbGlnaHQgPSBuZXcgU2V0KCk7XG4gICAgbGV0IHJlc2l6ZVRpbWVyO1xuXG4gICAgLy8gVHJhY2sgbGFzdCBkcmF3biBmcmFtZSB0byBza2lwIHJlZHVuZGFudCByZWRyYXdzXG4gICAgbGV0IGxhc3REcmF3bkluZGV4ID0gLTE7XG4gICAgbGV0IHJhZklkID0gbnVsbDtcblxuICAgIC8vIEFib3J0Q29udHJvbGxlciBmb3IgY2xlYW51cCBvZiBnbG9iYWwgbGlzdGVuZXJzXG4gICAgY29uc3QgYWMgPSBuZXcgQWJvcnRDb250cm9sbGVyKCk7XG5cbiAgICAvLyBEcmF3IGhlbHBlciAoY2FudmFzIGVxdWl2YWxlbnQgb2Ygb2JqZWN0LWZpdDogY292ZXIpXG4gICAgZnVuY3Rpb24gZHJhd0NvdmVyKGltZykge1xuICAgICAgaWYgKCFpbWcpIHJldHVybjtcbiAgICAgIGNvbnN0IGNhbnZhc1dpZHRoID0gY2FudmFzLndpZHRoO1xuICAgICAgY29uc3QgY2FudmFzSGVpZ2h0ID0gY2FudmFzLmhlaWdodDtcbiAgICAgIGNvbnN0IHNjYWxlID0gTWF0aC5tYXgoXG4gICAgICAgIGNhbnZhc1dpZHRoIC8gaW1nLndpZHRoLFxuICAgICAgICBjYW52YXNIZWlnaHQgLyBpbWcuaGVpZ2h0XG4gICAgICApO1xuICAgICAgY29uc3QgeCA9IChjYW52YXNXaWR0aCAtIGltZy53aWR0aCAqIHNjYWxlKSAvIDI7XG4gICAgICBjb25zdCB5ID0gKGNhbnZhc0hlaWdodCAtIGltZy5oZWlnaHQgKiBzY2FsZSkgLyAyO1xuICAgICAgY3R4LmNsZWFyUmVjdCgwLCAwLCBjYW52YXNXaWR0aCwgY2FudmFzSGVpZ2h0KTtcbiAgICAgIGN0eC5kcmF3SW1hZ2UoaW1nLCB4LCB5LCBpbWcud2lkdGggKiBzY2FsZSwgaW1nLmhlaWdodCAqIHNjYWxlKTtcbiAgICB9XG5cbiAgICB3aW5kb3cuYWRkRXZlbnRMaXN0ZW5lcihcbiAgICAgIFwicmVzaXplXCIsXG4gICAgICAoKSA9PiB7XG4gICAgICAgIGNsZWFyVGltZW91dChyZXNpemVUaW1lcik7XG4gICAgICAgIHJlc2l6ZVRpbWVyID0gc2V0VGltZW91dCgoKSA9PiB7XG4gICAgICAgICAgcmVzaXplQ2FudmFzKCk7XG4gICAgICAgICAgLy8gUmVzZXQgc28gdGhlIG5leHQgcmVuZGVyIGFjdHVhbGx5IHJlZHJhd3MgYXQgdGhlIG5ldyBzaXplXG4gICAgICAgICAgbGFzdERyYXduSW5kZXggPSAtMTtcbiAgICAgICAgICBpZiAobG9hZGVkLnNpemUpIHJlbmRlcihsYXN0UHJvZ3Jlc3MpO1xuICAgICAgICAgIC8vIFNjcm9sbFRyaWdnZXIgYWxyZWFkeSBkZWJvdW5jZXMgcmVzaXplIGludGVybmFsbHkg4oCUXG4gICAgICAgICAgLy8gbm8gbWFudWFsIHJlZnJlc2ggbmVlZGVkIGhlcmVcbiAgICAgICAgfSwgMjAwKTtcbiAgICAgIH0sXG4gICAgICB7IHNpZ25hbDogYWMuc2lnbmFsIH1cbiAgICApO1xuXG4gICAgZnVuY3Rpb24gcGFkKG51bSkge1xuICAgICAgcmV0dXJuIFN0cmluZyhudW0pLnBhZFN0YXJ0KGRpZ2l0cywgXCIwXCIpO1xuICAgIH1cblxuICAgIGZ1bmN0aW9uIGdldFVybChpKSB7XG4gICAgICByZXR1cm4gYCR7YmFzZVVybH0ke3BhZChpKX1gO1xuICAgIH1cblxuICAgIC8vIC0tLSBDb25jdXJyZW50IGJpbmFyeSBtaWRwb2ludCBsb2FkZXIgLS0tXG4gICAgY29uc3QgQ09OQ1VSUkVOQ1kgPSA0O1xuICAgIGNvbnN0IHF1ZXVlID0gW107XG4gICAgbGV0IGFjdGl2ZUxvYWRzID0gMDtcblxuICAgIGZ1bmN0aW9uIGxvYWRGcmFtZShpLCBvbkRvbmUpIHtcbiAgICAgIGlmIChsb2FkZWQuaGFzKGkpIHx8IGluZmxpZ2h0LmhhcyhpKSB8fCBpIDwgaW5kZXhTdGFydCB8fCBpID4gbGFzdEluZGV4KSB7XG4gICAgICAgIGlmICh0eXBlb2Ygb25Eb25lID09PSBcImZ1bmN0aW9uXCIpIG9uRG9uZSgpO1xuICAgICAgICByZXR1cm47XG4gICAgICB9XG5cbiAgICAgIGluZmxpZ2h0LmFkZChpKTtcbiAgICAgIGFjdGl2ZUxvYWRzKys7XG5cbiAgICAgIGNvbnN0IGltZyA9IG5ldyBJbWFnZSgpO1xuICAgICAgaW1nLnNyYyA9IGdldFVybChpKTtcblxuICAgICAgaW1nLm9ubG9hZCA9ICgpID0+IHtcbiAgICAgICAgLy8gRGVjb2RlIG9mZiBtYWluIHRocmVhZCBiZWZvcmUgc3RvcmluZyDigJQgcHJldmVudHMgamFuayBvbiBmaXJzdCBkcmF3XG4gICAgICAgIGltZ1xuICAgICAgICAgIC5kZWNvZGUoKVxuICAgICAgICAgIC5jYXRjaCgoKSA9PiB7fSlcbiAgICAgICAgICAudGhlbigoKSA9PiB7XG4gICAgICAgICAgICBsb2FkZWQuc2V0KGksIGltZyk7XG4gICAgICAgICAgICBpbmZsaWdodC5kZWxldGUoaSk7XG4gICAgICAgICAgICBhY3RpdmVMb2Fkcy0tO1xuICAgICAgICAgICAgaWYgKHR5cGVvZiBvbkRvbmUgPT09IFwiZnVuY3Rpb25cIikgb25Eb25lKCk7XG4gICAgICAgICAgICBkcmFpblF1ZXVlKCk7XG4gICAgICAgICAgfSk7XG4gICAgICB9O1xuXG4gICAgICBpbWcub25lcnJvciA9ICgpID0+IHtcbiAgICAgICAgaW5mbGlnaHQuZGVsZXRlKGkpO1xuICAgICAgICBhY3RpdmVMb2Fkcy0tO1xuICAgICAgICBjb25zb2xlLndhcm4oXCJbSW1hZ2VTZXF1ZW5jZV0gRmFpbGVkIHRvIGxvYWQgZnJhbWVcIiwge1xuICAgICAgICAgIGluZGV4OiBpLFxuICAgICAgICAgIHVybDogZ2V0VXJsKGkpLFxuICAgICAgICB9KTtcbiAgICAgICAgZHJhaW5RdWV1ZSgpO1xuICAgICAgfTtcbiAgICB9XG5cbiAgICBmdW5jdGlvbiBkcmFpblF1ZXVlKCkge1xuICAgICAgd2hpbGUgKGFjdGl2ZUxvYWRzIDwgQ09OQ1VSUkVOQ1kgJiYgcXVldWUubGVuZ3RoID4gMCkge1xuICAgICAgICBjb25zdCBbYSwgYl0gPSBxdWV1ZS5zaGlmdCgpO1xuXG4gICAgICAgIGlmIChiIC0gYSA8PSAxKSBjb250aW51ZTtcblxuICAgICAgICBjb25zdCBtID0gTWF0aC5mbG9vcigoYSArIGIpIC8gMik7XG4gICAgICAgIGxvYWRGcmFtZShtLCAoKSA9PiB7XG4gICAgICAgICAgLy8gT25seSBlbnF1ZXVlIHN1Yi1yYW5nZXMgdGhhdCBjb250YWluIGF0IGxlYXN0IG9uZSB1bmxvYWRlZCBmcmFtZVxuICAgICAgICAgIGlmIChtIC0gYSA+IDEpIHF1ZXVlLnB1c2goW2EsIG1dKTtcbiAgICAgICAgICBpZiAoYiAtIG0gPiAxKSBxdWV1ZS5wdXNoKFttLCBiXSk7XG4gICAgICAgICAgZHJhaW5RdWV1ZSgpO1xuICAgICAgICB9KTtcbiAgICAgIH1cbiAgICB9XG5cbiAgICBmdW5jdGlvbiBzdGFydExvYWRpbmcoKSB7XG4gICAgICBsb2FkRnJhbWUoaW5kZXhTdGFydCwgKCkgPT4ge1xuICAgICAgICBsYXN0RHJhd25JbmRleCA9IC0xOyAvLyBFbnN1cmUgZmlyc3QgZnJhbWUgZHJhd3NcbiAgICAgICAgZHJhd0ltYWdlQXQoaW5kZXhTdGFydCk7XG4gICAgICAgIFNjcm9sbFRyaWdnZXIucmVmcmVzaCgpO1xuXG4gICAgICAgIHF1ZXVlLnB1c2goW2luZGV4U3RhcnQsIGxhc3RJbmRleF0pO1xuICAgICAgICBkcmFpblF1ZXVlKCk7XG4gICAgICB9KTtcblxuICAgICAgbG9hZEZyYW1lKGxhc3RJbmRleCk7XG4gICAgfVxuXG4gICAgZnVuY3Rpb24gZmluZE5lYXJlc3RMb2FkZWQoaSkge1xuICAgICAgLy8gwrExMCBsaW5lYXIgc2NhbiBjb3ZlcnMgbmVhcmx5IGFsbCByZWFsLXdvcmxkIGNhc2VzIG9uY2UgbG9hZGluZ1xuICAgICAgLy8gaXMgdW5kZXJ3YXkuIEFueXRoaW5nIGZ1cnRoZXIgb3V0IG1lYW5zIGZyYW1lcyBzaW1wbHkgYXJlbid0XG4gICAgICAvLyByZWFkeSB5ZXQg4oCUIHJldHVybmluZyBudWxsIGxldHMgdGhlIGNhbnZhcyBob2xkIHRoZSBsYXN0IGRyYXduXG4gICAgICAvLyBmcmFtZSByYXRoZXIgdGhhbiBodW50aW5nIHRocm91Z2ggaHVuZHJlZHMgb2Yga2V5cy5cbiAgICAgIGZvciAobGV0IHIgPSAxOyByIDw9IDEwOyByKyspIHtcbiAgICAgICAgaWYgKGxvYWRlZC5oYXMoaSAtIHIpKSByZXR1cm4gaSAtIHI7XG4gICAgICAgIGlmIChsb2FkZWQuaGFzKGkgKyByKSkgcmV0dXJuIGkgKyByO1xuICAgICAgfVxuICAgICAgcmV0dXJuIG51bGw7XG4gICAgfVxuXG4gICAgZnVuY3Rpb24gZHJhd0ltYWdlQXQoaSkge1xuICAgICAgY29uc3QgaW1nID0gbG9hZGVkLmdldChpKTtcbiAgICAgIGlmICghaW1nKSByZXR1cm47XG4gICAgICBsYXN0RHJhd25JbmRleCA9IGk7XG4gICAgICBkcmF3Q292ZXIoaW1nKTtcbiAgICB9XG5cbiAgICBmdW5jdGlvbiByZW5kZXIocHJvZ3Jlc3MpIHtcbiAgICAgIGNvbnN0IHJlbGF0aXZlID0gcHJvZ3Jlc3MgKiAoZnJhbWVzIC0gMSk7XG4gICAgICBjb25zdCBpbmRleCA9IGluZGV4U3RhcnQgKyBNYXRoLnJvdW5kKHJlbGF0aXZlKTtcblxuICAgICAgLy8gU2tpcCBpZiB3ZSdkIGRyYXcgdGhlIGV4YWN0IHNhbWUgZnJhbWVcbiAgICAgIGlmIChpbmRleCA9PT0gbGFzdERyYXduSW5kZXgpIHJldHVybjtcblxuICAgICAgbGV0IHRhcmdldCA9IGluZGV4O1xuICAgICAgaWYgKCFsb2FkZWQuaGFzKGluZGV4KSkge1xuICAgICAgICBjb25zdCBuZWFyZXN0ID0gZmluZE5lYXJlc3RMb2FkZWQoaW5kZXgpO1xuICAgICAgICBpZiAobmVhcmVzdCA9PT0gbnVsbCkgcmV0dXJuO1xuICAgICAgICB0YXJnZXQgPSBuZWFyZXN0O1xuICAgICAgfVxuXG4gICAgICAvLyBTdGlsbCB0aGUgc2FtZSB2aXN1YWwgZnJhbWUgYWZ0ZXIgZmFsbGJhY2sg4oCUIHNraXBcbiAgICAgIGlmICh0YXJnZXQgPT09IGxhc3REcmF3bkluZGV4KSByZXR1cm47XG5cbiAgICAgIGRyYXdJbWFnZUF0KHRhcmdldCk7XG4gICAgfVxuXG4gICAgLy8gQmF0Y2ggc2Nyb2xsIHVwZGF0ZXMgaW50byBhIHNpbmdsZSByQUZcbiAgICBmdW5jdGlvbiBvblNjcm9sbFVwZGF0ZShzZWxmKSB7XG4gICAgICBsYXN0UHJvZ3Jlc3MgPSBzZWxmLnByb2dyZXNzO1xuICAgICAgaWYgKHJhZklkKSByZXR1cm47XG4gICAgICByYWZJZCA9IHJlcXVlc3RBbmltYXRpb25GcmFtZSgoKSA9PiB7XG4gICAgICAgIHJhZklkID0gbnVsbDtcbiAgICAgICAgcmVuZGVyKGxhc3RQcm9ncmVzcyk7XG4gICAgICB9KTtcbiAgICB9XG5cbiAgICAvLyBSZWR1Y2VkIG1vdGlvbjogZHJhdyBhIHNpbmdsZSBzdGF0aWMgaW1hZ2UgKG9yIGZpcnN0IGZyYW1lIGZhbGxiYWNrKVxuICAgIGlmIChyZWR1Y2VNb3Rpb24pIHtcbiAgICAgIGlmIChzdGF0aWNTcmMpIHtcbiAgICAgICAgY29uc3Qgc3RhdGljSW1hZ2UgPSBuZXcgSW1hZ2UoKTtcbiAgICAgICAgc3RhdGljSW1hZ2Uuc3JjID0gc3RhdGljU3JjO1xuICAgICAgICBzdGF0aWNJbWFnZS5vbmxvYWQgPSAoKSA9PiB7XG4gICAgICAgICAgZHJhd0NvdmVyKHN0YXRpY0ltYWdlKTtcbiAgICAgICAgfTtcbiAgICAgICAgc3RhdGljSW1hZ2Uub25lcnJvciA9ICgpID0+IHt9O1xuICAgICAgICBpbnN0YW5jZXMucHVzaCh7IHdyYXAsIGRlc3Ryb3k6ICgpID0+IGFjLmFib3J0KCkgfSk7XG4gICAgICAgIHJldHVybjtcbiAgICAgIH1cbiAgICAgIGxvYWRGcmFtZShpbmRleFN0YXJ0LCAoKSA9PiB7XG4gICAgICAgIGRyYXdJbWFnZUF0KGluZGV4U3RhcnQpO1xuICAgICAgfSk7XG4gICAgICBpbnN0YW5jZXMucHVzaCh7IHdyYXAsIGRlc3Ryb3k6ICgpID0+IGFjLmFib3J0KCkgfSk7XG4gICAgICByZXR1cm47XG4gICAgfVxuXG4gICAgLy8gQmVnaW4gbG9hZGluZyBmcmFtZXMgaW1tZWRpYXRlbHlcbiAgICBzdGFydExvYWRpbmcoKTtcblxuICAgIC8vIFNldCB1cCBTY3JvbGxUcmlnZ2VyXG4gICAgY29uc3Qgc3QgPSBTY3JvbGxUcmlnZ2VyLmNyZWF0ZSh7XG4gICAgICB0cmlnZ2VyOiB3cmFwLFxuICAgICAgc3RhcnQ6IHN0YXJ0VHJpZ2dlcixcbiAgICAgIGVuZDogZW5kVHJpZ2dlcixcbiAgICAgIHNjcnViOiB0cnVlLFxuICAgICAgb25VcGRhdGU6IG9uU2Nyb2xsVXBkYXRlLFxuICAgIH0pO1xuXG4gICAgLy8gRHJhdyBvbmNlIGltbWVkaWF0ZWx5XG4gICAgbGFzdFByb2dyZXNzID0gc3QucHJvZ3Jlc3MgfHwgMDtcbiAgICByZW5kZXIobGFzdFByb2dyZXNzKTtcblxuICAgIC8vIEV4cG9zZSBkZXN0cm95IGZvciBjbGVhbnVwIChCYXJiYSB0cmFuc2l0aW9ucywgU1BBIHRlYXJkb3duLCBldGMuKVxuICAgIGluc3RhbmNlcy5wdXNoKHtcbiAgICAgIHdyYXAsXG4gICAgICBkZXN0cm95KCkge1xuICAgICAgICBhYy5hYm9ydCgpO1xuICAgICAgICBpZiAocmFmSWQpIGNhbmNlbEFuaW1hdGlvbkZyYW1lKHJhZklkKTtcbiAgICAgICAgc3Qua2lsbCgpO1xuICAgICAgICBsb2FkZWQuY2xlYXIoKTtcbiAgICAgICAgaW5mbGlnaHQuY2xlYXIoKTtcbiAgICAgICAgcXVldWUubGVuZ3RoID0gMDtcbiAgICAgICAgd3JhcC5kYXRhc2V0LnNlcXVlbmNlSW5pdCA9IFwiXCI7XG4gICAgICB9LFxuICAgIH0pO1xuICB9KTtcblxuICAvLyBSZXR1cm4gYWxsIGluc3RhbmNlcyBzbyBjYWxsZXJzIGNhbiB0ZWFyIGRvd24gd2hlbiBuZWVkZWRcbiAgcmV0dXJuIGluc3RhbmNlcztcbn1cblxuZnVuY3Rpb24gaW5pdEFjY29yZGlvbkNTUygpIHtcbiAgZG9jdW1lbnRcbiAgICAucXVlcnlTZWxlY3RvckFsbChcIltkYXRhLWFjY29yZGlvbi1jc3MtaW5pdF1cIilcbiAgICAuZm9yRWFjaCgoYWNjb3JkaW9uKSA9PiB7XG4gICAgICBjb25zdCBjbG9zZVNpYmxpbmdzID1cbiAgICAgICAgYWNjb3JkaW9uLmdldEF0dHJpYnV0ZShcImRhdGEtYWNjb3JkaW9uLWNsb3NlLXNpYmxpbmdzXCIpID09PSBcInRydWVcIjtcblxuICAgICAgYWNjb3JkaW9uLmFkZEV2ZW50TGlzdGVuZXIoXCJjbGlja1wiLCAoZXZlbnQpID0+IHtcbiAgICAgICAgY29uc3QgdG9nZ2xlID0gZXZlbnQudGFyZ2V0LmNsb3Nlc3QoXCJbZGF0YS1hY2NvcmRpb24tdG9nZ2xlXVwiKTtcbiAgICAgICAgaWYgKCF0b2dnbGUpIHJldHVybjsgLy8gRXhpdCBpZiB0aGUgY2xpY2tlZCBlbGVtZW50IGlzIG5vdCBhIHRvZ2dsZVxuXG4gICAgICAgIGNvbnN0IHNpbmdsZUFjY29yZGlvbiA9IHRvZ2dsZS5jbG9zZXN0KFwiW2RhdGEtYWNjb3JkaW9uLXN0YXR1c11cIik7XG4gICAgICAgIGlmICghc2luZ2xlQWNjb3JkaW9uKSByZXR1cm47IC8vIEV4aXQgaWYgbm8gYWNjb3JkaW9uIGNvbnRhaW5lciBpcyBmb3VuZFxuXG4gICAgICAgIGNvbnN0IGlzQWN0aXZlID1cbiAgICAgICAgICBzaW5nbGVBY2NvcmRpb24uZ2V0QXR0cmlidXRlKFwiZGF0YS1hY2NvcmRpb24tc3RhdHVzXCIpID09PSBcImFjdGl2ZVwiO1xuICAgICAgICBzaW5nbGVBY2NvcmRpb24uc2V0QXR0cmlidXRlKFxuICAgICAgICAgIFwiZGF0YS1hY2NvcmRpb24tc3RhdHVzXCIsXG4gICAgICAgICAgaXNBY3RpdmUgPyBcIm5vdC1hY3RpdmVcIiA6IFwiYWN0aXZlXCJcbiAgICAgICAgKTtcblxuICAgICAgICAvLyBXaGVuIFtkYXRhLWFjY29yZGlvbi1jbG9zZS1zaWJsaW5ncz1cInRydWVcIl1cbiAgICAgICAgaWYgKGNsb3NlU2libGluZ3MgJiYgIWlzQWN0aXZlKSB7XG4gICAgICAgICAgYWNjb3JkaW9uXG4gICAgICAgICAgICAucXVlcnlTZWxlY3RvckFsbCgnW2RhdGEtYWNjb3JkaW9uLXN0YXR1cz1cImFjdGl2ZVwiXScpXG4gICAgICAgICAgICAuZm9yRWFjaCgoc2libGluZykgPT4ge1xuICAgICAgICAgICAgICBpZiAoc2libGluZyAhPT0gc2luZ2xlQWNjb3JkaW9uKVxuICAgICAgICAgICAgICAgIHNpYmxpbmcuc2V0QXR0cmlidXRlKFwiZGF0YS1hY2NvcmRpb24tc3RhdHVzXCIsIFwibm90LWFjdGl2ZVwiKTtcbiAgICAgICAgICAgIH0pO1xuICAgICAgICB9XG4gICAgICB9KTtcbiAgICB9KTtcbn1cblxuZnVuY3Rpb24gaW5pdEJhc2ljRmxpcCgpIHtcbiAgJChcIltkYXRhLWZsaXAtZ3JvdXBdXCIpLmVhY2goZnVuY3Rpb24gKCkge1xuICAgIGNvbnN0IGdyb3VwID0gJCh0aGlzKTtcbiAgICBjb25zdCBlbCA9IGdyb3VwLmZpbmQoXCJbZGF0YS1mbGlwLWVsZW1lbnRdXCIpO1xuICAgIGNvbnN0IGlkID0gZWwuYXR0cihcImRhdGEtZmxpcC1lbGVtZW50XCIpO1xuICAgIGNvbnN0IGRlc3RpbmF0aW9uID0gZ3JvdXAuZmluZChgW2RhdGEtZmxpcC1kZXN0aW5hdGlvbj1cIiR7aWR9XCJdYCk7XG4gICAgaWYgKCFlbC5sZW5ndGggfHwgIWRlc3RpbmF0aW9uLmxlbmd0aCkgcmV0dXJuO1xuXG4gICAgY29uc3Qgc3RhdGUgPSBGbGlwLmdldFN0YXRlKGVsWzBdKTtcblxuICAgIC8vIE1vdmUgZWxlbWVudCBpbnRvIGRlc3RpbmF0aW9uXG4gICAgZWwuYXBwZW5kVG8oZGVzdGluYXRpb24pO1xuXG4gICAgY29uc3Qgc2Nyb2xsU3RhcnRSYXcgPSBncm91cC5hdHRyKFwiZGF0YS1mbGlwLXNjcm9sbC1zdGFydFwiKSB8fCBcInRvcCBjZW50ZXJcIjtcbiAgICBjb25zdCBzY3JvbGxTdGFydCA9IGBjbGFtcCgke3Njcm9sbFN0YXJ0UmF3fSlgO1xuXG4gICAgY29uc3Qgc2Nyb2xsRW5kUmF3ID0gZ3JvdXAuYXR0cihcImRhdGEtZmxpcC1zY3JvbGwtZW5kXCIpIHx8IFwiYm90dG9tIGJvdHRvbVwiO1xuICAgIGNvbnN0IHNjcm9sbEVuZCA9IGBjbGFtcCgke3Njcm9sbEVuZFJhd30pYDtcblxuICAgIGNvbnN0IHRsID0gZ3NhcC50aW1lbGluZSh7XG4gICAgICBvblN0YXJ0OiAoKSA9PiB7XG4gICAgICAgIFNjcm9sbFRyaWdnZXIucmVmcmVzaCgpO1xuICAgICAgfSxcbiAgICAgIHNjcm9sbFRyaWdnZXI6IHtcbiAgICAgICAgdHJpZ2dlcjogZ3JvdXBbMF0sXG4gICAgICAgIHN0YXJ0OiBzY3JvbGxTdGFydCxcbiAgICAgICAgZW5kOiBzY3JvbGxFbmQsXG4gICAgICAgIHNjcnViOiAwLjUsXG4gICAgICB9LFxuICAgIH0pO1xuXG4gICAgdGwuYWRkKFxuICAgICAgRmxpcC5mcm9tKHN0YXRlLCB7XG4gICAgICAgIC8vIGR1cmF0aW9uOiAwLjYsXG4gICAgICAgIGFic29sdXRlOiB0cnVlLFxuICAgICAgICBlYXNlOiBcInBvd2VyMS5pbk91dFwiLFxuICAgICAgfSlcbiAgICApO1xuICB9KTtcbn1cblxuZnVuY3Rpb24gaW5pdFdvcmtWaWV3cygpIHtcbiAgY29uc3QgZ3JvdXBzID0gZG9jdW1lbnQucXVlcnlTZWxlY3RvckFsbChcIltkYXRhLXdvcmstZ3JvdXBdXCIpO1xuICBpZiAoIWdyb3Vwcy5sZW5ndGgpIHJldHVybjtcblxuICBncm91cHMuZm9yRWFjaChmdW5jdGlvbiAoZ3JvdXApIHtcbiAgICBpZiAoZ3JvdXAuZGF0YXNldC5qc0luaXQgPT09IFwidHJ1ZVwiKSByZXR1cm47XG4gICAgZ3JvdXAuZGF0YXNldC5qc0luaXQgPSBcInRydWVcIjtcblxuICAgIGNvbnN0IGlubmVyID0gZ3JvdXAucXVlcnlTZWxlY3RvcihcIltkYXRhLXdvcmstZ3JvdXAtaW5uZXJdXCIpO1xuICAgIGNvbnN0IGJ1dHRvbnMgPSBncm91cC5xdWVyeVNlbGVjdG9yQWxsKFwiW2RhdGEtd29yay1idXR0b25dXCIpO1xuICAgIGNvbnN0IGdhbGxlcnkgPSBncm91cC5xdWVyeVNlbGVjdG9yKFwiW2RhdGEtd29yay1nYWxsZXJ5XVwiKTtcbiAgICBjb25zdCBsaXN0ID0gZ3JvdXAucXVlcnlTZWxlY3RvcihcIltkYXRhLXdvcmstbGlzdF1cIik7XG5cbiAgICBpZiAoIWlubmVyIHx8ICFnYWxsZXJ5IHx8ICFsaXN0KSByZXR1cm47XG5cbiAgICBsZXQgY3VycmVudFN0YXRlID0gXCJnYWxsZXJ5XCI7XG4gICAgbGV0IGFjdGl2ZVRsID0gbnVsbDtcblxuICAgIC8vIHNldCBpbml0aWFsIHN0YXRlXG4gICAgZ3JvdXAuc2V0QXR0cmlidXRlKFwiZGF0YS13b3JrLXN0YXRlXCIsIFwiZ2FsbGVyeVwiKTtcbiAgICBnc2FwLnNldChsaXN0LCB7XG4gICAgICBwb3NpdGlvbjogXCJhYnNvbHV0ZVwiLFxuICAgICAgeFBlcmNlbnQ6IDUwLFxuICAgICAgc2NhbGU6IDAuMjUsXG4gICAgICBvcGFjaXR5OiAwLFxuICAgIH0pO1xuXG4gICAgZnVuY3Rpb24gc3dpdGNoVmlldyhuZXdTdGF0ZSkge1xuICAgICAgaWYgKG5ld1N0YXRlID09PSBjdXJyZW50U3RhdGUpIHJldHVybjtcblxuICAgICAgaWYgKGFjdGl2ZVRsKSBhY3RpdmVUbC5raWxsKCk7XG5cbiAgICAgIGNvbnN0IGlzVG9MaXN0ID0gbmV3U3RhdGUgPT09IFwibGlzdFwiO1xuICAgICAgY29uc3Qgb3V0Z29pbmcgPSBpc1RvTGlzdCA/IGdhbGxlcnkgOiBsaXN0O1xuICAgICAgY29uc3QgaW5jb21pbmcgPSBpc1RvTGlzdCA/IGxpc3QgOiBnYWxsZXJ5O1xuXG4gICAgICBjb25zdCBvdXRYID0gaXNUb0xpc3QgPyAtNTAgOiA1MDtcbiAgICAgIGNvbnN0IGluWCA9IGlzVG9MaXN0ID8gNTAgOiAtNTA7XG5cbiAgICAgIGN1cnJlbnRTdGF0ZSA9IG5ld1N0YXRlO1xuICAgICAgZ3JvdXAuc2V0QXR0cmlidXRlKFwiZGF0YS13b3JrLXN0YXRlXCIsIG5ld1N0YXRlKTtcblxuICAgICAgLy8gbG9jayBjb250YWluZXIgaGVpZ2h0IHNvIGl0IGRvZXNuJ3QgY29sbGFwc2Ugd2hlbiBib3RoIGNoaWxkcmVuIGFyZSBhYnNvbHV0ZVxuICAgICAgZ3NhcC5zZXQoaW5uZXIsIHsgaGVpZ2h0OiBpbm5lci5vZmZzZXRIZWlnaHQgfSk7XG5cbiAgICAgIC8vIGJvdGggYWJzb2x1dGUgZHVyaW5nIHRoZSBhbmltYXRpb24g4oCUIG5vIGxheW91dCBqdW1wc1xuICAgICAgZ3NhcC5zZXQoaW5jb21pbmcsIHtcbiAgICAgICAgcG9zaXRpb246IFwiYWJzb2x1dGVcIixcbiAgICAgICAgbGVmdDogMCxcbiAgICAgICAgdG9wOiAwLFxuICAgICAgICByaWdodDogMCxcbiAgICAgICAgeFBlcmNlbnQ6IGluWCxcbiAgICAgICAgc2NhbGU6IDAuMjUsXG4gICAgICAgIG9wYWNpdHk6IDAsXG4gICAgICB9KTtcblxuICAgICAgYWN0aXZlVGwgPSBnc2FwLnRpbWVsaW5lKHtcbiAgICAgICAgb25Db21wbGV0ZTogZnVuY3Rpb24gKCkge1xuICAgICAgICAgIC8vIGluY29taW5nIHRha2VzIG92ZXIgbGF5b3V0IGZsb3csIG91dGdvaW5nIHN0YXlzIHBhcmtlZFxuICAgICAgICAgIGdzYXAuc2V0KGluY29taW5nLCB7XG4gICAgICAgICAgICBwb3NpdGlvbjogXCJyZWxhdGl2ZVwiLFxuICAgICAgICAgIH0pO1xuICAgICAgICAgIGdzYXAuc2V0KGlubmVyLCB7IGNsZWFyUHJvcHM6IFwiaGVpZ2h0XCIgfSk7XG4gICAgICAgICAgYWN0aXZlVGwgPSBudWxsO1xuICAgICAgICAgIFNjcm9sbFRyaWdnZXIucmVmcmVzaCgpO1xuICAgICAgICAgIGdzYXAudG8oaW5jb21pbmcucXVlcnlTZWxlY3RvckFsbChcIltkb25lLWRlYWwtaW1hZ2Utd3JhcF1cIiksIHtcbiAgICAgICAgICAgIGNsaXBQYXRoOiBcInBvbHlnb24oMCUgMCUsIDEwMCUgMCUsIDEwMCUgMTAwJSwgMCUgMTAwJSlcIixcbiAgICAgICAgICAgIGR1cmF0aW9uOiAxLFxuICAgICAgICAgICAgZWFzZTogXCJleHBvLm91dFwiLFxuICAgICAgICAgICAgc3RhZ2dlcjoge1xuICAgICAgICAgICAgICBlYWNoOiAwLjEsXG4gICAgICAgICAgICB9LFxuICAgICAgICAgICAgb25Db21wbGV0ZTogKCkgPT4ge1xuICAgICAgICAgICAgICBnc2FwLnNldChcIltkb25lLWRlYWwtaW1hZ2Utd3JhcF1cIiwge1xuICAgICAgICAgICAgICAgIGJhY2tncm91bmRDb2xvcjogXCJ0cmFuc3BhcmVudFwiLFxuICAgICAgICAgICAgICB9KTtcbiAgICAgICAgICAgIH0sXG4gICAgICAgICAgfSk7XG4gICAgICAgIH0sXG4gICAgICB9KTtcblxuICAgICAgYWN0aXZlVGwudG8ob3V0Z29pbmcsIHtcbiAgICAgICAgeFBlcmNlbnQ6IG91dFgsXG4gICAgICAgIHNjYWxlOiAwLjI1LFxuICAgICAgICBvcGFjaXR5OiAwLFxuICAgICAgICBkdXJhdGlvbjogMSxcbiAgICAgICAgZWFzZTogXCJleHBvLmluT3V0XCIsXG4gICAgICAgIG9uQ29tcGxldGU6ICgpID0+IHtcbiAgICAgICAgICBnc2FwLnNldChvdXRnb2luZywge1xuICAgICAgICAgICAgcG9zaXRpb246IFwiYWJzb2x1dGVcIixcbiAgICAgICAgICB9KTtcbiAgICAgICAgfSxcbiAgICAgIH0pO1xuXG4gICAgICBhY3RpdmVUbC5zZXQoXG4gICAgICAgIGluY29taW5nLnF1ZXJ5U2VsZWN0b3JBbGwoXCJbZG9uZS1kZWFsLWltYWdlLXdyYXBdXCIpLFxuICAgICAgICB7XG4gICAgICAgICAgY2xpcFBhdGg6IFwicG9seWdvbigwJSAxMDAlLCAxMDAlIDEwMCUsIDEwMCUgMTAwJSwgMCUgMTAwJSlcIixcbiAgICAgICAgfSxcbiAgICAgICAgXCI8XCJcbiAgICAgICk7XG5cbiAgICAgIGFjdGl2ZVRsLnRvKFxuICAgICAgICBpbmNvbWluZyxcbiAgICAgICAge1xuICAgICAgICAgIHhQZXJjZW50OiAwLFxuICAgICAgICAgIHNjYWxlOiAxLFxuICAgICAgICAgIG9wYWNpdHk6IDEsXG4gICAgICAgICAgZHVyYXRpb246IDEsXG4gICAgICAgICAgZWFzZTogXCJleHBvLmluT3V0XCIsXG4gICAgICAgIH0sXG4gICAgICAgIFwiPFwiXG4gICAgICApO1xuICAgIH1cblxuICAgIGJ1dHRvbnMuZm9yRWFjaChmdW5jdGlvbiAoYnV0dG9uKSB7XG4gICAgICBidXR0b24uYWRkRXZlbnRMaXN0ZW5lcihcImNsaWNrXCIsIGZ1bmN0aW9uICgpIHtcbiAgICAgICAgY29uc3QgdGFyZ2V0ID0gYnV0dG9uLmdldEF0dHJpYnV0ZShcImRhdGEtd29yay1idXR0b25cIik7XG4gICAgICAgIHN3aXRjaFZpZXcodGFyZ2V0KTtcbiAgICAgIH0pO1xuICAgIH0pO1xuICB9KTtcbn1cblxuZnVuY3Rpb24gaW5pdFBhZ2VUcmFuc2l0aW9uKCkge1xuICAvLyBQcmUtcHJvY2VzcyBhbGwgdmFsaWQgbGlua3NcbiAgY29uc3QgdmFsaWRMaW5rcyA9IEFycmF5LmZyb20oZG9jdW1lbnQucXVlcnlTZWxlY3RvckFsbChcImFcIikpLmZpbHRlcihcbiAgICAobGluaykgPT4ge1xuICAgICAgY29uc3QgaHJlZiA9IGxpbmsuZ2V0QXR0cmlidXRlKFwiaHJlZlwiKSB8fCBcIlwiO1xuICAgICAgY29uc3QgaG9zdG5hbWUgPSBuZXcgVVJMKGxpbmsuaHJlZiwgd2luZG93LmxvY2F0aW9uLm9yaWdpbikuaG9zdG5hbWU7XG5cbiAgICAgIHJldHVybiAoXG4gICAgICAgIGhvc3RuYW1lID09PSB3aW5kb3cubG9jYXRpb24uaG9zdG5hbWUgJiYgLy8gU2FtZSBkb21haW5cbiAgICAgICAgIWhyZWYuc3RhcnRzV2l0aChcIiNcIikgJiYgLy8gTm90IGFuIGFuY2hvciBsaW5rXG4gICAgICAgIGxpbmsuZ2V0QXR0cmlidXRlKFwidGFyZ2V0XCIpICE9PSBcIl9ibGFua1wiICYmIC8vIE5vdCBvcGVuaW5nIGluIGEgbmV3IHRhYlxuICAgICAgICAhbGluay5oYXNBdHRyaWJ1dGUoXCJkYXRhLXRyYW5zaXRpb24tcHJldmVudFwiKSAvLyBObyAnZGF0YS10cmFuc2l0aW9uLXByZXZlbnQnIGF0dHJpYnV0ZVxuICAgICAgKTtcbiAgICB9XG4gICk7XG5cbiAgLy8gQWRkIGV2ZW50IGxpc3RlbmVycyB0byBwcmUtcHJvY2Vzc2VkIHZhbGlkIGxpbmtzXG4gIHZhbGlkTGlua3MuZm9yRWFjaCgobGluaykgPT4ge1xuICAgIGxpbmsuYWRkRXZlbnRMaXN0ZW5lcihcImNsaWNrXCIsIChldmVudCkgPT4ge1xuICAgICAgZXZlbnQucHJldmVudERlZmF1bHQoKTtcbiAgICAgIGNvbnN0IGRlc3RpbmF0aW9uID0gbGluay5ocmVmO1xuXG4gICAgICAkKFwiYm9keVwiKS5hZGRDbGFzcyhcImlzLXRyYW5zaXRpb25pbmdcIik7XG4gICAgICBnc2FwLmRlbGF5ZWRDYWxsKDEsIGZ1bmN0aW9uICgpIHtcbiAgICAgICAgd2luZG93LmxvY2F0aW9uLmhyZWYgPSBkZXN0aW5hdGlvbjtcbiAgICAgIH0pO1xuICAgIH0pO1xuICB9KTtcblxuICB3aW5kb3cuYWRkRXZlbnRMaXN0ZW5lcihcInBhZ2VzaG93XCIsIChldmVudCkgPT4ge1xuICAgIGlmIChldmVudC5wZXJzaXN0ZWQpIHtcbiAgICAgIHdpbmRvdy5sb2NhdGlvbi5yZWxvYWQoKTtcbiAgICB9XG4gIH0pO1xufVxuXG5mdW5jdGlvbiBpbml0U21vb290aGllcygpIHtcbiAgaWYgKFxuICAgIHR5cGVvZiBTbW9vb3RoeSA9PT0gXCJ1bmRlZmluZWRcIiB8fFxuICAgIHR5cGVvZiAkID09PSBcInVuZGVmaW5lZFwiIHx8XG4gICAgdHlwZW9mIGdzYXAgPT09IFwidW5kZWZpbmVkXCJcbiAgKVxuICAgIHJldHVybjtcblxuICAvLyBTaGFyZWQgYmFzZTogYWRkcyBsaW5rLWNsaWNrLWR1cmluZy1kcmFnIGhhbmRsaW5nLCBrZXlib2FyZCBhcnJvdyBuYXYsXG4gIC8vIGhvcml6b250YWwtb25seSB3aGVlbC90cmFja3BhZCBzY3JvbGxpbmcsIGFuZCBibG9ja3MgdGhlIGJyb3dzZXInc1xuICAvLyBiYWNrL2ZvcndhcmQgZ2VzdHVyZSBvbiBob3Jpem9udGFsIHRyYWNrcGFkIHNjcm9sbC5cbiAgY2xhc3MgU21vb290aHlTbGlkZXIgZXh0ZW5kcyBTbW9vb3RoeSB7XG4gICAgY29uc3RydWN0b3Iod3JhcHBlciwgY29uZmlnKSB7XG4gICAgICBzdXBlcih3cmFwcGVyLCBjb25maWcpO1xuICAgICAgdGhpcy5fdGlja2VyVXBkYXRlID0gdGhpcy51cGRhdGUuYmluZCh0aGlzKTtcbiAgICAgIHRoaXMuX29uS2V5ZG93biA9IHRoaXMuX29uS2V5ZG93bi5iaW5kKHRoaXMpO1xuICAgICAgdGhpcy5fb25XaGVlbCA9IHRoaXMuX29uV2hlZWwuYmluZCh0aGlzKTtcbiAgICAgIHRoaXMuX3NldHVwTGlua3MoKTtcbiAgICAgIHdpbmRvdy5hZGRFdmVudExpc3RlbmVyKFwia2V5ZG93blwiLCB0aGlzLl9vbktleWRvd24pO1xuICAgICAgdGhpcy53cmFwcGVyLmFkZEV2ZW50TGlzdGVuZXIoXCJ3aGVlbFwiLCB0aGlzLl9vbldoZWVsLCB7IHBhc3NpdmU6IGZhbHNlIH0pO1xuICAgICAgZ3NhcC50aWNrZXIuYWRkKHRoaXMuX3RpY2tlclVwZGF0ZSk7XG4gICAgfVxuXG4gICAgX3NldHVwTGlua3MoKSB7XG4gICAgICBjb25zdCBsaW5rcyA9IEFycmF5LnByb3RvdHlwZS5zbGljZS5jYWxsKFxuICAgICAgICB0aGlzLndyYXBwZXIucXVlcnlTZWxlY3RvckFsbChcImFcIilcbiAgICAgICk7XG4gICAgICBsaW5rcy5mb3JFYWNoKGZ1bmN0aW9uIChsaW5rKSB7XG4gICAgICAgIGlmICghbGluay5wYXJlbnRFbGVtZW50KSByZXR1cm47XG4gICAgICAgIGxpbmsuc3R5bGUucG9pbnRlckV2ZW50cyA9IFwibm9uZVwiO1xuXG4gICAgICAgIGxldCBzdGFydFggPSAwO1xuICAgICAgICBsZXQgc3RhcnRZID0gMDtcbiAgICAgICAgbGV0IHN0YXJ0VGltZSA9IDA7XG4gICAgICAgIGxldCBpc0RyYWdnaW5nID0gZmFsc2U7XG5cbiAgICAgICAgY29uc3Qgb25Eb3duID0gZnVuY3Rpb24gKGUpIHtcbiAgICAgICAgICBjb25zdCBwdCA9IGUudG91Y2hlcyA/IGUudG91Y2hlc1swXSA6IGU7XG4gICAgICAgICAgc3RhcnRYID0gcHQuY2xpZW50WDtcbiAgICAgICAgICBzdGFydFkgPSBwdC5jbGllbnRZO1xuICAgICAgICAgIHN0YXJ0VGltZSA9IERhdGUubm93KCk7XG4gICAgICAgICAgaXNEcmFnZ2luZyA9IGZhbHNlO1xuICAgICAgICB9O1xuICAgICAgICBjb25zdCBvbk1vdmUgPSBmdW5jdGlvbiAoZSkge1xuICAgICAgICAgIGlmICghc3RhcnRUaW1lKSByZXR1cm47XG4gICAgICAgICAgY29uc3QgcHQgPSBlLnRvdWNoZXMgPyBlLnRvdWNoZXNbMF0gOiBlO1xuICAgICAgICAgIGlmIChcbiAgICAgICAgICAgIE1hdGguYWJzKHB0LmNsaWVudFggLSBzdGFydFgpID4gNSB8fFxuICAgICAgICAgICAgTWF0aC5hYnMocHQuY2xpZW50WSAtIHN0YXJ0WSkgPiA1XG4gICAgICAgICAgKSB7XG4gICAgICAgICAgICBpc0RyYWdnaW5nID0gdHJ1ZTtcbiAgICAgICAgICB9XG4gICAgICAgIH07XG4gICAgICAgIGNvbnN0IG9uVXAgPSBmdW5jdGlvbiAoKSB7XG4gICAgICAgICAgY29uc3QgZHQgPSBEYXRlLm5vdygpIC0gc3RhcnRUaW1lO1xuICAgICAgICAgIGlmICghaXNEcmFnZ2luZyAmJiBkdCA8IDIwMCkgbGluay5jbGljaygpO1xuICAgICAgICAgIHN0YXJ0VGltZSA9IDA7XG4gICAgICAgICAgaXNEcmFnZ2luZyA9IGZhbHNlO1xuICAgICAgICB9O1xuXG4gICAgICAgIGNvbnN0IHBhcmVudCA9IGxpbmsucGFyZW50RWxlbWVudDtcbiAgICAgICAgcGFyZW50LmFkZEV2ZW50TGlzdGVuZXIoXCJtb3VzZWRvd25cIiwgb25Eb3duKTtcbiAgICAgICAgcGFyZW50LmFkZEV2ZW50TGlzdGVuZXIoXCJtb3VzZW1vdmVcIiwgb25Nb3ZlKTtcbiAgICAgICAgcGFyZW50LmFkZEV2ZW50TGlzdGVuZXIoXCJtb3VzZXVwXCIsIG9uVXApO1xuICAgICAgICBwYXJlbnQuYWRkRXZlbnRMaXN0ZW5lcihcInRvdWNoc3RhcnRcIiwgb25Eb3duLCB7IHBhc3NpdmU6IHRydWUgfSk7XG4gICAgICAgIHBhcmVudC5hZGRFdmVudExpc3RlbmVyKFwidG91Y2htb3ZlXCIsIG9uTW92ZSwgeyBwYXNzaXZlOiB0cnVlIH0pO1xuICAgICAgICBwYXJlbnQuYWRkRXZlbnRMaXN0ZW5lcihcInRvdWNoZW5kXCIsIG9uVXApO1xuICAgICAgfSk7XG4gICAgfVxuXG4gICAgX29uS2V5ZG93bihlKSB7XG4gICAgICBpZiAoIXRoaXMuaXNWaXNpYmxlIHx8IHRoaXMucGF1c2VkKSByZXR1cm47XG4gICAgICBpZiAoZS5rZXkgPT09IFwiQXJyb3dMZWZ0XCIpIHRoaXMuZ29Ub1ByZXYoKTtcbiAgICAgIGVsc2UgaWYgKGUua2V5ID09PSBcIkFycm93UmlnaHRcIikgdGhpcy5nb1RvTmV4dCgpO1xuICAgIH1cblxuICAgIF9vbldoZWVsKGUpIHtcbiAgICAgIC8vIEhvcml6b250YWwtb25seTogZmVlZCBkZWx0YVggaW50byB0aGUgc2xpZGVyLCBpZ25vcmUgZGVsdGFZIGVudGlyZWx5XG4gICAgICAvLyBzbyB0aGUgcGFnZSBjb250aW51ZXMgdG8gc2Nyb2xsIHZlcnRpY2FsbHkgYXMgbm9ybWFsIHdoZW4gdGhlIGN1cnNvclxuICAgICAgLy8gaXMgb3ZlciB0aGUgc2xpZGVyLlxuICAgICAgaWYgKE1hdGguYWJzKGUuZGVsdGFYKSA+IE1hdGguYWJzKGUuZGVsdGFZKSkge1xuICAgICAgICBlLnByZXZlbnREZWZhdWx0KCk7IC8vIGJsb2NrIGJyb3dzZXIgYmFjay9mb3J3YXJkIHN3aXBlIGdlc3R1cmVcbiAgICAgICAgLy8gQ29udmVydCBwaXhlbCBkZWx0YSB0byBzbGlkZXIgdW5pdHMuIDAuMDAyIGlzIGEgcmVhc29uYWJsZSBzdGFydGluZ1xuICAgICAgICAvLyBwb2ludCDigJQgdHVuZSB0byB0YXN0ZSAoaGlnaGVyID0gZmFzdGVyIHNjcm9sbCByZXNwb25zZSkuXG4gICAgICAgIHRoaXMudGFyZ2V0IC09IGUuZGVsdGFYICogMC4wMDU7XG4gICAgICB9XG4gICAgfVxuXG4gICAgZGVzdHJveSgpIHtcbiAgICAgIHdpbmRvdy5yZW1vdmVFdmVudExpc3RlbmVyKFwia2V5ZG93blwiLCB0aGlzLl9vbktleWRvd24pO1xuICAgICAgdGhpcy53cmFwcGVyLnJlbW92ZUV2ZW50TGlzdGVuZXIoXCJ3aGVlbFwiLCB0aGlzLl9vbldoZWVsKTtcbiAgICAgIGdzYXAudGlja2VyLnJlbW92ZSh0aGlzLl90aWNrZXJVcGRhdGUpO1xuICAgICAgaWYgKHN1cGVyLmRlc3Ryb3kpIHN1cGVyLmRlc3Ryb3koKTtcbiAgICB9XG4gIH1cblxuICAvLyBbRkVBVFVSRUQgUFJPSkVDVFNdXG4gICQoJ1tkYXRhLXNtb29vdGh5PVwiZmVhdHVyZWQtcHJvamVjdHNcIl0nKS5lYWNoKGZ1bmN0aW9uICgpIHtcbiAgICBpZiAodGhpcy5kYXRhc2V0LmpzSW5pdCA9PT0gXCJ0cnVlXCIpIHJldHVybjtcbiAgICB0aGlzLmRhdGFzZXQuanNJbml0ID0gXCJ0cnVlXCI7XG5cbiAgICBjb25zdCB3cmFwcGVyID0gdGhpcztcbiAgICBjb25zdCBlbmFibGVTbGlkZVkgPSB3cmFwcGVyLmhhc0F0dHJpYnV0ZShcImRhdGEtc21vb290aHkteVwiKTtcbiAgICBjb25zdCBzbGlkZXMgPSB3cmFwcGVyLmNoaWxkcmVuO1xuICAgIGNvbnN0IHhQYXJhbGxheEFtb3VudCA9IC0xMDsgLy8gbmVnYXRpdmUgcmV2ZXJzZXMgZGlyZWN0aW9uXG5cbiAgICBuZXcgU21vb290aHlTbGlkZXIod3JhcHBlciwge1xuICAgICAgaW5maW5pdGU6IGZhbHNlLFxuICAgICAgc25hcDogdHJ1ZSxcbiAgICAgIHNjcm9sbElucHV0OiBmYWxzZSwgLy8gd2UgaGFuZGxlIHdoZWVsIGlucHV0IG91cnNlbHZlcyAoaG9yaXpvbnRhbC1vbmx5KVxuICAgICAgYm91bmNlTGltaXQ6IDAsXG4gICAgICBzZXRPZmZzZXQ6IGZ1bmN0aW9uICh2aWV3cG9ydCkge1xuICAgICAgICByZXR1cm4gdmlld3BvcnQud3JhcHBlcldpZHRoO1xuICAgICAgfSxcbiAgICAgIG9uVXBkYXRlOiBmdW5jdGlvbiAoKSB7XG4gICAgICAgIGNvbnN0IHdyYXBwZXJSZWN0ID0gd3JhcHBlci5nZXRCb3VuZGluZ0NsaWVudFJlY3QoKTtcbiAgICAgICAgY29uc3Qgd3JhcHBlckNlbnRlciA9IHdyYXBwZXJSZWN0LmxlZnQgKyB3cmFwcGVyUmVjdC53aWR0aCAvIDI7XG4gICAgICAgIGNvbnN0IGhhbGZXaWR0aCA9IHdyYXBwZXJSZWN0LndpZHRoIC8gMjtcblxuICAgICAgICBmb3IgKGxldCBpID0gMDsgaSA8IHNsaWRlcy5sZW5ndGg7IGkrKykge1xuICAgICAgICAgIGNvbnN0IHNsaWRlID0gc2xpZGVzW2ldO1xuICAgICAgICAgIGlmICghc2xpZGUpIGNvbnRpbnVlO1xuXG4gICAgICAgICAgY29uc3Qgc2xpZGVSZWN0ID0gc2xpZGUuZ2V0Qm91bmRpbmdDbGllbnRSZWN0KCk7XG4gICAgICAgICAgY29uc3Qgc2xpZGVDZW50ZXIgPSBzbGlkZVJlY3QubGVmdCArIHNsaWRlUmVjdC53aWR0aCAvIDI7XG5cbiAgICAgICAgICAvLyAtMSBhdCB3cmFwcGVyJ3MgbGVmdCBlZGdlLCAwIGF0IGNlbnRyZSwgMSBhdCByaWdodCBlZGdlXG4gICAgICAgICAgbGV0IHYgPSAoc2xpZGVDZW50ZXIgLSB3cmFwcGVyQ2VudGVyKSAvIGhhbGZXaWR0aDtcbiAgICAgICAgICBpZiAodiA8IC0xKSB2ID0gLTE7XG4gICAgICAgICAgZWxzZSBpZiAodiA+IDEpIHYgPSAxO1xuXG4gICAgICAgICAgLy8gWCBwYXJhbGxheCBvbiB0aGUgW2RhdGEtcF0gaW1hZ2UgaW5zaWRlIHRoZSBzbGlkZVxuICAgICAgICAgIGNvbnN0IGltZyA9IHNsaWRlLnF1ZXJ5U2VsZWN0b3IoXCJbZGF0YS1wXVwiKTtcbiAgICAgICAgICBpZiAoaW1nKSB7XG4gICAgICAgICAgICBpbWcuc3R5bGUudHJhbnNmb3JtID1cbiAgICAgICAgICAgICAgXCJ0cmFuc2xhdGUzZChcIiArIHYgKiB4UGFyYWxsYXhBbW91bnQgKyBcIiUsMCwwKVwiO1xuICAgICAgICAgIH1cblxuICAgICAgICAgIC8vIFkgYXJjIG9uIHRoZSBpbm5lciB3cmFwcGVyIChzbyBzbW9vb3RoeSdzIGhvcml6b250YWwgdHJhbnNmb3JtXG4gICAgICAgICAgLy8gb24gdGhlIHNsaWRlIGl0c2VsZiBpc24ndCBjbG9iYmVyZWQpXG4gICAgICAgICAgaWYgKGVuYWJsZVNsaWRlWSkge1xuICAgICAgICAgICAgY29uc3QgaW5uZXIgPSBzbGlkZS5xdWVyeVNlbGVjdG9yKFwiW2RhdGEtc21vb290aHktaW5uZXJdXCIpO1xuICAgICAgICAgICAgaWYgKGlubmVyKSB7XG4gICAgICAgICAgICAgIGNvbnN0IHkgPSBNYXRoLmFicyh2KSAqIDIwIC0gMTA7XG4gICAgICAgICAgICAgIGlubmVyLnN0eWxlLnRyYW5zZm9ybSA9IFwidHJhbnNsYXRlM2QoMCxcIiArIHkgKyBcIiUsMClcIjtcbiAgICAgICAgICAgIH1cbiAgICAgICAgICB9XG4gICAgICAgIH1cbiAgICAgIH0sXG4gICAgfSk7XG4gIH0pO1xuXG4gIC8vIEFkZCBmdXR1cmUgc2xpZGVycyBiZWxvdyBhcyBhZGRpdGlvbmFsIC5lYWNoKCkgYmxvY2tzLCBlLmcuXG4gIC8vICQoJ1tkYXRhLXNtb29vdGh5PVwidGVzdGltb25pYWxzXCJdJykuZWFjaChmdW5jdGlvbiAoKSB7IC4uLiB9KTtcbn1cblxuZnVuY3Rpb24gaW5pdFNlcnZpY2VzU2Nyb2xsKCkge1xuICAkKFwiW2RhdGEtc2VydmljZXMtc2Nyb2xsLXNlY3Rpb25dXCIpLmVhY2goZnVuY3Rpb24gKCkge1xuICAgIGNvbnN0IHNlY3Rpb24gPSAkKHRoaXMpO1xuICAgIGNvbnN0IHN0YXJ0QW5jaG9yID0gc2VjdGlvbi5maW5kKFwiW2RhdGEtc2VydmljZXMtc2Nyb2xsLXN0YXJ0LWFuY2hvcl1cIik7XG4gICAgY29uc3QgaW1hZ2VzV3JhcCA9IHNlY3Rpb24uZmluZChcIltkYXRhLXNlcnZpY2VzLXNjcm9sbC1pbWFnZXMtd3JhcF1cIik7XG4gICAgY29uc3QgaW1hZ2VXcmFwcyA9IHNlY3Rpb24uZmluZChcIltkYXRhLXNlcnZpY2VzLXNjcm9sbC1pbWFnZS13cmFwXVwiKTtcbiAgICBjb25zdCB0cmFjayA9IHNlY3Rpb24uZmluZChcIltkYXRhLXNlcnZpY2VzLXNjcm9sbC10cmFja11cIik7XG4gICAgY29uc3Qgb3ZlcmxheXMgPSBzZWN0aW9uLmZpbmQoXCJbZGF0YS1zZXJ2aWNlcy1zY3JvbGwtaW1hZ2Utb3ZlcmxheV1cIik7XG4gICAgY29uc3QgYW5jaG9ycyA9IHNlY3Rpb24uZmluZChcIltkYXRhLXNlcnZpY2VzLXNjcm9sbC1hbmNob3JdXCIpO1xuICAgIGNvbnN0IHRleHRXcmFwcyA9IHNlY3Rpb24uZmluZChcIltkYXRhLXNlcnZpY2VzLXNjcm9sbC10ZXh0LXdyYXBdXCIpO1xuXG4gICAgbGV0IHByZVRsID0gZ3NhcC50aW1lbGluZSh7XG4gICAgICBzY3JvbGxUcmlnZ2VyOiB7XG4gICAgICAgIHRyaWdnZXI6IHNlY3Rpb24sXG4gICAgICAgIHN0YXJ0OiBcInRvcCBib3R0b21cIixcbiAgICAgICAgZW5kOiBcInRvcCAtMzMlXCIsXG4gICAgICAgIHNjcnViOiB0cnVlLFxuICAgICAgfSxcbiAgICB9KTtcblxuICAgIHByZVRsLmZyb20oaW1hZ2VzV3JhcCwge1xuICAgICAgc2NhbGU6IDEuMjUsXG4gICAgfSk7XG5cbiAgICBsZXQgc3RhcnRUbCA9IGdzYXAudGltZWxpbmUoe1xuICAgICAgc2Nyb2xsVHJpZ2dlcjoge1xuICAgICAgICB0cmlnZ2VyOiBzdGFydEFuY2hvcixcbiAgICAgICAgc3RhcnQ6IFwiYm90dG9tIDEyNSVcIixcbiAgICAgICAgZW5kOiBcImJvdHRvbSB0b3BcIixcbiAgICAgICAgc2NydWI6IHRydWUsXG4gICAgICB9LFxuICAgIH0pO1xuXG4gICAgc3RhcnRUbC50byhpbWFnZXNXcmFwLCB7XG4gICAgICB3aWR0aDogXCI1MCVcIixcbiAgICAgIGVhc2U6IFwicG93ZXIxLmluT3V0XCIsXG4gICAgfSk7XG5cbiAgICBsZXQgdHJhY2tUbCA9IGdzYXAudGltZWxpbmUoe1xuICAgICAgc2Nyb2xsVHJpZ2dlcjoge1xuICAgICAgICB0cmlnZ2VyOiB0cmFjayxcbiAgICAgICAgc3RhcnQ6IFwidG9wIDUwJVwiLFxuICAgICAgICBlbmQ6IFwiYm90dG9tIGJvdHRvbVwiLFxuICAgICAgICBzY3J1YjogdHJ1ZSxcbiAgICAgIH0sXG4gICAgfSk7XG5cbiAgICBpbWFnZVdyYXBzLmVhY2goZnVuY3Rpb24gKCkge1xuICAgICAgaWYgKCQodGhpcykuaXMoaW1hZ2VXcmFwcy5lcSgwKSkpIHtcbiAgICAgICAgcHJlVGwuZnJvbShcbiAgICAgICAgICAkKHRoaXMpLFxuICAgICAgICAgIHtcbiAgICAgICAgICAgIHNjYWxlOiAxLjI1LFxuICAgICAgICAgIH0sXG4gICAgICAgICAgMFxuICAgICAgICApO1xuICAgICAgfSBlbHNlIHtcbiAgICAgICAgdHJhY2tUbC5mcm9tVG8oXG4gICAgICAgICAgJCh0aGlzKSxcbiAgICAgICAgICB7XG4gICAgICAgICAgICBjbGlwUGF0aDogXCJwb2x5Z29uKDAlIDEwMCUsIDEwMCUgMTAwJSwgMTAwJSAxMDAlLCAwJSAxMDAlKVwiLFxuICAgICAgICAgICAgc2NhbGU6IDEuMjUsXG4gICAgICAgICAgfSxcbiAgICAgICAgICB7XG4gICAgICAgICAgICBjbGlwUGF0aDogXCJwb2x5Z29uKDAlIDAlLCAxMDAlIDAlLCAxMDAlIDEwMCUsIDAlIDEwMCUpXCIsXG4gICAgICAgICAgICBlYXNlOiBcInBvd2VyMi5pbk91dFwiLFxuICAgICAgICAgICAgc2NhbGU6IDEsXG4gICAgICAgICAgfSxcbiAgICAgICAgICBcIj4tLjI1XCJcbiAgICAgICAgKTtcbiAgICAgIH1cbiAgICB9KTtcblxuICAgIGxldCBvdmVybGF5c1RsID0gZ3NhcC50aW1lbGluZSh7XG4gICAgICBzY3JvbGxUcmlnZ2VyOiB7XG4gICAgICAgIHRyaWdnZXI6IHRyYWNrLFxuICAgICAgICBzdGFydDogXCJ0b3AgNTAlXCIsXG4gICAgICAgIGVuZDogXCJib3R0b20gYm90dG9tXCIsXG4gICAgICAgIHNjcnViOiB0cnVlLFxuICAgICAgfSxcbiAgICB9KTtcblxuICAgIG92ZXJsYXlzLmVhY2goZnVuY3Rpb24gKCkge1xuICAgICAgaWYgKCQodGhpcykuaXMob3ZlcmxheXMubGFzdCgpKSkgcmV0dXJuO1xuXG4gICAgICBvdmVybGF5c1RsLnRvKCQodGhpcyksIHtcbiAgICAgICAgb3BhY2l0eTogMC43NSxcbiAgICAgICAgZWFzZTogXCJwb3dlcjEuaW5cIixcbiAgICAgIH0pO1xuICAgIH0pO1xuXG4gICAgYW5jaG9ycy5lYWNoKGZ1bmN0aW9uIChpbmRleCkge1xuICAgICAgY29uc3QgdGV4dFdyYXAgPSB0ZXh0V3JhcHMuZXEoaW5kZXgpO1xuICAgICAgY29uc3QgdGV4dEhlYWRpbmcgPSB0ZXh0V3JhcC5maW5kKFwiW2RhdGEtc2VydmljZXMtc2Nyb2xsLXRleHQtaGVhZGluZ11cIik7XG4gICAgICBjb25zdCB0ZXh0U3ViaGVhZGluZyA9IHRleHRXcmFwLmZpbmQoXG4gICAgICAgIFwiW2RhdGEtc2VydmljZXMtc2Nyb2xsLXRleHQtc3ViaGVhZGluZ11cIlxuICAgICAgKTtcbiAgICAgIGNvbnN0IHRleHRSaWNoID0gdGV4dFdyYXAuZmluZChcIltkYXRhLXNlcnZpY2VzLXNjcm9sbC10ZXh0LXJpY2hdXCIpO1xuXG4gICAgICBsZXQgdGV4dFRsID0gZ3NhcC50aW1lbGluZSh7XG4gICAgICAgIHNjcm9sbFRyaWdnZXI6IHtcbiAgICAgICAgICB0cmlnZ2VyOiAkKHRoaXMpLFxuICAgICAgICAgIHN0YXJ0OiBcInRvcCA3NSVcIixcbiAgICAgICAgICB0b2dnbGVBY3Rpb25zOiBcInBsYXkgcmV2ZXJzZSBwbGF5IHJldmVyc2VcIixcbiAgICAgICAgfSxcbiAgICAgICAgZGVmYXVsdHM6IHtcbiAgICAgICAgICBlYXNlUmV2ZXJzZTogdHJ1ZSxcbiAgICAgICAgICBlYXNlOiBcImV4cG8ub3V0XCJcbiAgICAgICAgfSxcbiAgICAgIH0pO1xuXG4gICAgICAvLyBGYWRlIG91dCBwcmV2aW91cyB0ZXh0IHdyYXAgKHNraXAgZm9yIGZpcnN0KVxuICAgICAgaWYgKGluZGV4ID4gMCkge1xuICAgICAgICBjb25zdCBwcmV2VGV4dFdyYXAgPSB0ZXh0V3JhcHMuZXEoaW5kZXggLSAxKTtcbiAgICAgICAgdGV4dFRsLnRvKHByZXZUZXh0V3JhcCwge1xuICAgICAgICAgIG9wYWNpdHk6IDAsXG4gICAgICAgICAgZHVyYXRpb246IDAuMjUsXG4gICAgICAgIH0pO1xuICAgICAgfVxuXG4gICAgICB0ZXh0VGwuZnJvbShcbiAgICAgICAgdGV4dEhlYWRpbmcuZmluZChcIi53b3JkXCIpLFxuICAgICAgICB7XG4gICAgICAgICAgeVBlcmNlbnQ6IDEyNSxcbiAgICAgICAgICBkdXJhdGlvbjogMS4yNSxcbiAgICAgICAgICBlYXNlOiBcImV4cG8ub3V0XCIsXG4gICAgICAgICAgc3RhZ2dlcjoge1xuICAgICAgICAgICAgZWFjaDogMC4xMjUsXG4gICAgICAgICAgfSxcbiAgICAgICAgfSxcbiAgICAgICAgaW5kZXggPiAwID8gXCI8LjI1XCIgOiB1bmRlZmluZWRcbiAgICAgICk7XG5cbiAgICAgIHRleHRUbC5mcm9tKFxuICAgICAgICB0ZXh0U3ViaGVhZGluZy5maW5kKFwiLmxpbmVcIiksXG4gICAgICAgIHtcbiAgICAgICAgICB5UGVyY2VudDogMTAwLFxuICAgICAgICAgIGR1cmF0aW9uOiAxLFxuICAgICAgICAgIGVhc2U6IFwiZXhwby5vdXRcIixcbiAgICAgICAgICBzdGFnZ2VyOiB7IGVhY2g6IDAuMDEyNSB9LFxuICAgICAgICB9LFxuICAgICAgICBcIjwuMVwiXG4gICAgICApO1xuXG4gICAgICB0ZXh0VGwuZnJvbShcbiAgICAgICAgdGV4dFJpY2guZmluZChcIi5saW5lXCIpLFxuICAgICAgICB7XG4gICAgICAgICAgb3BhY2l0eTogMCxcbiAgICAgICAgICB5UGVyY2VudDogMTAwLFxuICAgICAgICAgIGR1cmF0aW9uOiAxLFxuICAgICAgICAgIGVhc2U6IFwiZXhwby5vdXRcIixcbiAgICAgICAgICBzdGFnZ2VyOiB7IGVhY2g6IDAuMDI1IH0sXG4gICAgICAgIH0sXG4gICAgICAgIFwiPC4xXCJcbiAgICAgICk7XG4gICAgfSk7XG4gIH0pO1xufVxuXG5mdW5jdGlvbiBpbml0UHJlbG9hZGVyKCkge1xuICAvLyBpZiAoIWRvY3VtZW50LmRvY3VtZW50RWxlbWVudC5jbGFzc0xpc3QuY29udGFpbnMoXCJzaG93LWludHJvXCIpKSByZXR1cm47XG5cbiAgLy8gTWFyayBpbnRybyBhcyBzaG93biBmb3IgdGhpcyBzZXNzaW9uXG4gIHNlc3Npb25TdG9yYWdlLnNldEl0ZW0oXCJpbnRyby1zaG93blwiLCBcIjFcIik7XG5cbiAgLy8gLi4uIHJlc3Qgb2YgeW91ciBpbnRybyB0aW1lbGluZVxuXG4gICQoXCJbZGF0YS1wcmVsb2FkZXItd3JhcF1cIikuZWFjaChmdW5jdGlvbiAoKSB7XG4gICAgY29uc3Qgd3JhcCA9ICQodGhpcyk7XG4gICAgY29uc3QgbG9nbyA9IHdyYXAuZmluZChcIltkYXRhLXByZWxvYWRlci1sb2dvXVwiKTtcbiAgICBjb25zdCBtaWQgPSB3cmFwLmZpbmQoXCJbZGF0YS1wcmVsb2FkZXItbWlkXVwiKTtcbiAgICBjb25zdCBsb2dvU1ZHcyA9IGxvZ28uZmluZChcIi5nX2xvZ29fc3BsaXRfc3ZnXCIpO1xuICAgIGNvbnN0IGJhcldyYXAgPSB3cmFwLmZpbmQoXCJbZGF0YS1wcmVsb2FkZXItYmFyLXdyYXBdXCIpXG4gICAgY29uc3QgYmFyID0gd3JhcC5maW5kKFwiW2RhdGEtcHJlbG9hZGVyLWJhcl1cIilcblxuICAgIGxldCBpbnRyb1RsID0gZ3NhcC50aW1lbGluZSh7XG4gICAgICBkZWxheTogMC41LFxuICAgICAgb25TdGFydDogKCkgPT4ge1xuICAgICAgICBsZW5pcy5zdG9wKCk7XG4gICAgICB9LFxuICAgICAgb25Db21wbGV0ZTogKCkgPT4ge1xuICAgICAgICBsZW5pcy5zdGFydCgpO1xuICAgICAgICBnc2FwLnNldCh3cmFwLCB7XG4gICAgICAgICAgdmlzaWJpbGl0eTogXCJoaWRkZW5cIixcbiAgICAgICAgfSk7XG4gICAgICB9LFxuICAgIH0pO1xuXG4gICAgaW50cm9UbC5mcm9tVG8obG9nbywge1xuICAgICAgeDogMCxcbiAgICAgIHNjYWxlOiAyLFxuXG4gICAgfSwge1xuICAgICAgeDogXCI2dndcIixcbiAgICAgIHNjYWxlOiAxLFxuICAgICAgZHVyYXRpb246IDIuNSxcbiAgICAgIGVhc2U6IFwiZXhwby5vdXRcIixcbiAgICB9KTtcblxuICAgIGludHJvVGwuZnJvbShcbiAgICAgIGxvZ29TVkdzLFxuICAgICAge1xuICAgICAgICB4UGVyY2VudDogMTI1LFxuICAgICAgICBlYXNlOiBcImV4cG8ub3V0XCIsXG4gICAgICAgIGR1cmF0aW9uOiAxLjUsXG4gICAgICAgIHN0YWdnZXI6IHtcbiAgICAgICAgICBlYWNoOiAwLjEsXG4gICAgICAgIH0sXG4gICAgICB9LFxuICAgICAgXCI8XCJcbiAgICApO1xuXG4gICAgaW50cm9UbC50byhsb2dvLCB7XG4gICAgICB4OiAwLFxuICAgICAgZHVyYXRpb246IDIsXG4gICAgICBlYXNlOiBcImV4cG8uaW5PdXRcIlxuICAgIH0sIFwiPDFcIilcblxuICAgIGludHJvVGwuZnJvbShiYXJXcmFwLCB7XG4gICAgICBzY2FsZVg6IDAsXG4gICAgICBkdXJhdGlvbjogMixcbiAgICAgIGVhc2U6IFwiZXhwby5pbk91dFwiXG4gICAgfSwgXCI8XCIpXG5cbiAgICBpbnRyb1RsLnRvKGJhciwge1xuICAgICAgc2NhbGVYOiAxLFxuICAgICAgZHVyYXRpb246IDIuNSxcbiAgICAgIGVhc2U6IEN1c3RvbUVhc2UuY3JlYXRlKFwiY3VzdG9tXCIsIFwiTTAsMCBDMCwwIDAuMDQ5LDAuMDIzIDAuMDYzLDAuMDM2IDAuMDc4LDAuMDUgMC4xMDUsMC4wNCAwLjEyLDAuMDU1IDAuMTMzLDAuMDY4IDAuMjEzLDAuMDcgMC4yMjcsMC4wODMgMC4yNDIsMC4wOTcgMC4zLDAuMTMzIDAuMzE1LDAuMTQ3IDAuMzI4LDAuMTYgMC4zNDIsMC4xOTggMC4zNTcsMC4yMTMgMC4zNzEsMC4yMjYgMC4zNjEsMC4yOTkgMC4zNzYsMC4zMTQgMC4zODksMC4zMjcgMC4zNjksMC4zNDYgMC4zODMsMC4zNTkgMC4zOTgsMC4zNzMgMC41MzMsMC4zNzUgMC41NTgsMC4zNzYgMC42NzMsMC4zOCAwLjc1OSwwLjUwNiAwLjg0NiwwLjUwNyAxLjAwNywwLjUwNyAxLDEgMSwxIFwiKSxcbiAgICB9LCBcIjwxXCIpXG5cbiAgICBpbnRyb1RsLnRvKFxuICAgICAgbG9nbyxcbiAgICAgIHtcbiAgICAgICAgeFBlcmNlbnQ6IC0zMDAsXG4gICAgICAgIGVhc2U6IFwiZXhwby5pblwiLFxuICAgICAgICBkdXJhdGlvbjogMi41LFxuICAgICAgfSwgXCI8MS43NVwiXG4gICAgKTtcblxuICAgIGludHJvVGwudG8oXG4gICAgICBiYXJXcmFwLFxuICAgICAge1xuICAgICAgICB4UGVyY2VudDogLTMwMCxcbiAgICAgICAgZWFzZTogXCJleHBvLmluXCIsXG4gICAgICAgIGR1cmF0aW9uOiAyLjUsXG4gICAgICB9LCBcIjxcIlxuICAgICk7XG5cbiAgICBpbnRyb1RsLnRvKFxuICAgICAgbG9nb1NWR3MsXG4gICAgICB7XG4gICAgICAgIHhQZXJjZW50OiAtMTI1LFxuICAgICAgICBlYXNlOiBcImV4cG8uaW5cIixcbiAgICAgICAgZHVyYXRpb246IDEuNSxcbiAgICAgICAgc3RhZ2dlcjoge1xuICAgICAgICAgIGVhY2g6IDAuMDUsXG4gICAgICAgIH0sXG4gICAgICB9LFxuICAgICAgXCI8XCJcbiAgICApO1xuXG4gICAgaW50cm9UbC50byhiYXJXcmFwLCB7XG4gICAgICBzY2FsZVg6IDAsXG4gICAgICBlYXNlOiBcImV4cG8uaW5cIixcbiAgICAgIGR1cmF0aW9uOiAxLjUsXG4gICAgfSwgXCI8LjI1XCIpXG4gIH0pO1xufVxuXG5mdW5jdGlvbiBhc3NpZ25MYXlvdXRJbmRleGVzKCkge1xuICAkKFwiW2RhdGEtd29yay1nYWxsZXJ5XVwiKS5lYWNoKGZ1bmN0aW9uICgpIHtcbiAgICBjb25zdCBzZWN0aW9uID0gJCh0aGlzKTtcbiAgICBjb25zdCBjbXNMaXN0ID0gc2VjdGlvbi5maW5kKFwiW2RhdGEtd29yay1nYWxsZXJ5LWxpc3RdXCIpO1xuXG4gICAgY29uc3QgaXRlbXMgPSBjbXNMaXN0LmZpbmQoJy53LWR5bi1pdGVtOm5vdChbc3R5bGUqPVwiZGlzcGxheTogbm9uZVwiXSknKTtcbiAgICBpdGVtcy5lYWNoKGZ1bmN0aW9uIChpKSB7XG4gICAgICAkKHRoaXMpLmF0dHIoXCJkYXRhLWxheW91dFwiLCAoaSAlIDYpICsgMSk7XG4gICAgfSk7XG4gIH0pO1xufVxuXG4vLyBmdW5jdGlvbiBpbml0UHJvamVjdExpc3RIb3ZlcnMoKSB7XG4vLyAgIGlmICghJChcIltkYXRhLXdvcmstbGlzdF1cIikubGVuZ3RoKSByZXR1cm47XG5cbi8vICAgY29uc3QgJGFsbFByb2plY3RMaW5rcyA9ICQoXCJbZGF0YS1saXN0LXByb2plY3RdXCIpLnNpYmxpbmdzKFwiYVwiKTtcbi8vICAgY29uc3QgJG9yaWdpbmFsQ3VycmVudCA9ICRhbGxQcm9qZWN0TGlua3MuZmlsdGVyKFwiLnctLWN1cnJlbnRcIik7XG5cbi8vICAgJChcIltkYXRhLWxpc3QtbGlua11cIikuZWFjaChmdW5jdGlvbiAoKSB7XG4vLyAgICAgY29uc3Qgc2x1ZyA9ICQodGhpcykuYXR0cihcImRhdGEtbGlzdC1saW5rXCIpO1xuLy8gICAgIGNvbnN0ICRwcm9qZWN0ID0gJChgW2RhdGEtbGlzdC1wcm9qZWN0PVwiJHtzbHVnfVwiXWApO1xuXG4vLyAgICAgaWYgKCEkcHJvamVjdC5sZW5ndGgpIHJldHVybjtcblxuLy8gICAgIGNvbnN0ICRwcm9qZWN0TGluayA9ICRwcm9qZWN0LnNpYmxpbmdzKFwiYVwiKS5maXJzdCgpO1xuXG4vLyAgICAgJCh0aGlzKS5vbihcIm1vdXNlZW50ZXJcIiwgZnVuY3Rpb24gKCkge1xuLy8gICAgICAgJGFsbFByb2plY3RMaW5rcy5yZW1vdmVDbGFzcyhcInctLWN1cnJlbnRcIik7XG4vLyAgICAgICAkcHJvamVjdExpbmsuYWRkQ2xhc3MoXCJ3LS1jdXJyZW50XCIpO1xuLy8gICAgIH0pO1xuXG4vLyAgICAgJCh0aGlzKS5vbihcIm1vdXNlbGVhdmVcIiwgZnVuY3Rpb24gKCkge1xuLy8gICAgICAgJGFsbFByb2plY3RMaW5rcy5yZW1vdmVDbGFzcyhcInctLWN1cnJlbnRcIik7XG4vLyAgICAgICAkb3JpZ2luYWxDdXJyZW50LmFkZENsYXNzKFwidy0tY3VycmVudFwiKTtcbi8vICAgICB9KTtcbi8vICAgfSk7XG4vLyB9XG5cbmZ1bmN0aW9uIGluaXRIb21lSGVyb1Njcm9sbCgpIHtcbiAgJChcIltkYXRhLWhvbWUtaGVyb11cIikuZWFjaChmdW5jdGlvbiAoKSB7XG4gICAgY29uc3Qgc2VjdGlvbiA9ICQodGhpcyk7XG4gICAgY29uc3QgaGVhZGluZ1JpbyA9IHNlY3Rpb24uZmluZChcIltkYXRhLWhlYWRpbmc9cmlvXVwiKTtcbiAgICBjb25zdCBoZWFkaW5nUHJvcGVydHkgPSBzZWN0aW9uLmZpbmQoXCJbZGF0YS1oZWFkaW5nPXByb3BlcnR5XVwiKTtcbiAgICBjb25zdCBoZWFkaW5nS25vd3MgPSBzZWN0aW9uLmZpbmQoXCJbZGF0YS1oZWFkaW5nPWtub3dzXVwiKTtcbiAgICBjb25zdCBoZWFkaW5nQ2FwZVRvd24gPSBzZWN0aW9uLmZpbmQoXCJbZGF0YS1oZWFkaW5nPSdjYXBlIHRvd24nXVwiKTtcbiAgICBjb25zdCBwYXJhZ3JhcGhMZWZ0ID0gc2VjdGlvbi5maW5kKFwiW2RhdGEtcGFyYWdyYXBoPWxlZnRdXCIpO1xuICAgIGNvbnN0IHBhcmFncmFwaFJpZ2h0ID0gc2VjdGlvbi5maW5kKFwiW2RhdGEtcGFyYWdyYXBoPXJpZ2h0XVwiKTtcbiAgICBjb25zdCBvdmVybGF5ID0gc2VjdGlvbi5maW5kKFwiW2RhdGEtaG9tZS1oZXJvLW92ZXJsYXldXCIpO1xuXG4gICAgbGV0IHRsID0gZ3NhcC50aW1lbGluZSh7XG4gICAgICBzY3JvbGxUcmlnZ2VyOiB7XG4gICAgICAgIHRyaWdnZXI6IHNlY3Rpb24sXG4gICAgICAgIHN0YXJ0OiBcInRvcCB0b3BcIixcbiAgICAgICAgZW5kOiBcImJvdHRvbSBjZW50ZXJcIixcbiAgICAgICAgc2NydWI6IHRydWUsXG4gICAgICB9LFxuICAgIH0pO1xuXG4gICAgdGwudG8oaGVhZGluZ1Jpbywge1xuICAgICAgeFBlcmNlbnQ6IC0xNzUsXG4gICAgfSk7XG5cbiAgICB0bC50byhcbiAgICAgIGhlYWRpbmdQcm9wZXJ0eSxcbiAgICAgIHtcbiAgICAgICAgeFBlcmNlbnQ6IC0xMjUsXG4gICAgICB9LFxuICAgICAgXCI8XCJcbiAgICApO1xuXG4gICAgdGwudG8oXG4gICAgICBoZWFkaW5nS25vd3MsXG4gICAgICB7XG4gICAgICAgIHhQZXJjZW50OiAxNTAsXG4gICAgICB9LFxuICAgICAgXCI8XCJcbiAgICApO1xuXG4gICAgdGwudG8oXG4gICAgICBoZWFkaW5nQ2FwZVRvd24sXG4gICAgICB7XG4gICAgICAgIHhQZXJjZW50OiAxMjUsXG4gICAgICB9LFxuICAgICAgXCI8XCJcbiAgICApO1xuXG4gICAgdGwudG8oXG4gICAgICBwYXJhZ3JhcGhMZWZ0LFxuICAgICAge1xuICAgICAgICB4UGVyY2VudDogLTEyNSxcbiAgICAgIH0sXG4gICAgICBcIjxcIlxuICAgICk7XG5cbiAgICB0bC50byhcbiAgICAgIHBhcmFncmFwaFJpZ2h0LFxuICAgICAge1xuICAgICAgICB4UGVyY2VudDogMzAwLFxuICAgICAgfSxcbiAgICAgIFwiPFwiXG4gICAgKTtcblxuICAgIHRsLnRvKG92ZXJsYXksIHtcbiAgICAgIG9wYWNpdHk6IDAsXG4gICAgICBlYXNlOiBcInBvd2VyMi5pbk91dFwiLFxuICAgIH0sXCI8XCIpXG4gIH0pO1xufVxuXG5kb2N1bWVudC5hZGRFdmVudExpc3RlbmVyKFwiRE9NQ29udGVudExvYWRlZFwiLCBmdW5jdGlvbiAoKSB7XG4gIGluaXRMZW5pcygpO1xuICBpbml0R2xvYmFsUGFyYWxsYXgoKTtcbiAgaW5pdEZPVUMoKTtcbiAgZG9jdW1lbnQuZm9udHMucmVhZHkudGhlbigoKSA9PiB7XG4gICAgaW5pdFRleHRTcGxpdCgpO1xuICAgIGluaXRMb2FkQW5pbWF0aW9ucygpO1xuICAgIGluaXRTY3JvbGxBbmltYXRpb25zKCk7XG4gICAgaW5pdFNlcnZpY2VzU2Nyb2xsKCk7XG4gIH0pO1xuICBpbml0Qm9sZEZ1bGxTY3JlZW5OYXZpZ2F0aW9uKCk7XG4gIGluaXRGb290ZXJQYXJhbGxheCgpO1xuICBpbml0SW1hZ2VTZXF1ZW5jZVNjcm9sbCgpO1xuICBpbml0QmFzaWNGbGlwKCk7XG4gIGluaXRBY2NvcmRpb25DU1MoKTtcbiAgaW5pdE1hcnF1ZWVTY3JvbGxEaXJlY3Rpb24oKTtcbiAgaW5pdENoZWNrU2VjdGlvblRoZW1lU2Nyb2xsKCk7XG4gIGluaXRNb3VzZU1vdmUoKTtcbiAgaW5pdFdvcmtWaWV3cygpO1xuICBpbml0UGFnZVRyYW5zaXRpb24oKTtcbiAgaW5pdFNtb29vdGhpZXMoKTtcbiAgaW5pdFByZWxvYWRlcigpO1xuICAvLyBhc3NpZ25MYXlvdXRJbmRleGVzKCk7XG4gIGluaXRIb21lSGVyb1Njcm9sbCgpO1xuICAvLyBpbml0UHJvamVjdExpc3RIb3ZlcnMoKTtcbn0pO1xuIl0sIm1hcHBpbmdzIjoiOzs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OztBQUNBLE9BQUssZUFBZSxhQUFhO0FBQ2pDLE9BQUssZUFBZSxTQUFTO0FBQzdCLE9BQUssZUFBZSxhQUFhO0FBQ2pDLE9BQUssZUFBZSxJQUFJO0FBQ3hCLE9BQUssZUFBZSxVQUFVO0FBRTlC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