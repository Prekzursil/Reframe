import { Button } from "@/components/ui/button"
import { Loader2 } from "lucide-react"

interface SubtitleFormActionsProps {
  loading: boolean
  videoListLength: number
}

export function SubtitleFormActions({
  loading,
  videoListLength
}: SubtitleFormActionsProps) {
  return (
    <Button
      type="submit"
      className="w-full bg-gradient-to-r from-blue-500 to-blue-600 hover:from-blue-600 hover:to-blue-700"
      disabled={loading || videoListLength === 0}
    >
      {loading ? (
        <>
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          Adding to Queue...
        </>
      ) : (
        "Add to Queue"
      )}
    </Button>
  )
}