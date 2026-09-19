import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import Guardrails from "./pages/Guardrails";
import Incidents from "./pages/Incidents";
import Models from "./pages/Models";
import Overview from "./pages/Overview";
import { useEventSource } from "./state/store";

export default function App() {
  useEventSource();
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Overview />} />
        <Route path="/incidents" element={<Navigate to="/incidents/INC-4412" replace />} />
        <Route path="/incidents/:id" element={<Incidents />} />
        <Route path="/guardrails" element={<Guardrails />} />
        <Route path="/models" element={<Navigate to="/models/fraud-v3-candidate" replace />} />
        <Route path="/models/:name" element={<Models />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
