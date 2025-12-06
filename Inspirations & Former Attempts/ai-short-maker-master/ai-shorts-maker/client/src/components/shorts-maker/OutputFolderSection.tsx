import { Label } from "@/components/ui/label"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { FolderOpen } from "lucide-react"
import { useState } from "react"

interface OutputFolderSectionProps {
  value: string
  onChange: (value: string) => void
}

export function OutputFolderSection({ value, onChange }: OutputFolderSectionProps) {
  const [loading, setLoading] = useState(false)

  const handleBrowseFolder = async () => {
    if (loading) return
    
    setLoading(true)
    try {
      // @ts-ignore - window.showDirectoryPicker is not in the TypeScript types yet
      const directoryHandle = await window.showDirectoryPicker()
      onChange(directoryHandle.name)
    } catch (error) {
      // Only log if it's not an abort error
      if (!(error instanceof Error) || !error.message.includes('abort')) {
        console.error("Error selecting directory:", error)
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-2">
      <Label>Output Folder</Label>
      <div className="flex gap-2">
        <Input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Select output folder..."
        />
        <Button
          type="button"
          variant="secondary"
          onClick={handleBrowseFolder}
          disabled={loading}
          className="shrink-0 hover:scale-105 transition-transform"
        >
          <FolderOpen className="h-4 w-4 mr-2" />
          {loading ? "Selecting..." : "Browse"}
        </Button>
      </div>
    </div>
  )
}