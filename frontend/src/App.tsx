import { Route, Routes } from "react-router-dom"
import { AppShell } from "./components/layout/AppShell"
import { BriefingPage } from "./features/briefing/BriefingPage"
import { PortfolioPage } from "./features/portfolio/PortfolioPage"
import { ResearchPage } from "./features/research/ResearchPage"

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<BriefingPage />} />
        <Route path="portfolio" element={<PortfolioPage />} />
        <Route path="research" element={<ResearchPage />} />
        <Route path="research/:symbol" element={<ResearchPage />} />
      </Route>
    </Routes>
  )
}
