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
; FileFunc gives the uninstall page ${un.GetSize} (the reclaimable-size probe) and
; ${un.GetParameters}/${un.GetOptions} (the --updated veto). All three are STOCK NSIS,
; not app-builder-lib, so build/check-installer-nsh.ps1's harness can resolve them.
; The header carries its own include guard, so re-requesting it here is safe.
!include FileFunc.nsh

; --- the contract with app/main/installProfiles.ts (pinned by installerSeed.test.ts) ---
!define REFRAME_PROFILE_IDS "minimum|default|full|custom"
!define REFRAME_BUNDLE_IDS "transcription|ai-director"
!define REFRAME_PROFILE_DEFAULT "default"
!define REFRAME_PROFILE_SEED_FILE ".first-run-profile.json"

; --- the UNINSTALL contract with app/main/installerSeed.ts (pinned by installerSeed.test.ts) ---
; Three path literals the app also owns in TypeScript. Pinned in BOTH directions by
; installerSeed.test.ts so the uninstaller can never become a second, drifting copy of
; the data-root path policy. See the WU-L7 block in app/main/installerSeed.ts.
!define REFRAME_DATA_ROOT_DIRNAME "media-studio"
!define REFRAME_USER_DATA_DIRNAME "Reframe"
!define REFRAME_DATA_DIR_MARKER "data-dir.txt"
!define REFRAME_UNINSTALL_MODEL_DIRS "models|envs|tools"

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

; ===========================================================================
; WU-L7 — THE UNINSTALL KEEP-VS-REMOVE PAGE
; ===========================================================================
;
; WHAT WAS WRONG. Uninstalling stranded EVERYTHING. `deleteAppDataOnUninstall` is false
; (and must stay false — see electron-builder.yml), there was no `customUnInstall`, and
; the data root is not `%APPDATA%/<app>` anyway, so nothing the uninstaller does has ever
; gone near it. A user removing Reframe was silently left with the whole data root on
; disk — the library, the projects, and every downloaded model, easily several GB, at a
; path they were never shown at uninstall time.
;
; WHAT THIS ADDS. One page, first in the uninstaller, offering two independent opt-ins
; with the reclaimable size measured on the spot. BOTH DEFAULT TO OFF. Nothing is deleted
; unless the user ticks a box on a visible page.
;
; THE UNINSTALLER-PASS VAR TRAP (the same one the installer-pass block above records, in
; mirror image). electron-builder runs makensis TWICE over this script. The uninstall
; half of app-builder-lib's installer.nsi is compiled ONLY in the second pass
; (templates/nsis/installer.nsi:130-132), so `customUnWelcomePage` and `customUnInstall`
; are inserted ONLY there. A Var for them declared at FILE scope would be
; declared-and-never-referenced in the installer pass -> `warning 6001` -> /WX ->
; "Error: warning treated as error" -> NO INSTALLER IS PRODUCED AT ALL. So every var
; below is declared with `Var /GLOBAL` from INSIDE a macro, which means it exists in
; exactly the pass that inserts that macro — and in neither of
; build/check-installer-nsh.ps1's two passes, which insert no custom macro at all.
; `Var /GLOBAL` is legal both at file scope and inside a Section; app-builder-lib does
; the same at templates/nsis/uninstaller.nsh:216.
;
; WHAT THE UNINSTALLER CANNOT SEE. `MEDIA_STUDIO_CONFIG_DIR` is a runtime env override,
; so a data root chosen that way is invisible here and is simply never offered for
; removal. That is the safe direction: data we cannot positively identify is kept.

!macro reframeUnVars
  ; Idempotent: both un-macros request the vars, and whichever is expanded first
  ; declares them. A second declaration of the same name is a compile error.
  !ifndef REFRAME_UN_VARS_DECLARED
    !define REFRAME_UN_VARS_DECLARED
    Var /GLOBAL ReframeUnRemoveModels   ; "1" only after an explicit tick
    Var /GLOBAL ReframeUnRemoveUserData ; "1" only after an explicit tick
    Var /GLOBAL ReframeUnDataRoot       ; the resolved data root, or ""
    Var /GLOBAL ReframeUnDataRootOk     ; "1" only when that root is safe to delete
    Var /GLOBAL ReframeUnDialog
    Var /GLOBAL ReframeUnCheckModels
    Var /GLOBAL ReframeUnCheckUserData
    Var /GLOBAL ReframeUnScratch        ; in-param / throwaway control handle
    Var /GLOBAL ReframeUnScratch2       ; out-param
    Var /GLOBAL ReframeUnModelsKb
    Var /GLOBAL ReframeUnTotalKb
    Var /GLOBAL ReframeUnModelsSize     ; "3.4 GB" — what the models tick frees
    Var /GLOBAL ReframeUnUserSize       ; "4.1 GB" — what the everything tick frees
  !endif
