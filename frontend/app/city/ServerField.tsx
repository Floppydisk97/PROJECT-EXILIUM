"use client";

import { useState } from "react";
import { apiBase, saveApiBase } from "../lib/api";

/** Dove sta il server, e come cambiarlo.
 *
 *  Vive qui e non in tre copie perche' lo mostrano tre schermate: la pagina che non ha un
 *  server, quella che chiede il token, e il menu dentro al gioco. La prima era un vicolo
 *  cieco -- diceva che mancava un server e non dava modo di dirglielo.
 */
export default function ServerField() {
  const [typed, setTyped] = useState(apiBase());
  const [saved, setSaved] = useState(false);

  return (
    <form
      className="server-field"
      onSubmit={(event) => {
        event.preventDefault();
        saveApiBase(typed);
        setSaved(true);
        // Il sito legge l'indirizzo all'avvio, quindi va riletta la pagina: piu' onesto che
        // far finta che il cambio abbia effetto su cio' che e' gia' a schermo.
        window.location.reload();
      }}
    >
      <label htmlFor="server">Server</label>
      <input
        id="server"
        value={typed}
        onChange={(event) => { setTyped(event.target.value); setSaved(false); }}
        placeholder="http://localhost:8000"
        autoComplete="off"
        spellCheck={false}
      />
      <button type="submit" disabled={saved}>Usa questo</button>
    </form>
  );
}
