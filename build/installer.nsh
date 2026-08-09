; installer.nsh — Reframe's NSIS customisation (WU-I1, the v1.5 installer revamp).
;
; Wired via electron-builder.yml `nsis.include`. electron-builder emits its defines
; and `!include`s THIS file BEFORE its own templates/nsis/installer.nsi, so anything
; here that needs MUI2 / nsDialogs / LogicLib lives INSIDE a macro body (expanded at
; `!insertmacro` time, i.e. after common.nsh loaded them). Only `Var` declarations and
; `!define`s sit at file scope. The two standard headers below carry their own include
; guards, so requesting them early is safe and makes the page functions compilable.
;
; WHAT THIS ADDS
;   1. A real component page after the directory page (`customPageAfterChangeDir`):
;      Minimum / Default / Full / Custom, with individually selectable feature packs.
;   2. An install-time write of that choice (`customInstall`) as the SEED the app
;      adopts on first launch, so the first run provisions unattended instead of
;      asking the same question again in the in-app ProfilePicker.
;
; WHY A nsDialogs PAGE AND NOT `MUI_PAGE_COMPONENTS`. A real MUI components page is
; driven by NSIS `Section`s, and electron-builder owns the one and only install
; Section (templates/nsis/installer.nsi:94) plus all of the update / uninstall
; bookkeeping inside it. Adding Sections would require replacing the whole script
; (`nsis.script`), forfeiting that machinery — a far larger backward-compatibility
; risk than this feature is worth. `customPageAfterChangeDir` is the supported hook
; (templates/nsis/assistedInstaller.nsh:42) and gives the same user-facing page.
;
; NO MODEL BYTES SHIP HERE. The packs are asset NAMES routed to bootstrap.py's
; `--assets`; the weights still download on demand. Bundling them would blow the NSIS
; ~2 GB format ceiling (see electron-builder.yml's header) and is an owner decision.
;
; DRIFT GUARD. Every id, label and filename below is pinned against
; app/main/installProfiles.ts by app/main/installerSeed.test.ts. Change one side and
; that test fails — the ids are not a second hand-maintained list.

!include nsDialogs.nsh
!include LogicLib.nsh

; --- the contract with app/main/installProfiles.ts (pinned by installerSeed.test.ts) ---
!define REFRAME_PROFILE_IDS "minimum|default|full|custom"
!define REFRAME_BUNDLE_IDS "transcription|ai-director"
!define REFRAME_PROFILE_DEFAULT "default"
!define REFRAME_PROFILE_SEED_FILE ".first-run-profile.json"

; Labels are the app's own words (INSTALL_PROFILES[].label / INSTALL_BUNDLES[].label)
; so the installer and the first-run UI never describe the same thing differently.
!define REFRAME_LABEL_MINIMUM "Minimum"
!define REFRAME_LABEL_DEFAULT "Default"
!define REFRAME_LABEL_FULL "Full"
!define REFRAME_LABEL_CUSTOM "Custom"
!define REFRAME_LABEL_TRANSCRIPTION "Transcription & subtitles"
!define REFRAME_LABEL_AI_DIRECTOR "AI Director"

; A bare `&` is a keyboard-mnemonic prefix in a Win32 control caption, so the display
; copy doubles it. Same trick electron-builder uses for the product name
; (templates/nsis/common.nsh:13) — the canonical label above stays the app's verbatim
; string for the conformance test, and only the rendered caption is escaped.
!searchreplace REFRAME_UI_TRANSCRIPTION "${REFRAME_LABEL_TRANSCRIPTION}" "&" "&&"

; INSTALLER-PASS ONLY. electron-builder runs makensis TWICE over this same script: once for
; the installer, and once for the uninstaller with -DBUILD_UNINSTALLER (see the build log's
; `Command line defined: "BUILD_UNINSTALLER"`, and app-builder-lib templates/nsis/installer.nsi
; :90,:95 which gate the whole install half on `!ifndef BUILD_UNINSTALLER`).
;
; Every one of these vars is used ONLY inside customPageAfterChangeDir / customInstall, and
; app-builder-lib does not insert those macros in the uninstaller pass. Declared unconditionally
; they were therefore declared-and-never-referenced in that pass, and NSIS emitted
;   warning 6001: Variable "ReframeProfile" not referenced or never set, wasting memory!
; which electron-builder compiles with /WX -> "Error: warning treated as error" -> NO INSTALLER
; IS PRODUCED AT ALL. Measured on this box: the packaging run reached
; `dist/win-unpacked` and `.nsis.7z` and then died at the uninstaller compile.
!ifndef BUILD_UNINSTALLER
Var ReframeProfile
Var ReframeBundles
Var ReframeDialog
Var ReframeRadioMinimum
Var ReframeRadioDefault
Var ReframeRadioFull
Var ReframeRadioCustom
Var ReframeCheckTranscription
Var ReframeCheckAiDirector
Var ReframeScratch
!endif

; ---------------------------------------------------------------------------
; The component page
; ---------------------------------------------------------------------------
!macro customPageAfterChangeDir
  Page custom reframeComponentsPageCreate reframeComponentsPageLeave

  ; Grey the feature-pack checkboxes unless Custom is selected — the fixed profiles
  ; are fully determined by their id (installProfiles.resolveInstallChoice ignores
  ; bundles for a non-custom profile), so an editable list there would lie.
  Function reframeSyncBundleEnabled
    ${NSD_GetState} $ReframeRadioCustom $ReframeScratch
    ${If} $ReframeScratch == ${BST_CHECKED}
      EnableWindow $ReframeCheckTranscription 1
      EnableWindow $ReframeCheckAiDirector 1
    ${Else}
      EnableWindow $ReframeCheckTranscription 0
      EnableWindow $ReframeCheckAiDirector 0
    ${EndIf}
  FunctionEnd

  Function reframeOnProfileChanged
    Pop $ReframeScratch ; the notifying control handle (unused)
    Call reframeSyncBundleEnabled
  FunctionEnd

  Function reframeComponentsPageCreate
    ; A silent / updater-driven run still calls the creator; there is no UI to show,
    ; so keep the default and move on. The default is safe by construction: the app
    ; only ADOPTS a seed when the data root has no profile, so an unattended upgrade
    ; can never downgrade an existing choice (installerSeed.ts).
    ${If} ${Silent}
      Abort
    ${EndIf}

    !insertmacro MUI_HEADER_TEXT "Choose what to set up" \
      "Everything not installed now downloads the first time you use it."

    nsDialogs::Create 1018
    Pop $ReframeDialog
    ${If} $ReframeDialog == error
      Abort
    ${EndIf}

    ${NSD_CreateRadioButton} 0 0u 100% 11u "${REFRAME_LABEL_MINIMUM} — app plus subject tracking only"
    Pop $ReframeRadioMinimum
    ${NSD_CreateRadioButton} 0 13u 100% 11u "${REFRAME_LABEL_DEFAULT} — also offline transcription (recommended)"
    Pop $ReframeRadioDefault
    ${NSD_CreateRadioButton} 0 26u 100% 11u "${REFRAME_LABEL_FULL} — everything up front, including the AI Director model"
    Pop $ReframeRadioFull
    ${NSD_CreateRadioButton} 0 39u 100% 11u "${REFRAME_LABEL_CUSTOM} — pick the feature packs below"
    Pop $ReframeRadioCustom

    ${NSD_CreateLabel} 0 56u 100% 10u "Feature packs (Custom only):"
    Pop $ReframeScratch
    ${NSD_CreateCheckbox} 8u 68u 100% 11u "${REFRAME_UI_TRANSCRIPTION}"
    Pop $ReframeCheckTranscription
    ${NSD_CreateCheckbox} 8u 81u 100% 11u "${REFRAME_LABEL_AI_DIRECTOR}"
    Pop $ReframeCheckAiDirector

    ${NSD_CreateLabel} 0 98u 100% 20u \
      "Models are downloaded on demand, not bundled in this installer. You can add or remove packs later in Settings."
    Pop $ReframeScratch

    ; Restore the previous answer when the user steps Back, otherwise preselect the
    ; profile the app itself marks recommended (${REFRAME_PROFILE_DEFAULT}).
    ${If} $ReframeProfile == "minimum"
      ${NSD_Check} $ReframeRadioMinimum
    ${ElseIf} $ReframeProfile == "full"
      ${NSD_Check} $ReframeRadioFull
    ${ElseIf} $ReframeProfile == "custom"
      ${NSD_Check} $ReframeRadioCustom
    ${Else}
      ${NSD_Check} $ReframeRadioDefault
    ${EndIf}

    ${NSD_OnClick} $ReframeRadioMinimum reframeOnProfileChanged
    ${NSD_OnClick} $ReframeRadioDefault reframeOnProfileChanged
    ${NSD_OnClick} $ReframeRadioFull reframeOnProfileChanged
    ${NSD_OnClick} $ReframeRadioCustom reframeOnProfileChanged
    Call reframeSyncBundleEnabled

    nsDialogs::Show
  FunctionEnd

  Function reframeComponentsPageLeave
    StrCpy $ReframeBundles ""

    ${NSD_GetState} $ReframeRadioMinimum $ReframeScratch
    ${If} $ReframeScratch == ${BST_CHECKED}
      StrCpy $ReframeProfile "minimum"
      Return
    ${EndIf}

    ${NSD_GetState} $ReframeRadioFull $ReframeScratch
    ${If} $ReframeScratch == ${BST_CHECKED}
      StrCpy $ReframeProfile "full"
      Return
    ${EndIf}

    ${NSD_GetState} $ReframeRadioCustom $ReframeScratch
    ${If} $ReframeScratch == ${BST_CHECKED}
      StrCpy $ReframeProfile "custom"
      ${NSD_GetState} $ReframeCheckTranscription $ReframeScratch
      ${If} $ReframeScratch == ${BST_CHECKED}
        StrCpy $ReframeBundles '$\"transcription$\"'
      ${EndIf}
      ${NSD_GetState} $ReframeCheckAiDirector $ReframeScratch
      ${If} $ReframeScratch == ${BST_CHECKED}
        ${If} $ReframeBundles == ""
          StrCpy $ReframeBundles '$\"ai-director$\"'
        ${Else}
          StrCpy $ReframeBundles '$ReframeBundles, $\"ai-director$\"'
        ${EndIf}
      ${EndIf}
      Return
    ${EndIf}

    StrCpy $ReframeProfile "${REFRAME_PROFILE_DEFAULT}"
  FunctionEnd
!macroend

; ---------------------------------------------------------------------------
; The seed write
; ---------------------------------------------------------------------------
!macro customInstall
  ; A silent run never showed the page, so nothing set $ReframeProfile.
  ${If} $ReframeProfile == ""
    StrCpy $ReframeProfile "${REFRAME_PROFILE_DEFAULT}"
  ${EndIf}

  ; $INSTDIR is the one path NSIS and the app agree on byte-for-byte (the app reads it
  ; back as dirname(process.execPath) — dataRootIo.exeDir). The app copies it into
  ; whatever data root it resolves at runtime, and ONLY when that root has no profile
  ; yet, so this write can never disturb an existing install (installerSeed.ts).
  ClearErrors
  FileOpen $ReframeScratch "$INSTDIR\${REFRAME_PROFILE_SEED_FILE}" w
  ${IfNot} ${Errors}
    FileWrite $ReframeScratch '{$\r$\n'
    FileWrite $ReframeScratch '  $\"profile$\": $\"$ReframeProfile$\",$\r$\n'
    FileWrite $ReframeScratch '  $\"bundles$\": [$ReframeBundles]$\r$\n'
    FileWrite $ReframeScratch '}$\r$\n'
    FileClose $ReframeScratch
  ${EndIf}
  ; A failed write is deliberately NOT fatal: the app falls back to its in-app
  ; profile picker, which is exactly the pre-WU-I1 behaviour.
  ClearErrors
!macroend
