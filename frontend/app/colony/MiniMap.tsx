"use client";

import { useEffect, useRef } from "react";
import type { Generated } from "./citygen";
import type { Camera } from "./ColonyView";
import { groundColor } from "./ground";

/** La minimappa: tutta la colonia in un francobollo, col rettangolo di dove stai guardando.
 *
 *  Disegnata dal TERRENO VERO, non da un'immagine a parte: campiona le stesse celle che il
 *  visore dipinge, quindi non puo' mostrare un posto diverso da quello che c'e'. Una
 *  minimappa che mente e' peggio di una minimappa che manca.
 */
export default function MiniMap(
  { ground, camera, goTo }: {
    ground: Generated;
    camera: Camera | null;
    goTo: { current: ((x: number, y: number) => void) | null };
  },
) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const terrainRef = useRef<HTMLCanvasElement | null>(null);

  // Il terreno in piccolo si disegna UNA volta: non cambia, e ridisegnarlo a ogni panoramica
  // significherebbe campionare 590.000 celle sessanta volte al secondo.
  useEffect(() => {
    const side = 160;
    const buffer = document.createElement("canvas");
    buffer.width = side;
    buffer.height = side;
    const context = buffer.getContext("2d")!;
    const image = context.createImageData(side, side);
    const step = ground.size / side;
    for (let y = 0; y < side; y++) {
      for (let x = 0; x < side; x++) {
        const cell = Math.min(ground.size - 1, Math.floor(y * step)) * ground.size
                   + Math.min(ground.size - 1, Math.floor(x * step));
        const [r, g, b] = groundColor(ground, cell);
        const at = (y * side + x) * 4;
        image.data[at] = r; image.data[at + 1] = g; image.data[at + 2] = b; image.data[at + 3] = 255;
      }
    }
    context.putImageData(image, 0, 0);
    terrainRef.current = buffer;
    draw();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ground]);

  useEffect(draw, [camera]);

  function draw() {
    const canvas = canvasRef.current;
    const terrain = terrainRef.current;
    if (!canvas || !terrain) return;
    const context = canvas.getContext("2d")!;
    const side = canvas.width;
    context.clearRect(0, 0, side, side);
    context.drawImage(terrain, 0, 0, side, side);
    if (!camera) return;
    // Il rettangolo di cio' che stai guardando. Se e' tutta la mappa non si disegna: una
    // cornice che coincide col bordo e' rumore.
    const k = side / ground.size;
    const x = camera.x0 * k;
    const y = camera.y0 * k;
    const w = (camera.x1 - camera.x0) * k;
    const h = (camera.y1 - camera.y0) * k;
    if (w >= side - 2 && h >= side - 2) return;
    context.strokeStyle = "rgba(255, 255, 255, 0.85)";
    context.lineWidth = 1.5;
    context.strokeRect(Math.max(0.75, x), Math.max(0.75, y),
                       Math.min(w, side - 1.5), Math.min(h, side - 1.5));
  }

  function jump(event: React.MouseEvent<HTMLCanvasElement>) {
    const canvas = canvasRef.current;
    if (!canvas || !goTo.current) return;
    const rect = canvas.getBoundingClientRect();
    goTo.current(
      ((event.clientX - rect.left) / rect.width) * ground.size,
      ((event.clientY - rect.top) / rect.height) * ground.size,
    );
  }

  return (
    <canvas
      ref={canvasRef}
      className="hud-minimap"
      width={160}
      height={160}
      onClick={jump}
      title="Clicca per spostarti"
    />
  );
}
