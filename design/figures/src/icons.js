// 实心 glyph：20×20 网格，可见区 2–18，镂空用 SVG mask 做成真孔（与 SideIcons.tsx 同一写法）
// 用法：<i class="ic" data-ic="clock"></i>  或  <span class="tile" style="background:var(--hue-time)" data-ic="clock"></span>
(function () {
  const C = 'fill="black"';
  const CS = (w) => `fill="none" stroke="black" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round"`;
  const G = {
    clock: {
      shape: '<circle cx="10" cy="10" r="8"/>',
      cut: `<path ${CS(1.8)} d="M10 5.6V10l3 2"/>`,
    },
    grid: {
      shape:
        '<rect x="2.5" y="2.5" width="6.6" height="6.6" rx="1.8"/><rect x="10.9" y="2.5" width="6.6" height="6.6" rx="1.8"/><rect x="2.5" y="10.9" width="6.6" height="6.6" rx="1.8"/><rect x="10.9" y="10.9" width="6.6" height="6.6" rx="1.8"/>',
    },
    people: {
      shape:
        '<circle cx="7.4" cy="6.4" r="3.1"/><path d="M7.4 10.9c-3.2 0-5.6 2-5.6 4.4 0 .7.5 1.2 1.2 1.2h8.8c.7 0 1.2-.5 1.2-1.2 0-2.4-2.4-4.4-5.6-4.4z"/><circle cx="13.9" cy="6.9" r="2.6"/><path d="M13.9 10.9c-.6 0-1.2.1-1.7.2 1.2.9 2 2.3 2 3.9v1.5h2.6c.6 0 1.1-.5 1.1-1.1 0-2.5-1.8-4.5-4-4.5z"/>',
    },
    leaf: {
      shape: '<path d="M17.2 2.8C9.6 2.6 3.4 6.4 3.4 12.4c0 1.2.3 2.3.8 3.2L2.6 17.2l1 1 1.6-1.6c.9.5 2 .8 3.2.8 6 0 9.4-6.4 8.8-14.6z"/>',
      cut: `<path ${CS(1.5)} d="M5.2 15.2c2.8-3 5.6-5.4 9-7.6"/>`,
    },
    sparkle: {
      shape:
        '<path d="M8.6 2.6c.2-.5.9-.5 1.1 0l1.2 3.3c.5 1.4 1.6 2.5 3 3l3.3 1.2c.5.2.5.9 0 1.1l-3.3 1.2c-1.4.5-2.5 1.6-3 3l-1.2 3.3c-.2.5-.9.5-1.1 0l-1.2-3.3c-.5-1.4-1.6-2.5-3-3L1.1 11.2c-.5-.2-.5-.9 0-1.1L4.4 8.9c1.4-.5 2.5-1.6 3-3z" transform="translate(1.2 -.8) scale(.92)"/><path d="M15.6 1.8c.1-.3.5-.3.6 0l.4 1.1c.2.5.5.8 1 1l1.1.4c.3.1.3.5 0 .6l-1.1.4c-.5.2-.8.5-1 1l-.4 1.1c-.1.3-.5.3-.6 0l-.4-1.1c-.2-.5-.5-.8-1-1l-1.1-.4c-.3-.1-.3-.5 0-.6l1.1-.4c.5-.2.8-.5 1-1z" transform="translate(-.6 .4)"/>',
    },
    chip: {
      shape:
        '<rect x="4.5" y="4.5" width="11" height="11" rx="2.6"/><rect x="7.4" y="2" width="1.5" height="2.4" rx=".75"/><rect x="11.1" y="2" width="1.5" height="2.4" rx=".75"/><rect x="7.4" y="15.6" width="1.5" height="2.4" rx=".75"/><rect x="11.1" y="15.6" width="1.5" height="2.4" rx=".75"/><rect x="2" y="7.4" width="2.4" height="1.5" rx=".75"/><rect x="2" y="11.1" width="2.4" height="1.5" rx=".75"/><rect x="15.6" y="7.4" width="2.4" height="1.5" rx=".75"/><rect x="15.6" y="11.1" width="2.4" height="1.5" rx=".75"/>',
      cut: `<rect ${C} x="7.7" y="7.7" width="4.6" height="4.6" rx="1.2"/>`,
    },
    doc: {
      shape: '<path d="M5.6 2h5.5l4.9 4.9v8.6a2.5 2.5 0 0 1-2.5 2.5H5.6a2.5 2.5 0 0 1-2.5-2.5v-11A2.5 2.5 0 0 1 5.6 2z"/>',
      cut: `<path ${CS(1.3)} d="M11.1 2.2v3.4c0 .8.5 1.3 1.3 1.3h3.5"/><rect ${C} x="6" y="10.1" width="8" height="1.5" rx=".75"/><rect ${C} x="6" y="13.2" width="5.2" height="1.5" rx=".75"/>`,
    },
    check: {
      shape: '<circle cx="10" cy="10" r="8"/>',
      cut: `<path ${CS(1.9)} d="M6.4 10.3l2.5 2.5 4.7-5.1"/>`,
    },
    xmark: {
      shape: '<circle cx="10" cy="10" r="8"/>',
      cut: `<path ${CS(1.9)} d="M7.3 7.3l5.4 5.4M12.7 7.3l-5.4 5.4"/>`,
    },
    exclam: {
      shape: '<circle cx="10" cy="10" r="8"/>',
      cut: `<rect ${C} x="9" y="5.2" width="2" height="6.2" rx="1"/><circle ${C} cx="10" cy="14" r="1.15"/>`,
    },
    triangle: {
      shape: '<path d="M8.5 3.2a1.7 1.7 0 0 1 3 0l6.2 11.2a1.7 1.7 0 0 1-1.5 2.6H3.8a1.7 1.7 0 0 1-1.5-2.6z"/>',
      cut: `<rect ${C} x="9.1" y="7" width="1.8" height="5" rx=".9"/><circle ${C} cx="10" cy="14.2" r="1.05"/>`,
    },
    info: {
      shape: '<circle cx="10" cy="10" r="8"/>',
      cut: `<circle ${C} cx="10" cy="6.3" r="1.15"/><rect ${C} x="9" y="8.6" width="2" height="5.6" rx="1"/>`,
    },
    seal: {
      shape: '',
      seal: true,
      cut: `<path ${CS(1.8)} d="M6.6 10.2l2.5 2.5 4.4-4.9"/>`,
    },
    list: {
      shape:
        '<circle cx="4" cy="5" r="1.6"/><circle cx="4" cy="10" r="1.6"/><circle cx="4" cy="15" r="1.6"/><rect x="7.4" y="4.1" width="10.6" height="1.8" rx=".9"/><rect x="7.4" y="9.1" width="10.6" height="1.8" rx=".9"/><rect x="7.4" y="14.1" width="10.6" height="1.8" rx=".9"/>',
    },
    table: {
      shape: '<rect x="2" y="3" width="16" height="14" rx="3"/>',
      cut: `<rect ${C} x="3.6" y="7.2" width="5.4" height="3.6" rx=".6"/><rect ${C} x="10.6" y="7.2" width="5.8" height="3.6" rx=".6"/><rect ${C} x="3.6" y="12" width="5.4" height="3.4" rx=".6"/><rect ${C} x="10.6" y="12" width="5.8" height="3.4" rx=".6"/>`,
    },
    graph: {
      shape:
        '<circle cx="5" cy="5" r="2.8"/><circle cx="15" cy="6.5" r="2.4"/><circle cx="8" cy="15" r="2.8"/><path d="M6.6 4.6l6.3 1.2-.3 1.5-6.3-1.2zM5.6 6.9l2 6.2-1.4.5-2-6.2zM13.8 8.1l-4.4 5.6-1.2-.9 4.4-5.6z"/>',
    },
    funnel: {
      shape: '<path d="M2.8 3.2h14.4c.9 0 1.3 1 .8 1.7l-5.3 6.4v5.1c0 .5-.3 1-.8 1.1l-2.4.8c-.6.2-1.2-.2-1.2-.9v-6.1L2 4.9c-.5-.7-.1-1.7.8-1.7z"/>',
    },
    merge: {
      shape:
        '<rect x="2" y="2.6" width="5.2" height="5.2" rx="1.6"/><rect x="2" y="12.2" width="5.2" height="5.2" rx="1.6"/><rect x="12.4" y="7.4" width="5.6" height="5.2" rx="1.6"/><path d="M7 4.6h1.6c1.2 0 2.2 1 2.2 2.2v1.9h1.7v2.6h-1.7v1.9c0 1.2-1 2.2-2.2 2.2H7v-1.6h1.6c.4 0 .6-.3.6-.6V7c0-.4-.3-.6-.6-.6H7z"/>',
    },
    shield: {
      shape: '<path d="M10 1.8l6.4 2.6c.4.2.6.5.6.9v4.4c0 4-2.7 7.2-6.6 8.5-.3.1-.6.1-.8 0C5.7 16.9 3 13.7 3 9.7V5.3c0-.4.2-.7.6-.9z"/>',
      cut: `<path ${CS(1.8)} d="M6.9 9.8l2.2 2.2 4-4.4"/>`,
    },
    calendar: {
      shape: '<rect x="2" y="3.6" width="16" height="14" rx="3"/><rect x="5.4" y="1.8" width="1.8" height="3.6" rx=".9"/><rect x="12.8" y="1.8" width="1.8" height="3.6" rx=".9"/>',
      cut: `<rect ${C} x="3.4" y="7.4" width="13.2" height="1.4" rx=".7"/><rect ${C} x="5" y="10.6" width="2.4" height="2.2" rx=".6"/><rect ${C} x="8.8" y="10.6" width="2.4" height="2.2" rx=".6"/><rect ${C} x="12.6" y="10.6" width="2.4" height="2.2" rx=".6"/><rect ${C} x="5" y="13.8" width="2.4" height="2.2" rx=".6"/><rect ${C} x="8.8" y="13.8" width="2.4" height="2.2" rx=".6"/>`,
    },
    person: {
      shape: '<circle cx="10" cy="6.4" r="3.6"/><path d="M10 11.6c-3.8 0-6.5 2.3-6.5 5 0 .8.6 1.4 1.4 1.4h10.2c.8 0 1.4-.6 1.4-1.4 0-2.7-2.7-5-6.5-5z"/>',
    },
    tag: {
      shape: '<path d="M2.4 3.8c0-.8.6-1.4 1.4-1.4h5.6c.4 0 .7.1 1 .4l7.2 7.2c.5.5.5 1.4 0 2l-5.6 5.6c-.5.5-1.4.5-2 0L2.8 10.4c-.3-.3-.4-.6-.4-1z"/>',
      cut: `<circle ${C} cx="6.4" cy="6.4" r="1.6"/>`,
    },
    search: {
      shape: '<path d="M8.6 2.4a6.2 6.2 0 0 1 5 9.9l3.9 3.9c.4.4.4 1 0 1.4-.4.4-1 .4-1.4 0l-3.9-3.9A6.2 6.2 0 1 1 8.6 2.4z"/>',
      cut: `<circle ${C} cx="8.6" cy="8.6" r="4.1"/>`,
    },
    stack: {
      shape:
        '<path d="M10 2.2l7.6 3.7c.6.3.6 1.2 0 1.5L10 11.1 2.4 7.4c-.6-.3-.6-1.2 0-1.5z"/><path d="M3.8 9.6L10 12.6l6.2-3 1.4.7c.6.3.6 1.2 0 1.5L10 15.5l-7.6-3.7c-.6-.3-.6-1.2 0-1.5z"/><path d="M3.8 13.4l6.2 3 6.2-3 1.4.7c.6.3.6 1.2 0 1.5L10 19 2.4 15.6c-.6-.3-.6-1.2 0-1.5z" transform="translate(0 -1.2)"/>',
    },
    uturn: {
      shape: '<path d="M8.6 2.8c.4.4.4 1 0 1.4L7 5.8h4.6a5.6 5.6 0 0 1 0 11.2H6.4c-.6 0-1-.4-1-1s.4-1 1-1h5.2a3.6 3.6 0 0 0 0-7.2H7l1.6 1.6c.4.4.4 1 0 1.4-.4.4-1 .4-1.4 0L3.9 7.5c-.4-.4-.4-1 0-1.4l3.3-3.3c.4-.4 1-.4 1.4 0z"/>',
    },
    bolt: {
      shape: '<path d="M11.4 1.9c.3-.6 1.1-.3 1 .3l-.9 5.9h4.2c.6 0 .9.7.5 1.1l-7.7 8.9c-.4.5-1.2.1-1.1-.5l.9-5.6H4.2c-.6 0-.9-.7-.5-1.1z"/>',
    },
    pencil: {
      shape: '<path d="M13.2 2.9c.8-.8 2.1-.8 2.9 0l1 1c.8.8.8 2.1 0 2.9l-9.3 9.3-4.4 1.2c-.5.1-1-.3-.8-.8l1.2-4.4z"/>',
    },
    flag: {
      shape: '<rect x="3.6" y="2" width="1.8" height="16" rx=".9"/><path d="M5.4 3.2c3.2-1.6 5 1.2 8.8 0 .8-.2 1.6.1 1.6.9v6.6c0 .4-.3.8-.7.9-3.9 1.4-5.6-1.5-9.7.3z"/>',
    },
    cube: {
      shape: '<path d="M10 1.8l7 3.6v9.2L10 18.2 3 14.6V5.4z"/>',
      cut: `<path ${CS(1.4)} d="M3.4 5.6L10 9l6.6-3.4M10 9v8.8"/>`,
    },
    cloud: {
      shape: '<path d="M14.6 16H5.8a4 4 0 0 1-.7-7.94A5.2 5.2 0 0 1 15 6.6a4.7 4.7 0 0 1-.4 9.4z"/>',
    },
    sum: {
      shape: '<path d="M4.4 2.8h11.2c.6 0 1 .4 1 1v1.6c0 .6-.4 1-1 1s-1-.4-1-1v-.6H7.3l4.3 5.2-4.3 5.2h7.3v-.6c0-.6.4-1 1-1s1 .4 1 1v1.6c0 .6-.4 1-1 1H4.4c-.8 0-1.3-1-.8-1.6L8.9 10 3.6 4.4c-.5-.6 0-1.6.8-1.6z"/>',
    },
  };

  function rosette(cx, cy, rOut, rIn, lobes) {
    const pts = [];
    for (let i = 0; i < lobes * 2; i++) {
      const a = (Math.PI * i) / lobes - Math.PI / 2;
      const r = i % 2 === 0 ? rOut : rIn;
      pts.push(`${(cx + r * Math.cos(a)).toFixed(2)} ${(cy + r * Math.sin(a)).toFixed(2)}`);
    }
    return `M${pts.join('L')}Z`;
  }

  let uid = 0;
  window.iconSVG = function (name) {
    const g = G[name];
    if (!g) return '';
    const id = 'm' + uid++;
    const shape = g.seal
      ? `<path d="${rosette(10, 10, 8.6, 7.5, 10)}" stroke="currentColor" stroke-width="1" stroke-linejoin="round"/>`
      : g.shape;
    const mask = g.cut
      ? `<mask id="${id}" maskUnits="userSpaceOnUse" x="0" y="0" width="20" height="20"><rect x="0" y="0" width="20" height="20" fill="white"/>${g.cut}</mask>`
      : '';
    return `<svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">${mask}<g${g.cut ? ` mask="url(#${id})"` : ''}>${shape}</g></svg>`;
  };
  window.chevronSVG = function () {
    return '<svg viewBox="0 0 12 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 4l6 6-6 6"/></svg>';
  };
  function hydrate(root) {
    root.querySelectorAll('[data-ic]').forEach((el) => {
      el.innerHTML = window.iconSVG(el.getAttribute('data-ic'));
    });
    root.querySelectorAll('.chev').forEach((el) => {
      if (!el.innerHTML.trim()) el.innerHTML = window.chevronSVG();
    });
  }
  window.hydrateIcons = hydrate;
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => hydrate(document));
  } else {
    hydrate(document);
  }
})();
