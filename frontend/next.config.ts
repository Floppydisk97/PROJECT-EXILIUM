import type { NextConfig } from "next";

const config: NextConfig = {
  // A static export: HTML, JS and the planet itself, with no server behind them. Nothing
  // here runs on a request, so nothing here can be asleep when someone arrives. This is what
  // removed the whole class of cold-start failures from the act of looking at the world --
  // and it is the shape the downloadable game wants anyway, since a client ships its world
  // as data rather than fetching it.
  output: "export",
  poweredByHeader: false,
  images: { unoptimized: true },   // no server means no on-demand image pipeline
};

export default config;
