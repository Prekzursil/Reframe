import { Controller } from "react-hook-form"
import { Control } from "react-hook-form"
import { Label } from "./ui/label"
import { Input } from "./ui/input"
import { Slider } from "./ui/slider"
import { Settings, ChevronDown } from "lucide-react"
import { Button } from "./ui/button"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "./ui/collapsible"
import { SUBTITLE_TEMPLATES } from "@/lib/constants"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./ui/select"
import { Card } from "./ui/card"
import { VideoPreview } from "./VideoPreview"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs"
import { SubtitleTemplateGrid } from "./subtitle-templates/SubtitleTemplateGrid"
import { useToast } from "@/hooks/useToast"

interface SubtitleSettingsProps {
  control: Control<any>
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  disabled?: boolean
  prefix?: string
}

export function SubtitleSettings({ control, isOpen, onOpenChange, disabled, prefix = "" }: SubtitleSettingsProps) {
  const { toast } = useToast()
  const getFieldName = (name: string) => prefix ? `${prefix}.${name}` : name;

  return (
    <Collapsible
      open={isOpen}
      onOpenChange={onOpenChange}
      className="space-y-2"
    >
      <CollapsibleTrigger asChild>
        <Button
          variant="outline"
          className="flex w-full justify-between"
          disabled={disabled}
        >
          <div className="flex items-center">
            <Settings className="mr-2 h-4 w-4" />
            Subtitle Style Settings
          </div>
          <ChevronDown
            className={`h-4 w-4 transition-transform duration-200 ${
              isOpen ? "rotate-180" : ""
            }`}
          />
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent className="space-y-4">
        <Tabs defaultValue="manual" className="w-full">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="templates">Templates</TabsTrigger>
            <TabsTrigger value="manual">Manual Settings</TabsTrigger>
          </TabsList>
          <TabsContent value="templates" className="mt-4">
            <div className="space-y-4">
              <Controller
                name={getFieldName("template")}
                control={control}
                render={({ field }) => (
                  <SubtitleTemplateGrid
                    selectedTemplate={field.value}
                    onTemplateSelect={(value) => {
                      field.onChange(value);
                      const template = SUBTITLE_TEMPLATES.find(t => t.id === value);
                      if (template) {
                        control.setValue(getFieldName("fontSize"), template.style.fontSize);
                        control.setValue(getFieldName("fontColor"), template.style.fontColor);
                        control.setValue(getFieldName("highlightColor"), template.style.highlightColor);
                        control.setValue(getFieldName("backgroundColor"), template.style.backgroundColor);
                        control.setValue(getFieldName("opacity"), template.style.opacity);
                        toast({
                          title: "Template Selected",
                          description: `Template "${template.name}" applied successfully`,
                        });
                      }
                    }}
                  />
                )}
              />
            </div>
          </TabsContent>
          <TabsContent value="manual" className="mt-4">
            <div className="space-y-4">
              <div className="space-y-2">
                <Label>Font Size</Label>
                <Controller
                  name={getFieldName("fontSize")}
                  control={control}
                  render={({ field }) => (
                    <Slider
                      min={12}
                      max={48}
                      step={1}
                      value={[field.value]}
                      onValueChange={([value]) => field.onChange(value)}
                      disabled={disabled}
                    />
                  )}
                />
              </div>
              <div className="space-y-2">
                <Label>Font Color</Label>
                <Controller
                  name={getFieldName("fontColor")}
                  control={control}
                  render={({ field }) => (
                    <Input
                      type="color"
                      className="h-10 px-2 py-1"
                      {...field}
                      disabled={disabled}
                    />
                  )}
                />
              </div>
              <div className="space-y-2">
                <Label>Highlight Color</Label>
                <Controller
                  name={getFieldName("highlightColor")}
                  control={control}
                  render={({ field }) => (
                    <Input
                      type="color"
                      className="h-10 px-2 py-1"
                      {...field}
                      disabled={disabled}
                    />
                  )}
                />
              </div>
              <div className="space-y-2">
                <Label>Background Color</Label>
                <Controller
                  name={getFieldName("backgroundColor")}
                  control={control}
                  render={({ field }) => (
                    <Input
                      type="color"
                      className="h-10 px-2 py-1"
                      {...field}
                      disabled={disabled}
                    />
                  )}
                />
              </div>
              <div className="space-y-2">
                <Label>Background Opacity</Label>
                <Controller
                  name={getFieldName("opacity")}
                  control={control}
                  render={({ field }) => (
                    <Slider
                      min={0}
                      max={100}
                      step={1}
                      value={[field.value]}
                      onValueChange={([value]) => field.onChange(value)}
                      disabled={disabled}
                    />
                  )}
                />
              </div>
            </div>
          </TabsContent>
        </Tabs>
      </CollapsibleContent>
    </Collapsible>
  )
}