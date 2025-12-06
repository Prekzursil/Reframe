import { useState } from "react";
import { Button, Input, TextArea } from "./ui";

interface Props {
  onClose: () => void;
}

export function SettingsModal({ onClose }: Props) {
  const [model, setModel] = useState("whisper-large-v3");
  const [language, setLanguage] = useState("auto");
  const [outputPath, setOutputPath] = useState("/media/output");
  const [notes, setNotes] = useState("");

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <div className="modal">
        <header className="modal-head">
          <div>
            <p className="eyebrow">Workspace</p>
            <h2>Default settings</h2>
          </div>
          <Button variant="ghost" onClick={onClose} aria-label="Close settings">
            Close
          </Button>
        </header>
        <div className="modal-body">
          <label className="field">
            <span>Preferred model</span>
            <Input value={model} onChange={(e) => setModel(e.target.value)} />
          </label>
          <label className="field">
            <span>Language</span>
            <Input value={language} onChange={(e) => setLanguage(e.target.value)} placeholder="auto" />
          </label>
          <label className="field">
            <span>Default output path</span>
            <Input value={outputPath} onChange={(e) => setOutputPath(e.target.value)} />
          </label>
          <label className="field">
            <span>Notes</span>
            <TextArea rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </label>
        </div>
        <footer className="modal-footer">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" onClick={onClose}>
            Save
          </Button>
        </footer>
      </div>
    </div>
  );
}
