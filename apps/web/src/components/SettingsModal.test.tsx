import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SettingsModal } from "./SettingsModal";

describe("SettingsModal", () => {
  it("updates fields and closes via action buttons", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();

    render(<SettingsModal onClose={onClose} />);

    const modelInput = screen.getByLabelText("Preferred model") as HTMLInputElement;
    const languageInput = screen.getByLabelText("Language") as HTMLInputElement;
    const outputPathInput = screen.getByLabelText("Default output path") as HTMLInputElement;
    const notesInput = screen.getByLabelText("Notes") as HTMLTextAreaElement;

    await user.clear(modelInput);
    await user.type(modelInput, "whisper-small");
    await user.clear(languageInput);
    await user.type(languageInput, "en");
    await user.clear(outputPathInput);
    await user.type(outputPathInput, "/tmp/out");
    await user.type(notesInput, "keep this profile");

    expect(modelInput.value).toBe("whisper-small");
    expect(languageInput.value).toBe("en");
    expect(outputPathInput.value).toBe("/tmp/out");
    expect(notesInput.value).toContain("keep this profile");

    await user.click(screen.getByRole("button", { name: "Close settings" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(onClose).toHaveBeenCalledTimes(3);
  });
});

