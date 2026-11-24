// Aircraft silhouettes for the /live map, generated at runtime as signed
// distance field (SDF) images so MapLibre can tint them per altitude
// (icon-color) and outline them (icon-halo-*). Shapes are original simple
// outlines on a 48x48 grid, nose up; MapLibre rotates them by track.

export const SDF_RADIUS = 8;
export const SDF_CUTOFF = 0.25;
const GRID = 48;
const SCALE = 1; // texels per grid unit
const PAD = SDF_RADIUS;
export const ICON_SIZE = GRID * SCALE + PAD * 2;

const poly = (points) => ({ type: "poly", points });
const circle = (cx, cy, r) => ({ type: "circle", cx, cy, r });
const rect = (x, y, w, h, angle = 0) => ({ type: "rect", x, y, w, h, angle });

export const SHAPE_PATHS = Object.freeze({
  airliner: [poly([[24, 2], [26.5, 6], [27, 18], [44, 28], [44, 31], [27, 26], [26.5, 38], [33, 43], [33, 45.5], [24, 43.5], [15, 45.5], [15, 43], [21.5, 38], [21, 26], [4, 31], [4, 28], [21, 18], [21.5, 6]])],
  heavy: [poly([[24, 1], [27.5, 5], [28, 17], [47, 29], [47, 32.5], [28, 26.5], [27.5, 38], [35, 43], [35, 46], [24, 43.5], [13, 46], [13, 43], [20.5, 38], [20, 26.5], [1, 32.5], [1, 29], [20, 17], [20.5, 5]])],
  jet_small: [poly([[24, 4], [26, 8], [26.5, 22], [39, 30], [39, 32], [26.5, 29], [26, 38], [31, 42], [31, 44], [24, 42.5], [17, 44], [17, 42], [22, 38], [21.5, 29], [9, 32], [9, 30], [21.5, 22], [22, 8]])],
  prop: [poly([[24, 6], [25.8, 9], [26, 16], [44, 17], [44, 21], [26, 21.5], [25.5, 34], [31, 36], [31, 39], [24, 38.5], [17, 39], [17, 36], [22.5, 34], [22, 21.5], [4, 21], [4, 17], [22, 16], [22.2, 9]])],
  helicopter: [circle(24, 20, 7), rect(22.8, 24, 2.4, 20), rect(19, 41, 10, 2.5), rect(4, 19, 40, 2.2, 45), rect(4, 19, 40, 2.2, -45)],
  glider: [poly([[24, 8], [25, 10], [25.3, 20], [47, 22], [47, 24], [25.3, 24], [25, 40], [29, 41], [29, 43], [24, 42.5], [19, 43], [19, 41], [23, 40], [22.7, 24], [1, 24], [1, 22], [22.7, 20], [23, 10]])],
  balloon: [circle(24, 19, 14), rect(21, 38, 6, 6), rect(17, 30, 1.6, 9, -20), rect(29.4, 30, 1.6, 9, 20)],
  uav: [poly([[24, 8], [27, 22], [44, 30], [44, 33], [27, 30], [26, 40], [30, 44], [18, 44], [22, 40], [21, 30], [4, 33], [4, 30], [21, 22]])],
  ground: [rect(17, 8, 14, 32)],
  unknown: [poly([[24, 4], [40, 42], [24, 34], [8, 42]])],
});

// Signed distance field from a coverage mask (0..1 per texel), as MapLibre
// expects for sdf images: alpha = 1 - (d / radius + cutoff), d > 0 outside.
export function maskToSdf(mask, width, height, radius = SDF_RADIUS, cutoff = SDF_CUTOFF) {
  const out = new Uint8ClampedArray(width * height * 4);
  const inside = (x, y) => mask[y * width + x] >= 0.5;
  const r = Math.ceil(radius);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const self = inside(x, y);
      let best = radius;
      for (let dy = -r; dy <= r; dy += 1) {
        const yy = y + dy;
        if (yy < 0 || yy >= height) continue;
        for (let dx = -r; dx <= r; dx += 1) {
          const xx = x + dx;
          if (xx < 0 || xx >= width) continue;
          if (inside(xx, yy) !== self) {
            const d = Math.hypot(dx, dy) - 0.5;
            if (d < best) best = d;
          }
        }
      }
      const signed = self ? -best : best;
      const value = 1 - (signed / radius + cutoff);
      out[(y * width + x) * 4 + 3] = Math.round(Math.min(1, Math.max(0, value)) * 255);
    }
  }
  return out;
}

function drawShape(ctx, parts) {
  ctx.save();
  ctx.translate(PAD, PAD);
  ctx.scale(SCALE, SCALE);
  ctx.fillStyle = "#fff";
  for (const part of parts) {
    ctx.beginPath();
    if (part.type === "poly") {
      part.points.forEach(([px, py], i) => (i ? ctx.lineTo(px, py) : ctx.moveTo(px, py)));
      ctx.closePath();
      ctx.fill();
    } else if (part.type === "circle") {
      ctx.arc(part.cx, part.cy, part.r, 0, Math.PI * 2);
      ctx.fill();
    } else if (part.type === "rect") {
      ctx.save();
      ctx.translate(part.x + part.w / 2, part.y + part.h / 2);
      ctx.rotate((part.angle * Math.PI) / 180);
      ctx.fillRect(-part.w / 2, -part.h / 2, part.w, part.h);
      ctx.restore();
    }
  }
  ctx.restore();
}

// Browser only: rasterise every shape and convert it to an SDF image.
export function createAircraftImages(doc = globalThis.document) {
  const canvas = doc.createElement("canvas");
  canvas.width = ICON_SIZE;
  canvas.height = ICON_SIZE;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  return Object.entries(SHAPE_PATHS).map(([shape, parts]) => {
    ctx.clearRect(0, 0, ICON_SIZE, ICON_SIZE);
    drawShape(ctx, parts);
    const { data } = ctx.getImageData(0, 0, ICON_SIZE, ICON_SIZE);
    const mask = new Float32Array(ICON_SIZE * ICON_SIZE);
    for (let i = 0; i < mask.length; i += 1) mask[i] = data[i * 4 + 3] / 255;
    return {
      id: `sw-ac-${shape}`,
      image: { width: ICON_SIZE, height: ICON_SIZE, data: maskToSdf(mask, ICON_SIZE, ICON_SIZE) },
      options: { sdf: true, pixelRatio: 2 },
    };
  });
}
