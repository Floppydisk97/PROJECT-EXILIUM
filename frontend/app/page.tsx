import Globe from "./globe/Globe";
import WorldStatus from "./WorldStatus";

export default function Home() {
  // Nothing is fetched here: the shell renders at once and both the globe and the status
  // pill fill themselves in. That matters most exactly when the API is slowest.
  return (
    <main>
      <Globe />
      <WorldStatus />
    </main>
  );
}
