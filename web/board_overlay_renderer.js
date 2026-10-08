/* Shared, presentation-only SVG overlay projector for native WebView and Web.
   No fetch, no innerHTML, no persistent state or chess-rule authority. */
(() => {
  "use strict";
  const SVG = "http://www.w3.org/2000/svg";
  const validSquare = value => typeof value === "string" && /^[a-h][1-8]$/.test(value);
  const validColor = value => typeof value === "string" && /^#[0-9a-fA-F]{6}$/.test(value);
  const validPurpose = value => typeof value === "string" && /^[a-z0-9_-]{1,32}$/.test(value);
  const svgNode = name => document.createElementNS(SVG,name);
  function project(grid, ordered, visual) {
    if (!grid) return;
    const holder=grid.parentElement || grid.parentNode;
    const summary=holder && typeof holder.querySelector==="function" ?
      holder.querySelector(".ac42-board-annotation-summary") : null;
    if (summary) summary.textContent="";
    if (!Array.isArray(ordered) || ordered.length !== 64 || !visual) return;
    const cells = [...grid.querySelectorAll('[role="gridcell"]')];
    if (cells.length !== 64) return;
    const positions = new Map();
    ordered.forEach((cell,index) => {
      if (cell && validSquare(cell.square) && !positions.has(cell.square)) {
        positions.set(cell.square, index);
      }
    });
    if (positions.size !== 64) return;
    const en=!!(document.documentElement && document.documentElement.lang==="en");
    const labelFor=(purpose)=> {
      const meanings={attack:["Атака","Attack"],defence:["Захист","Defence"],
        idea:["Ідея","Idea"],legal:["Дозволений хід","Legal move"],
        target:["Ціль","Target"],selected:["Вибір","Selection"],
        custom:["Позначка","Mark"],"last-move":["Останній хід","Last move"]};
      const pair=meanings[purpose];
      return pair ? pair[en?1:0] : purpose;
    };
    const descriptions=[];
    const highlights = Array.isArray(visual.highlights) ? visual.highlights.slice(0,64) : [];
    for (const item of highlights) {
      if (!item || !validSquare(item.square) || !validColor(item.color)
          || !validPurpose(item.purpose)) continue;
      const index = positions.get(item.square);
      const node = cells[index];
      if (!node) continue;
      descriptions.push(labelFor(item.purpose)+": "+item.square);
      node.dataset.ac42Highlight = "true";
      node.dataset.ac42HighlightPurpose = item.purpose;
      node.style.setProperty("--ac42-highlight-color",item.color);
    }
    const arrows = Array.isArray(visual.arrows) ? visual.arrows.slice(0,48) : [];
    if (!arrows.length) {if(summary)summary.textContent=descriptions.join("; ");return;}
    const svg = svgNode("svg");
    svg.classList.add("ac42-board-arrows");
    svg.setAttribute("viewBox","0 0 800 800");
    svg.setAttribute("preserveAspectRatio","none");
    svg.setAttribute("aria-hidden","true");
    svg.setAttribute("focusable","false");
    let plotted = 0;
    for (const item of arrows) {
      if (!item || !validSquare(item.from) || !validSquare(item.to)
          || item.from === item.to || !positions.has(item.from)
          || !positions.has(item.to) || !validColor(item.color)
          || !validPurpose(item.purpose)) continue;
      descriptions.push(labelFor(item.purpose)+": "+item.from+"–"+item.to);
      const from = positions.get(item.from), to = positions.get(item.to);
      const sx = 50+(from%8)*100, sy = 50+Math.floor(from/8)*100;
      const ex = 50+(to%8)*100, ey = 50+Math.floor(to/8)*100;
      const dx = ex-sx, dy = ey-sy, length = Math.hypot(dx,dy);
      if (length < 1) continue;
      const ux = dx/length, uy = dy/length;
      const tx=ex-ux*16, ty=ey-uy*16, bx=ex-ux*39, by=ey-uy*39;
      const shape=svgNode("line");
      shape.setAttribute("x1",String(sx));shape.setAttribute("y1",String(sy));
      shape.setAttribute("x2",String(tx));shape.setAttribute("y2",String(ty));
      shape.setAttribute("stroke",item.color);
      shape.setAttribute("stroke-width","12");
      shape.setAttribute("stroke-linecap","round");
      svg.appendChild(shape);
      const head=svgNode("polygon");
      head.setAttribute("points",[
        [tx,ty],[bx-uy*17,by+ux*17],[bx+uy*17,by-ux*17]
      ].map(x=>x.map(Math.round).join(",")).join(" "));
      head.setAttribute("fill",item.color);
      svg.appendChild(head);
      plotted++;
    }
    if (plotted > 0) grid.appendChild(svg);
    if(summary)summary.textContent=descriptions.join("; ");
  }
  globalThis.AccessibleChessBoardOverlay = Object.freeze({project});
})();