!macroend

; ---------------------------------------------------------------------------
; The page. app-builder-lib inserts customUnWelcomePage IN PLACE OF the stock
; MUI_UNPAGE_WELCOME (templates/nsis/assistedInstaller.nsh:66-71), so this is the first
; thing the user sees when they uninstall — before any file is touched.
; ---------------------------------------------------------------------------
!macro customUnWelcomePage
  !insertmacro reframeUnVars

  UninstPage custom un.reframeUnDataPageCreate un.reframeUnDataPageLeave

  ; Strip trailing CR/LF/space/tab and one trailing backslash. In/out: the stack.
  Function un.reframeUnTrimTail
    Exch $R0
    Push $R1
    ${Do}
      StrLen $R1 $R0
      ${If} $R1 == 0
        ${Break}
      ${EndIf}
      StrCpy $R1 $R0 1 -1
      ${If} $R1 == "$\r"
      ${OrIf} $R1 == "$\n"
      ${OrIf} $R1 == " "
      ${OrIf} $R1 == "$\t"
      ${OrIf} $R1 == "\"
        StrCpy $R0 $R0 -1
      ${Else}
        ${Break}
      ${EndIf}
    ${Loop}
    Pop $R1
    Exch $R0
  FunctionEnd

  ; Read the first line of a marker file. In: path. Out: trimmed value, or "" when the
  ; file is absent, unreadable or empty. Never fails the uninstall.
  Function un.reframeUnReadMarker
    Exch $R0
    Push $R1
    ClearErrors
    FileOpen $R1 "$R0" r
    ${If} ${Errors}
      StrCpy $R0 ""
    ${Else}
      ClearErrors
      FileRead $R1 $R0
      FileClose $R1
      ${If} ${Errors}
        StrCpy $R0 "" ; empty file: FileRead left $R0 holding the PATH, so clear it
      ${EndIf}
    ${EndIf}
    ClearErrors
    Push $R0
    Call un.reframeUnTrimTail
    Pop $R0
    Pop $R1
    Exch $R0
  FunctionEnd

  ; "1" when the string contains "..". Any hit disqualifies the path: a poisoned
  ; data-dir.txt could otherwise walk `…\media-studio\..\..` up to %APPDATA% and hand a
  ; recursive delete the wrong tree. Deliberately stricter than a real path parse — a
  ; folder legitimately containing ".." just means we do not offer to remove it.
  Function un.reframeUnHasDotDot
    Exch $R0
    Push $R1
    Push $R2
    Push $R3
    StrCpy $R3 "0"
    StrCpy $R2 0
    ${Do}
      StrCpy $R1 $R0 2 $R2
      ${If} $R1 == ""
        ${Break}
      ${EndIf}
      ${If} $R1 == ".."
        StrCpy $R3 "1"
        ${Break}
      ${EndIf}
      IntOp $R2 $R2 + 1
    ${Loop}
    StrCpy $R0 $R3
    Pop $R3
    Pop $R2
    Pop $R1
    Exch $R0
  FunctionEnd

  ; "1" when the path is a plausible, existing, NON-system directory we may recursively
  ; delete. Mirrors app/main/dataRoot.ts isSafeLocalDataRoot (no UNC, no `..`) and adds
  ; the shell-folder blacklist, because the input can come from a file on disk.
  Function un.reframeUnSafeRoot
    Exch $R0
    Push $R1
    Push $R2
    StrCpy $R1 "1"

    StrLen $R2 $R0
    ${If} $R2 < 4          ; "", "C:", "C:\" — never a data root
      StrCpy $R1 "0"
    ${EndIf}

    StrCpy $R2 $R0 2
    ${If} $R2 == "\\"      ; UNC: refuse to walk the network
      StrCpy $R1 "0"
    ${EndIf}

    ${If} $R0 == "$INSTDIR"
    ${OrIf} $R0 == "$APPDATA"
    ${OrIf} $R0 == "$LOCALAPPDATA"
    ${OrIf} $R0 == "$PROFILE"
    ${OrIf} $R0 == "$DESKTOP"
    ${OrIf} $R0 == "$DOCUMENTS"
    ${OrIf} $R0 == "$WINDIR"
    ${OrIf} $R0 == "$PROGRAMFILES"
    ${OrIf} $R0 == "$PROGRAMFILES64"
    ${OrIf} $R0 == "$TEMP"
      StrCpy $R1 "0"
    ${EndIf}

    Push $R0
    Call un.reframeUnHasDotDot
    Pop $R2
    ${If} $R2 == "1"
      StrCpy $R1 "0"
    ${EndIf}

    ${IfNot} ${FileExists} "$R0\*.*"
      StrCpy $R1 "0"       ; nothing there: nothing to offer
    ${EndIf}

    StrCpy $R0 $R1
    Pop $R2
    Pop $R1
    Exch $R0
  FunctionEnd

  ; Replay app/main/dataRootIo.ts resolveDataDirMarker + main.ts resolveDataRoot, using
  ; only paths NSIS can name: the STABLE per-user marker first, then the LEGACY
  ; <exeDir>/data-dir.txt ($INSTDIR IS exeDir), then the default appData home.
  Function un.reframeUnResolveDataRoot
    StrCpy $ReframeUnDataRootOk "0"

    Push "$APPDATA\${REFRAME_USER_DATA_DIRNAME}\${REFRAME_DATA_DIR_MARKER}"
    Call un.reframeUnReadMarker
    Pop $ReframeUnDataRoot

    ${If} $ReframeUnDataRoot == ""
      Push "$INSTDIR\${REFRAME_DATA_DIR_MARKER}"
      Call un.reframeUnReadMarker
      Pop $ReframeUnDataRoot
    ${EndIf}

    ${If} $ReframeUnDataRoot == ""
      StrCpy $ReframeUnDataRoot "$APPDATA\${REFRAME_DATA_ROOT_DIRNAME}"
    ${EndIf}

    Push $ReframeUnDataRoot
    Call un.reframeUnSafeRoot
    Pop $ReframeUnDataRootOk
  FunctionEnd

  ; In: $ReframeUnScratch (a directory). Out: $ReframeUnScratch2 (size in KB, 0 when
  ; absent). ${un.GetSize} walks the tree, so this costs real IO — it runs once per
  ; measured directory on page create, never on a silent run.
  Function un.reframeUnDirKb
    StrCpy $ReframeUnScratch2 0
    ${If} ${FileExists} "$ReframeUnScratch\*.*"
      ClearErrors
      ${un.GetSize} "$ReframeUnScratch" "/S=0K" $ReframeUnScratch2 $0 $1
      ${If} ${Errors}
        StrCpy $ReframeUnScratch2 0
      ${EndIf}
      ClearErrors
    ${EndIf}
  FunctionEnd

  ; In: KB on the stack. Out: "4.1 GB" / "820 MB" / "under 1 MB". Integer maths only.
  Function un.reframeUnFormatKb
    Exch $R0
    Push $R1
    Push $R2
    ${If} $R0 >= 1048576
      IntOp $R1 $R0 / 1048576
      IntOp $R2 $R0 % 1048576
      IntOp $R2 $R2 * 10
      IntOp $R2 $R2 / 1048576
      StrCpy $R0 "$R1.$R2 GB"
    ${ElseIf} $R0 >= 1024
      IntOp $R1 $R0 / 1024
      StrCpy $R0 "$R1 MB"
    ${Else}
      StrCpy $R0 "under 1 MB"
    ${EndIf}
    Pop $R2
    Pop $R1
    Exch $R0
  FunctionEnd

  ; Measure both offers. "Models" is the re-downloadable set; "everything" is the whole
  ; data root PLUS the app's own %APPDATA% folder, which is exactly what the second tick
  ; deletes — so the number on each line is the number that line frees.
  Function un.reframeUnMeasure
    StrCpy $ReframeUnModelsKb 0
    StrCpy $ReframeUnTotalKb 0

    StrCpy $ReframeUnScratch "$ReframeUnDataRoot\models"
    Call un.reframeUnDirKb
    IntOp $ReframeUnModelsKb $ReframeUnModelsKb + $ReframeUnScratch2
    StrCpy $ReframeUnScratch "$ReframeUnDataRoot\envs"
    Call un.reframeUnDirKb
    IntOp $ReframeUnModelsKb $ReframeUnModelsKb + $ReframeUnScratch2
    StrCpy $ReframeUnScratch "$ReframeUnDataRoot\tools"
    Call un.reframeUnDirKb
    IntOp $ReframeUnModelsKb $ReframeUnModelsKb + $ReframeUnScratch2

    StrCpy $ReframeUnScratch "$ReframeUnDataRoot"
    Call un.reframeUnDirKb
    IntOp $ReframeUnTotalKb $ReframeUnTotalKb + $ReframeUnScratch2
    StrCpy $ReframeUnScratch "$APPDATA\${REFRAME_USER_DATA_DIRNAME}"
    Call un.reframeUnDirKb
    IntOp $ReframeUnTotalKb $ReframeUnTotalKb + $ReframeUnScratch2

    Push $ReframeUnModelsKb
    Call un.reframeUnFormatKb
    Pop $ReframeUnModelsSize
    Push $ReframeUnTotalKb
    Call un.reframeUnFormatKb
    Pop $ReframeUnUserSize
  FunctionEnd

  ; Ticking "everything" necessarily takes the models with it (it removes the whole data
  ; root), so show that: check the models box and grey it, the same idiom the install
  ; page uses for the feature packs. The visible state is always exactly what will happen.
  Function un.reframeUnSyncBoxes
    ${NSD_GetState} $ReframeUnCheckUserData $ReframeUnScratch
    ${If} $ReframeUnScratch == ${BST_CHECKED}
      ${NSD_Check} $ReframeUnCheckModels
      EnableWindow $ReframeUnCheckModels 0
    ${Else}
      EnableWindow $ReframeUnCheckModels 1
    ${EndIf}
  FunctionEnd

  Function un.reframeUnOnUserDataClick
    Pop $ReframeUnScratch ; the notifying control handle (unused)
    Call un.reframeUnSyncBoxes
  FunctionEnd

  Function un.reframeUnDataPageCreate
    ; KEEP is the default, and it is re-asserted here rather than assumed, so the flags
    ; are "0" even if the page is later reached twice (Back) or aborted below.
    StrCpy $ReframeUnRemoveModels "0"
    StrCpy $ReframeUnRemoveUserData "0"

    ; A silent run — which is EVERY in-place auto-update, because the installer launches
    ; the old uninstaller with /S (app-builder-lib templates/nsis/include/installUtil.nsh
    ; :209-215) — has no UI to ask in. Keep everything and move on.
    ${If} ${Silent}
      Abort
    ${EndIf}

    Call un.reframeUnResolveDataRoot

    !insertmacro MUI_HEADER_TEXT "Keep your videos and models?" \
      "Uninstalling removes the app. Your data folder is left alone unless you say otherwise."

    nsDialogs::Create 1018
    Pop $ReframeUnDialog
    ${If} $ReframeUnDialog == error
      Abort
    ${EndIf}

    ${NSD_CreateLabel} 0 0u 100% 24u \
      "Reframe keeps your library, projects, settings and every downloaded model in a data folder OUTSIDE the program folder. Uninstalling does not touch it, so reinstalling picks up where you left off and nothing is downloaded twice."
    Pop $ReframeUnScratch

    ${If} $ReframeUnDataRootOk == "1"
      Call un.reframeUnMeasure

      ${NSD_CreateLabel} 0 28u 100% 18u "Data folder: $ReframeUnDataRoot"
      Pop $ReframeUnScratch

      ${NSD_CreateCheckbox} 0 50u 100% 11u \
        "Also delete downloaded models, runtimes and tools (frees $ReframeUnModelsSize)"
      Pop $ReframeUnCheckModels
      ${NSD_CreateLabel} 12u 62u 100% 10u "Re-downloadable. Your library and projects stay."
      Pop $ReframeUnScratch

      ${NSD_CreateCheckbox} 0 76u 100% 11u \
        "Also delete EVERYTHING, including my library and settings (frees $ReframeUnUserSize)"
      Pop $ReframeUnCheckUserData
      ${NSD_CreateLabel} 12u 88u 100% 10u "This cannot be undone."
      Pop $ReframeUnScratch

      ${NSD_OnClick} $ReframeUnCheckUserData un.reframeUnOnUserDataClick
      Call un.reframeUnSyncBoxes

      ${NSD_CreateLabel} 0 104u 100% 20u \
        "Both boxes are off. Leave them off and every byte of your data stays exactly where it is."
      Pop $ReframeUnScratch
    ${Else}
      ${NSD_CreateLabel} 0 28u 100% 40u \
        "No data folder could be identified on this machine, so none is offered for removal and nothing of yours will be deleted. If you set a custom folder with MEDIA_STUDIO_CONFIG_DIR, remove it yourself once the uninstall finishes."
      Pop $ReframeUnScratch
    ${EndIf}

    nsDialogs::Show
  FunctionEnd

  Function un.reframeUnDataPageLeave
    ${If} $ReframeUnDataRootOk == "1"
      ${NSD_GetState} $ReframeUnCheckModels $ReframeUnScratch
      ${If} $ReframeUnScratch == ${BST_CHECKED}
        StrCpy $ReframeUnRemoveModels "1"
      ${Else}
        StrCpy $ReframeUnRemoveModels "0"
      ${EndIf}

      ${NSD_GetState} $ReframeUnCheckUserData $ReframeUnScratch
      ${If} $ReframeUnScratch == ${BST_CHECKED}
        StrCpy $ReframeUnRemoveUserData "1"
        StrCpy $ReframeUnRemoveModels "1" ; the whole root goes; keep the flags coherent
      ${Else}
        StrCpy $ReframeUnRemoveUserData "0"
      ${EndIf}
    ${EndIf}
  FunctionEnd
