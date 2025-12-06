import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Check } from "lucide-react"
import { cn } from "@/lib/utils"

interface SubtitleTemplateProps {
  id: string
  name: string
  style: {
    fontSize: number
    fontColor: string
    highlightColor: string
    backgroundColor: string
    opacity: number
  }
  selected?: boolean
  onSelect: (id: string) => void
}

export function SubtitleTemplateCard({
  id,
  name,
  style,
  selected,
  onSelect
}: SubtitleTemplateProps) {
  return (
    <Card
      className={cn(
        "relative overflow-hidden hover:shadow-lg transition-all duration-200 cursor-pointer",
        "transform hover:scale-[1.02]",
        selected && "ring-2 ring-primary"
      )}
      onClick={() => onSelect(id)}
    >
      <div className="aspect-[9/16] relative bg-black">
        <div
          className="absolute bottom-0 left-0 right-0 p-4 text-center"
          style={{
            fontSize: `${style.fontSize}px`,
            color: style.fontColor,
            backgroundColor: `${style.backgroundColor}${Math.round(style.opacity * 2.55).toString(16).padStart(2, '0')}`
          }}
        >
          <span
            style={{
              backgroundColor: style.highlightColor,
              padding: "0.2em 0.4em",
              borderRadius: "0.2em"
            }}
          >
            Sample text
          </span>
        </div>
      </div>

      <div className="p-4 bg-card">
        <div className="flex items-center justify-between">
          <span className="font-medium">{name}</span>
          {selected && (
            <Check className="h-5 w-5 text-primary" />
          )}
        </div>
      </div>
    </Card>
  )
}