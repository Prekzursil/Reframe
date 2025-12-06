import { useNavigate, useLocation } from "react-router-dom"
import { cn } from "@/lib/utils"
import {
  Video,
  FileVideo,
  Languages,
  Combine
} from "lucide-react"
import { Button } from "./ui/button"

export function Sidebar() {
  const navigate = useNavigate()
  const location = useLocation()

  const menuItems = [
    {
      title: "Shorts Maker",
      icon: Video,
      path: "/",
    },
    {
      title: "Subtitle Generator",
      icon: FileVideo,
      path: "/subtitle-generator",
    },
    {
      title: "Subtitle Translator",
      icon: Languages,
      path: "/subtitle-translator",
    },
    {
      title: "Subtitle Merger",
      icon: Combine,
      path: "/subtitle-merger",
    },
  ]

  return (
    <div className="w-64 border-r bg-card/50 backdrop-blur-sm">
      <div className="flex flex-col gap-2 p-4">
        {menuItems.map((item) => (
          <Button
            key={item.path}
            variant={location.pathname === item.path ? "default" : "ghost"}
            className={cn(
              "justify-start gap-2",
              location.pathname === item.path && "bg-primary text-primary-foreground"
            )}
            onClick={() => navigate(item.path)}
          >
            <item.icon className="h-5 w-5" />
            {item.title}
          </Button>
        ))}
      </div>
    </div>
  )
}