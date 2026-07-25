(() => {
  "use strict";

  const TAU = Math.PI * 2;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const heroCanvas = document.querySelector("#hero-scene");
  const posterCanvases = [...document.querySelectorAll("canvas[data-poster]")];
  let heroVisible = true;
  let heroFrame = 0;
  let lastHeroPaint = 0;
  let resizeTimer = 0;
  let toastTimer = 0;

  function randomFactory(seed) {
    let value = seed >>> 0;
    return () => {
      value += 0x6d2b79f5;
      let next = value;
      next = Math.imul(next ^ (next >>> 15), next | 1);
      next ^= next + Math.imul(next ^ (next >>> 7), next | 61);
      return ((next ^ (next >>> 14)) >>> 0) / 4294967296;
    };
  }

  function prepareCanvas(canvas) {
    const bounds = canvas.getBoundingClientRect();
    const width = Math.max(1, Math.round(bounds.width));
    const height = Math.max(1, Math.round(bounds.height));
    const scale = Math.min(2, window.devicePixelRatio || 1);
    const pixelWidth = Math.round(width * scale);
    const pixelHeight = Math.round(height * scale);
    if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
      canvas.width = pixelWidth;
      canvas.height = pixelHeight;
    }
    const context = canvas.getContext("2d");
    context.setTransform(scale, 0, 0, scale, 0, 0);
    context.imageSmoothingEnabled = true;
    return { context, width, height };
  }

  function fill(context, color, x, y, width, height) {
    context.fillStyle = color;
    context.fillRect(x, y, width, height);
  }

  function line(context, color, width, points, close = false) {
    if (!points.length) return;
    context.beginPath();
    context.moveTo(points[0][0], points[0][1]);
    points.slice(1).forEach(([x, y]) => context.lineTo(x, y));
    if (close) context.closePath();
    context.strokeStyle = color;
    context.lineWidth = width;
    context.stroke();
  }

  function polygon(context, color, points) {
    if (!points.length) return;
    context.beginPath();
    context.moveTo(points[0][0], points[0][1]);
    points.slice(1).forEach(([x, y]) => context.lineTo(x, y));
    context.closePath();
    context.fillStyle = color;
    context.fill();
  }

  function circle(context, color, x, y, radius) {
    context.beginPath();
    context.arc(x, y, radius, 0, TAU);
    context.fillStyle = color;
    context.fill();
  }

  function drawStars(context, width, height, seed, count, colors) {
    const random = randomFactory(seed);
    for (let index = 0; index < count; index += 1) {
      const x = random() * width;
      const y = random() * height * 0.78;
      const size = random() > 0.91 ? 1.5 : random() > 0.6 ? 1 : 0.55;
      circle(context, colors[Math.floor(random() * colors.length)], x, y, size);
    }
  }

  function ellipseStroke(context, color, lineWidth, x, y, radiusX, radiusY, rotation, start = 0, end = TAU) {
    context.beginPath();
    context.ellipse(x, y, radiusX, radiusY, rotation, start, end);
    context.strokeStyle = color;
    context.lineWidth = lineWidth;
    context.stroke();
  }

  function drawHero(time = 0) {
    if (!heroCanvas) return;
    const { context, width, height } = prepareCanvas(heroCanvas);
    fill(context, "#081013", 0, 0, width, height);

    const random = randomFactory(7192026);
    for (let index = 0; index < 180; index += 1) {
      const x = random() * width;
      const y = random() * height;
      const pulse = 0.25 + random() * 0.55;
      context.globalAlpha = pulse;
      circle(context, index % 13 === 0 ? "#d7bc79" : "#b9cbc8", x, y, random() > 0.95 ? 1.4 : 0.65);
    }
    context.globalAlpha = 1;

    const horizon = height * 0.72;
    line(context, "rgba(116, 151, 148, 0.22)", 1, [[0, horizon], [width, horizon - height * 0.06]]);
    line(context, "rgba(116, 151, 148, 0.12)", 1, [[0, horizon + 38], [width, horizon - height * 0.015]]);

    const phase = reduceMotion.matches ? 0 : time * 0.00012;
    const gates = width < 720
      ? [
          [width * 0.74, height * 0.30, width * 0.26, height * 0.15, "#6f998e", 0.3],
          [width * 0.84, height * 0.66, width * 0.19, height * 0.11, "#bd9e5f", 1.1],
          [width * 0.28, height * 0.80, width * 0.14, height * 0.08, "#806c8e", 1.8],
        ]
      : [
          [width * 0.73, height * 0.37, width * 0.25, height * 0.29, "#6f998e", 0.3],
          [width * 0.91, height * 0.73, width * 0.16, height * 0.18, "#bd9e5f", 1.1],
          [width * 0.57, height * 0.82, width * 0.10, height * 0.12, "#806c8e", 1.8],
        ];

    gates.forEach(([x, y, radiusX, radiusY, color, offset], gateIndex) => {
      context.save();
      context.translate(x, y);
      context.rotate(-0.32 + gateIndex * 0.12);
      context.translate(-x, -y);
      ellipseStroke(context, `${color}99`, 1.2, x, y, radiusX, radiusY, 0, phase + offset, phase + offset + Math.PI * 1.5);
      ellipseStroke(context, `${color}55`, 6, x, y, radiusX * 0.84, radiusY * 0.84, 0, -phase + offset, -phase + offset + Math.PI * 1.2);
      ellipseStroke(context, `${color}bb`, 1, x, y, radiusX * 0.64, radiusY * 0.64, 0);
      for (let tick = 0; tick < 18; tick += 1) {
        const angle = (tick / 18) * TAU + phase;
        const px = x + Math.cos(angle) * radiusX;
        const py = y + Math.sin(angle) * radiusY;
        circle(context, color, px, py, tick % 5 === 0 ? 1.7 : 0.75);
      }
      context.restore();
    });

    const lowerRandom = randomFactory(3301);
    for (let index = 0; index < 22; index += 1) {
      const x = lowerRandom() * width;
      const base = height * (0.78 + lowerRandom() * 0.18);
      const peak = base - height * (0.025 + lowerRandom() * 0.08);
      polygon(context, index % 3 === 0 ? "#122528" : "#0d1b1e", [[x - 45, height], [x, peak], [x + 50, height]]);
    }

    context.globalAlpha = 0.4;
    for (let index = 0; index < 7; index += 1) {
      const y = horizon + index * 18;
      line(context, index % 2 ? "#47655f" : "#294744", 1, [[width * 0.44, y], [width, y - 30]]);
    }
    context.globalAlpha = 1;
  }

  function posterFrame(context, width, height, base, lineColor, seed) {
    fill(context, base, 0, 0, width, height);
    drawStars(context, width, height, seed, 72, ["rgba(255,255,255,0.45)", lineColor, "rgba(255,255,255,0.16)"]);
    context.strokeStyle = `${lineColor}88`;
    context.lineWidth = 1;
    context.strokeRect(14.5, 14.5, width - 29, height - 29);
    context.globalAlpha = 0.22;
    for (let index = 1; index < 5; index += 1) {
      line(context, lineColor, 1, [[14, (height / 5) * index], [width - 14, (height / 5) * index]]);
    }
    context.globalAlpha = 1;
  }

  function drawTaixuan(context, width, height) {
    posterFrame(context, width, height, "#102322", "#d3b768", 101);
    circle(context, "#d4b363", width * 0.29, height * 0.24, width * 0.09);
    circle(context, "#f0d995", width * 0.29, height * 0.24, width * 0.055);

    polygon(context, "#1d3c39", [[0, height * 0.70], [width * 0.22, height * 0.38], [width * 0.43, height * 0.70], [width * 0.68, height * 0.32], [width, height * 0.69], [width, height], [0, height]]);
    polygon(context, "#285147", [[0, height * 0.77], [width * 0.31, height * 0.53], [width * 0.52, height * 0.74], [width * 0.79, height * 0.47], [width, height * 0.68], [width, height], [0, height]]);
    polygon(context, "#142d2b", [[0, height * 0.82], [width * 0.25, height * 0.68], [width * 0.47, height * 0.80], [width * 0.74, height * 0.63], [width, height * 0.76], [width, height], [0, height]]);

    context.globalAlpha = 0.28;
    polygon(context, "#d9e0d6", [[0, height * 0.50], [width, height * 0.44], [width, height * 0.51], [0, height * 0.58]]);
    polygon(context, "#d9e0d6", [[0, height * 0.66], [width, height * 0.59], [width, height * 0.66], [0, height * 0.72]]);
    context.globalAlpha = 1;

    const templeX = width * 0.63;
    const templeY = height * 0.59;
    fill(context, "#0a1717", templeX - width * 0.11, templeY, width * 0.22, height * 0.14);
    polygon(context, "#0a1717", [[templeX - width * 0.16, templeY], [templeX, templeY - height * 0.055], [templeX + width * 0.16, templeY]]);
    fill(context, "#0a1717", templeX - width * 0.012, templeY - height * 0.14, width * 0.024, height * 0.12);
    polygon(context, "#0a1717", [[templeX - width * 0.08, templeY - height * 0.13], [templeX, templeY - height * 0.17], [templeX + width * 0.08, templeY - height * 0.13]]);
    line(context, "#d7c789", 1, [[width * 0.76, height * 0.22], [width * 0.84, height * 0.19], [width * 0.88, height * 0.21]]);
    line(context, "#d7c789", 1, [[width * 0.69, height * 0.28], [width * 0.74, height * 0.26], [width * 0.78, height * 0.28]]);
  }

  function drawMagic(context, width, height) {
    posterFrame(context, width, height, "#17182c", "#8eaed0", 202);
    circle(context, "#7e648d", width * 0.74, height * 0.23, width * 0.105);
    circle(context, "#b1c9dc", width * 0.74, height * 0.23, width * 0.072);
    circle(context, "#d8b975", width * 0.22, height * 0.31, width * 0.026);

    const constellation = [
      [width * 0.17, height * 0.18],
      [width * 0.30, height * 0.13],
      [width * 0.40, height * 0.25],
      [width * 0.52, height * 0.17],
      [width * 0.61, height * 0.29],
    ];
    line(context, "rgba(181, 203, 225, 0.55)", 1, constellation);
    constellation.forEach(([x, y]) => circle(context, "#dbe8f2", x, y, 2));

    polygon(context, "#29243e", [[0, height * 0.70], [width * 0.24, height * 0.55], [width * 0.42, height * 0.69], [width * 0.69, height * 0.49], [width, height * 0.70], [width, height], [0, height]]);
    polygon(context, "#131425", [[0, height * 0.80], [width * 0.24, height * 0.70], [width * 0.43, height * 0.75], [width * 0.72, height * 0.64], [width, height * 0.76], [width, height], [0, height]]);

    const castleBase = height * 0.70;
    fill(context, "#0c0d19", width * 0.22, castleBase - height * 0.17, width * 0.56, height * 0.22);
    [0.27, 0.43, 0.58, 0.73].forEach((x, index) => {
      const towerHeight = height * (index % 2 ? 0.30 : 0.24);
      fill(context, "#0c0d19", width * x - width * 0.045, castleBase - towerHeight, width * 0.09, towerHeight);
      polygon(context, "#0c0d19", [[width * x - width * 0.07, castleBase - towerHeight], [width * x, castleBase - towerHeight - height * 0.09], [width * x + width * 0.07, castleBase - towerHeight]]);
      circle(context, index === 2 ? "#d3aa62" : "#6e9bbd", width * x, castleBase - towerHeight * 0.45, 2.2);
    });

    ellipseStroke(context, "rgba(123, 160, 194, 0.55)", 1, width * 0.50, height * 0.57, width * 0.35, height * 0.055, -0.08);
    ellipseStroke(context, "rgba(199, 161, 100, 0.46)", 3, width * 0.50, height * 0.57, width * 0.25, height * 0.035, -0.08, 0.3, 4.7);
  }

  function drawStellar(context, width, height) {
    posterFrame(context, width, height, "#081a20", "#70b09e", 303);
    const starX = width * 0.47;
    const starY = height * 0.31;
    circle(context, "rgba(198, 163, 93, 0.16)", starX, starY, width * 0.16);
    circle(context, "rgba(198, 163, 93, 0.28)", starX, starY, width * 0.115);
    circle(context, "#d0aa5e", starX, starY, width * 0.067);
    circle(context, "#f1dc9b", starX, starY, width * 0.036);

    const ringColors = ["#6fae9c", "#81a7bc", "#c2a45f", "#587c78"];
    for (let index = 0; index < 12; index += 1) {
      const radiusX = width * (0.14 + index * 0.025);
      const radiusY = height * (0.032 + index * 0.007);
      ellipseStroke(context, `${ringColors[index % ringColors.length]}aa`, index % 4 === 0 ? 2.8 : 1, starX, starY, radiusX, radiusY, -0.28, index * 0.18, 5.1 + index * 0.07);
    }
    ellipseStroke(context, "rgba(183, 83, 73, 0.7)", 2, starX, starY, width * 0.43, height * 0.13, -0.28, 3.8, 6.2);

    polygon(context, "#102f34", [[0, height * 0.70], [width * 0.22, height * 0.61], [width * 0.52, height * 0.67], [width * 0.78, height * 0.57], [width, height * 0.67], [width, height], [0, height]]);
    fill(context, "#071215", 0, height * 0.73, width, height * 0.27);
    for (let index = 0; index < 11; index += 1) {
      const x = width * (0.06 + index * 0.085);
      const towerHeight = height * (0.035 + (index % 4) * 0.02);
      fill(context, "#17363a", x, height * 0.73 - towerHeight, width * 0.035, towerHeight);
      circle(context, index % 3 === 0 ? "#d2a85c" : "#6ba994", x + width * 0.0175, height * 0.73 - towerHeight * 0.55, 1.2);
    }
    line(context, "#5a8f82", 2, [[0, height * 0.79], [width, height * 0.73]]);
    line(context, "rgba(108, 153, 164, 0.55)", 1, [[0, height * 0.84], [width, height * 0.77]]);

    const ship = [[width * 0.77, height * 0.18], [width * 0.82, height * 0.20], [width * 0.76, height * 0.21]];
    polygon(context, "#b8d3cd", ship);
    line(context, "rgba(111, 149, 176, 0.55)", 1, [[width * 0.76, height * 0.205], [width * 0.68, height * 0.24]]);
  }

  function drawPosters() {
    posterCanvases.forEach((canvas) => {
      const { context, width, height } = prepareCanvas(canvas);
      switch (canvas.dataset.poster) {
        case "taixuan":
          drawTaixuan(context, width, height);
          break;
        case "magic":
          drawMagic(context, width, height);
          break;
        case "stellar":
          drawStellar(context, width, height);
          break;
        default:
          fill(context, "#101416", 0, 0, width, height);
      }
    });
  }

  function animateHero(time) {
    if (heroVisible && (!lastHeroPaint || time - lastHeroPaint > 38)) {
      drawHero(time);
      lastHeroPaint = time;
    }
    heroFrame = window.requestAnimationFrame(animateHero);
  }

  function startHero() {
    window.cancelAnimationFrame(heroFrame);
    drawHero(0);
    if (!reduceMotion.matches) {
      heroFrame = window.requestAnimationFrame(animateHero);
    }
  }

  function activateTab(tab) {
    const tabs = [...document.querySelectorAll('[role="tab"]')];
    tabs.forEach((candidate) => {
      const selected = candidate === tab;
      candidate.setAttribute("aria-selected", String(selected));
      candidate.tabIndex = selected ? 0 : -1;
      const panel = document.querySelector(`#${candidate.getAttribute("aria-controls")}`);
      if (panel) panel.hidden = !selected;
    });
  }

  function setupTabs() {
    const tabs = [...document.querySelectorAll('[role="tab"]')];
    tabs.forEach((tab, index) => {
      tab.addEventListener("click", () => activateTab(tab));
      tab.addEventListener("keydown", (event) => {
        let nextIndex = index;
        if (event.key === "ArrowRight") nextIndex = (index + 1) % tabs.length;
        else if (event.key === "ArrowLeft") nextIndex = (index - 1 + tabs.length) % tabs.length;
        else if (event.key === "Home") nextIndex = 0;
        else if (event.key === "End") nextIndex = tabs.length - 1;
        else return;
        event.preventDefault();
        activateTab(tabs[nextIndex]);
        tabs[nextIndex].focus();
      });
    });
  }

  function setupGlossary() {
    const input = document.querySelector("#glossary-search");
    const count = document.querySelector("#glossary-count");
    const empty = document.querySelector("#glossary-empty");
    const terms = [...document.querySelectorAll("#glossary-list [data-term]")];
    if (!input || !count || !empty) return;
    input.addEventListener("input", () => {
      const query = input.value.trim().toLocaleLowerCase("zh-CN");
      let visible = 0;
      terms.forEach((term) => {
        const matches = !query || term.dataset.term.toLocaleLowerCase("zh-CN").includes(query);
        term.hidden = !matches;
        if (matches) visible += 1;
      });
      count.textContent = `${visible} 个词条`;
      empty.hidden = visible !== 0;
    });
  }

  async function copyText(value) {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(value);
      return;
    }
    const field = document.createElement("textarea");
    field.value = value;
    field.setAttribute("readonly", "");
    field.style.position = "fixed";
    field.style.opacity = "0";
    document.body.append(field);
    field.select();
    const copied = document.execCommand("copy");
    field.remove();
    if (!copied) throw new Error("copy failed");
  }

  function showToast(message) {
    const toast = document.querySelector("#copy-toast");
    if (!toast) return;
    window.clearTimeout(toastTimer);
    toast.textContent = message;
    toast.classList.add("is-visible");
    toastTimer = window.setTimeout(() => toast.classList.remove("is-visible"), 1800);
  }

  function setupCopyButtons() {
    document.querySelectorAll("[data-copy-command]").forEach((button) => {
      button.addEventListener("click", async () => {
        const command = button.dataset.copyCommand;
        try {
          await copyText(command);
          showToast(`已复制：${command.trim()}`);
        } catch {
          showToast(`命令：${command.trim()}`);
        }
      });
    });
  }

  function setupSectionTracking() {
    const links = [...document.querySelectorAll(".site-nav a[href^='#']")];
    const sections = links
      .map((link) => document.querySelector(link.getAttribute("href")))
      .filter(Boolean);
    if (!("IntersectionObserver" in window)) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
        if (!visible) return;
        links.forEach((link) => {
          const current = link.getAttribute("href") === `#${visible.target.id}`;
          if (current) link.setAttribute("aria-current", "page");
          else link.removeAttribute("aria-current");
        });
      },
      { rootMargin: "-18% 0px -64% 0px", threshold: [0, 0.08, 0.25] },
    );
    sections.forEach((section) => observer.observe(section));

    if (heroCanvas) {
      const heroObserver = new IntersectionObserver(([entry]) => {
        heroVisible = entry.isIntersecting;
      });
      heroObserver.observe(heroCanvas);
    }
  }

  function redraw() {
    drawPosters();
    drawHero(lastHeroPaint || 0);
  }

  window.addEventListener("resize", () => {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(redraw, 120);
  });
  reduceMotion.addEventListener("change", startHero);

  drawPosters();
  startHero();
  setupTabs();
  setupGlossary();
  setupCopyButtons();
  setupSectionTracking();
})();
