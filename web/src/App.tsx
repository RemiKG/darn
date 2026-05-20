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
