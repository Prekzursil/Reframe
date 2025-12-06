import { Bell, LogOut } from "lucide-react"
import { Button } from "./ui/button"
import { ThemeToggle } from "./ui/theme-toggle"
import { useAuth } from "@/contexts/AuthContext"
import { useLanguage } from "@/contexts/LanguageContext"
import { useNavigate } from "react-router-dom"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import ReactCountryFlag from "react-country-flag"
import { translations } from "@/lib/translations"

export function Header() {
  const { logout } = useAuth()
  const { language, setLanguage } = useLanguage()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate("/login")
  }

  const handleHomeClick = () => {
    navigate("/")
  }

  return (
    <header className="fixed top-0 z-50 w-full border-b bg-background/80 backdrop-blur-sm">
      <div className="flex h-16 items-center justify-between px-6">
        <div className="text-xl font-bold cursor-pointer" onClick={handleHomeClick}>
          {translations[language].common.home}
        </div>
        <div className="flex items-center gap-4">
          <Select value={language} onValueChange={(value: "en" | "ro") => setLanguage(value)}>
            <SelectTrigger className="w-[140px]">
              <SelectValue>
                <div className="flex items-center gap-2">
                  <ReactCountryFlag
                    countryCode={language === "en" ? "GB" : "RO"}
                    svg
                    style={{
                      width: '1.2em',
                      height: '1.2em',
                    }}
                  />
                  {language === "en" ? "English" : "Română"}
                </div>
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="en">
                <div className="flex items-center gap-2">
                  <ReactCountryFlag countryCode="GB" svg />
                  English
                </div>
              </SelectItem>
              <SelectItem value="ro">
                <div className="flex items-center gap-2">
                  <ReactCountryFlag countryCode="RO" svg />
                  Română
                </div>
              </SelectItem>
            </SelectContent>
          </Select>
          <ThemeToggle />
          <Button variant="ghost" size="icon" onClick={handleLogout}>
            <LogOut className="h-5 w-5" />
          </Button>
        </div>
      </div>
    </header>
  )
}