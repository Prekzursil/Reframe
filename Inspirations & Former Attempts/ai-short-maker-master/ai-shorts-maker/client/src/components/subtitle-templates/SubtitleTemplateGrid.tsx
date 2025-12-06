import { SubtitleTemplateCard } from "./SubtitleTemplateCard"
import { SUBTITLE_TEMPLATES } from "@/lib/constants"

interface SubtitleTemplateGridProps {
  selectedTemplate: string
  onTemplateSelect: (id: string) => void
}

export function SubtitleTemplateGrid({
  selectedTemplate,
  onTemplateSelect
}: SubtitleTemplateGridProps) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
      {SUBTITLE_TEMPLATES.map((template) => (
        <SubtitleTemplateCard
          key={template.id}
          id={template.id}
          name={template.name}
          style={template.style}
          selected={selectedTemplate === template.id}
          onSelect={onTemplateSelect}
        />
      ))}
    </div>
  )
}