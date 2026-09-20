"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import ColonyPicker from "../colony/ColonyPicker";

function Chosen() {
  const tile = useSearchParams().get("tile");
  const id = tile === null ? null : Number.parseInt(tile, 10);
  return <ColonyPicker tileId={id === null || Number.isNaN(id) ? null : id} />;
}

export default function ColonyPage() {
  // The query string is only readable on the client in a static export, so the page is a
  // client component and the suspense boundary is what Next asks for in return.
  return (
    <Suspense fallback={<p className="colony-progress">…</p>}>
      <Chosen />
    </Suspense>
  );
}
