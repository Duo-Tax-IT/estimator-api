import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@/styles/app.css";
import Learn from "./Learn";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <Learn />
  </StrictMode>
);
