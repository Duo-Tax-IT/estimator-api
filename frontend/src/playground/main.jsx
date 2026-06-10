import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@/styles/app.css";
import Playground from "./Playground";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <Playground />
  </StrictMode>
);
