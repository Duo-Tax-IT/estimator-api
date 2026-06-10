import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@/styles/app.css";
import Estimator from "./Estimator";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <Estimator />
  </StrictMode>
);
