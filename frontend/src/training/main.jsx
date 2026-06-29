import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@/styles/app.css";
import Training from "./Training";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <Training />
  </StrictMode>
);
