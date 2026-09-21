"use client";

import { useEffect, useRef } from "react";
import type { Generated } from "./citygen";
import type { Camera } from "./ColonyView";
import { litColor } from "./ground";
import { reliefOf } from "./relief";
import { mapHeight } from "./hexgrid";

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
    // La mappa non e' quadrata: righe distanti 0,866 fanno un rettangolo largo. Il francobollo
    // segue la stessa proporzione, se no la colonia si vedrebbe stirata in verticale e il
    // rettangolo della telecamera cadrebbe nel posto sbagliato.
    const tall = Math.round(side * (mapHeight(ground.size) / ground.size));
    const buffer = document.createElement("canvas");
    buffer.width = side;
    buffer.height = tall;
    const context = buffer.getContext("2d")!;
    const image = context.createImageData(side, tall);
    const step = ground.size / side;
    const stepRow = ground.size / tall;
    // La STESSA luce della tela grande: una minimappa piatta accanto a un terreno in rilievo
    // sembrerebbe la mappa di un altro posto.
    const relief = reliefOf(ground);
    for (let y = 0; y < tall; y++) {
      for (let x = 0; x < side; x++) {
        const cell = Math.min(ground.size - 1, Math.floor(y * stepRow)) * ground.size
                   + Math.min(ground.size - 1, Math.floor(x * step));
        const [r, g, b] = litColor(ground, relief, cell);
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
    const tall = canvas.height;
    context.clearRect(0, 0, side, tall);
    context.drawImage(terrain, 0, 0, side, tall);
    if (!camera) return;
    // Il rettangolo di cio' che stai guardando. Se e' tutta la mappa non si disegna: una
    // cornice che coincide col bordo e' rumore.
    // Una scala sola per i due assi: la telecamera e il francobollo sono gia' nella stessa
    // proporzione, e due scale diverse sposterebbero il rettangolo invece di adattarlo.
    const k = side / ground.size;
    const x = camera.x0 * k;
    const y = camera.y0 * k;
    const w = (camera.x1 - camera.x0) * k;
    const h = (camera.y1 - camera.y0) * k;
    if (w >= side - 2 && h >= tall - 2) return;
    context.strokeStyle = "rgba(255, 255, 255, 0.85)";
    context.lineWidth = 1.5;
    context.strokeRect(Math.max(0.75, x), Math.max(0.75, y),
                       Math.min(w, side - 1.5), Math.min(h, tall - 1.5));
  }

  function jump(event: React.MouseEvent<HTMLCanvasElement>) {
    const canvas = canvasRef.current;
    if (!canvas || !goTo.current) return;
    const rect = canvas.getBoundingClientRect();
    goTo.current(
      ((event.clientX - rect.left) / rect.width) * ground.size,
      ((event.clientY - rect.top) / rect.height) * mapHeight(ground.size),
    );
  }

  return (
    <canvas
      ref={canvasRef}
      className="hud-minimap"
      width={160}
      height={Math.round(160 * (mapHeight(ground.size) / ground.size))}
      onClick={jump}
      title="Clicca per spostarti"
    />
  );
}
