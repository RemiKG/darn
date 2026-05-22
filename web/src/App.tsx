/**
 * Route table:
 *   /                → The shop floor (landing + demo path)
 *   /incident/:id    → Incident view — the receipt ledger
 *   /yours           → Use it on yours (wizard ⇄ Your watch)
 *   /yours/settings  → Power user settings
 *   *                → 404 / empty states
 * The global Chrome (top bar / live strip / footer) wraps every page.
 */

import { Route, Routes } from "react-router-dom";
import Chrome from "./components/Chrome";
import Incident from "./pages/Incident";
import NotFound from "./pages/NotFound";
import SettingsPage from "./pages/SettingsPage";
import ShopFloor from "./pages/ShopFloor";
import Yours from "./pages/Yours";

export default function App() {
  return (
    <Chrome>
      <Routes>
        <Route path="/" element={<ShopFloor />} />
        <Route path="/incident/:id" element={<Incident />} />
        <Route path="/yours" element={<Yours />} />
        <Route path="/yours/settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Chrome>
  );
}
