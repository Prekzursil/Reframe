import { Controller } from "react-hook-form"
import { Control } from "react-hook-form"
import { Label } from "./ui/label"
import { Switch } from "./ui/switch"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { LANGUAGES } from "@/lib/constants"
import { SubtitleSettings } from "./SubtitleSettings"
import { WhisperModelSelect } from "./WhisperModelSelect"

interface SubtitleGenerationSettingsProps {
  control: Control<any>
  watchTranslate: boolean
  isStyleOpen: boolean
  onStyleOpenChange: (open: boolean) => void
  disabled?: boolean
  prefix?: string
}

export function SubtitleGenerationSettings({
  control,
  watchTranslate,
  isStyleOpen,
  onStyleOpenChange,
  disabled,
  prefix = ""
}: SubtitleGenerationSettingsProps) {
  const getFieldName = (name: string) => prefix ? `${prefix}.${name}` : name;

  return (
    <div className="space-y-6">
      <div className="space-y-4">
        <div className="space-y-2">
          <Label>Original Video Language</Label>
          <Controller
            name={getFieldName("originalLanguage")}
            control={control}
            render={({ field }) => (
              <Select onValueChange={field.onChange} value={field.value} disabled={disabled}>
                <SelectTrigger>
                  <SelectValue placeholder="Select language" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="auto">Auto Detect</SelectItem>
                  {LANGUAGES.map((lang) => (
                    <SelectItem key={lang.value} value={lang.value}>
                      {lang.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          />
        </div>

        <Controller
          name={getFieldName("subtitleWhisperModel")}
          control={control}
          render={({ field }) => (
            <WhisperModelSelect
              value={field.value}
              onValueChange={field.onChange}
              label="Subtitle Whisper Model"
              disabled={disabled}
            />
          )}
        />

        <div className="flex items-center space-x-2">
          <Controller
            name={getFieldName("burnSubtitles")}
            control={control}
            render={({ field }) => (
              <Switch
                id={getFieldName("burnSubtitles")}
                checked={field.value}
                onCheckedChange={field.onChange}
                disabled={disabled}
              />
            )}
          />
          <Label htmlFor={getFieldName("burnSubtitles")}>Burn Subtitles into Video</Label>
        </div>

        <div className="flex items-center space-x-2">
          <Controller
            name={getFieldName("saveSrtSeparately")}
            control={control}
            render={({ field }) => (
              <Switch
                id={getFieldName("saveSrtSeparately")}
                checked={field.value}
                onCheckedChange={field.onChange}
                disabled={disabled}
              />
            )}
          />
          <Label htmlFor={getFieldName("saveSrtSeparately")}>Save Subtitles Separately (SRT)</Label>
        </div>

        <div className="flex items-center space-x-2">
          <Controller
            name={getFieldName("translateSubtitles")}
            control={control}
            render={({ field }) => (
              <Switch
                id={getFieldName("translateSubtitles")}
                checked={field.value}
                onCheckedChange={field.onChange}
                disabled={disabled}
              />
            )}
          />
          <Label htmlFor={getFieldName("translateSubtitles")}>Translate Subtitles</Label>
        </div>

        <div className={`space-y-4 pl-6 border-l-2 transition-opacity duration-200 ${!watchTranslate ? 'opacity-50 pointer-events-none' : ''}`}>
          <div className="space-y-2">
            <Label>Target Language</Label>
            <Controller
              name={getFieldName("targetLanguage")}
              control={control}
              render={({ field }) => (
                <Select onValueChange={field.onChange} value={field.value} disabled={!watchTranslate || disabled}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select target language" />
                  </SelectTrigger>
                  <SelectContent>
                    {LANGUAGES.map((lang) => (
                      <SelectItem key={lang.value} value={lang.value}>
                        {lang.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
          </div>

          <div className="flex items-center space-x-2">
            <Controller
              name={getFieldName("translateTitle")}
              control={control}
              render={({ field }) => (
                <Switch
                  id={getFieldName("translateTitle")}
                  checked={field.value}
                  onCheckedChange={field.onChange}
                  disabled={!watchTranslate || disabled}
                />
              )}
            />
            <Label htmlFor={getFieldName("translateTitle")}>Also Translate Title</Label>
          </div>

          <div className="flex items-center space-x-2">
            <Controller
              name={getFieldName("saveOriginalSrt")}
              control={control}
              render={({ field }) => (
                <Switch
                  id={getFieldName("saveOriginalSrt")}
                  checked={field.value}
                  onCheckedChange={field.onChange}
                  disabled={!watchTranslate || disabled}
                />
              )}
            />
            <Label htmlFor={getFieldName("saveOriginalSrt")}>Save Original SRT</Label>
          </div>

          <div className="flex items-center space-x-2">
            <Controller
              name={getFieldName("saveTranslatedSrt")}
              control={control}
              render={({ field }) => (
                <Switch
                  id={getFieldName("saveTranslatedSrt")}
                  checked={field.value}
                  onCheckedChange={field.onChange}
                  disabled={!watchTranslate || disabled}
                />
              )}
            />
            <Label htmlFor={getFieldName("saveTranslatedSrt")}>Save Translated SRT</Label>
          </div>
        </div>

        <SubtitleSettings
          control={control}
          isOpen={isStyleOpen}
          onOpenChange={onStyleOpenChange}
          disabled={disabled}
          prefix={prefix ? `${prefix}.subtitleStyle` : "subtitleStyle"}
        />
      </div>
    </div>
  )
}