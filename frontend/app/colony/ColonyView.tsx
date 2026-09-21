"use client";

import { useEffect, useRef, useState } from "react";
import type { Generated } from "./citygen";
import { describe, seedNumber } from "./ground";
import { makeGrain, paintProps, paintTerrain } from "./draw";

// Zoomed all the way out means the whole colony on screen, so the floor is not a constant:
// at 768 cells a side, six kilometres of ground in an 800-pixel window is about one pixel per
// cell, and a fixed floor of three would have made a third of the map unreachable.
const MAX_SCALE = 42;

/** Dove sta guardando la camera, in celle. La minimappa lo disegna, e il click sulla
 *  minimappa lo sposta -- quindi deve uscire da qui invece di restare in una chiusura. */
export type Camera = { x0: number; y0: number; x1: number; y1: number };

export default function ColonyView(
  { ground, onCamera, goTo }: {
    ground: Generated;
    onCamera?: (camera: Camera) => void;
    /** Un contenitore che la minimappa riempie con "portami qui". Non uno stato di React:
     *  una panoramica non deve passare da un render. */
    goTo?: { current: ((x: number, y: number) => void) | null };
  },
) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [hover, setHover] = useState<string | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d")!;
    const seed = seedNumber(ground.seed);
    const terrain = paintTerrain(ground, seed);
    const grain = context.createPattern(makeGrain(seed), "repeat")!;
    const coarse = context.createPattern(makeGrain(seed ^ 0x9e3779b9, 96), "repeat")!;

    // The camera: pixels per cell, and which cell sits at the top-left. Kept in a ref-like
    // closure rather than in state, because a pan must not go through React.
    let scale = 0;
    let originX = 0;
    let originY = 0;
    let frame = 0;

    function fit() {
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const width = canvas!.clientWidth;
      const height = canvas!.clientHeight;
      canvas!.width = Math.round(width * dpr);
      canvas!.height = Math.round(height * dpr);
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (scale === 0) {
        scale = minScale();
        originX = ground.size / 2 - width / (2 * scale);
        originY = ground.size / 2 - height / (2 * scale);
      }
      clampOrigin();
      schedule();
    }

    /** The widest the camera goes: the ground COVERS the window, never letterboxed.
     *
     *  Taking the shorter side instead would fit the whole colony on screen and leave black
     *  bars beside it -- correct for a map viewer, wrong for a game screen. Seeing the whole
     *  colony at once is the minimap's job; this canvas is the ground you stand on. */
    function minScale(): number {
      const width = canvas!.clientWidth;
      const height = canvas!.clientHeight;
      return Math.max(width, height) / ground.size;
    }

    function clampOrigin() {
      const width = canvas!.clientWidth / scale;
      const height = canvas!.clientHeight / scale;
      // Never show anything that is not ground: a colony has edges and they are real.
      originX = Math.max(-0.5, Math.min(ground.size - width + 0.5, originX));
      originY = Math.max(-0.5, Math.min(ground.size - height + 0.5, originY));
      if (width >= ground.size) originX = (ground.size - width) / 2;
      if (height >= ground.size) originY = (ground.size - height) / 2;
    }

    function schedule() {
      if (frame) return;
      frame = requestAnimationFrame(() => { frame = 0; paint(); report(); });
    }

    function report() {
      if (!onCamera) return;
      onCamera({
        x0: originX, y0: originY,
        x1: originX + canvas!.clientWidth / scale,
        y1: originY + canvas!.clientHeight / scale,
      });
    }

    function paint() {
      const width = canvas!.clientWidth;
      const height = canvas!.clientHeight;
      // Smoothing on, always. Nearest-neighbour turns the terrain buffer into a mosaic of
      // squares at any real zoom; the texture comes from the grain laid over the top.
      context.imageSmoothingEnabled = true;
      context.fillStyle = "#0b1016";
      context.fillRect(0, 0, width, height);
      context.save();
      context.translate(-originX * scale, -originY * scale);
      context.drawImage(terrain, 0, 0, ground.size * scale, ground.size * scale);
      // The fine texture, at screen resolution and therefore the same crispness at every zoom.
      // La grana fine e' una cosa da VICINO. A tutta mappa sono seicentomila celle sotto un
      // velo di puntini: si legge come carta vetrata, non come terra. Il terreno larga scala
      // ce l'ha gia' dentro il buffer, quindi qui la si fa entrare solo quando ci si avvicina.
      const closeness = Math.max(0, Math.min(1, (scale - 3) / 11));
      if (closeness > 0) {
        context.save();
        context.globalAlpha = 0.04 + 0.12 * closeness;
        context.fillStyle = grain;
        context.fillRect(originX * scale, originY * scale, width, height);
        // E una seconda passata ANCORATA AL TERRENO, che cresce insieme a lui. Il buffer ha
        // due pixel per cella: ingrandito a venti e' una poltiglia sfocata, e fra un cespuglio
        // e l'altro restava una tinta unita. Questa e' la terra da vicino.
        if (scale > 6) {
          coarse.setTransform(new DOMMatrix().scale(scale / 7));
          context.globalAlpha = 0.05 + 0.07 * closeness;
          context.fillStyle = coarse;
          context.fillRect(originX * scale, originY * scale, width, height);
        }
        context.restore();
      }
      paintProps(context, ground, seed, {
        x0: originX, y0: originY,
        x1: originX + width / scale, y1: originY + height / scale, scale,
      });
      context.restore();
    }

    function cellAt(event: PointerEvent): [number, number] | null {
      const rect = canvas!.getBoundingClientRect();
      const x = Math.floor(originX + (event.clientX - rect.left) / scale);
      const y = Math.floor(originY + (event.clientY - rect.top) / scale);
      if (x < 0 || y < 0 || x >= ground.size || y >= ground.size) return null;
      return [x, y];
    }

    let dragging = false;
    let lastX = 0;
    let lastY = 0;

    const onDown = (event: PointerEvent) => {
      dragging = true;
      lastX = event.clientX; lastY = event.clientY;
      canvas!.setPointerCapture(event.pointerId);
    };
    const onUp = (event: PointerEvent) => {
      dragging = false;
      if (canvas!.hasPointerCapture(event.pointerId)) canvas!.releasePointerCapture(event.pointerId);
    };
    const onMove = (event: PointerEvent) => {
      if (dragging) {
        originX -= (event.clientX - lastX) / scale;
        originY -= (event.clientY - lastY) / scale;
        lastX = event.clientX; lastY = event.clientY;
        clampOrigin();
        schedule();
      }
      const cell = cellAt(event);
      setHover(cell === null ? null : describe(ground, cell[0], cell[1]));
    };
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const rect = canvas!.getBoundingClientRect();
      const px = event.clientX - rect.left;
      const py = event.clientY - rect.top;
      // Zoom about the cursor, so the cell under the pointer stays under the pointer.
      const cellX = originX + px / scale;
      const cellY = originY + py / scale;
      const next = Math.max(minScale(), Math.min(MAX_SCALE, scale * Math.exp(-event.deltaY * 0.0016)));
      scale = next;
      originX = cellX - px / scale;
      originY = cellY - py / scale;
      clampOrigin();
      schedule();
    };

    if (goTo) {
      goTo.current = (x: number, y: number) => {
        originX = x - canvas!.clientWidth / (2 * scale);
        originY = y - canvas!.clientHeight / (2 * scale);
        clampOrigin();
        schedule();
      };
    }

    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(canvas);
    canvas.addEventListener("pointerdown", onDown);
    canvas.addEventListener("pointerup", onUp);
    canvas.addEventListener("pointermove", onMove);
    canvas.addEventListener("pointerleave", () => setHover(null));
    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      if (goTo) goTo.current = null;
      observer.disconnect();
      canvas.removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("pointerup", onUp);
      canvas.removeEventListener("pointermove", onMove);
      canvas.removeEventListener("wheel", onWheel);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [ground, onCamera, goTo]);

  return (
    <div className="colony-stage">
      <canvas ref={canvasRef} className="colony-canvas" />
      {hover && <div className="colony-inspector">{hover}</div>}
    </div>
  );
}
