// La tavolozza di questo visore e quella spedita col pianeta sono la stessa.
//
// Le tinte vivevano SOLO qui. Quando e' arrivato un secondo visore -- il client Godot -- sono
// state trascritte una seconda volta, ed e' bastato un pomeriggio perche' diventassero due
// elenchi che dovevano coincidere e che nessuno confrontava. Di quelle coppie questo progetto
// ne ha gia' pagate sei.
//
// Adesso la tavolozza viaggia DENTRO al file del pianeta, scritta da `worldgen.BIOME_COLORS`,
// e chi disegna la legge invece di ricordarsela -- il client Godot fa cosi'. Questo visore no:
// ha la sua tabella perche' le serve anche per le ETICHETTE, che nel file non ci sono. Quindi
// resta una copia, ma non piu' una copia non controllata: se le due divergono, cade qui.
import { gunzipSync } from "node:zlib";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { BIOMES, OCEAN_DEEP, RIVER_MAJOR, RIVER_MINOR, SHELF_SHALLOW } from "./biomes";

function shippedPlanet(): Record<string, unknown> {
  const folder = "public/map";
  const manifest = JSON.parse(readFileSync(`${folder}/manifest.json`, "utf8"));
  return JSON.parse(gunzipSync(readFileSync(`${folder}/${manifest.file}`)).toString("utf8"));
}

describe("la tavolozza", () => {
  const planet = shippedPlanet();
  const names = planet.biome_names as string[];
  const colors = planet.biome_colors as number[];
  const palette = planet.palette as Record<string, number>;

  it("da' la stessa tinta a ogni bioma che il pianeta conosce", () => {
    expect(names.length).toBe(colors.length);
    for (let i = 0; i < names.length; i++) {
      const here = BIOMES[names[i]];
      expect(here, `bioma senza tinta in biomes.ts: ${names[i]}`).toBeDefined();
      expect(here.color, `tinta diversa per ${names[i]}`).toBe(colors[i]);
    }
  });

  it("non conosce biomi che il pianeta non ha", () => {
    // Una tinta di troppo non rompe niente oggi e diventa una bugia il giorno in cui
    // qualcuno la cerca: se un bioma sparisce dal generatore, deve sparire anche da qui.
    expect(Object.keys(BIOMES).sort()).toEqual([...names].sort());
  });

  it("concorda anche sull'acqua e sui fiumi", () => {
    expect(palette.shelf_shallow).toBe(SHELF_SHALLOW);
    expect(palette.ocean_deep).toBe(OCEAN_DEEP);
    expect(palette.river_minor).toBe(RIVER_MINOR);
    expect(palette.river_major).toBe(RIVER_MAJOR);
  });
});
