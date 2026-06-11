import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@/styles/app.css";
import Suggestions from "./Suggestions";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <Suggestions />
  </StrictMode>
);
