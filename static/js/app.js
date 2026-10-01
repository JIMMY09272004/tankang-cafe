(() => {
    const $ = (selector, scope = document) => scope.querySelector(selector);
    const $$ = (selector, scope = document) => Array.from(scope.querySelectorAll(selector));
    const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const loader = $("[data-loader]");
    const hideLoader = () => loader?.classList.add("is-hidden");
    window.addEventListener("load", hideLoader, { once: true });
    window.setTimeout(hideLoader, 1100);

    const siteNav = $("[data-site-nav]");
    const navToggle = $("[data-nav-toggle]");
    navToggle?.addEventListener("click", () => {
        const open = siteNav?.classList.toggle("open");
        navToggle.setAttribute("aria-expanded", String(Boolean(open)));
    });
    $$("a", siteNav || document).forEach((link) => {
        link.addEventListener("click", () => {
            siteNav?.classList.remove("open");
            navToggle?.setAttribute("aria-expanded", "false");
        });
    });

    const header = $("[data-header]");
    const progress = $("[data-progress]");
    const toTop = $("[data-to-top]");
    const parallaxTargets = $$("[data-parallax]");
    let ticking = false;

    const updateScrollUI = () => {
        const y = window.scrollY || 0;
        header?.classList.toggle("scrolled", y > 18);
        toTop?.classList.toggle("show", y > 640);
        if (progress) {
            const docHeight = document.documentElement.scrollHeight - window.innerHeight;
            progress.style.width = `${docHeight > 0 ? (y / docHeight) * 100 : 0}%`;
        }
        if (!prefersReducedMotion) {
            parallaxTargets.forEach((el) => {
                const speed = Number(el.dataset.parallax || 0);
                el.style.transform = `translate3d(0, ${Math.round(y * speed)}px, 0)`;
            });
        }
        ticking = false;
    };

    const onScroll = () => {
        if (!ticking) {
            window.requestAnimationFrame(updateScrollUI);
            ticking = true;
        }
    };
    updateScrollUI();
    window.addEventListener("scroll", onScroll, { passive: true });
    toTop?.addEventListener("click", () => {
        window.scrollTo({ top: 0, behavior: prefersReducedMotion ? "auto" : "smooth" });
    });

    const revealTargets = $$("[data-reveal]");
    if (revealTargets.length) {
        if (prefersReducedMotion || !("IntersectionObserver" in window)) {
            revealTargets.forEach((el) => el.classList.add("is-visible"));
        } else {
            const observer = new IntersectionObserver((entries, obs) => {
                entries.forEach((entry) => {
                    if (!entry.isIntersecting) return;
                    entry.target.classList.add("is-visible");
                    obs.unobserve(entry.target);
                });
            }, { threshold: 0.12, rootMargin: "0px 0px -8% 0px" });
            revealTargets.forEach((el) => {
                const delay = Number(el.dataset.revealDelay || 0);
                if (delay) el.style.transitionDelay = `${Math.min(delay, 8) * 80}ms`;
                observer.observe(el);
            });
        }
    }

    const hero = $("[data-hero]");
    if (hero) {
        const slides = $$("[data-hero-slide]", hero);
        const dots = $$("[data-hero-dot]", hero);
        let active = 0;
        let timer = null;

        const activate = (index) => {
            if (!slides.length) return;
            active = (index + slides.length) % slides.length;
            slides.forEach((slide, i) => slide.classList.toggle("is-active", i === active));
            dots.forEach((dot, i) => dot.classList.toggle("is-active", i === active));
        };

        const start = () => {
            if (prefersReducedMotion || slides.length < 2) return;
            window.clearInterval(timer);
            timer = window.setInterval(() => activate(active + 1), 5400);
        };

        dots.forEach((dot) => {
            dot.addEventListener("click", () => {
                activate(Number(dot.dataset.heroDot || 0));
                start();
            });
        });
        activate(0);
        start();
    }

    $$("[data-carousel]").forEach((carousel) => {
        const track = $("[data-carousel-track]", carousel);
        if (!track) return;
        const step = () => Math.max(track.clientWidth * 0.82, 280);
        const behavior = prefersReducedMotion ? "auto" : "smooth";
        $("[data-carousel-prev]", carousel)?.addEventListener("click", () => {
            track.scrollBy({ left: -step(), behavior });
        });
        $("[data-carousel-next]", carousel)?.addEventListener("click", () => {
            track.scrollBy({ left: step(), behavior });
        });
    });

    const grid = $("[data-product-grid]");
    const cards = $$("[data-product-card]");
    const applyProductFilters = () => {
        if (!grid || !cards.length) return;
        const query = ($("[data-product-search]")?.value || "").trim().toLowerCase();
        const category = $("[data-product-filter]")?.value || "all";
        const sort = $("[data-product-sort]")?.value || "featured";
        const visible = cards.filter((card) => {
            const text = `${card.dataset.name || ""} ${card.dataset.description || ""}`.toLowerCase();
            const matchesQuery = !query || text.includes(query);
            const matchesCategory = category === "all" || card.dataset.category === category;
            card.hidden = !(matchesQuery && matchesCategory);
            return !card.hidden;
        });
        visible.sort((a, b) => {
            if (sort === "price-asc") return Number(a.dataset.price) - Number(b.dataset.price);
            if (sort === "price-desc") return Number(b.dataset.price) - Number(a.dataset.price);
            if (sort === "name") return (a.dataset.name || "").localeCompare(b.dataset.name || "", "zh-Hant");
            return Number(b.dataset.featured) - Number(a.dataset.featured);
        });
        visible.forEach((card, index) => {
            const current = Array.from(grid.children).filter((child) => !child.hidden)[index];
            // Moving an unchanged card during input blur can cancel its button click.
            if (current !== card) grid.insertBefore(card, current || null);
        });
    };

    ["input", "change"].forEach((eventName) => {
        $("[data-product-search]")?.addEventListener(eventName, applyProductFilters);
        $("[data-product-filter]")?.addEventListener(eventName, applyProductFilters);
        $("[data-product-sort]")?.addEventListener(eventName, applyProductFilters);
    });
    applyProductFilters();

    const quickPanel = $("[data-quick-panel]");
    const openQuickView = (card) => {
        if (!quickPanel || !card) return;
        $("[data-quick-image]", quickPanel).src = card.dataset.image || "";
        $("[data-quick-image]", quickPanel).alt = card.dataset.name || "";
        $("[data-quick-category]", quickPanel).textContent = card.dataset.category || "";
        $("[data-quick-name]", quickPanel).textContent = card.dataset.name || "";
        $("[data-quick-description]", quickPanel).textContent = card.dataset.description || "";
        $("[data-quick-link]", quickPanel).href = card.dataset.productUrl;
        quickPanel.classList.add("open");
        quickPanel.setAttribute("aria-hidden", "false");
    };
    $$("[data-quick-view]").forEach((button) => {
        button.addEventListener("click", () => openQuickView(button.closest("[data-product-card]")));
    });
    $("[data-quick-close]")?.addEventListener("click", () => {
        quickPanel?.classList.remove("open");
        quickPanel?.setAttribute("aria-hidden", "true");
    });
    document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") return;
        quickPanel?.classList.remove("open");
        quickPanel?.setAttribute("aria-hidden", "true");
        siteNav?.classList.remove("open");
    });

    $$("[data-image-preview]").forEach((input) => {
        input.addEventListener("change", () => {
            const target = input.closest("form")?.querySelector("[data-preview-target]");
            const file = input.files?.[0];
            if (!target || !file) return;
            target.src = URL.createObjectURL(file);
            target.hidden = false;
        });
    });

    const adminSearch = $("[data-admin-search]");
    adminSearch?.addEventListener("input", () => {
        const query = adminSearch.value.trim().toLowerCase();
        $$("[data-admin-product]").forEach((card) => {
            card.hidden = !card.dataset.name.toLowerCase().includes(query);
        });
    });

    const counters = $$("[data-count]");
    if (counters.length && !prefersReducedMotion && "IntersectionObserver" in window) {
        const runCount = (el) => {
            const target = Number(el.dataset.count) || 0;
            const duration = 820;
            const start = performance.now();
            const step = (now) => {
                const pct = Math.min((now - start) / duration, 1);
                const eased = 1 - Math.pow(1 - pct, 3);
                el.textContent = Math.round(target * eased);
                if (pct < 1) requestAnimationFrame(step);
                else el.textContent = String(target);
            };
            requestAnimationFrame(step);
        };
        const counterObserver = new IntersectionObserver((entries, obs) => {
            entries.forEach((entry) => {
                if (!entry.isIntersecting) return;
                runCount(entry.target);
                obs.unobserve(entry.target);
            });
        }, { threshold: 0.35 });
        counters.forEach((el) => counterObserver.observe(el));
    }

    window.showToast = (message) => {
        const toast = $("[data-toast]");
        if (!toast) return;
        toast.textContent = message;
        toast.classList.add("show");
        window.clearTimeout(toast._timer);
        toast._timer = window.setTimeout(() => toast.classList.remove("show"), 2800);
    };
})();
