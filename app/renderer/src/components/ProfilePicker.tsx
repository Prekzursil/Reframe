// ProfilePicker.tsx — the FIRST-EVER-run install PROFILE picker (WU-1c).
//
// Shown INSIDE the full-screen FirstRunSetup gate BEFORE any download starts, on a
// first-ever launch only (a silent WU-S2 re-bootstrap reuses the persisted profile
// and never sees this). The user picks Minimum / Default / Full / Custom — each
// with a one-line WHAT + WHY + approx first-run download size — and the supervisor
// routes the choice into bootstrap.py's `--assets`. The size + asset content come
// from the SINGLE-SOURCE-OF-TRUTH map (installProfiles.ts), which the Electron
// supervisor also uses to build the argv, so the number shown here can never drift
// from what actually installs.
//
// The CORE FLOOR (subject tracking) is in every option including Minimum — the map
// guarantees it — so no choice can leave the app silently centre-cropping.
import React, { useCallback, useState } from 'react';

import {
  INSTALL_BUNDLES,
  INSTALL_PROFILES,
  assetsSizeMb,
  formatSize,
  profileSizeLabel,
  type BundleId,
  type InstallProfileId,
} from '../../../main/installProfiles';
import './profilePicker.css';

// The pre-selected profile: the one flagged `recommended` (Default).
// installProfiles.test.ts pins Default as the sole recommended profile, so this
// find is total — the fallback only exists to satisfy the type.
const RECOMMENDED = INSTALL_PROFILES.find((p) => p.recommended);
/* v8 ignore next -- a recommended profile is guaranteed (pinned by installProfiles.test.ts) */
export const DEFAULT_PROFILE_ID: InstallProfileId = RECOMMENDED ? RECOMMENDED.id : 'default';

export interface ProfilePickerProps {
  /** Commit the choice: the profile and (for Custom) the selected bundle ids. */
  onChoose: (profile: InstallProfileId, bundles: BundleId[]) => void;
}

/**
 * The install-profile picker. Local state only — it surfaces the choice via
 * `onChoose`; the supervisor owns persistence + the bootstrap kickoff. A radio
 * group selects the profile; picking Custom reveals the optional feature bundles.
 */
export function ProfilePicker({ onChoose }: ProfilePickerProps): React.ReactElement {
  const [selected, setSelected] = useState<InstallProfileId>(DEFAULT_PROFILE_ID);
  const [bundles, setBundles] = useState<ReadonlySet<BundleId>>(() => new Set<BundleId>());

  const toggleBundle = useCallback((id: BundleId) => {
    setBundles((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  // For Custom the chosen bundles drive the size + the committed value; every other
  // profile is fully determined by its id (bundles are ignored downstream).
  const chosenBundles: BundleId[] = selected === 'custom' ? [...bundles] : [];
  const confirm = useCallback(() => {
    onChoose(selected, selected === 'custom' ? [...bundles] : []);
  }, [onChoose, selected, bundles]);

  return (
    <div className="profile-picker">
      <p className="profile-picker__lead">
        Pick how much to set up now. You can always add the rest later — features download the first
        time you use them.
      </p>
      <fieldset className="profile-picker__options">
        <legend className="profile-picker__legend">Install profile</legend>
        {INSTALL_PROFILES.map((profile) => {
          const isSelected = selected === profile.id;
          const size = profileSizeLabel(profile.id, profile.id === 'custom' ? chosenBundles : []);
          return (
            <label
              key={profile.id}
              className={`profile-picker__option${isSelected ? ' is-selected' : ''}`}
              data-profile={profile.id}
            >
              <input
                type="radio"
                name="install-profile"
                className="profile-picker__radio"
                value={profile.id}
                checked={isSelected}
                onChange={() => setSelected(profile.id)}
              />
              <span className="profile-picker__head">
                <span className="profile-picker__name">
                  {profile.label}
                  {profile.recommended ? (
                    <span className="profile-picker__badge">Recommended</span>
                  ) : null}
                </span>
                <span className="profile-picker__size" data-testid={`size-${profile.id}`}>
                  {size}
                </span>
              </span>
              <span className="profile-picker__what">{profile.what}</span>
              <span className="profile-picker__why">{profile.why}</span>
            </label>
          );
        })}
      </fieldset>

      {selected === 'custom' ? (
        <fieldset className="profile-picker__bundles">
          <legend className="profile-picker__legend">Feature packs</legend>
          {INSTALL_BUNDLES.map((bundle) => (
            <label key={bundle.id} className="profile-picker__bundle" data-bundle={bundle.id}>
              <input
                type="checkbox"
                className="profile-picker__check"
                checked={bundles.has(bundle.id)}
                onChange={() => toggleBundle(bundle.id)}
              />
              <span className="profile-picker__bundle-head">
                <span className="profile-picker__bundle-name">{bundle.label}</span>
                <span className="profile-picker__bundle-size">
                  {formatSize(assetsSizeMb(bundle.assets))}
                </span>
              </span>
              <span className="profile-picker__bundle-what">{bundle.what}</span>
            </label>
          ))}
        </fieldset>
      ) : null}

      <button
        type="button"
        className="profile-picker__confirm"
        data-action="confirm-profile"
        onClick={confirm}
      >
        Install {profileSizeLabel(selected, chosenBundles)}
      </button>
    </div>
  );
}

export default ProfilePicker;
