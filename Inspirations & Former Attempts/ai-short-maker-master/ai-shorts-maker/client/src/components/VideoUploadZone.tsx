import { useState } from "react"
import { Upload } from "lucide-react"
import { Label } from "./ui/label"
import { cn } from "@/lib/utils"

interface VideoUploadZoneProps {
  onFileChange: (event: React.ChangeEvent<HTMLInputElement>) => void
  accept?: string
  multiple?: boolean
  id: string
  label: string
}

export function VideoUploadZone({
  onFileChange,
  accept = "video/*",
  multiple = true,
  id,
  label
}: VideoUploadZoneProps) {
  const [isDragging, setIsDragging] = useState(false)

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    const files = e.dataTransfer.files
    const event = {
      target: {
        files
      }
    } as React.ChangeEvent<HTMLInputElement>
    onFileChange(event)
  }

  return (
    <div
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className={cn(
        "border-2 border-dashed rounded-lg p-8 text-center transition-all duration-200",
        isDragging ? "border-primary bg-primary/5 scale-105" : "hover:bg-accent/50",
      )}
    >
      <input
        type="file"
        multiple={multiple}
        accept={accept}
        className="hidden"
        onChange={onFileChange}
        id={id}
      />
      <Label htmlFor={id} className="cursor-pointer block">
        <Upload className="h-12 w-12 mx-auto mb-4 animate-bounce text-primary" />
        <span className="text-sm text-muted-foreground block">
          {label}
        </span>
      </Label>
    </div>
  )
}