!macroend

; ---------------------------------------------------------------------------
; The removal. Expanded INSIDE app-builder-lib's `Section "un.Uninstall"`, above the
; RMDir of $INSTDIR (templates/nsis/uninstaller.nsh:156-158, :187) — so this must NEVER
; `Return` or `Abort`, which would skip the real uninstall.
; ---------------------------------------------------------------------------
!macro customUnInstall
  !insertmacro reframeUnVars

  ; KEEP IS ENFORCED THREE INDEPENDENT WAYS, because deleting a user's library on an
  ; ordinary version upgrade would be the worst bug this feature could possibly ship:
  ;   1. the flags are only ever set by the page's LEAVE handler, which cannot run
  ;      without a visible page;
  ;   2. ${Silent} — an in-place auto-update always runs the old uninstaller with /S;
  ;   3. --updated — the installer ALWAYS appends that flag for an in-place upgrade
  ;      (installUtil.nsh:205-206), and it is the same signal app-builder-lib's own
  ;      ${isUpdated} reads. Checked with stock FileFunc rather than ${isUpdated} so
  ;      build/check-installer-nsh.ps1 can still compile this file standalone.
  ; $ReframeUnDataRootOk is "" unless the page ran its safety check, which is a fourth.
  StrCpy $ReframeUnScratch "0"
  ClearErrors
  ${un.GetParameters} $ReframeUnScratch2
  ${un.GetOptions} $ReframeUnScratch2 "--updated" $ReframeUnScratch
  ${IfNot} ${Errors}
    StrCpy $ReframeUnScratch "updated"
  ${Else}
    StrCpy $ReframeUnScratch "0"
  ${EndIf}
  ClearErrors

  ${If} $ReframeUnScratch != "updated"
  ${AndIfNot} ${Silent}
  ${AndIf} $ReframeUnDataRootOk == "1"
    ${If} $ReframeUnRemoveModels == "1"
      DetailPrint "Removing downloaded models and runtimes from $ReframeUnDataRoot"
      RMDir /r "$ReframeUnDataRoot\models"
      RMDir /r "$ReframeUnDataRoot\envs"
      RMDir /r "$ReframeUnDataRoot\tools"
    ${EndIf}
    ${If} $ReframeUnRemoveUserData == "1"
      DetailPrint "Removing the Reframe data folder $ReframeUnDataRoot"
      RMDir /r "$ReframeUnDataRoot"
      RMDir /r "$APPDATA\${REFRAME_USER_DATA_DIRNAME}"
    ${EndIf}
  ${EndIf}
!macroend
