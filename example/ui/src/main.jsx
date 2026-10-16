import { createRoot } from "react-dom/client";
import { AppProvider } from "@slowboard/app-react";
import { Hint } from "@slowboard/ui";

import App from "./App.jsx";

createRoot(document.getElementById("root")).render(
  <AppProvider fallback={<Hint>Connecting to the hub…</Hint>}>
    <App />
  </AppProvider>,
);
