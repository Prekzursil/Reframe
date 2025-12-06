import { BrowserRouter as Router, Routes, Route } from "react-router-dom"
import { ThemeProvider } from "./components/ui/theme-provider"
import { Toaster } from "./components/ui/toaster"
import { AuthProvider } from "./contexts/AuthContext"
import { LanguageProvider } from "./contexts/LanguageContext"
import { JobQueueProvider } from "./contexts/JobQueueContext"
import { VideoListProvider } from "./contexts/VideoListContext"
import { Login } from "./pages/Login"
import { Register } from "./pages/Register"
import { Layout } from "./components/Layout"
import { ProtectedRoute } from "./components/ProtectedRoute"
import { ShortsMaker } from "./pages/ShortsMaker"
import { SubtitleGenerator } from "./pages/SubtitleGenerator"
import { SubtitleTranslator } from "./pages/SubtitleTranslator"
import { SubtitleMerger } from "./pages/SubtitleMerger"

function App() {
  return (
    <AuthProvider>
      <LanguageProvider>
        <JobQueueProvider>
          <VideoListProvider>
            <ThemeProvider defaultTheme="light" storageKey="ui-theme">
              <Router>
                <Routes>
                  <Route path="/login" element={<Login />} />
                  <Route path="/register" element={<Register />} />
                  <Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
                    <Route index element={<ShortsMaker />} />
                    <Route path="subtitle-generator" element={<SubtitleGenerator />} />
                    <Route path="subtitle-translator" element={<SubtitleTranslator />} />
                    <Route path="subtitle-merger" element={<SubtitleMerger />} />
                  </Route>
                </Routes>
                <Toaster />
              </Router>
            </ThemeProvider>
          </VideoListProvider>
        </JobQueueProvider>
      </LanguageProvider>
    </AuthProvider>
  )
}

export default App