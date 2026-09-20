import Globe from "./globe/Globe";
import WorldStatus from "./WorldStatus";

export default function Home() {
  // Nothing is fetched here: the shell renders at once and both the globe and the status
  // pill fill themselves in. That matters most exactly when the API is slowest.
  return (
    <main>
      <Globe />
      <WorldStatus />
      {/* La sola pagina che parla col server autoritativo. Sta qui perche' una schermata che
          nessuno trova vale quanto una che non esiste. */}
      <a className="home-city" href="/citta">La tua colonia →</a>
    </main>
  );
}
